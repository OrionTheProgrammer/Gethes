from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json


GRAPHICS_LEVELS = {"low", "medium", "high"}
LANGUAGE_MODES = {"auto", "es", "en", "pt"}
SYSTER_MODES = {"off", "lite", "lore", "hybrid"}


@dataclass
class GameConfig:
    bg_color: str = "#07090D"
    fg_color: str = "#C7D5DF"
    font_family: str = "Consolas"
    font_size: int = 13
    sound: bool = True
    graphics: str = "medium"
    language: str = "auto"
    active_slot: int = 1
    syster_mode: str = "lite"
    syster_endpoint: str = ""
    update_repo: str = "OrionTheProgrammer/Gethes"
    auto_update_check: bool = True
    ui_scale: float = 1.0


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> GameConfig:
        if not self.path.exists():
            return GameConfig()

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return GameConfig()

        cfg = GameConfig()
        if isinstance(payload.get("bg_color"), str):
            cfg.bg_color = payload["bg_color"]
        if isinstance(payload.get("fg_color"), str):
            cfg.fg_color = payload["fg_color"]
        if isinstance(payload.get("font_family"), str):
            cfg.font_family = payload["font_family"]

        font_size = payload.get("font_size")
        if isinstance(font_size, int) and 8 <= font_size <= 42:
            cfg.font_size = font_size

        sound = payload.get("sound")
        if isinstance(sound, bool):
            cfg.sound = sound

        graphics = payload.get("graphics")
        if isinstance(graphics, str) and graphics in GRAPHICS_LEVELS:
            cfg.graphics = graphics

        language = payload.get("language")
        if isinstance(language, str) and language in LANGUAGE_MODES:
            cfg.language = language

        active_slot = payload.get("active_slot")
        if isinstance(active_slot, int) and 1 <= active_slot <= 9:
            cfg.active_slot = active_slot

        syster_mode = payload.get("syster_mode")
        if isinstance(syster_mode, str) and syster_mode in SYSTER_MODES:
            cfg.syster_mode = syster_mode

        syster_endpoint = payload.get("syster_endpoint")
        if isinstance(syster_endpoint, str):
            cfg.syster_endpoint = syster_endpoint.strip()

        update_repo = payload.get("update_repo")
        if isinstance(update_repo, str):
            cfg.update_repo = update_repo.strip()

        auto_update_check = payload.get("auto_update_check")
        if isinstance(auto_update_check, bool):
            cfg.auto_update_check = auto_update_check

        ui_scale = payload.get("ui_scale")
        if isinstance(ui_scale, (int, float)) and 0.7 <= float(ui_scale) <= 2.5:
            cfg.ui_scale = float(ui_scale)

        return cfg

    def save(self, config: GameConfig) -> None:
        try:
            self.path.write_text(
                json.dumps(asdict(config), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            # La app no debe romperse si no puede persistir configuracion.
            pass

