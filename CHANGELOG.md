# Changelog

All notable changes to CNC Audio are documented here.

## [0.2.1] - 2026-07-22

### Added

- Browser recovery for the most recently used local project.
- Project bundle open/export controls and strict bundle validation.
- A version endpoint and visible application version.
- Automated tests on Python 3.10 and 3.13 with GitHub Actions.

### Fixed

- Weighted selection controls now submit valid per-asset weights.
- Crossfades no longer bridge explicit silence, and non-repeating source
  sections account for the full overlap.
- Feasibility calculations respect per-clip limits when source sections may
  repeat.
- Changing generation inputs invalidates stale timelines and renders, while
  reloading unchanged settings preserves resumable work.
- Render downloads keep working after a project rename.
- Project saves and final render publication are atomic within one process.
- Final output uses sample-peak normalization/limiting without claiming LUFS
  or true-peak analysis.

### Security

- Project and asset identifiers, upload sizes, extracted bundle sizes, member
  counts, paths, hashes, durations, and timeline references are validated.
- Bundle extraction rejects traversal paths, links, duplicate members,
  encrypted entries, and unsafe absolute paths.
- User-controlled clip names and server error details are rendered as text in
  the browser to prevent stored cross-site scripting.
- The local launcher binds only to `127.0.0.1` and no longer enables reload.

### Changed

- Portable bundles include `project.cnc` and original source media only;
  converted caches and rendered output are regenerated locally.
- The documented v0.2.1 output contract is WAV, 44.1 kHz, stereo, 16-bit PCM.

## [0.2.0] - 2026-07-21

- Added separate Songs and Sounds layers, a DAW-style timeline, combined
  generation/rendering, timeline zoom, and project bundles.

## [0.1.0]

- Initial constrained, deterministic timeline generator and project format.
