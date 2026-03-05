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
AUDIO_EXTENSIONS = (".wav", ".ogg", ".mp3")


class AudioManager:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.mixer_ready = False
        self.assets_dir: Path | None = None
        self.user_assets_dir: Path | None = None
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.loaded_paths: dict[str, Path] = {}
        self.event_overrides: dict[str, str] = {}

    def initialize(
        self,
        assets_dir: Path,
        user_assets_dir: Path | None = None,
        overrides: dict[str, str] | None = None,
    ) -> None:
        self.assets_dir = assets_dir
        self.user_assets_dir = user_assets_dir
        self.sounds = {}
        self.loaded_paths = {}
        self.set_event_overrides(overrides or {})

        if self.user_assets_dir is not None:
            try:
                self.user_assets_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                self.user_assets_dir = None

        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self.mixer_ready = True
        except pygame.error:
            self.mixer_ready = False
            return

        for event_name in EVENT_FILES:
            for path in self._candidate_paths_for_event(event_name):
                if not path.exists():
                    continue
                try:
                    self.sounds[event_name] = pygame.mixer.Sound(str(path))
                    self.loaded_paths[event_name] = path
                    break
                except pygame.error:
                    continue

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def set_event_overrides(self, overrides: dict[str, str]) -> None:
        clean: dict[str, str] = {}
        for event, file_name in overrides.items():
            if event not in EVENT_FILES:
                continue
            sanitized = Path(str(file_name)).name.strip()
            if not sanitized:
                continue
            clean[event] = sanitized
        self.event_overrides = clean

    def reload(self) -> None:
        if self.assets_dir is None:
            return
        self.initialize(
            self.assets_dir,
            user_assets_dir=self.user_assets_dir,
            overrides=self.event_overrides,
        )

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

    def loaded_files(self) -> dict[str, str]:
        return {event: path.name for event, path in self.loaded_paths.items()}

    def describe_status(self) -> str:
        if not self.mixer_ready:
            return "mixer=off"
        custom_count = 0
        if self.user_assets_dir is not None:
            for path in self.loaded_paths.values():
                try:
                    path.relative_to(self.user_assets_dir)
                    custom_count += 1
                except ValueError:
                    continue
        return f"mixer=on, loaded={len(self.sounds)}/{len(EVENT_FILES)}, custom={custom_count}"

    def _candidate_paths_for_event(self, event: str) -> list[Path]:
        candidates: list[Path] = []
        seen: set[str] = set()

        override_name = self.event_overrides.get(event)
        if override_name:
            self._append_candidate(candidates, seen, self.user_assets_dir, override_name)
            self._append_candidate(candidates, seen, self.assets_dir, override_name)

        default_name = EVENT_FILES.get(event, "")
        names = self._build_candidate_names(event, default_name)
        for name in names:
            self._append_candidate(candidates, seen, self.user_assets_dir, name)
            self._append_candidate(candidates, seen, self.assets_dir, name)

        return candidates

    def _build_candidate_names(self, event: str, default_name: str) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()

        for base in (default_name, Path(default_name).stem, event):
            raw = Path(base).name.strip()
            if not raw:
                continue

            if Path(raw).suffix:
                candidate_names = [raw]
            else:
                candidate_names = [f"{raw}{ext}" for ext in AUDIO_EXTENSIONS]

            for name in candidate_names:
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                names.append(name)

        return names

    @staticmethod
    def _append_candidate(
        candidates: list[Path],
        seen: set[str],
        base_dir: Path | None,
        file_name: str,
    ) -> None:
        if base_dir is None:
            return
        clean_name = Path(file_name).name
        candidate = base_dir / clean_name
        key = str(candidate).lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(candidate)
