# CNC Audio

A constrained randomness engine for generating coherent, intentional audio tracks for live performance and shows.

## Overview

CNC Audio takes a library of audio clips and generates "random" tracks that actually *sound good*. The core insight is that randomness without constraint sounds chaotic -- but randomness *within* carefully designed constraints can sound intentional, dynamic, and alive.

Every output track is:
- **Reproducible** -- generated from a seed, so the same inputs and settings recreate the same track
- **Coherent** -- clips are selected and ordered to satisfy hard constraints and respect soft preferences
- **Validated** -- the engine checks feasibility before generating and warns if your settings can't produce a valid track
- **Non-destructive** -- all gain, fade, and effect values are stored in the timeline; the source files are never modified

## How to Run

### Requirements
- Python 3.10+
- FFmpeg (install via winget on Windows: `winget install Gyan.FFmpeg`; or `brew install ffmpeg` on Mac)

### Setup
```
pip install -r requirements.txt
```

### Start the app
```
python start.py
```

Then open **http://localhost:8000** in your browser.

## How it Works

1. **Import clips** -- drag & drop any audio (MP3, WAV, FLAC, AAC) or video (MP4, MOV, etc.) files. Audio is extracted and converted automatically.
2. **Set layer parameters** -- use separate **Songs** and **Sounds** tabs with independent clip ranges, repeats, selection mode, crossfades, silence gaps, and per-layer gain behavior.
3. **Set render settings** -- control total length, song/sound layer gains, global render gain, and output normalization.
4. **Set a seed** -- same seed + same clips + same params = same track every time. Change the seed for a different arrangement.
5. **Generate** -- feasibility runs first, then a base song timeline is generated and a sound timeline is layered on top.
6. **Render** -- mixes both layers with fades/crossfades into a stereo WAV.
7. **Play & Download** -- preview in the browser or download the WAV file.

## Architecture

```
Clips + Parameters + Seed
         |
         v
  [ Timeline Engine ]  -->  .cnc project file (JSON)
         |
         v
  [ Audio Renderer ]   -->  WAV / MP3 / FLAC output
```

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| 1 | Project rules, JSON schema, file format spec | Done |
| 2 | Deterministic timeline generator | Done |
| 3 | Audio import, WAV renderer, FastAPI, browser UI | Done |
| 4 | Timeline editor -- lock sections, reroll clips | Planned |
| 5 | Rhythm & energy analysis | Planned |
| 6 | Key detection, pitch correction, advanced effects | Planned |
| 7 | Studio Mode + Performance Mode | Planned |

## License

MIT
