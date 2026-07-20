# CNC Audio — Architecture

## Overview

CNC Audio is built around a strict separation between **composition** (deciding *what* to play and *when*) and **rendering** (actually producing audio).

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Interface                          │
│                    (React + TypeScript)                         │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP (FastAPI)
┌────────────────────────────▼────────────────────────────────────┐
│                          API Layer                              │
│                         packages/api                            │
└───────┬───────────────────────────────────────┬────────────────┘
        │                                       │
┌───────▼───────┐                   ┌───────────▼──────────┐
│    Engine     │                   │      Renderer        │
│  packages/    │                   │     packages/        │
│  engine/      │                   │     renderer/        │
│               │                   │                      │
│ Takes:        │                   │ Takes:               │
│  - assets     │                   │  - .cnc timeline     │
│  - parameters │                   │  - source audio      │
│  - seed       │                   │                      │
│               │                   │ Produces:            │
│ Produces:     │                   │  - WAV/MP3/FLAC      │
│  - timeline   │                   │    via FFmpeg        │
│  - .cnc file  │                   └──────────────────────┘
└───────┬───────┘
        │
┌───────▼───────┐
│   Analyzer    │
│  packages/    │
│  analyzer/    │
│               │
│ Optional:     │
│  - BPM        │
│  - Key        │
│  - LUFS       │
│  - Energy     │
│ (confidence   │
│  scored)      │
└───────────────┘
```

## Packages

### `engine/`
The heart of CNC Audio. Responsible for:
- Validating that parameters are feasible before attempting generation
- Building a valid, deterministic timeline from a seed + assets + parameters
- Enforcing hard constraints (max repeats, duration bounds)
- Applying soft preferences (gap rules, chaos level, energy curve)
- Outputting a validated `.cnc` project file

**Does not touch audio files.** Works entirely on metadata.

### `renderer/`
Converts a `.cnc` timeline into actual audio. Uses **FFmpeg** for all media operations:
- Decoding source audio (any format FFmpeg supports)
- Applying gain adjustments (via `volume` filter)
- Applying fade-in/fade-out (via `afade` filter)
- Concatenating clips with overlapping crossfades (via `amix`/`acrossfade`)
- Final loudness normalization + true-peak limiting (via `loudnorm`)
- Encoding output (WAV, MP3, FLAC, AAC)

**Never modifies source files.**

### `analyzer/`
Optional analysis that enriches asset metadata:
- **BPM detection** — using librosa beat tracker
- **Key detection** — using librosa chromagram
- **LUFS measurement** — using FFmpeg `ebur128` filter
- **Energy estimation** — RMS energy normalized to [0, 1]

All results include a **confidence score**. The engine only uses analysis data when:
1. It has been explicitly enabled by the user
2. The confidence score exceeds a configurable threshold

### `api/`
FastAPI server that exposes the engine, renderer, and analyzer as HTTP endpoints. The frontend communicates exclusively through this API.

### `frontend/`
React + TypeScript single-page application. Key views:
- **Clip Library** — import, tag, weight, and preview clips
- **Parameter Panel** — all generation controls with real-time feasibility feedback
- **Timeline View** — visualize, lock, and reroll sections of the generated timeline
- **Export** — configure output format and trigger render

## Data Flow

```
1. User imports audio files
   → API calls ffprobe to extract duration/format metadata
   → Assets added to .cnc project

2. [Optional] User runs analysis
   → Analyzer runs BPM/key/LUFS/energy detection
   → Results stored in asset.analysis with confidence scores

3. User sets parameters and clicks Generate
   → API validates feasibility
   → Engine generates timeline (deterministic, seeded)
   → Timeline stored in .cnc project
   → Frontend visualizes timeline

4. [Optional] User edits timeline
   → Lock/unlock individual events
   → Reroll unlocked events with same or new seed

5. User renders
   → Renderer reads timeline + source files
   → FFmpeg pipeline assembles and processes audio
   → Output file saved to disk
```

## FFmpeg as Primary Tool

FFmpeg is used for all media I/O and processing. This provides:
- Universal format support (any audio/video FFmpeg can read)
- Video-to-audio extraction (`-vn` flag)
- Professional-grade loudness measurement and normalization (`ebur128`, `loudnorm`)
- True-peak limiting
- No Python audio library dependencies for core functionality

`pydub` may be used for rapid prototyping during development but is not part of the production rendering pipeline.
