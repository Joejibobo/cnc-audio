# CNC Audio — Engine

The timeline generation engine. Takes assets, parameters, and a seed — produces a validated `.cnc` timeline.

## Status

⏳ Phase 2 — in development

## Responsibilities

- Feasibility validation (can these parameters produce a valid track?)
- Deterministic, seeded random timeline generation
- Hard constraint enforcement
- Soft preference scoring
- `.cnc` project file serialization/deserialization

## Key Files

- `generator.py` — main timeline generation logic
- `constraints.py` — hard constraint validation
- `preferences.py` — soft preference scoring
- `feasibility.py` — pre-generation feasibility checks
- `models.py` — Python dataclasses mirroring the JSON schema
