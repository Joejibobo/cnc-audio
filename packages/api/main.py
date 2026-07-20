"""CNC Audio -- FastAPI backend."""
import os
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from packages.engine import (
    Asset, ClipDuration, CrossfadeParams, ExportSettings, GainParams,
    Parameters, RepetitionParams, SelectionParams, SilenceParams,
    check_feasibility, generate_timeline, hash_file, load_project,
    new_project, save_project,
)
from packages.renderer.importer import convert_to_standard_wav, probe_duration
from packages.renderer.renderer import render_timeline

app = FastAPI(title="CNC Audio", version="1.0.0")

PROJECTS_DIR = Path("projects")
PROJECTS_DIR.mkdir(exist_ok=True)
STATIC_DIR = Path("packages/api/static")
STATIC_DIR.mkdir(parents=True, exist_ok=True)


def _pdir(pid): return PROJECTS_DIR / pid
def _cnc(pid):  return _pdir(pid) / "project.cnc"

def _load(pid):
    p = _cnc(pid)
    if not p.exists(): raise HTTPException(404, f"Project '{pid}' not found.")
    return load_project(str(p))

def _save(pid, project): save_project(project, str(_cnc(pid)))

def _to_dict(project):
    from packages.engine.project import _dump_asset, _dump_parameters, _dump_event
    d = {
        "version": project.version, "project": project.project,
        "assets": [_dump_asset(a) for a in project.assets],
        "parameters": _dump_parameters(project.parameters),
        "seed": project.seed,
        "export": {
            "format": project.export.format, "sample_rate": project.export.sample_rate,
            "bit_depth": project.export.bit_depth, "normalize_output": project.export.normalize_output,
            "target_output_lufs": project.export.target_output_lufs,
            "true_peak_limit_dbtp": project.export.true_peak_limit_dbtp,
        },
    }
    if project.timeline:
        d["timeline"] = {
            "total_duration_seconds": project.timeline.total_duration_seconds,
            "events": [_dump_event(e) for e in project.timeline.events],
        }
    return d


# -- Projects --
class CreateProjectRequest(BaseModel):
    name: str = "Untitled Project"

@app.post("/api/projects")
def create_project(body: CreateProjectRequest):
    pid = str(uuid.uuid4())
    (_pdir(pid) / "assets").mkdir(parents=True, exist_ok=True)
    (_pdir(pid) / "renders").mkdir(parents=True, exist_ok=True)
    project = new_project(body.name)
    _save(pid, project)
    return {"id": pid, **_to_dict(project)}

@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return {"id": pid, **_to_dict(_load(pid))}


# -- Assets --
@app.post("/api/projects/{pid}/assets")
async def import_asset(pid: str, file: UploadFile = File(...)):
    project = _load(pid)
    assets_dir = _pdir(pid) / "assets"
    ext = Path(file.filename).suffix.lower()
    asset_id = str(uuid.uuid4())
    orig = assets_dir / f"{asset_id}_original{ext}"
    with orig.open("wb") as f:
        f.write(await file.read())
    wav = assets_dir / f"{asset_id}.wav"
    try:
        convert_to_standard_wav(str(orig), str(wav))
        duration = probe_duration(str(wav))
    except Exception as e:
        orig.unlink(missing_ok=True); wav.unlink(missing_ok=True)
        raise HTTPException(422, f"Audio processing failed: {e}")
    asset = Asset(
        id=asset_id, name=Path(file.filename).stem, path=f"assets/{asset_id}_original{ext}",
        hash=hash_file(str(orig)), duration_seconds=round(duration, 4),
        format=ext.lstrip("."), weight=1.0,
    )
    project.assets.append(asset)
    _save(pid, project)
    from packages.engine.project import _dump_asset
    return _dump_asset(asset)

@app.delete("/api/projects/{pid}/assets/{asset_id}")
def delete_asset(pid: str, asset_id: str):
    project = _load(pid)
    project.assets = [a for a in project.assets if a.id != asset_id]
    for f in (_pdir(pid) / "assets").glob(f"{asset_id}*"):
        f.unlink(missing_ok=True)
    _save(pid, project)
    return {"ok": True}


