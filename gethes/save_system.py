from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


@dataclass
class SaveSlot:
    slot_id: int
    route_name: str = "Route Alpha"
    created_at: str = ""
    updated_at: str = ""
    story_title: str = "Gethes"
    story_page: int = 0
    story_total: int = 0
    notes: str = ""
    flags: dict[str, bool] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)


class SaveManager:
    def __init__(self, save_dir: Path, slots: int = 3) -> None:
        self.save_dir = save_dir
        self.slots = max(1, slots)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_slots()

    def list_slots(self) -> list[SaveSlot]:
        items: list[SaveSlot] = []
        for slot_id in range(1, self.slots + 1):
            items.append(self.load_slot(slot_id))
        return items

    def load_slot(self, slot_id: int) -> SaveSlot:
        path = self._slot_path(slot_id)
        if not path.exists():
            slot = self._default_slot(slot_id)
            self.save_slot(slot)
            return slot

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            slot = self._default_slot(slot_id)
            self.save_slot(slot)
            return slot

        slot = self._default_slot(slot_id)
        for key in asdict(slot):
            if key not in payload:
                continue
            setattr(slot, key, payload[key])

        slot.slot_id = slot_id
        if not isinstance(slot.route_name, str) or not slot.route_name.strip():
            slot.route_name = f"Route {slot_id}"
        if not isinstance(slot.story_page, int):
            slot.story_page = 0
        if not isinstance(slot.story_total, int):
            slot.story_total = 0
        if not isinstance(slot.story_title, str):
            slot.story_title = "Gethes"
        if not isinstance(slot.flags, dict):
            slot.flags = {}
        else:
            slot.flags = {str(k): bool(v) for k, v in slot.flags.items()}
        if not isinstance(slot.notes, str):
            slot.notes = ""
        if not isinstance(slot.stats, dict):
            slot.stats = {}
        else:
            parsed_stats: dict[str, int] = {}
            for key, value in slot.stats.items():
                if isinstance(value, bool):
                    continue
                if isinstance(value, int):
                    parsed_stats[str(key)] = value
                elif isinstance(value, float):
                    parsed_stats[str(key)] = int(value)
            slot.stats = parsed_stats

        if not slot.created_at:
            slot.created_at = _now_iso()
        if not slot.updated_at:
            slot.updated_at = slot.created_at
        return slot

    def save_slot(self, slot: SaveSlot) -> None:
        path = self._slot_path(slot.slot_id)
        if not slot.created_at:
            slot.created_at = _now_iso()
        slot.updated_at = _now_iso()
        try:
            path.write_text(
                json.dumps(asdict(slot), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            return

    def _ensure_slots(self) -> None:
        for slot_id in range(1, self.slots + 1):
            path = self._slot_path(slot_id)
            if path.exists():
                continue
            slot = self._default_slot(slot_id)
            self.save_slot(slot)

    def _default_slot(self, slot_id: int) -> SaveSlot:
        now = _now_iso()
        return SaveSlot(
            slot_id=slot_id,
            route_name=f"Route {slot_id}",
            created_at=now,
            updated_at=now,
        )

    def _slot_path(self, slot_id: int) -> Path:
        return self.save_dir / f"slot_{slot_id}.json"
