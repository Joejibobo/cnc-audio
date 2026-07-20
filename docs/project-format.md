# CNC Audio Project Format (.cnc)

A `.cnc` file is a JSON document that fully describes a CNC Audio project. It contains everything needed to reproduce a rendered track: the asset list, generation parameters, the random seed, and the generated timeline.

## Design Goals

- **Reproducible** — given the same `.cnc` file and the same source audio files, the renderer always produces the same output.
- **Non-destructive** — source audio files are never modified. All adjustments (gain, fades, trimming) are stored in the timeline and applied at render time.
- **Editable** — individual timeline events can be locked, reordered, or replaced without re-generating the full track.
- **Versionable** — `.cnc` files are plain JSON and can be committed to git. Media files should not be committed (see `.gitignore`).

---

## Top-Level Fields

| Field | Required | Description |
|-------|----------|-------------|
| `version` | ✅ | Schema version (e.g. `"1.0.0"`) |
| `project` | ✅ | Project metadata (name, timestamps) |
| `assets` | ✅ | List of registered audio clips |
| `parameters` | ✅ | Generation parameters |
| `seed` | ✅ | Random seed string |
| `timeline` | — | Generated timeline (absent until first generation) |
| `export` | — | Export settings (format, sample rate, loudness target) |

---

## Assets

Each asset represents one audio clip registered in the project.

```json
{
  "id": "clip_001",
  "name": "Drone Hit A",
  "path": "assets/drone_hit_a.wav",
  "hash": "sha256:a3f1...",
  "duration_seconds": 8.3,
  "weight": 1.5,
  "tags": ["impact", "low"]
}
```

- **`id`** — unique string identifier, referenced by timeline events
- **`path`** — relative to the `.cnc` file location
- **`hash`** — SHA-256 of the file; the renderer warns if the file has changed since import
- **`weight`** — selection probability weight (default 1.0); higher = selected more often in weighted mode
- **`tags`** — optional user-defined labels for filtering and grouping
- **`analysis`** — populated if analysis has been run; includes `bpm`, `key`, `lufs`, `energy`, each with a `confidence` score

---

## Parameters

### Hard Constraints
These are always enforced. Generation fails with a clear error if they cannot be satisfied.

| Parameter | Description |
|-----------|-------------|
| `target_duration_seconds` | Exact output track length |
| `clip_duration.min_seconds` | No clip contributes less than this duration |
| `clip_duration.max_seconds` | No clip contributes more than this duration (longer clips are trimmed) |
| `repetition.max_per_clip` | No clip appears more than this many times |

### Soft Preferences
These influence selection without blocking generation.

| Parameter | Description |
|-----------|-------------|
| `repetition.min_gap_clips` | Prefer at least N different clips between reuses |
| `selection.chaos` | 0 = most constrained/predictable, 1 = most random |
| `repetition.allow_consecutive` | Whether the same clip can play twice in a row |

### Crossfade
Crossfades overlap the tail of one clip with the head of the next. The overlap duration is picked randomly within `[min_seconds, max_seconds]` when `probability` triggers.

> **Duration note:** Crossfades *reduce* the total timeline length because two clips overlap. The engine accounts for this when filling to `target_duration_seconds`.

### Silence
Silence gaps are inserted *between* clips (not during crossfades). A clip event is followed by a silence event before the next clip event.

### Gain
All gain values are non-destructive:
1. If `normalize: true`, a per-clip `gain_db` is calculated to bring each clip toward `target_lufs`, capped at `max_gain_db`.
2. A random variation of ±`random_variation_db` is added on top.
3. This final `gain_db` is stored on the timeline event and applied by the renderer via FFmpeg.

### Duration Rule
How the final clip is handled to hit the exact `target_duration_seconds`:
- `trim_last` — hard cut at exactly the right moment
- `fade_last` *(default)* — apply a fade-out over the last 2 seconds before the cut
- `pad_silence` — let the last clip play out naturally and pad with silence

### Selection Distribution
- `uniform` — all clips have equal probability
- `weighted` — clips are selected proportionally to their `weight` field
- `sequential` — clips play in the order they are listed in `assets` (loops back to start)

---

## Timeline

The timeline is a flat list of events in chronological order.

### ClipEvent

```json
{
  "type": "clip",
  "asset_id": "clip_001",
  "position_seconds": 0.0,
  "source_start_seconds": 1.5,
  "source_end_seconds": 7.0,
  "gain_db": -2.1,
  "fade_in_seconds": 0.0,
  "fade_out_seconds": 1.2,
  "locked": false
}
```

- **`position_seconds`** — where this event starts in the output track
- **`source_start/end_seconds`** — which portion of the source file is used (enables trimming without touching the source)
- **`fade_in/out_seconds`** — linear fades applied at render time; crossfades are implemented as a fade-out on the ending clip + fade-in on the starting clip at the same position
- **`locked`** — if `true`, reroll operations skip this event

### SilenceEvent

```json
{
  "type": "silence",
  "position_seconds": 7.0,
  "duration_seconds": 0.8,
  "locked": false
}
```

---

## Export Settings

```json
{
  "format": "wav",
  "sample_rate": 44100,
  "bit_depth": 24,
  "normalize_output": true,
  "target_output_lufs": -14,
  "true_peak_limit_dbtp": -1.0
}
```

Final-track normalization uses FFmpeg's `loudnorm` filter with true-peak limiting. This is applied after all clip gain and fades.

---

## Example Minimal Project

```json
{
  "version": "1.0.0",
  "project": {
    "name": "Show Night 1",
    "created_at": "2026-07-20T12:00:00Z"
  },
  "assets": [
    {
      "id": "clip_001",
      "name": "Drone A",
      "path": "assets/drone_a.wav",
      "hash": "sha256:abc123",
      "duration_seconds": 10.0,
      "weight": 1.0
    },
    {
      "id": "clip_002",
      "name": "Stinger B",
      "path": "assets/stinger_b.wav",
      "hash": "sha256:def456",
      "duration_seconds": 3.5,
      "weight": 2.0
    }
  ],
  "parameters": {
    "target_duration_seconds": 60,
    "clip_duration": { "min_seconds": 2.0, "max_seconds": 8.0 },
    "repetition": { "max_per_clip": 5, "min_gap_clips": 1, "allow_consecutive": false },
    "crossfade": { "enabled": true, "min_seconds": 0.5, "max_seconds": 1.5, "probability": 0.7 },
    "silence": { "enabled": false },
    "gain": { "normalize": true, "target_lufs": -18, "max_gain_db": 12, "random_variation_db": 1.5 },
    "selection": { "distribution": "weighted", "chaos": 0.4 },
    "duration_rule": "fade_last"
  },
  "seed": "show-night-1-take-3",
  "export": {
    "format": "wav",
    "sample_rate": 44100,
    "bit_depth": 24,
    "normalize_output": true,
    "target_output_lufs": -14,
    "true_peak_limit_dbtp": -1.0
  }
}
```