# -- Parameters --
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
    distribution: str = "weighted"
    chaos: float = 0.5
    duration_rule: str = "fade_last"
    asset_weights: Optional[Dict[str, float]] = None

@app.put("/api/projects/{pid}/parameters")
def update_parameters(pid: str, body: ParametersRequest):
    project = _load(pid)
    if body.asset_weights:
        for a in project.assets:
            if a.id in body.asset_weights:
                a.weight = body.asset_weights[a.id]
    project.parameters = Parameters(
        target_duration_seconds=body.target_duration_seconds,
        clip_duration=ClipDuration(min_seconds=body.clip_duration_min, max_seconds=body.clip_duration_max),
        repetition=RepetitionParams(max_per_clip=body.max_per_clip, min_gap_clips=body.min_gap_clips, allow_consecutive=body.allow_consecutive),
        crossfade=CrossfadeParams(enabled=body.crossfade_enabled, min_seconds=body.crossfade_min, max_seconds=body.crossfade_max, probability=body.crossfade_probability),
        silence=SilenceParams(enabled=body.silence_enabled, probability=body.silence_probability, min_seconds=body.silence_min, max_seconds=body.silence_max),
        gain=GainParams(normalize=body.normalize, target_lufs=body.target_lufs, max_gain_db=body.max_gain_db, random_variation_db=body.random_variation_db),
        selection=SelectionParams(distribution=body.distribution, chaos=body.chaos),
        duration_rule=body.duration_rule,
    )
    _save(pid, project)
    return _to_dict(project)

class SeedRequest(BaseModel):
    seed: str

@app.put("/api/projects/{pid}/seed")
def update_seed(pid: str, body: SeedRequest):
    project = _load(pid)
    project.seed = body.seed
    _save(pid, project)
    return {"seed": project.seed}


# -- Feasibility --
@app.get("/api/projects/{pid}/feasibility")
def get_feasibility(pid: str):
    project = _load(pid)
    r = check_feasibility(project.assets, project.parameters)
    return {"feasible": r.feasible, "warnings": r.warnings, "errors": r.errors}


# -- Generate --
@app.post("/api/projects/{pid}/generate")
def generate(pid: str):
    project = _load(pid)
    r = check_feasibility(project.assets, project.parameters)
    if not r.feasible:
        raise HTTPException(422, {"errors": r.errors, "warnings": r.warnings})
    project.timeline = generate_timeline(project.assets, project.parameters, project.seed)
    _save(pid, project)
    from packages.engine.project import _dump_event
    return {
        "total_duration_seconds": project.timeline.total_duration_seconds,
        "event_count": len(project.timeline.events),
        "clip_count": sum(1 for e in project.timeline.events if e.type == "clip"),
        "events": [_dump_event(e) for e in project.timeline.events],
        "warnings": r.warnings,
    }


# -- Render --
@app.post("/api/projects/{pid}/render")
def render(pid: str):
    project = _load(pid)
    if not project.timeline:
        raise HTTPException(422, "Generate a timeline first.")
    wav_map = {a.id: str(_pdir(pid) / "assets" / f"{a.id}.wav") for a in project.assets}
    out = str(_pdir(pid) / "renders" / "latest.wav")
    try:
        render_timeline(project.timeline, wav_map, out, project.export)
    except Exception as e:
        raise HTTPException(500, f"Render failed: {e}")
    size_mb = round(os.path.getsize(out) / (1024*1024), 2)
    return {"ok": True, "duration_seconds": project.timeline.total_duration_seconds, "size_mb": size_mb, "audio_url": f"/api/projects/{pid}/audio"}

@app.get("/api/projects/{pid}/audio")
def get_audio(pid: str):
    p = _pdir(pid) / "renders" / "latest.wav"
    if not p.exists(): raise HTTPException(404, "No render found. Render the project first.")
    return FileResponse(str(p), media_type="audio/wav", filename="cnc-audio.wav")


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
