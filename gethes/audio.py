from __future__ import annotations

from pathlib import Path
import threading
import time

import pygame

try:
    import miniaudio
except Exception:  # pragma: no cover - optional dependency.
    miniaudio = None


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
EVENT_COOLDOWNS: dict[str, float] = {
    "typing": 0.028,
    "message": 0.07,
    "error": 0.12,
    "success": 0.08,
}
EVENT_VOLUMES: dict[str, float] = {
    "typing": 0.45,
    "message": 0.72,
    "error": 0.95,
    "success": 0.82,
    "hit": 0.80,
    "achievement": 0.92,
    "game_over": 0.94,
    "intro": 0.90,
}
FORCED_CHANNEL_EVENTS = {"intro", "error", "achievement", "game_over"}


class AudioManager:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.mixer_ready = False
        self.mixer_error = ""
        self.backend_name = "mute"
        self.assets_dir: Path | None = None
        self.user_assets_dir: Path | None = None
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.loaded_paths: dict[str, Path] = {}
        self.event_overrides: dict[str, str] = {}
        self._mini_lock = threading.Lock()
        self._mini_playbacks: list[tuple[object, object, float]] = []
        self._last_play_times: dict[str, float] = {}

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
        self.mixer_error = ""
        self.backend_name = "mute"
        self._last_play_times = {}
        self.set_event_overrides(overrides or {})
        self._stop_all_miniaudio_playbacks()

        if self.user_assets_dir is not None:
            try:
                self.user_assets_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                self.user_assets_dir = None

        init_ok = self._ensure_mixer()
        if init_ok:
            self.mixer_ready = True
            self.backend_name = "pygame"
            try:
                pygame.mixer.set_num_channels(28)
            except pygame.error:
                pass
            for event_name in EVENT_FILES:
                for path in self._candidate_paths_for_event(event_name):
                    if not path.exists():
                        continue
                    try:
                        sound = pygame.mixer.Sound(str(path))
                        sound.set_volume(EVENT_VOLUMES.get(event_name, 0.86))
                        self.sounds[event_name] = sound
                        self.loaded_paths[event_name] = path
                        break
                    except pygame.error:
                        continue
            return

        self.mixer_ready = False
        if miniaudio is None:
            self.backend_name = "mute"
            return

        self._load_paths_for_miniaudio()
        self.backend_name = "miniaudio" if self.loaded_paths else "mute"

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
        if not self.enabled:
            return
        if event not in EVENT_FILES:
            return

        now = time.monotonic()
        cooldown = EVENT_COOLDOWNS.get(event, 0.0)
        last_play = self._last_play_times.get(event, 0.0)
        if cooldown > 0.0 and (now - last_play) < cooldown:
            return
        self._last_play_times[event] = now

        if self.backend_name == "pygame" and self.mixer_ready:
            sound = self.sounds.get(event)
            if sound is None:
                return
            try:
                force_channel = event in FORCED_CHANNEL_EVENTS
                channel = pygame.mixer.find_channel(force=force_channel)
                if channel is not None:
                    channel.play(sound)
                else:
                    sound.play()
            except pygame.error:
                return
            return

        if self.backend_name == "miniaudio":
            self._play_with_miniaudio(event)

    def available_events(self) -> list[str]:
        return sorted(EVENT_FILES)

    def loaded_events(self) -> list[str]:
        return sorted(self.loaded_paths)

    def loaded_files(self) -> dict[str, str]:
        return {event: path.name for event, path in self.loaded_paths.items()}

    def source_path_for_event(self, event: str) -> str:
        path = self.loaded_paths.get(event)
        if path is None:
            return "-"
        return str(path)

    def backend(self) -> str:
        return self.backend_name

    def describe_status(self) -> str:
        mixer_state = "on" if self.mixer_ready else "off"
        if not self.mixer_ready and self.mixer_error:
            mixer_state = f"off ({self.mixer_error})"
        custom_count = 0
        if self.user_assets_dir is not None:
            for path in self.loaded_paths.values():
                try:
                    path.relative_to(self.user_assets_dir)
                    custom_count += 1
                except ValueError:
                    continue
        loaded_count = len(self.loaded_paths)
        return (
            f"backend={self.backend_name}, mixer={mixer_state}, "
            f"loaded={loaded_count}/{len(EVENT_FILES)}, custom={custom_count}"
        )

    def _ensure_mixer(self) -> bool:
        if pygame.mixer.get_init() is not None:
            return True

        attempts = (
            (44100, -16, 2, 512),
            (48000, -16, 2, 1024),
            (22050, -16, 2, 1024),
        )
        for frequency, size, channels, buffer in attempts:
            try:
                pygame.mixer.init(
                    frequency=frequency,
                    size=size,
                    channels=channels,
                    buffer=buffer,
                )
                self.mixer_error = ""
                return True
            except pygame.error as exc:
                self.mixer_error = str(exc)
                continue
        return False

    def _load_paths_for_miniaudio(self) -> None:
        self.loaded_paths = {}
        for event_name in EVENT_FILES:
            for path in self._candidate_paths_for_event(event_name):
                if path.exists():
                    self.loaded_paths[event_name] = path
                    break

    def _play_with_miniaudio(self, event: str) -> None:
        if miniaudio is None:
            return
        source = self.loaded_paths.get(event)
        if source is None:
            return

        try:
            if hasattr(miniaudio, "PlaybackDevice") and hasattr(miniaudio, "stream_file"):
                stream = miniaudio.stream_file(str(source))
                device = miniaudio.PlaybackDevice()
                device.start(stream)
                with self._mini_lock:
                    self._mini_playbacks.append((device, stream, time.monotonic()))
                    self._cleanup_miniaudio_playbacks_locked()
                return

            if hasattr(miniaudio, "play_file"):
                miniaudio.play_file(str(source))
                return
        except Exception as exc:
            self.mixer_error = str(exc)
            return

    def _stop_all_miniaudio_playbacks(self) -> None:
        if not self._mini_playbacks:
            return
        with self._mini_lock:
            for device, _, _ in self._mini_playbacks:
                self._close_miniaudio_device(device)
            self._mini_playbacks = []

    def _cleanup_miniaudio_playbacks_locked(self) -> None:
        now = time.monotonic()
        keep: list[tuple[object, object, float]] = []
        for device, stream, started in self._mini_playbacks:
            if (now - started) < 8.0 and len(keep) < 16:
                keep.append((device, stream, started))
                continue
            self._close_miniaudio_device(device)
        self._mini_playbacks = keep

    @staticmethod
    def _close_miniaudio_device(device: object) -> None:
        for method_name in ("stop", "close"):
            method = getattr(device, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass

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
