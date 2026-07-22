"""CNC Audio — FastAPI backend server."""
import json
import math
import os
import re
import shutil
import stat
import threading
import uuid
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Literal, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jsonschema import Draft7Validator
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.api import APP_VERSION

from packages.engine import (
    Asset,
    ClipDuration,
    CrossfadeParams,
    ExportSettings,
    GainParams,
    Parameters,
    RepetitionParams,
    SelectionParams,
    SilenceEvent,
    SilenceParams,
    Timeline,
    check_feasibility,
    generate_timeline,
    hash_file,
    load_project,
    new_project,
    save_project,
)
from packages.renderer.importer import convert_to_standard_wav, probe_duration
from packages.renderer.renderer import render_timeline
from packages.engine.project import (
    _dump_asset,
    _dump_event,
    _dump_parameters,
    _load_asset,
    _load_parameters,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="CNC Audio", version=APP_VERSION)

PROJECTS_DIR = Path("projects")
PROJECTS_DIR.mkdir(exist_ok=True)

STATIC_DIR = Path("packages/api/static")
STATIC_DIR.mkdir(parents=True, exist_ok=True)

SCHEMA_PATH = Path("schemas/project.schema.json")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = int(os.environ.get("CNC_AUDIO_MAX_UPLOAD_BYTES", 2 * 1024**3))
MAX_BUNDLE_BYTES = int(os.environ.get("CNC_AUDIO_MAX_BUNDLE_BYTES", 8 * 1024**3))
MAX_BUNDLE_EXPANDED_BYTES = int(
    os.environ.get("CNC_AUDIO_MAX_BUNDLE_EXPANDED_BYTES", 16 * 1024**3)
)
MAX_BUNDLE_MEMBERS = int(os.environ.get("CNC_AUDIO_MAX_BUNDLE_MEMBERS", 5000))
MAX_PROJECT_ASSETS = int(os.environ.get("CNC_AUDIO_MAX_PROJECT_ASSETS", 500))
MAX_PROJECT_DURATION_SECONDS = float(
    os.environ.get("CNC_AUDIO_MAX_DURATION_SECONDS", 3600)
)
MAX_TIMELINE_EVENTS = int(os.environ.get("CNC_AUDIO_MAX_TIMELINE_EVENTS", 100000))

# A single process-wide transaction lock per project prevents stale snapshots
# from overwriting newer project state. Project JSON writes are also atomic.
_project_locks: Dict[str, threading.RLock] = {}
_project_locks_guard = threading.Lock()


def _validate_identifier(value: str, kind: str) -> str:
    if not SAFE_ID_RE.fullmatch(value or ""):
        raise HTTPException(status_code=422, detail=f"Invalid {kind} identifier.")
    return value


def _get_lock(project_id: str) -> threading.RLock:
    project_id = _validate_identifier(project_id, "project")
    with _project_locks_guard:
        return _project_locks.setdefault(project_id, threading.RLock())


def _project_dir(project_id: str) -> Path:
    project_id = _validate_identifier(project_id, "project")
    project_root = PROJECTS_DIR.resolve()
    project_dir = (project_root / project_id).resolve()
    try:
        project_dir.relative_to(project_root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid project path.") from exc
    return project_dir


def _cnc_path(project_id: str) -> Path:
    return _project_dir(project_id) / "project.cnc"


def _load(project_id: str):
    path = _cnc_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
    return load_project(str(path))


def _save(project_id: str, project):
    _ensure_layered_project_state(project)
    save_project(project, str(_cnc_path(project_id)))


def _project_to_dict(project, project_id: Optional[str] = None) -> dict:
    """Serialize a Project to a JSON-safe dict for API responses."""
    _ensure_layered_project_state(project)
    song_assets = _get_song_assets(project)
    sound_assets = _get_sound_assets(project)
    song_parameters = _get_song_parameters(project)
    sound_parameters = _get_sound_parameters(project)
    render_settings = _get_render_settings(project)
    d = {
        "version": project.version,
        "project": project.project,
        "assets": [_dump_asset(a) for a in song_assets],  # legacy alias (songs)
        "song_assets": [_dump_asset(a) for a in song_assets],
        "sound_assets": [_dump_asset(a) for a in sound_assets],
        "parameters": _dump_parameters(song_parameters),  # legacy alias (songs)
        "song_parameters": _dump_parameters(song_parameters),
        "sound_parameters": _dump_parameters(sound_parameters),
        "render_settings": render_settings,
        "seed": project.seed,
        "export": {
            "format": project.export.format,
            "sample_rate": project.export.sample_rate,
            "bit_depth": project.export.bit_depth,
            "normalize_output": project.export.normalize_output,
            "target_output_lufs": project.export.target_output_lufs,
            "true_peak_limit_dbtp": project.export.true_peak_limit_dbtp,
        },
        "download_filename": _project_download_filename(project),
    }
    if project.timeline:
        d["timeline"] = {
            "total_duration_seconds": project.timeline.total_duration_seconds,
            "events": _dump_timeline_events_with_layers(project),
        }
    if project_id is not None:
        d["has_render"] = (_project_dir(project_id) / "renders" / "latest.wav").exists()
    return d


def _safe_project_filename(project_name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "-", project_name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "Untitled Project"
    return cleaned


def _download_output_path(project_id: str, project) -> Path:
    del project  # Download names are Content-Disposition metadata, not storage paths.
    return _project_dir(project_id) / "renders" / "latest.wav"


def _ensure_project_dirs(project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "assets").mkdir(exist_ok=True)
    (project_dir / "renders").mkdir(exist_ok=True)
    (project_dir / "downloads").mkdir(exist_ok=True)


def _export_bundle_path(project_id: str, project) -> Path:
    export_dir = _project_dir(project_id) / "exports"
    export_dir.mkdir(exist_ok=True)
    filename = f"{_safe_project_filename(project.project.get('name', 'Untitled Project'))}.cncaudio.zip"
    return export_dir / filename


def _project_download_filename(project) -> str:
    project_name = project.project.get("name", "Untitled Project")
    return f"{_safe_project_filename(project_name)}.wav"


def _invalidate_render(project_id: str) -> None:
    (_project_dir(project_id) / "renders" / "latest.wav").unlink(missing_ok=True)


def _invalidate_timeline_and_render(project_id: str, project) -> None:
    project.timeline = None
    _invalidate_render(project_id)


def _resolve_asset_source(project_dir: Path, asset_path: str) -> Path:
    if not isinstance(asset_path, str) or not asset_path:
        raise HTTPException(status_code=422, detail="Invalid asset path in project bundle.")
    relative = Path(asset_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(status_code=422, detail="Invalid asset path in project bundle.")
    candidate = (project_dir / relative).resolve()
    assets_root = (project_dir / "assets").resolve()
    try:
        candidate.relative_to(assets_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="Project asset paths must stay inside assets/."
        ) from exc
    return candidate


async def _stream_upload(file: UploadFile, destination: Path, max_bytes: int) -> int:
    total = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail="Uploaded file is too large.")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return total


def _validate_project_schema(project_file: Path) -> None:
    def reject_constant(value: str):
        raise ValueError(f"Invalid non-finite JSON number: {value}")

    try:
        with project_file.open("r", encoding="utf-8") as stream:
            project_data = json.load(stream, parse_constant=reject_constant)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Project file is not valid JSON.") from exc

    errors = sorted(
        Draft7Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))).iter_errors(
            project_data
        ),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "project"
        raise HTTPException(
            status_code=422,
            detail=f"Project file does not match schema at {location}: {first.message}",
        )


