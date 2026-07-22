# CNC Audio - API

This package contains the running application:

- the **FastAPI** backend
- the current **browser UI**
- project import/export endpoints
- timeline generation and rendering endpoints

At the moment, the shipped frontend lives in `packages/api/static/index.html`.

## Current Status

**Active and in use in v0.2.1.**

Start it from the repository root with:

```bash
python start.py
```

Or directly:

```bash
python -m uvicorn packages.api.main:app --host 127.0.0.1 --port 8000
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
| `GET` | `/api/version` | Report the running app version |
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

- Asset import converts media into standard WAV caches for the renderer.
- The app uses per-project locking and atomic project/render publication.
- Bundle import validates paths, schema, hashes, sizes, counts, and references.
- This is an unauthenticated local service; do not bind it to an untrusted network.
- Timeline playback, zoom, fades, and DAW visualization are currently implemented in the static UI layer.
