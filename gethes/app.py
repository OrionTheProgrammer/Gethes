from __future__ import annotations

import json
import os
import queue
import shlex
import threading
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
from gethes.games.snake import SnakeGame
from gethes.games.tictactoe import TicTacToeGame
from gethes.i18n import I18n
from gethes.runtime_paths import resource_package_dir, user_data_dir
from gethes.save_system import SaveManager
from gethes.story.story_mode import StoryMode
from gethes.syster import SysterAssistant, SysterContext
from gethes.updater import UpdateInfo, UpdateManager
from gethes.ui import ConsoleUI


BUILTIN_THEME_PRESETS: dict[str, tuple[str, str]] = {
    "obsidian": ("#07090D", "#C7D5DF"),
    "void": ("#040507", "#8DA8BA"),
    "deepsea": ("#050B12", "#91D8FF"),
    "matrix": ("#050A07", "#7AF57C"),
    "amber": ("#0D0905", "#FFCF84"),
}
DEFAULT_UPDATE_REPO = "OrionTheProgrammer/Gethes"
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
        self.update_check_running = False
        self.update_install_running = False
        self.update_install_after_check = False
        self.auto_update_check_done = False
        self.pending_update: UpdateInfo | None = None
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
        )
        self.config.update_repo = self.update_manager.repo

        self.save_manager = SaveManager(self.storage_dir / "saves", slots=3)
        self.current_slot = self.save_manager.load_slot(self._clamp_slot(self.config.active_slot))
        self.config.active_slot = self.current_slot.slot_id

        self.syster = SysterAssistant(
            mode=self.config.syster_mode,
            remote_endpoint=self.config.syster_endpoint or None,
        )
        self.config.syster_mode = self.syster.mode

        self.ui = ConsoleUI(
            title=self.tr("ui.title"),
            on_command=self._on_command,
        )
        self.ui.on_close = self._shutdown
        self.ui.on_idle = self._on_idle
        self.ui.set_audio(self.audio)
        self._ensure_modding_templates()
        self.theme_presets = self._load_theme_presets()
        self._reload_audio_assets()

        self.boot_active = False
        self.boot_steps: list[str] = []
        self.boot_completed = 0
        self.boot_timer_ms = 0.0
        self.idle_count = 0
        self.intro_active = False
        self.last_command = "menu"

        self._migrate_legacy_theme()
        self._refresh_ui_language()
        self._apply_visual_config()

        words = self._load_words()
        self.snake = SnakeGame(self)
        self.hangman = HangmanGame(self, words)
        self.story = StoryMode(self, self.data_dir, mod_story_dir=self.story_mods_dir)
        self.tictactoe = TicTacToeGame(self)
        self.codebreaker = CodeBreakerGame(self)

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

    def set_input_handler(self, handler: Callable[[str], None]) -> None:
        self.input_handler = handler

    def clear_input_handler(self) -> None:
        self.input_handler = None

    def on_story_progress(self, page: int, total: int, title: str) -> None:
        self.current_slot.story_page = max(0, page)
        self.current_slot.story_total = max(0, total)
        self.current_slot.story_title = title

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

    def _migrate_legacy_theme(self) -> None:
        legacy_bg = self.config.bg_color.strip().lower()
        legacy_fg = self.config.fg_color.strip().lower()
        if legacy_bg == "#101820" and legacy_fg == "#e8f1f2":
            bg, fg = self.theme_presets.get("obsidian", BUILTIN_THEME_PRESETS["obsidian"])
            self.config.bg_color = bg
            self.config.fg_color = fg

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
                            "",
                            "Theme mod format (pack):",
                            '  {"themes":{"nocturne":{"bg":"#05070B","fg":"#C3CEDA"}}}',
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
                                "nocturne": {"bg": "#05070B", "fg": "#C3CEDA"},
                                "bloodmoon": {"bg": "#10060A", "fg": "#F0B7C1"},
                                "mono_ice": {"bg": "#070B0D", "fg": "#D2E1E8"},
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

    def _load_theme_presets(self) -> dict[str, tuple[str, str]]:
        presets = dict(BUILTIN_THEME_PRESETS)
        for mod_file in sorted(self.theme_mods_dir.glob("*.json")):
            try:
                payload = json.loads(mod_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            for name, bg, fg in self._collect_theme_entries(payload):
                normalized = name.strip().lower().replace(" ", "_")
                if not normalized:
                    continue
                if not self.ui.is_valid_color(bg) or not self.ui.is_valid_color(fg):
                    continue
                presets[normalized] = (bg, fg)

        return presets

    def _collect_theme_entries(self, payload: object) -> list[tuple[str, str, str]]:
        entries: list[tuple[str, str, str]] = []
        if not isinstance(payload, dict):
            return entries

        if all(isinstance(payload.get(k), str) for k in ("name", "bg", "fg")):
            entries.append(
                (
                    str(payload["name"]),
                    str(payload["bg"]),
                    str(payload["fg"]),
                )
            )

        theme_pack = payload.get("themes")
        if isinstance(theme_pack, dict):
            for name, item in theme_pack.items():
                if not isinstance(name, str) or not isinstance(item, dict):
                    continue
                bg = item.get("bg")
                fg = item.get("fg")
                if isinstance(bg, str) and isinstance(fg, str):
                    entries.append((name, bg, fg))

        for name, item in payload.items():
            if name == "themes":
                continue
            if not isinstance(name, str) or not isinstance(item, dict):
                continue
            bg = item.get("bg")
            fg = item.get("fg")
            if isinstance(bg, str) and isinstance(fg, str):
                entries.append((name, bg, fg))

        return entries

    def _reload_theme_presets(self) -> int:
        self.theme_presets = self._load_theme_presets()
        return len(self.theme_presets)

    def _on_idle(self) -> None:
        if self.intro_active or self.boot_active or self.snake.active or self.input_handler is not None:
            return

        if self.idle_count % 3 == 2:
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

        if cmd in {"help", "ayuda", "ajuda", "?"}:
            self.ui.write(self._help_text())
            return

        if cmd in {"clear", "cls"}:
            self.ui.clear()
            return

        if cmd in {"menu", "inicio", "home"}:
            self.ui.set_screen(self._welcome_text())
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

        if cmd in {"opciones", "options", "opcoes"}:
            self.ui.write(self._options_text())
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

        self.ui.write(self.tr("app.unknown", cmd=cmd))

    def _handle_syster(self, args: list[str]) -> None:
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

        self.ui.write(self.tr("app.sfx.usage"))

    def _show_sfx_status(self) -> None:
        loaded = ", ".join(self.audio.loaded_events()) or "-"
        events = ", ".join(self.audio.available_events())
        provider = "ON" if self.sfx_service.is_dependency_available() else "OFF"
        overrides_count = len(self.config.sfx_overrides)

        self.ui.write(self.tr("app.sfx.status", status=self.audio.describe_status()))
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

        self.ui.write(self.tr("app.sfx.bind_downloading", event=event, id=sound_id))
        target_name = f"{event}_{sound_id}.ogg"
        downloaded, error_msg = self.sfx_service.download_preview(
            sound_id=sound_id,
            output_dir=self.user_sfx_dir,
            target_name=target_name,
            quality="lq",
            file_format="ogg",
        )
        if downloaded is None or error_msg:
            self.ui.write(self.tr("app.sfx.bind_failed", error=(error_msg or "unknown")))
            return

        self.config.sfx_overrides[event] = downloaded.name
        self._reload_audio_assets()
        self._save_config()
        self.ui.write(self.tr("app.sfx.bind_done", event=event, file=downloaded.name))
        self.audio.play(event)

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

            self.config.bg_color, self.config.fg_color = theme
            self._apply_visual_config()
            self._save_config()
            self.ui.write(self.tr("app.theme_preset_applied", name=token))
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
        self._apply_visual_config()
        self._save_config()
        self.ui.write(self.tr("app.theme_updated", bg=bg, fg=fg))

    def _show_theme_list(self) -> None:
        self.ui.write(self.tr("app.theme_list_title"))
        active = self._detect_theme_name(self.config.bg_color, self.config.fg_color)
        self.ui.write(self.tr("app.theme_mod_path", path=str(self.theme_mods_dir)))
        for name, colors in self.theme_presets.items():
            mark = ">" if name == active else "-"
            bg, fg = colors
            self.ui.write(self.tr("app.theme_list_item", mark=mark, name=name, bg=bg, fg=fg))

    def _detect_theme_name(self, bg: str, fg: str) -> str:
        for name, colors in self.theme_presets.items():
            if colors[0].lower() == bg.lower() and colors[1].lower() == fg.lower():
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
        if action in {"status", "info"}:
            self._show_update_status()
            return

        if action == "check":
            self._start_update_check(user_feedback=True)
            return

        if action == "install":
            self._start_update_install()
            return

        if action == "repo":
            self._handle_update_repo(args[1:])
            return

        if action == "auto":
            self._handle_update_auto(args[1:])
            return

        self.ui.write(self.tr("app.update.usage"))

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

        if self.pending_update is None:
            self.ui.write(self.tr("app.update.status_none"))
            return

        self.ui.write(
            self.tr(
                "app.update.status_available",
                version=self.pending_update.latest_version,
            )
        )
        self.ui.write(self.tr("app.update.install_hint"))

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

    def _start_update_install(self) -> None:
        if self.update_install_running:
            self.ui.write(self.tr("app.update.busy"))
            return

        if self.pending_update is None:
            self.update_install_after_check = True
            self._start_update_check(user_feedback=True)
            return

        self._start_update_download(self.pending_update)

    def _start_update_download(self, update: UpdateInfo) -> None:
        if self.update_install_running:
            self.ui.write(self.tr("app.update.busy"))
            return

        self.update_install_running = True
        self.ui.write(self.tr("app.update.downloading", version=update.latest_version))
        self.ui.set_status(self.tr("app.update.status_downloading"))

        def worker() -> None:
            try:
                installer = self.update_manager.download_installer(update, self.update_download_dir)
                self.update_events.put(
                    (
                        "install_downloaded",
                        {
                            "path": str(installer),
                            "version": update.latest_version,
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

            if event == "install_failed":
                self._consume_update_install_failed(payload)
                continue

    def _consume_update_check_result(self, payload: dict[str, object]) -> None:
        self.update_check_running = False
        self.ui.set_status(self.tr("ui.ready"))

        status = str(payload.get("status", "invalid_response"))
        info = payload.get("info")
        user_feedback = bool(payload.get("user_feedback", False))
        self.update_last_status = status

        if status == "available" and isinstance(info, UpdateInfo):
            self.pending_update = info
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
                self._start_update_download(info)
            return

        if status == "up_to_date":
            if isinstance(info, UpdateInfo):
                self.pending_update = None
            if user_feedback:
                self.ui.write(self.tr("app.update.latest", version=__version__))
            self.update_install_after_check = False
            return

        self.pending_update = None
        if self.update_install_after_check:
            self.update_install_after_check = False

        if not user_feedback:
            return

        if status == "repo_missing":
            self.ui.write(self.tr("app.update.repo_missing"))
            self.ui.write(self.tr("app.update.repo_hint"))
            return
        if status == "installer_missing":
            self.ui.write(self.tr("app.update.installer_missing"))
            return
        if status == "network_error":
            self.ui.write(self.tr("app.update.network_error"))
            return
        self.ui.write(self.tr("app.update.invalid_response"))

    def _consume_update_downloaded(self, payload: dict[str, object]) -> None:
        self.update_install_running = False

        raw_path = payload.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            self.ui.write(self.tr("app.update.launch_failed"))
            self.ui.set_status(self.tr("ui.ready"))
            return

        installer_path = Path(raw_path)
        if not self.update_manager.launch_installer(installer_path):
            self.ui.write(self.tr("app.update.launch_failed"))
            self.ui.set_status(self.tr("ui.ready"))
            return

        self.ui.write(self.tr("app.update.launching"))
        self.ui.write(self.tr("app.update.installing_exit"))
        self._shutdown()
        self.ui.request_quit()

    def _consume_update_install_failed(self, payload: dict[str, object]) -> None:
        self.update_install_running = False
        self.ui.set_status(self.tr("ui.ready"))
        error_msg = str(payload.get("error", "")).strip()
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
            )
        except Exception:
            self.config = GameConfig()
            self.ui.apply_style(
                bg_color=self.config.bg_color,
                fg_color=self.config.fg_color,
                font_family=self.config.font_family,
                font_size=self.config.font_size,
                ui_scale=self.config.ui_scale,
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
        return "\n".join(
            [
                self.tr("app.help.title"),
                f"- help                     : {self.tr('app.help.help')}",
                f"- clear                    : {self.tr('app.help.clear')}",
                f"- menu                     : {self.tr('app.help.menu')}",
                f"- snake                    : {self.tr('app.help.snake')}",
                f"- ahorcado1 / hangman1     : {self.tr('app.help.hangman1')}",
                f"- ahorcado2 / hangman2     : {self.tr('app.help.hangman2')}",
                f"- gato / tictactoe         : {self.tr('app.help.tictactoe')}",
                f"- codigo / codebreaker     : {self.tr('app.help.codebreaker')}",
                f"- historia / story         : {self.tr('app.help.story')}",
                f"- logros / achievements    : {self.tr('app.help.achievements')}",
                f"- slots                    : {self.tr('app.help.slots')}",
                f"- slot <1-3>               : {self.tr('app.help.slot')}",
                f"- slotname <nombre>        : {self.tr('app.help.slotname')}",
                f"- savegame                 : {self.tr('app.help.savegame')}",
                f"- options / opciones       : {self.tr('app.help.options')}",
                f"- sound <on|off>           : {self.tr('app.help.sound')}",
                f"- graphics <low|medium|high>: {self.tr('app.help.graphics')}",
                f"- uiscale <0.7-2.5>        : {self.tr('app.help.uiscale')}",
                f"- theme <preset|list|reload|bg fg>: {self.tr('app.help.theme')}",
                f"- bg <color>               : {self.tr('app.help.bg')}",
                f"- fg <color>               : {self.tr('app.help.fg')}",
                f"- font <familia> [tamano]  : {self.tr('app.help.font')}",
                f"- fonts [filtro]           : {self.tr('app.help.fonts')}",
                f"- lang [auto|es|en|pt]     : {self.tr('app.help.lang')}",
                f"- update ...               : {self.tr('app.help.update')}",
                f"- syster ...               : {self.tr('app.help.syster')}",
                f"- syster endpoint <url|off>: {self.tr('app.help.syster_endpoint')}",
                f"- sfx                      : {self.tr('app.help.sfx')}",
                f"- save                     : {self.tr('app.help.save')}",
                f"- exit                     : {self.tr('app.help.exit')}",
            ]
        )

    def _options_text(self) -> str:
        active_theme = self._detect_theme_name(self.config.bg_color, self.config.fg_color)
        theme_value = active_theme if active_theme != "custom" else self.tr("app.theme_custom")
        remote_state = "ON" if self.syster.has_remote_endpoint() else "OFF"
        return "\n".join(
            [
                self.tr("app.options.title"),
                f"- {self.tr('app.options.slot'):13}: {self.current_slot.slot_id} ({self.current_slot.route_name})",
                f"- {self.tr('app.options.bg'):13}: {self.config.bg_color}",
                f"- {self.tr('app.options.fg'):13}: {self.config.fg_color}",
                f"- {self.tr('app.options.font'):13}: {self.config.font_family}",
                f"- {self.tr('app.options.font_size'):13}: {self.config.font_size}",
                f"- {self.tr('app.options.sound'):13}: {'ON' if self.config.sound else 'OFF'}",
                f"- {self.tr('app.options.graphics'):13}: {self.config.graphics}",
                f"- {self.tr('app.options.fps'):13}: {self.ui.get_target_fps()}",
                f"- {self.tr('app.options.theme'):13}: {theme_value}",
                f"- {self.tr('app.options.themes_count'):13}: {len(self.theme_presets)}",
                f"- {self.tr('app.options.ui_scale'):13}: {self.config.ui_scale:.2f}x",
                f"- {self.tr('app.options.version'):13}: {__version__}",
                f"- {self.tr('app.options.language'):13}: {self.config.language} -> {self.i18n.active_language}",
                f"- {self.tr('app.options.syster'):13}: {self.syster.mode}",
                f"- {self.tr('app.options.syster_remote'):13}: {remote_state}",
                f"- {self.tr('app.options.update_auto'):13}: {'ON' if self.config.auto_update_check else 'OFF'}",
                f"- {self.tr('app.options.update_repo'):13}: {self.update_manager.repo or '-'}",
                f"- {self.tr('app.options.achievements'):13}: {unlocked_count(self.current_slot.flags)}/{len(ACHIEVEMENTS)}",
                f"- {self.tr('app.options.mods_path'):13}: {self.mods_dir}",
                f"- {self.tr('app.options.storage'):13}: {self.storage_dir}",
            ]
        )

    def _clamp_slot(self, slot_id: int) -> int:
        return min(max(1, slot_id), self.save_manager.slots)