def _default_render_settings(project) -> dict:
    target = project.parameters.target_duration_seconds
    return {
        "target_duration_seconds": target,
        "song_gain_db": 0.0,
        "sound_gain_db": 0.0,
        "render_gain_db": 0.0,
        "normalize_output": project.export.normalize_output,
        "master_fade_in_seconds": 0.0,
        "master_fade_out_seconds": 0.0,
    }


def _ensure_layered_project_state(project) -> None:
    meta = project.project
    if "song_assets" not in meta:
        meta["song_assets"] = [_dump_asset(a) for a in project.assets]
    if "sound_assets" not in meta:
        meta["sound_assets"] = []
    if "song_parameters" not in meta:
        meta["song_parameters"] = _dump_parameters(project.parameters)
    if "sound_parameters" not in meta:
        sound_params = replace(project.parameters)
        meta["sound_parameters"] = _dump_parameters(sound_params)
    if "render_settings" not in meta:
        meta["render_settings"] = _default_render_settings(project)

    render = meta["render_settings"]
    render.setdefault("target_duration_seconds", project.parameters.target_duration_seconds)
    render.setdefault("song_gain_db", 0.0)
    render.setdefault("sound_gain_db", 0.0)
    render.setdefault("render_gain_db", 0.0)
    render.setdefault("normalize_output", project.export.normalize_output)
    render.setdefault("master_fade_in_seconds", 0.0)
    render.setdefault("master_fade_out_seconds", 0.0)

    song_params = _load_parameters(meta["song_parameters"])
    sound_params = _load_parameters(meta["sound_parameters"])
    song_params.target_duration_seconds = float(render["target_duration_seconds"])
    sound_params.target_duration_seconds = float(render["target_duration_seconds"])
    meta["song_parameters"] = _dump_parameters(song_params)
    meta["sound_parameters"] = _dump_parameters(sound_params)

    project.assets = [_load_asset(a) for a in meta["song_assets"]]
    project.parameters = song_params
    project.export.normalize_output = bool(render["normalize_output"])


def _get_song_assets(project) -> List[Asset]:
    _ensure_layered_project_state(project)
    return [_load_asset(a) for a in project.project["song_assets"]]


def _set_song_assets(project, assets: List[Asset]) -> None:
    _ensure_layered_project_state(project)
    project.project["song_assets"] = [_dump_asset(a) for a in assets]
    project.assets = list(assets)


def _get_sound_assets(project) -> List[Asset]:
    _ensure_layered_project_state(project)
    return [_load_asset(a) for a in project.project["sound_assets"]]


def _set_sound_assets(project, assets: List[Asset]) -> None:
    _ensure_layered_project_state(project)
    project.project["sound_assets"] = [_dump_asset(a) for a in assets]


def _get_song_parameters(project) -> Parameters:
    _ensure_layered_project_state(project)
    return _load_parameters(project.project["song_parameters"])


def _set_song_parameters(project, params: Parameters) -> None:
    _ensure_layered_project_state(project)
    project.project["song_parameters"] = _dump_parameters(params)
    project.parameters = params


def _get_sound_parameters(project) -> Parameters:
    _ensure_layered_project_state(project)
    return _load_parameters(project.project["sound_parameters"])


def _set_sound_parameters(project, params: Parameters) -> None:
    _ensure_layered_project_state(project)
    project.project["sound_parameters"] = _dump_parameters(params)


def _get_render_settings(project) -> dict:
    _ensure_layered_project_state(project)
    render = dict(project.project["render_settings"])
    render["target_duration_seconds"] = float(render["target_duration_seconds"])
    render["song_gain_db"] = float(render["song_gain_db"])
    render["sound_gain_db"] = float(render["sound_gain_db"])
    render["render_gain_db"] = float(render["render_gain_db"])
    render["normalize_output"] = bool(render["normalize_output"])
    render["master_fade_in_seconds"] = float(render.get("master_fade_in_seconds", 0.0))
    render["master_fade_out_seconds"] = float(render.get("master_fade_out_seconds", 0.0))
    return render


def _set_render_settings(project, render_settings: dict) -> None:
    _ensure_layered_project_state(project)
    project.project["render_settings"] = {
        "target_duration_seconds": float(render_settings["target_duration_seconds"]),
        "song_gain_db": float(render_settings["song_gain_db"]),
        "sound_gain_db": float(render_settings["sound_gain_db"]),
        "render_gain_db": float(render_settings["render_gain_db"]),
        "normalize_output": bool(render_settings["normalize_output"]),
        "master_fade_in_seconds": float(render_settings.get("master_fade_in_seconds", 0.0)),
        "master_fade_out_seconds": float(render_settings.get("master_fade_out_seconds", 0.0)),
    }
    project.export.normalize_output = bool(render_settings["normalize_output"])


