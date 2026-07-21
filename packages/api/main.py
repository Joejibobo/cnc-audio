"""CNC Audio — FastAPI backend server."""
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from packages.engine import (
    Asset,
    ClipDuration,
    CrossfadeParams,
    ExportSettings,
    GainParams,
    Parameters,
    RepetitionParams,
    SelectionParams,
    SilenceParams,
    check_feasibility,
    generate_timeline,
    hash_file,
    load_project,
    new_project,
    save_project,
)
from packages.renderer.importer import convert_to_standard_wav, probe_duration
from packages.renderer.renderer import render_timeline

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="CNC Audio", version="1.0.0")

PROJECTS_DIR = Path("projects")
PROJECTS_DIR.mkdir(exist_ok=True)

STATIC_DIR = Path("packages/api/static")
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# In-memory project registry: project_id -> project dir
_projects: Dict[str, Path] = {}


def _project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def _cnc_path(project_id: str) -> Path:
    return _project_dir(project_id) / "project.cnc"


def _load(project_id: str):
    path = _cnc_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
    return load_project(str(path))


def _save(project_id: str, project):
    save_project(project, str(_cnc_path(project_id)))


def _project_to_dict(project, project_id: Optional[str] = None) -> dict:
    """Serialize a Project to a JSON-safe dict for API responses."""
    from packages.engine.project import _dump_asset, _dump_parameters, _dump_event
    d = {
        "version": project.version,
        "project": project.project,
        "assets": [_dump_asset(a) for a in project.assets],
        "parameters": _dump_parameters(project.parameters),
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
            "events": [_dump_event(e) for e in project.timeline.events],
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
    download_dir = _project_dir(project_id) / "downloads"
    download_dir.mkdir(exist_ok=True)
    project_name = project.project.get("name", "Untitled Project")
    return download_dir / f"{_safe_project_filename(project_name)}.wav"


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


def _safe_extract_bundle(archive: zipfile.ZipFile, destination: Path) -> None:
    base = destination.resolve()
    for member in archive.infolist():
        member_path = Path(member.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise HTTPException(status_code=422, detail="Invalid project bundle path.")
        try:
            (base / member_path).resolve().relative_to(base)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid project bundle path.") from exc
    archive.extractall(destination)


# ---------------------------------------------------------------------------
# Project endpoints
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    name: str = "Untitled Project"


@app.post("/api/projects")
def create_project(body: CreateProjectRequest):
    project_id = str(uuid.uuid4())
    project_dir = _project_dir(project_id)
    _ensure_project_dirs(project_dir)

    project = new_project(body.name)
    _save(project_id, project)
    return {"id": project_id, **_project_to_dict(project, project_id)}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    project = _load(project_id)
    return {"id": project_id, **_project_to_dict(project, project_id)}


class ProjectNameRequest(BaseModel):
    name: str


@app.put("/api/projects/{project_id}/name")
def update_project_name(project_id: str, body: ProjectNameRequest):
    project = _load(project_id)
    name = body.name.strip() or "Untitled Project"
    project.project["name"] = name
    _save(project_id, project)
    return {"name": name}


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str):
    project = _load(project_id)
    project_dir = _project_dir(project_id)
    bundle_path = _export_bundle_path(project_id, project)

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        project_file = _cnc_path(project_id)
        if project_file.exists():
            archive.write(project_file, arcname="project.cnc")
        for folder_name in ("assets", "renders", "downloads"):
            folder = project_dir / folder_name
            if not folder.exists():
                continue
            for file_path in folder.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, arcname=str(file_path.relative_to(project_dir)))

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
        with bundle_path.open("wb") as f:
            f.write(await file.read())

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

        project = load_project(str(project_file))
        for asset in project.assets:
            source_path = project_dir / asset.path
            if not source_path.exists():
                raise HTTPException(
                    status_code=422,
                    detail=f"Project bundle is missing asset source '{asset.path}'.",
                )

            wav_path = project_dir / "assets" / f"{asset.id}.wav"
            if not wav_path.exists():
                try:
                    convert_to_standard_wav(str(source_path), str(wav_path))
                except Exception as exc:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Failed to prepare imported asset '{asset.name}': {exc}",
                    ) from exc

        _save(project_id, project)
        return {"id": project_id, **_project_to_dict(project, project_id)}
    except HTTPException:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Project import failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Asset import
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/assets")
async def import_asset(project_id: str, file: UploadFile = File(...)):
    project = _load(project_id)
    project_dir = _project_dir(project_id)
    assets_dir = project_dir / "assets"

    # Save the uploaded file to a temp location
    ext = Path(file.filename).suffix.lower()
    asset_id = str(uuid.uuid4())
    original_path = assets_dir / f"{asset_id}_original{ext}"

    with original_path.open("wb") as f:
        content = await file.read()
        f.write(content)

    # Convert to standard WAV for rendering
    wav_path = assets_dir / f"{asset_id}.wav"
    try:
        convert_to_standard_wav(str(original_path), str(wav_path))
        duration = probe_duration(str(wav_path))
    except Exception as e:
        original_path.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Failed to process audio: {e}")

    file_hash = hash_file(str(original_path))

    asset = Asset(
        id=asset_id,
        name=Path(file.filename).stem,
        path=f"assets/{asset_id}_original{ext}",
        hash=file_hash,
        duration_seconds=round(duration, 4),
        format=ext.lstrip("."),
        weight=1.0,
    )
    project.assets.append(asset)
    _save(project_id, project)

    from packages.engine.project import _dump_asset
    return _dump_asset(asset)


