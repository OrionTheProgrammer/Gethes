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

## Commands added/expanded

- `vmenu` (`menuui`, `visualmenu`): opens visual menu.
- `mods status`: shows mod-watcher state and mod paths.
- `mods reload`: manual reload for themes and story.
- `physics` (`lab`, `physicslab`): starts physics minigame.

## Packaging note

`Gethes.spec` and `build_exe.ps1` now include hidden imports for the new runtime dependencies used by the executable build.