def _generation_state(project) -> str:
    """Return a stable snapshot of every input that affects generation/rendering."""
    _ensure_layered_project_state(project)
    return json.dumps(
        {
            "song_assets": [_dump_asset(asset) for asset in _get_song_assets(project)],
            "sound_assets": [_dump_asset(asset) for asset in _get_sound_assets(project)],
            "song_parameters": _dump_parameters(_get_song_parameters(project)),
            "sound_parameters": _dump_parameters(_get_sound_parameters(project)),
            "render_settings": _get_render_settings(project),
            "seed": project.seed,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _dump_timeline_events_with_layers(project) -> list:
    _ensure_layered_project_state(project)
    song_ids = {a.id for a in _get_song_assets(project)}
    events = []
    for event in project.timeline.events:
        dumped = _dump_event(event)
        if dumped["type"] == "clip":
            dumped["layer"] = "songs" if dumped["asset_id"] in song_ids else "sounds"
        else:
            dumped["layer"] = "songs"
        events.append(dumped)
    return events


def _collect_sound_overlay_issues(sound_assets: List[Asset], sound_params: Parameters):
    warnings: List[str] = []
    errors: List[str] = []
    min_dur = sound_params.clip_duration.min_seconds
    max_dur = sound_params.clip_duration.max_seconds
    if min_dur <= 0:
        errors.append(f"clip_duration.min_seconds must be > 0 (got {min_dur}).")
    if max_dur <= 0:
        errors.append(f"clip_duration.max_seconds must be > 0 (got {max_dur}).")
    if min_dur > max_dur:
        errors.append(
            f"clip_duration.min_seconds ({min_dur}s) > clip_duration.max_seconds ({max_dur}s)."
        )
        return warnings, errors

    usable = [a for a in sound_assets if a.duration_seconds >= min_dur]
    unusable = [a for a in sound_assets if a.duration_seconds < min_dur]
    if not usable:
        errors.append(
            f"No sound assets meet the minimum clip duration of {min_dur}s. "
            f"Lower sound Clip Min or import longer sound clips."
        )
        return warnings, errors

    if unusable:
        warnings.append(
            f"{len(unusable)} sound asset(s) are shorter than sound Clip Min ({min_dur}s) "
            f"and will never be selected."
        )
    return warnings, errors


def _merge_adjacent_silence_events(events: List) -> List:
    merged: List = []
    for event in events:
        if (
            event.type == "silence"
            and merged
            and merged[-1].type == "silence"
        ):
            previous = merged[-1]
            prev_start = previous.position_seconds
            prev_end = previous.position_seconds + previous.duration_seconds
            curr_start = event.position_seconds
            curr_end = event.position_seconds + event.duration_seconds
            if curr_start <= prev_end + 0.001:
                merged[-1] = SilenceEvent(
                    type="silence",
                    position_seconds=round(prev_start, 4),
                    duration_seconds=round(max(prev_end, curr_end) - prev_start, 4),
                    locked=previous.locked and event.locked,
                )
                continue
        merged.append(event)
    return merged


def _apply_sound_end_behavior(sound_events: List, song_target: float, behavior: str) -> List:
    if behavior == "extend_last_clip":
        return sound_events
    processed = []
    for event in sound_events:
        duration = event.source_end_seconds - event.source_start_seconds
        end = event.position_seconds + duration
        if event.position_seconds >= song_target:
            continue
        if end <= song_target + 1e-6:
            processed.append(event)
            continue
        kept_duration = song_target - event.position_seconds
        if kept_duration <= 0:
            continue
        fade_out = event.fade_out_seconds
        if behavior == "fade_last":
            fade_out = max(fade_out, round(min(2.0, kept_duration * 0.3), 4))
        else:
            fade_out = 0.0
        processed.append(
            replace(
                event,
                source_end_seconds=round(event.source_start_seconds + kept_duration, 4),
                fade_out_seconds=fade_out,
            )
        )
    return processed


def _safe_extract_bundle(archive: zipfile.ZipFile, destination: Path) -> None:
    base = destination.resolve()
    members = archive.infolist()
    if len(members) > MAX_BUNDLE_MEMBERS:
        raise HTTPException(status_code=413, detail="Project bundle contains too many files.")
    expanded_total = sum(member.file_size for member in members)
    if expanded_total > MAX_BUNDLE_EXPANDED_BYTES:
        raise HTTPException(status_code=413, detail="Expanded project bundle is too large.")

    seen_paths = set()
    for member in members:
        member_path = Path(member.filename)
        normalized_name = member.filename.replace("\\", "/").rstrip("/").casefold()
        if not normalized_name or normalized_name in seen_paths:
            raise HTTPException(status_code=422, detail="Project bundle has duplicate paths.")
        seen_paths.add(normalized_name)
        unix_mode = member.external_attr >> 16
        if stat.S_ISLNK(unix_mode) or member.flag_bits & 0x1:
            raise HTTPException(status_code=422, detail="Project bundle contains an unsafe file.")
        if member_path.is_absolute() or member_path.drive or ".." in member_path.parts:
            raise HTTPException(status_code=422, detail="Invalid project bundle path.")
        try:
            target = (base / member_path).resolve()
            target.relative_to(base)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid project bundle path.") from exc

    extracted_total = 0
    for member in members:
        target = (base / Path(member.filename)).resolve()
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member, "r") as source, target.open("wb") as output:
            while chunk := source.read(UPLOAD_CHUNK_BYTES):
                extracted_total += len(chunk)
                if extracted_total > MAX_BUNDLE_EXPANDED_BYTES:
                    raise HTTPException(status_code=413, detail="Expanded project bundle is too large.")
                output.write(chunk)


# ---------------------------------------------------------------------------
# Project endpoints
# ---------------------------------------------------------------------------

class StrictRequestModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class CreateProjectRequest(StrictRequestModel):
    name: str = Field(default="Untitled Project", max_length=200)


@app.get("/api/version")
def get_version():
    return {"version": APP_VERSION}


@app.post("/api/projects")
def create_project(body: CreateProjectRequest):
    project_id = str(uuid.uuid4())
    project_dir = _project_dir(project_id)
    _ensure_project_dirs(project_dir)

    project = new_project(body.name.strip() or "Untitled Project")
    _save(project_id, project)
    return {"id": project_id, **_project_to_dict(project, project_id)}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    with _get_lock(project_id):
        project = _load(project_id)
        return {"id": project_id, **_project_to_dict(project, project_id)}


class ProjectNameRequest(StrictRequestModel):
    name: str = Field(max_length=200)


@app.put("/api/projects/{project_id}/name")
def update_project_name(project_id: str, body: ProjectNameRequest):
    with _get_lock(project_id):
        project = _load(project_id)
        name = body.name.strip() or "Untitled Project"
        project.project["name"] = name
        _save(project_id, project)
        return {"name": name, "download_filename": _project_download_filename(project)}


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str):
    with _get_lock(project_id):
        project = _load(project_id)
        project_dir = _project_dir(project_id)
        bundle_path = _export_bundle_path(project_id, project)

        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            project_file = _cnc_path(project_id)
            archive.write(project_file, arcname="project.cnc")
            assets = _get_song_assets(project) + _get_sound_assets(project)
            for asset in assets:
                source_path = _resolve_asset_source(project_dir, asset.path)
                if not source_path.is_file():
                    raise HTTPException(
                        status_code=422,
                        detail=f"Project is missing source media for '{asset.name}'.",
                    )
                archive.write(
                    source_path,
                    arcname=source_path.relative_to(project_dir).as_posix(),
                )

    return FileResponse(
        str(bundle_path),
        media_type="application/zip",
        filename=bundle_path.name,
    )