@app.delete("/api/projects/{project_id}/assets/{asset_id}")
def delete_asset(project_id: str, asset_id: str):
    project = _load(project_id)
    project.assets = [a for a in project.assets if a.id != asset_id]

    # Remove files
    assets_dir = _project_dir(project_id) / "assets"
    for f in assets_dir.glob(f"{asset_id}*"):
        f.unlink(missing_ok=True)

    _save(project_id, project)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

class ParametersRequest(BaseModel):
    target_duration_seconds: float
    clip_duration_min: float
    clip_duration_max: float
    max_per_clip: Optional[int] = None
    min_gap_clips: int = 0
    allow_consecutive: bool = False
    crossfade_enabled: bool = True
    crossfade_min: float = 0.1
    crossfade_max: float = 2.0
    crossfade_probability: float = 0.8
    silence_enabled: bool = False
    silence_probability: float = 0.3
    silence_min: float = 0.2
    silence_max: float = 2.0
    normalize: bool = True
    target_lufs: float = -18.0
    max_gain_db: float = 12.0
    random_variation_db: float = 0.0
    distribution: str = "uniform"
    chaos: float = 1.0
    allow_repeats: bool = True
    no_repeat_sections: bool = True
    repeat_decay: float = 0.0
    duration_rule: str = "fade_last"
    asset_weights: Optional[Dict[str, float]] = None


@app.put("/api/projects/{project_id}/parameters")
def update_parameters(project_id: str, body: ParametersRequest):
    project = _load(project_id)

    # Apply per-asset weights if provided
    if body.asset_weights:
        for asset in project.assets:
            if asset.id in body.asset_weights:
                asset.weight = body.asset_weights[asset.id]

    project.parameters = Parameters(
        target_duration_seconds=body.target_duration_seconds,
        clip_duration=ClipDuration(
            min_seconds=body.clip_duration_min,
            max_seconds=body.clip_duration_max,
        ),
        repetition=RepetitionParams(
            max_per_clip=1 if not body.allow_repeats else body.max_per_clip,
            min_gap_clips=body.min_gap_clips,
            allow_consecutive=body.allow_consecutive,
            no_repeat_sections=body.no_repeat_sections,
            repeat_decay=body.repeat_decay,
        ),
        crossfade=CrossfadeParams(
            enabled=body.crossfade_enabled,
            min_seconds=body.crossfade_min,
            max_seconds=body.crossfade_max,
            probability=body.crossfade_probability,
        ),
        silence=SilenceParams(
            enabled=body.silence_enabled,
            probability=body.silence_probability,
            min_seconds=body.silence_min,
            max_seconds=body.silence_max,
        ),
        gain=GainParams(
            normalize=body.normalize,
            target_lufs=body.target_lufs,
            max_gain_db=body.max_gain_db,
            random_variation_db=body.random_variation_db,
        ),
        selection=SelectionParams(
            distribution=body.distribution,
            chaos=body.chaos,
        ),
        duration_rule=body.duration_rule,
    )
    _save(project_id, project)
    return _project_to_dict(project, project_id)


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

