from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
import json
import os
import queue
import random
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from gethes import __version__
from gethes.achievements import ACHIEVEMENTS, BY_ID, is_unlocked, unlocked_count
from gethes.application import CommandRouter, DomainSupervisor
from gethes.audio import AudioManager
from gethes.cloud_sync import CloudSyncClient
from gethes.config import (
    GRAPHICS_LEVELS,
    LANGUAGE_MODES,
    SYSTER_MODES,
    THEME_STYLE_MODES,
    ConfigStore,
    GameConfig,
)
from gethes.daily_logic import next_daily_streak, normalize_date_key
from gethes.freesound_sfx import FreesoundSFXService
from gethes.games.codebreaker import CodeBreakerGame
from gethes.games.hangman import HangmanGame
from gethes.games.physics_lab import PhysicsLabGame
from gethes.games.roguelike import RoguelikeGame
from gethes.games.snake import SnakeGame
from gethes.games.tictactoe import TicTacToeGame
from gethes.i18n import I18n
from gethes.domain.resilience import DomainFailureEvent, DomainPolicy, DomainState
from gethes.mod_watcher import ModWatcher
from gethes.runtime_paths import resource_package_dir, user_data_dir
from gethes.schema_validation import validate_theme_payload
from gethes.save_system import SaveManager
from gethes.story.story_mode import StoryMode
from gethes.syster import SysterAssistant, SysterContext
from gethes.syster_memory import SysterKnowledgeStore
from gethes.updater import UpdateInfo, UpdateManager
from gethes.ui import ConsoleUI

try:
    from rapidfuzz import process as rapid_process
except ImportError:  # pragma
    rapid_process = None


@dataclass(frozen=True)
class ThemePreset:
    bg: str
    fg: str
    accent: str = ""
    panel: str = ""
    dim: str = ""
    secondary: str = ""
    style: str = "terminal"
    font_family: str = ""
    scan_strength: float = 1.0
    glow_strength: float = 1.0
    particle_strength: float = 1.0
    unlock_achievement: str = ""


BUILTIN_THEME_PRESETS: dict[str, ThemePreset] = {
    "obsidian": ThemePreset(
        bg="#06080C",
        fg="#D2DCE8",
        accent="#78BDEB",
        panel="#0D141E",
        dim="#6E849A",
        secondary="#182337",
        style="terminal",
        font_family="consolas",
        scan_strength=1.04,
        glow_strength=1.08,
        particle_strength=0.92,
    ),
    "void": ThemePreset(
        bg="#030408",
        fg="#9BB3CF",
        accent="#6EA7D0",
        panel="#09101A",
        dim="#667D95",
        secondary="#16263E",
        style="split_v",
        font_family="lucidaconsole",
        scan_strength=0.82,
        glow_strength=0.9,
        particle_strength=0.7,
    ),
    "deepsea": ThemePreset(
        bg="#04101A",
        fg="#ADE6FF",
        accent="#4BCBFF",
        panel="#0B1A2B",
        dim="#79A9C8",
        secondary="#0B2F59",
        style="grid",
        font_family="consolas",
        scan_strength=1.1,
        glow_strength=1.16,
        particle_strength=1.0,
    ),
    "matrix": ThemePreset(
        bg="#040B07",
        fg="#A6FFB0",
        accent="#6AFF86",
        panel="#091510",
        dim="#65B37B",
        secondary="#17361D",
        style="blueprint",
        font_family="couriernew",
        scan_strength=1.24,
        glow_strength=1.06,
        particle_strength=1.12,
    ),
    "amber": ThemePreset(
        bg="#0C0703",
        fg="#FFD9A2",
        accent="#FFB85A",
        panel="#1B1106",
        dim="#BE8C50",
        secondary="#4A2F13",
        style="diagonal",
        font_family="lucidaconsole",
        scan_strength=0.9,
        glow_strength=0.96,
        particle_strength=0.78,
    ),
    "crimson_archive": ThemePreset(
        bg="#11060A",
        fg="#F8C1CD",
        accent="#FF4D73",
        panel="#1C0A11",
        dim="#AF7A89",
        secondary="#3A1124",
        style="split_h",
        font_family="consolas",
        scan_strength=1.2,
        glow_strength=1.24,
        particle_strength=0.94,
        unlock_achievement="hangman_win",
    ),
    "neon_grid": ThemePreset(
        bg="#05030F",
        fg="#D6C8FF",
        accent="#A66BFF",
        panel="#120B20",
        dim="#9480C8",
        secondary="#2B1C64",
        style="grid",
        font_family="consolas",
        scan_strength=1.3,
        glow_strength=1.3,
        particle_strength=1.24,
        unlock_achievement="snake_score_120",
    ),
    "protocol_ice": ThemePreset(
        bg="#050A11",
        fg="#D4F0FF",
        accent="#7DE2FF",
        panel="#0A1621",
        dim="#85A9C4",
        secondary="#1C4461",
        style="split_h",
        font_family="consolas",
        scan_strength=0.82,
        glow_strength=1.1,
        particle_strength=0.74,
        unlock_achievement="codebreaker_win",
    ),
    "sunken_gold": ThemePreset(
        bg="#090603",
        fg="#FFECC2",
        accent="#FFCC63",
        panel="#171005",
        dim="#C19A64",
        secondary="#4A3111",
        style="diagonal",
        font_family="couriernew",
        scan_strength=0.94,
        glow_strength=1.04,
        particle_strength=0.86,
        unlock_achievement="daily_first_win",
    ),
    "pulse_vector": ThemePreset(
        bg="#050613",
        fg="#D2E3FF",
        accent="#86A3FF",
        panel="#11152B",
        dim="#8F9FD2",
        secondary="#232A59",
        style="split_v",
        font_family="consolas",
        scan_strength=1.28,
        glow_strength=1.22,
        particle_strength=1.16,
        unlock_achievement="daily_streak_3",
    ),
    "companion_dusk": ThemePreset(
        bg="#080A13",
        fg="#DDE2F8",
        accent="#9AAAF0",
        panel="#101428",
        dim="#909BC4",
        secondary="#2A203B",
        style="split_h",
        font_family="lucidaconsole",
        scan_strength=0.78,
        glow_strength=0.95,
        particle_strength=0.66,
        unlock_achievement="story_companion_route",
    ),
    "abyss_protocol": ThemePreset(
        bg="#02040A",
        fg="#CDDFFF",
        accent="#6E9BFF",
        panel="#070D19",
        dim="#7285AF",
        secondary="#1A2445",
        style="terminal",
        font_family="consolas",
        scan_strength=1.22,
        glow_strength=1.25,
        particle_strength=1.18,
        unlock_achievement="rogue_victory",
    ),
    "binary_eclipse": ThemePreset(
        bg="#02050A",
        fg="#DCE8F8",
        accent="#5CE3FF",
        panel="#0A121D",
        dim="#7F97BB",
        secondary="#1A3453",
        style="grid",
        font_family="consolas",
        scan_strength=1.34,
        glow_strength=1.32,
        particle_strength=1.22,
        unlock_achievement="daily_dual_clear",
    ),
    "ghost_echo": ThemePreset(
        bg="#03070A",
        fg="#C9EFF4",
        accent="#59EAD8",
        panel="#09141A",
        dim="#77A0AA",
        secondary="#194236",
        style="blueprint",
        font_family="couriernew",
        scan_strength=1.36,
        glow_strength=1.36,
        particle_strength=1.3,
        unlock_achievement="secret_echo",
    ),
}
DEFAULT_UPDATE_REPO = "OrionTheProgrammer/Gethes"
DEFAULT_CLOUD_ENDPOINT = "http://ec2-44-205-252-139.compute-1.amazonaws.com:443"
DEFAULT_CLOUD_SYNC_INTERVAL_SECONDS = 75
DEFAULT_CLOUD_NEWS_POLL_SECONDS = 300
SYSTER_ENABLED = True
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
DOMAIN_POLICIES: tuple[DomainPolicy, ...] = (
    DomainPolicy(name="ui", max_consecutive_failures=1, cooldown_seconds=2.0),
    DomainPolicy(name="update", max_consecutive_failures=2, cooldown_seconds=5.0),
    DomainPolicy(name="cloud", max_consecutive_failures=2, cooldown_seconds=12.0),
    DomainPolicy(name="games", max_consecutive_failures=2, cooldown_seconds=8.0),
    DomainPolicy(name="syster", max_consecutive_failures=2, cooldown_seconds=10.0),
    DomainPolicy(name="mods", max_consecutive_failures=2, cooldown_seconds=6.0),
)