@app.post("/api/projects/import")
async def import_project_bundle(file: UploadFile = File(...)):
    project_id = str(uuid.uuid4())
    project_dir = _project_dir(project_id)
    _ensure_project_dirs(project_dir)
    bundle_path = project_dir / "__import_bundle.zip"

    try:
        await _stream_upload(file, bundle_path, MAX_BUNDLE_BYTES)

        try:
            with zipfile.ZipFile(bundle_path, "r") as archive:
                _safe_extract_bundle(archive, project_dir)
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=422, detail="Uploaded file is not a valid project bundle.") from exc
        finally:
            bundle_path.unlink(missing_ok=True)

        project_file = _cnc_path(project_id)
        if not project_file.exists():
            raise HTTPException(status_code=422, detail="Project bundle is missing project.cnc.")

        _validate_project_schema(project_file)
        project = load_project(str(project_file))
        _ensure_layered_project_state(project)
        song_assets = _get_song_assets(project)
        sound_assets = _get_sound_assets(project)
        all_assets = song_assets + sound_assets
        if len(all_assets) > MAX_PROJECT_ASSETS:
            raise HTTPException(status_code=413, detail="Project contains too many assets.")
        asset_ids = set()
        for asset in all_assets:
            _validate_identifier(asset.id, "asset")
            if asset.id in asset_ids:
                raise HTTPException(status_code=422, detail="Project contains duplicate asset IDs.")
            asset_ids.add(asset.id)
            source_path = _resolve_asset_source(project_dir, asset.path)
            if not source_path.is_file():
                raise HTTPException(
                    status_code=422,
                    detail=f"Project bundle is missing asset source '{asset.path}'.",
                )
            if hash_file(str(source_path)) != asset.hash:
                raise HTTPException(
                    status_code=422,
                    detail=f"Source media hash does not match for '{asset.name}'.",
                )

            wav_path = project_dir / "assets" / f"{asset.id}.wav"
            try:
                convert_to_standard_wav(str(source_path), str(wav_path))
                actual_duration = probe_duration(str(wav_path))
            except Exception as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Failed to prepare imported asset '{asset.name}'.",
                ) from exc
            if not math.isfinite(actual_duration) or not (0 < actual_duration <= MAX_PROJECT_DURATION_SECONDS):
                raise HTTPException(status_code=422, detail="Imported asset duration is invalid.")
            asset.duration_seconds = round(actual_duration, 4)

        _set_song_assets(project, song_assets)
        _set_sound_assets(project, sound_assets)

        if project.timeline is not None:
            if (
                project.timeline.total_duration_seconds > MAX_PROJECT_DURATION_SECONDS
                or len(project.timeline.events) > MAX_TIMELINE_EVENTS
            ):
                raise HTTPException(status_code=413, detail="Project timeline exceeds release limits.")
            previous_position = -1.0
            asset_by_id = {asset.id: asset for asset in all_assets}
            for event in project.timeline.events:
                if event.position_seconds < previous_position:
                    raise HTTPException(status_code=422, detail="Timeline events are not ordered.")
                previous_position = event.position_seconds
                if event.type == "clip":
                    if event.asset_id not in asset_ids:
                        raise HTTPException(
                            status_code=422, detail="Timeline references an unknown asset."
                        )
                    if (
                        event.source_end_seconds <= event.source_start_seconds
                        or event.source_end_seconds
                        > asset_by_id[event.asset_id].duration_seconds + 0.001
                    ):
                        raise HTTPException(
                            status_code=422, detail="Timeline contains an invalid source region."
                        )
                    event_end = event.position_seconds + (
                        event.source_end_seconds - event.source_start_seconds
                    )
                else:
                    event_end = event.position_seconds + event.duration_seconds
                if event_end > project.timeline.total_duration_seconds + 0.001:
                    raise HTTPException(
                        status_code=422, detail="Timeline event exceeds the timeline duration."
                    )

        _invalidate_render(project_id)
        _save(project_id, project)
        return {"id": project_id, **_project_to_dict(project, project_id)}
    except HTTPException:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise
    except (OSError, ValueError) as exc:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail="Project import failed validation.") from exc
    except Exception as exc:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Project import failed.") from exc


