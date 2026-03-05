from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
import json
import os
import queue
import shlex
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from gethes import __version__
from gethes.achievements import ACHIEVEMENTS, BY_ID, is_unlocked, unlocked_count
from gethes.audio import AudioManager
from gethes.config import (
    GRAPHICS_LEVELS,
    LANGUAGE_MODES,
    SYSTER_MODES,
    ConfigStore,
    GameConfig,
)
from gethes.freesound_sfx import FreesoundSFXService
from gethes.games.codebreaker import CodeBreakerGame
from gethes.games.hangman import HangmanGame
from gethes.games.physics_lab import PhysicsLabGame
from gethes.games.roguelike import RoguelikeGame
from gethes.games.snake import SnakeGame
from gethes.games.tictactoe import TicTacToeGame
from gethes.i18n import I18n
from gethes.mod_watcher import ModWatcher
from gethes.runtime_paths import resource_package_dir, user_data_dir
from gethes.schema_validation import validate_theme_payload
from gethes.save_system import SaveManager
from gethes.story.story_mode import StoryMode
from gethes.syster import SysterAssistant, SysterContext
from gethes.updater import UpdateInfo, UpdateManager
from gethes.ui import ConsoleUI

try:
    from rapidfuzz import process as rapid_process
except ImportError:  # pragma: no cover - optional dependency fallback
    rapid_process = None


@dataclass(frozen=True)
class ThemePreset:
    bg: str
    fg: str
    accent: str = ""
    panel: str = ""
    dim: str = ""
    scan_strength: float = 1.0
    glow_strength: float = 1.0
    particle_strength: float = 1.0
    unlock_achievement: str = ""


BUILTIN_THEME_PRESETS: dict[str, ThemePreset] = {
    "obsidian": ThemePreset(
        bg="#07090D",
        fg="#C7D5DF",
        accent="#6CB7E8",
        panel="#0D131B",
        dim="#6B8495",
        scan_strength=1.0,
        glow_strength=1.0,
        particle_strength=1.0,
    ),
    "void": ThemePreset(
        bg="#040507",
        fg="#8DA8BA",
        accent="#4F90B7",
        panel="#0A1018",
        dim="#5A6F83",
        scan_strength=0.86,
        glow_strength=0.8,
        particle_strength=0.72,
    ),
    "deepsea": ThemePreset(
        bg="#050B12",
        fg="#91D8FF",
        accent="#39C4FF",
        panel="#0A1724",
        dim="#6E9FBC",
        scan_strength=1.1,
        glow_strength=1.12,
        particle_strength=0.95,
    ),
    "matrix": ThemePreset(
        bg="#050A07",
        fg="#7AF57C",
        accent="#3DEB65",
        panel="#09130D",
        dim="#5BA56A",
        scan_strength=1.22,
        glow_strength=1.02,
        particle_strength=1.1,
    ),
    "amber": ThemePreset(
        bg="#0D0905",
        fg="#FFCF84",
        accent="#EAA24F",
        panel="#1A1208",
        dim="#B2874D",
        scan_strength=0.95,
        glow_strength=0.92,
        particle_strength=0.74,
    ),
    "crimson_archive": ThemePreset(
        bg="#10070A",
        fg="#F0B7C1",
        accent="#FF5A7A",
        panel="#1A0B11",
        dim="#A87984",
        scan_strength=1.16,
        glow_strength=1.18,
        particle_strength=0.88,
        unlock_achievement="hangman_win",
    ),
    "neon_grid": ThemePreset(
        bg="#06040F",
        fg="#CCBEFF",
        accent="#8F63FF",
        panel="#110B1F",
        dim="#8E7DBE",
        scan_strength=1.3,
        glow_strength=1.25,
        particle_strength=1.22,
        unlock_achievement="snake_score_120",
    ),
    "protocol_ice": ThemePreset(
        bg="#050A10",
        fg="#CDEBFF",
        accent="#6FD8FF",
        panel="#0A151F",
        dim="#82A4BC",
        scan_strength=0.84,
        glow_strength=1.08,
        particle_strength=0.7,
        unlock_achievement="codebreaker_win",
    ),
    "companion_dusk": ThemePreset(
        bg="#080A12",
        fg="#D6DAF1",
        accent="#8DA1DF",
        panel="#101425",
        dim="#8B96BC",
        scan_strength=0.74,
        glow_strength=0.9,
        particle_strength=0.62,
        unlock_achievement="story_companion_route",
    ),
    "ghost_echo": ThemePreset(
        bg="#04070B",
        fg="#BFE7F0",
        accent="#4BE1D2",
        panel="#09131A",
        dim="#7395A1",
        scan_strength=1.36,
        glow_strength=1.32,
        particle_strength=1.28,
        unlock_achievement="secret_echo",
    ),
}
DEFAULT_UPDATE_REPO = "OrionTheProgrammer/Gethes"
SYSTER_ENABLED = False
SFX_EVENT_ALIASES: dict[str, str] = {
    "msg": "message",
    "mensaje": "message",
    "respuesta": "message",
    "response": "message",
    "error": "error",
    "errores": "error",
    "typing": "typing",
    "tecleo": "typing",
    "logro": "achievement",
    "logros": "achievement",
}


