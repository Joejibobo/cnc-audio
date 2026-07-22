# CNC Audio - Tests

This directory contains the automated test suite for the current Python/FastAPI MVP.

## Current Coverage

```text
tests/
  api/      API and project workflow tests
  engine/   generation, feasibility, and project serialization tests
  renderer/ WAV format and output-peak behavior tests
```

## Notable Areas Covered

- feasibility validation
- deterministic timeline generation
- project serialization / bundle behavior
- layered API workflows

## Running Tests

From the repository root:

```bash
pytest
```

Or run a narrower subset:

```bash
pytest tests/engine
pytest tests/api
pytest tests/renderer
```

## Notes

- Media conversion still depends on local FFmpeg, so bundle tests replace that external conversion step with a deterministic test double.
- This README reflects the current repo layout rather than earlier planned package structure.