# ---------------------------------------------------------------------------
# Asset import
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/assets")
async def import_asset(
    project_id: str,
    category: Literal["songs", "sounds"] = "songs",
    file: UploadFile = File(...),
):
    project_dir = _project_dir(project_id)
    assets_dir = project_dir / "assets"
    with _get_lock(project_id):
        _load(project_id)

    # Save the uploaded file to a temp location (outside the lock — I/O only)
    original_name = Path(file.filename or "media")
    ext = original_name.suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", ext):
        ext = ".media"
    asset_id = str(uuid.uuid4())
    original_path = assets_dir / f"{asset_id}_original{ext}"

    await _stream_upload(file, original_path, MAX_UPLOAD_BYTES)

    # Convert to standard WAV for rendering (CPU work, outside the lock)
    wav_path = assets_dir / f"{asset_id}.wav"
    try:
        convert_to_standard_wav(str(original_path), str(wav_path))
        duration = probe_duration(str(wav_path))
    except Exception as e:
        original_path.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Failed to process audio: {e}")
    if not math.isfinite(duration) or not (0 < duration <= MAX_PROJECT_DURATION_SECONDS):
        original_path.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Imported asset duration is invalid.")

    file_hash = hash_file(str(original_path))

    asset = Asset(
        id=asset_id,
        name=(re.sub(r"[\x00-\x1f\x7f]", "", original_name.stem).strip() or "Untitled Clip")[:200],
        path=f"assets/{asset_id}_original{ext}",
        hash=file_hash,
        duration_seconds=round(duration, 4),
        format=ext.lstrip("."),
        weight=1.0,
    )

    # Serialise the project-file write under a per-project lock
    with _get_lock(project_id):
        project = _load(project_id)
        _ensure_layered_project_state(project)
        if len(_get_song_assets(project)) + len(_get_sound_assets(project)) >= MAX_PROJECT_ASSETS:
            original_path.unlink(missing_ok=True)
            wav_path.unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail="Project contains too many assets.")
        if category == "songs":
            song_assets = _get_song_assets(project)
            song_assets.append(asset)
            _set_song_assets(project, song_assets)
        else:
            sound_assets = _get_sound_assets(project)
            sound_assets.append(asset)
            _set_sound_assets(project, sound_assets)
        _invalidate_timeline_and_render(project_id, project)
        _save(project_id, project)

    return {"category": category, **_dump_asset(asset)}


@app.delete("/api/projects/{project_id}/assets/{asset_id}")
async def delete_asset(project_id: str, asset_id: str):
    _validate_identifier(asset_id, "asset")
    with _get_lock(project_id):
        project = _load(project_id)
        _ensure_layered_project_state(project)
        # Asset may already be gone if a previous delete raced — that's fine
        _set_song_assets(project, [a for a in _get_song_assets(project) if a.id != asset_id])
        _set_sound_assets(project, [a for a in _get_sound_assets(project) if a.id != asset_id])

        # Remove files — use missing_ok so repeated calls don't crash
        assets_dir = _project_dir(project_id) / "assets"
        if assets_dir.exists():
            for f in assets_dir.glob(f"{asset_id}*"):
                f.unlink(missing_ok=True)

        _invalidate_timeline_and_render(project_id, project)
        _save(project_id, project)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

class LayerParametersRequest(StrictRequestModel):
    clip_duration_min: float = Field(gt=0, le=MAX_PROJECT_DURATION_SECONDS)
    clip_duration_max: float = Field(gt=0, le=MAX_PROJECT_DURATION_SECONDS)
    max_per_clip: Optional[int] = Field(default=None, ge=1, le=100000)
    min_gap_clips: int = Field(default=0, ge=0, le=1000)
    allow_consecutive: bool = False
    crossfade_enabled: bool = True
    crossfade_min: float = Field(default=0.1, ge=0, le=60)
    crossfade_max: float = Field(default=2.0, ge=0, le=60)
    crossfade_probability: float = Field(default=0.8, ge=0, le=1)
    silence_enabled: bool = False
    silence_probability: float = Field(default=0.3, ge=0, le=1)
    silence_min: float = Field(default=0.2, ge=0, le=MAX_PROJECT_DURATION_SECONDS)
    silence_max: float = Field(default=2.0, ge=0, le=MAX_PROJECT_DURATION_SECONDS)
    normalize: bool = False
    target_lufs: float = Field(default=-18.0, ge=-70, le=0)
    max_gain_db: float = Field(default=12.0, ge=0, le=60)
    random_variation_db: float = Field(default=0.0, ge=0, le=60)
    distribution: Literal["uniform", "weighted", "sequential"] = "uniform"
    chaos: float = Field(default=1.0, ge=0, le=1)
    allow_repeats: bool = True
    no_repeat_sections: bool = True
    repeat_decay: float = Field(default=0.0, ge=0, le=1)
    duration_rule: Literal[
        "trim_last", "fade_last", "pad_silence", "fill_random_clip", "extend_last_clip"
    ] = "fade_last"
    asset_weights: Optional[Dict[str, float]] = None

    @field_validator("asset_weights")
    @classmethod
    def validate_asset_weights(cls, weights):
        if weights is None:
            return None
        for asset_id, weight in weights.items():
            if not SAFE_ID_RE.fullmatch(asset_id) or not math.isfinite(weight) or not (0.1 <= weight <= 5.0):
                raise ValueError("asset_weights must map valid asset IDs to values from 0.1 to 5.0")
        return weights

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.clip_duration_min > self.clip_duration_max:
            raise ValueError("clip_duration_min must not exceed clip_duration_max")
        if self.crossfade_min > self.crossfade_max:
            raise ValueError("crossfade_min must not exceed crossfade_max")
        if self.silence_min > self.silence_max:
            raise ValueError("silence_min must not exceed silence_max")
        return self


class RenderSettingsRequest(StrictRequestModel):
    target_duration_seconds: float = Field(gt=0, le=MAX_PROJECT_DURATION_SECONDS)
    song_gain_db: float = Field(default=0.0, ge=-60, le=24)
    sound_gain_db: float = Field(default=0.0, ge=-60, le=24)
    render_gain_db: float = Field(default=0.0, ge=-60, le=24)
    normalize_output: bool = True
    master_fade_in_seconds: float = Field(default=0.0, ge=0, le=600)
    master_fade_out_seconds: float = Field(default=0.0, ge=0, le=600)


