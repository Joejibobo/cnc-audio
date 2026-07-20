# CNC Audio — Renderer

The audio rendering engine. Takes a validated `.cnc` timeline and renders it to an audio file via FFmpeg.

## Status

⏳ Phase 3 — planned

## Responsibilities

- Reading and validating `.cnc` timeline files
- Verifying source audio files (existence, hash integrity)
- Building FFmpeg filter graphs for:
  - Clip trimming (`ss`, `to` flags)
  - Gain adjustment (`volume` filter)
  - Fade in/out (`afade` filter)
  - Crossfading (`acrossfade` filter)
  - Concatenation (`concat` filter)
  - Output normalization (`loudnorm` filter)
- Encoding output in the requested format

## Requirements

- FFmpeg must be installed and available on `PATH`
- `ffprobe` must be available on `PATH`
