"""Project file serialization and deserialization (.cnc JSON format)."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from .models import (
    AnalysisResult,
    Asset,
    ClipDuration,
    ClipEvent,
    CrossfadeParams,
    ExportSettings,
    GainParams,
    Parameters,
    Project,
    RepetitionParams,
    SelectionParams,
    SilenceEvent,
    SilenceParams,
    Timeline,
)

SCHEMA_VERSION = "1.0.0"


def _load_analysis(d: Optional[dict]) -> Optional[AnalysisResult]:
    if d is None:
        return None
    return AnalysisResult(
        bpm=d.get("bpm"),
        key=d.get("key"),
        lufs=d.get("lufs"),
        energy=d.get("energy"),
    )


def _load_asset(d: dict) -> Asset:
    return Asset(
        id=d["id"],
        name=d["name"],
        path=d["path"],
        hash=d["hash"],
        duration_seconds=d["duration_seconds"],
        sample_rate=d.get("sample_rate"),
        channels=d.get("channels"),
        format=d.get("format"),
        weight=d.get("weight", 1.0),
        tags=d.get("tags", []),
        analysis=_load_analysis(d.get("analysis")),
    )


def _load_parameters(d: dict) -> Parameters:
    cd = d["clip_duration"]
    rep = d.get("repetition", {})
    cf = d.get("crossfade", {})
    sil = d.get("silence", {})
    gain = d.get("gain", {})
    sel = d.get("selection", {})
    return Parameters(
        target_duration_seconds=d["target_duration_seconds"],
        clip_duration=ClipDuration(
            min_seconds=cd["min_seconds"],
            max_seconds=cd["max_seconds"],
        ),
        repetition=RepetitionParams(
            max_per_clip=rep.get("max_per_clip"),
            min_gap_clips=rep.get("min_gap_clips", 0),
            allow_consecutive=rep.get("allow_consecutive", False),
            no_repeat_sections=rep.get("no_repeat_sections", True),
            repeat_decay=rep.get("repeat_decay", 0.0),
        ),
        crossfade=CrossfadeParams(
            enabled=cf.get("enabled", True),
            min_seconds=cf.get("min_seconds", 0.1),
            max_seconds=cf.get("max_seconds", 2.0),
            probability=cf.get("probability", 0.8),
        ),
        silence=SilenceParams(
            enabled=sil.get("enabled", False),
            probability=sil.get("probability", 0.3),
            min_seconds=sil.get("min_seconds", 0.2),
            max_seconds=sil.get("max_seconds", 2.0),
        ),
        gain=GainParams(
            normalize=gain.get("normalize", True),
            target_lufs=gain.get("target_lufs", -18.0),
            max_gain_db=gain.get("max_gain_db", 12.0),
            random_variation_db=gain.get("random_variation_db", 0.0),
        ),
        selection=SelectionParams(
            distribution=sel.get("distribution", "uniform"),
            chaos=sel.get("chaos", 0.5),
        ),
        duration_rule=d.get("duration_rule", "fade_last"),
    )


def _load_event(d: dict):
    if d["type"] == "clip":
        return ClipEvent(
            type="clip",
            asset_id=d["asset_id"],
            position_seconds=d["position_seconds"],
            source_start_seconds=d["source_start_seconds"],
            source_end_seconds=d["source_end_seconds"],
            gain_db=d.get("gain_db", 0.0),
            fade_in_seconds=d.get("fade_in_seconds", 0.0),
            fade_out_seconds=d.get("fade_out_seconds", 0.0),
            locked=d.get("locked", False),
        )
    return SilenceEvent(
        type="silence",
        position_seconds=d["position_seconds"],
        duration_seconds=d["duration_seconds"],
        locked=d.get("locked", False),
    )


def load_project(path: str) -> Project:
    """Load a .cnc project file from disk."""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)

    tl_data = d.get("timeline")
    timeline = None
    if tl_data:
        timeline = Timeline(
            events=[_load_event(e) for e in tl_data["events"]],
            total_duration_seconds=tl_data["total_duration_seconds"],
        )

    exp = d.get("export", {})
    return Project(
        version=d["version"],
        project=d["project"],
        assets=[_load_asset(a) for a in d["assets"]],
        parameters=_load_parameters(d["parameters"]),
        seed=d["seed"],
        timeline=timeline,
        export=ExportSettings(
            format=exp.get("format", "wav"),
            sample_rate=exp.get("sample_rate", 44100),
            bit_depth=exp.get("bit_depth", 24),
            normalize_output=exp.get("normalize_output", True),
            target_output_lufs=exp.get("target_output_lufs", -14.0),
            true_peak_limit_dbtp=exp.get("true_peak_limit_dbtp", -1.0),
        ),
    )


def _dump_analysis(a: Optional[AnalysisResult]) -> Optional[dict]:
    if a is None:
        return None
    result = {}
    if a.bpm is not None:
        result["bpm"] = a.bpm
    if a.key is not None:
        result["key"] = a.key
    if a.lufs is not None:
        result["lufs"] = a.lufs
    if a.energy is not None:
        result["energy"] = a.energy
    return result or None


def _dump_asset(a: Asset) -> dict:
    d: dict = {
        "id": a.id,
        "name": a.name,
        "path": a.path,
        "hash": a.hash,
        "duration_seconds": a.duration_seconds,
        "weight": a.weight,
    }
    if a.sample_rate is not None:
        d["sample_rate"] = a.sample_rate
    if a.channels is not None:
        d["channels"] = a.channels
    if a.format is not None:
        d["format"] = a.format
    if a.tags:
        d["tags"] = a.tags
    analysis = _dump_analysis(a.analysis)
    if analysis:
        d["analysis"] = analysis
    return d


def _dump_parameters(p: Parameters) -> dict:
    return {
        "target_duration_seconds": p.target_duration_seconds,
        "clip_duration": {
            "min_seconds": p.clip_duration.min_seconds,
            "max_seconds": p.clip_duration.max_seconds,
        },
        "repetition": {
            "max_per_clip": p.repetition.max_per_clip,
            "min_gap_clips": p.repetition.min_gap_clips,
            "allow_consecutive": p.repetition.allow_consecutive,
            "no_repeat_sections": p.repetition.no_repeat_sections,
            "repeat_decay": p.repetition.repeat_decay,
        },
        "crossfade": {
            "enabled": p.crossfade.enabled,
            "min_seconds": p.crossfade.min_seconds,
            "max_seconds": p.crossfade.max_seconds,
            "probability": p.crossfade.probability,
        },
        "silence": {
            "enabled": p.silence.enabled,
            "probability": p.silence.probability,
            "min_seconds": p.silence.min_seconds,
            "max_seconds": p.silence.max_seconds,
        },
        "gain": {
            "normalize": p.gain.normalize,
            "target_lufs": p.gain.target_lufs,
            "max_gain_db": p.gain.max_gain_db,
            "random_variation_db": p.gain.random_variation_db,
        },
        "selection": {
            "distribution": p.selection.distribution,
            "chaos": p.selection.chaos,
        },
        "duration_rule": p.duration_rule,
    }


def _dump_event(e) -> dict:
    if isinstance(e, ClipEvent):
        return {
            "type": "clip",
            "asset_id": e.asset_id,
            "position_seconds": e.position_seconds,
            "source_start_seconds": e.source_start_seconds,
            "source_end_seconds": e.source_end_seconds,
            "gain_db": e.gain_db,
            "fade_in_seconds": e.fade_in_seconds,
            "fade_out_seconds": e.fade_out_seconds,
            "locked": e.locked,
        }
    return {
        "type": "silence",
        "position_seconds": e.position_seconds,
        "duration_seconds": e.duration_seconds,
        "locked": e.locked,
    }


def save_project(project: Project, path: str) -> None:
    """Save a project to a .cnc file."""
    d: dict = {
        "version": project.version,
        "project": project.project,
        "assets": [_dump_asset(a) for a in project.assets],
        "parameters": _dump_parameters(project.parameters),
        "seed": project.seed,
    }
    if project.timeline:
        d["timeline"] = {
            "total_duration_seconds": project.timeline.total_duration_seconds,
            "events": [_dump_event(e) for e in project.timeline.events],
        }
    d["export"] = {
        "format": project.export.format,
        "sample_rate": project.export.sample_rate,
        "bit_depth": project.export.bit_depth,
        "normalize_output": project.export.normalize_output,
        "target_output_lufs": project.export.target_output_lufs,
        "true_peak_limit_dbtp": project.export.true_peak_limit_dbtp,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def hash_file(path: str) -> str:
    """Return the SHA-256 hash of a file as 'sha256:<hex>'."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def new_project(name: str) -> Project:
    """Create a new, empty project with sensible defaults."""
    return Project(
        version=SCHEMA_VERSION,
        project={
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        assets=[],
        parameters=Parameters(
            target_duration_seconds=60.0,
            clip_duration=ClipDuration(min_seconds=2.0, max_seconds=10.0),
        ),
        seed="default",
        export=ExportSettings(),
    )