class ParametersRequest(StrictRequestModel):
    target_duration_seconds: Optional[float] = Field(
        default=None, gt=0, le=MAX_PROJECT_DURATION_SECONDS
    )
    clip_duration_min: Optional[float] = Field(
        default=None, gt=0, le=MAX_PROJECT_DURATION_SECONDS
    )
    clip_duration_max: Optional[float] = Field(
        default=None, gt=0, le=MAX_PROJECT_DURATION_SECONDS
    )
    max_per_clip: Optional[int] = Field(default=None, ge=1, le=100000)
    min_gap_clips: int = Field(default=0, ge=0, le=1000)
    allow_consecutive: bool = False
    crossfade_enabled: bool = True
    crossfade_min: float = Field(default=0.1, ge=0, le=60)
    crossfade_max: float = Field(default=2.0, ge=0, le=60)
    crossfade_probability: float = Field(default=0.8, ge=0, le=1)
    silence_enabled: bool = False
    silence_probability: float = Field(default=0.3, ge=0, le=1)
    silence_min: float = Field(default=0.2, ge=0, le=MAX_PROJECT_DURATION_SECONDS)
    silence_max: float = Field(default=2.0, ge=0, le=MAX_PROJECT_DURATION_SECONDS)
    normalize: bool = False
    target_lufs: float = Field(default=-18.0, ge=-70, le=0)
    max_gain_db: float = Field(default=12.0, ge=0, le=60)
    random_variation_db: float = Field(default=0.0, ge=0, le=60)
    distribution: Literal["uniform", "weighted", "sequential"] = "uniform"
    chaos: float = Field(default=1.0, ge=0, le=1)
    allow_repeats: bool = True
    no_repeat_sections: bool = True
    repeat_decay: float = Field(default=0.0, ge=0, le=1)
    duration_rule: Literal[
        "trim_last", "fade_last", "pad_silence", "fill_random_clip", "extend_last_clip"
    ] = "fade_last"
    asset_weights: Optional[Dict[str, float]] = None
    song_parameters: Optional[LayerParametersRequest] = None
    sound_parameters: Optional[LayerParametersRequest] = None
    render_settings: Optional[RenderSettingsRequest] = None

    @field_validator("asset_weights")
    @classmethod
    def validate_legacy_asset_weights(cls, weights):
        return LayerParametersRequest.validate_asset_weights(weights)

    @model_validator(mode="after")
    def validate_legacy_bounds(self):
        if (
            self.clip_duration_min is not None
            and self.clip_duration_max is not None
            and self.clip_duration_min > self.clip_duration_max
        ):
            raise ValueError("clip_duration_min must not exceed clip_duration_max")
        if self.crossfade_min > self.crossfade_max:
            raise ValueError("crossfade_min must not exceed crossfade_max")
        if self.silence_min > self.silence_max:
            raise ValueError("silence_min must not exceed silence_max")
        return self


def _build_parameters(layer: LayerParametersRequest, target_duration_seconds: float) -> Parameters:
    return Parameters(
        target_duration_seconds=target_duration_seconds,
        clip_duration=ClipDuration(
            min_seconds=layer.clip_duration_min,
            max_seconds=layer.clip_duration_max,
        ),
        repetition=RepetitionParams(
            # allow_repeats=True with max_per_clip<=1 is contradictory; treat as unlimited.
            max_per_clip=(
                1 if not layer.allow_repeats
                else (layer.max_per_clip if (layer.max_per_clip or 0) > 1 else None)
            ),
            min_gap_clips=layer.min_gap_clips,
            allow_consecutive=layer.allow_consecutive,
            no_repeat_sections=layer.no_repeat_sections,
            repeat_decay=layer.repeat_decay,
        ),
        crossfade=CrossfadeParams(
            enabled=layer.crossfade_enabled,
            min_seconds=layer.crossfade_min,
            max_seconds=layer.crossfade_max,
            probability=layer.crossfade_probability,
        ),
        silence=SilenceParams(
            enabled=layer.silence_enabled,
            probability=layer.silence_probability,
            min_seconds=layer.silence_min,
            max_seconds=layer.silence_max,
        ),
        gain=GainParams(
            normalize=layer.normalize,
            target_lufs=layer.target_lufs,
            max_gain_db=layer.max_gain_db,
            random_variation_db=layer.random_variation_db,
        ),
        selection=SelectionParams(
            distribution=layer.distribution,
            chaos=layer.chaos,
        ),
        duration_rule=layer.duration_rule,
    )


def _collect_layered_feasibility(project):
    _ensure_layered_project_state(project)
    render = _get_render_settings(project)
    target = float(render["target_duration_seconds"])

    song_assets = _get_song_assets(project)
    sound_assets = _get_sound_assets(project)
    song_params = _get_song_parameters(project)
    sound_params = _get_sound_parameters(project)
    song_params.target_duration_seconds = target
    sound_params.target_duration_seconds = (
        target + sound_params.clip_duration.max_seconds
        if sound_params.duration_rule == "extend_last_clip"
        else target
    )

    song_result = check_feasibility(song_assets, song_params)
    if sound_assets:
        sound_warnings, sound_errors = _collect_sound_overlay_issues(sound_assets, sound_params)
    else:
        sound_warnings = []
        sound_errors = []

    warnings = [f"Songs: {w}" for w in song_result.warnings]
    errors = [f"Songs: {e}" for e in song_result.errors]

    warnings.extend(f"Sounds: {w}" for w in sound_warnings)
    errors.extend(f"Sounds: {e}" for e in sound_errors)

    feasible = song_result.feasible and not sound_errors
    return {
        "feasible": feasible,
        "warnings": warnings,
        "errors": errors,
        "target_duration_seconds": target,
        "song_assets": song_assets,
        "sound_assets": sound_assets,
        "song_params": song_params,
        "sound_params": sound_params,
    }


@app.put("/api/projects/{project_id}/parameters")
def update_parameters(project_id: str, body: ParametersRequest):
    with _get_lock(project_id):
        return _update_parameters(project_id, body)


