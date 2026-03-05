from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except Exception:  # pragma: no cover - optional dependency.
    FileSystemEvent = object  # type: ignore[assignment]
    FileSystemEventHandler = object  # type: ignore[assignment]
    Observer = None


ChangeCallback = Callable[[str, Path], None]


@dataclass(frozen=True)
class WatchTarget:
    path: Path
    tag: str


class _TaggedEventHandler(FileSystemEventHandler):
    def __init__(self, tag: str, callback: ChangeCallback) -> None:
        super().__init__()
        self.tag = tag
        self.callback = callback

    def on_any_event(self, event: FileSystemEvent) -> None:
        if getattr(event, "is_directory", False):
            return

        kind = str(getattr(event, "event_type", "")).lower()
        if kind not in {"created", "modified", "moved", "deleted"}:
            return

        src_path = str(getattr(event, "src_path", "")).strip()
        dst_path = str(getattr(event, "dest_path", "")).strip()
        raw_path = dst_path or src_path
        if not raw_path:
            return

        path = Path(raw_path)
        if path.suffix.lower() != ".json":
            return
        if path.name.startswith("."):
            return

        self.callback(self.tag, path)


class ModWatcher:
    def __init__(self, callback: ChangeCallback) -> None:
        self.callback = callback
        self.targets: list[WatchTarget] = []
        self._observer = Observer() if Observer is not None else None
        self._running = False

    @staticmethod
    def is_available() -> bool:
        return Observer is not None

    def add_target(self, path: Path, tag: str) -> None:
        clean_tag = tag.strip().lower()
        if not clean_tag:
            return
        self.targets.append(WatchTarget(path=path, tag=clean_tag))

    def start(self) -> bool:
        if self._observer is None:
            return False
        if self._running:
            return True

        has_target = False
        for target in self.targets:
            if not target.path.exists():
                continue
            has_target = True
            handler = _TaggedEventHandler(target.tag, self.callback)
            self._observer.schedule(handler, str(target.path), recursive=False)

        if not has_target:
            return False

        self._observer.start()
        self._running = True
        return True

    def stop(self) -> None:
        if self._observer is None or not self._running:
            return
        self._observer.stop()
        self._observer.join(timeout=1.8)
        self._running = False

    def is_running(self) -> bool:
        return self._running
