# Gethes Dependency Integration

This document tracks dependencies that are now integrated into the project.

## Adopted dependencies

1. `watchdog`
   - Integrated for automatic mod reload (theme/story JSON files).
   - Runtime behavior: file changes in `mods/themes` and `mods/story` trigger automatic refresh with in-game notifications.
   - Source: https://pypi.org/project/watchdog/

2. `pytweening`
   - Integrated in UI animation easing (panel/toast transitions).
   - Runtime behavior: if available, easing curves use `pytweening`; otherwise built-in fallback equations are used.
   - Source: https://pypi.org/project/pytweening/

3. `miniaudio`
   - Integrated as optional audio fallback backend when `pygame.mixer` cannot initialize.
   - Runtime behavior: auto fallback to `miniaudio` playback for SFX paths if dependency exists.
   - Note: on Python 3.13, wheel availability may require local C++ build tools.
   - Source: https://pypi.org/project/miniaudio/

4. `pygame-menu`
   - Integrated as visual menu system (`vmenu` command).
   - Runtime behavior: opens an in-window interactive menu for game modes and options.
   - Source: https://pygame-menu.readthedocs.io/en/latest/

5. `pymunk`
   - Integrated through a new minigame: `physics` / `physicslab`.
   - Runtime behavior: real physics simulation in a console-style playable loop.
   - Source: https://www.pymunk.org/en/latest/

6. `jsonschema`
   - Integrated to validate story/theme mod payloads before runtime merge/load.
   - Runtime behavior: malformed mod files are rejected safely instead of causing broken runtime state.
   - Source: https://python-jsonschema.readthedocs.io/

7. `rapidfuzz`
   - Integrated for fuzzy command/intent matching.
   - Runtime behavior: command typos now get suggestions and Syster improves typo intent detection.
   - Source: https://rapidfuzz.github.io/RapidFuzz/

8. `httpx`
   - Integrated in Syster remote calls.
   - Runtime behavior: modern HTTP client path with cleaner request handling and fallback to urllib.
   - Source: https://www.python-httpx.org/

9. `tenacity`
   - Integrated for retry policy in Syster remote HTTP calls (httpx path).
   - Runtime behavior: transient network/server issues retry automatically with exponential backoff.
   - Source: https://tenacity.readthedocs.io/

10. `platformdirs`
    - Integrated in runtime storage path resolution.
    - Runtime behavior: per-OS user data directory resolution with backward-compatible fallback behavior.
    - Source: https://platformdirs.readthedocs.io/

## Commands added/expanded

- `vmenu` (`menuui`, `visualmenu`): opens visual menu.
- `mods status`: shows mod-watcher state and mod paths.
- `mods reload`: manual reload for themes and story.
- `physics` (`lab`, `physicslab`): starts physics minigame.
- Unknown command fallback now suggests likely commands (`did you mean ...`).

## Packaging note

`Gethes.spec` and `build_exe.ps1` now include hidden imports for the new runtime dependencies used by the executable build.

## Candidate dependencies (researched, not integrated yet)

Evaluation date: 2026-03-05

1. `Babel`
   - Why: stronger i18n/l10n support (plural rules, locale-aware formatting, catalog workflows).
   - Impact: higher quality multi-language output as story/UI text grows.
   - Source: https://babel.pocoo.org/

2. `pygame_gui`
   - Why: mature retained-mode UI toolkit for in-window settings panels, dialogs, and lists without custom widget code.
   - Impact: faster UX iteration for options/profile screens and fewer custom input edge cases.
   - Source: https://pygame-gui.readthedocs.io/

3. `PyTMX`
   - Why: TMX map loading support for authored tilemaps (Tiled), useful for roguelike rooms and handcrafted story spaces.
   - Impact: cleaner content pipeline; designers can edit maps without touching Python logic.
   - Source: https://pytmx.readthedocs.io/

4. `pyscroll`
   - Why: camera + scrolling renderer built for tiled maps in pygame.
   - Impact: better world rendering quality and less custom camera/render boilerplate.
   - Source: https://github.com/bitcraft/pyscroll

5. `moderngl`
   - Why: GPU rendering and post-processing path (bloom, CRT passes, chromatic aberration, vignette) beyond pure software blits.
   - Impact: large visual ceiling increase for premium feel, but requires careful fallback path and profiling.
   - Source: https://moderngl.readthedocs.io/

6. `numpy`
   - Why: high-performance array math for particles, effects fields, and image processing pipelines.
   - Impact: lower CPU cost for advanced visual effects and deterministic simulation helpers.
   - Source: https://numpy.org/

## Recommended adoption order

1. `pygame_gui` (low-medium risk, immediate UX gain)
2. `Babel` (low risk, long-term i18n quality)
3. `PyTMX` + `pyscroll` (medium risk, large map/content gain)
4. `numpy` (medium risk, performance gain once effects grow)
5. `moderngl` (higher risk, highest visual ceiling)