def _update_parameters(project_id: str, body: ParametersRequest):
    project = _load(project_id)
    _ensure_layered_project_state(project)
    previous_state = _generation_state(project)

    has_layered_payload = (
        body.song_parameters is not None
        or body.sound_parameters is not None
        or body.render_settings is not None
    )
    render = _get_render_settings(project)

    if has_layered_payload:
        if body.render_settings is not None:
            render = (
                body.render_settings.model_dump()
                if hasattr(body.render_settings, "model_dump")
                else body.render_settings.dict()
            )
        _set_render_settings(project, render)
        target = float(render["target_duration_seconds"])

        if body.song_parameters is not None:
            song_params = _build_parameters(body.song_parameters, target)
            _set_song_parameters(project, song_params)
        else:
            song_params = _get_song_parameters(project)
            song_params.target_duration_seconds = target
            _set_song_parameters(project, song_params)

        if body.sound_parameters is not None:
            sound_params = _build_parameters(body.sound_parameters, target)
            _set_sound_parameters(project, sound_params)
        else:
            sound_params = _get_sound_parameters(project)
            sound_params.target_duration_seconds = target
            _set_sound_parameters(project, sound_params)

        if body.song_parameters and body.song_parameters.asset_weights:
            song_assets = _get_song_assets(project)
            for asset in song_assets:
                if asset.id in body.song_parameters.asset_weights:
                    asset.weight = body.song_parameters.asset_weights[asset.id]
            _set_song_assets(project, song_assets)
        if body.sound_parameters and body.sound_parameters.asset_weights:
            sound_assets = _get_sound_assets(project)
            for asset in sound_assets:
                if asset.id in body.sound_parameters.asset_weights:
                    asset.weight = body.sound_parameters.asset_weights[asset.id]
            _set_sound_assets(project, sound_assets)
    else:
        if body.clip_duration_min is None or body.clip_duration_max is None:
            raise HTTPException(
                status_code=422,
                detail="Legacy parameter updates require clip_duration_min and clip_duration_max.",
            )
        target = (
            body.target_duration_seconds
            if body.target_duration_seconds is not None
            else _get_render_settings(project)["target_duration_seconds"]
        )
        render["target_duration_seconds"] = float(target)
        _set_render_settings(project, render)

        if body.asset_weights:
            song_assets = _get_song_assets(project)
            for asset in song_assets:
                if asset.id in body.asset_weights:
                    asset.weight = body.asset_weights[asset.id]
            _set_song_assets(project, song_assets)

        legacy_layer = LayerParametersRequest(
            clip_duration_min=body.clip_duration_min,
            clip_duration_max=body.clip_duration_max,
            max_per_clip=body.max_per_clip,
            min_gap_clips=body.min_gap_clips,
            allow_consecutive=body.allow_consecutive,
            crossfade_enabled=body.crossfade_enabled,
            crossfade_min=body.crossfade_min,
            crossfade_max=body.crossfade_max,
            crossfade_probability=body.crossfade_probability,
            silence_enabled=body.silence_enabled,
            silence_probability=body.silence_probability,
            silence_min=body.silence_min,
            silence_max=body.silence_max,
            normalize=body.normalize,
            target_lufs=body.target_lufs,
            max_gain_db=body.max_gain_db,
            random_variation_db=body.random_variation_db,
            distribution=body.distribution,
            chaos=body.chaos,
            allow_repeats=body.allow_repeats,
            no_repeat_sections=body.no_repeat_sections,
            repeat_decay=body.repeat_decay,
            duration_rule=body.duration_rule,
            asset_weights=body.asset_weights,
        )
        song_params = _build_parameters(legacy_layer, float(target))
        _set_song_parameters(project, song_params)
    if _generation_state(project) != previous_state:
        _invalidate_timeline_and_render(project_id, project)
    _save(project_id, project)
    return _project_to_dict(project, project_id)


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

class SeedRequest(StrictRequestModel):
    seed: str = Field(min_length=1, max_length=500)


@app.put("/api/projects/{project_id}/seed")
def update_seed(project_id: str, body: SeedRequest):
    with _get_lock(project_id):
        project = _load(project_id)
        changed = project.seed != body.seed
        project.seed = body.seed
        if changed:
            _invalidate_timeline_and_render(project_id, project)
        _save(project_id, project)
        return {"seed": project.seed}


# ---------------------------------------------------------------------------
# Feasibility
# ---------------------------------------------------------------------------

@app.get("/api/projects/{project_id}/feasibility")
def get_feasibility(project_id: str):
    with _get_lock(project_id):
        project = _load(project_id)
        result = _collect_layered_feasibility(project)
        return {
            "feasible": result["feasible"],
            "warnings": result["warnings"],
            "errors": result["errors"],
        }


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/generate")
def generate(project_id: str):
    with _get_lock(project_id):
        return _generate(project_id)


