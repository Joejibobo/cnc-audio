# CNC Audio Project Format (`.cnc`)

A `.cnc` file is UTF-8 JSON containing project metadata, source-media records,
generation settings, a seed, and optionally a generated timeline. The current
file schema version is `1.0.0`; this is independent of the app release version.
The normative contract is [`schemas/project.schema.json`](../schemas/project.schema.json).

## Top-level fields

| Field | Required | Purpose |
|---|---:|---|
| `version` | yes | Project schema version (`1.0.0`) |
| `project` | yes | Name, creation time, and layered v0.2 state |
| `assets` | yes | Legacy alias for Songs assets |
| `parameters` | yes | Legacy alias for Songs parameters |
| `seed` | yes | Deterministic generation seed |
| `timeline` | no | Generated events; absent after inputs change |
| `export` | yes | Current renderer settings |

For backward compatibility, layered state is stored inside `project` as
`song_assets`, `sound_assets`, `song_parameters`, `sound_parameters`, and
`render_settings`. When these fields are absent, v0.2.1 migrates the top-level
assets and parameters into the Songs layer in memory and saves the layered form
on the next update.

## Assets

Each asset has a safe project-local ID, display name, `assets/...` source path,
full `sha256:<hex>` hash, positive duration, and selection weight from 0.1 to
5. Source hashes cover the original uploaded media, not the generated WAV
cache. Timeline clip events refer to assets by ID.

## Parameters

Each layer stores:

- minimum and maximum source-section duration;
- maximum uses, gap preference, consecutive-use policy, non-overlapping source
  section policy, and repeat decay;
- crossfade probability and bounds;
- optional silence probability and bounds;
- per-event gain variation and reserved loudness fields;
- uniform, weighted, or sequential selection;
- a duration rule: `trim_last`, `fade_last`, `pad_silence`,
  `fill_random_clip`, or `extend_last_clip`.

The seed, asset order/weights, and generation parameters determine the timeline.
The same inputs produce the same arrangement.

Per-clip `normalize` and `target_lufs` fields remain in the schema for forward
compatibility. v0.2.1 does not analyze imported loudness, so normalization only
has an effect if an asset already contains LUFS analysis metadata.

## Timeline

A timeline has `total_duration_seconds` and ordered clip or silence events.
A clip event records the asset ID, output position, source start/end, gain, and
linear fade durations. A silence event records position and duration. Crossfade
events overlap in output time; explicit silence prevents a crossfade across the
gap.

`locked` is serialized for future editing workflows but the v0.2.1 UI does not
offer event locking or reroll editing.

## Export settings

The v0.2.1 contract is:

```json
{
  "format": "wav",
  "sample_rate": 44100,
  "bit_depth": 16,
  "normalize_output": true,
  "target_output_lufs": -14.0,
  "true_peak_limit_dbtp": -1.0
}
```

Despite the legacy field names, `target_output_lufs` is reserved and
`true_peak_limit_dbtp` is used as a sample-peak dBFS ceiling. Integrated LUFS
and oversampled true-peak measurement are not implemented in this release.

## Portable bundles

The browser's Export Project action produces a `.cncaudio.zip` containing
`project.cnc` and each referenced original source file. Converted WAV caches
and renders are omitted and rebuilt locally during import. Bundle import
rejects unsafe paths, links, duplicate/encrypted members, excessive sizes or
counts, invalid schema data, hash mismatches, and unknown timeline asset IDs.
