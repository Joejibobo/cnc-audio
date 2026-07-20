# CNC Audio — Analyzer

Optional audio analysis. Enriches asset metadata with BPM, key, loudness, and energy data.

## Status

⏳ Phase 6 — planned

## Responsibilities

- BPM detection (librosa beat tracker)
- Key detection (librosa chromagram + key estimation)
- LUFS measurement (FFmpeg `ebur128` filter)
- Energy estimation (RMS, normalized to [0, 1])

## Design Notes

- All results include a **confidence score** (0–1)
- The engine only uses analysis data when explicitly enabled AND confidence ≥ threshold
- Analysis is idempotent — running it twice on the same file produces the same results
- Not every clip has a meaningful BPM or key — that's fine and expected