def _generate(project_id: str):
    project = _load(project_id)
    feasibility = _collect_layered_feasibility(project)
    if not feasibility["feasible"]:
        raise HTTPException(
            status_code=422,
            detail={"errors": feasibility["errors"], "warnings": feasibility["warnings"]},
        )

    song_timeline = generate_timeline(
        feasibility["song_assets"], feasibility["song_params"], f"{project.seed}|songs"
    )
    sound_timeline = None
    if feasibility["sound_assets"]:
        sound_timeline = generate_timeline(
            feasibility["sound_assets"], feasibility["sound_params"], f"{project.seed}|sounds"
        )

    events = list(song_timeline.events)
    if sound_timeline is not None:
        sound_clips = [e for e in sound_timeline.events if e.type == "clip"]
        sound_clips = _apply_sound_end_behavior(
            sound_clips,
            song_timeline.total_duration_seconds,
            feasibility["sound_params"].duration_rule,
        )
        events.extend(sound_clips)
    events.sort(key=lambda e: e.position_seconds)
    events = _merge_adjacent_silence_events(events)

    total_duration = song_timeline.total_duration_seconds
    if sound_timeline is not None and feasibility["sound_params"].duration_rule == "extend_last_clip":
        if events:
            total_duration = round(max(
                (e.position_seconds + (e.source_end_seconds - e.source_start_seconds))
                if e.type == "clip"
                else (e.position_seconds + e.duration_seconds)
                for e in events
            ), 4)
    project.timeline = Timeline(events=events, total_duration_seconds=total_duration)
    _invalidate_render(project_id)
    _save(project_id, project)
    song_clip_count = sum(1 for e in song_timeline.events if e.type == "clip")
    sound_clip_count = (
        sum(1 for e in sound_timeline.events if e.type == "clip")
        if sound_timeline is not None
        else 0
    )

    warnings = list(feasibility["warnings"])
    # Warn when the song timeline fell short of the target (source material ran out).
    # total_duration_seconds is padded to the target with silence, so we must
    # compute the actual end of the last clip event instead.
    song_target = feasibility["song_params"].target_duration_seconds
    song_clip_events = [e for e in song_timeline.events if e.type == "clip"]
    if song_clip_events:
        last_clip_end = max(
            e.position_seconds + (e.source_end_seconds - e.source_start_seconds)
            for e in song_clip_events
        )
    else:
        last_clip_end = 0.0
    shortfall = song_target - last_clip_end
    min_clip = feasibility["song_params"].clip_duration.min_seconds
    if shortfall > min_clip:
        pct = round(shortfall / song_target * 100)
        warnings.append(
            f"Song timeline is {round(shortfall)}s shorter than the {round(song_target)}s target "
            f"({pct}% unfilled). Source material may have run out. "
            "Try disabling 'No Repeat Sections', enabling 'Allow Repeats', or adding more / longer songs."
        )

    return {
        "total_duration_seconds": project.timeline.total_duration_seconds,
        "event_count": len(project.timeline.events),
        "clip_count": sum(1 for e in project.timeline.events if e.type == "clip"),
        "song_clip_count": song_clip_count,
        "sound_clip_count": sound_clip_count,
        "events": _dump_timeline_events_with_layers(project),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/render")
def render(project_id: str):
    with _get_lock(project_id):
        return _render(project_id)


def _render(project_id: str):
    project = _load(project_id)
    _ensure_layered_project_state(project)

    if not project.timeline:
        raise HTTPException(status_code=422, detail="Generate a timeline first.")

    # Build asset_id -> wav path map
    project_dir = _project_dir(project_id)
    song_assets = _get_song_assets(project)
    sound_assets = _get_sound_assets(project)
    asset_wav_map = {
        a.id: str(project_dir / "assets" / f"{a.id}.wav")
        for a in (song_assets + sound_assets)
    }
    song_ids = {a.id for a in song_assets}
    render_settings = _get_render_settings(project)
    layer_offsets = {
        "songs": float(render_settings["song_gain_db"]) + float(render_settings["render_gain_db"]),
        "sounds": float(render_settings["sound_gain_db"]) + float(render_settings["render_gain_db"]),
    }

    adjusted_events = []
    for event in project.timeline.events:
        if event.type != "clip":
            adjusted_events.append(event)
            continue
        layer = "songs" if event.asset_id in song_ids else "sounds"
        adjusted_events.append(replace(event, gain_db=event.gain_db + layer_offsets[layer]))
    render_timeline_obj = Timeline(
        events=adjusted_events,
        total_duration_seconds=project.timeline.total_duration_seconds,
    )

    output_path = _download_output_path(project_id, project)
    temp_output_path = output_path.with_name(f".latest-{uuid.uuid4().hex}.tmp.wav")

    try:
        render_timeline(render_timeline_obj, asset_wav_map, str(temp_output_path), project.export,
                        master_fade_in=render_settings.get("master_fade_in_seconds", 0.0),
                        master_fade_out=render_settings.get("master_fade_out_seconds", 0.0))
        os.replace(temp_output_path, output_path)
    except Exception as e:
        temp_output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Render failed: {e}")

    size_mb = os.path.getsize(str(output_path)) / (1024 * 1024)
    filename = _project_download_filename(project)
    return {
        "ok": True,
        "duration_seconds": project.timeline.total_duration_seconds,
        "size_mb": round(size_mb, 2),
        "audio_url": f"/api/projects/{project_id}/audio",
        "download_url": f"/api/projects/{project_id}/download",
        "filename": filename,
    }


@app.get("/api/projects/{project_id}/audio")
def get_audio(project_id: str, request: Request):
    """Serve the rendered WAV with full HTTP Range support so browsers can seek."""
    audio_path = _project_dir(project_id) / "renders" / "latest.wav"
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="No render found. Render the project first.")

    file_size = audio_path.stat().st_size
    media_type = "audio/wav"
    base_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache, no-store",
    }

    range_header = request.headers.get("range")
    if not range_header:
        # No Range header — send the whole file (but still advertise range support)
        return FileResponse(str(audio_path), media_type=media_type, headers=base_headers)

    # Parse "bytes=start-end" (end is optional)
    m = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
    if not m:
        raise HTTPException(status_code=416, detail="Invalid Range header")

    start = int(m.group(1))
    end   = int(m.group(2)) if m.group(2) else file_size - 1
    end   = min(end, file_size - 1)

    if start > end or start >= file_size:
        raise HTTPException(
            status_code=416,
            detail="Range Not Satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_length = end - start + 1

    def _iter_file(path: Path, offset: int, length: int):
        CHUNK = 64 * 1024  # 64 KB
        with open(path, "rb") as f:
            f.seek(offset)
            remaining = length
            while remaining > 0:
                data = f.read(min(CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        _iter_file(audio_path, start, chunk_length),
        status_code=206,
        media_type=media_type,
        headers={
            **base_headers,
            "Content-Range":  f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(chunk_length),
        },
    )


@app.get("/api/projects/{project_id}/download")
def download_audio(project_id: str):
    with _get_lock(project_id):
        project = _load(project_id)
        output_path = _download_output_path(project_id, project)
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="No render found. Render the project first.")
        filename = _project_download_filename(project)
    return FileResponse(str(output_path), media_type="audio/wav", filename=filename)


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