class GethesApp:
    def __init__(self) -> None:
        package_dir = resource_package_dir()
        self.package_dir = package_dir
        self.data_dir = package_dir / "data"
        self.assets_dir = package_dir / "assets" / "sfx"
        self.storage_dir = user_data_dir()
        self.mods_dir = self.storage_dir / "mods"
        self.theme_mods_dir = self.mods_dir / "themes"
        self.story_mods_dir = self.mods_dir / "story"
        self.user_sfx_dir = self.storage_dir / "sfx"
        self.syster_data_dir = self.storage_dir / "syster"
        self.syster_store = SysterKnowledgeStore(self.syster_data_dir)

        self.config_store = ConfigStore(self.storage_dir / "gethes_config.json")
        self.config = self.config_store.load()
        default_cloud_endpoint = (
            os.getenv("GETHES_CLOUD_ENDPOINT", "").strip() or DEFAULT_CLOUD_ENDPOINT
        )
        if not self.config.cloud_endpoint and default_cloud_endpoint:
            self.config.cloud_endpoint = default_cloud_endpoint
        if self.config.cloud_endpoint.strip():
            self.config.cloud_enabled = True
        self.config.cloud_sync_interval_seconds = max(
            20,
            min(
                600,
                int(self.config.cloud_sync_interval_seconds or DEFAULT_CLOUD_SYNC_INTERVAL_SECONDS),
            ),
        )
        self.config.cloud_news_poll_seconds = max(
            60,
            min(
                3600,
                int(self.config.cloud_news_poll_seconds or DEFAULT_CLOUD_NEWS_POLL_SECONDS),
            ),
        )
        self.i18n = I18n.from_mode(self.config.language)
        self.audio = AudioManager(enabled=self.config.sound)
        self.sfx_service = FreesoundSFXService(api_key=self.config.freesound_api_key)
        self.cloud = CloudSyncClient(
            endpoint=self.config.cloud_endpoint,
            api_key=self.config.cloud_api_key,
            session_token=self.config.cloud_session_token,
        )
        if self.cloud.is_linked():
            # Cloud sync is background-only when endpoint is configured.
            self.config.cloud_enabled = True
        self.ui: ConsoleUI | None = None
        self._pending_domain_notices: list[str] = []
        self.domain_supervisor = DomainSupervisor(
            policies=DOMAIN_POLICIES,
            on_failure=self._on_domain_failure,
        )
        self.input_handler: Callable[[str], None] | None = None
        self.update_events: queue.Queue[tuple[str, dict[str, object]]] = queue.Queue()
        self.mod_watcher: ModWatcher | None = None
        self.mod_reload_times: dict[str, float] = {"theme": 0.0, "story": 0.0}
        self.theme_mod_errors: list[str] = []
        self.awaiting_player_name = False
        self.awaiting_cloud_auth_setup = False
        self.cloud_auth_setup_stage = ""
        self.cloud_auth_pending: dict[str, str] = {}
        self.cloud_auth_running = False
        self.cloud_auth_user: dict[str, str] = {}
        self.cloud_sync_running = False
        self.cloud_sync_cooldown = float(self.config.cloud_sync_interval_seconds)
        self.cloud_sync_elapsed = 0.0
        self.cloud_news_running = False
        self.cloud_leaderboard_running = False
        self.cloud_leaderboard_running_game = ""
        self.cloud_news_elapsed = 0.0
        self.cloud_news_cooldown = float(self.config.cloud_news_poll_seconds)
        self.cloud_last_news_at = 0.0
        self.cloud_seen_news_keys: set[str] = set()
        self.cloud_last_status = "idle"
        self.cloud_last_message = ""
        self.cloud_last_presence: dict[str, object] = {}
        self.cloud_last_snake_leaderboard: list[dict[str, object]] = []
        self.cloud_last_rogue_leaderboard: list[dict[str, object]] = []
        self.cloud_last_hangman_leaderboard: list[dict[str, object]] = []
        self.cloud_last_snake_arena: list[dict[str, object]] = []
        self.cloud_last_snake_arena_players_online = 0
        self.cloud_snake_arena_running = False
        self.cloud_snake_arena_elapsed = 0.0
        self.cloud_snake_arena_keepalive_elapsed = 0.0
        self.cloud_snake_arena_last_rtt_ms = 0
        self.cloud_snake_arena_last_ok_at = 0.0
        self.cloud_snake_arena_fail_streak = 0
        self.cloud_snake_arena_fast_interval = 0.5
        self.cloud_snake_arena_idle_interval = 1.2
        self.cloud_snake_arena_keepalive_interval = 2.6
        self.cloud_snake_arena_last_state: tuple[int, int, int, int, int] = (0, 0, 1, -1, -1)
        self.cloud_snake_arena_room = "global"
        self.cloud_live_leaderboard_interval = 4.0
        self.cloud_live_leaderboard_elapsed = 0.0
        self.cloud_live_leaderboard_game = ""
        self.cloud_last_sync_at = 0.0
        self.daily_active_game = ""
        self.daily_active_date = ""
        self.daily_active_seed = 0
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
            mode="local",
            remote_endpoint=None,
            ollama_enabled=True,
            ollama_model="mistral",
            ollama_host=self.config.syster_ollama_host,
            ollama_timeout=self.config.syster_ollama_timeout,
            package_dir=self.package_dir,
            storage_dir=self.storage_dir,
            knowledge_store=self.syster_store,
        )
        if not self.syster_enabled:
            self.syster.set_mode("local")
            self.syster.set_remote_endpoint(None)
            self.syster.set_ollama_enabled(True)
        else:
            self.syster.warmup_local_ai()
        self.config.syster_mode = "local"
        self.config.syster_mode_user_set = True
        self.config.syster_endpoint = ""
        self.config.syster_ollama_enabled = True
        self.config.syster_ollama_model = "mistral"

        self.ui = ConsoleUI(
            title=self.tr("ui.title"),
            on_command=self._on_command,
        )
        self.ui.on_close = self._shutdown
        self.ui.on_idle = self._on_idle
        self.ui.set_audio(self.audio)
        self._flush_domain_notices()
        self._ensure_modding_templates()
        self.theme_presets = self._load_theme_presets()
        self._start_mod_watcher()
        self._reload_audio_assets()

        self.boot_active = False
        self.boot_steps: list[str] = []
        self.boot_completed = 0
        self.boot_timer_ms = 0.0
        self.boot_progress_percent = 0
        self.boot_stage_queue: list[tuple[bool, str]] = []
        self.boot_stage_cursor = 0
        self.boot_recent_activity: list[str] = []
        self.boot_spinner_frame = 0
        self.idle_count = 0
        self.intro_active = False
        self.last_command = "menu"
        self.syster_auto_enabled = False
        self.syster_auto_pending = False
        self.syster_last_auto_ts = 0.0
        self.syster_auto_cooldown = 7.0
        self.syster_commands_since_auto = 0
        self.syster_control_running = False
        self.syster_reply_running = False
        self.syster_pending_reply: tuple[str, str] | None = None
        self.syster_last_prompt = ""
        self.syster_last_reply = ""
        self.syster_auto_feedback_last_ts = 0.0
        self.syster_auto_feedback_cooldown = 24.0
        self.terminal_passthrough = bool(getattr(self.config, "terminal_passthrough", False))
        self.terminal_exec_running = False
        self.terminal_timeout_seconds = 14
        self.terminal_output_limit = 150

        if self.config.cloud_auth_username.strip():
            self.cloud_auth_user["username"] = self.config.cloud_auth_username.strip()
        if self.config.cloud_auth_email.strip():
            self.cloud_auth_user["email"] = self.config.cloud_auth_email.strip()

        self._migrate_legacy_theme()
        self._sync_theme_visual_profile()
        self._refresh_ui_language()
        self._apply_visual_config()
        self._apply_player_identity()

        words = self._load_words()
        self.snake = SnakeGame(self)
        self.hangman = HangmanGame(self, words)
        self.story = StoryMode(self, self.data_dir, mod_story_dir=self.story_mods_dir)
        self.tictactoe = TicTacToeGame(self)
        self.codebreaker = CodeBreakerGame(self)
        self.physics_lab = PhysicsLabGame(self)
        self.roguelike = RoguelikeGame(self)
        self.command_router = self._build_command_router()
        self._known_aliases_set = set(self.command_router.aliases)
        self._known_aliases_sorted = sorted(self._known_aliases_set)

    def tr(self, key: str, **kwargs: object) -> str:
        return self.i18n.t(key, **kwargs)

    def _on_domain_failure(self, event: DomainFailureEvent) -> None:
        if event.state == DomainState.OPEN:
            notice = self.tr(
                "app.domain.failure_open",
                domain=event.domain,
                action=event.action,
                error=f"{event.error_type}: {event.error_message}",
            )
        else:
            notice = self.tr(
                "app.domain.failure_degraded",
                domain=event.domain,
                action=event.action,
                error=f"{event.error_type}: {event.error_message}",
            )

        ui = self.ui
        if ui is None:
            self._pending_domain_notices.append(notice)
            return

        try:
            ui.write(notice)
            ui.set_status(self.tr("app.domain.status_degraded", domain=event.domain))
        except Exception:
            self._pending_domain_notices.append(notice)

    def _flush_domain_notices(self) -> None:
        if self.ui is None:
            return
        pending = list(self._pending_domain_notices)
        self._pending_domain_notices.clear()
        for notice in pending:
            try:
                self.ui.write(notice)
            except Exception:
                break

    def _run_domain(
        self,
        domain: str,
        action: str,
        operation: Callable[[], object],
        *,
        fallback: object | None = None,
    ) -> object | None:
        return self.domain_supervisor.call(domain, action, operation, fallback=fallback)

    def _show_domain_health(self) -> None:
        self.ui.write(self.tr("app.domain.health.title"))
        for item in self.domain_supervisor.snapshots():
            self.ui.write(
                self.tr(
                    "app.domain.health.item",
                    domain=item.domain,
                    state=item.state.value.upper(),
                    failures=item.total_failures,
                    streak=item.failure_streak,
                    skipped=item.skipped_calls,
                )
            )
            if item.last_error:
                self.ui.write(
                    self.tr(
                        "app.domain.health.last_error",
                        domain=item.domain,
                        error=item.last_error[:160],
                    )
                )

    def run(self) -> None:
        self._run_domain("ui", "intro_sequence", self._start_intro_sequence)
        self._run_domain("ui", "main_loop", lambda: self.ui.run(update_callback=self._update))

    def _update(self, dt: float) -> None:
        self._run_domain("update", "event_pump", self._process_update_events)
        if self.intro_active:
            intro_done = bool(
                self._run_domain("ui", "intro_update", lambda: self.ui.update_intro(dt), fallback=False)
            )
            if intro_done:
                self.intro_active = False
                self._run_domain("ui", "boot_start", self._start_boot_sequence)
            return
        if self.boot_active:
            self._run_domain("ui", "boot_update", lambda: self._update_boot(dt))
            return

        self._run_domain("cloud", "autosync_tick", lambda: self._update_cloud_autosync(dt))
        self._run_domain("cloud", "news_tick", lambda: self._update_cloud_news_poll(dt))
        self._run_domain("cloud", "leaderboard_tick", lambda: self._update_live_leaderboard(dt))
        if self.snake.active:
            self._run_domain("games", "snake_tick", lambda: self.snake.update(dt))
        if self.physics_lab.active:
            self._run_domain("games", "physics_tick", lambda: self.physics_lab.update(dt))
        if self.roguelike.active:
            self._run_domain("games", "rogue_tick", lambda: self.roguelike.update(dt))
        if self.syster_enabled:
            self._run_domain("syster", "autochat_tick", self._update_syster_autochat)

    def set_input_handler(self, handler: Callable[[str], None]) -> None:
        self.input_handler = handler
        self.ui.clear_action_buttons()

    def clear_input_handler(self) -> None:
        self.input_handler = None
        self.ui.clear_action_buttons()

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
        self._record_syster_event("story_finished", {"completed": True})
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

        if self.daily_active_game == "snake" and self.daily_active_date:
            key_best = self._daily_stat_key(self.daily_active_date, "snake", "best_score")
            previous_best = self.get_stat(key_best, 0)
            self.set_stat_max(key_best, score)
            best_now = self.get_stat(key_best, 0)
            self.ui.write(self.tr("app.daily.snake_result", score=score, best=best_now))
            if score > previous_best:
                self.ui.push_notification(
                    self.tr("app.daily.toast.title"),
                    self.tr("app.daily.toast.snake", score=score),
                    icon_key="mdi:trophy-outline",
                )
            first_completion, game_streak, overall_streak, dual_ready = self._mark_daily_completion(
                "snake",
                self.daily_active_date,
            )
            self.ui.write(
                self.tr(
                    "app.daily.progress",
                    game="snake",
                    game_streak=game_streak,
                    overall_streak=overall_streak,
                )
            )
            if first_completion:
                self._unlock_achievement("daily_first_win")
                if overall_streak >= 3:
                    self._unlock_achievement("daily_streak_3")
                if dual_ready:
                    self._unlock_achievement("daily_dual_clear")
                    self.ui.push_notification(
                        self.tr("app.daily.toast.title"),
                        self.tr("app.daily.toast.dual"),
                        icon_key="mdi:trophy-outline",
                    )
        if self.daily_active_game == "snake":
            self._clear_daily_session()
        self._record_syster_event(
            "snake_finished",
            {
                "score": score,
                "level": level,
                "foods": foods_eaten,
                "game_over": game_over,
                "user_exit": user_exit,
            },
        )
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
        self._record_syster_event(
            "hangman_finished",
            {"won": won, "mode": mode, "errors": errors, "hint_used": hint_used},
        )
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
        self._record_syster_event("ttt_finished", {"won": won, "draw": draw})
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
        self._record_syster_event(
            "codebreaker_finished",
            {"won": won, "attempts_used": attempts_used, "hint_used": hint_used},
        )
        self._save_current_slot(user_feedback=False)

    def on_physics_finished(self, score: int, won: bool, cancelled: bool) -> None:
        if cancelled:
            return
        self.bump_stat("physics_games", 1)
        if won:
            self.bump_stat("physics_wins", 1)
        self.set_stat_max("physics_best_score", score)
        self._record_syster_event("physics_finished", {"score": score, "won": won})
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
            if self.daily_active_game == "rogue":
                self._clear_daily_session()
            return
        self.bump_stat("rogue_runs", 1)
        self._unlock_achievement("rogue_first_run")
        if won:
            self.bump_stat("rogue_wins", 1)
            self._unlock_achievement("rogue_victory")
        if depth >= 3:
            self._unlock_achievement("rogue_depth_3")
        self.set_stat_max("rogue_best_depth", depth)
        self.set_stat_max("rogue_best_gold", gold)
        self.set_stat_max("rogue_best_kills", kills)

        if self.daily_active_game == "rogue" and self.daily_active_date:
            key_depth = self._daily_stat_key(self.daily_active_date, "rogue", "best_depth")
            key_gold = self._daily_stat_key(self.daily_active_date, "rogue", "best_gold")
            prev_depth = self.get_stat(key_depth, 0)
            prev_gold = self.get_stat(key_gold, 0)
            self.set_stat_max(key_depth, depth)
            self.set_stat_max(key_gold, gold)
            best_depth = self.get_stat(key_depth, 0)
            best_gold = self.get_stat(key_gold, 0)
            self.ui.write(
                self.tr(
                    "app.daily.rogue_result",
                    depth=depth,
                    gold=gold,
                    best_depth=best_depth,
                    best_gold=best_gold,
                )
            )
            if depth > prev_depth or gold > prev_gold:
                self.ui.push_notification(
                    self.tr("app.daily.toast.title"),
                    self.tr("app.daily.toast.rogue", depth=best_depth, gold=best_gold),
                    icon_key="mdi:trophy-outline",
                )
            first_completion, game_streak, overall_streak, dual_ready = self._mark_daily_completion(
                "rogue",
                self.daily_active_date,
            )
            self.ui.write(
                self.tr(
                    "app.daily.progress",
                    game="rogue",
                    game_streak=game_streak,
                    overall_streak=overall_streak,
                )
            )
            if first_completion:
                self._unlock_achievement("daily_first_win")
                if overall_streak >= 3:
                    self._unlock_achievement("daily_streak_3")
                if dual_ready:
                    self._unlock_achievement("daily_dual_clear")
                    self.ui.push_notification(
                        self.tr("app.daily.toast.title"),
                        self.tr("app.daily.toast.dual"),
                        icon_key="mdi:trophy-outline",
                    )
        if self.daily_active_game == "rogue":
            self._clear_daily_session()
        self._record_syster_event(
            "roguelike_finished",
            {"won": won, "depth": depth, "kills": kills, "gold": gold},
        )
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
            self.config.theme_secondary_color = theme.secondary
            self.config.theme_style = theme.style
            self.config.theme_scan_strength = theme.scan_strength
            self.config.theme_glow_strength = theme.glow_strength
            self.config.theme_particles_strength = theme.particle_strength

    def _sync_theme_visual_profile(self) -> None:
        theme_name = self._detect_theme_name(self.config.bg_color, self.config.fg_color)
        preset = self.theme_presets.get(theme_name)
        if preset is None:
            for candidate in self.theme_presets.values():
                if (
                    candidate.bg.lower() == self.config.bg_color.lower()
                    and candidate.fg.lower() == self.config.fg_color.lower()
                ):
                    preset = candidate
                    break
        if preset is None:
            return

        if not self.config.theme_accent_color.strip():
            self.config.theme_accent_color = preset.accent
        if not self.config.theme_panel_color.strip():
            self.config.theme_panel_color = preset.panel
        if not self.config.theme_dim_color.strip():
            self.config.theme_dim_color = preset.dim
        if (
            abs(float(self.config.theme_scan_strength) - 1.0) <= 0.001
            and abs(float(self.config.theme_glow_strength) - 1.0) <= 0.001
            and abs(float(self.config.theme_particles_strength) - 1.0) <= 0.001
        ):
            self.config.theme_scan_strength = preset.scan_strength
            self.config.theme_glow_strength = preset.glow_strength
            self.config.theme_particles_strength = preset.particle_strength
        if not self.config.theme_secondary_color.strip():
            self.config.theme_secondary_color = preset.secondary
        if self._normalize_theme_style(self.config.theme_style) not in THEME_STYLE_MODES:
            self.config.theme_style = preset.style

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
                            "  Optional: accent/panel/dim/secondary + style + font_family + fx scan/glow/particles + unlock_achievement",
                            "",
                            "Theme mod format (pack):",
                            '  {"themes":{"nocturne":{"bg":"#05070B","fg":"#C3CEDA","accent":"#6CB7E8","secondary":"#1A2438","style":"split_v","font_family":"consolas","fx":{"scan":1.1,"glow":0.9,"particles":0.8},"unlock_achievement":"codebreaker_win"}}}',
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
                                    "secondary": "#1A2438",
                                    "style": "split_v",
                                    "font_family": "consolas",
                                    "fx": {"scan": 1.0, "glow": 0.9, "particles": 0.8},
                                },
                                "bloodmoon": {
                                    "bg": "#10060A",
                                    "fg": "#F0B7C1",
                                    "accent": "#FF5A7A",
                                    "secondary": "#2D1220",
                                    "style": "split_h",
                                    "fx": {"scan": 1.2, "glow": 1.2, "particles": 0.9},
                                    "unlock_achievement": "hangman_win",
                                },
                                "mono_ice": {
                                    "bg": "#070B0D",
                                    "fg": "#D2E1E8",
                                    "accent": "#7AD0F2",
                                    "secondary": "#153041",
                                    "style": "grid",
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

    @staticmethod
    def _normalize_theme_style(value: object) -> str:
        if not isinstance(value, str):
            return ""
        token = value.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "splitv": "split_v",
            "split_vertical": "split_v",
            "splith": "split_h",
            "split_horizontal": "split_h",
            "diag": "diagonal",
            "neo": "terminal",
        }
        normalized = aliases.get(token, token)
        if normalized not in THEME_STYLE_MODES:
            return ""
        return normalized

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
        secondary = payload.get("secondary")
        if not isinstance(secondary, str):
            secondary = payload.get("secondary_color")
        style = self._normalize_theme_style(payload.get("style"))
        if not style:
            style = self._normalize_theme_style(payload.get("theme_style"))
        if not style:
            style = "terminal"
        font_family = payload.get("font_family")
        if not isinstance(font_family, str):
            font_family = payload.get("font")
        if not isinstance(font_family, str):
            font_family = ""
        unlock = payload.get("unlock_achievement")
        if not isinstance(unlock, str):
            unlock = ""

        return ThemePreset(
            bg=bg.strip(),
            fg=fg.strip(),
            accent=(accent.strip() if isinstance(accent, str) else ""),
            panel=(panel.strip() if isinstance(panel, str) else ""),
            dim=(dim.strip() if isinstance(dim, str) else ""),
            secondary=(secondary.strip() if isinstance(secondary, str) else ""),
            style=style,
            font_family=font_family.strip(),
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
                if theme.secondary and not self.ui.is_valid_color(theme.secondary):
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

    def _handle_terminal(self, args: list[str], command: str) -> None:
        action = args[0].lower() if args else "status"

        if action in {"status", "state"}:
            mode = "ON" if self.terminal_passthrough else "OFF"
            self.ui.write(
                self.tr(
                    "app.terminal.status",
                    mode=mode,
                    timeout=self.terminal_timeout_seconds,
                    limit=self.terminal_output_limit,
                )
            )
            self.ui.write(self.tr("app.terminal.usage"))
            return

        if action in {"on", "enable"}:
            if self.terminal_passthrough:
                self.ui.write(self.tr("app.terminal.already_on"))
                return
            self.terminal_passthrough = True
            self.config.terminal_passthrough = True
            self._apply_player_identity()
            self.ui.write(self.tr("app.terminal.on"))
            self.ui.write(self.tr("app.terminal.prefix_hint"))
            return

        if action in {"off", "disable"}:
            if not self.terminal_passthrough:
                self.ui.write(self.tr("app.terminal.already_off"))
                return
            self.terminal_passthrough = False
            self.config.terminal_passthrough = False
            self._apply_player_identity()
            self.ui.write(self.tr("app.terminal.off"))
            return

        if action in {"run", "exec"}:
            parts = command.split(None, 2)
            if len(parts) < 3 or not parts[2].strip():
                self.ui.write(self.tr("app.terminal.run_usage"))
                return
            self._run_terminal_command(parts[2].strip(), from_passthrough=False)
            return

        self.ui.write(self.tr("app.terminal.usage"))

    def _run_terminal_command(self, shell_command: str, *, from_passthrough: bool) -> None:
        command = shell_command.strip()
        if not command:
            key = "app.terminal.exec_empty" if from_passthrough else "app.terminal.run_usage"
            self.ui.write(self.tr(key))
            return

        if self.terminal_exec_running:
            self.ui.write(self.tr("app.terminal.busy"))
            return

        self.terminal_exec_running = True
        self.ui.set_status(self.tr("app.terminal.running"))
        self.ui.write(self.tr("app.terminal.exec_header", cmd=command), play_sound=False)
        self.audio.play("tick")

        timeout = self.terminal_timeout_seconds

        def as_text(value: object) -> str:
            if value is None:
                return ""
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace")
            return str(value)

        def worker() -> None:
            start_ts = time.monotonic()
            try:
                proc = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                )
                elapsed_ms = int((time.monotonic() - start_ts) * 1000)
                self.update_events.put(
                    (
                        "terminal_result",
                        {
                            "stdout": proc.stdout or "",
                            "stderr": proc.stderr or "",
                            "returncode": int(proc.returncode),
                            "timed_out": False,
                            "elapsed_ms": elapsed_ms,
                        },
                    )
                )
                return
            except subprocess.TimeoutExpired as exc:
                elapsed_ms = int((time.monotonic() - start_ts) * 1000)
                self.update_events.put(
                    (
                        "terminal_result",
                        {
                            "stdout": as_text(exc.stdout),
                            "stderr": as_text(exc.stderr),
                            "returncode": 124,
                            "timed_out": True,
                            "elapsed_ms": elapsed_ms,
                        },
                    )
                )
                return
            except Exception as exc:
                self.update_events.put(
                    (
                        "terminal_result",
                        {
                            "error": str(exc),
                        },
                    )
                )

        threading.Thread(target=worker, daemon=True, name="gethes-terminal-exec").start()

    def _consume_terminal_result(self, payload: dict[str, object]) -> None:
        self.terminal_exec_running = False
        self.ui.set_status(self.tr("ui.ready"))

        error = str(payload.get("error", "")).strip()
        if error:
            self.ui.write(self.tr("app.terminal.failed", error=error))
            return

        timed_out = bool(payload.get("timed_out", False))
        return_code = int(payload.get("returncode", 1) or 1)
        elapsed_ms = int(payload.get("elapsed_ms", 0) or 0)
        stdout = str(payload.get("stdout", "") or "")
        stderr = str(payload.get("stderr", "") or "")

        lines: list[str] = []
        if stdout.strip():
            lines.append(self.tr("app.terminal.stdout"))
            lines.extend(stdout.rstrip().splitlines())
        if stderr.strip():
            lines.append(self.tr("app.terminal.stderr"))
            lines.extend(stderr.rstrip().splitlines())

        if not lines:
            self.ui.write(self.tr("app.terminal.no_output"), play_sound=False)
        else:
            total_lines = len(lines)
            if total_lines > self.terminal_output_limit:
                lines = lines[: self.terminal_output_limit]
                self.ui.write("\n".join(lines), play_sound=False)
                self.ui.write(
                    self.tr("app.terminal.truncated", limit=self.terminal_output_limit),
                    play_sound=False,
                )
            else:
                self.ui.write("\n".join(lines), play_sound=False)

        if timed_out:
            self.ui.write(self.tr("app.terminal.timeout", seconds=self.terminal_timeout_seconds))

        self.ui.write(self.tr("app.terminal.completed", code=return_code, ms=elapsed_ms))
        if return_code == 0:
            self.audio.play("tick")
        else:
            self.audio.play("error")

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

        if not self.syster_auto_enabled:
            return

        if self.syster_enabled and self._trigger_syster_auto("idle"):
            return

        if self.syster_enabled and self.idle_count % 3 == 2:
            self.ui.write(self.tr("app.idle.secret"))
        else:
            self.ui.write(self.tr("app.idle.help"))
        self.audio.play("message")
        self.idle_count += 1

    def _build_command_router(self) -> CommandRouter:
        router = CommandRouter()

        def add_noargs(aliases: set[str], action: Callable[[], None]) -> None:
            router.add_many(aliases, lambda _args, _raw_command, _parts: action())

        def add_args(aliases: set[str], action: Callable[[list[str]], None]) -> None:
            router.add_many(aliases, lambda args, _raw_command, _parts: action(args))

        def start_snake(args: list[str]) -> None:
            self._handle_snake_command(args)

        def start_roguelike() -> None:
            self._clear_daily_session()
            self._run_domain("games", "rogue_start", lambda: self.roguelike.start())

        def save_config_feedback() -> None:
            self._save_config()
            self.ui.write(self.tr("app.config_saved"))

        add_noargs({"help", "ayuda", "ajuda", "?"}, lambda: self.ui.write(self._help_text()))
        add_noargs({"clear", "cls"}, self.ui.clear)
        add_noargs({"menu", "inicio", "home"}, lambda: self.ui.set_screen(self._welcome_text()))
        add_noargs({"vmenu", "menuui", "visualmenu"}, lambda: self.ui.write(self.tr("app.vmenu_removed")))

        add_args({"snake"}, start_snake)
        add_noargs(
            {"ahorcado1", "hangman1"},
            lambda: self._run_domain(
                "games",
                "hangman_single_start",
                lambda: self.hangman.start_single_player(),
            ),
        )
        add_noargs(
            {"ahorcado2", "hangman2"},
            lambda: self._run_domain(
                "games",
                "hangman_dual_start",
                lambda: self.hangman.start_two_player(),
            ),
        )
        add_noargs(
            {"historia", "story"},
            lambda: self._run_domain("games", "story_start", lambda: self.story.start()),
        )
        add_noargs(
            {"gato", "tictactoe", "ttt"},
            lambda: self._run_domain("games", "tictactoe_start", lambda: self.tictactoe.start()),
        )
        add_noargs(
            {"codigo", "codebreaker", "mastermind"},
            lambda: self._run_domain("games", "codebreaker_start", lambda: self.codebreaker.start()),
        )
        add_noargs(
            {"physics", "lab", "physicslab"},
            lambda: self._run_domain("games", "physics_start", lambda: self.physics_lab.start()),
        )
        add_noargs({"roguelike", "rogelike", "rogue", "dungeon"}, start_roguelike)

        add_args({"daily", "reto", "desafio"}, self._handle_daily)
        add_noargs({"opciones", "options", "opcoes"}, lambda: self.ui.write(self._options_text()))
        add_args({"doctor", "diag", "diagnostic"}, self._handle_doctor)
        add_noargs({"health", "domains", "dominios"}, self._show_domain_health)
        add_noargs({"modsreload"}, lambda: self._handle_mods(["reload"]))
        add_args({"mods"}, self._handle_mods)
        add_noargs({"logros", "achievements", "ach"}, self._show_achievements)
        add_noargs({"slots"}, self._show_slots)
        add_args({"slot"}, self._switch_slot)
        add_args({"slotname"}, self._rename_slot)
        add_args({"user", "username", "usuario", "nome", "player"}, self._handle_user)
        add_noargs({"savegame"}, lambda: self._save_current_slot(user_feedback=True))
        add_args(
            {"syster"},
            lambda args: self._run_domain("syster", "command", lambda: self._handle_syster(args)),
        )
        add_args({"sound"}, self._set_sound)
        add_args({"graphics"}, self._set_graphics)
        add_args({"uiscale", "ui-scale", "scaleui"}, self._set_ui_scale)
        add_args({"theme"}, self._set_theme)
        add_args({"bg"}, lambda args: self._set_single_color(args, key="bg"))
        add_args({"fg"}, lambda args: self._set_single_color(args, key="fg"))
        add_args({"font"}, self._set_font)
        add_args({"fonts"}, self._list_fonts)
        add_args({"lang", "language", "idioma", "lingua"}, self._set_language)
        add_args({"update", "actualizar", "atualizar"}, self._handle_update)
        add_args({"assets"}, self._handle_assets)
        add_args({"cloud", "nube", "nuvem"}, self._handle_cloud)
        add_args({"auth", "account", "cuenta"}, self._handle_auth)
        add_args({"register", "registro"}, lambda args: self._handle_auth(["register", *args]))
        add_args({"login", "signin", "iniciar"}, lambda args: self._handle_auth(["login", *args]))
        add_noargs({"logout", "cerrarsesion"}, lambda: self._handle_auth(["logout"]))
        add_args({"news", "noticias"}, lambda args: self._handle_cloud(["news", *args]))
        add_args(
            {"leaderboard", "ranking", "rank", "top"},
            lambda args: self._handle_cloud(["leaderboard", *args]),
        )
        add_args({"sfx"}, self._handle_sfx)
        add_noargs({"save"}, save_config_feedback)

        def handle_terminal(args: list[str], raw_command: str, _parts: list[str]) -> None:
            self._handle_terminal(args, command=raw_command)

        def handle_sh(_args: list[str], raw_command: str, parts: list[str]) -> None:
            shell_command = raw_command.split(None, 1)[1].strip() if len(parts) > 1 else ""
            self._run_terminal_command(shell_command, from_passthrough=False)

        def handle_secret(_args: list[str], _raw_command: str, parts: list[str]) -> None:
            alias = parts[0].lower() if parts else "creator"
            self._trigger_secret(alias)

        def handle_exit(_args: list[str], _raw_command: str, _parts: list[str]) -> None:
            self._shutdown()
            self.ui.request_quit()

        router.add_many({"terminal", "term"}, handle_terminal)
        router.add_many({"sh", "shell"}, handle_sh)
        router.add_many({"creator", "orion", "gethes"}, handle_secret)
        router.add_many({"exit", "salir", "sair", "quit"}, handle_exit)
        return router

    def _on_command(self, raw_command: str) -> None:
        if self.input_handler is not None:
            self.input_handler(raw_command)
            return

        command = raw_command.strip()
        if not command:
            return

        force_internal = False
        if self.terminal_passthrough and command.startswith("/"):
            command = command[1:].strip()
            force_internal = True
            if not command:
                self.ui.write(self.tr("app.terminal.prefix_hint"))
                return

        try:
            parts = shlex.split(command)
        except ValueError as exc:
            lowered_command = command.lower()
            if lowered_command.startswith("sh ") or lowered_command.startswith("shell "):
                chunks = command.split(None, 1)
                if len(chunks) > 1 and chunks[1].strip():
                    self._run_terminal_command(chunks[1].strip(), from_passthrough=False)
                    return
            if lowered_command.startswith("terminal run ") or lowered_command.startswith("terminal exec "):
                chunks = command.split(None, 2)
                if len(chunks) > 2 and chunks[2].strip():
                    self._run_terminal_command(chunks[2].strip(), from_passthrough=False)
                    return
            if self.terminal_passthrough and not force_internal:
                self._run_terminal_command(command, from_passthrough=True)
                return
            self.ui.write(self.tr("app.syntax_error", error=str(exc)))
            self._record_syster_command(command, outcome="syntax_error")
            return

        cmd = parts[0].lower()
        args = parts[1:]
        self._record_syster_command(command, outcome="accepted")
        if cmd != "syster":
            self.last_command = cmd
            if not self.syster_control_running:
                self._queue_syster_auto_from_command(cmd)

        if self.command_router.dispatch(cmd, args, command, parts):
            return

        if cmd not in self._known_aliases_set:
            if self.terminal_passthrough and not force_internal:
                self._run_terminal_command(command, from_passthrough=True)
                return

            suggestion = self._suggest_command_alias(cmd)
            if suggestion:
                self.ui.write(self.tr("app.unknown_suggest", cmd=cmd, suggestion=suggestion))
                return

            if self.syster_enabled and self.syster.mode == "local":
                core_ready, _core_state = self.syster.get_ollama_status(force_probe=False)
                if core_ready and self._emit_syster_response(command, source="player_freeform"):
                    return

            self.ui.write(self.tr("app.unknown", cmd=cmd))
            return

    def _suggest_command_alias(self, cmd: str) -> str:
        token = cmd.strip().lower()
        if not token:
            return ""

        aliases = self._known_aliases_sorted
        if token in self._known_aliases_set:
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
        if not self.syster_auto_enabled:
            return
        if not self.syster_enabled:
            return
        if self.syster.mode != "local":
            return
        if cmd in {"syster", "save", "savegame", "exit", "salir", "sair", "quit"}:
            return

        self.syster_commands_since_auto += 1
        if self.syster_commands_since_auto >= 2:
            self.syster_commands_since_auto = 0
            self.syster_auto_pending = True

    def _update_syster_autochat(self) -> None:
        if not self.syster_auto_enabled:
            return
        if not self.syster_enabled:
            return
        if not self.syster_auto_pending:
            return
        if self._trigger_syster_auto("command"):
            self.syster_auto_pending = False

    def _syster_auto_prompt(self, trigger: str) -> str:
        if trigger == "boot":
            return "briefing"
        if trigger == "idle":
            return "briefing"

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
        if not self.syster_auto_enabled:
            return False
        if not self.syster_enabled:
            return False
        if self.syster.mode != "local":
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
        if not self._emit_syster_response(prompt, source="auto"):
            return False
        self.syster_last_auto_ts = now
        return True

    def _emit_syster_response(self, prompt: str, *, source: str) -> bool:
        return self._queue_syster_response(prompt, source=source)

    def _queue_syster_response(self, prompt: str, *, source: str) -> bool:
        normalized_prompt = " ".join((prompt or "").split()).strip()
        if not normalized_prompt:
            return False
        if self.syster_reply_running:
            self.syster_pending_reply = (normalized_prompt, source)
            if source in {"player", "player_freeform"}:
                self.ui.write(self.tr("app.syster.busy"))
            return True

        context = self._build_syster_context()
        self.syster_reply_running = True
        if source in {"player", "player_freeform"}:
            self.ui.set_status(self.tr("app.syster.thinking"))

        def worker() -> None:
            try:
                raw_reply_obj = self.syster.reply(
                    normalized_prompt,
                    lambda key, **kwargs: self.tr(key, **kwargs),
                    context=context,
                )
                raw_reply = str(raw_reply_obj or "")
                error_message = ""
            except Exception as exc:
                raw_reply = ""
                error_message = f"{type(exc).__name__}: {exc}"
            self.update_events.put(
                (
                    "syster_reply_done",
                    {
                        "prompt": normalized_prompt,
                        "source": source,
                        "context": context,
                        "raw_reply": raw_reply,
                        "error": error_message,
                    },
                )
            )

        threading.Thread(target=worker, daemon=True, name=f"gethes-syster-reply-{source}").start()
        return True

    def _consume_syster_reply_done(self, payload: dict[str, object]) -> None:
        self.syster_reply_running = False
        prompt = str(payload.get("prompt", "") or "")
        source = str(payload.get("source", "") or "player")
        context = payload.get("context")
        if not isinstance(context, SysterContext):
            context = self._build_syster_context()
        raw_reply = str(payload.get("raw_reply", "") or "")
        error_message = str(payload.get("error", "") or "").strip()

        if (
            not self.snake.active
            and not self.roguelike.active
            and not self.physics_lab.active
            and self.input_handler is None
        ):
            self.ui.set_status(self.tr("ui.help_hint"))

        if error_message and not raw_reply.strip():
            if source in {"player", "player_freeform"}:
                self.ui.write(self.tr("app.syster.error", error=error_message[:220]))
            self._start_pending_syster_reply()
            return

        if not raw_reply.strip():
            self._start_pending_syster_reply()
            return

        control_command, cleaned_reply = self.syster.extract_control_command(raw_reply)
        visible_reply = cleaned_reply.strip()
        if not visible_reply and not control_command:
            visible_reply = raw_reply.strip()
        if source == "player":
            normalized_prompt = " ".join(prompt.split())
            if normalized_prompt:
                self.syster_last_prompt = normalized_prompt[:400]
            if visible_reply:
                self.syster_last_reply = visible_reply[:800]
        self.syster.observe_exchange(
            prompt=prompt,
            reply=visible_reply,
            context=context,
            source=source,
            intent=self.syster.last_intent,
        )
        self._auto_train_syster_feedback(
            prompt=prompt,
            reply=visible_reply,
            source=source,
        )

        if visible_reply:
            self.ui.write(self.tr("app.syster.prefix"), play_sound=False)
            self.ui.write(visible_reply)
            self.audio.play("message")

        if control_command:
            self._apply_syster_control_command(control_command, source=source)

        self._start_pending_syster_reply()

    def _start_pending_syster_reply(self) -> None:
        pending = self.syster_pending_reply
        self.syster_pending_reply = None
        if pending is None:
            return
        prompt, source = pending
        self._queue_syster_response(prompt, source=source)

    def _emit_syster_response_sync(self, prompt: str, *, source: str) -> bool:
        # Reserved for diagnostics where synchronous behavior may still be required.
        context = self._build_syster_context()
        raw_reply_obj = self.syster.reply(
            prompt,
            lambda key, **kwargs: self.tr(key, **kwargs),
            context=context,
        )
        raw_reply = str(raw_reply_obj or "")
        if not raw_reply.strip():
            return False

        control_command, cleaned_reply = self.syster.extract_control_command(raw_reply)
        visible_reply = cleaned_reply.strip()
        if not visible_reply and not control_command:
            visible_reply = raw_reply.strip()
        if source == "player":
            normalized_prompt = " ".join(prompt.split())
            if normalized_prompt:
                self.syster_last_prompt = normalized_prompt[:400]
            if visible_reply:
                self.syster_last_reply = visible_reply[:800]
        self.syster.observe_exchange(
            prompt=prompt,
            reply=visible_reply,
            context=context,
            source=source,
            intent=self.syster.last_intent,
        )
        self._auto_train_syster_feedback(
            prompt=prompt,
            reply=visible_reply,
            source=source,
        )

        if visible_reply:
            self.ui.write(self.tr("app.syster.prefix"), play_sound=False)
            self.ui.write(visible_reply)
            self.audio.play("message")

        if control_command:
            self._apply_syster_control_command(control_command, source=source)

        return bool(visible_reply or control_command)

    def _auto_train_syster_feedback(self, *, prompt: str, reply: str, source: str) -> None:
        prompt_text = " ".join((prompt or "").split()).strip()
        reply_text = " ".join((reply or "").split()).strip()
        if not prompt_text or not reply_text:
            return

        now = time.monotonic()
        if (now - self.syster_auto_feedback_last_ts) < self.syster_auto_feedback_cooldown:
            return

        score, notes = self._estimate_syster_feedback(prompt_text, reply_text, source)
        self.syster.record_feedback(
            prompt=prompt_text[:500],
            reply=reply_text[:900],
            score=score,
            notes=notes,
        )
        self.syster_auto_feedback_last_ts = now
        self._record_syster_event(
            "syster_auto_feedback",
            {
                "score": round(score, 3),
                "source": source[:24],
                "notes": notes[:120],
            },
        )

    def _estimate_syster_feedback(self, prompt: str, reply: str, source: str) -> tuple[float, str]:
        score = 0.68 if source in {"player", "player_freeform"} else 0.56
        notes: list[str] = [f"auto:{source}"]
        lowered = reply.lower()

        if len(reply) < 24:
            score -= 0.22
            notes.append("short_reply")
        elif len(reply) > 820:
            score -= 0.08
            notes.append("long_reply")

        if lowered.startswith("app.syster.") or "app.syster." in lowered:
            score -= 0.5
            notes.append("fallback_key")

        immersion_break = any(token in lowered for token in ("ollama", "mistral", "api", "endpoint"))
        if immersion_break:
            score -= 0.38
            notes.append("immersion_break")

        if prompt.lower().strip() == reply.lower().strip():
            score -= 0.25
            notes.append("echo_like")

        bounded = max(0.0, min(1.0, score))
        return bounded, ",".join(notes)

    def _is_syster_control_allowed(self, command: str) -> bool:
        token = " ".join(command.lower().split())
        if not token:
            return False

        if any(mark in token for mark in ("\n", "\r", "&&", "||", ";", "|", ">", "<")):
            return False

        blocked_tokens = (
            "terminal",
            "sh",
            "shell",
            "update",
            "cloud",
            "mods",
            "sfx",
            "syster",
            "exit",
            "quit",
            "salir",
            "sair",
        )
        if token in blocked_tokens:
            return False
        if any(token.startswith(f"{prefix} ") for prefix in blocked_tokens):
            return False

        allowed_exact = {
            "help",
            "?",
            "clear",
            "menu",
            "inicio",
            "home",
            "historia",
            "story",
            "logros",
            "achievements",
            "slots",
            "savegame",
            "snake",
            "ahorcado1",
            "hangman1",
            "ahorcado2",
            "hangman2",
            "gato",
            "tictactoe",
            "codigo",
            "codebreaker",
            "physics",
            "roguelike",
            "rogue",
            "dungeon",
            "daily status",
            "options",
            "opciones",
            "opcoes",
            "theme list",
        }
        if token in allowed_exact:
            return True

        allowed_prefixes = (
            "slot ",
            "slotname ",
            "user ",
            "sound ",
            "graphics ",
            "uiscale ",
            "ui-scale ",
            "theme ",
            "bg ",
            "fg ",
            "font ",
            "lang ",
            "language ",
            "idioma ",
            "lingua ",
            "daily ",
        )
        return any(token.startswith(prefix) for prefix in allowed_prefixes)

    def _apply_syster_control_command(self, command: str, *, source: str) -> None:
        if self.syster_control_running:
            return

        normalized = " ".join(command.split())
        if not normalized:
            return

        if not self._is_syster_control_allowed(normalized):
            self._record_syster_event(
                "syster_control_blocked",
                {"command": normalized, "source": source},
            )
            self.ui.write(self.tr("app.syster.control.blocked", cmd=normalized))
            return

        self.syster_control_running = True
        try:
            self.ui.write(self.tr("app.syster.control.exec", cmd=normalized), play_sound=False)
            self._record_syster_event(
                "syster_control_exec",
                {"command": normalized, "source": source},
            )
            self._on_command(normalized)
        finally:
            self.syster_control_running = False

    def _handle_syster(self, args: list[str]) -> None:
        if not self.syster_enabled:
            self.ui.write(self.tr("app.syster.temporarily_disabled"))
            return

        if not args:
            context = self._build_syster_context()
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
            self._show_syster_core_status(force_probe=True)
            summary = self.syster.briefing(
                lambda key, **kwargs: self.tr(key, **kwargs),
                context,
            )
            self.syster.observe_exchange(
                prompt="status",
                reply=summary,
                context=context,
                source="player",
                intent="briefing",
            )
            self.syster_last_prompt = "status"
            self.syster_last_reply = summary[:800]
            self.ui.write(self.tr("app.syster.prefix"), play_sound=False)
            self.ui.write(summary)
            self.ui.write(self.tr("app.syster.usage"))
            return

        action = args[0].lower()
        if action in {"brief", "briefing", "recap"}:
            context = self._build_syster_context()
            summary = self.syster.briefing(
                lambda key, **kwargs: self.tr(key, **kwargs),
                context,
            )
            self.syster.observe_exchange(
                prompt="briefing",
                reply=summary,
                context=context,
                source="player",
                intent="briefing",
            )
            self.syster_last_prompt = "briefing"
            self.syster_last_reply = summary[:800]
            self.ui.write(self.tr("app.syster.prefix"))
            self.ui.write(summary)
            self.audio.play("message")
            return

        if action == "mode":
            if len(args) == 2 and args[1].strip().lower() == "local":
                self.syster.set_mode("local")
                self.config.syster_mode = "local"
                self.config.syster_ollama_enabled = True
                self.config.syster_ollama_model = "mistral"
                self.config.syster_endpoint = ""
                self.config.syster_mode_user_set = True
                self._save_config()
                self.ui.write(self.tr("app.syster.mode_set", mode="local"))
                return
            self.ui.write(self.tr("app.syster.mode_local_only"))
            self.ui.write(self.tr("app.syster.mode_usage"))
            return

        if action == "endpoint":
            self.ui.write(self.tr("app.syster.endpoint_local_only"))
            self.config.syster_endpoint = ""
            self.syster.set_remote_endpoint(None)
            self.config.syster_mode_user_set = True
            self._save_config()
            return

        if action == "core":
            self._handle_syster_core(args[1:])
            return

        if action == "train":
            self._handle_syster_train(args[1:])
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

        self._emit_syster_response(prompt, source="player")

    def _show_syster_core_status(self, force_probe: bool) -> None:
        status = self.syster.core_runtime_status(force_probe=force_probe)
        ok = bool(status.get("online", False))
        reason = self.syster._humanize_core_reason(str(status.get("state", "unknown")))
        runtime_path = str(status.get("runtime_path", "") or "")
        model_ready = bool(status.get("model_ready", False))
        cuda_available = bool(status.get("cuda_available", False))
        if not self.syster.ollama_enabled:
            state = self.tr("app.syster.ollama.state.disabled")
        elif ok:
            state = self.tr("app.syster.ollama.state.online")
        else:
            state = self.tr("app.syster.ollama.state.offline")
        self.ui.write(
            self.tr(
                "app.syster.ollama.status",
                enabled=("ON" if self.syster.ollama_enabled else "OFF"),
                state=state,
                model=self.syster.ollama_model,
                host=(self.syster.ollama_host or "-"),
                reason=reason,
            )
        )
        self.ui.write(
            self.tr(
                "app.syster.ollama.runtime",
                runtime=(runtime_path or "-"),
                models=str(status.get("models_dir", "-")),
                model_ready=("YES" if model_ready else "NO"),
            )
        )
        runtime_bootstrap_in_progress = bool(status.get("runtime_bootstrap_in_progress", False))
        runtime_bootstrap_error = str(status.get("runtime_bootstrap_error", "") or "")
        if runtime_bootstrap_in_progress:
            self.ui.write(
                self.tr(
                    "app.syster.ollama.runtime_bootstrap",
                    state="downloading",
                )
            )
        elif runtime_bootstrap_error:
            self.ui.write(
                self.tr(
                    "app.syster.ollama.runtime_bootstrap_error",
                    error=runtime_bootstrap_error,
                )
            )
        self.ui.write(
            self.tr(
                "app.syster.ollama.tuning",
                context=str(status.get("context_length", self.syster.ollama_context_length)),
                flash=("ON" if bool(status.get("flash_attention", False)) else "OFF"),
                kv=str(status.get("kv_cache_type", self.syster.ollama_kv_cache_type)),
                keep_alive=str(status.get("keep_alive", self.syster.ollama_keep_alive)),
                cuda=("ON" if cuda_available else "OFF"),
            )
        )

    def _handle_syster_core(self, args: list[str]) -> None:
        action = args[0].lower() if args else "status"

        if action in {"status", "state"}:
            self._show_syster_core_status(force_probe=True)
            self.ui.write(self.tr("app.syster.ollama.usage"))
            return

        if action in {"on", "enable"}:
            self.syster.set_ollama_enabled(True)
            self.config.syster_ollama_enabled = True
            self.syster.set_mode("local")
            self.config.syster_mode = "local"
            self.config.syster_ollama_model = "mistral"
            self._save_config()
            self.ui.write(self.tr("app.syster.ollama.on"))
            self._show_syster_core_status(force_probe=True)
            return

        if action in {"off", "disable"}:
            self.syster.set_ollama_enabled(True)
            self.config.syster_ollama_enabled = True
            self.ui.write(self.tr("app.syster.ollama.off_blocked"))
            return

        if action == "model":
            self.syster.set_ollama_model("mistral")
            self.config.syster_ollama_model = "mistral"
            self._save_config()
            self.ui.write(self.tr("app.syster.ollama.model_locked", model="mistral"))
            return

        if action == "host":
            if len(args) == 1:
                self.ui.write(self.tr("app.syster.ollama.host_status", host=self.syster.ollama_host or "-"))
                self.ui.write(self.tr("app.syster.ollama.host_usage"))
                return
            host = " ".join(args[1:]).strip()
            if host.lower() in {"off", "none", "clear", "reset"}:
                self.syster.set_ollama_host("")
                self.config.syster_ollama_host = ""
                self._save_config()
                self.ui.write(self.tr("app.syster.ollama.host_cleared"))
                return
            if not host:
                self.ui.write(self.tr("app.syster.ollama.host_usage"))
                return
            self.syster.set_ollama_host(host)
            if not self.syster.ollama_host.startswith(("http://", "https://")):
                self.ui.write(self.tr("app.syster.ollama.host_invalid"))
                return
            self.config.syster_ollama_host = self.syster.ollama_host
            self._save_config()
            self.ui.write(self.tr("app.syster.ollama.host_set", host=self.syster.ollama_host))
            return

        if action == "timeout":
            if len(args) == 1:
                self.ui.write(
                    self.tr(
                        "app.syster.ollama.timeout_status",
                        value=f"{self.syster.ollama_timeout:.1f}",
                    )
                )
                self.ui.write(self.tr("app.syster.ollama.timeout_usage"))
                return
            token = args[1].strip().lower().replace("s", "")
            try:
                value = float(token)
            except ValueError:
                self.ui.write(self.tr("app.syster.ollama.timeout_invalid"))
                return
            if value < 1.0 or value > 120.0:
                self.ui.write(self.tr("app.syster.ollama.timeout_invalid"))
                return
            self.syster.set_ollama_timeout(value)
            self.config.syster_ollama_timeout = self.syster.ollama_timeout
            self._save_config()
            self.ui.write(
                self.tr(
                    "app.syster.ollama.timeout_set",
                    value=f"{self.syster.ollama_timeout:.1f}",
                )
            )
            return

        if action in {"optimize", "cuda", "gpu"}:
            profile = args[1].strip().lower() if len(args) > 1 else "balanced"
            result = self.syster.optimize_for_cuda(profile)
            self.ui.write(
                self.tr(
                    "app.syster.ollama.optimize",
                    profile=str(result.get("profile", "balanced")),
                    context=str(result.get("context_length", self.syster.ollama_context_length)),
                    kv=str(result.get("kv_cache_type", self.syster.ollama_kv_cache_type)),
                    flash=("ON" if bool(result.get("flash_attention", True)) else "OFF"),
                    keep_alive=str(result.get("keep_alive", self.syster.ollama_keep_alive)),
                )
            )
            self.syster.warmup_local_ai()
            self._show_syster_core_status(force_probe=True)
            return

        if action in {"warmup", "wake"}:
            self.syster.warmup_local_ai()
            self.ui.write(self.tr("app.syster.ollama.warmup"))
            self._show_syster_core_status(force_probe=True)
            return

        self.ui.write(self.tr("app.syster.ollama.usage"))

    def _handle_syster_train(self, args: list[str]) -> None:
        action = args[0].lower() if args else "status"

        if action in {"status", "state"}:
            overview = self.syster_store.get_training_overview()
            self.ui.write(
                self.tr(
                    "app.syster.train.status",
                    interactions=overview["interactions"],
                    feedback=overview["feedback"],
                    memory=overview["long_memory"],
                    events=overview["events"],
                    commands=overview["commands"],
                    snapshots=overview["snapshots"],
                )
            )
            if self.syster_last_prompt and self.syster_last_reply:
                self.ui.write(self.tr("app.syster.train.last_ready"))
            else:
                self.ui.write(self.tr("app.syster.train.last_missing"))
            return

        if action == "memory":
            items = self.syster_store.get_long_memory_entries(limit=6, min_weight=0.0)
            if not items:
                self.ui.write(self.tr("app.syster.train.memory_empty"))
                return
            self.ui.write(self.tr("app.syster.train.memory_title"))
            for row in items:
                self.ui.write(
                    self.tr(
                        "app.syster.train.memory_item",
                        key=row.get("key", "-"),
                        value=str(row.get("value", ""))[:120],
                        weight=f"{float(row.get('weight', 0.0)):.2f}",
                    )
                )
            return

        if action == "remember":
            if len(args) < 3:
                self.ui.write(self.tr("app.syster.train.remember_usage"))
                return
            raw_key = args[1].strip().lower()
            key = "".join(ch for ch in raw_key if ch.isalnum() or ch in {"_", "-", "."})
            if not key:
                self.ui.write(self.tr("app.syster.train.remember_usage"))
                return
            value = " ".join(args[2:]).strip()
            if not value:
                self.ui.write(self.tr("app.syster.train.remember_usage"))
                return
            self.syster_store.upsert_long_memory(
                key[:120],
                value[:900],
                weight=2.4,
                source="manual",
            )
            self._record_syster_event("syster_memory_remember", {"key": key[:120]})
            self.ui.write(self.tr("app.syster.train.remember_saved", key=key[:120]))
            return

        if action == "forget":
            self.ui.write(self.tr("app.syster.train.forget_blocked"))
            return

        if not self.syster_last_prompt or not self.syster_last_reply:
            self.ui.write(self.tr("app.syster.train.no_exchange"))
            return

        score = 0.0
        notes = ""
        if action in {"up", "good", "like", "+"}:
            score = 1.0
            notes = " ".join(args[1:]).strip() or "manual_positive"
        elif action in {"down", "bad", "dislike", "-"}:
            score = 0.0
            notes = " ".join(args[1:]).strip() or "manual_negative"
        elif action == "score":
            if len(args) < 2:
                self.ui.write(self.tr("app.syster.train.usage"))
                return
            token = args[1].strip().replace(",", ".")
            try:
                score = float(token)
            except ValueError:
                self.ui.write(self.tr("app.syster.train.invalid"))
                return
            if score < 0.0 or score > 1.0:
                self.ui.write(self.tr("app.syster.train.invalid"))
                return
            notes = " ".join(args[2:]).strip() or "manual_score"
        else:
            self.ui.write(self.tr("app.syster.train.usage"))
            return

        self.syster.record_feedback(
            prompt=self.syster_last_prompt,
            reply=self.syster_last_reply,
            score=score,
            notes=notes,
        )
        self._record_syster_event(
            "syster_feedback",
            {"score": score, "notes": notes[:140]},
        )
        self.ui.write(self.tr("app.syster.train.saved", score=f"{score:.2f}"))

    def _build_syster_context(self) -> SysterContext:
        digest = self.syster_store.get_context_digest(commands_limit=8, events_limit=8)
        recent_commands_raw = digest.get("recent_commands", [])
        recent_events_raw = digest.get("recent_events", [])
        recent_commands = (
            [str(item)[:160] for item in recent_commands_raw if isinstance(item, str)]
            if isinstance(recent_commands_raw, list)
            else []
        )
        recent_events = (
            [str(item)[:120] for item in recent_events_raw if isinstance(item, str)]
            if isinstance(recent_events_raw, list)
            else []
        )
        best_scores = {
            "snake_best_score": self.get_stat("snake_best_score"),
            "snake_best_level": self.get_stat("snake_best_level"),
            "rogue_best_depth": self.get_stat("rogue_best_depth"),
            "rogue_best_gold": self.get_stat("rogue_best_gold"),
            "rogue_best_kills": self.get_stat("rogue_best_kills"),
            "hangman_wins": self.get_stat("hangman_wins"),
            "codebreaker_wins": self.get_stat("codebreaker_wins"),
            "physics_best_score": self.get_stat("physics_best_score"),
        }
        unlocked_themes = [
            name
            for name, preset in self.theme_presets.items()
            if self._is_theme_unlocked(preset)
        ]
        player_name = self._sanitize_player_name(self.config.player_name) or "guest"
        return SysterContext(
            slot_id=self.current_slot.slot_id,
            route_name=self.current_slot.route_name,
            story_page=self.current_slot.story_page,
            story_total=self.current_slot.story_total,
            achievements_unlocked=unlocked_count(self.current_slot.flags),
            achievements_total=len(ACHIEVEMENTS),
            rogue_runs=self.get_stat("rogue_runs"),
            rogue_wins=self.get_stat("rogue_wins"),
            rogue_best_depth=self.get_stat("rogue_best_depth"),
            last_command=self.last_command,
            player_name=player_name,
            language=self.i18n.active_language,
            active_theme=self._detect_theme_name(self.config.bg_color, self.config.fg_color),
            sound_enabled=bool(self.config.sound),
            graphics_level=self.config.graphics,
            ui_scale=float(self.config.ui_scale),
            recent_commands=recent_commands,
            recent_events=recent_events,
            best_scores=best_scores,
            unlocked_themes=unlocked_themes,
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
                player=self._player_name(),
            )
        )

        if section in {"all", "system"} and self.syster_enabled:
            ollama_ok, ollama_reason = self.syster.get_ollama_status(force_probe=False)
            if not self.syster.ollama_enabled:
                ollama_state = "OFF"
            else:
                ollama_state = "ONLINE" if ollama_ok else "OFFLINE"
            self.ui.write(
                self.tr(
                    "app.doctor.syster_ai",
                    state=ollama_state,
                    model=self.syster.ollama_model,
                    host=(self.syster.ollama_host or "-"),
                    reason=ollama_reason,
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
            for item in self.domain_supervisor.snapshots():
                self.ui.write(
                    self.tr(
                        "app.doctor.domain",
                        domain=item.domain,
                        state=item.state.value.upper(),
                        failures=item.total_failures,
                        streak=item.failure_streak,
                        skipped=item.skipped_calls,
                    )
                )

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

    def _handle_assets(self, args: list[str]) -> None:
        packs = {
            "rogue": self.package_dir / "assets" / "rogue",
            "snake": self.package_dir / "assets" / "snake",
            "ttt": self.package_dir / "assets" / "ttt",
        }

        def asset_count(path: Path) -> int:
            return len(list(path.glob("*.png"))) if path.exists() else 0

        if not args:
            self.ui.write(self.tr("app.assets.usage"))
            self.ui.write(
                self.tr(
                    "app.assets.status",
                    rogue_path=str(packs["rogue"]),
                    rogue_count=asset_count(packs["rogue"]),
                    snake_path=str(packs["snake"]),
                    snake_count=asset_count(packs["snake"]),
                    ttt_path=str(packs["ttt"]),
                    ttt_count=asset_count(packs["ttt"]),
                )
            )
            return

        action = args[0].strip().lower()
        if action in {"status", "info"}:
            self.ui.write(
                self.tr(
                    "app.assets.status",
                    rogue_path=str(packs["rogue"]),
                    rogue_count=asset_count(packs["rogue"]),
                    snake_path=str(packs["snake"]),
                    snake_count=asset_count(packs["snake"]),
                    ttt_path=str(packs["ttt"]),
                    ttt_count=asset_count(packs["ttt"]),
                )
            )
            return

        if action in {"reload", "refresh"}:
            self.ui.reload_visual_assets()
            self.ui.write(self.tr("app.assets.reload"))
            return

        self.ui.write(self.tr("app.assets.usage"))

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
        self._record_syster_event("achievement_unlocked", {"id": achievement_id, "title": title})
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
        self._queue_cloud_sync(reason="slot_switched", force=True)

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

    def _handle_user(self, args: list[str]) -> None:
        if not args:
            self.ui.write(self.tr("app.player.current", name=self._player_name()))
            self.ui.write(self.tr("app.player.usage"))
            return

        raw = " ".join(args).strip()
        lowered = raw.lower()
        if lowered in {"guest", "invitado", "convidado", "off", "none"}:
            self.config.player_name = ""
            self._apply_player_identity()
            self._save_config()
            self.ui.write(self.tr("app.player.guest_set"))
            self._queue_cloud_sync(reason="player_guest")
            return

        name = self._sanitize_player_name(raw)
        if not name:
            self.ui.write(self.tr("app.player.invalid"))
            self.ui.write(self.tr("app.player.usage"))
            return

        self.config.player_name = name
        self._apply_player_identity()
        self._save_config()
        self.ui.write(self.tr("app.player.updated", name=name))
        self.ui.push_notification(
            self.tr("app.player.toast.title"),
            self.tr("app.player.toast.body", name=name),
            icon_key="mdi:account",
        )
        self._queue_cloud_sync(reason="player_updated", force=True)

    @staticmethod
    def _today_key() -> str:
        return time.strftime("%Y%m%d", time.localtime())

    @staticmethod
    def _daily_seed(game: str, date_key: str) -> int:
        token = f"gethes-daily:{date_key}:{game}:v1"
        value = 0
        for ch in token:
            value = ((value * 131) + ord(ch)) & 0xFFFFFFFF
        return value

    @staticmethod
    def _daily_stat_key(date_key: str, game: str, metric: str) -> str:
        return f"daily_{date_key}_{game}_{metric}"

    def _advance_daily_streak(self, scope: str, date_key: str) -> int:
        date_int = normalize_date_key(date_key)
        if date_int <= 0:
            return self.get_stat(f"daily_streak_{scope}", 0)
        last_key = f"daily_last_{scope}_date"
        streak_key = f"daily_streak_{scope}"
        previous_date = self.get_stat(last_key, 0)
        previous_streak = self.get_stat(streak_key, 0)
        new_streak = next_daily_streak(previous_date, date_int, previous_streak)
        self.set_stat(last_key, date_int)
        self.set_stat(streak_key, new_streak)
        return new_streak

    def _is_daily_game_completed(self, date_key: str, game: str) -> bool:
        return self.get_stat(self._daily_stat_key(date_key, game, "completed"), 0) > 0

    def _mark_daily_completion(self, game: str, date_key: str) -> tuple[bool, int, int, bool]:
        game_done_key = self._daily_stat_key(date_key, game, "completed")
        if self.get_stat(game_done_key, 0) > 0:
            game_streak = self.get_stat(f"daily_streak_{game}", 0)
            overall_streak = self.get_stat("daily_streak_any", 0)
            dual_ready = self._is_daily_game_completed(date_key, "snake") and self._is_daily_game_completed(
                date_key,
                "rogue",
            )
            return False, game_streak, overall_streak, dual_ready

        self.set_stat(game_done_key, 1)
        self.bump_stat("daily_completed_total", 1)
        game_streak = self._advance_daily_streak(game, date_key)

        any_done_key = self._daily_stat_key(date_key, "any", "completed")
        if self.get_stat(any_done_key, 0) > 0:
            overall_streak = self.get_stat("daily_streak_any", 0)
        else:
            self.set_stat(any_done_key, 1)
            overall_streak = self._advance_daily_streak("any", date_key)

        dual_ready = self._is_daily_game_completed(date_key, "snake") and self._is_daily_game_completed(
            date_key,
            "rogue",
        )
        return True, game_streak, overall_streak, dual_ready

    def _clear_daily_session(self) -> None:
        self.daily_active_game = ""
        self.daily_active_date = ""
        self.daily_active_seed = 0

    def _start_daily_challenge(self, game: str) -> None:
        date_key = self._today_key()
        seed = self._daily_seed(game, date_key)
        self.daily_active_game = game
        self.daily_active_date = date_key
        self.daily_active_seed = seed
        self.ui.write(self.tr("app.daily.start", game=game, seed=seed, date=date_key))

        if game == "snake":
            self.snake.start(seed=seed)
            return
        if game == "rogue":
            self.roguelike.start(seed=seed)
            return
        self._clear_daily_session()

    def _show_daily_status(self) -> None:
        date_key = self._today_key()
        snake_seed = self._daily_seed("snake", date_key)
        rogue_seed = self._daily_seed("rogue", date_key)
        snake_best = self.get_stat(self._daily_stat_key(date_key, "snake", "best_score"), 0)
        rogue_best_depth = self.get_stat(self._daily_stat_key(date_key, "rogue", "best_depth"), 0)
        rogue_best_gold = self.get_stat(self._daily_stat_key(date_key, "rogue", "best_gold"), 0)

        self.ui.write(self.tr("app.daily.title", date=date_key))
        self.ui.write(self.tr("app.daily.snake_status", seed=snake_seed, best=snake_best))
        self.ui.write(
            self.tr(
                "app.daily.rogue_status",
                seed=rogue_seed,
                depth=rogue_best_depth,
                gold=rogue_best_gold,
            )
        )
        snake_done = "OK" if self._is_daily_game_completed(date_key, "snake") else "--"
        rogue_done = "OK" if self._is_daily_game_completed(date_key, "rogue") else "--"
        self.ui.write(self.tr("app.daily.completed", snake=snake_done, rogue=rogue_done))
        self.ui.write(
            self.tr(
                "app.daily.streaks",
                overall=self.get_stat("daily_streak_any", 0),
                snake=self.get_stat("daily_streak_snake", 0),
                rogue=self.get_stat("daily_streak_rogue", 0),
            )
        )
        if self.daily_active_game:
            self.ui.write(
                self.tr(
                    "app.daily.active",
                    game=self.daily_active_game,
                    seed=self.daily_active_seed,
                )
            )

    def _handle_daily(self, args: list[str]) -> None:
        action = args[0].strip().lower() if args else "status"

        if action in {"status", "state", "info"}:
            self._show_daily_status()
            self.ui.write(self.tr("app.daily.usage"))
            return

        if action in {"snake", "s"}:
            self._start_daily_challenge("snake")
            return

        if action in {"rogue", "roguelike", "dungeon", "r"}:
            self._start_daily_challenge("rogue")
            return

        self.ui.write(self.tr("app.daily.usage"))

    def _handle_snake_command(self, args: list[str]) -> None:
        self._clear_daily_session()

        mode = "classic"
        difficulty = "normal"
        apples = 0
        room = self.cloud_snake_arena_room

        for raw in args:
            token = raw.strip().lower()
            if not token:
                continue
            if token in {
                "easy",
                "facil",
                "fácil",
                "normal",
                "hard",
                "dificil",
                "difícil",
                "insane",
                "extreme",
                "impossible",
                "nightmare",
            }:
                difficulty = token
                continue
            if token in {"classic", "clasico", "clásico"}:
                mode = "classic"
                continue
            if token in {"multi", "multimanzana", "multiapple", "manzanas", "apples"}:
                mode = "multiapple"
                continue
            if token in {"online", "arena", "multiplayer", "mp", "slither", "slitherio", "agar", "agario", "io"}:
                mode = "online"
                continue
            if token.startswith("apples="):
                value = token.split("=", 1)[1].strip()
                if value.isdigit():
                    apples = max(2, min(7, int(value)))
                continue
            if token.startswith("room=") or token.startswith("sala=") or token.startswith("server="):
                value = token.split("=", 1)[1].strip()
                cleaned = self._sanitize_snake_room(value)
                if cleaned:
                    room = cleaned
                continue
            if token.isdigit():
                apples = max(2, min(7, int(token)))

        if mode == "online" and (not self.config.cloud_enabled or not self.cloud.is_linked()):
            self.ui.write(self.tr("app.cloud.not_linked"))
            self.ui.write("Tip: `cloud link <url>` and login to enable online Snake arena.")
            mode = "classic"
        if mode == "online":
            self.cloud_snake_arena_room = self._sanitize_snake_room(room)
            self._reset_snake_arena_runtime(clear_cache=True)
            self.ui.write(self.tr("game.snake.online_room_joined", room=self.cloud_snake_arena_room))
        else:
            self._reset_snake_arena_runtime(clear_cache=False)

        self._run_domain(
            "games",
            "snake_start",
            lambda: self.snake.start(
                difficulty=difficulty,
                mode=mode,
                apples=apples,
            ),
        )

    def _handle_cloud(self, args: list[str]) -> None:
        action = args[0].strip().lower() if args else "status"

        if action in {"status", "state"}:
            self._show_cloud_status()
            return

        if action in {"link", "set"}:
            if not args[1:]:
                self.ui.write(self.tr("app.cloud.link_usage"))
                return
            endpoint = args[1].strip()
            token = " ".join(args[2:]).strip() if len(args) >= 3 else ""
            normalized = CloudSyncClient.normalize_endpoint(endpoint)
            if not (normalized.startswith("http://") or normalized.startswith("https://")):
                self.ui.write(self.tr("app.cloud.endpoint_invalid"))
                self.ui.write(self.tr("app.cloud.link_usage"))
                return
            self.cloud.configure(
                normalized,
                token or self.config.cloud_api_key,
                self.config.cloud_session_token,
            )
            self.config.cloud_endpoint = self.cloud.endpoint
            if token:
                self.config.cloud_api_key = token
            self.config.cloud_enabled = True
            self._save_config()
            self.ui.write(self.tr("app.cloud.linked", endpoint=self.cloud.endpoint))
            self._queue_cloud_sync(reason="cloud_link", force=True)
            if not self.cloud.has_session():
                self.ui.write(self.tr("app.cloud.auth_hint"))
            return

        if action in {"off", "unlink", "disable"}:
            self.cloud.configure("", "", "")
            self.config.cloud_endpoint = ""
            self.config.cloud_enabled = False
            self.config.cloud_session_token = ""
            self.config.cloud_auth_username = ""
            self.config.cloud_auth_email = ""
            self.cloud_auth_user = {}
            self._save_config()
            self.ui.write(self.tr("app.cloud.disabled"))
            return

        if action in {"key", "token"}:
            if len(args) < 2:
                self.ui.write(self.tr("app.cloud.key_usage"))
                return
            value = " ".join(args[1:]).strip()
            if value.lower() in {"off", "none", "clear"}:
                self.cloud.configure(self.cloud.endpoint, "", self.cloud.session_token)
                self.config.cloud_api_key = ""
                self._save_config()
                self.ui.write(self.tr("app.cloud.key_cleared"))
                return
            self.cloud.configure(self.cloud.endpoint, value, self.cloud.session_token)
            self.config.cloud_api_key = value
            self._save_config()
            self.ui.write(self.tr("app.cloud.key_set", value=self.cloud.masked_key()))
            return

        if action in {"sync", "push"}:
            if not self.config.cloud_enabled or not self.cloud.is_linked():
                self.ui.write(self.tr("app.cloud.not_linked"))
                return
            self._queue_cloud_sync(reason="manual_sync", force=True, user_feedback=True)
            return

        if action in {"online", "presence"}:
            if not self.config.cloud_enabled or not self.cloud.is_linked():
                self.ui.write(self.tr("app.cloud.not_linked"))
                return
            self._queue_cloud_presence(user_feedback=True)
            return

        if action in {"leaderboard", "ranking", "rank", "top"}:
            if not self.config.cloud_enabled or not self.cloud.is_linked():
                self.ui.write(self.tr("app.cloud.not_linked"))
                return

            game_token = "snake"
            limit = 10
            if len(args) >= 2:
                token_2 = args[1].strip().lower()
                if token_2.isdigit():
                    limit = max(1, min(50, int(token_2)))
                else:
                    game_token = token_2
            if len(args) >= 3:
                token_3 = args[2].strip()
                if token_3.isdigit():
                    limit = max(1, min(50, int(token_3)))
                else:
                    self.ui.write(self.tr("app.cloud.leaderboard_usage"))
                    return

            game = self._normalize_leaderboard_game(game_token)
            if not game:
                self.ui.write(self.tr("app.cloud.leaderboard_game_invalid"))
                self.ui.write(self.tr("app.cloud.leaderboard_usage"))
                return

            self._queue_cloud_leaderboard(game=game, limit=limit, user_feedback=True)
            return

        if action in {"interval", "every", "timer"}:
            if len(args) < 2:
                self.ui.write(self.tr("app.cloud.interval_usage"))
                return
            raw = args[1].strip().replace(",", ".")
            if not raw.isdigit():
                self.ui.write(self.tr("app.cloud.interval_invalid"))
                return
            seconds = int(raw)
            if seconds < 20 or seconds > 600:
                self.ui.write(self.tr("app.cloud.interval_range"))
                return
            self.config.cloud_sync_interval_seconds = seconds
            self.cloud_sync_cooldown = float(seconds)
            self.cloud_sync_elapsed = 0.0
            self._save_config()
            self.ui.write(self.tr("app.cloud.interval_set", seconds=seconds))
            return

        if action in {"newsinterval", "feedinterval"}:
            if len(args) < 2:
                self.ui.write(self.tr("app.cloud.news_interval_usage"))
                return
            raw = args[1].strip().replace(",", ".")
            if not raw.isdigit():
                self.ui.write(self.tr("app.cloud.news_interval_invalid"))
                return
            seconds = int(raw)
            if seconds < 60 or seconds > 3600:
                self.ui.write(self.tr("app.cloud.news_interval_range"))
                return
            self.config.cloud_news_poll_seconds = seconds
            self.cloud_news_cooldown = float(seconds)
            self.cloud_news_elapsed = 0.0
            self._save_config()
            self.ui.write(self.tr("app.cloud.news_interval_set", seconds=seconds))
            return

        if action in {"news", "feed"}:
            limit = 8
            if len(args) >= 2 and args[1].strip().isdigit():
                limit = max(1, min(30, int(args[1].strip())))
            if not self.config.cloud_enabled or not self.cloud.is_linked():
                self.ui.write(self.tr("app.cloud.not_linked"))
                return
            if not self.cloud.has_session():
                self.ui.write(self.tr("app.auth.not_logged"))
                return
            self._queue_cloud_news(limit=limit, mark_seen=True, user_feedback=True)
            return

        if action in {"auth", "account"}:
            self._handle_auth(args[1:])
            return

        self.ui.write(self.tr("app.cloud.usage"))

    def _normalize_leaderboard_game(self, token: str) -> str:
        value = token.strip().lower()
        if value in {"snake", "s"}:
            return "snake"
        if value in {"rogue", "roguelike", "rogelike", "dungeon", "r"}:
            return "rogue"
        if value in {"hangman", "ahorcado", "forca", "h"}:
            return "hangman"
        return ""

    def _leaderboard_cache(self, game: str) -> list[dict[str, object]]:
        token = game.strip().lower()
        if token == "rogue":
            return self.cloud_last_rogue_leaderboard
        if token == "hangman":
            return self.cloud_last_hangman_leaderboard
        return self.cloud_last_snake_leaderboard

    def _active_live_leaderboard_game(self) -> str:
        if self.snake.active:
            return "snake"
        if self.roguelike.active:
            return "rogue"
        if self.hangman.active:
            return "hangman"
        return ""

    def _update_live_leaderboard(self, dt: float) -> None:
        game = self._active_live_leaderboard_game()
        if not game:
            self.cloud_live_leaderboard_elapsed = 0.0
            self.cloud_live_leaderboard_game = ""
            self._reset_snake_arena_runtime(clear_cache=False)
            return

        if game != "snake":
            self._reset_snake_arena_runtime(clear_cache=False)

        if game == "snake" and self.snake.active and self.snake.mode == "online":
            self._update_snake_online_arena(dt)
            return

        if not self.config.cloud_enabled or not self.cloud.is_linked():
            return

        if self.cloud_live_leaderboard_game != game:
            self.cloud_live_leaderboard_game = game
            self.cloud_live_leaderboard_elapsed = self.cloud_live_leaderboard_interval

        self.cloud_live_leaderboard_elapsed += dt
        if self.cloud_live_leaderboard_elapsed < self.cloud_live_leaderboard_interval:
            return
        self.cloud_live_leaderboard_elapsed = 0.0
        self._queue_cloud_leaderboard(game=game, limit=6, user_feedback=False)

    def _reset_snake_arena_runtime(self, *, clear_cache: bool) -> None:
        self.cloud_snake_arena_elapsed = 0.0
        self.cloud_snake_arena_keepalive_elapsed = 0.0
        self.cloud_snake_arena_last_state = (0, 0, 1, -1, -1)
        self.cloud_snake_arena_fail_streak = 0
        self.cloud_snake_arena_last_rtt_ms = 0
        self.cloud_snake_arena_last_ok_at = 0.0
        if clear_cache:
            self.cloud_last_snake_arena = []
            self.cloud_last_snake_arena_players_online = 0

    def _update_snake_online_arena(self, dt: float) -> None:
        if not self.snake.active or self.snake.mode != "online":
            self._reset_snake_arena_runtime(clear_cache=False)
            return
        if not self.config.cloud_enabled or not self.cloud.is_linked():
            return
        if not self.snake.snake:
            return

        head_x, head_y = self.snake.snake[0]
        current_state = (
            int(self.snake.score),
            int(len(self.snake.snake)),
            max(1, int(self.snake.level)),
            int(head_x),
            int(head_y),
        )
        changed = current_state != self.cloud_snake_arena_last_state
        interval = self.cloud_snake_arena_fast_interval if changed else self.cloud_snake_arena_idle_interval

        self.cloud_snake_arena_elapsed += dt
        self.cloud_snake_arena_keepalive_elapsed += dt
        if self.cloud_snake_arena_elapsed < interval:
            return
        if self.cloud_snake_arena_running:
            return
        if not changed and self.cloud_snake_arena_keepalive_elapsed < self.cloud_snake_arena_keepalive_interval:
            return

        self.cloud_snake_arena_elapsed = 0.0
        self.cloud_snake_arena_keepalive_elapsed = 0.0
        self._queue_cloud_snake_arena_push(
            score=current_state[0],
            length=current_state[1],
            level=current_state[2],
            head_x=current_state[3],
            head_y=current_state[4],
            room=self.cloud_snake_arena_room,
            mode=self.snake.mode,
        )

    def _queue_cloud_snake_arena_push(
        self,
        *,
        score: int,
        length: int,
        level: int,
        head_x: int,
        head_y: int,
        room: str = "global",
        mode: str = "online",
    ) -> bool:
        if not self.config.cloud_enabled or not self.cloud.is_linked():
            return False
        if self.cloud_snake_arena_running:
            return False
        if self.cloud_auth_running:
            return False

        room_token = room.strip().lower() or "global"
        mode_token = mode.strip().lower() or "online"
        payload_state = (int(score), int(length), int(level), int(head_x), int(head_y))
        self.cloud_snake_arena_running = True

        def worker() -> None:
            started = time.monotonic()
            response = self.cloud.push_snake_arena_state(
                install_id=self.config.install_id,
                player_name=self._player_name(),
                score=payload_state[0],
                length=payload_state[1],
                level=payload_state[2],
                x=payload_state[3],
                y=payload_state[4],
                mode=mode_token,
                room=room_token,
            )
            self.update_events.put(
                (
                    "cloud_snake_arena_done",
                    {
                        "ok": response.ok,
                        "status_code": response.status_code,
                        "message": response.message,
                        "payload": response.payload,
                        "state": payload_state,
                        "room": room_token,
                        "rtt_ms": max(1, int((time.monotonic() - started) * 1000)),
                    },
                )
            )

        threading.Thread(target=worker, daemon=True, name="gethes-cloud-snake-arena").start()
        return True

    def get_snake_online_player_count(self) -> int:
        return max(0, int(self.cloud_last_snake_arena_players_online))

    def get_snake_online_room(self) -> str:
        return self._sanitize_snake_room(self.cloud_snake_arena_room)

    def get_snake_online_sync_meta(self) -> tuple[int, int, int]:
        ping_ms = max(0, int(self.cloud_snake_arena_last_rtt_ms))
        age_seconds = 0
        if self.cloud_snake_arena_last_ok_at > 0:
            age_seconds = max(0, int(time.monotonic() - self.cloud_snake_arena_last_ok_at))
        fail_streak = max(0, int(self.cloud_snake_arena_fail_streak))
        return (ping_ms, age_seconds, fail_streak)

    def get_snake_online_rank(self) -> int:
        own = self.config.install_id.strip().lower().replace("-", "")
        for row in self.cloud_last_snake_arena:
            if not isinstance(row, dict):
                continue
            install = str(row.get("install_id", "")).strip().lower().replace("-", "")
            if install and install == own:
                return max(0, int(row.get("rank", 0) or 0))
        return 0

    def get_snake_online_ghosts(self) -> list[tuple[int, int, str]]:
        if not (self.snake.active and self.snake.mode == "online"):
            return []
        own = self.config.install_id.strip().lower().replace("-", "")
        ghosts: list[tuple[int, int, str]] = []
        for row in self.cloud_last_snake_arena:
            if not isinstance(row, dict):
                continue
            install = str(row.get("install_id", "")).strip().lower().replace("-", "")
            if install and install == own:
                continue
            x = int(row.get("x", -1) or -1)
            y = int(row.get("y", -1) or -1)
            if x < 0 or y < 0:
                continue
            ghosts.append((x, y, str(row.get("player_name", "Guest") or "Guest")))
            if len(ghosts) >= 10:
                break
        return ghosts

    def set_live_leaderboard_panel(self, game: str, current_lines: list[str] | None = None) -> None:
        token = self._normalize_leaderboard_game(game)
        if not token:
            self.ui.clear_side_panel()
            return

        lines: list[str] = []
        if current_lines:
            lines.extend([str(item).strip() for item in current_lines if str(item).strip()])
            if lines:
                lines.append("")

        rows = self._leaderboard_cache(token)
        if token == "rogue":
            title = self.tr("app.cloud.sidebar.rogue.title")
            if rows:
                for row in rows[:5]:
                    lines.append(
                        self.tr(
                            "app.cloud.sidebar.rogue.item",
                            rank=int(row.get("rank", 0) or 0),
                            name=str(row.get("player_name", "") or "Guest"),
                            depth=int(row.get("rogue_best_depth", 0) or 0),
                            gold=int(row.get("rogue_best_gold", 0) or 0),
                            kills=int(row.get("rogue_best_kills", 0) or 0),
                        )
                    )
            else:
                lines.append(self.tr("app.cloud.sidebar.empty"))
            self.ui.set_side_panel(title=title, lines=lines)
            return

        if token == "hangman":
            title = self.tr("app.cloud.sidebar.hangman.title")
            if rows:
                for row in rows[:5]:
                    lines.append(
                        self.tr(
                            "app.cloud.sidebar.hangman.item",
                            rank=int(row.get("rank", 0) or 0),
                            name=str(row.get("player_name", "") or "Guest"),
                            wins=int(row.get("hangman_wins", 0) or 0),
                            games=int(row.get("hangman_games", 0) or 0),
                            clean=int(row.get("hangman_best_errors_left", 0) or 0),
                        )
                    )
            else:
                lines.append(self.tr("app.cloud.sidebar.empty"))
            self.ui.set_side_panel(title=title, lines=lines)
            return

        if self.snake.active and self.snake.mode == "online":
            title = self.tr("app.cloud.sidebar.snake.online_title")
            lines.append(
                self.tr(
                    "app.cloud.sidebar.snake.online_count",
                    count=self.get_snake_online_player_count(),
                    room=self.get_snake_online_room(),
                )
            )
            ping_ms, age_seconds, fail_streak = self.get_snake_online_sync_meta()
            lines.append(
                self.tr(
                    "app.cloud.sidebar.snake.online_sync",
                    ping=ping_ms,
                    sync=age_seconds,
                    fails=fail_streak,
                )
            )
            rank = self.get_snake_online_rank()
            if rank > 0:
                lines.append(self.tr("app.cloud.sidebar.snake.online_rank", rank=rank))
            lines.append("")
            arena_rows = [row for row in self.cloud_last_snake_arena if isinstance(row, dict)]
            if arena_rows:
                for row in arena_rows[:6]:
                    rank = int(row.get("rank", 0) or 0)
                    name = str(row.get("player_name", "") or "Guest")
                    score = int(row.get("score", 0) or 0)
                    level = int(row.get("level", 1) or 1)
                    length = int(row.get("length", 0) or 0)
                    lines.append(f"#{rank} {name}  S:{score} L:{level} LEN:{length}")
            else:
                lines.append(self.tr("app.cloud.sidebar.snake.online_searching"))
            self.ui.set_side_panel(title=title, lines=lines)
            return

        title = self.tr("app.cloud.sidebar.snake.title")
        if rows:
            for row in rows[:5]:
                lines.append(
                    self.tr(
                        "app.cloud.sidebar.snake.item",
                        rank=int(row.get("rank", 0) or 0),
                        name=str(row.get("player_name", "") or "Guest"),
                        score=int(row.get("snake_best_score", 0) or 0),
                        level=int(row.get("snake_best_level", 0) or 0),
                        length=int(row.get("snake_longest_length", 0) or 0),
                    )
                )
        else:
            lines.append(self.tr("app.cloud.sidebar.empty"))
        self.ui.set_side_panel(title=title, lines=lines)

    def clear_live_leaderboard_panel(self) -> None:
        self.ui.clear_side_panel()

    def _refresh_active_game_side_panel(self) -> None:
        if self.snake.active:
            self.set_live_leaderboard_panel(
                "snake",
                current_lines=[
                    self.tr("game.snake.title", score=self.snake.score, level=self.snake.level),
                    self.tr("game.snake.foods", count=self.snake.foods_eaten),
                ],
            )
            return
        if self.roguelike.active:
            self.set_live_leaderboard_panel(
                "rogue",
                current_lines=[
                    self.tr("game.rogue.title", depth=self.roguelike.depth, max_depth=self.roguelike.max_depth),
                    self.tr(
                        "game.rogue.stats",
                        hp=max(0, self.roguelike.hp),
                        max_hp=self.roguelike.max_hp,
                        atk=self.roguelike.atk,
                        potions=self.roguelike.potions,
                        gold=self.roguelike.gold,
                        kills=self.roguelike.kills,
                        enemies=len(self.roguelike.enemies),
                        guard=self.roguelike.guard_charges,
                    ),
                ],
            )
            return
        if self.hangman.active:
            self.set_live_leaderboard_panel(
                "hangman",
                current_lines=[
                    self.tr("game.hangman.title", mode=self.hangman.mode),
                    self.tr("game.hangman.left", count=max(0, self.hangman.max_errors - self.hangman.errors)),
                ],
            )

    def _show_cloud_status(self) -> None:
        enabled = self.config.cloud_enabled and self.cloud.is_linked()
        self.ui.write(
            self.tr(
                "app.cloud.status",
                enabled=("ON" if enabled else "OFF"),
                endpoint=(self.cloud.endpoint or "-"),
                api_key=self.cloud.masked_key(),
                state=self.cloud_last_status,
            )
        )
        self.ui.write(
            self.tr(
                "app.cloud.auth_state",
                state=("ON" if self.cloud.has_session() else "OFF"),
                user=(self.config.cloud_auth_username or "-"),
            )
        )
        self.ui.write(
            self.tr(
                "app.cloud.intervals",
                sync=self.config.cloud_sync_interval_seconds,
                news=self.config.cloud_news_poll_seconds,
            )
        )
        if self.cloud_last_message:
            self.ui.write(self.tr("app.cloud.last_message", value=self.cloud_last_message))
        if self.cloud_last_sync_at > 0:
            self.ui.write(
                self.tr(
                    "app.cloud.last_sync",
                    seconds=max(0, int(time.monotonic() - self.cloud_last_sync_at)),
                )
            )
        if self.cloud_last_presence:
            online = int(self.cloud_last_presence.get("players_online", 0) or 0)
            users = int(self.cloud_last_presence.get("registered_users", 0) or 0)
            self.ui.write(self.tr("app.cloud.presence", online=online, users=users))
        self.ui.write(self.tr("app.cloud.usage"))

    @staticmethod
    def _sanitize_auth_username(raw: str) -> str:
        value = raw.strip()
        if not value:
            return ""
        cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-", "."})
        return cleaned[:24]

    @staticmethod
    def _sanitize_auth_email(raw: str) -> str:
        token = raw.strip().lower()
        if len(token) > 190:
            return ""
        if "@" not in token or "." not in token:
            return ""
        local, _, domain = token.partition("@")
        if not local or not domain or "." not in domain:
            return ""
        return token

    def _show_auth_status(self) -> None:
        logged = self.cloud.has_session() and bool(self.config.cloud_auth_username.strip())
        self.ui.write(
            self.tr(
                "app.auth.status",
                state=("ON" if logged else "OFF"),
                username=(self.config.cloud_auth_username or "-"),
                email=(self.config.cloud_auth_email or "-"),
            )
        )
        self.ui.write(self.tr("app.auth.usage"))

    def _handle_auth(self, args: list[str]) -> None:
        action = args[0].strip().lower() if args else "status"

        if action in {"status", "state"}:
            self._show_auth_status()
            return

        if action in {"setup", "onboarding"}:
            if not self.config.cloud_enabled or not self.cloud.is_linked():
                self.ui.write(self.tr("app.cloud.not_linked"))
                return
            if self.cloud.has_session():
                self.ui.write(self.tr("app.auth.me_ok", username=self.config.cloud_auth_username or "-"))
                return
            self._start_cloud_auth_setup()
            return

        if action in {"me", "whoami"}:
            if not self.config.cloud_enabled or not self.cloud.is_linked():
                self.ui.write(self.tr("app.cloud.not_linked"))
                return
            if not self.cloud.has_session():
                self.ui.write(self.tr("app.auth.not_logged"))
                return
            self._queue_cloud_auth(action="me", user_feedback=True)
            return

        if action in {"register", "signup"}:
            if not self.config.cloud_enabled or not self.cloud.is_linked():
                self.ui.write(self.tr("app.cloud.not_linked"))
                return
            if len(args) < 4:
                self.ui.write(self.tr("app.auth.register_usage"))
                return
            username = self._sanitize_auth_username(args[1])
            email = self._sanitize_auth_email(args[2])
            password = " ".join(args[3:]).strip()
            if not username:
                self.ui.write(self.tr("app.auth.username_invalid"))
                return
            if not email:
                self.ui.write(self.tr("app.auth.email_invalid"))
                return
            if len(password) < 8:
                self.ui.write(self.tr("app.auth.password_invalid"))
                return
            if not self._queue_cloud_auth(
                action="register",
                username=username,
                email=email,
                password=password,
                user_feedback=True,
            ):
                self.ui.write(self.tr("app.auth.busy"))
            return

        if action in {"login", "signin"}:
            if not self.config.cloud_enabled or not self.cloud.is_linked():
                self.ui.write(self.tr("app.cloud.not_linked"))
                return
            if len(args) < 3:
                self.ui.write(self.tr("app.auth.login_usage"))
                return
            login = args[1].strip()
            password = " ".join(args[2:]).strip()
            if not login or len(password) < 8:
                self.ui.write(self.tr("app.auth.login_usage"))
                return
            if not self._queue_cloud_auth(
                action="login",
                login=login,
                password=password,
                user_feedback=True,
            ):
                self.ui.write(self.tr("app.auth.busy"))
            return

        if action in {"logout", "off"}:
            if not self.config.cloud_enabled or not self.cloud.is_linked():
                self.ui.write(self.tr("app.cloud.not_linked"))
                return
            if not self.cloud.has_session():
                self.ui.write(self.tr("app.auth.not_logged"))
                return
            if not self._queue_cloud_auth(action="logout", user_feedback=True):
                self.ui.write(self.tr("app.auth.busy"))
            return

        self.ui.write(self.tr("app.auth.usage"))

    def _queue_cloud_auth(
        self,
        *,
        action: str,
        username: str = "",
        email: str = "",
        login: str = "",
        password: str = "",
        user_feedback: bool = False,
        from_setup: bool = False,
    ) -> bool:
        if not self.config.cloud_enabled or not self.cloud.is_linked():
            return False
        if self.cloud_auth_running:
            return False

        self.cloud_auth_running = True
        if user_feedback:
            if action == "register":
                self.ui.write(self.tr("app.auth.registering"))
            elif action == "login":
                self.ui.write(self.tr("app.auth.logging_in"))
            elif action == "logout":
                self.ui.write(self.tr("app.auth.logging_out"))
            elif action == "me":
                self.ui.write(self.tr("app.auth.checking"))

        def worker() -> None:
            if action == "register":
                response = self.cloud.register(
                    username=username,
                    email=email,
                    password=password,
                    install_id=self.config.install_id,
                )
            elif action == "login":
                response = self.cloud.login(
                    login=login,
                    password=password,
                    install_id=self.config.install_id,
                )
            elif action == "logout":
                response = self.cloud.logout()
            elif action == "me":
                response = self.cloud.fetch_me()
            else:
                response = self.cloud.fetch_me()
            self.update_events.put(
                (
                    "cloud_auth_done",
                    {
                        "ok": response.ok,
                        "status_code": response.status_code,
                        "message": response.message,
                        "payload": response.payload,
                        "action": action,
                        "user_feedback": user_feedback,
                        "from_setup": from_setup,
                    },
                )
            )

        threading.Thread(target=worker, daemon=True, name=f"gethes-cloud-auth-{action}").start()
        return True

    def _build_cloud_payload(self, reason: str) -> dict[str, object]:
        active_theme = self._detect_theme_name(self.config.bg_color, self.config.fg_color)
        syster_training = self.syster_store.get_cloud_training_payload(
            feedback_limit=6,
            memory_limit=5,
            intents_limit=6,
        )
        payload: dict[str, object] = {
            "install_id": self.config.install_id,
            "player_name": self._player_name(),
            "reason": reason,
            "version": __version__,
            "timestamp_unix": int(time.time()),
            "profile": {
                "slot_id": self.current_slot.slot_id,
                "route_name": self.current_slot.route_name,
                "story_page": self.current_slot.story_page,
                "story_total": self.current_slot.story_total,
                "achievements_unlocked": unlocked_count(self.current_slot.flags),
                "achievements_total": len(ACHIEVEMENTS),
            },
            "scores": {
                "snake_best_score": self.get_stat("snake_best_score"),
                "snake_best_level": self.get_stat("snake_best_level"),
                "snake_longest_length": self.get_stat("snake_longest_length"),
                "rogue_best_depth": self.get_stat("rogue_best_depth"),
                "rogue_best_gold": self.get_stat("rogue_best_gold"),
                "rogue_best_kills": self.get_stat("rogue_best_kills"),
                "rogue_runs": self.get_stat("rogue_runs"),
                "rogue_wins": self.get_stat("rogue_wins"),
                "hangman_wins": self.get_stat("hangman_wins"),
                "hangman_games": self.get_stat("hangman_games"),
                "hangman_best_errors_left": self.get_stat("hangman_best_errors_left"),
                "daily_completed_total": self.get_stat("daily_completed_total"),
                "daily_streak_any": self.get_stat("daily_streak_any"),
            },
            "preferences": {
                "language_mode": self.config.language,
                "language_active": self.i18n.active_language,
                "graphics": self.config.graphics,
                "sound": bool(self.config.sound),
                "ui_scale": float(self.config.ui_scale),
                "theme": active_theme,
                "theme_fx": {
                    "scan": float(self.config.theme_scan_strength),
                    "glow": float(self.config.theme_glow_strength),
                    "particles": float(self.config.theme_particles_strength),
                },
            },
            "syster": {
                "mode": self.syster.mode,
                "core_enabled": bool(self.syster.ollama_enabled),
                "model": self.syster.ollama_model,
                "training": syster_training,
            },
        }
        if self.cloud.has_session() and self.config.cloud_auth_username.strip():
            payload["auth_user"] = {
                "username": self.config.cloud_auth_username.strip(),
                "email": self.config.cloud_auth_email.strip(),
            }
        return payload

    def _queue_cloud_sync(
        self,
        reason: str,
        force: bool = False,
        user_feedback: bool = False,
    ) -> bool:
        if not self.config.cloud_enabled or not self.cloud.is_linked():
            return False
        if self.cloud_auth_running:
            return False
        if self.cloud_sync_running:
            return False
        if not force and (time.monotonic() - self.cloud_last_sync_at) < 4.0:
            return False

        self.cloud_sync_running = True
        payload = self._build_cloud_payload(reason)
        if user_feedback:
            self.ui.write(self.tr("app.cloud.syncing"))

        def worker() -> None:
            response = self.cloud.push_snapshot(payload)
            self.update_events.put(
                (
                    "cloud_sync_done",
                    {
                        "ok": response.ok,
                        "status_code": response.status_code,
                        "message": response.message,
                        "payload": response.payload,
                        "user_feedback": user_feedback,
                    },
                )
            )

        threading.Thread(target=worker, daemon=True, name="gethes-cloud-sync").start()
        return True

    def _queue_cloud_presence(self, user_feedback: bool = False) -> bool:
        if not self.config.cloud_enabled or not self.cloud.is_linked():
            return False
        if self.cloud_auth_running:
            return False
        if self.cloud_sync_running:
            return False
        self.cloud_sync_running = True
        if user_feedback:
            self.ui.write(self.tr("app.cloud.presence_query"))

        def worker() -> None:
            response = self.cloud.fetch_presence()
            self.update_events.put(
                (
                    "cloud_presence_done",
                    {
                        "ok": response.ok,
                        "status_code": response.status_code,
                        "message": response.message,
                        "payload": response.payload,
                        "user_feedback": user_feedback,
                    },
                )
            )

        threading.Thread(target=worker, daemon=True, name="gethes-cloud-presence").start()
        return True

    def _queue_cloud_leaderboard(
        self,
        *,
        game: str,
        limit: int = 10,
        user_feedback: bool = False,
    ) -> bool:
        game_token = self._normalize_leaderboard_game(game)
        if not game_token:
            return False
        if not self.config.cloud_enabled or not self.cloud.is_linked():
            return False
        if self.cloud_leaderboard_running:
            return False
        if self.cloud_auth_running:
            return False

        limit_value = max(1, min(50, int(limit)))
        self.cloud_leaderboard_running = True
        self.cloud_leaderboard_running_game = game_token
        if user_feedback:
            self.ui.write(self.tr("app.cloud.leaderboard_query", game=game_token.upper()))

        def worker() -> None:
            response = self.cloud.fetch_leaderboard(game=game_token, limit=limit_value)
            self.update_events.put(
                (
                    "cloud_leaderboard_done",
                    {
                        "game": game_token,
                        "ok": response.ok,
                        "status_code": response.status_code,
                        "message": response.message,
                        "payload": response.payload,
                        "user_feedback": user_feedback,
                    },
                )
            )

        threading.Thread(target=worker, daemon=True, name=f"gethes-cloud-{game_token}-leaderboard").start()
        return True

    def _queue_cloud_news(
        self,
        *,
        limit: int = 8,
        mark_seen: bool = False,
        user_feedback: bool = False,
    ) -> bool:
        if not self.config.cloud_enabled or not self.cloud.is_linked():
            return False
        if not self.cloud.has_session():
            return False
        if self.cloud_news_running or self.cloud_auth_running:
            return False
        self.cloud_news_running = True
        if user_feedback:
            self.ui.write(self.tr("app.cloud.news_query"))

        def worker() -> None:
            response = self.cloud.fetch_news(limit=limit, mark_seen=mark_seen, repo=self.update_manager.repo)
            self.update_events.put(
                (
                    "cloud_news_done",
                    {
                        "ok": response.ok,
                        "status_code": response.status_code,
                        "message": response.message,
                        "payload": response.payload,
                        "user_feedback": user_feedback,
                        "mark_seen": mark_seen,
                    },
                )
            )

        threading.Thread(target=worker, daemon=True, name="gethes-cloud-news").start()
        return True

    def _update_cloud_autosync(self, dt: float) -> None:
        if not self.config.cloud_enabled or not self.cloud.is_linked():
            return
        if self.awaiting_player_name:
            return
        if self.awaiting_cloud_auth_setup:
            return
        if self.input_handler is not None:
            return
        if self.snake.active or self.hangman.active or self.physics_lab.active or self.roguelike.active:
            return

        self.cloud_sync_elapsed += dt
        if self.cloud_sync_elapsed < self.cloud_sync_cooldown:
            return
        self.cloud_sync_elapsed = 0.0
        self._queue_cloud_sync(reason="autosync")

    def _update_cloud_news_poll(self, dt: float) -> None:
        if not self.config.cloud_enabled or not self.cloud.is_linked():
            return
        if not self.cloud.has_session():
            return
        if self.awaiting_player_name or self.awaiting_cloud_auth_setup:
            return
        if self.input_handler is not None:
            return
        if self.snake.active or self.physics_lab.active or self.roguelike.active:
            return

        self.cloud_news_elapsed += dt
        if self.cloud_news_elapsed < self.cloud_news_cooldown:
            return
        self.cloud_news_elapsed = 0.0
        self._queue_cloud_news(limit=6, mark_seen=False, user_feedback=False)

    def _record_syster_command(self, raw_command: str, outcome: str = "") -> None:
        self.syster_store.record_command(raw_command, outcome=outcome)

    def _record_syster_event(self, event_type: str, payload: dict[str, object] | None = None) -> None:
        self.syster_store.record_event(event_type, payload)

    def _snapshot_syster_state(self) -> None:
        config_payload = {
            "sound": bool(self.config.sound),
            "graphics": self.config.graphics,
            "language": self.i18n.active_language,
            "theme": self._detect_theme_name(self.config.bg_color, self.config.fg_color),
            "ui_scale": float(self.config.ui_scale),
            "syster_mode": self.syster.mode,
        }
        self.syster_store.save_snapshot(
            slot_id=self.current_slot.slot_id,
            route_name=self.current_slot.route_name,
            stats=dict(self.current_slot.stats),
            flags=dict(self.current_slot.flags),
            config=config_payload,
        )
        self.syster_store.set_preference("theme", config_payload["theme"])
        self.syster_store.set_preference("language", config_payload["language"])
        self.syster_store.set_preference("graphics", str(config_payload["graphics"]))
        self.syster_store.set_preference("sound", "on" if config_payload["sound"] else "off")

    def _save_current_slot(self, user_feedback: bool) -> None:
        self.save_manager.save_slot(self.current_slot)
        self._snapshot_syster_state()
        if user_feedback:
            self.ui.write(
                self.tr(
                    "app.savegame.done",
                    id=self.current_slot.slot_id,
                    route=self.current_slot.route_name,
                )
            )
        self._queue_cloud_sync(reason="save_slot")

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
        self.config.theme_secondary_color = ""
        self.config.theme_style = ""
        self.config.theme_scan_strength = 1.0
        self.config.theme_glow_strength = 1.0
        self.config.theme_particles_strength = 1.0

    def _apply_theme_preset(self, name: str, theme: ThemePreset) -> None:
        self.config.bg_color = theme.bg
        self.config.fg_color = theme.fg
        self.config.theme_accent_color = theme.accent
        self.config.theme_panel_color = theme.panel
        self.config.theme_dim_color = theme.dim
        self.config.theme_secondary_color = theme.secondary
        self.config.theme_style = self._normalize_theme_style(theme.style) or "terminal"
        self.config.theme_scan_strength = theme.scan_strength
        self.config.theme_glow_strength = theme.glow_strength
        self.config.theme_particles_strength = theme.particle_strength
        if theme.font_family.strip():
            resolved = self._resolve_font_family(theme.font_family)
            if resolved is not None:
                self.config.font_family = resolved
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
                    secondary=(preset.secondary or "auto"),
                    style=(preset.style or "terminal"),
                    font=(preset.font_family or "-"),
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
        cfg_secondary = self.config.theme_secondary_color.strip().lower()
        cfg_style = self._normalize_theme_style(self.config.theme_style)
        for name, preset in self.theme_presets.items():
            if preset.bg.lower() != bg.lower() or preset.fg.lower() != fg.lower():
                continue
            if preset.accent.strip().lower() != cfg_accent:
                continue
            if preset.panel.strip().lower() != cfg_panel:
                continue
            if preset.dim.strip().lower() != cfg_dim:
                continue
            if cfg_secondary and preset.secondary.strip().lower() != cfg_secondary:
                continue
            preset_style = self._normalize_theme_style(preset.style) or "terminal"
            if cfg_style and preset_style != cfg_style:
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
                self._run_domain("update", "consume_check_result", lambda: self._consume_update_check_result(payload))
                continue

            if event == "install_downloaded":
                self._run_domain("update", "consume_install_downloaded", lambda: self._consume_update_downloaded(payload))
                continue

            if event == "download_prepared":
                self._run_domain("update", "consume_download_prepared", lambda: self._consume_update_prepared(payload))
                continue

            if event == "install_failed":
                self._run_domain("update", "consume_install_failed", lambda: self._consume_update_install_failed(payload))
                continue

            if event == "download_progress":
                self._run_domain("update", "consume_download_progress", lambda: self._consume_update_progress(payload))
                continue

            if event == "download_verifying":
                self.ui.set_status(self.tr("app.update.status_verifying"))
                continue

            if event == "mod_change":
                self._run_domain("mods", "consume_mod_change", lambda: self._consume_mod_change(payload))
                continue

            if event == "cloud_sync_done":
                self._run_domain("cloud", "consume_sync_done", lambda: self._consume_cloud_sync_done(payload))
                continue

            if event == "cloud_presence_done":
                self._run_domain("cloud", "consume_presence_done", lambda: self._consume_cloud_presence_done(payload))
                continue

            if event == "cloud_leaderboard_done":
                self._run_domain(
                    "cloud",
                    "consume_leaderboard_done",
                    lambda: self._consume_cloud_leaderboard_done(payload),
                )
                continue

            if event == "cloud_snake_arena_done":
                self._run_domain(
                    "cloud",
                    "consume_snake_arena_done",
                    lambda: self._consume_cloud_snake_arena_done(payload),
                )
                continue

            if event == "cloud_auth_done":
                self._run_domain("cloud", "consume_auth_done", lambda: self._consume_cloud_auth_done(payload))
                continue

            if event == "cloud_news_done":
                self._run_domain("cloud", "consume_news_done", lambda: self._consume_cloud_news_done(payload))
                continue

            if event == "syster_reply_done":
                self._run_domain("syster", "consume_reply_done", lambda: self._consume_syster_reply_done(payload))
                continue

            if event == "terminal_result":
                self._run_domain("ui", "consume_terminal_result", lambda: self._consume_terminal_result(payload))
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

    def _consume_cloud_sync_done(self, payload: dict[str, object]) -> None:
        self.cloud_sync_running = False
        self.cloud_last_sync_at = time.monotonic()
        ok = bool(payload.get("ok", False))
        message = str(payload.get("message", "")).strip()
        data = payload.get("payload")
        user_feedback = bool(payload.get("user_feedback", False))

        self.cloud_last_status = "ok" if ok else "error"
        self.cloud_last_message = message

        if isinstance(data, dict):
            online = data.get("players_online")
            users = data.get("registered_users")
            if isinstance(online, (int, float)) or isinstance(users, (int, float)):
                current = dict(self.cloud_last_presence)
                if isinstance(online, (int, float)):
                    current["players_online"] = int(online)
                if isinstance(users, (int, float)):
                    current["registered_users"] = int(users)
                self.cloud_last_presence = current

        if user_feedback:
            if ok:
                self.ui.write(self.tr("app.cloud.sync_ok"))
            else:
                self.ui.write(self.tr("app.cloud.sync_failed", error=(message or "network_error")))

    def _consume_cloud_presence_done(self, payload: dict[str, object]) -> None:
        self.cloud_sync_running = False
        self.cloud_last_sync_at = time.monotonic()
        ok = bool(payload.get("ok", False))
        message = str(payload.get("message", "")).strip()
        data = payload.get("payload")
        user_feedback = bool(payload.get("user_feedback", False))

        self.cloud_last_status = "ok" if ok else "error"
        self.cloud_last_message = message

        if isinstance(data, dict):
            self.cloud_last_presence = data
            if user_feedback:
                online = int(data.get("players_online", 0) or 0)
                users = int(data.get("registered_users", 0) or 0)
                self.ui.write(self.tr("app.cloud.presence", online=online, users=users))
                return

        if user_feedback:
            self.ui.write(self.tr("app.cloud.sync_failed", error=(message or "network_error")))

    def _consume_cloud_leaderboard_done(self, payload: dict[str, object]) -> None:
        self.cloud_leaderboard_running = False
        self.cloud_leaderboard_running_game = ""
        game = self._normalize_leaderboard_game(str(payload.get("game", "") or "snake"))
        if not game:
            game = "snake"
        ok = bool(payload.get("ok", False))
        message = str(payload.get("message", "")).strip()
        data = payload.get("payload")
        user_feedback = bool(payload.get("user_feedback", False))

        self.cloud_last_status = "ok" if ok else "error"
        self.cloud_last_message = message or ("ok" if ok else "network_error")

        if not ok:
            if user_feedback:
                self.ui.write(
                    self.tr(
                        "app.cloud.leaderboard_failed",
                        game=game.upper(),
                        error=(message or "network_error"),
                    )
                )
            return

        if not isinstance(data, dict):
            if user_feedback:
                self.ui.write(self.tr("app.cloud.leaderboard_empty"))
            return

        raw_items = data.get("items")
        items = raw_items if isinstance(raw_items, list) else []
        parsed_items: list[dict[str, object]] = []
        for item in items:
            if isinstance(item, dict):
                parsed_items.append(item)
        if game == "rogue":
            self.cloud_last_rogue_leaderboard = parsed_items
        elif game == "hangman":
            self.cloud_last_hangman_leaderboard = parsed_items
        else:
            self.cloud_last_snake_leaderboard = parsed_items
        self._refresh_active_game_side_panel()

        if not user_feedback:
            return
        if not parsed_items:
            self.ui.write(self.tr("app.cloud.leaderboard_empty"))
            return

        if game == "rogue":
            self.ui.write(self.tr("app.cloud.leaderboard.rogue.title", count=len(parsed_items)))
            for row in parsed_items:
                self.ui.write(
                    self.tr(
                        "app.cloud.leaderboard.rogue.item",
                        rank=int(row.get("rank", 0) or 0),
                        name=str(row.get("player_name", "") or "Guest"),
                        depth=int(row.get("rogue_best_depth", 0) or 0),
                        gold=int(row.get("rogue_best_gold", 0) or 0),
                        kills=int(row.get("rogue_best_kills", 0) or 0),
                        route=str(row.get("route_name", "") or "-"),
                        version=str(row.get("version_tag", "") or "-"),
                    )
                )
            return

        if game == "hangman":
            self.ui.write(self.tr("app.cloud.leaderboard.hangman.title", count=len(parsed_items)))
            for row in parsed_items:
                self.ui.write(
                    self.tr(
                        "app.cloud.leaderboard.hangman.item",
                        rank=int(row.get("rank", 0) or 0),
                        name=str(row.get("player_name", "") or "Guest"),
                        wins=int(row.get("hangman_wins", 0) or 0),
                        games=int(row.get("hangman_games", 0) or 0),
                        clean=int(row.get("hangman_best_errors_left", 0) or 0),
                        route=str(row.get("route_name", "") or "-"),
                        version=str(row.get("version_tag", "") or "-"),
                    )
                )
            return

        self.ui.write(self.tr("app.cloud.leaderboard.snake.title", count=len(parsed_items)))
        for row in parsed_items:
            self.ui.write(
                self.tr(
                    "app.cloud.leaderboard.snake.item",
                    rank=int(row.get("rank", 0) or 0),
                    name=str(row.get("player_name", "") or "Guest"),
                    score=int(row.get("snake_best_score", 0) or 0),
                    level=int(row.get("snake_best_level", 0) or 0),
                    length=int(row.get("snake_longest_length", 0) or 0),
                    route=str(row.get("route_name", "") or "-"),
                    version=str(row.get("version_tag", "") or "-"),
                )
            )

    def _consume_cloud_snake_arena_done(self, payload: dict[str, object]) -> None:
        self.cloud_snake_arena_running = False
        ok = bool(payload.get("ok", False))
        message = str(payload.get("message", "")).strip()
        data = payload.get("payload")
        room = self._sanitize_snake_room(str(payload.get("room", "")))
        self.cloud_snake_arena_last_rtt_ms = max(0, int(payload.get("rtt_ms", 0) or 0))
        state = payload.get("state")
        if isinstance(state, tuple) and len(state) == 5:
            try:
                self.cloud_snake_arena_last_state = (
                    int(state[0]),
                    int(state[1]),
                    max(1, int(state[2])),
                    int(state[3]),
                    int(state[4]),
                )
            except (TypeError, ValueError):
                pass
        self.cloud_last_status = "ok" if ok else "error"
        self.cloud_last_message = message or ("ok" if ok else "network_error")
        if not ok or not isinstance(data, dict):
            self.cloud_snake_arena_fail_streak += 1
            return

        self.cloud_snake_arena_fail_streak = 0
        self.cloud_snake_arena_last_ok_at = time.monotonic()
        self.cloud_snake_arena_room = room
        players_online = int(data.get("players_online", 0) or 0)
        self.cloud_last_snake_arena_players_online = max(0, players_online)
        raw_items = data.get("items")
        parsed: list[dict[str, object]] = []
        if isinstance(raw_items, list):
            for row in raw_items:
                if isinstance(row, dict):
                    parsed.append(row)
        self.cloud_last_snake_arena = parsed
        self._refresh_active_game_side_panel()

    def _consume_cloud_auth_done(self, payload: dict[str, object]) -> None:
        self.cloud_auth_running = False
        ok = bool(payload.get("ok", False))
        message = str(payload.get("message", "")).strip()
        action = str(payload.get("action", "")).strip().lower()
        data = payload.get("payload")
        user_feedback = bool(payload.get("user_feedback", False))
        from_setup = bool(payload.get("from_setup", False))

        if ok and isinstance(data, dict):
            if action == "logout":
                self.cloud.clear_session()
                self.config.cloud_session_token = ""
                self.config.cloud_auth_username = ""
                self.config.cloud_auth_email = ""
                self.cloud_auth_user = {}
            else:
                session_token = str(data.get("session_token", "")).strip()
                if session_token:
                    self.cloud.set_session(session_token)
                    self.config.cloud_session_token = session_token
                username = self._sanitize_auth_username(str(data.get("username", "")))
                email = self._sanitize_auth_email(str(data.get("email", "")))
                if username:
                    self.config.cloud_auth_username = username
                    self.cloud_auth_user["username"] = username
                if email:
                    self.config.cloud_auth_email = email
                    self.cloud_auth_user["email"] = email

            self.cloud_last_status = "ok"
            self.cloud_last_message = message or "ok"
            self.cloud_sync_elapsed = 0.0
            self.cloud_news_elapsed = 0.0
            self._save_config()

            if action in {"register", "login", "me"}:
                self._queue_cloud_sync(reason=f"auth_{action}", force=True)
            if action in {"register", "login"}:
                self.ui.push_notification(
                    self.tr("app.auth.toast_title"),
                    self.tr(
                        "app.auth.toast_body",
                        username=(self.config.cloud_auth_username or self._player_name()),
                    ),
                    icon_key="mdi:account",
                )
            if user_feedback:
                if action == "register":
                    self.ui.write(self.tr("app.auth.register_ok", username=self.config.cloud_auth_username))
                elif action == "login":
                    self.ui.write(self.tr("app.auth.login_ok", username=self.config.cloud_auth_username))
                elif action == "logout":
                    self.ui.write(self.tr("app.auth.logout_ok"))
                else:
                    self.ui.write(self.tr("app.auth.me_ok", username=self.config.cloud_auth_username))

            if from_setup:
                self._finish_cloud_auth_setup(success=True)
            return

        self.cloud_last_status = "error"
        self.cloud_last_message = message or "auth_error"
        if action in {"me", "logout"} and message in {"invalid_session", "not_authenticated"}:
            self.cloud.clear_session()
            self.config.cloud_session_token = ""
            self.config.cloud_auth_username = ""
            self.config.cloud_auth_email = ""
            self.cloud_auth_user = {}
            self._save_config()
            if not from_setup and not self.awaiting_player_name and self.input_handler is None:
                self._start_cloud_auth_setup()
        if from_setup:
            self._resume_cloud_auth_setup_after_error(message or "auth_error")
        if user_feedback:
            self.ui.write(self.tr("app.auth.failed", error=(message or "auth_error")))

    def _consume_cloud_news_done(self, payload: dict[str, object]) -> None:
        self.cloud_news_running = False
        self.cloud_last_news_at = time.monotonic()
        ok = bool(payload.get("ok", False))
        message = str(payload.get("message", "")).strip()
        data = payload.get("payload")
        user_feedback = bool(payload.get("user_feedback", False))

        if not ok:
            self.cloud_last_status = "error"
            self.cloud_last_message = message or "network_error"
            if message == "invalid_session":
                self.cloud.clear_session()
                self.config.cloud_session_token = ""
                self.config.cloud_auth_username = ""
                self.config.cloud_auth_email = ""
                self.cloud_auth_user = {}
                self._save_config()
                if not self.awaiting_player_name and self.input_handler is None:
                    self._start_cloud_auth_setup()
            if user_feedback:
                self.ui.write(self.tr("app.cloud.news_failed", error=(message or "network_error")))
            return

        self.cloud_last_status = "ok"
        self.cloud_last_message = message or "ok"
        if not isinstance(data, dict):
            if user_feedback:
                self.ui.write(self.tr("app.cloud.news_empty"))
            return

        raw_items = data.get("items")
        items = raw_items if isinstance(raw_items, list) else []
        unread = int(data.get("unread", 0) or 0)
        new_unseen: list[dict[str, object]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", "")).strip()
            if not key:
                continue
            if key in self.cloud_seen_news_keys:
                continue
            self.cloud_seen_news_keys.add(key)
            if not bool(item.get("seen", False)):
                new_unseen.append(item)

        if not user_feedback and new_unseen:
            first = new_unseen[0]
            title = str(first.get("title", "")).strip() or self.tr("app.cloud.news_generic")
            self.ui.push_notification(
                self.tr("app.cloud.news_toast_title"),
                self.tr("app.cloud.news_toast_body", title=title[:72]),
                icon_key="mdi:information-outline",
            )

        if user_feedback:
            if not items:
                self.ui.write(self.tr("app.cloud.news_empty"))
                return
            self.ui.write(self.tr("app.cloud.news_count", unread=unread, total=len(items)))
            for item in items[:8]:
                if not isinstance(item, dict):
                    continue
                self.ui.write(
                    self.tr(
                        "app.cloud.news_item",
                        kind=str(item.get("type", "news")).upper(),
                        title=(str(item.get("title", "")).strip() or self.tr("app.cloud.news_generic")),
                        url=(str(item.get("url", "")).strip() or "-"),
                    )
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
        self._apply_player_identity()

    @staticmethod
    def _sanitize_player_name(raw: str) -> str:
        value = " ".join(raw.strip().split())
        if not value:
            return ""
        cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-", " "})
        normalized = " ".join(cleaned.split()).strip()
        return normalized[:24]

    @staticmethod
    def _sanitize_snake_room(raw: str) -> str:
        value = raw.strip().lower()
        if not value:
            return "global"
        cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-"})
        if not cleaned:
            return "global"
        return cleaned[:24]

    def _player_name(self) -> str:
        name = self._sanitize_player_name(self.config.player_name)
        if not name:
            return self.tr("app.player.guest")
        return name

    def _apply_player_identity(self) -> None:
        prompt_suffix = "$" if self.terminal_passthrough else ">"
        raw_name = self._sanitize_player_name(self.config.player_name)
        if not raw_name:
            self.ui.set_prompt(f"Gethes{prompt_suffix}")
            return
        prompt_token = raw_name.replace(" ", "_")
        self.ui.set_prompt(f"{prompt_token}{prompt_suffix}")

    def _reload_audio_assets(self) -> None:
        self.audio.initialize(
            self.assets_dir,
            user_assets_dir=self.user_sfx_dir,
            overrides=self.config.sfx_overrides,
        )
        self.audio.set_enabled(self.config.sound)

    def _apply_visual_config(self) -> None:
        active_theme_name = self._detect_theme_name(self.config.bg_color, self.config.fg_color)
        active_preset = self.theme_presets.get(active_theme_name)
        secondary_color = self.config.theme_secondary_color.strip()
        theme_style = self._normalize_theme_style(self.config.theme_style)
        if active_preset is not None:
            if not secondary_color and active_preset.secondary.strip():
                secondary_color = active_preset.secondary.strip()
            if not theme_style:
                theme_style = self._normalize_theme_style(active_preset.style) or "terminal"
        if not theme_style:
            theme_style = "terminal"

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
                secondary_color=(secondary_color or None),
                theme_style=theme_style,
                scan_strength=self.config.theme_scan_strength,
                glow_strength=self.config.theme_glow_strength,
                particle_strength=self.config.theme_particles_strength,
            )
        except Exception:
            self.config = GameConfig()
            secondary_color = ""
            theme_style = "terminal"
            self.ui.apply_style(
                bg_color=self.config.bg_color,
                fg_color=self.config.fg_color,
                font_family=self.config.font_family,
                font_size=self.config.font_size,
                ui_scale=self.config.ui_scale,
                accent_color=(self.config.theme_accent_color or None),
                panel_color=(self.config.theme_panel_color or None),
                dim_color=(self.config.theme_dim_color or None),
                secondary_color=(secondary_color or None),
                theme_style=theme_style,
                scan_strength=self.config.theme_scan_strength,
                glow_strength=self.config.theme_glow_strength,
                particle_strength=self.config.theme_particles_strength,
            )
        self._apply_performance_config()

    def _apply_performance_config(self) -> None:
        self.ui.set_graphics_level(self.config.graphics)

    def _save_config(self) -> None:
        self.config.active_slot = self.current_slot.slot_id
        self.config.syster_mode = "local"
        self.config.syster_mode_user_set = True
        self.config.syster_endpoint = ""
        self.config.syster_ollama_enabled = True
        self.config.syster_ollama_model = "mistral"
        if self.syster.mode != "local":
            self.syster.set_mode("local")
        if self.syster.remote_endpoint:
            self.syster.set_remote_endpoint(None)
        if not self.syster.ollama_enabled:
            self.syster.set_ollama_enabled(True)
        if self.syster.ollama_model != "mistral":
            self.syster.set_ollama_model("mistral")
        self.config.syster_ollama_host = self.syster.ollama_host
        self.config.syster_ollama_timeout = self.syster.ollama_timeout
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
        self.config.cloud_endpoint = self.cloud.endpoint
        self.config.cloud_api_key = self.cloud.api_key
        self.config.cloud_session_token = self.cloud.session_token
        if self.cloud_auth_user.get("username"):
            self.config.cloud_auth_username = str(self.cloud_auth_user["username"]).strip()
        if self.cloud_auth_user.get("email"):
            self.config.cloud_auth_email = str(self.cloud_auth_user["email"]).strip().lower()
        self.config.cloud_sync_interval_seconds = int(max(20, min(600, round(self.cloud_sync_cooldown))))
        self.config.cloud_news_poll_seconds = int(max(60, min(3600, round(self.cloud_news_cooldown))))
        self.config_store.save(self.config)

    def _shutdown(self) -> None:
        self._stop_mod_watcher()
        self._save_current_slot(user_feedback=False)
        self._save_config()
        self.syster_store.close()

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
        fake_steps = [
            self.tr("app.boot.fake.cache"),
            self.tr("app.boot.fake.entropy"),
            self.tr("app.boot.fake.telemetry"),
            self.tr("app.boot.fake.routing"),
            self.tr("app.boot.fake.audio"),
            self.tr("app.boot.fake.shaders"),
            self.tr("app.boot.fake.session"),
            self.tr("app.boot.fake.signature"),
        ]
        rng = random.Random(time.monotonic_ns())
        rng.shuffle(fake_steps)
        self.boot_stage_queue = []
        fake_cursor = 0
        for step in self.boot_steps:
            self.boot_stage_queue.append((False, fake_steps[fake_cursor % len(fake_steps)]))
            fake_cursor += 1
            if fake_cursor < len(fake_steps) and rng.random() >= 0.45:
                self.boot_stage_queue.append((False, fake_steps[fake_cursor % len(fake_steps)]))
                fake_cursor += 1
            self.boot_stage_queue.append((True, step))

        self.boot_active = True
        self.boot_completed = 0
        self.boot_timer_ms = 0.0
        self.boot_progress_percent = 0
        self.boot_stage_cursor = 0
        self.boot_recent_activity = []
        self.boot_spinner_frame = 0
        self.ui.set_entry_enabled(False)
        self.ui.set_status(self.tr("app.booting"))
        self.ui.set_screen(
            self._boot_text(
                steps=self.boot_steps,
                completed=0,
                current_step=self.tr("app.boot.preparing"),
                progress_percent=0,
                background_tasks=self.boot_recent_activity,
                spinner_index=self.boot_spinner_frame,
            )
        )

    def _update_boot(self, dt: float) -> None:
        self.boot_timer_ms += dt * 1000.0
        if self.boot_timer_ms < self._boot_delay_ms():
            return

        self.boot_timer_ms = 0.0
        if self.boot_stage_cursor < len(self.boot_stage_queue):
            is_module_step, step = self.boot_stage_queue[self.boot_stage_cursor]
            self.boot_stage_cursor += 1
            self.boot_spinner_frame = (self.boot_spinner_frame + 1) % 4

            if is_module_step:
                self.boot_completed += 1
                total_steps = max(1, len(self.boot_steps))
                module_target = int((self.boot_completed / total_steps) * 100)
                self.boot_progress_percent = max(self.boot_progress_percent, module_target)
            else:
                progress_bump = random.randint(2, 6)
                self.boot_progress_percent = min(96, self.boot_progress_percent + progress_bump)

            self.boot_recent_activity.append(step)
            if len(self.boot_recent_activity) > 4:
                self.boot_recent_activity = self.boot_recent_activity[-4:]

            self.ui.set_screen(
                self._boot_text(
                    steps=self.boot_steps,
                    completed=self.boot_completed,
                    current_step=step,
                    progress_percent=self.boot_progress_percent,
                    background_tasks=self.boot_recent_activity,
                    spinner_index=self.boot_spinner_frame,
                )
            )
            self.audio.play("tick")
            return

        self.boot_active = False
        self.ui.set_entry_enabled(True)
        self._after_boot_ready()
        self._unlock_achievement("boot_sequence")
        self._trigger_syster_auto("boot")
        self._trigger_auto_update_check()

    def _boot_delay_ms(self) -> int:
        delay_by_graphics = {
            "low": 340,
            "medium": 230,
            "high": 150,
        }
        base_delay = delay_by_graphics.get(self.config.graphics, 230)
        if self.boot_stage_cursor < len(self.boot_stage_queue):
            is_module_step, _ = self.boot_stage_queue[self.boot_stage_cursor]
            if not is_module_step:
                return max(90, int(base_delay * 0.62))
        return base_delay

    def _boot_text(
        self,
        steps: list[str],
        completed: int,
        current_step: str,
        progress_percent: int | None = None,
        background_tasks: list[str] | None = None,
        spinner_index: int = 0,
    ) -> str:
        total = len(steps)
        bar_size = 34
        if progress_percent is None:
            progress = completed / total if total else 1
            percent = int(progress * 100)
        else:
            percent = max(0, min(100, int(progress_percent)))
            progress = percent / 100
        filled = int(progress * bar_size)
        bar = ("#" * filled) + ("-" * (bar_size - filled))
        spinner = "|/-\\"[spinner_index % 4]

        lines = [
            self.tr("app.boot.title"),
            "==========================================",
            "",
            f"[{bar}] {percent:3d}%  {spinner}",
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

        lines.append("")
        lines.append(self.tr("app.boot.background"))
        history = background_tasks or []
        if history:
            for item in history[-3:]:
                lines.append(f" - {item}")
        else:
            lines.append(f" - {self.tr('app.boot.fake.fallback')}")

        lines.extend(
            [
                "",
                self.tr("app.boot.wait"),
            ]
        )
        return "\n".join(lines)

    def _after_boot_ready(self) -> None:
        self.audio.play("success")
        name = self._sanitize_player_name(self.config.player_name)
        if not name:
            self._start_player_name_setup()
            return

        self.config.player_name = name
        self._apply_player_identity()
        self._save_config()
        self._on_identity_ready(sync_reason="boot")

    def _on_identity_ready(self, sync_reason: str) -> None:
        self.ui.set_screen(self._welcome_text())
        self.ui.set_status(self.tr("ui.help_hint"))
        self._queue_cloud_sync(reason=sync_reason, force=True)
        self._bootstrap_cloud_identity()

    def _bootstrap_cloud_identity(self) -> None:
        if not self.config.cloud_enabled or not self.cloud.is_linked():
            return
        if self.awaiting_player_name:
            return
        if self.cloud.has_session():
            self._queue_cloud_auth(action="me", user_feedback=False)
            return
        self._start_cloud_auth_setup()

    def _start_player_name_setup(self) -> None:
        self.awaiting_player_name = True
        self.set_input_handler(self._handle_player_name_input)
        self.ui.set_input_mask(False)
        self.ui.set_status(self.tr("app.player.setup.status"))
        self.ui.set_screen(
            "\n".join(
                [
                    self.tr("app.player.setup.title"),
                    "==========================================",
                    "",
                    self.tr("app.player.setup.hint1"),
                    self.tr("app.player.setup.hint2"),
                    "",
                    self.tr("app.player.setup.controls"),
                ]
            )
        )

    def _handle_player_name_input(self, raw: str) -> None:
        token = raw.strip()
        lowered = token.lower()
        if lowered in {"guest", "invitado", "convidado", "skip", "omitir"}:
            self.config.player_name = ""
            self.awaiting_player_name = False
            self.clear_input_handler()
            self._apply_player_identity()
            self.ui.write(self.tr("app.player.setup.skip"))
            self._save_config()
            self._on_identity_ready(sync_reason="boot_guest")
            return

        name = self._sanitize_player_name(token)
        if not name:
            self.ui.write(self.tr("app.player.setup.invalid"))
            return

        self.config.player_name = name
        self.awaiting_player_name = False
        self.clear_input_handler()
        self._apply_player_identity()
        self.ui.write(self.tr("app.player.setup.saved", name=name))
        self.ui.push_notification(
            self.tr("app.player.toast.title"),
            self.tr("app.player.toast.body", name=name),
            icon_key="mdi:account",
        )
        self._save_config()
        self._on_identity_ready(sync_reason="player_name_set")

    def _start_cloud_auth_setup(self) -> None:
        if not self.config.cloud_enabled or not self.cloud.is_linked():
            return
        if self.cloud.has_session():
            return
        if self.awaiting_player_name:
            return
        if self.awaiting_cloud_auth_setup:
            return
        if self.input_handler is not None:
            return

        self.awaiting_cloud_auth_setup = True
        self.cloud_auth_setup_stage = "choice"
        self.cloud_auth_pending = {}
        self.set_input_handler(self._handle_cloud_auth_setup_input)
        self.ui.set_input_mask(False)
        self.ui.set_status(self.tr("app.auth.setup.status"))
        self.ui.set_screen(
            "\n".join(
                [
                    self.tr("app.auth.setup.title"),
                    "==========================================",
                    "",
                    self.tr("app.auth.setup.hint1"),
                    self.tr("app.auth.setup.hint2"),
                    "",
                    self.tr("app.auth.setup.controls"),
                ]
            )
        )

    def _finish_cloud_auth_setup(self, success: bool) -> None:
        self.awaiting_cloud_auth_setup = False
        self.cloud_auth_setup_stage = ""
        self.cloud_auth_pending = {}
        self.clear_input_handler()
        self.ui.set_input_mask(False)
        self.ui.set_status(self.tr("ui.help_hint"))
        self.ui.set_screen(self._welcome_text())
        if not success:
            self.ui.write(self.tr("app.auth.setup.skip"))

    def _resume_cloud_auth_setup_after_error(self, error: str) -> None:
        if not self.awaiting_cloud_auth_setup:
            self._start_cloud_auth_setup()
            return
        self.cloud_auth_setup_stage = "choice"
        self.cloud_auth_pending = {}
        self.ui.set_input_mask(False)
        self.ui.write(self.tr("app.auth.failed", error=error))
        self.ui.write(self.tr("app.auth.setup.controls"))

    def _handle_cloud_auth_setup_input(self, raw: str) -> None:
        stage = self.cloud_auth_setup_stage
        token = raw.strip()
        lowered = token.lower()

        if stage == "waiting":
            self.ui.write(self.tr("app.auth.busy"))
            return

        if stage == "choice":
            if lowered in {"skip", "guest", "invitado", "convidado"}:
                self._finish_cloud_auth_setup(success=False)
                return
            if lowered in {"register", "registro", "signup", "r"}:
                self.cloud_auth_setup_stage = "register_username"
                self.ui.write(self.tr("app.auth.setup.ask_username"))
                return
            if lowered in {"login", "signin", "l"}:
                self.cloud_auth_setup_stage = "login_login"
                self.ui.write(self.tr("app.auth.setup.ask_login"))
                return
            self.ui.write(self.tr("app.auth.setup.controls"))
            return

        if stage == "register_username":
            username = self._sanitize_auth_username(token)
            if not username:
                self.ui.write(self.tr("app.auth.username_invalid"))
                self.ui.write(self.tr("app.auth.setup.ask_username"))
                return
            self.cloud_auth_pending = {"username": username}
            self.cloud_auth_setup_stage = "register_email"
            self.ui.write(self.tr("app.auth.setup.ask_email"))
            return

        if stage == "register_email":
            email = self._sanitize_auth_email(token)
            if not email:
                self.ui.write(self.tr("app.auth.email_invalid"))
                self.ui.write(self.tr("app.auth.setup.ask_email"))
                return
            self.cloud_auth_pending["email"] = email
            self.cloud_auth_setup_stage = "register_password"
            self.ui.set_input_mask(True)
            self.ui.write(self.tr("app.auth.setup.ask_password"))
            return

        if stage == "register_password":
            password = token
            self.ui.set_input_mask(False)
            if len(password) < 8:
                self.ui.write(self.tr("app.auth.password_invalid"))
                self.cloud_auth_setup_stage = "register_password"
                self.ui.set_input_mask(True)
                self.ui.write(self.tr("app.auth.setup.ask_password"))
                return
            self.cloud_auth_setup_stage = "waiting"
            queued = self._queue_cloud_auth(
                action="register",
                username=self.cloud_auth_pending.get("username", ""),
                email=self.cloud_auth_pending.get("email", ""),
                password=password,
                user_feedback=True,
                from_setup=True,
            )
            if not queued:
                self.cloud_auth_setup_stage = "choice"
                self.ui.write(self.tr("app.auth.busy"))
                self.ui.write(self.tr("app.auth.setup.controls"))
            return

        if stage == "login_login":
            if not token:
                self.ui.write(self.tr("app.auth.setup.ask_login"))
                return
            self.cloud_auth_pending = {"login": token}
            self.cloud_auth_setup_stage = "login_password"
            self.ui.set_input_mask(True)
            self.ui.write(self.tr("app.auth.setup.ask_password"))
            return

        if stage == "login_password":
            password = token
            self.ui.set_input_mask(False)
            if len(password) < 8:
                self.ui.write(self.tr("app.auth.password_invalid"))
                self.cloud_auth_setup_stage = "login_password"
                self.ui.set_input_mask(True)
                self.ui.write(self.tr("app.auth.setup.ask_password"))
                return
            self.cloud_auth_setup_stage = "waiting"
            queued = self._queue_cloud_auth(
                action="login",
                login=self.cloud_auth_pending.get("login", ""),
                password=password,
                user_feedback=True,
                from_setup=True,
            )
            if not queued:
                self.cloud_auth_setup_stage = "choice"
                self.ui.write(self.tr("app.auth.busy"))
                self.ui.write(self.tr("app.auth.setup.controls"))
            return

        self.cloud_auth_setup_stage = "choice"
        self.ui.set_input_mask(False)
        self.ui.write(self.tr("app.auth.setup.controls"))

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
                self.tr("app.welcome.user", name=self._player_name()),
                self.tr(
                    "app.welcome.account",
                    user=(self.config.cloud_auth_username or self.tr("app.auth.guest")),
                ),
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
                "- `user <nombre>`",
                "- `savegame`",
                "",
                self.tr("app.welcome.cloud"),
                "- `cloud status`",
                "- `auth register <user> <email> <pass>` / `auth login <user|email> <pass>`",
                "- `news`",
                "",
                self.tr("app.welcome.help"),
            ]
        )

    @staticmethod
    def _language_mode_labels() -> str:
        preferred = ["auto", "es", "en", "pt", "fr", "de"]
        ordered = [item for item in preferred if item in LANGUAGE_MODES]
        ordered.extend(sorted(item for item in LANGUAGE_MODES if item not in ordered))
        return "|".join(ordered)

    def _help_text(self) -> str:
        language_modes = self._language_mode_labels()
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
            f"- daily [snake|rogue]      : {self.tr('app.help.daily')}",
            f"- historia / story         : {self.tr('app.help.story')}",
            f"- logros / achievements    : {self.tr('app.help.achievements')}",
            f"- slots                    : {self.tr('app.help.slots')}",
            f"- slot <1-3>               : {self.tr('app.help.slot')}",
            f"- slotname <nombre>        : {self.tr('app.help.slotname')}",
            f"- user [nombre|guest]      : {self.tr('app.help.user')}",
            f"- savegame                 : {self.tr('app.help.savegame')}",
            f"- options / opciones       : {self.tr('app.help.options')}",
            f"- doctor [all|audio|update|ui]: {self.tr('app.help.doctor')}",
            f"- health / domains         : {self.tr('app.help.health')}",
            f"- terminal <status|on|off|run ...>: {self.tr('app.help.terminal')}",
            f"- sh <comando_sistema>     : {self.tr('app.help.sh')}",
            f"- sound <on|off>           : {self.tr('app.help.sound')}",
            f"- graphics <low|medium|high>: {self.tr('app.help.graphics')}",
            f"- uiscale <0.7-2.5|auto|small|normal|large|huge>: {self.tr('app.help.uiscale')}",
            f"- theme <preset|list|reload|bg fg>: {self.tr('app.help.theme')}",
            f"- bg <color>               : {self.tr('app.help.bg')}",
            f"- fg <color>               : {self.tr('app.help.fg')}",
            f"- font <familia> [tamano]  : {self.tr('app.help.font')}",
            f"- fonts [filtro]           : {self.tr('app.help.fonts')}",
            f"- lang [{language_modes}]  : {self.tr('app.help.lang')}",
            f"- update ...               : {self.tr('app.help.update')}",
            f"- cloud ...                : {self.tr('app.help.cloud')}",
            f"- auth ...                 : {self.tr('app.help.auth')}",
            f"- news [limite]            : {self.tr('app.help.news')}",
            f"- assets <status|reload>   : {self.tr('app.help.assets')}",
            f"- mods <status|reload>     : {self.tr('app.help.mods')}",
            f"- sfx                      : {self.tr('app.help.sfx')}",
            f"- save                     : {self.tr('app.help.save')}",
            f"- exit                     : {self.tr('app.help.exit')}",
        ]
        if self.syster_enabled:
            lines.append(f"- syster ...               : {self.tr('app.help.syster')}")
            lines.append(
                f"- syster core ...          : {self.tr('app.help.syster_ollama')}"
            )
            lines.append(
                f"- syster train ...         : {self.tr('app.help.syster_train')}"
            )
        return "\n".join(lines)

    def _options_text(self) -> str:
        active_theme = self._detect_theme_name(self.config.bg_color, self.config.fg_color)
        theme_value = active_theme if active_theme != "custom" else self.tr("app.theme_custom")
        theme_style = self._normalize_theme_style(self.config.theme_style) or "terminal"
        theme_secondary = self.config.theme_secondary_color or "auto"
        remote_state = "ON" if self.syster.has_remote_endpoint() else "OFF"
        ollama_ok, _ = self.syster.get_ollama_status(force_probe=False)
        if not self.syster.ollama_enabled:
            ollama_state = "OFF"
        else:
            ollama_state = "ONLINE" if ollama_ok else "OFFLINE"
        ui_user, ui_responsive, ui_effective = self.ui.get_scale_snapshot()
        return "\n".join(
            [
                self.tr("app.options.title"),
                f"- {self.tr('app.options.player'):13}: {self._player_name()}",
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
                f"- {self.tr('app.options.theme_style'):13}: {theme_style}",
                f"- {self.tr('app.options.theme_secondary'):13}: {theme_secondary}",
                f"- {self.tr('app.options.theme_fx'):13}: "
                f"scan {self.config.theme_scan_strength:.2f} | "
                f"glow {self.config.theme_glow_strength:.2f} | "
                f"particles {self.config.theme_particles_strength:.2f}",
                f"- {self.tr('app.options.themes_count'):13}: {len(self.theme_presets)}",
                f"- {self.tr('app.options.ui_scale'):13}: {self.config.ui_scale:.2f}x",
                f"- {self.tr('app.options.terminal'):13}: {'ON' if self.terminal_passthrough else 'OFF'}",
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
                f"- {self.tr('app.options.syster_ai'):13}: {ollama_state}",
                f"- {self.tr('app.options.syster_ai_model'):13}: {self.syster.ollama_model}",
                f"- {self.tr('app.options.syster_ai_host'):13}: {self.syster.ollama_host or '-'}",
                f"- {self.tr('app.options.update_auto'):13}: {'ON' if self.config.auto_update_check else 'OFF'}",
                f"- {self.tr('app.options.update_repo'):13}: {self.update_manager.repo or '-'}",
                f"- {self.tr('app.options.cloud'):13}: {'ON' if (self.config.cloud_enabled and self.cloud.is_linked()) else 'OFF'}",
                f"- {self.tr('app.options.cloud_endpoint'):13}: {self.cloud.endpoint or '-'}",
                f"- {self.tr('app.options.cloud_user'):13}: {self.config.cloud_auth_username or '-'}",
                f"- {self.tr('app.options.cloud_sync_interval'):13}: {int(self.cloud_sync_cooldown)}s",
                f"- {self.tr('app.options.cloud_news_interval'):13}: {int(self.cloud_news_cooldown)}s",
                f"- {self.tr('app.options.achievements'):13}: {unlocked_count(self.current_slot.flags)}/{len(ACHIEVEMENTS)}",
                f"- {self.tr('app.options.mods_path'):13}: {self.mods_dir}",
                f"- {self.tr('app.options.mods_watch'):13}: {'ON' if self.mod_watcher is not None and self.mod_watcher.is_running() else 'OFF'}",
                f"- {self.tr('app.options.storage'):13}: {self.storage_dir}",
            ]
        )

    def _clamp_slot(self, slot_id: int) -> int:
        return min(max(1, slot_id), self.save_manager.slots)

