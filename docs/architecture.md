# CNC Audio Architecture

## Overview

CNC Audio is a local browser application with four working parts:

```text
Browser UI (HTML/CSS/JavaScript)
              |
              v
       FastAPI application
          /          \
 timeline engine    WAV renderer
          \          /
          project.cnc + local media
```

- `packages/api/` serves the single-page browser UI and JSON/media endpoints.
- `packages/engine/` validates constraints and deterministically builds a
  timeline from assets, parameters, and a seed. It does not decode audio.
- `packages/renderer/importer.py` uses FFmpeg/ffprobe to probe and convert
  imported media to 44.1 kHz stereo PCM WAV caches.
- `packages/renderer/renderer.py` uses NumPy and Python's `wave` module to mix
  clips, gains, overlaps, and fades into the final WAV.

`packages/analyzer/` is reserved for future BPM, key, loudness, and energy
analysis. No analysis pipeline is active in v0.2.1.

## Data flow

1. The API streams source media into a project asset directory with a size cap.
2. FFmpeg prepares an internal WAV cache and ffprobe supplies the duration.
3. Settings and the seed are atomically saved in `project.cnc`.
4. The engine checks feasibility and stores a deterministic timeline.
5. The renderer mixes cached WAV assets in memory and atomically publishes
   `renders/latest.wav`.
6. The browser previews or downloads that render.

Changing an asset, generation setting, render setting, or seed invalidates the
old timeline and render. Changing only the project name preserves them.

## Persistence and portability

Local autosaves live under `projects/<project-id>/`. Writes to `project.cnc`
and publication of the final render use same-directory temporary files and
atomic replacement. A per-project in-process lock serializes mutations.

Portable `.cncaudio.zip` bundles contain only `project.cnc` and referenced
original source media. On import, the API validates the schema, paths, member
counts, expanded size, hashes, asset IDs, durations, and timeline references,
then regenerates internal WAV caches. Renders are intentionally not trusted or
restored from bundles.

## Renderer contract in v0.2.1

- Output: WAV, 44.1 kHz, stereo, 16-bit PCM.
- Crossfades: overlapping clips with complementary linear fades.
- Output protection: sample-peak normalization/limiting to the configured
  ceiling (default -1 dBFS).
- Not implemented: measured integrated LUFS normalization, oversampled
  true-peak limiting, or MP3/FLAC/AAC output.

The renderer holds the output mix and decoded asset cache in memory. The local
API caps target and asset duration at one hour by default; deployments can
lower the documented `CNC_AUDIO_MAX_*` environment limits for their hardware.

## Network boundary

`start.py` binds to `127.0.0.1:8000` without development reload. The API is a
single-user local service; it does not provide authentication and should not be
exposed directly to an untrusted network.
