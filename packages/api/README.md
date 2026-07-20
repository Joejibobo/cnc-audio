# CNC Audio — API

FastAPI server exposing the engine, renderer, and analyzer over HTTP.

## Status

⏳ Phase 3 — planned

## Endpoints (planned)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/project` | Create a new project |
| `GET` | `/project/{id}` | Load an existing project |
| `POST` | `/project/{id}/assets` | Import audio/video files |
| `POST` | `/project/{id}/generate` | Run the timeline engine |
| `POST` | `/project/{id}/reroll` | Reroll unlocked sections |
| `POST` | `/project/{id}/render` | Render the timeline to audio |
| `POST` | `/project/{id}/analyze/{asset_id}` | Run analysis on an asset |
| `GET` | `/project/{id}/feasibility` | Check if current params are feasible |
