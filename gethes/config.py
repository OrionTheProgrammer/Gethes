from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import uuid


GRAPHICS_LEVELS = {"low", "medium", "high"}
LANGUAGE_MODES = {"auto", "es", "en", "pt", "fr", "de"}
SYSTER_MODES = {"local"}
THEME_STYLE_MODES = {"terminal", "split_h", "split_v", "grid", "diagonal", "blueprint"}


@dataclass
class GameConfig:
    bg_color: str = "#07090D"
    fg_color: str = "#C7D5DF"
    theme_accent_color: str = ""
    theme_panel_color: str = ""
    theme_dim_color: str = ""
    theme_secondary_color: str = ""
    theme_style: str = ""
    theme_scan_strength: float = 1.0
    theme_glow_strength: float = 1.0
    theme_particles_strength: float = 1.0
    font_family: str = "Consolas"
    font_size: int = 13
    sound: bool = True
    graphics: str = "medium"
    language: str = "auto"
    active_slot: int = 1
    syster_mode: str = "local"
    syster_mode_user_set: bool = False
    syster_endpoint: str = ""
    syster_ollama_enabled: bool = True
    syster_ollama_model: str = "mistral"
    syster_ollama_host: str = "http://127.0.0.1:11434"
    syster_ollama_timeout: float = 24.0
    update_repo: str = "OrionTheProgrammer/Gethes"
    auto_update_check: bool = True
    ui_scale: float = 1.0
    terminal_passthrough: bool = False
    player_name: str = ""
    install_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    cloud_endpoint: str = ""
    cloud_api_key: str = ""
    cloud_enabled: bool = False
    cloud_session_token: str = ""
    cloud_auth_username: str = ""
    cloud_auth_email: str = ""
    cloud_sync_interval_seconds: int = 75
    cloud_news_poll_seconds: int = 300
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
        if isinstance(payload.get("theme_secondary_color"), str):
            cfg.theme_secondary_color = payload["theme_secondary_color"]
        theme_style = payload.get("theme_style")
        if isinstance(theme_style, str) and theme_style in THEME_STYLE_MODES:
            cfg.theme_style = theme_style
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
        if isinstance(syster_mode, str):
            # Compatibility migration: all previous modes map to local.
            cfg.syster_mode = "local"

        syster_mode_user_set = payload.get("syster_mode_user_set")
        if isinstance(syster_mode_user_set, bool):
            cfg.syster_mode_user_set = syster_mode_user_set

        syster_ollama_enabled = payload.get("syster_ollama_enabled")
        if isinstance(syster_ollama_enabled, bool):
            # Local AI is mandatory for Syster in current architecture.
            cfg.syster_ollama_enabled = True

        syster_ollama_model = payload.get("syster_ollama_model")
        if isinstance(syster_ollama_model, str):
            cfg.syster_ollama_model = "mistral"

        syster_ollama_host = payload.get("syster_ollama_host")
        if isinstance(syster_ollama_host, str):
            cfg.syster_ollama_host = syster_ollama_host.strip() or "http://127.0.0.1:11434"

        syster_ollama_timeout = payload.get("syster_ollama_timeout")
        if isinstance(syster_ollama_timeout, (int, float)) and 1.0 <= float(syster_ollama_timeout) <= 120.0:
            cfg.syster_ollama_timeout = float(syster_ollama_timeout)

        # Hard guards for runtime invariants.
        cfg.syster_mode = "local"
        cfg.syster_endpoint = ""
        cfg.syster_ollama_enabled = True
        cfg.syster_ollama_model = "mistral"

        update_repo = payload.get("update_repo")
        if isinstance(update_repo, str):
            cfg.update_repo = update_repo.strip()

        auto_update_check = payload.get("auto_update_check")
        if isinstance(auto_update_check, bool):
            cfg.auto_update_check = auto_update_check

        ui_scale = payload.get("ui_scale")
        if isinstance(ui_scale, (int, float)) and 0.7 <= float(ui_scale) <= 2.5:
            cfg.ui_scale = float(ui_scale)

        terminal_passthrough = payload.get("terminal_passthrough")
        if isinstance(terminal_passthrough, bool):
            cfg.terminal_passthrough = terminal_passthrough

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

        cloud_session_token = payload.get("cloud_session_token")
        if isinstance(cloud_session_token, str):
            cfg.cloud_session_token = cloud_session_token.strip()[:300]

        cloud_auth_username = payload.get("cloud_auth_username")
        if isinstance(cloud_auth_username, str):
            cfg.cloud_auth_username = cloud_auth_username.strip()[:64]

        cloud_auth_email = payload.get("cloud_auth_email")
        if isinstance(cloud_auth_email, str):
            cfg.cloud_auth_email = cloud_auth_email.strip().lower()[:190]

        cloud_sync_interval_seconds = payload.get("cloud_sync_interval_seconds")
        if isinstance(cloud_sync_interval_seconds, int) and 20 <= cloud_sync_interval_seconds <= 600:
            cfg.cloud_sync_interval_seconds = cloud_sync_interval_seconds

        cloud_news_poll_seconds = payload.get("cloud_news_poll_seconds")
        if isinstance(cloud_news_poll_seconds, int) and 60 <= cloud_news_poll_seconds <= 3600:
            cfg.cloud_news_poll_seconds = cloud_news_poll_seconds

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