class GethesApp:
    def __init__(self) -> None:
        package_dir = resource_package_dir()
        self.data_dir = package_dir / "data"
        self.assets_dir = package_dir / "assets" / "sfx"
        self.storage_dir = user_data_dir()
        self.mods_dir = self.storage_dir / "mods"
        self.theme_mods_dir = self.mods_dir / "themes"
        self.story_mods_dir = self.mods_dir / "story"
        self.user_sfx_dir = self.storage_dir / "sfx"

        self.config_store = ConfigStore(self.storage_dir / "gethes_config.json")
        self.config = self.config_store.load()
        self.i18n = I18n.from_mode(self.config.language)
        self.audio = AudioManager(enabled=self.config.sound)
        self.sfx_service = FreesoundSFXService(api_key=self.config.freesound_api_key)
        self.input_handler: Callable[[str], None] | None = None
        self.update_events: queue.Queue[tuple[str, dict[str, object]]] = queue.Queue()
        self.mod_watcher: ModWatcher | None = None
        self.mod_reload_times: dict[str, float] = {"theme": 0.0, "story": 0.0}
        self.theme_mod_errors: list[str] = []
        self.update_check_running = False
        self.update_install_running = False
        self.update_install_after_check = False
        self.update_install_require_checksum = True
        self.update_prepare_after_check = False
        self.update_prepare_require_checksum = True
        self.update_cancel_event: threading.Event | None = None
        self.update_downloaded_bytes = 0
        self.update_download_total_bytes = 0
        self.auto_update_check_done = False
        self.pending_update: UpdateInfo | None = None
        self.prepared_update_path: Path | None = None
        self.prepared_update_method = ""
        self.prepared_update_version = ""
        self.prepared_update_checksum_status = ""
        self.update_last_status = "idle"
        self.update_download_dir = self.storage_dir / "updates"
        update_repo = (
            self.config.update_repo
            or os.getenv("GETHES_UPDATE_REPO", "")
            or DEFAULT_UPDATE_REPO
        )
        self.update_manager = UpdateManager(
            current_version=__version__,
            repo=update_repo,
            cache_dir=self.update_download_dir / "cache",
        )
        self.config.update_repo = self.update_manager.repo
        self.update_manager.cleanup_update_artifacts(self.update_download_dir)

        self.save_manager = SaveManager(self.storage_dir / "saves", slots=3)
        self.current_slot = self.save_manager.load_slot(self._clamp_slot(self.config.active_slot))
        self.config.active_slot = self.current_slot.slot_id

        self.syster_enabled = SYSTER_ENABLED
        self.syster = SysterAssistant(
            mode=self.config.syster_mode,
            remote_endpoint=self.config.syster_endpoint or None,
        )
        if not self.syster_enabled:
            self.syster.set_mode("off")
            self.syster.set_remote_endpoint(None)
        self.config.syster_mode = self.syster.mode
        if not self.syster_enabled:
            self.config.syster_endpoint = ""

        self.ui = ConsoleUI(
            title=self.tr("ui.title"),
            on_command=self._on_command,
        )
        self.ui.on_close = self._shutdown
        self.ui.on_idle = self._on_idle
        self.ui.set_audio(self.audio)
        self._ensure_modding_templates()
        self.theme_presets = self._load_theme_presets()
        self._start_mod_watcher()
        self._reload_audio_assets()

        self.boot_active = False
        self.boot_steps: list[str] = []
        self.boot_completed = 0
        self.boot_timer_ms = 0.0
        self.idle_count = 0
        self.intro_active = False
        self.last_command = "menu"
        self.syster_auto_pending = False
        self.syster_last_auto_ts = 0.0
        self.syster_auto_cooldown = 7.0
        self.syster_commands_since_auto = 0

        self._migrate_legacy_theme()
        self._sync_theme_visual_profile()
        self._refresh_ui_language()
        self._apply_visual_config()

        words = self._load_words()
        self.snake = SnakeGame(self)
        self.hangman = HangmanGame(self, words)
        self.story = StoryMode(self, self.data_dir, mod_story_dir=self.story_mods_dir)
        self.tictactoe = TicTacToeGame(self)
        self.codebreaker = CodeBreakerGame(self)
        self.physics_lab = PhysicsLabGame(self)
        self.roguelike = RoguelikeGame(self)

    def tr(self, key: str, **kwargs: object) -> str:
        return self.i18n.t(key, **kwargs)

    def run(self) -> None:
        self._start_intro_sequence()
        self.ui.run(update_callback=self._update)

    def _update(self, dt: float) -> None:
        self._process_update_events()
        if self.intro_active:
            if self.ui.update_intro(dt):
                self.intro_active = False
                self._start_boot_sequence()
            return
        if self.boot_active:
            self._update_boot(dt)
        if self.snake.active:
            self.snake.update(dt)
        if self.physics_lab.active:
            self.physics_lab.update(dt)
        if self.roguelike.active:
            self.roguelike.update(dt)
        if self.syster_enabled:
            self._update_syster_autochat()

    def set_input_handler(self, handler: Callable[[str], None]) -> None:
        self.input_handler = handler

    def clear_input_handler(self) -> None:
        self.input_handler = None

    def on_story_progress(self, page: int, total: int, title: str) -> None:
        self.current_slot.story_page = max(0, page)
        self.current_slot.story_total = max(0, total)
        self.current_slot.story_title = title

    def on_story_choice_made(self, choice_flag: str) -> None:
        token = choice_flag.strip()
        if not token:
            return
        event_flag = f"story_choice_seen_{token}"
        if self.current_slot.flags.get(event_flag, False):
            return
        self.current_slot.flags[event_flag] = True
        self.bump_stat("story_choices_total", 1)
        self._unlock_achievement("story_first_choice")
        self._save_current_slot(user_feedback=False)

    def on_story_secret_unlocked(self, secret_id: str) -> None:
        token = secret_id.strip().lower()
        if not token:
            return
        flag = f"story_secret_unlocked_{token}"
        if self.current_slot.flags.get(flag, False):
            return
        self.current_slot.flags[flag] = True
        self.bump_stat("story_secrets_unlocked", 1)
        self._unlock_achievement("story_secret_finder")
        self._save_current_slot(user_feedback=False)

    def on_story_secret_viewed(self, secret_id: str) -> None:
        token = secret_id.strip().lower()
        if not token:
            return
        flag = f"story_secret_read_{token}"
        if self.current_slot.flags.get(flag, False):
            return
        self.current_slot.flags[flag] = True
        total_read = self.bump_stat("story_secrets_read", 1)
        if total_read >= 3:
            self._unlock_achievement("story_archivist")
        self._save_current_slot(user_feedback=False)

    def on_story_route_entered(self, route_id: str) -> None:
        token = route_id.strip().lower()
        if not token:
            return
        flag = f"story_route_{token}"
        if self.current_slot.flags.get(flag, False):
            return
        self.current_slot.flags[flag] = True
        if token == "companion":
            self._unlock_achievement("story_companion_route")
        self._save_current_slot(user_feedback=False)

    def get_stat(self, key: str, default: int = 0) -> int:
        value = self.current_slot.stats.get(key, default)
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return default

    def set_stat(self, key: str, value: int) -> None:
        self.current_slot.stats[key] = int(value)

    def bump_stat(self, key: str, delta: int = 1) -> int:
        current = self.get_stat(key, 0)
        updated = current + int(delta)
        self.current_slot.stats[key] = updated
        return updated

    def set_stat_max(self, key: str, value: int) -> bool:
        current = self.get_stat(key, 0)
        if value > current:
            self.current_slot.stats[key] = int(value)
            return True
        return False

    def on_story_finished(self, completed: bool) -> None:
        if not completed:
            return
        self.bump_stat("story_completed_runs", 1)
        self._unlock_achievement("story_complete")
        self._save_current_slot(user_feedback=False)

    def on_snake_food_eaten(self, score: int, level: int, length: int) -> None:
        self.bump_stat("snake_food_total", 1)
        self.set_stat_max("snake_best_level", level)
        self.set_stat_max("snake_longest_length", length)
        if score >= 10:
            self._unlock_achievement("snake_first_food")
        if score >= 120:
            self._unlock_achievement("snake_score_120")

    def on_snake_finished(
        self,
        score: int,
        level: int,
        foods_eaten: int,
        game_over: bool,
        user_exit: bool,
    ) -> None:
        self.set_stat_max("snake_best_score", score)
        self.set_stat_max("snake_best_level", level)
        self.set_stat_max("snake_best_food_run", foods_eaten)
        self.bump_stat("snake_games", 1)
        if not user_exit and not game_over and score >= 120:
            self._unlock_achievement("snake_score_120")
        self._save_current_slot(user_feedback=False)

    def on_hangman_finished(self, won: bool, mode: str, errors: int, hint_used: bool) -> None:
        self.bump_stat("hangman_games", 1)
        if won:
            self.bump_stat("hangman_wins", 1)
            self._unlock_achievement("hangman_win")
            if mode == "2P":
                self._unlock_achievement("hangman_duel_win")
        if hint_used:
            self.bump_stat("hangman_hints", 1)
        self.set_stat_max("hangman_best_errors_left", max(0, 6 - errors))
        self._save_current_slot(user_feedback=False)

    def on_tictactoe_finished(self, won: bool, draw: bool) -> None:
        self.bump_stat("ttt_games", 1)
        if won:
            self.bump_stat("ttt_wins", 1)
            self._unlock_achievement("ttt_win")
        elif draw:
            self.bump_stat("ttt_draws", 1)
        else:
            self.bump_stat("ttt_losses", 1)
        self._save_current_slot(user_feedback=False)

    def on_codebreaker_finished(self, won: bool, attempts_used: int, hint_used: bool) -> None:
        self.bump_stat("codebreaker_games", 1)
        if won:
            self.bump_stat("codebreaker_wins", 1)
            self._unlock_achievement("codebreaker_win")
            best = self.get_stat("codebreaker_best_attempts", 999)
            if best <= 0 or attempts_used < best:
                self.set_stat("codebreaker_best_attempts", attempts_used)
        if hint_used:
            self.bump_stat("codebreaker_hints", 1)
        self._save_current_slot(user_feedback=False)

    def on_physics_finished(self, score: int, won: bool, cancelled: bool) -> None:
        if cancelled:
            return
        self.bump_stat("physics_games", 1)
        if won:
            self.bump_stat("physics_wins", 1)
        self.set_stat_max("physics_best_score", score)
        self._save_current_slot(user_feedback=False)

    def on_roguelike_finished(
        self,
        won: bool,
        cancelled: bool,
        depth: int,
        kills: int,
        gold: int,
    ) -> None:
        if cancelled:
            return
        self.bump_stat("rogue_runs", 1)
        if won:
            self.bump_stat("rogue_wins", 1)
        self.set_stat_max("rogue_best_depth", depth)
        self.set_stat_max("rogue_best_gold", gold)
        self.set_stat_max("rogue_best_kills", kills)
        self._save_current_slot(user_feedback=False)

    def _migrate_legacy_theme(self) -> None:
        legacy_bg = self.config.bg_color.strip().lower()
        legacy_fg = self.config.fg_color.strip().lower()
        if legacy_bg == "#101820" and legacy_fg == "#e8f1f2":
            theme = self.theme_presets.get("obsidian", BUILTIN_THEME_PRESETS["obsidian"])
            self.config.bg_color = theme.bg
            self.config.fg_color = theme.fg
            self.config.theme_accent_color = theme.accent
            self.config.theme_panel_color = theme.panel
            self.config.theme_dim_color = theme.dim
            self.config.theme_scan_strength = theme.scan_strength
            self.config.theme_glow_strength = theme.glow_strength
            self.config.theme_particles_strength = theme.particle_strength

    def _sync_theme_visual_profile(self) -> None:
        if self.config.theme_accent_color.strip():
            return
        if self.config.theme_panel_color.strip():
            return
        if self.config.theme_dim_color.strip():
            return
        if (
            abs(float(self.config.theme_scan_strength) - 1.0) > 0.001
            or abs(float(self.config.theme_glow_strength) - 1.0) > 0.001
            or abs(float(self.config.theme_particles_strength) - 1.0) > 0.001
        ):
            return

        for preset in self.theme_presets.values():
            if (
                preset.bg.lower() == self.config.bg_color.lower()
                and preset.fg.lower() == self.config.fg_color.lower()
            ):
                self.config.theme_accent_color = preset.accent
                self.config.theme_panel_color = preset.panel
                self.config.theme_dim_color = preset.dim
                self.config.theme_scan_strength = preset.scan_strength
                self.config.theme_glow_strength = preset.glow_strength
                self.config.theme_particles_strength = preset.particle_strength
                return

    def _load_words(self) -> list[str]:
        words_file = self.data_dir / "words.txt"
        if not words_file.exists():
            return ["SYSTEM", "CONSOLE", "SNAKE", "HANGMAN", "STORY"]

        words = []
        for raw in words_file.read_text(encoding="utf-8").splitlines():
            value = raw.strip().upper()
            if not value or value.startswith("#"):
                continue
            words.append(value)

        return words or ["SYSTEM", "CONSOLE", "SNAKE", "HANGMAN", "STORY"]

    def _ensure_modding_templates(self) -> None:
        try:
            self.theme_mods_dir.mkdir(parents=True, exist_ok=True)
            self.story_mods_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

        readme_path = self.mods_dir / "README_MODS.txt"
        if not readme_path.exists():
            try:
                readme_path.write_text(
                    "\n".join(
                        [
                            "Gethes Mods Folder",
                            "",
                            "themes/: add JSON files to define or override themes.",
                            "story/: add story_<lang>.json (es/en/pt) or story.json.",
                            "",
                            "Story mod format:",
                            "  {",
                            '    "mode": "append" | "replace",',
                            '    "title": "Optional title",',
                            '    "chapters": [{"title": "...", "pages": ["...", "..."]}]',
                            "  }",
                            "",
                            "Theme mod format (single):",
                            '  {"name":"nocturne","bg":"#05070B","fg":"#C3CEDA"}',
                            "  Optional: accent/panel/dim + fx scan/glow/particles + unlock_achievement",
                            "",
                            "Theme mod format (pack):",
                            '  {"themes":{"nocturne":{"bg":"#05070B","fg":"#C3CEDA","accent":"#6CB7E8","fx":{"scan":1.1,"glow":0.9,"particles":0.8},"unlock_achievement":"codebreaker_win"}}}',
                        ]
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass

        theme_sample = self.theme_mods_dir / "sample_theme_pack.json"
        if not theme_sample.exists():
            try:
                theme_sample.write_text(
                    json.dumps(
                        {
                            "themes": {
                                "nocturne": {
                                    "bg": "#05070B",
                                    "fg": "#C3CEDA",
                                    "accent": "#7AA8D9",
                                    "fx": {"scan": 1.0, "glow": 0.9, "particles": 0.8},
                                },
                                "bloodmoon": {
                                    "bg": "#10060A",
                                    "fg": "#F0B7C1",
                                    "accent": "#FF5A7A",
                                    "fx": {"scan": 1.2, "glow": 1.2, "particles": 0.9},
                                    "unlock_achievement": "hangman_win",
                                },
                                "mono_ice": {
                                    "bg": "#070B0D",
                                    "fg": "#D2E1E8",
                                    "accent": "#7AD0F2",
                                    "fx": {"scan": 0.85, "glow": 1.0, "particles": 0.7},
                                },
                            }
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass

        story_sample = self.story_mods_dir / "sample_story_es.json"
        if not story_sample.exists():
            try:
                story_sample.write_text(
                    json.dumps(
                        {
                            "mode": "append",
                            "title": "Gethes: Ecos Externos",
                            "chapters": [
                                {
                                    "title": "Capitulo Mod - Lluvia de Fondo",
                                    "pages": [
                                        "La ventana recibe gotas imaginarias. Syster no las oye, pero responde igual.",
                                        "Si agregas mas capitulos aqui, apareceran al final del modo historia.",
                                    ],
                                }
                            ],
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass

    @staticmethod
    def _clamp_theme_strength(value: object, default: float = 1.0) -> float:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return max(0.2, min(2.0, float(value)))
        return default

    def _parse_theme_preset(self, payload: object) -> ThemePreset | None:
        if not isinstance(payload, dict):
            return None

        bg = payload.get("bg")
        fg = payload.get("fg")
        if not isinstance(bg, str) or not isinstance(fg, str):
            return None

        fx: dict[str, object] = {}
        raw_fx = payload.get("fx")
        if isinstance(raw_fx, dict):
            fx = raw_fx

        accent = payload.get("accent")
        panel = payload.get("panel")
        dim = payload.get("dim")
        unlock = payload.get("unlock_achievement")
        if not isinstance(unlock, str):
            unlock = ""

        return ThemePreset(
            bg=bg.strip(),
            fg=fg.strip(),
            accent=(accent.strip() if isinstance(accent, str) else ""),
            panel=(panel.strip() if isinstance(panel, str) else ""),
            dim=(dim.strip() if isinstance(dim, str) else ""),
            scan_strength=self._clamp_theme_strength(
                fx.get("scan", payload.get("scan_strength", payload.get("scan", 1.0))),
                default=1.0,
            ),
            glow_strength=self._clamp_theme_strength(
                fx.get("glow", payload.get("glow_strength", payload.get("glow", 1.0))),
                default=1.0,
            ),
            particle_strength=self._clamp_theme_strength(
                fx.get(
                    "particles",
                    payload.get("particle_strength", payload.get("particles", 1.0)),
                ),
                default=1.0,
            ),
            unlock_achievement=unlock.strip().lower(),
        )

    def _load_theme_presets(self) -> dict[str, ThemePreset]:
        presets = dict(BUILTIN_THEME_PRESETS)
        self.theme_mod_errors = []
        for mod_file in sorted(self.theme_mods_dir.glob("*.json")):
            try:
                payload = json.loads(mod_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.theme_mod_errors.append(f"{mod_file.name}: invalid_json")
                continue

            valid, error_msg = validate_theme_payload(payload)
            if not valid:
                self.theme_mod_errors.append(f"{mod_file.name}: {error_msg}")
                continue

            for name, theme in self._collect_theme_entries(payload):
                normalized = name.strip().lower().replace(" ", "_")
                if not normalized:
                    continue
                if not self.ui.is_valid_color(theme.bg) or not self.ui.is_valid_color(theme.fg):
                    continue
                if theme.accent and not self.ui.is_valid_color(theme.accent):
                    continue
                if theme.panel and not self.ui.is_valid_color(theme.panel):
                    continue
                if theme.dim and not self.ui.is_valid_color(theme.dim):
                    continue
                presets[normalized] = theme

        return presets

    def _collect_theme_entries(self, payload: object) -> list[tuple[str, ThemePreset]]:
        entries: list[tuple[str, ThemePreset]] = []
        if not isinstance(payload, dict):
            return entries

        name = payload.get("name")
        base_theme = self._parse_theme_preset(payload)
        if isinstance(name, str) and base_theme is not None:
            entries.append((name, base_theme))

        theme_pack = payload.get("themes")
        if isinstance(theme_pack, dict):
            for name, item in theme_pack.items():
                if not isinstance(name, str) or not isinstance(item, dict):
                    continue
                parsed = self._parse_theme_preset(item)
                if parsed is not None:
                    entries.append((name, parsed))

        for name, item in payload.items():
            if name == "themes":
                continue
            if not isinstance(name, str) or not isinstance(item, dict):
                continue
            parsed = self._parse_theme_preset(item)
            if parsed is not None:
                entries.append((name, parsed))

        return entries

    def _reload_theme_presets(self) -> int:
        self.theme_presets = self._load_theme_presets()
        return len(self.theme_presets)

    def _start_mod_watcher(self) -> None:
        if self.mod_watcher is not None:
            return
        if not ModWatcher.is_available():
            return

        watcher = ModWatcher(self._on_mod_file_change)
        watcher.add_target(self.theme_mods_dir, tag="theme")
        watcher.add_target(self.story_mods_dir, tag="story")
        if watcher.start():
            self.mod_watcher = watcher

    def _stop_mod_watcher(self) -> None:
        if self.mod_watcher is None:
            return
        self.mod_watcher.stop()
        self.mod_watcher = None

    def _on_mod_file_change(self, tag: str, path: Path) -> None:
        self.update_events.put(
            (
                "mod_change",
                {
                    "tag": tag,
                    "path": str(path),
                },
            )
        )

    def _handle_mods(self, args: list[str]) -> None:
        action = args[0].lower() if args else "status"
        if action in {"status", "state"}:
            watch_state = (
                "ON"
                if self.mod_watcher is not None and self.mod_watcher.is_running()
                else "OFF"
            )
            self.ui.write(
                self.tr(
                    "app.mods.status",
                    watch=watch_state,
                    themes=len(self.theme_presets),
                    story_pages=len(self.story.pages),
                )
            )
            self.ui.write(
                self.tr(
                    "app.mods.paths",
                    themes=str(self.theme_mods_dir),
                    story=str(self.story_mods_dir),
                )
            )
            self.ui.write(self.tr("app.mods.usage"))
            return

        if action == "reload":
            count = self._reload_theme_presets()
            self.story.reload_for_language()
            self.ui.write(self.tr("app.mods.reloaded", themes=count, story_pages=len(self.story.pages)))
            return

        self.ui.write(self.tr("app.mods.usage"))

    def _on_idle(self) -> None:
        if (
            self.intro_active
            or self.boot_active
            or self.snake.active
            or self.physics_lab.active
            or self.roguelike.active
            or self.input_handler is not None
        ):
            return

        if self.syster_enabled and self._trigger_syster_auto("idle"):
            return

        if self.syster_enabled and self.idle_count % 3 == 2:
            self.ui.write(self.tr("app.idle.secret"))
        else:
            self.ui.write(self.tr("app.idle.help"))
        self.audio.play("message")
        self.idle_count += 1

    def _on_command(self, raw_command: str) -> None:
        if self.input_handler is not None:
            self.input_handler(raw_command)
            return

        command = raw_command.strip()
        if not command:
            return

        try:
            parts = shlex.split(command)
        except ValueError as exc:
            self.ui.write(self.tr("app.syntax_error", error=str(exc)))
            return

        cmd = parts[0].lower()
        args = parts[1:]
        if cmd != "syster":
            self.last_command = cmd
            self._queue_syster_auto_from_command(cmd)

        if cmd in {"help", "ayuda", "ajuda", "?"}:
            self.ui.write(self._help_text())
            return

        if cmd in {"clear", "cls"}:
            self.ui.clear()
            return

        if cmd in {"menu", "inicio", "home"}:
            self.ui.set_screen(self._welcome_text())
            return

        if cmd in {"vmenu", "menuui", "visualmenu"}:
            self.ui.write(self.tr("app.vmenu_removed"))
            return

        if cmd == "snake":
            self.snake.start()
            return

        if cmd in {"ahorcado1", "hangman1"}:
            self.hangman.start_single_player()
            return

        if cmd in {"ahorcado2", "hangman2"}:
            self.hangman.start_two_player()
            return

        if cmd in {"historia", "story"}:
            self.story.start()
            return

        if cmd in {"gato", "tictactoe", "ttt"}:
            self.tictactoe.start()
            return

        if cmd in {"codigo", "codebreaker", "mastermind"}:
            self.codebreaker.start()
            return

        if cmd in {"physics", "lab", "physicslab"}:
            self.physics_lab.start()
            return

        if cmd in {"roguelike", "rogelike", "rogue", "dungeon"}:
            self.roguelike.start()
            return

        if cmd in {"opciones", "options", "opcoes"}:
            self.ui.write(self._options_text())
            return

        if cmd in {"doctor", "diag", "diagnostic"}:
            self._handle_doctor(args)
            return

        if cmd == "modsreload":
            self._handle_mods(["reload"])
            return

        if cmd == "mods":
            self._handle_mods(args)
            return

        if cmd in {"logros", "achievements", "ach"}:
            self._show_achievements()
            return

        if cmd == "slots":
            self._show_slots()
            return

        if cmd == "slot":
            self._switch_slot(args)
            return

        if cmd == "slotname":
            self._rename_slot(args)
            return

        if cmd == "savegame":
            self._save_current_slot(user_feedback=True)
            return

        if cmd == "syster":
            self._handle_syster(args)
            return

        if cmd in {"creator", "orion", "gethes"}:
            self._trigger_secret(cmd)
            return

        if cmd == "sound":
            self._set_sound(args)
            return

        if cmd == "graphics":
            self._set_graphics(args)
            return

        if cmd in {"uiscale", "ui-scale", "scaleui"}:
            self._set_ui_scale(args)
            return

        if cmd == "theme":
            self._set_theme(args)
            return

        if cmd == "bg":
            self._set_single_color(args, key="bg")
            return

        if cmd == "fg":
            self._set_single_color(args, key="fg")
            return

        if cmd == "font":
            self._set_font(args)
            return

        if cmd == "fonts":
            self._list_fonts(args)
            return

        if cmd in {"lang", "language", "idioma", "lingua"}:
            self._set_language(args)
            return

        if cmd in {"update", "actualizar", "atualizar"}:
            self._handle_update(args)
            return

        if cmd == "sfx":
            self._handle_sfx(args)
            return

        if cmd == "save":
            self._save_config()
            self.ui.write(self.tr("app.config_saved"))
            return

        if cmd in {"exit", "salir", "sair", "quit"}:
            self._shutdown()
            self.ui.request_quit()
            return

        suggestion = self._suggest_command_alias(cmd)
        if suggestion:
            self.ui.write(self.tr("app.unknown_suggest", cmd=cmd, suggestion=suggestion))
        else:
            self.ui.write(self.tr("app.unknown", cmd=cmd))

    @staticmethod
    def _known_command_aliases() -> set[str]:
        return {
            "help",
            "ayuda",
            "ajuda",
            "?",
            "clear",
            "cls",
            "menu",
            "inicio",
            "home",
            "vmenu",
            "menuui",
            "visualmenu",
            "snake",
            "ahorcado1",
            "hangman1",
            "ahorcado2",
            "hangman2",
            "historia",
            "story",
            "gato",
            "tictactoe",
            "ttt",
            "codigo",
            "codebreaker",
            "mastermind",
            "physics",
            "lab",
            "physicslab",
            "roguelike",
            "rogelike",
            "rogue",
            "dungeon",
            "opciones",
            "options",
            "opcoes",
            "doctor",
            "diag",
            "diagnostic",
            "modsreload",
            "mods",
            "logros",
            "achievements",
            "ach",
            "slots",
            "slot",
            "slotname",
            "savegame",
            "syster",
            "creator",
            "orion",
            "gethes",
            "sound",
            "graphics",
            "uiscale",
            "ui-scale",
            "scaleui",
            "theme",
            "bg",
            "fg",
            "font",
            "fonts",
            "lang",
            "language",
            "idioma",
            "lingua",
            "update",
            "actualizar",
            "atualizar",
            "sfx",
            "save",
            "exit",
            "salir",
            "sair",
            "quit",
        }

    def _suggest_command_alias(self, cmd: str) -> str:
        token = cmd.strip().lower()
        if not token:
            return ""

        aliases = sorted(self._known_command_aliases())
        if token in aliases:
            return ""

        if rapid_process is not None:
            hit = rapid_process.extractOne(
                token,
                aliases,
                score_cutoff=74,
            )
            if hit is not None:
                return str(hit[0])

        fallback = get_close_matches(token, aliases, n=1, cutoff=0.74)
        if fallback:
            return fallback[0]
        return ""

    def _queue_syster_auto_from_command(self, cmd: str) -> None:
        if not self.syster_enabled:
            return
        if self.syster.mode == "off":
            return
        if cmd in {"syster", "save", "savegame", "exit", "salir", "sair", "quit"}:
            return

        self.syster_commands_since_auto += 1
        if self.syster_commands_since_auto >= 2:
            self.syster_commands_since_auto = 0
            self.syster_auto_pending = True

    def _update_syster_autochat(self) -> None:
        if not self.syster_enabled:
            return
        if not self.syster_auto_pending:
            return
        if self._trigger_syster_auto("command"):
            self.syster_auto_pending = False

    def _syster_auto_prompt(self, trigger: str) -> str:
        if trigger == "boot":
            return "hola"
        if trigger == "idle":
            return "help"

        cmd = self.last_command
        if cmd in {
            "snake",
            "ahorcado1",
            "ahorcado2",
            "gato",
            "tictactoe",
            "codigo",
            "codebreaker",
            "physics",
            "roguelike",
            "rogelike",
            "rogue",
            "dungeon",
        }:
            return "games"
        if cmd in {"options", "opciones", "theme", "graphics", "sound", "lang", "uiscale"}:
            return "settings"
        if cmd in {"historia", "story"}:
            return "story"
        if cmd in {"sfx"}:
            return "audio"
        if cmd in {"update", "actualizar", "atualizar"}:
            return "update"
        return "help"

    def _trigger_syster_auto(self, trigger: str) -> bool:
        if not self.syster_enabled:
            return False
        if self.syster.mode == "off":
            return False
        if (
            self.intro_active
            or self.boot_active
            or self.snake.active
            or self.physics_lab.active
            or self.roguelike.active
            or self.input_handler is not None
        ):
            return False

        now = time.monotonic()
        if trigger != "boot" and (now - self.syster_last_auto_ts) < self.syster_auto_cooldown:
            return False

        prompt = self._syster_auto_prompt(trigger)
        reply = self.syster.reply(
            prompt,
            lambda key, **kwargs: self.tr(key, **kwargs),
            context=self._build_syster_context(),
        )
        if not reply.strip():
            return False

        self.ui.write(self.tr("app.syster.prefix"), play_sound=False)
        self.ui.write(reply)
        self.audio.play("message")
        self.syster_last_auto_ts = now
        return True

    def _handle_syster(self, args: list[str]) -> None:
        if not self.syster_enabled:
            self.ui.write(self.tr("app.syster.temporarily_disabled"))
            return

        if not args:
            self.ui.write(
                self.tr(
                    "app.syster.status",
                    mode=self.syster.mode,
                )
            )
            remote_status = (
                self.tr("app.syster.remote.on")
                if self.syster.has_remote_endpoint()
                else self.tr("app.syster.remote.off")
            )
            self.ui.write(self.tr("app.syster.remote_status", status=remote_status))
            self.ui.write(self.tr("app.syster.usage"))
            return

        action = args[0].lower()
        if action == "mode":
            if len(args) != 2:
                self.ui.write(self.tr("app.syster.mode_usage"))
                return
            mode = args[1].lower()
            if mode not in SYSTER_MODES:
                self.ui.write(self.tr("app.syster.mode_invalid"))
                return
            self.syster.set_mode(mode)
            self.config.syster_mode = mode
            self._save_config()
            self.ui.write(self.tr("app.syster.mode_set", mode=mode))
            if mode == "hybrid" and not self.syster.has_remote_endpoint():
                self.ui.write(self.tr("app.syster.hybrid_fallback"))
            return

        if action == "endpoint":
            if len(args) == 1:
                value = self.syster.remote_endpoint or "-"
                self.ui.write(self.tr("app.syster.endpoint_status", value=value))
                return

            endpoint = " ".join(args[1:]).strip()
            if endpoint.lower() in {"off", "none", "reset", "clear"}:
                self.syster.set_remote_endpoint(None)
                self.config.syster_endpoint = ""
                self._save_config()
                self.ui.write(self.tr("app.syster.endpoint_cleared"))
                return

            if not endpoint.startswith(("http://", "https://")):
                self.ui.write(self.tr("app.syster.endpoint_invalid"))
                self.ui.write(self.tr("app.syster.endpoint_usage"))
                return

            self.syster.set_remote_endpoint(endpoint)
            self.config.syster_endpoint = endpoint
            self._save_config()
            self.ui.write(self.tr("app.syster.endpoint_set", value=endpoint))
            return

        if action == "secret":
            self._trigger_secret("syster")
            return

        if action == "ask":
            if len(args) < 2:
                self.ui.write(self.tr("app.syster.ask_usage"))
                return
            prompt = " ".join(args[1:])
        else:
            prompt = " ".join(args)

        reply = self.syster.reply(
            prompt,
            lambda key, **kwargs: self.tr(key, **kwargs),
            context=self._build_syster_context(),
        )
        self.ui.write(self.tr("app.syster.prefix"))
        self.ui.write(reply)
        self.audio.play("message")

    def _build_syster_context(self) -> SysterContext:
        return SysterContext(
            slot_id=self.current_slot.slot_id,
            route_name=self.current_slot.route_name,
            story_page=self.current_slot.story_page,
            story_total=self.current_slot.story_total,
            achievements_unlocked=unlocked_count(self.current_slot.flags),
            achievements_total=len(ACHIEVEMENTS),
            last_command=self.last_command,
        )

    def _trigger_secret(self, token: str) -> None:
        self.ui.trigger_glitch()
        if token == "syster":
            self.current_slot.flags["secret_syster"] = True
            self.ui.write(self.tr("app.secret.syster"))
        elif token in {"creator", "orion"}:
            self.current_slot.flags["secret_creator"] = True
            self.ui.write(self.tr("app.secret.creator"))
        else:
            self.current_slot.flags["secret_gethes"] = True
            self.ui.write(self.tr("app.secret.gethes"))
        if any(
            self.current_slot.flags.get(flag, False)
            for flag in ("secret_syster", "secret_creator", "secret_gethes")
        ):
            self._unlock_achievement("secret_echo")
        self.ui.set_status(self.tr("app.secret.status"))
        self.audio.play("secret")
        self._save_current_slot(user_feedback=False)

    def _handle_doctor(self, args: list[str]) -> None:
        section = args[0].strip().lower() if args else "all"
        if section not in {"all", "audio", "sfx", "update", "ui", "system"}:
            self.ui.write(self.tr("app.doctor.usage"))
            return

        self.ui.write(self.tr("app.doctor.title"))
        self.ui.write(
            self.tr(
                "app.doctor.core",
                version=__version__,
                slot=self.current_slot.slot_id,
                route=self.current_slot.route_name,
                language=self.i18n.active_language,
            )
        )

        if section in {"all", "ui", "system"}:
            width, height = self.ui.get_window_size()
            ui_user, ui_responsive, ui_effective = self.ui.get_scale_snapshot()
            self.ui.write(
                self.tr(
                    "app.doctor.ui",
                    width=width,
                    height=height,
                    fullscreen=("ON" if self.ui.is_fullscreen() else "OFF"),
                    ui_user=f"{ui_user:.2f}",
                    ui_responsive=f"{ui_responsive:.2f}",
                    ui_effective=f"{ui_effective:.2f}",
                    fps=self.ui.get_target_fps(),
                )
            )

        if section in {"all", "audio", "sfx"}:
            self._handle_sfx_doctor()

        if section in {"all", "update"}:
            self._show_update_status()

        if section in {"all", "system"}:
            self.ui.write(self.tr("app.doctor.paths", storage=str(self.storage_dir), updates=str(self.update_download_dir)))

    def _handle_sfx(self, args: list[str]) -> None:
        if not args:
            self._show_sfx_status()
            self.ui.write(self.tr("app.sfx.usage"))
            return

        action = args[0].lower()
        payload = args[1:]

        if action in {"status", "state"}:
            self._show_sfx_status()
            return
        if action == "key":
            self._handle_sfx_key(payload)
            return
        if action == "search":
            self._handle_sfx_search(payload)
            return
        if action == "bind":
            self._handle_sfx_bind(payload)
            return
        if action == "reset":
            self._handle_sfx_reset(payload)
            return
        if action == "test":
            self._handle_sfx_test(payload)
            return
        if action in {"doctor", "diag", "debug"}:
            self._handle_sfx_doctor()
            return

        self.ui.write(self.tr("app.sfx.usage"))

    def _show_sfx_status(self) -> None:
        loaded = ", ".join(self.audio.loaded_events()) or "-"
        events = ", ".join(self.audio.available_events())
        provider = "ON" if self.sfx_service.is_dependency_available() else "OFF"
        overrides_count = len(self.config.sfx_overrides)

        self.ui.write(self.tr("app.sfx.status", status=self.audio.describe_status()))
        self.ui.write(self.tr("app.sfx.backend", value=self.audio.backend()))
        self.ui.write(self.tr("app.sfx.assets", path=str(self.assets_dir)))
        self.ui.write(self.tr("app.sfx.custom_dir", path=str(self.user_sfx_dir)))
        self.ui.write(self.tr("app.sfx.provider", value=provider))
        self.ui.write(self.tr("app.sfx.key_status", value=self.sfx_service.masked_key()))
        self.ui.write(self.tr("app.sfx.overrides", count=overrides_count))
        self.ui.write(self.tr("app.sfx.events", events=events))
        self.ui.write(self.tr("app.sfx.loaded", events=loaded))

        if self.config.sfx_overrides:
            items = ", ".join(
                f"{event}:{name}" for event, name in sorted(self.config.sfx_overrides.items())
            )
            self.ui.write(self.tr("app.sfx.override_items", items=items))

        loaded_files = self.audio.loaded_files()
        if loaded_files:
            items = ", ".join(f"{event}:{name}" for event, name in sorted(loaded_files.items()))
            self.ui.write(self.tr("app.sfx.loaded_files", items=items))

    def _handle_sfx_doctor(self) -> None:
        self._show_sfx_status()
        self.ui.write(self.tr("app.sfx.doctor_title"))
        loaded = set(self.audio.loaded_events())
        critical_events = {"intro", "typing", "message", "error", "achievement"}
        missing_critical = []
        for event in self.audio.available_events():
            if event in loaded:
                state = "OK"
            elif event in critical_events:
                state = "!!"
                missing_critical.append(event)
            else:
                state = "--"
            source = self.audio.source_path_for_event(event)
            self.ui.write(self.tr("app.sfx.doctor_item", state=state, event=event, source=source))
        if missing_critical:
            self.ui.write(
                self.tr(
                    "app.sfx.doctor_missing_critical",
                    events=", ".join(sorted(missing_critical)),
                )
            )
        if not self.audio.mixer_ready:
            self.ui.write(self.tr("app.sfx.doctor_mixer_off"))
        elif not loaded:
            self.ui.write(self.tr("app.sfx.doctor_no_events"))

    def _handle_sfx_key(self, args: list[str]) -> None:
        if len(args) != 1:
            self.ui.write(self.tr("app.sfx.key_usage"))
            return

        value = args[0].strip()
        if not value:
            self.ui.write(self.tr("app.sfx.key_usage"))
            return

        if value.lower() in {"off", "none", "clear", "reset"}:
            self.sfx_service.clear_api_key()
            self.config.freesound_api_key = ""
            self._save_config()
            self.ui.write(self.tr("app.sfx.key_cleared"))
            return

        if not self.sfx_service.set_api_key(value):
            if not self.sfx_service.is_dependency_available():
                self.ui.write(self.tr("app.sfx.dependency_missing"))
            else:
                self.ui.write(self.tr("app.sfx.key_invalid"))
            return

        self.config.freesound_api_key = value
        self._save_config()
        self.ui.write(self.tr("app.sfx.key_set", value=self.sfx_service.masked_key()))

    def _handle_sfx_search(self, args: list[str]) -> None:
        if not args:
            self.ui.write(self.tr("app.sfx.search_usage"))
            return

        query = " ".join(args).strip()
        if not query:
            self.ui.write(self.tr("app.sfx.search_usage"))
            return

        if not self.sfx_service.is_dependency_available():
            self.ui.write(self.tr("app.sfx.dependency_missing"))
            return
        if not self.sfx_service.is_configured():
            self.ui.write(self.tr("app.sfx.key_required"))
            return

        self.ui.write(self.tr("app.sfx.searching", query=query))
        results, error_msg = self.sfx_service.search(query=query, limit=6)
        if error_msg:
            self.ui.write(self.tr("app.sfx.search_failed", error=error_msg))
            return
        if not results:
            self.ui.write(self.tr("app.sfx.search_empty"))
            return

        self.ui.write(self.tr("app.sfx.search_title", query=query))
        for item in results:
            self.ui.write(
                self.tr(
                    "app.sfx.search_item",
                    id=item.sound_id,
                    name=item.name[:40],
                    duration=f"{item.duration:.1f}",
                    author=item.username,
                    license=item.license_name,
                )
            )
        self.ui.write(self.tr("app.sfx.search_bind_hint"))

    def _handle_sfx_bind(self, args: list[str]) -> None:
        if len(args) != 2:
            self.ui.write(self.tr("app.sfx.bind_usage"))
            return

        event = self._normalize_sfx_event(args[0])
        if event is None:
            self.ui.write(self.tr("app.sfx.bind_event_invalid"))
            self.ui.write(self.tr("app.sfx.events", events=", ".join(self.audio.available_events())))
            return

        try:
            sound_id = int(args[1])
        except ValueError:
            self.ui.write(self.tr("app.sfx.bind_id_invalid"))
            return
        if sound_id <= 0:
            self.ui.write(self.tr("app.sfx.bind_id_invalid"))
            return

        if not self.sfx_service.is_dependency_available():
            self.ui.write(self.tr("app.sfx.dependency_missing"))
            return
        if not self.sfx_service.is_configured():
            self.ui.write(self.tr("app.sfx.key_required"))
            return

        previous_override = self.config.sfx_overrides.get(event)
        last_error = "unknown"
        for file_format in ("ogg", "mp3"):
            self.ui.write(
                self.tr(
                    "app.sfx.bind_downloading_fmt",
                    event=event,
                    id=sound_id,
                    fmt=file_format,
                )
            )
            target_name = f"{event}_{sound_id}.{file_format}"
            downloaded, error_msg = self.sfx_service.download_preview(
                sound_id=sound_id,
                output_dir=self.user_sfx_dir,
                target_name=target_name,
                quality="lq",
                file_format=file_format,
            )
            if downloaded is None or error_msg:
                last_error = error_msg or "download_failed"
                continue

            self.config.sfx_overrides[event] = downloaded.name
            self._reload_audio_assets()
            if not self.audio.mixer_ready:
                if previous_override is None:
                    self.config.sfx_overrides.pop(event, None)
                else:
                    self.config.sfx_overrides[event] = previous_override
                self._reload_audio_assets()
                self.ui.write(self.tr("app.sfx.doctor_mixer_off"))
                return
            if event not in self.audio.loaded_events():
                last_error = f"unsupported_{file_format}"
                continue

            self._save_config()
            self.ui.write(self.tr("app.sfx.bind_done", event=event, file=downloaded.name))
            self.audio.play(event)
            return

        if previous_override is None:
            self.config.sfx_overrides.pop(event, None)
        else:
            self.config.sfx_overrides[event] = previous_override
        self._reload_audio_assets()
        self.ui.write(self.tr("app.sfx.bind_failed", error=last_error))

    def _handle_sfx_reset(self, args: list[str]) -> None:
        if len(args) != 1:
            self.ui.write(self.tr("app.sfx.reset_usage"))
            return

        target = args[0].lower()
        if target == "all":
            self.config.sfx_overrides = {}
            self._reload_audio_assets()
            self._save_config()
            self.ui.write(self.tr("app.sfx.reset_done_all"))
            return

        event = self._normalize_sfx_event(target)
        if event is None:
            self.ui.write(self.tr("app.sfx.bind_event_invalid"))
            self.ui.write(self.tr("app.sfx.events", events=", ".join(self.audio.available_events())))
            return

        self.config.sfx_overrides.pop(event, None)
        self._reload_audio_assets()
        self._save_config()
        self.ui.write(self.tr("app.sfx.reset_done_one", event=event))

    def _handle_sfx_test(self, args: list[str]) -> None:
        if len(args) != 1:
            self.ui.write(self.tr("app.sfx.test_usage"))
            return

        event = self._normalize_sfx_event(args[0])
        if event is None:
            self.ui.write(self.tr("app.sfx.bind_event_invalid"))
            self.ui.write(self.tr("app.sfx.events", events=", ".join(self.audio.available_events())))
            return

        if event not in self.audio.loaded_events():
            self.ui.write(self.tr("app.sfx.test_missing", event=event))
            return

        self.audio.play(event)
        self.ui.write(self.tr("app.sfx.test_done", event=event))

    def _normalize_sfx_event(self, raw_event: str) -> str | None:
        token = raw_event.strip().lower()
        if token in self.audio.available_events():
            return token
        alias = SFX_EVENT_ALIASES.get(token)
        if alias and alias in self.audio.available_events():
            return alias
        return None

    def _show_achievements(self) -> None:
        unlocked = unlocked_count(self.current_slot.flags)
        total = len(ACHIEVEMENTS)
        self.ui.write(self.tr("app.achievements.title", unlocked=unlocked, total=total))
        for item in ACHIEVEMENTS:
            done = is_unlocked(self.current_slot.flags, item.achievement_id)
            if not done and item.hidden:
                title = self.tr("achievement.hidden.title")
                desc = self.tr("achievement.hidden.desc")
            else:
                title = self.tr(item.title_key)
                desc = self.tr(item.desc_key)
            mark = "[OK]" if done else "[--]"
            self.ui.write(f"{mark} {title} - {desc}")

    def _unlock_achievement(self, achievement_id: str) -> None:
        item = BY_ID.get(achievement_id)
        if item is None:
            return

        flag_key = f"achv_{achievement_id}"
        if self.current_slot.flags.get(flag_key):
            return

        self.current_slot.flags[flag_key] = True
        title = self.tr(item.title_key)
        self.ui.write(self.tr("app.achievements.unlocked", title=title), play_sound=False)
        self.ui.push_notification(
            self.tr("ui.achievement_unlocked"),
            title,
            icon_key="mdi:trophy-outline",
        )
        self.audio.play("achievement")
        self._notify_theme_unlocks(achievement_id)
        self._save_current_slot(user_feedback=False)

    def _show_slots(self) -> None:
        self.ui.write(self.tr("app.slots.title"))
        for slot in self.save_manager.list_slots():
            is_current = slot.slot_id == self.current_slot.slot_id
            prefix = ">" if is_current else "-"
            self.ui.write(
                self.tr(
                    "app.slots.item",
                    prefix=prefix,
                    id=slot.slot_id,
                    route=slot.route_name,
                    story=slot.story_page,
                    total=slot.story_total,
                    updated=slot.updated_at,
                )
            )

    def _switch_slot(self, args: list[str]) -> None:
        if len(args) != 1:
            self.ui.write(self.tr("app.slot.usage"))
            return

        if not args[0].isdigit():
            self.ui.write(self.tr("app.slot.invalid"))
            return

        slot_id = int(args[0])
        if slot_id < 1 or slot_id > self.save_manager.slots:
            self.ui.write(self.tr("app.slot.invalid"))
            return

        self._save_current_slot(user_feedback=False)
        self.current_slot = self.save_manager.load_slot(slot_id)
        self.config.active_slot = slot_id
        self._save_config()
        self.ui.write(
            self.tr(
                "app.slot.changed",
                id=self.current_slot.slot_id,
                route=self.current_slot.route_name,
            )
        )
        self.ui.write(self._options_text())

    def _rename_slot(self, args: list[str]) -> None:
        if not args:
            self.ui.write(self.tr("app.slotname.usage"))
            return

        route_name = " ".join(args).strip()
        if not route_name:
            self.ui.write(self.tr("app.slotname.usage"))
            return

        self.current_slot.route_name = route_name[:42]
        self._save_current_slot(user_feedback=False)
        self.ui.write(
            self.tr(
                "app.slotname.changed",
                id=self.current_slot.slot_id,
                route=self.current_slot.route_name,
            )
        )

    def _save_current_slot(self, user_feedback: bool) -> None:
        self.save_manager.save_slot(self.current_slot)
        if user_feedback:
            self.ui.write(
                self.tr(
                    "app.savegame.done",
                    id=self.current_slot.slot_id,
                    route=self.current_slot.route_name,
                )
            )

    def _set_sound(self, args: list[str]) -> None:
        if len(args) != 1:
            self.ui.write(self.tr("app.sound_usage"))
            return

        value = args[0].lower()
        if value not in {"on", "off"}:
            self.ui.write(self.tr("app.sound_invalid"))
            return

        self.config.sound = value == "on"
        self.audio.set_enabled(self.config.sound)
        self._save_config()
        self.ui.write(
            self.tr(
                "app.sound_status",
                value=("ON" if self.config.sound else "OFF"),
            )
        )

    def _set_graphics(self, args: list[str]) -> None:
        if len(args) != 1:
            self.ui.write(self.tr("app.graphics_usage"))
            return

        value = args[0].lower()
        if value not in GRAPHICS_LEVELS:
            self.ui.write(self.tr("app.graphics_invalid"))
            return

        self.config.graphics = value
        self._apply_performance_config()
        self._save_config()
        self.ui.write(self.tr("app.graphics_updated", value=value))

    def _set_ui_scale(self, args: list[str]) -> None:
        if len(args) != 1:
            self.ui.write(self.tr("app.ui_scale_usage"))
            return

        token = args[0].strip().lower().replace(",", ".")
        preset_values = {
            "small": 0.85,
            "normal": 1.00,
            "large": 1.20,
            "huge": 1.40,
        }
        if token in preset_values:
            value = preset_values[token]
            self.config.ui_scale = value
            self._apply_visual_config()
            self._save_config()
            self.ui.write(self.tr("app.ui_scale_updated", value=f"{value:.2f}x"))
            return

        if token in {"auto", "adaptive", "adapt"}:
            value = self.ui.recommended_user_ui_scale()
            self.config.ui_scale = value
            self._apply_visual_config()
            self._save_config()
            self.ui.write(self.tr("app.ui_scale_auto", value=f"{value:.2f}x"))
            return

        try:
            if token.endswith("%"):
                value = float(token[:-1]) / 100.0
            elif token.endswith("x"):
                value = float(token[:-1])
            else:
                value = float(token)
        except ValueError:
            self.ui.write(self.tr("app.ui_scale_invalid"))
            return

        if value < 0.7 or value > 2.5:
            self.ui.write(self.tr("app.ui_scale_range"))
            return

        self.config.ui_scale = value
        self._apply_visual_config()
        self._save_config()
        self.ui.write(self.tr("app.ui_scale_updated", value=f"{value:.2f}x"))

    def _theme_unlock_title(self, achievement_id: str) -> str:
        token = achievement_id.strip().lower()
        if not token:
            return "-"
        item = BY_ID.get(token)
        if item is None:
            return token
        if item.hidden and not self.current_slot.flags.get(f"achv_{token}", False):
            return self.tr("achievement.hidden.title")
        return self.tr(item.title_key)

    def _is_theme_unlocked(self, theme: ThemePreset) -> bool:
        token = theme.unlock_achievement.strip().lower()
        if not token:
            return True
        return bool(self.current_slot.flags.get(f"achv_{token}", False))

    def _reset_theme_visual_tuning(self) -> None:
        self.config.theme_accent_color = ""
        self.config.theme_panel_color = ""
        self.config.theme_dim_color = ""
        self.config.theme_scan_strength = 1.0
        self.config.theme_glow_strength = 1.0
        self.config.theme_particles_strength = 1.0

    def _apply_theme_preset(self, name: str, theme: ThemePreset) -> None:
        self.config.bg_color = theme.bg
        self.config.fg_color = theme.fg
        self.config.theme_accent_color = theme.accent
        self.config.theme_panel_color = theme.panel
        self.config.theme_dim_color = theme.dim
        self.config.theme_scan_strength = theme.scan_strength
        self.config.theme_glow_strength = theme.glow_strength
        self.config.theme_particles_strength = theme.particle_strength
        self._apply_visual_config()
        self._save_config()
        self.ui.write(self.tr("app.theme_preset_applied", name=name))

    def _notify_theme_unlocks(self, achievement_id: str) -> None:
        token = achievement_id.strip().lower()
        if not token:
            return
        unlocked = [
            name for name, preset in self.theme_presets.items() if preset.unlock_achievement == token
        ]
        if not unlocked:
            return

        if len(unlocked) == 1:
            names_text = unlocked[0]
        else:
            names_text = ", ".join(unlocked[:3])
            if len(unlocked) > 3:
                names_text = f"{names_text}, +{len(unlocked) - 3}"

        self.ui.write(self.tr("app.theme_unlock_message", themes=names_text))
        self.ui.push_notification(
            self.tr("app.theme_unlock_title"),
            self.tr("app.theme_unlock_toast", themes=names_text),
            icon_key="mdi:trophy-outline",
        )

    def _set_theme(self, args: list[str]) -> None:
        if not args:
            self.ui.write(self.tr("app.theme_usage"))
            return

        if len(args) == 1:
            token = args[0].lower()
            if token in {"list", "ls"}:
                self._show_theme_list()
                return
            if token in {"reload", "mods"}:
                count = self._reload_theme_presets()
                self.ui.write(self.tr("app.theme_reloaded", count=count))
                self.ui.write(self.tr("app.theme_mod_path", path=str(self.theme_mods_dir)))
                return

            theme = self.theme_presets.get(token)
            if theme is None:
                self.ui.write(self.tr("app.theme_invalid"))
                self._show_theme_list()
                return

            if not self._is_theme_unlocked(theme):
                self.ui.write(
                    self.tr(
                        "app.theme_locked",
                        name=token,
                        achievement=self._theme_unlock_title(theme.unlock_achievement),
                    )
                )
                return

            self._apply_theme_preset(token, theme)
            return

        if len(args) != 2:
            self.ui.write(self.tr("app.theme_usage"))
            return

        bg, fg = args
        if not self.ui.is_valid_color(bg):
            self.ui.write(self.tr("app.bg_invalid", color=bg))
            return
        if not self.ui.is_valid_color(fg):
            self.ui.write(self.tr("app.fg_invalid", color=fg))
            return

        self.config.bg_color = bg
        self.config.fg_color = fg
        self._reset_theme_visual_tuning()
        self._apply_visual_config()
        self._save_config()
        self.ui.write(self.tr("app.theme_updated", bg=bg, fg=fg))

    def _show_theme_list(self) -> None:
        self.ui.write(self.tr("app.theme_list_title"))
        active = self._detect_theme_name(self.config.bg_color, self.config.fg_color)
        self.ui.write(self.tr("app.theme_mod_path", path=str(self.theme_mods_dir)))
        for name, preset in self.theme_presets.items():
            locked = not self._is_theme_unlocked(preset)
            mark = ">" if name == active else ("x" if locked else "-")
            self.ui.write(
                self.tr(
                    "app.theme_list_item",
                    mark=mark,
                    name=name,
                    bg=preset.bg,
                    fg=preset.fg,
                )
            )
            lock_text = self.tr("app.theme_unlock_open")
            if locked:
                lock_text = self.tr(
                    "app.theme_unlock_need",
                    achievement=self._theme_unlock_title(preset.unlock_achievement),
                )
            self.ui.write(
                self.tr(
                    "app.theme_list_fx",
                    accent=(preset.accent or "auto"),
                    scan=f"{preset.scan_strength:.2f}",
                    glow=f"{preset.glow_strength:.2f}",
                    particles=f"{preset.particle_strength:.2f}",
                    lock=lock_text,
                )
            )

    def _detect_theme_name(self, bg: str, fg: str) -> str:
        cfg_accent = self.config.theme_accent_color.strip().lower()
        cfg_panel = self.config.theme_panel_color.strip().lower()
        cfg_dim = self.config.theme_dim_color.strip().lower()
        for name, preset in self.theme_presets.items():
            if preset.bg.lower() != bg.lower() or preset.fg.lower() != fg.lower():
                continue
            if preset.accent.strip().lower() != cfg_accent:
                continue
            if preset.panel.strip().lower() != cfg_panel:
                continue
            if preset.dim.strip().lower() != cfg_dim:
                continue
            if abs(float(preset.scan_strength) - float(self.config.theme_scan_strength)) > 0.001:
                continue
            if abs(float(preset.glow_strength) - float(self.config.theme_glow_strength)) > 0.001:
                continue
            if (
                abs(float(preset.particle_strength) - float(self.config.theme_particles_strength))
                > 0.001
            ):
                continue
            return name
        return "custom"

    def _set_single_color(self, args: list[str], key: str) -> None:
        if len(args) != 1:
            self.ui.write(self.tr("app.color_usage", key=key))
            return

        color = args[0]
        if not self.ui.is_valid_color(color):
            self.ui.write(self.tr("app.color_invalid", color=color))
            return

        if key == "bg":
            self.config.bg_color = color
        else:
            self.config.fg_color = color

        self._reset_theme_visual_tuning()
        self._apply_visual_config()
        self._save_config()
        self.ui.write(self.tr("app.color_updated", key=key, color=color))

    def _set_font(self, args: list[str]) -> None:
        if not args:
            self.ui.write(self.tr("app.font_usage"))
            return

        size = self.config.font_size
        family_parts = args

        if args[-1].isdigit():
            size = int(args[-1])
            family_parts = args[:-1]

        if not family_parts:
            self.ui.write(self.tr("app.font_missing_family"))
            return

        if size < 8 or size > 42:
            self.ui.write(self.tr("app.font_invalid_size"))
            return

        requested_family = " ".join(family_parts)
        resolved_family = self._resolve_font_family(requested_family)
        if resolved_family is None:
            self.ui.write(self.tr("app.font_not_found"))
            return

        self.config.font_family = resolved_family
        self.config.font_size = size
        self._apply_visual_config()
        self._save_config()
        self.ui.write(self.tr("app.font_updated", family=resolved_family, size=size))

    def _list_fonts(self, args: list[str]) -> None:
        text_filter = " ".join(args) if args else ""
        families = self.ui.available_fonts(text_filter=text_filter)
        if not families:
            self.ui.write(self.tr("app.fonts_empty"))
            return

        shown = families[:30]
        self.ui.write(self.tr("app.fonts_title"))
        for family in shown:
            self.ui.write(f"- {family}")
        if len(families) > len(shown):
            self.ui.write(self.tr("app.fonts_more", count=(len(families) - len(shown))))

    def _set_language(self, args: list[str]) -> None:
        if not args:
            self.ui.write(
                self.tr(
                    "app.language_current",
                    mode=self.config.language,
                    active=self.i18n.active_language,
                )
            )
            return

        if len(args) != 1:
            self.ui.write(self.tr("app.language_usage"))
            return

        mode = args[0].lower()
        if mode not in LANGUAGE_MODES:
            self.ui.write(self.tr("app.language_invalid"))
            return

        self.config.language = mode
        self.i18n.set_mode(mode)
        self.story.reload_for_language()
        self._refresh_ui_language()
        self._save_config()
        self.ui.write(
            self.tr(
                "app.language_changed",
                mode=self.config.language,
                active=self.i18n.active_language,
            )
        )
        self.ui.write(self._options_text())

    def _handle_update(self, args: list[str]) -> None:
        if not args:
            self._show_update_status()
            self.ui.write(self.tr("app.update.usage"))
            return

        action = args[0].lower()
        payload = args[1:]
        if action in {"status", "info"}:
            self._show_update_status()
            return

        if action == "notes":
            self._show_update_notes()
            return

        if action == "check":
            self._start_update_check(user_feedback=True)
            return

        if action == "install":
            require_checksum = self._parse_update_checksum_policy(payload)
            if require_checksum is None:
                self.ui.write(self.tr("app.update.usage"))
                return
            self._start_update_install(require_checksum=require_checksum)
            return

        if action == "prepare":
            require_checksum = self._parse_update_checksum_policy(payload)
            if require_checksum is None:
                self.ui.write(self.tr("app.update.usage"))
                return
            self._start_update_prepare(require_checksum=require_checksum)
            return

        if action == "apply":
            self._start_update_apply_prepared()
            return

        if action == "cancel":
            self._cancel_update_download()
            return

        if action == "repo":
            self._handle_update_repo(args[1:])
            return

        if action == "auto":
            self._handle_update_auto(args[1:])
            return

        self.ui.write(self.tr("app.update.usage"))

    @staticmethod
    def _parse_update_checksum_policy(args: list[str]) -> bool | None:
        if not args:
            return True
        token = args[0].strip().lower()
        if token in {"strict", "safe", "secure"}:
            return True
        if token in {"unsafe", "--unsafe", "nochecksum", "no-checksum", "insecure"}:
            return False
        return None

    def _handle_update_repo(self, args: list[str]) -> None:
        if not args:
            repo = self.update_manager.repo or "-"
            self.ui.write(self.tr("app.update.repo_status", repo=repo))
            return

        token = " ".join(args).strip()
        if token.lower() in {"off", "none", "clear", "reset"}:
            self.update_manager.clear_repo()
            self.config.update_repo = ""
            self._save_config()
            self.ui.write(self.tr("app.update.repo_cleared"))
            return

        if not self.update_manager.set_repo(token):
            self.ui.write(self.tr("app.update.repo_invalid"))
            return

        self.config.update_repo = self.update_manager.repo
        self._save_config()
        self.ui.write(self.tr("app.update.repo_set", repo=self.update_manager.repo))

    def _handle_update_auto(self, args: list[str]) -> None:
        if not args:
            state = "ON" if self.config.auto_update_check else "OFF"
            self.ui.write(self.tr("app.update.auto_status", value=state))
            return

        if len(args) != 1:
            self.ui.write(self.tr("app.update.auto_usage"))
            return

        token = args[0].lower()
        if token not in {"on", "off"}:
            self.ui.write(self.tr("app.update.auto_usage"))
            return

        self.config.auto_update_check = token == "on"
        self._save_config()
        self.ui.write(
            self.tr(
                "app.update.auto_set",
                value=("ON" if self.config.auto_update_check else "OFF"),
            )
        )

    def _show_update_status(self) -> None:
        self.ui.write(self.tr("app.update.status_title"))
        repo = self.update_manager.repo or "-"
        self.ui.write(self.tr("app.update.repo_status", repo=repo))
        self.ui.write(self.tr("app.update.current_version", version=__version__))
        self.ui.write(
            self.tr(
                "app.update.auto_status",
                value=("ON" if self.config.auto_update_check else "OFF"),
            )
        )
        if self.prepared_update_path is not None and self.prepared_update_path.exists():
            self.ui.write(
                self.tr(
                    "app.update.prepared_status",
                    version=(self.prepared_update_version or "-"),
                    method=(self.prepared_update_method or "-"),
                    path=str(self.prepared_update_path),
                )
            )
            self.ui.write(self.tr("app.update.prepared_hint"))

        if self.pending_update is None:
            self.ui.write(self.tr("app.update.status_none"))
            return

        self.ui.write(
            self.tr(
                "app.update.status_available",
                version=self.pending_update.latest_version,
            )
        )
        self.ui.write(
            self.tr(
                "app.update.status_release",
                name=(self.pending_update.release_name or self.pending_update.tag_name),
            )
        )
        self.ui.write(self.tr("app.update.install_hint"))

    def _show_update_notes(self) -> None:
        if self.pending_update is None:
            self.ui.write(self.tr("app.update.notes_none"))
            return

        title = self.pending_update.release_name or self.pending_update.tag_name
        self.ui.write(self.tr("app.update.notes_title", name=title))
        notes = self.pending_update.release_notes.strip()
        if not notes:
            self.ui.write(self.tr("app.update.notes_empty"))
            return
        for raw_line in notes.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            self.ui.write(self.tr("app.update.notes_line", line=line))

    def _cancel_update_download(self) -> None:
        if not self.update_install_running or self.update_cancel_event is None:
            self.ui.write(self.tr("app.update.cancel_idle"))
            return
        self.update_install_after_check = False
        self.update_prepare_after_check = False
        self.update_cancel_event.set()
        self.ui.write(self.tr("app.update.cancel_request"))

    def _start_update_check(self, user_feedback: bool) -> None:
        if self.update_check_running or self.update_install_running:
            if user_feedback:
                self.ui.write(self.tr("app.update.busy"))
            return

        if not self.update_manager.has_repo():
            if user_feedback:
                self.ui.write(self.tr("app.update.repo_missing"))
                self.ui.write(self.tr("app.update.repo_hint"))
            return

        self.update_check_running = True
        if user_feedback:
            self.ui.write(self.tr("app.update.checking"))
            self.ui.set_status(self.tr("app.update.status_checking"))

        def worker() -> None:
            status, info = self.update_manager.check_latest()
            self.update_events.put(
                (
                    "check_result",
                    {
                        "status": status,
                        "info": info,
                        "user_feedback": user_feedback,
                    },
                )
            )

        threading.Thread(target=worker, daemon=True, name="gethes-update-check").start()

    def _clear_prepared_update(self) -> None:
        self.prepared_update_path = None
        self.prepared_update_method = ""
        self.prepared_update_version = ""
        self.prepared_update_checksum_status = ""

    def _start_update_prepare(self, require_checksum: bool = True) -> None:
        if self.update_install_running:
            self.ui.write(self.tr("app.update.busy"))
            return

        self.update_install_after_check = False
        if self.pending_update is None:
            self.update_prepare_after_check = True
            self.update_prepare_require_checksum = require_checksum
            self._start_update_check(user_feedback=True)
            return

        if (
            self.prepared_update_path is not None
            and self.prepared_update_path.exists()
            and self.prepared_update_version == self.pending_update.latest_version
        ):
            self.ui.write(
                self.tr(
                    "app.update.prepared_status",
                    version=self.prepared_update_version,
                    method=(self.prepared_update_method or "-"),
                    path=str(self.prepared_update_path),
                )
            )
            self.ui.write(self.tr("app.update.prepared_hint"))
            return

        self._start_update_download(
            self.pending_update,
            preferred_method="auto",
            apply_after_download=False,
            require_checksum=require_checksum,
        )

    def _start_update_apply_prepared(self) -> None:
        if self.update_install_running:
            self.ui.write(self.tr("app.update.busy"))
            return
        if self.prepared_update_path is None:
            self.ui.write(self.tr("app.update.prepared_none"))
            return
        if not self.prepared_update_path.exists():
            self._clear_prepared_update()
            self.ui.write(self.tr("app.update.prepared_missing"))
            return
        if (
            self.pending_update is not None
            and self.prepared_update_version
            and self.prepared_update_version != self.pending_update.latest_version
        ):
            self._clear_prepared_update()
            self.ui.write(self.tr("app.update.prepared_outdated"))
            return

        self.ui.write(self.tr("app.update.prepared_apply"))
        self._apply_downloaded_update(
            downloaded_path=self.prepared_update_path,
            method=self.prepared_update_method or "installer",
            checksum_status=self.prepared_update_checksum_status,
        )

    def _start_update_install(self, require_checksum: bool = True) -> None:
        if self.update_install_running:
            self.ui.write(self.tr("app.update.busy"))
            return

        self.update_prepare_after_check = False
        if self.prepared_update_path is not None and self.prepared_update_path.exists():
            self._start_update_apply_prepared()
            return

        if self.pending_update is None:
            self.update_install_after_check = True
            self.update_install_require_checksum = require_checksum
            self._start_update_check(user_feedback=True)
            return

        self._start_update_download(
            self.pending_update,
            preferred_method="auto",
            apply_after_download=True,
            require_checksum=require_checksum,
        )

    def _runtime_update_target(self) -> tuple[Path, Path] | None:
        if not getattr(sys, "frozen", False):
            return None
        exe_path = Path(sys.executable).resolve()
        app_dir = exe_path.parent
        if not exe_path.exists() or not app_dir.exists():
            return None
        return app_dir, exe_path

    def _choose_update_method(self, update: UpdateInfo, preferred_method: str = "auto") -> str:
        if preferred_method == "portable":
            return "portable" if update.portable_url else "none"
        if preferred_method == "installer":
            return "installer" if update.installer_url else "none"

        target = self._runtime_update_target()
        if target is not None and update.portable_url:
            app_dir, _ = target
            if self.update_manager.can_portable_update(app_dir):
                return "portable"
        if update.installer_url:
            return "installer"
        if update.portable_url:
            return "portable"
        return "none"

    def _start_update_download(
        self,
        update: UpdateInfo,
        preferred_method: str = "auto",
        apply_after_download: bool = True,
        require_checksum: bool = True,
    ) -> None:
        if self.update_install_running:
            self.ui.write(self.tr("app.update.busy"))
            return

        self.update_manager.cleanup_update_artifacts(self.update_download_dir)
        method = self._choose_update_method(update, preferred_method=preferred_method)
        if method == "none":
            self.ui.write(self.tr("app.update.asset_missing"))
            return

        if apply_after_download:
            self._clear_prepared_update()

        self.update_install_running = True
        self.update_cancel_event = threading.Event()
        self.update_downloaded_bytes = 0
        self.update_download_total_bytes = 0
        self.ui.write(
            self.tr(
                "app.update.downloading" if apply_after_download else "app.update.preparing",
                version=update.latest_version,
            )
        )
        self.ui.set_status(self.tr("app.update.status_downloading"))

        def worker() -> None:
            last_emit = 0.0

            def progress(downloaded: int, total: int) -> None:
                nonlocal last_emit
                now = time.monotonic()
                should_emit = (now - last_emit) >= 0.22 or (total > 0 and downloaded >= total)
                if not should_emit:
                    return
                last_emit = now
                self.update_events.put(
                    (
                        "download_progress",
                        {
                            "downloaded": int(downloaded),
                            "total": int(total),
                        },
                    )
                )

            try:
                cached_asset = self.update_manager.find_cached_download(
                    update,
                    self.update_download_dir,
                    method,
                )
                if cached_asset is not None:
                    self.update_events.put(("download_verifying", {}))
                    verified, checksum_status = self.update_manager.verify_asset_checksum(
                        cached_asset,
                        update,
                        self.update_download_dir,
                        cancel_event=self.update_cancel_event,
                        require_checksum=require_checksum,
                    )
                    if verified:
                        self.update_events.put(
                            (
                                "install_downloaded" if apply_after_download else "download_prepared",
                                {
                                    "path": str(cached_asset),
                                    "version": update.latest_version,
                                    "method": method,
                                    "checksum_status": checksum_status,
                                    "cached": True,
                                },
                            )
                        )
                        return
                    if checksum_status == "checksum_missing_required":
                        raise RuntimeError(checksum_status)
                    try:
                        cached_asset.unlink(missing_ok=True)
                    except OSError:
                        pass

                if method == "portable":
                    downloaded = self.update_manager.download_portable_zip(
                        update,
                        self.update_download_dir,
                        progress_callback=progress,
                        cancel_event=self.update_cancel_event,
                    )
                else:
                    downloaded = self.update_manager.download_installer(
                        update,
                        self.update_download_dir,
                        progress_callback=progress,
                        cancel_event=self.update_cancel_event,
                    )

                self.update_events.put(("download_verifying", {}))
                verified, checksum_status = self.update_manager.verify_asset_checksum(
                    downloaded,
                    update,
                    self.update_download_dir,
                    cancel_event=self.update_cancel_event,
                    require_checksum=require_checksum,
                )
                if not verified:
                    raise RuntimeError(checksum_status)

                self.update_events.put(
                    (
                        "install_downloaded" if apply_after_download else "download_prepared",
                        {
                            "path": str(downloaded),
                            "version": update.latest_version,
                            "method": method,
                            "checksum_status": checksum_status,
                            "cached": False,
                        },
                    )
                )
            except RuntimeError as exc:
                self.update_events.put(
                    (
                        "install_failed",
                        {
                            "error": str(exc),
                        },
                    )
                )

        threading.Thread(target=worker, daemon=True, name="gethes-update-install").start()

    def _format_megabytes(self, value: int) -> str:
        if value <= 0:
            return "0.0"
        return f"{(value / (1024 * 1024)):.1f}"

    def _process_update_events(self) -> None:
        while True:
            try:
                event, payload = self.update_events.get_nowait()
            except queue.Empty:
                return

            if event == "check_result":
                self._consume_update_check_result(payload)
                continue

            if event == "install_downloaded":
                self._consume_update_downloaded(payload)
                continue

            if event == "download_prepared":
                self._consume_update_prepared(payload)
                continue

            if event == "install_failed":
                self._consume_update_install_failed(payload)
                continue

            if event == "download_progress":
                self._consume_update_progress(payload)
                continue

            if event == "download_verifying":
                self.ui.set_status(self.tr("app.update.status_verifying"))
                continue

            if event == "mod_change":
                self._consume_mod_change(payload)
                continue

    def _consume_update_progress(self, payload: dict[str, object]) -> None:
        downloaded = int(payload.get("downloaded", 0) or 0)
        total = int(payload.get("total", 0) or 0)
        self.update_downloaded_bytes = max(0, downloaded)
        self.update_download_total_bytes = max(0, total)

        if total > 0:
            percent = min(100, int((downloaded * 100) / total))
            self.ui.set_status(
                self.tr(
                    "app.update.status_progress",
                    percent=percent,
                    downloaded=self._format_megabytes(downloaded),
                    total=self._format_megabytes(total),
                )
            )
        else:
            self.ui.set_status(
                self.tr(
                    "app.update.status_progress_unknown",
                    downloaded=self._format_megabytes(downloaded),
                )
            )

    def _consume_mod_change(self, payload: dict[str, object]) -> None:
        tag = str(payload.get("tag", "")).strip().lower()
        if tag not in {"theme", "story"}:
            return

        now = time.monotonic()
        last = self.mod_reload_times.get(tag, 0.0)
        if (now - last) < 0.35:
            return
        self.mod_reload_times[tag] = now

        if tag == "theme":
            count = self._reload_theme_presets()
            self.ui.push_notification(
                self.tr("app.mods.toast.theme_title"),
                self.tr("app.mods.toast.theme_body", count=count),
                icon_key="mdi:information-outline",
            )
            return

        self.story.reload_for_language()
        self.ui.push_notification(
            self.tr("app.mods.toast.story_title"),
            self.tr("app.mods.toast.story_body"),
            icon_key="mdi:information-outline",
        )

    def _consume_update_check_result(self, payload: dict[str, object]) -> None:
        self.update_check_running = False
        self.ui.set_status(self.tr("ui.ready"))

        status = str(payload.get("status", "invalid_response"))
        info = payload.get("info")
        user_feedback = bool(payload.get("user_feedback", False))
        self.update_last_status = status

        if status == "available" and isinstance(info, UpdateInfo):
            self.pending_update = info
            if (
                self.prepared_update_path is not None
                and self.prepared_update_path.exists()
                and self.prepared_update_version
                and self.prepared_update_version != info.latest_version
            ):
                self._clear_prepared_update()
            if user_feedback:
                self.ui.write(
                    self.tr(
                        "app.update.available",
                        version=info.latest_version,
                        current=info.current_version,
                    )
                )
                self.ui.write(self.tr("app.update.install_hint"))
            else:
                self.ui.push_notification(
                    self.tr("app.update.toast_title"),
                    self.tr("app.update.toast_body", version=info.latest_version),
                    icon_key="mdi:information-outline",
                )
            if self.update_install_after_check:
                self.update_install_after_check = False
                self._start_update_download(
                    info,
                    apply_after_download=True,
                    require_checksum=self.update_install_require_checksum,
                )
            if self.update_prepare_after_check:
                self.update_prepare_after_check = False
                self._start_update_download(
                    info,
                    apply_after_download=False,
                    require_checksum=self.update_prepare_require_checksum,
                )
            return

        if status == "up_to_date":
            if isinstance(info, UpdateInfo):
                self.pending_update = None
            if user_feedback:
                self.ui.write(self.tr("app.update.latest", version=__version__))
            self.update_install_after_check = False
            self.update_prepare_after_check = False
            return

        self.pending_update = None
        if self.update_install_after_check:
            self.update_install_after_check = False
        if self.update_prepare_after_check:
            self.update_prepare_after_check = False

        if not user_feedback:
            return

        if status == "repo_missing":
            self.ui.write(self.tr("app.update.repo_missing"))
            self.ui.write(self.tr("app.update.repo_hint"))
            return
        if status in {"installer_missing", "asset_missing"}:
            self.ui.write(self.tr("app.update.asset_missing"))
            return
        if status == "network_error":
            self.ui.write(self.tr("app.update.network_error"))
            return
        self.ui.write(self.tr("app.update.invalid_response"))

    def _consume_update_prepared(self, payload: dict[str, object]) -> None:
        self.update_install_running = False
        self.update_cancel_event = None
        self.update_downloaded_bytes = 0
        self.update_download_total_bytes = 0
        self.ui.set_status(self.tr("ui.ready"))

        raw_path = payload.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            self.ui.write(self.tr("app.update.prepared_missing"))
            return

        method = str(payload.get("method", "installer")).strip().lower()
        checksum_status = str(payload.get("checksum_status", "")).strip().lower()
        version = str(payload.get("version", "")).strip()
        cached = bool(payload.get("cached", False))
        prepared_path = Path(raw_path)
        if not prepared_path.exists():
            self.ui.write(self.tr("app.update.prepared_missing"))
            return

        self.prepared_update_path = prepared_path
        self.prepared_update_method = method
        self.prepared_update_version = version
        self.prepared_update_checksum_status = checksum_status

        if checksum_status == "checksum_ok":
            self.ui.write(self.tr("app.update.checksum_ok"))
        elif checksum_status in {"checksum_missing", "checksum_missing_required"}:
            self.ui.write(self.tr("app.update.checksum_missing"))

        self.ui.write(
            self.tr(
                "app.update.prepared_done",
                version=(version or "-"),
                method=method,
            )
        )
        if cached:
            self.ui.write(self.tr("app.update.prepared_cached"))
        self.ui.write(self.tr("app.update.prepared_hint"))
        self.ui.push_notification(
            self.tr("app.update.prepared_toast_title"),
            self.tr("app.update.prepared_toast_body", version=(version or "-")),
            icon_key="mdi:information-outline",
        )

    def _consume_update_downloaded(self, payload: dict[str, object]) -> None:
        self.update_install_running = False
        self.update_cancel_event = None
        self.update_downloaded_bytes = 0
        self.update_download_total_bytes = 0

        raw_path = payload.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            self.ui.write(self.tr("app.update.launch_failed"))
            self.ui.set_status(self.tr("ui.ready"))
            return

        method = str(payload.get("method", "installer")).strip().lower()
        checksum_status = str(payload.get("checksum_status", "")).strip().lower()
        downloaded_path = Path(raw_path)
        if not downloaded_path.exists():
            self.ui.write(self.tr("app.update.launch_failed"))
            self.ui.set_status(self.tr("ui.ready"))
            return

        self._apply_downloaded_update(downloaded_path, method=method, checksum_status=checksum_status)

    def _apply_downloaded_update(
        self,
        downloaded_path: Path,
        method: str,
        checksum_status: str,
    ) -> None:
        if checksum_status == "checksum_ok":
            self.ui.write(self.tr("app.update.checksum_ok"))
        elif checksum_status in {"checksum_missing", "checksum_missing_required"}:
            self.ui.write(self.tr("app.update.checksum_missing"))

        if method == "portable":
            target = self._runtime_update_target()
            if target is None:
                self.ui.write(self.tr("app.update.portable_unavailable"))
                if self.pending_update is not None and self.pending_update.installer_url:
                    self.ui.write(self.tr("app.update.fallback_installer"))
                    self._start_update_download(self.pending_update, preferred_method="installer")
                else:
                    self.ui.set_status(self.tr("ui.ready"))
                return

            app_dir, exe_path = target
            launch_status = self.update_manager.launch_portable_self_update(
                zip_path=downloaded_path,
                app_dir=app_dir,
                exe_path=exe_path,
                working_dir=self.update_download_dir,
            )
            if launch_status == "elevation_denied":
                self.ui.write(self.tr("app.update.elevation_denied"))
                self.ui.set_status(self.tr("ui.ready"))
                return

            if launch_status not in {"launched", "launched_elevated"}:
                self.ui.write(self.tr("app.update.portable_unavailable"))
                if self.pending_update is not None and self.pending_update.installer_url:
                    self.ui.write(self.tr("app.update.fallback_installer"))
                    self._start_update_download(self.pending_update, preferred_method="installer")
                else:
                    self.ui.set_status(self.tr("ui.ready"))
                return

            self._clear_prepared_update()
            if launch_status == "launched_elevated":
                self.ui.write(self.tr("app.update.elevation_requested"))
            self.ui.write(self.tr("app.update.applying_portable"))
            self.ui.write(self.tr("app.update.installing_exit"))
            self._shutdown()
            self.ui.request_quit()
            return

        if not self.update_manager.launch_installer(downloaded_path, silent=True):
            self.ui.write(self.tr("app.update.launch_failed"))
            self.ui.set_status(self.tr("ui.ready"))
            return

        self._clear_prepared_update()
        self.ui.write(self.tr("app.update.launching_silent"))
        self.ui.write(self.tr("app.update.installing_exit"))
        self._shutdown()
        self.ui.request_quit()

    def _consume_update_install_failed(self, payload: dict[str, object]) -> None:
        self.update_install_running = False
        self.update_cancel_event = None
        self.update_downloaded_bytes = 0
        self.update_download_total_bytes = 0
        self.ui.set_status(self.tr("ui.ready"))
        error_msg = str(payload.get("error", "")).strip()
        if error_msg == "cancelled":
            self.ui.write(self.tr("app.update.cancelled"))
            return
        if error_msg.startswith("checksum_"):
            self.ui.write(self.tr("app.update.checksum_failed", error=error_msg))
            return
        if error_msg:
            self.ui.write(self.tr("app.update.download_failed", error=error_msg))
        else:
            self.ui.write(self.tr("app.update.download_failed", error="unknown"))

    def _trigger_auto_update_check(self) -> None:
        if self.auto_update_check_done:
            return
        self.auto_update_check_done = True
        if not self.config.auto_update_check:
            return
        if not self.update_manager.has_repo():
            return
        self._start_update_check(user_feedback=False)

    def _resolve_font_family(self, requested: str) -> str | None:
        requested_cf = requested.casefold()
        for family in self.ui.available_fonts():
            if family.casefold() == requested_cf:
                return family
        return None

    def _refresh_ui_language(self) -> None:
        self.ui.set_title(self.tr("ui.title"))
        self.ui.set_header(self.tr("ui.header"))
        self.ui.set_mode_chip(self.tr("ui.version_chip", version=__version__))
        if self.input_handler is None and not self.boot_active and not self.intro_active:
            self.ui.set_status(self.tr("ui.ready"))

    def _reload_audio_assets(self) -> None:
        self.audio.initialize(
            self.assets_dir,
            user_assets_dir=self.user_sfx_dir,
            overrides=self.config.sfx_overrides,
        )
        self.audio.set_enabled(self.config.sound)

    def _apply_visual_config(self) -> None:
        try:
            self.ui.apply_style(
                bg_color=self.config.bg_color,
                fg_color=self.config.fg_color,
                font_family=self.config.font_family,
                font_size=self.config.font_size,
                ui_scale=self.config.ui_scale,
                accent_color=(self.config.theme_accent_color or None),
                panel_color=(self.config.theme_panel_color or None),
                dim_color=(self.config.theme_dim_color or None),
                scan_strength=self.config.theme_scan_strength,
                glow_strength=self.config.theme_glow_strength,
                particle_strength=self.config.theme_particles_strength,
            )
        except Exception:
            self.config = GameConfig()
            self.ui.apply_style(
                bg_color=self.config.bg_color,
                fg_color=self.config.fg_color,
                font_family=self.config.font_family,
                font_size=self.config.font_size,
                ui_scale=self.config.ui_scale,
                accent_color=(self.config.theme_accent_color or None),
                panel_color=(self.config.theme_panel_color or None),
                dim_color=(self.config.theme_dim_color or None),
                scan_strength=self.config.theme_scan_strength,
                glow_strength=self.config.theme_glow_strength,
                particle_strength=self.config.theme_particles_strength,
            )
        self._apply_performance_config()

    def _apply_performance_config(self) -> None:
        self.ui.set_graphics_level(self.config.graphics)

    def _save_config(self) -> None:
        self.config.active_slot = self.current_slot.slot_id
        self.config.syster_mode = self.syster.mode
        self.config.syster_endpoint = self.syster.remote_endpoint
        self.config.update_repo = self.update_manager.repo
        clean_overrides: dict[str, str] = {}
        for event, file_name in self.config.sfx_overrides.items():
            if event not in self.audio.available_events():
                continue
            normalized_name = Path(file_name).name.strip()
            if not normalized_name:
                continue
            clean_overrides[event] = normalized_name
        self.config.sfx_overrides = clean_overrides
        self.config_store.save(self.config)

    def _shutdown(self) -> None:
        self._stop_mod_watcher()
        self._save_current_slot(user_feedback=False)
        self._save_config()

    def _start_intro_sequence(self) -> None:
        self.intro_active = True
        self.boot_active = False
        self.ui.set_entry_enabled(False)
        self.ui.set_status("")
        self.audio.play("intro")
        self.ui.start_intro(title=self.tr("ui.title"), duration=2.7)

    def _start_boot_sequence(self) -> None:
        self.boot_steps = [
            self.tr("app.boot.step.kernel"),
            self.tr("app.boot.step.options"),
            self.tr("app.boot.step.games"),
            self.tr("app.boot.step.story"),
            self.tr("app.boot.step.ui"),
        ]
        self.boot_active = True
        self.boot_completed = 0
        self.boot_timer_ms = 0.0
        self.ui.set_entry_enabled(False)
        self.ui.set_status(self.tr("app.booting"))
        self.ui.set_screen(
            self._boot_text(
                steps=self.boot_steps,
                completed=0,
                current_step=self.tr("app.boot.preparing"),
            )
        )

    def _update_boot(self, dt: float) -> None:
        self.boot_timer_ms += dt * 1000.0
        if self.boot_timer_ms < self._boot_delay_ms():
            return

        self.boot_timer_ms = 0.0
        if self.boot_completed < len(self.boot_steps):
            step = self.boot_steps[self.boot_completed]
            self.boot_completed += 1
            self.ui.set_screen(
                self._boot_text(
                    steps=self.boot_steps,
                    completed=self.boot_completed,
                    current_step=step,
                )
            )
            self.audio.play("tick")
            return

        self.boot_active = False
        self.ui.set_screen(self._welcome_text())
        self.ui.set_status(self.tr("ui.help_hint"))
        self.ui.set_entry_enabled(True)
        self.audio.play("success")
        self._unlock_achievement("boot_sequence")
        self._trigger_syster_auto("boot")
        self._trigger_auto_update_check()

    def _boot_delay_ms(self) -> int:
        delay_by_graphics = {
            "low": 340,
            "medium": 230,
            "high": 150,
        }
        return delay_by_graphics.get(self.config.graphics, 230)

    def _boot_text(self, steps: list[str], completed: int, current_step: str) -> str:
        total = len(steps)
        bar_size = 34
        progress = completed / total if total else 1
        filled = int(progress * bar_size)
        bar = ("#" * filled) + ("-" * (bar_size - filled))
        percent = int(progress * 100)

        lines = [
            self.tr("app.boot.title"),
            "==========================================",
            "",
            f"[{bar}] {percent:3d}%",
            self.tr("app.boot.current", step=current_step),
            "",
            self.tr("app.boot.modules"),
        ]

        for i, step in enumerate(steps, start=1):
            if i <= completed:
                prefix = "[OK] "
            elif i == completed + 1:
                prefix = "[..] "
            else:
                prefix = "[  ] "
            lines.append(f"{prefix}{step}")

        lines.extend(
            [
                "",
                self.tr("app.boot.wait"),
            ]
        )
        return "\n".join(lines)

    def _welcome_text(self) -> str:
        return "\n".join(
            [
                "  ____      _   _                ",
                " / ___| ___| |_| |__   ___  ___  ",
                "| |  _ / _ \\ __| '_ \\ / _ \\/ __| ",
                "| |_| |  __/ |_| | | |  __/\\__ \\ ",
                " \\____|\\___|\\__|_| |_|\\___||___/ ",
                "",
                self.tr("app.welcome.subtitle"),
                self.tr(
                    "app.welcome.slot",
                    id=self.current_slot.slot_id,
                    route=self.current_slot.route_name,
                ),
                "",
                self.tr("app.welcome.quick"),
                "- `snake`",
                "- `ahorcado1` / `ahorcado2`",
                "- `gato` / `tictactoe`",
                "- `codigo` / `codebreaker`",
                "- `physics`",
                "- `roguelike` / `rogue`",
                "- `historia`",
                "",
                self.tr("app.welcome.saves"),
                "- `slots`",
                "- `slot 1|2|3`",
                "- `slotname <nombre>`",
                "- `savegame`",
                "",
                self.tr("app.welcome.help"),
            ]
        )

    def _help_text(self) -> str:
        lines = [
            self.tr("app.help.title"),
            f"- help                     : {self.tr('app.help.help')}",
            f"- clear                    : {self.tr('app.help.clear')}",
            f"- menu                     : {self.tr('app.help.menu')}",
            f"- snake                    : {self.tr('app.help.snake')}",
            f"- ahorcado1 / hangman1     : {self.tr('app.help.hangman1')}",
            f"- ahorcado2 / hangman2     : {self.tr('app.help.hangman2')}",
            f"- gato / tictactoe         : {self.tr('app.help.tictactoe')}",
            f"- codigo / codebreaker     : {self.tr('app.help.codebreaker')}",
            f"- physics                  : {self.tr('app.help.physics')}",
            f"- roguelike / rogue        : {self.tr('app.help.roguelike')}",
            f"- historia / story         : {self.tr('app.help.story')}",
            f"- logros / achievements    : {self.tr('app.help.achievements')}",
            f"- slots                    : {self.tr('app.help.slots')}",
            f"- slot <1-3>               : {self.tr('app.help.slot')}",
            f"- slotname <nombre>        : {self.tr('app.help.slotname')}",
            f"- savegame                 : {self.tr('app.help.savegame')}",
            f"- options / opciones       : {self.tr('app.help.options')}",
            f"- doctor [all|audio|update|ui]: {self.tr('app.help.doctor')}",
            f"- sound <on|off>           : {self.tr('app.help.sound')}",
            f"- graphics <low|medium|high>: {self.tr('app.help.graphics')}",
            f"- uiscale <0.7-2.5|auto|small|normal|large|huge>: {self.tr('app.help.uiscale')}",
            f"- theme <preset|list|reload|bg fg>: {self.tr('app.help.theme')}",
            f"- bg <color>               : {self.tr('app.help.bg')}",
            f"- fg <color>               : {self.tr('app.help.fg')}",
            f"- font <familia> [tamano]  : {self.tr('app.help.font')}",
            f"- fonts [filtro]           : {self.tr('app.help.fonts')}",
            f"- lang [auto|es|en|pt]     : {self.tr('app.help.lang')}",
            f"- update ...               : {self.tr('app.help.update')}",
            f"- mods <status|reload>     : {self.tr('app.help.mods')}",
            f"- sfx                      : {self.tr('app.help.sfx')}",
            f"- save                     : {self.tr('app.help.save')}",
            f"- exit                     : {self.tr('app.help.exit')}",
        ]
        if self.syster_enabled:
            lines.append(f"- syster ...               : {self.tr('app.help.syster')}")
            lines.append(
                f"- syster endpoint <url|off>: {self.tr('app.help.syster_endpoint')}"
            )
        return "\n".join(lines)

    def _options_text(self) -> str:
        active_theme = self._detect_theme_name(self.config.bg_color, self.config.fg_color)
        theme_value = active_theme if active_theme != "custom" else self.tr("app.theme_custom")
        remote_state = "ON" if self.syster.has_remote_endpoint() else "OFF"
        ui_user, ui_responsive, ui_effective = self.ui.get_scale_snapshot()
        return "\n".join(
            [
                self.tr("app.options.title"),
                f"- {self.tr('app.options.slot'):13}: {self.current_slot.slot_id} ({self.current_slot.route_name})",
                f"- {self.tr('app.options.bg'):13}: {self.config.bg_color}",
                f"- {self.tr('app.options.fg'):13}: {self.config.fg_color}",
                f"- {self.tr('app.options.font'):13}: {self.config.font_family}",
                f"- {self.tr('app.options.font_size'):13}: {self.config.font_size}",
                f"- {self.tr('app.options.sound'):13}: {'ON' if self.config.sound else 'OFF'}",
                f"- {self.tr('app.options.audio_backend'):13}: {self.audio.backend()}",
                f"- {self.tr('app.options.graphics'):13}: {self.config.graphics}",
                f"- {self.tr('app.options.fps'):13}: {self.ui.get_target_fps()}",
                f"- {self.tr('app.options.theme'):13}: {theme_value}",
                f"- {self.tr('app.options.theme_fx'):13}: "
                f"scan {self.config.theme_scan_strength:.2f} | "
                f"glow {self.config.theme_glow_strength:.2f} | "
                f"particles {self.config.theme_particles_strength:.2f}",
                f"- {self.tr('app.options.themes_count'):13}: {len(self.theme_presets)}",
                f"- {self.tr('app.options.ui_scale'):13}: {self.config.ui_scale:.2f}x",
                self.tr(
                    "app.options.ui_scale_runtime",
                    user=f"{ui_user:.2f}",
                    responsive=f"{ui_responsive:.2f}",
                    effective=f"{ui_effective:.2f}",
                ),
                f"- {self.tr('app.options.version'):13}: {__version__}",
                f"- {self.tr('app.options.language'):13}: {self.config.language} -> {self.i18n.active_language}",
                f"- {self.tr('app.options.syster'):13}: {self.syster.mode}",
                f"- {self.tr('app.options.syster_remote'):13}: {remote_state}",
                f"- {self.tr('app.options.update_auto'):13}: {'ON' if self.config.auto_update_check else 'OFF'}",
                f"- {self.tr('app.options.update_repo'):13}: {self.update_manager.repo or '-'}",
                f"- {self.tr('app.options.achievements'):13}: {unlocked_count(self.current_slot.flags)}/{len(ACHIEVEMENTS)}",
                f"- {self.tr('app.options.mods_path'):13}: {self.mods_dir}",
                f"- {self.tr('app.options.mods_watch'):13}: {'ON' if self.mod_watcher is not None and self.mod_watcher.is_running() else 'OFF'}",
                f"- {self.tr('app.options.storage'):13}: {self.storage_dir}",
            ]
        )

    def _clamp_slot(self, slot_id: int) -> int:
        return min(max(1, slot_id), self.save_manager.slots)
