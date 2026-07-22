# CNC Audio

CNC Audio is a browser-based tool for building constrained-random audio tracks for live performance, installations, and shows.

It takes a library of source clips, applies user-defined rules, and generates a repeatable arrangement that still feels alive and unpredictable.

## Current Status

**v0.2.1** is a usable local-first MVP.

You can currently:
- import audio and video files
- organize clips into separate **Songs** and **Sounds** layers
- generate deterministic timelines from a seed
- render the result to audio
- preview the render in-browser
- inspect the generated arrangement in a DAW-style timeline
- save/import project bundles and keep local settings

## Core Ideas

Every output track is:
- **Reproducible** - same seed + same clips + same settings = same result
- **Constrained** - randomness is shaped by clip length, repeats, fades, gaps, and selection rules
- **Validated** - feasibility checks help catch impossible settings before generation
- **Layered** - songs and sounds can be controlled independently, then mixed together
- **Non-destructive** - source media is preserved; edits live in project/timeline data

## v0.2.1 Highlights

- resume the most recent autosaved project in the same browser
- open and export portable project bundles from the main toolbar
- safer uploads and bundle imports with strict path, size, hash, and schema checks
- weighted-selection, crossfade/silence, no-repeat, and feasibility fixes
- atomic project/render publication and stable downloads after project renames
- output controls that accurately describe the current renderer

## How to Run

### Requirements

- Python 3.10+
- FFmpeg

Windows:
```powershell
winget install Gyan.FFmpeg
```

macOS:
```bash
brew install ffmpeg
```

### Setup

Create and activate a virtual environment first, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS/Linux, use `source .venv/bin/activate` in place of the PowerShell
activation command.

### Start the app

```bash
python start.py
```

Then open **http://localhost:8000** in your browser.

The launcher listens on `127.0.0.1` only. Project autosaves are stored under
`projects/` on that machine; export a project bundle when you need a portable
backup or want to move to another computer.

## Typical Workflow

1. **Create or load a project**
2. **Import clips** - drag in audio or video files; video audio is extracted automatically
3. **Tune layer settings** - set clip length bounds, repeats, gaps, crossfades, weights, and selection behavior
4. **Set render options** - target duration, layer gains, output gain, normalization, and master fades
5. **Choose a seed** - reuse it for a repeatable result, or change it for a new variation
6. **Generate & Render** - build the timeline and render the output in one step
7. **Preview / scrub / download** - inspect the timeline and export the finished file

## Supported Media

- Audio: MP3, WAV, FLAC, AAC, and other FFmpeg-supported formats
- Video: MP4, MOV, and other FFmpeg-supported formats with extractable audio

Imported media is converted to a standard WAV format internally for rendering consistency.

The v0.2.1 renderer outputs 44.1 kHz stereo 16-bit PCM WAV. Optional output
normalization is sample-peak based with a -1 dBFS ceiling; integrated LUFS and
oversampled true-peak analysis are not implemented yet.

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

Tests run in GitHub Actions on Python 3.10 and 3.13.

## Architecture

```text
Clips + Parameters + Seed
         |
         v
  [ Timeline Engine ]  -->  .cnc project data
         |
         v
  [ FastAPI App + Renderer ]  -->  rendered WAV output
         |
         v
  [ Browser UI ]  -->  timeline preview, playback, download
```

## Repository Layout

```text
packages/
  api/        FastAPI app and browser UI
  engine/     timeline generation logic
  renderer/   audio rendering pipeline
  analyzer/   analysis-related code

start.py      local development launcher
projects/     local generated project data
tests/        automated tests
```

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| 1 | Project rules, JSON schema, file format spec | Done |
| 2 | Deterministic timeline generator | Done |
| 3 | Import, rendering, FastAPI app, browser MVP | Done |
| 4 | Timeline editing tools, reroll controls, lockable sections | Planned |
| 5 | Rhythm and energy analysis | Planned |
| 6 | Key detection, pitch correction, advanced effects | Planned |
| 7 | Studio Mode and Performance Mode | Planned |

## License

[MIT](LICENSE)
