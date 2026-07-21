# CNC Audio - Frontend

This directory is currently a **placeholder for a future extracted frontend package**.

## Current Status

There is **no standalone React frontend in production right now**.

The real shipped UI for v0.2 lives here instead:

```text
packages/api/static/index.html
```

That UI currently provides:

- clip import and library management
- separate Songs / Sounds controls
- feasibility feedback
- Generate & Render flow
- in-browser playback and scrubbing
- DAW-style timeline view with zoom and playhead tracking
- project import/export helpers

## Why This Folder Exists

It reserves a clean place for a future frontend extraction if the app is later split into:

- API backend
- dedicated SPA frontend

Until then, treat this directory as a stub rather than an active package.
