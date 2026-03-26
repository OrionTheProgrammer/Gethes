# Gethes Hexagonal Domain Architecture

This version introduces a domain-oriented hexagonal baseline focused on runtime resilience.

## Layers

- `domain/`
  - Pure domain contracts and models.
  - Contains resilience entities:
    - `DomainPolicy`
    - `DomainState`
    - `DomainFailureEvent`
    - `DomainHealthSnapshot`

- `application/`
  - Orchestration services that do not depend on UI/framework details.
  - `DomainSupervisor` executes domain operations behind fault boundaries:
    - failure streak tracking
    - circuit opening per domain
    - temporary cooldown
    - health snapshots for diagnostics
  - `CommandRouter` provides normalized alias-based command dispatch:
    - centralized command registration
    - lower branching overhead in `GethesApp._on_command`
    - single source of truth for alias suggestions

- `adapters` (current practical adapter: `app.py`)
  - `GethesApp` acts as a primary adapter (UI + command loop) and calls the application layer.
  - Domain failures are translated into player-visible notices and diagnostics output.

## Runtime domains

The supervisor currently manages these domains:

- `ui`
- `update`
- `cloud`
- `games`
- `syster`
- `mods`

Each domain has its own failure threshold and cooldown window.

## Fault-tolerance behavior

- A failing domain does not crash the whole main loop.
- Repeated failures in one domain open a temporary circuit for that domain only.
- Other domains continue running.
- Health status is available in-game:
  - `health` / `domains`
  - `doctor all` (includes domain rows)

## Migration strategy

This is an incremental migration (strangler pattern):

1. Keep game behavior and commands compatible.
2. Move high-risk execution points behind `DomainSupervisor`.
3. Continue extracting bounded contexts (story, games, syster, cloud) into explicit application services.
