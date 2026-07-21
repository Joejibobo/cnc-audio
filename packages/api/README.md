# CNC Audio - API

This package contains the running application:

- the **FastAPI** backend
- the current **browser UI**
- project import/export endpoints
- timeline generation and rendering endpoints

At the moment, the shipped frontend lives in `packages/api/static/index.html`.

## Current Status

**Active and in use in v0.2.**

Start it from the repository root with:

```bash
python start.py
```

Or directly:

```bash
python -m uvicorn packages.api.main:app --reload --host 0.0.0.0 --port 8000
```

Then open:

```text
http://localhost:8000
```

## What It Does

- creates and loads projects
- imports audio and video assets
- stores separate **Songs** and **Sounds** asset libraries
- saves layer parameters and render settings
- checks feasibility before generation
- generates deterministic seeded timelines
- renders output audio
- serves the rendered file for preview and download
- exports and imports project bundles

## Main Files

- `main.py` - FastAPI app and route handlers
- `static/index.html` - current single-file browser UI

## Implemented Routes

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/projects` | Create a new project |
| `GET` | `/api/projects/{project_id}` | Load project state |
| `PUT` | `/api/projects/{project_id}/name` | Rename a project |
| `GET` | `/api/projects/{project_id}/export` | Export a project bundle |
| `POST` | `/api/projects/import` | Import a project bundle |
| `POST` | `/api/projects/{project_id}/assets` | Import an audio/video asset into songs or sounds |
| `DELETE` | `/api/projects/{project_id}/assets/{asset_id}` | Remove an asset |
| `PUT` | `/api/projects/{project_id}/parameters` | Save layer/render parameters |
| `PUT` | `/api/projects/{project_id}/seed` | Update the project seed |
| `GET` | `/api/projects/{project_id}/feasibility` | Run feasibility checks |
| `POST` | `/api/projects/{project_id}/generate` | Generate the timeline |
| `POST` | `/api/projects/{project_id}/render` | Render audio output |
| `GET` | `/api/projects/{project_id}/audio` | Stream rendered audio |
| `GET` | `/api/projects/{project_id}/download` | Download rendered audio |

## Notes

- Asset import normalizes media into standard WAV files for the renderer.
- The app now uses per-project locking to avoid upload/delete write races.
- Timeline playback, zoom, fades, and DAW visualization are currently implemented in the static UI layer.