class SeedRequest(BaseModel):
    seed: str


@app.put("/api/projects/{project_id}/seed")
def update_seed(project_id: str, body: SeedRequest):
    project = _load(project_id)
    project.seed = body.seed
    _save(project_id, project)
    return {"seed": project.seed}


# ---------------------------------------------------------------------------
# Feasibility
# ---------------------------------------------------------------------------

@app.get("/api/projects/{project_id}/feasibility")
def get_feasibility(project_id: str):
    project = _load(project_id)
    result = check_feasibility(project.assets, project.parameters)
    return {
        "feasible": result.feasible,
        "warnings": result.warnings,
        "errors": result.errors,
    }


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/generate")
def generate(project_id: str):
    project = _load(project_id)

    feasibility = check_feasibility(project.assets, project.parameters)
    if not feasibility.feasible:
        raise HTTPException(
            status_code=422,
            detail={"errors": feasibility.errors, "warnings": feasibility.warnings},
        )

    project.timeline = generate_timeline(
        project.assets, project.parameters, project.seed
    )
    _save(project_id, project)

    from packages.engine.project import _dump_event
    return {
        "total_duration_seconds": project.timeline.total_duration_seconds,
        "event_count": len(project.timeline.events),
        "clip_count": sum(1 for e in project.timeline.events if e.type == "clip"),
        "events": [_dump_event(e) for e in project.timeline.events],
        "warnings": feasibility.warnings,
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/render")
def render(project_id: str):
    project = _load(project_id)

    if not project.timeline:
        raise HTTPException(status_code=422, detail="Generate a timeline first.")

    # Build asset_id -> wav path map
    project_dir = _project_dir(project_id)
    asset_wav_map = {
        a.id: str(project_dir / "assets" / f"{a.id}.wav")
        for a in project.assets
    }

    latest_path = project_dir / "renders" / "latest.wav"
    output_path = _download_output_path(project_id, project)

    try:
        render_timeline(project.timeline, asset_wav_map, str(output_path), project.export)
        shutil.copyfile(str(output_path), str(latest_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render failed: {e}")

    size_mb = os.path.getsize(str(output_path)) / (1024 * 1024)
    filename = output_path.name
    return {
        "ok": True,
        "duration_seconds": project.timeline.total_duration_seconds,
        "size_mb": round(size_mb, 2),
        "audio_url": f"/api/projects/{project_id}/audio",
        "download_url": f"/api/projects/{project_id}/download",
        "filename": filename,
    }


@app.get("/api/projects/{project_id}/audio")
def get_audio(project_id: str):
    audio_path = _project_dir(project_id) / "renders" / "latest.wav"
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="No render found. Render the project first.")
    return FileResponse(
        str(audio_path),
        media_type="audio/wav",
    )


@app.get("/api/projects/{project_id}/download")
def download_audio(project_id: str):
    project = _load(project_id)
    output_path = _download_output_path(project_id, project)
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="No render found. Render the project first.")
    return FileResponse(
        str(output_path),
        media_type="audio/wav",
        filename=output_path.name,
    )


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
