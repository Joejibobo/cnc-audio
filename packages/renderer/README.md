# CNC Audio - Renderer

The renderer package handles media import preparation and final audio rendering.

## Current Status

**Implemented and active.**

## What It Actually Does

### Import side

`importer.py` uses **FFmpeg / ffprobe** to:

- inspect source files
- probe durations and media info
- convert imported audio or video into a standard render-ready WAV
- extract audio from video files

### Render side

`renderer.py` uses **NumPy + Python's wave module** to:

- load prepared WAV assets
- trim source sections by sample position
- apply per-clip gain
- apply clip fade-ins and fade-outs
- mix overlapping clips directly in memory
- apply master fade-in / fade-out
- optionally sample-peak normalize the output to a -1 dBFS ceiling
- write a 44.1 kHz stereo 16-bit PCM WAV file

## Main Files

- `importer.py` - FFmpeg-based probing and WAV conversion
- `renderer.py` - in-memory WAV mixing and output writing

## Requirements

- FFmpeg
- ffprobe
- NumPy

## Notes

- The current renderer is **not** building a live FFmpeg filtergraph for the full mix.
- Crossfades work by overlapping already-faded clip segments in the shared sample buffer.
- Imported source assets are standardized to 44.1 kHz stereo WAV before rendering.
- Integrated LUFS normalization and oversampled true-peak limiting are not implemented.
