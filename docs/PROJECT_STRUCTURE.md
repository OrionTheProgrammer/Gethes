# Project Structure

## Core

- `gethes/`
  - `app.py`: main adapter/orchestrator
  - `ui.py`: pygame rendering and input loop
  - `application/`: application services (routing/supervision)
  - `domain/`: domain-level resilience contracts
  - `games/`: minigame modules
  - `story/`: story mode logic
  - `assets/`: runtime assets (sfx, icons, sprites)

## Infrastructure

- `backend/`: cloud telemetry backends (AWS SQLite / Oracle variant)
- `packaging/`: installer/versioning resources
- `tools/`: deployment and maintenance scripts
- `docs/`: architecture and operational docs
- `tests/`: automated tests

## Cleanliness policy

- Keep generated folders out of source control: `build/`, `dist/`, `.pytest_cache/`, `.hypothesis/`, `__pycache__/`.
- Keep release binaries out of git; publish them in GitHub Releases.
