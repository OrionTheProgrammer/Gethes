from __future__ import annotations

from pathlib import Path

import pygame


EVENT_FILES: dict[str, str] = {
    "intro": "SFX INTRO GETHES.wav",
    "success": "success.wav",
    "error": "error.wav",
    "tick": "tick.wav",
    "hit": "hit.wav",
    "game_over": "game_over.wav",
    "typing": "typing.wav",
    "message": "message.wav",
    "secret": "secret.wav",
    "achievement": "Logros.wav",
}


class AudioManager:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.mixer_ready = False
        self.assets_dir: Path | None = None
        self.sounds: dict[str, pygame.mixer.Sound] = {}

    def initialize(self, assets_dir: Path) -> None:
        self.assets_dir = assets_dir
        self.sounds = {}

        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self.mixer_ready = True
        except pygame.error:
            self.mixer_ready = False
            return

        for event_name, file_name in EVENT_FILES.items():
            path = assets_dir / file_name
            if not path.exists():
                continue
            try:
                self.sounds[event_name] = pygame.mixer.Sound(str(path))
            except pygame.error:
                continue

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def play(self, event: str) -> None:
        if not self.enabled or not self.mixer_ready:
            return

        sound = self.sounds.get(event)
        if sound is None:
            return

        try:
            sound.play()
        except pygame.error:
            return

    def available_events(self) -> list[str]:
        return sorted(EVENT_FILES)

    def loaded_events(self) -> list[str]:
        return sorted(self.sounds)

    def describe_status(self) -> str:
        if not self.mixer_ready:
            return "mixer=off"
        return f"mixer=on, loaded={len(self.sounds)}/{len(EVENT_FILES)}"
