# CNC Audio

A constrained randomness engine for generating coherent, intentional audio tracks for live performance and shows.

## Overview

CNC Audio takes a library of audio clips and generates "random" tracks that actually *sound good*. The core insight is that randomness without constraint sounds chaotic — but randomness *within* carefully designed constraints can sound intentional, dynamic, and alive.

Every output track is:
- **Reproducible** — generated from a seed, so the same inputs and settings recreate the same track
- **Coherent** — clips are selected and ordered to satisfy hard constraints and respect soft preferences
- **Validated** — the engine checks feasibility before generating and warns if your settings can't produce a valid track
- **Non-destructive** — all gain, fade, and effect values are stored in the timeline; the source files are never modified

## Architecture

CNC Audio separates **composition** from **rendering**:

1. **Engine** — Takes your clips, parameters, and a seed → produces a validated JSON timeline
2. **Renderer** — Takes the timeline → renders to audio via FFmpeg

This means you can inspect, edit, and lock sections of the timeline before committing to a render.

```
Clips + Parameters + Seed
         │
         ▼
  [ Timeline Engine ]  ──→  .cnc project file (JSON)
         │
         ▼
  [ Audio Renderer ]   ──→  WAV / MP3 / FLAC output
```

## Project Structure

```
cnc-audio/
├── packages/
│   ├── engine/          # Timeline generator (Python) ✅
│   ├── renderer/        # Audio renderer via FFmpeg (Python)
│   ├── analyzer/        # BPM, key, energy analysis (optional)
│   ├── api/             # FastAPI server
│   └── frontend/        # React + TypeScript UI
├── schemas/             # Shared JSON schemas (.cnc project format) ✅
├── tests/               # Unit tests (31 passing) ✅
└── docs/
```

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| 1 | Project rules, JSON schema, file format spec | ✅ Done |
| 2 | Deterministic timeline generator | ✅ Done — 31/31 tests passing |
| 3 | Audio import, analysis stubs, WAV renderer | 🔄 Next |
| 4 | UI — clip library, parameter panel, preview player | ⏳ Planned |
| 5 | Timeline editor — lock sections, reroll clips | ⏳ Planned |
| 6 | Rhythm & energy analysis | ⏳ Planned |
| 7 | Key detection, pitch correction, advanced effects | ⏳ Planned |
| 8 | Studio Mode + Performance Mode | ⏳ Planned |

## Key Design Decisions

### Hard vs Soft Constraints
- **Hard constraints** (e.g. max repeats per clip, exact output duration) are always enforced. Generation fails with a clear error if they cannot be satisfied.
- **Soft preferences** (e.g. avoid recently used clips, energy curve) influence selection without making generation impossible.

### Seeded Randomness
Every generation run takes a seed string. The same seed + same inputs + same parameters always produces the same timeline. Seeds can be copied, shared, and stored in the project file.

### Feasibility Checks
Before generating, the engine validates that your settings can actually produce a track of the requested length. If not, it surfaces a specific warning (e.g. "not enough unique clips to fill 5 minutes without violating the max-repeat rule").

### Musical Analysis is Optional
Not every clip has a meaningful key or tempo. Analysis results are stored with confidence scores. BPM matching and pitch correction are only applied when explicitly enabled *and* confidence is above a configurable threshold.

## Getting Started

*Setup instructions coming in Phase 3 once the renderer and API are complete.*

## License

MIT
