from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import uuid


GRAPHICS_LEVELS = {"low", "medium", "high"}
LANGUAGE_MODES = {"auto", "es", "en", "pt"}
SYSTER_MODES = {"off", "lite", "lore", "hybrid"}


@dataclass
class GameConfig:
    bg_color: str = "#07090D"
    fg_color: str = "#C7D5DF"
    theme_accent_color: str = ""
    theme_panel_color: str = ""
    theme_dim_color: str = ""
    theme_scan_strength: float = 1.0
    theme_glow_strength: float = 1.0
    theme_particles_strength: float = 1.0
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
    player_name: str = ""
    install_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    cloud_endpoint: str = ""
    cloud_api_key: str = ""
    cloud_enabled: bool = False
    freesound_api_key: str = ""
    sfx_overrides: dict[str, str] = field(default_factory=dict)


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
        if isinstance(payload.get("theme_accent_color"), str):
            cfg.theme_accent_color = payload["theme_accent_color"]
        if isinstance(payload.get("theme_panel_color"), str):
            cfg.theme_panel_color = payload["theme_panel_color"]
        if isinstance(payload.get("theme_dim_color"), str):
            cfg.theme_dim_color = payload["theme_dim_color"]
        theme_scan_strength = payload.get("theme_scan_strength")
        if isinstance(theme_scan_strength, (int, float)) and 0.2 <= float(theme_scan_strength) <= 2.0:
            cfg.theme_scan_strength = float(theme_scan_strength)
        theme_glow_strength = payload.get("theme_glow_strength")
        if isinstance(theme_glow_strength, (int, float)) and 0.2 <= float(theme_glow_strength) <= 2.0:
            cfg.theme_glow_strength = float(theme_glow_strength)
        theme_particles_strength = payload.get("theme_particles_strength")
        if isinstance(theme_particles_strength, (int, float)) and 0.2 <= float(theme_particles_strength) <= 2.0:
            cfg.theme_particles_strength = float(theme_particles_strength)
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

        player_name = payload.get("player_name")
        if isinstance(player_name, str):
            cfg.player_name = player_name.strip()

        install_id = payload.get("install_id")
        if isinstance(install_id, str):
            token = install_id.strip().lower().replace("-", "")
            if len(token) == 32 and all(ch in "0123456789abcdef" for ch in token):
                cfg.install_id = token

        cloud_endpoint = payload.get("cloud_endpoint")
        if isinstance(cloud_endpoint, str):
            cfg.cloud_endpoint = cloud_endpoint.strip()

        cloud_api_key = payload.get("cloud_api_key")
        if isinstance(cloud_api_key, str):
            cfg.cloud_api_key = cloud_api_key.strip()

        cloud_enabled = payload.get("cloud_enabled")
        if isinstance(cloud_enabled, bool):
            cfg.cloud_enabled = cloud_enabled

        freesound_api_key = payload.get("freesound_api_key")
        if isinstance(freesound_api_key, str):
            cfg.freesound_api_key = freesound_api_key.strip()

        raw_overrides = payload.get("sfx_overrides")
        if isinstance(raw_overrides, dict):
            clean_overrides: dict[str, str] = {}
            for key, value in raw_overrides.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    continue
                event_name = key.strip().lower()
                file_name = Path(value.strip()).name
                if not event_name or not file_name:
                    continue
                clean_overrides[event_name] = file_name
            cfg.sfx_overrides = clean_overrides

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

