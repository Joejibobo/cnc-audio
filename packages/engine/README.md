# CNC Audio - Engine

The engine package generates deterministic timelines from:

- imported assets
- per-layer parameters
- a seed

It is the core constrained-random arrangement system used by the app.

## Current Status

**Implemented and active.**

## Responsibilities

- feasibility validation before generation
- seeded deterministic clip selection
- duration-constrained timeline construction
- repetition rules such as max-per-clip, no-repeat-sections, and min-gap handling
- selection distributions such as uniform, weighted, and sequential
- clip-level gain variation
- timeline and project model definitions
- `.cnc`-style project serialization helpers

## Main Files

- `models.py` - core dataclasses for assets, parameters, events, timelines, and projects
- `generator.py` - seeded timeline generation logic
- `feasibility.py` - pre-generation validation and warnings
- `project.py` - project/timeline serialization helpers

## Notes

- Generation is reproducible from the seed.
- Feasibility warnings try to explain why a setup has low variety or cannot fill the target duration.
- The engine is shared by both the browser workflow and project persistence flow.
