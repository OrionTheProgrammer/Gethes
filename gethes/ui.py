from __future__ import annotations

import math
import random
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import pygame

try:
    import pygame_menu
except Exception:  # pragma: no cover - optional dependency.
    pygame_menu = None

try:
    import pytweening
except Exception:  # pragma: no cover - optional dependency.
    pytweening = None

from gethes.icon_pack import IconPack
from gethes.runtime_paths import resource_package_dir


@dataclass
class ToastNotification:
    title: str
    message: str
    lifetime: float
    age: float = 0.0
    icon_key: str = "mdi:information-outline"


@dataclass
class ActionButton:
    label: str
    command: str
    enabled: bool = True


THEME_VISUAL_STYLES: set[str] = {
    "terminal",
    "split_h",
    "split_v",
    "grid",
    "diagonal",
    "blueprint",
}


class ConsoleUI:
    def __init__(self, title: str, on_command: Callable[[str], None]) -> None:
        pygame.init()
        pygame.font.init()

        self.base_width = 1080
        self.base_height = 720
        self.width = self.base_width
        self.height = self.base_height
        self.fullscreen = False
        self.windowed_size = (self.width, self.height)
        self.screen = pygame.display.set_mode((self.width, self.height), pygame.RESIZABLE)
        pygame.display.set_caption(title)

        self.command_handler = on_command
        self.on_close: Callable[[], None] | None = None
        self.on_idle: Callable[[], None] | None = None
        self.key_handler: Callable[[str], None] | None = None
        self.audio = None

        self.history: list[str] = []
        self.history_index = 0
        self.echo_commands = True
        self.prompt_text = "Gethes>"
        self.status_text = "Ready."
        self.header_text = "Gethes"
        self.mode_chip_text = "ONLINE"
        self.input_enabled = True
        self.input_mask = False
        self.input_buffer = ""
        self.output_lines: list[str] = []
        self.output_scroll = 0
        self.max_output_lines = 2600
        self._output_revision = 0
        self._wrap_cache_revision = -1
        self._wrap_cache_max_chars = -1
        self._wrap_cache_lines: list[str] = []
        self._line_surface_cache: dict[str, pygame.Surface] = {}
        self._line_surface_cache_limit = 1200

        self.graphics_level = "medium"
        self.target_fps = 60

        self.bg_color = pygame.Color("#07090D")
        self.fg_color = pygame.Color("#C7D5DF")
        self.panel_color = pygame.Color("#0D131B")
        self.dim_color = pygame.Color("#6B8495")
        self.accent_color = pygame.Color("#6CB7E8")
        self.secondary_color = pygame.Color("#101827")
        self.theme_style = "terminal"
        self.scan_strength = 1.0
        self.glow_strength = 1.0
        self.particle_strength = 1.0

        self.font_family = "consolas"
        self.base_font_size = 22
        self.base_ui_font_size = 18
        self.font_size = 22
        self.ui_font_size = 18

        self.user_ui_scale = 1.0
        self.responsive_scale = 1.0
        self.effective_ui_scale = 1.0

        self.notifications: list[ToastNotification] = []
        self.max_notifications = 4
        self.action_buttons: list[ActionButton] = []
        self._action_button_hit_areas: list[tuple[pygame.Rect, ActionButton]] = []
        self.icons = IconPack()
        self.icons.preload(
            [
                "mdi:terminal",
                "mdi:power",
                "mdi:trophy-outline",
                "mdi:information-outline",
                "mdi:account",
                "mdi:wall",
                "mdi:stairs-up",
                "mdi:cash",
                "mdi:flask-round-bottom",
                "mdi:star-four-points",
                "mdi:alert-octagram",
                "mdi:emoticon-devil-outline",
                "mdi:snake",
                "mdi:wolf-outline",
                "mdi:skull",
                "mdi:close-thick",
                "mdi:circle-outline",
            ]
        )
        self._rogue_tile_cache: dict[tuple[object, ...], pygame.Surface] = {}
        self._rogue_asset_raw_cache: dict[str, pygame.Surface] = {}
        self._rogue_tiles_dir: Path = resource_package_dir() / "assets" / "rogue"
        self._snake_tile_cache: dict[tuple[object, ...], pygame.Surface] = {}
        self._snake_asset_raw_cache: dict[str, pygame.Surface] = {}
        self._snake_tiles_dir: Path = resource_package_dir() / "assets" / "snake"
        self._ttt_tile_cache: dict[tuple[object, ...], pygame.Surface] = {}
        self._ttt_asset_raw_cache: dict[str, pygame.Surface] = {}
        self._ttt_tiles_dir: Path = resource_package_dir() / "assets" / "ttt"
        self._layout_rect = pygame.Rect(0, 0, self.width, self.height)

        self._refresh_scale(reload_fonts=True)

        self.clock = pygame.time.Clock()
        self.running = False
        self.cursor_timer = 0.0
        self.cursor_visible = True
        self.idle_elapsed = 0.0
        self.idle_seconds = 35.0
        self.animation_phase = 0.0
        self.glitch_timer = 0.0
        self.session_elapsed = 0.0
        self.panel_intro_duration = 1.15
        self.command_flash = 0.0
        self.typing_glow = 0.0
        self.feedback_flash = 0.0
        self.status_flash = 0.0
        self.screen_shake = 0.0
        self.screen_shake_phase = 0.0
        self.intro_active = False
        self.intro_elapsed = 0.0
        self.intro_duration = 2.6
        self.intro_title = "Gethes"
        self.ambient_glitch_cooldown = random.uniform(5.0, 11.0)
        self.error_overlay_timer = 0.0
        self.error_overlay_cooldown = random.uniform(7.5, 13.5)
        self.error_overlay_text = ""
        self._bg_cache_surface: pygame.Surface | None = None
        self._bg_cache_key: tuple[object, ...] | None = None

    def _refresh_scale(self, reload_fonts: bool) -> None:
        fit = min(self.width / self.base_width, self.height / self.base_height)
        self.responsive_scale = max(0.78, min(2.0, fit))
        self.effective_ui_scale = max(0.7, min(2.8, self.user_ui_scale * self.responsive_scale))

        self.font_size = max(10, min(74, int(round(self.base_font_size * self.effective_ui_scale))))
        self.ui_font_size = max(11, min(66, int(round(self.base_ui_font_size * self.effective_ui_scale))))

        if reload_fonts:
            self._load_fonts()

    def _scale_px(self, value: int) -> int:
        return max(1, int(round(value * self.effective_ui_scale)))

    def _load_fonts(self) -> None:
        font_name = pygame.font.match_font(self.font_family) or pygame.font.match_font("consolas")
        ui_name = pygame.font.match_font(self.font_family) or pygame.font.match_font("arial")
        self.text_font = pygame.font.Font(font_name, self.font_size)
        self.status_font = pygame.font.Font(ui_name, self.ui_font_size)
        self.header_font = pygame.font.Font(ui_name, self.ui_font_size + self._scale_px(2))
        self.chip_font = pygame.font.Font(ui_name, max(12, self.ui_font_size - self._scale_px(2)))
        self.brand_font = pygame.font.Font(ui_name, max(28, self._scale_px(62)))
        self.brand_sub_font = pygame.font.Font(ui_name, max(13, self._scale_px(16)))
        self._line_surface_cache = {}
        self._rogue_tile_cache = {}
        self._snake_tile_cache = {}
        self._ttt_tile_cache = {}
        self.icons.clear_scaled_cache()

    def set_audio(self, audio_manager: object) -> None:
        self.audio = audio_manager

    def start_intro(self, title: str = "Gethes", duration: float = 2.6) -> None:
        self.intro_active = True
        self.intro_elapsed = 0.0
        self.intro_duration = max(1.4, min(8.0, duration))
        self.intro_title = title.strip() or "Gethes"

    def update_intro(self, dt: float) -> bool:
        if not self.intro_active:
            return False
        self.intro_elapsed += dt
        if self.intro_elapsed >= self.intro_duration:
            self.intro_active = False
            return True
        return False

    def run(self, update_callback: Callable[[float], None] | None = None) -> None:
        self.running = True

        while self.running:
            dt = self.clock.tick(self.target_fps) / 1000.0
            self.animation_phase += dt
            self.session_elapsed += dt
            self.cursor_timer += dt
            if self.cursor_timer >= 0.55:
                self.cursor_timer = 0.0
                self.cursor_visible = not self.cursor_visible

            if self.glitch_timer > 0.0:
                self.glitch_timer = max(0.0, self.glitch_timer - dt)
            if self.command_flash > 0.0:
                self.command_flash = max(0.0, self.command_flash - (dt * 1.8))
            if self.typing_glow > 0.0:
                self.typing_glow = max(0.0, self.typing_glow - (dt * 2.1))
            if self.feedback_flash > 0.0:
                self.feedback_flash = max(0.0, self.feedback_flash - (dt * 1.7))
            if self.status_flash > 0.0:
                self.status_flash = max(0.0, self.status_flash - (dt * 1.9))
            if self.screen_shake > 0.0:
                self.screen_shake = max(0.0, self.screen_shake - (dt * 2.8))
            self.screen_shake_phase += dt

            self._update_notifications(dt)
            self._update_ambient_effects(dt)

            for event in pygame.event.get():
                self._handle_event(event)

            if update_callback is not None:
                update_callback(dt)

            self._update_idle(dt)
            self._draw()
            pygame.display.flip()

        pygame.quit()

    def request_quit(self) -> None:
        self.running = False

    def _handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self._close_requested()
            return

        if event.type == pygame.VIDEORESIZE and not self.fullscreen:
            self.width = max(760, event.w)
            self.height = max(500, event.h)
            self.windowed_size = (self.width, self.height)
            self.screen = pygame.display.set_mode((self.width, self.height), pygame.RESIZABLE)
            self._refresh_scale(reload_fonts=True)
            self._invalidate_background_cache()
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            self._register_activity()
            if self.intro_active:
                return
            if event.button == 1 and self._handle_action_button_click(event.pos):
                return
            if event.button == 4:
                self.output_scroll += 2
            elif event.button == 5:
                self.output_scroll = max(0, self.output_scroll - 2)
            return

        if event.type != pygame.KEYDOWN:
            return

        self._register_activity()

        if event.key == pygame.K_F11:
            self._toggle_fullscreen()
            return

        if self.intro_active:
            return

        if self.key_handler and not self.input_enabled:
            key_name = pygame.key.name(event.key).lower()
            self.key_handler(key_name)
            return

        if not self.input_enabled:
            return

        if event.key == pygame.K_RETURN:
            self._submit_command()
            return

        if event.key == pygame.K_BACKSPACE:
            if self.input_buffer:
                self.input_buffer = self.input_buffer[:-1]
                self.typing_glow = min(1.0, self.typing_glow + 0.08)
                self._play_sound("typing")
            return

        if event.key == pygame.K_UP:
            self._history_up()
            return

        if event.key == pygame.K_DOWN:
            self._history_down()
            return

        if event.key == pygame.K_ESCAPE:
            return

        if event.unicode and event.unicode >= " ":
            if len(self.input_buffer) < 280:
                self.input_buffer += event.unicode
                self.typing_glow = min(1.0, self.typing_glow + 0.14)
                self._play_sound("typing")

    def _toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.windowed_size = (self.width, self.height)
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            self.width, self.height = self.screen.get_size()
        else:
            win_w = max(760, self.windowed_size[0])
            win_h = max(500, self.windowed_size[1])
            self.width, self.height = (win_w, win_h)
            self.screen = pygame.display.set_mode((self.width, self.height), pygame.RESIZABLE)

        self._refresh_scale(reload_fonts=True)
        self._invalidate_background_cache()

    def _history_up(self) -> None:
        if not self.history:
            return
        self.history_index = max(0, self.history_index - 1)
        self.input_buffer = self.history[self.history_index]

    def _history_down(self) -> None:
        if not self.history:
            return

        if self.history_index >= len(self.history) - 1:
            self.history_index = len(self.history)
            self.input_buffer = ""
            return

        self.history_index += 1
        self.input_buffer = self.history[self.history_index]

    def _submit_command(self) -> None:
        raw = self.input_buffer
        self.input_buffer = ""
        self.command_flash = 1.0
        self.feedback_flash = min(1.0, self.feedback_flash + 0.22)

        if raw.strip():
            self.history.append(raw)
            self.history_index = len(self.history)
            if self.echo_commands:
                self.write(f"{self.prompt_text} {raw}")

        self.command_handler(raw)
        self._play_sound("message")

    def _handle_action_button_click(self, pos: tuple[int, int]) -> bool:
        if not self.input_enabled or not self._action_button_hit_areas:
            return False
        for rect, button in self._action_button_hit_areas:
            if not button.enabled:
                continue
            if rect.collidepoint(pos):
                self._dispatch_command(button.command)
                return True
        return False

    def _dispatch_command(self, raw: str) -> None:
        command = raw.strip()
        if not command:
            return

        if command.startswith("__append__:"):
            payload = command.split(":", 1)[1]
            if payload and len(self.input_buffer) < 280:
                budget = 280 - len(self.input_buffer)
                self.input_buffer += payload[:budget]
                self.typing_glow = min(1.0, self.typing_glow + 0.12)
                self._play_sound("typing")
            return
        if command == "__backspace__":
            if self.input_buffer:
                self.input_buffer = self.input_buffer[:-1]
                self.typing_glow = min(1.0, self.typing_glow + 0.08)
                self._play_sound("typing")
            return
        if command == "__clear__":
            if self.input_buffer:
                self.input_buffer = ""
                self.typing_glow = min(1.0, self.typing_glow + 0.08)
                self._play_sound("tick")
            return
        if command == "__submit__":
            self._submit_command()
            return

        self.command_flash = 1.0
        self.feedback_flash = min(1.0, self.feedback_flash + 0.24)
        self.input_buffer = ""
        self.history.append(command)
        self.history_index = len(self.history)
        if self.echo_commands:
            self.write(f"{self.prompt_text} {command}")
        self.command_handler(command)
        self._play_sound("message")

    def _close_requested(self) -> None:
        if self.on_close is not None:
            self.on_close()
        self.running = False

    def _update_idle(self, dt: float) -> None:
        if not self.input_enabled or self.key_handler is not None:
            self.idle_elapsed = 0.0
            return

        self.idle_elapsed += dt
        if self.idle_elapsed >= self.idle_seconds:
            self.idle_elapsed = 0.0
            if self.on_idle is not None:
                self.on_idle()

    def _register_activity(self) -> None:
        self.idle_elapsed = 0.0

    def apply_style(
        self,
        bg_color: str,
        fg_color: str,
        font_family: str,
        font_size: int,
        ui_scale: float | None = None,
        accent_color: str | None = None,
        panel_color: str | None = None,
        dim_color: str | None = None,
        secondary_color: str | None = None,
        theme_style: str = "terminal",
        scan_strength: float = 1.0,
        glow_strength: float = 1.0,
        particle_strength: float = 1.0,
    ) -> None:
        try:
            self.bg_color = pygame.Color(bg_color)
            self.fg_color = pygame.Color(fg_color)
        except ValueError:
            self.bg_color = pygame.Color("#07090D")
            self.fg_color = pygame.Color("#C7D5DF")

        self.font_family = font_family.strip() or "consolas"
        self.base_font_size = max(10, min(42, font_size))
        self.base_ui_font_size = max(12, self.base_font_size - 3)

        if ui_scale is not None:
            self.user_ui_scale = max(0.7, min(2.5, float(ui_scale)))

        self._refresh_scale(reload_fonts=True)

        if accent_color:
            try:
                self.accent_color = pygame.Color(accent_color)
            except ValueError:
                self.accent_color = self._derive_accent(self.fg_color)
        else:
            self.accent_color = self._derive_accent(self.fg_color)

        if panel_color:
            try:
                self.panel_color = pygame.Color(panel_color)
            except ValueError:
                self.panel_color = self._mix(self.bg_color, self.accent_color, 0.13)
        else:
            self.panel_color = self._mix(self.bg_color, self.accent_color, 0.13)

        if dim_color:
            try:
                self.dim_color = pygame.Color(dim_color)
            except ValueError:
                self.dim_color = self._mix(self.fg_color, self.bg_color, 0.45)
        else:
            self.dim_color = self._mix(self.fg_color, self.bg_color, 0.45)

        if secondary_color:
            try:
                self.secondary_color = pygame.Color(secondary_color)
            except ValueError:
                self.secondary_color = self._derive_secondary(self.bg_color, self.accent_color)
        else:
            self.secondary_color = self._derive_secondary(self.bg_color, self.accent_color)

        self.theme_style = self._normalize_theme_style(theme_style)
        self.scan_strength = max(0.2, min(2.0, float(scan_strength)))
        self.glow_strength = max(0.2, min(2.0, float(glow_strength)))
        self.particle_strength = max(0.2, min(2.0, float(particle_strength)))
        self._invalidate_background_cache()

    def set_ui_scale(self, value: float) -> None:
        self.user_ui_scale = max(0.7, min(2.5, float(value)))
        self._refresh_scale(reload_fonts=True)
        self._invalidate_background_cache()

    def get_ui_scale(self) -> float:
        return self.user_ui_scale

    def set_graphics_level(self, level: str) -> None:
        normalized = level.lower().strip()
        if normalized not in {"low", "medium", "high"}:
            normalized = "medium"

        self.graphics_level = normalized
        self.target_fps = {
            "low": 40,
            "medium": 60,
            "high": 75,
        }[normalized]
        self._invalidate_background_cache()

    def get_target_fps(self) -> int:
        return self.target_fps

    def get_window_size(self) -> tuple[int, int]:
        return self.width, self.height

    def is_fullscreen(self) -> bool:
        return self.fullscreen

    def get_scale_snapshot(self) -> tuple[float, float, float]:
        return (
            float(self.user_ui_scale),
            float(self.responsive_scale),
            float(self.effective_ui_scale),
        )

    def recommended_user_ui_scale(self) -> float:
        target_effective = 1.32
        recommended = target_effective / max(0.4, float(self.responsive_scale))
        return max(0.7, min(2.5, recommended))

    def is_valid_color(self, color: str) -> bool:
        try:
            pygame.Color(color)
            return True
        except ValueError:
            return False

    def available_fonts(self, text_filter: str = "") -> list[str]:
        names = sorted(set(pygame.font.get_fonts()))
        if not text_filter:
            return names
        lowered = text_filter.casefold()
        return [name for name in names if lowered in name.casefold()]

    def set_prompt(self, value: str) -> None:
        self.prompt_text = value

    def set_title(self, value: str) -> None:
        pygame.display.set_caption(value)

    def set_header(self, value: str) -> None:
        self.header_text = value

    def set_mode_chip(self, value: str) -> None:
        self.mode_chip_text = value

    def set_action_buttons(
        self,
        items: Sequence[tuple[str, str, bool] | tuple[str, str]],
    ) -> None:
        buttons: list[ActionButton] = []
        for item in items:
            if len(item) == 2:
                raw_label, raw_command = item
                enabled = True
            else:
                raw_label, raw_command, enabled = item
            label = str(raw_label).strip()
            command = str(raw_command).strip()
            if not label or not command:
                continue
            buttons.append(ActionButton(label=label, command=command, enabled=bool(enabled)))

        self.action_buttons = buttons
        self._action_button_hit_areas = []

    def clear_action_buttons(self) -> None:
        self.action_buttons = []
        self._action_button_hit_areas = []

    def reload_visual_assets(self) -> None:
        self._rogue_asset_raw_cache = {}
        self._rogue_tile_cache = {}
        self._snake_asset_raw_cache = {}
        self._snake_tile_cache = {}
        self._ttt_asset_raw_cache = {}
        self._ttt_tile_cache = {}

    def reload_rogue_assets(self) -> None:
        # Backward-compatible alias for existing callers.
        self.reload_visual_assets()

    def set_status(self, value: str) -> None:
        if value != self.status_text:
            self.status_flash = min(1.0, self.status_flash + 0.85)
            self.feedback_flash = min(1.0, self.feedback_flash + 0.18)
        self.status_text = value

    def supports_visual_menu(self) -> bool:
        return pygame_menu is not None

    def open_visual_menu(
        self,
        title: str,
        items: Sequence[tuple[str, str]],
        back_label: str,
    ) -> str | None:
        if pygame_menu is None or not self.running:
            return None

        result: dict[str, str | None] = {"command": None}
        accent = (self.accent_color.r, self.accent_color.g, self.accent_color.b)
        foreground = (self.fg_color.r, self.fg_color.g, self.fg_color.b)
        background = (self.bg_color.r, self.bg_color.g, self.bg_color.b)

        theme = pygame_menu.themes.THEME_DARK.copy()
        theme.background_color = background
        theme.selection_color = accent
        theme.title_background_color = background
        theme.title_font_color = foreground
        theme.widget_font_color = foreground
        try:
            theme.widget_selection_effect = pygame_menu.widgets.LeftArrowSelection(arrow_size=(10, 14))
        except Exception:
            pass
        theme.widget_margin = (0, 7)
        theme.scrollbar_color = accent
        theme.scrollbar_slider_color = foreground

        menu_width = min(self.width - self._scale_px(80), self._scale_px(640))
        menu_height = min(self.height - self._scale_px(80), self._scale_px(520))

        menu = pygame_menu.Menu(
            title=title,
            width=max(self._scale_px(360), menu_width),
            height=max(self._scale_px(300), menu_height),
            theme=theme,
        )

        def select_command(command_value: str | None = None) -> None:
            result["command"] = command_value
            menu.disable()

        for label, command in items:
            menu.add.button(label, select_command, command)
        menu.add.button(back_label, select_command, None)

        while self.running and result["command"] is None and menu.is_enabled():
            dt = self.clock.tick(self.target_fps) / 1000.0
            self.animation_phase += dt
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    self._close_requested()
                    return None
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    menu.disable()
                    return None
                if event.type in {pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN}:
                    self._register_activity()

            self._draw_background()
            menu.update(events)
            menu.draw(self.screen)
            pygame.display.flip()

        return result["command"]

    def set_key_handler(self, handler: Callable[[str], None] | None) -> None:
        self.key_handler = handler

    def set_entry_enabled(self, enabled: bool) -> None:
        self.input_enabled = enabled
        if not enabled:
            self.input_buffer = ""
            self.clear_action_buttons()

    def set_echo(self, enabled: bool) -> None:
        self.echo_commands = enabled

    def set_input_mask(self, masked: bool) -> None:
        self.input_mask = masked

    def clear(self) -> None:
        self.set_screen("")

    def set_screen(self, content: str) -> None:
        if not content:
            self.output_lines = []
        else:
            self.output_lines = content.splitlines()
        self._trim_output_lines()
        self._output_revision += 1
        self.output_scroll = 0

    def write(self, content: str = "", play_sound: bool = True) -> None:
        lines = content.splitlines() or [""]
        self.output_lines.extend(lines)
        self._trim_output_lines()
        self._output_revision += 1
        self.output_scroll = 0

        joined = " ".join(lines).casefold()
        is_error_like = any(
            token in joined
            for token in (
                "error",
                "failed",
                "inval",
                "unknown",
                "missing",
                "denied",
                "fallo",
                "falha",
                "no se pudo",
                "no disponible",
            )
        )
        if is_error_like:
            self.feedback_flash = min(1.0, self.feedback_flash + 0.5)
            self.status_flash = min(1.0, self.status_flash + 0.4)
            self.screen_shake = max(self.screen_shake, 0.55)
            self.trigger_glitch(0.26)
            self._trigger_error_overlay(force_text="TERMINAL WARNING")
        else:
            self.feedback_flash = min(1.0, self.feedback_flash + 0.24)

        if play_sound:
            self._play_sound("message")

    def push_notification(
        self,
        title: str,
        message: str = "",
        duration: float = 3.8,
        icon_key: str = "mdi:information-outline",
    ) -> None:
        toast = ToastNotification(
            title=title.strip() or "Notification",
            message=message.strip(),
            lifetime=max(1.8, min(9.0, duration)),
            icon_key=icon_key,
        )
        self.notifications.append(toast)
        if len(self.notifications) > self.max_notifications:
            self.notifications = self.notifications[-self.max_notifications :]
        self.feedback_flash = min(1.0, self.feedback_flash + 0.35)
        self.status_flash = min(1.0, self.status_flash + 0.45)

    def _trim_output_lines(self) -> None:
        extra = len(self.output_lines) - self.max_output_lines
        if extra <= 0:
            return
        del self.output_lines[:extra]
        self.output_scroll = max(0, self.output_scroll - extra)

    def _get_wrapped_output(self, max_chars: int) -> list[str]:
        if (
            self._wrap_cache_revision == self._output_revision
            and self._wrap_cache_max_chars == max_chars
        ):
            return self._wrap_cache_lines

        wrapped = self._wrap_lines(self.output_lines, max_chars=max_chars)
        self._wrap_cache_lines = wrapped
        self._wrap_cache_max_chars = max_chars
        self._wrap_cache_revision = self._output_revision
        return wrapped

    def _invalidate_background_cache(self) -> None:
        self._bg_cache_surface = None
        self._bg_cache_key = None

    def _rebuild_background_cache(self) -> None:
        key = (
            self.width,
            self.height,
            self.bg_color.normalize(),
            self.fg_color.normalize(),
            self.accent_color.normalize(),
            self.secondary_color.normalize(),
            self.panel_color.normalize(),
            self.dim_color.normalize(),
            self.theme_style,
            self.graphics_level,
            round(self.scan_strength, 3),
            round(self.glow_strength, 3),
            round(self.particle_strength, 3),
            int(round(self.effective_ui_scale * 100)),
        )
        if self._bg_cache_surface is not None and self._bg_cache_key == key:
            return

        surface = pygame.Surface((self.width, self.height))
        self._paint_background(surface)

        self._bg_cache_surface = surface.convert()
        self._bg_cache_key = key

    def _paint_background(self, surface: pygame.Surface) -> None:
        style = self.theme_style
        if style == "split_h":
            self._paint_split_background(surface, vertical=False)
            self._paint_scanlines(surface, mix_ratio=0.09)
            return
        if style == "split_v":
            self._paint_split_background(surface, vertical=True)
            self._paint_scanlines(surface, mix_ratio=0.08)
            return
        if style == "grid":
            self._paint_grid_background(surface)
            self._paint_scanlines(surface, mix_ratio=0.06)
            return
        if style == "diagonal":
            self._paint_diagonal_background(surface)
            self._paint_scanlines(surface, mix_ratio=0.07)
            return
        if style == "blueprint":
            self._paint_blueprint_background(surface)
            self._paint_scanlines(surface, mix_ratio=0.05)
            return
        self._paint_terminal_background(surface)

    def _paint_terminal_background(self, surface: pygame.Surface) -> None:
        base = self.bg_color
        top = self._mix(base, self.accent_color, min(0.16, 0.05 + (0.03 * self.glow_strength)))
        line_step = 2 if self.graphics_level == "low" else 1
        for y in range(0, self.height, line_step):
            t = y / max(1, self.height - 1)
            blend = (0.1 * (1.0 - t)) + (0.04 * (0.5 + 0.5 * math.sin(t * 5.0)))
            color = self._mix(base, top, blend)
            pygame.draw.line(surface, color, (0, y), (self.width, y), width=line_step)
        self._paint_scanlines(surface, mix_ratio=0.1)

        if self.graphics_level != "low":
            stripe = self._mix(self.accent_color, self.bg_color, 0.75)
            if self.graphics_level == "high":
                diag_gap = max(self._scale_px(56), 34)
            else:
                diag_gap = max(self._scale_px(72), 48)
            for x in range(-self.height, self.width + self.height, diag_gap):
                pygame.draw.line(
                    surface,
                    stripe,
                    (x, 0),
                    (x - self.height // 3, self.height),
                    1,
                )

    def _paint_split_background(self, surface: pygame.Surface, vertical: bool) -> None:
        first = self._mix(self.bg_color, self.accent_color, 0.06)
        second = self._mix(self.secondary_color, self.panel_color, 0.06)
        blend = max(self._scale_px(32), 18)
        if vertical:
            mid = self.width // 2
            for x in range(0, self.width):
                if x < mid - blend:
                    color = first
                elif x > mid + blend:
                    color = second
                else:
                    ratio = (x - (mid - blend)) / max(1, blend * 2)
                    color = self._mix(first, second, ratio)
                pygame.draw.line(surface, color, (x, 0), (x, self.height))
            seam = self._mix(self.accent_color, self.fg_color, 0.18)
            pygame.draw.line(surface, seam, (mid, 0), (mid, self.height), 1)
            return

        mid = self.height // 2
        for y in range(0, self.height):
            if y < mid - blend:
                color = first
            elif y > mid + blend:
                color = second
            else:
                ratio = (y - (mid - blend)) / max(1, blend * 2)
                color = self._mix(first, second, ratio)
            pygame.draw.line(surface, color, (0, y), (self.width, y))
        seam = self._mix(self.accent_color, self.fg_color, 0.18)
        pygame.draw.line(surface, seam, (0, mid), (self.width, mid), 1)

    def _paint_grid_background(self, surface: pygame.Surface) -> None:
        base = self._mix(self.bg_color, self.secondary_color, 0.23)
        top = self._mix(base, self.accent_color, 0.08)
        line_step = 2 if self.graphics_level == "low" else 1
        for y in range(0, self.height, line_step):
            t = y / max(1, self.height - 1)
            color = self._mix(base, top, 0.18 * (1.0 - t))
            pygame.draw.line(surface, color, (0, y), (self.width, y), width=line_step)

        minor = max(self._scale_px(22), 14)
        major = minor * 4
        minor_color = self._mix(self.secondary_color, self.dim_color, 0.38)
        major_color = self._mix(self.accent_color, self.fg_color, 0.22)
        for x in range(0, self.width, minor):
            color = major_color if x % major == 0 else minor_color
            pygame.draw.line(surface, color, (x, 0), (x, self.height), 1)
        for y in range(0, self.height, minor):
            color = major_color if y % major == 0 else minor_color
            pygame.draw.line(surface, color, (0, y), (self.width, y), 1)

    def _paint_diagonal_background(self, surface: pygame.Surface) -> None:
        surface.fill(self._mix(self.bg_color, self.panel_color, 0.16))
        band = max(self._scale_px(86), 48)
        stripe = max(8, band // 2)
        tone_a = self._mix(self.bg_color, self.accent_color, 0.14)
        tone_b = self._mix(self.secondary_color, self.panel_color, 0.12)
        index = 0
        for offset in range(-self.height, self.width + self.height, band):
            color = tone_a if index % 2 == 0 else tone_b
            pygame.draw.line(
                surface,
                color,
                (offset, 0),
                (offset - self.height, self.height),
                stripe,
            )
            index += 1

    def _paint_blueprint_background(self, surface: pygame.Surface) -> None:
        base = self._mix(self.bg_color, self.secondary_color, 0.28)
        surface.fill(base)
        dot_step = max(self._scale_px(18), 12)
        dot_color = self._mix(self.dim_color, self.accent_color, 0.22)
        for y in range(dot_step // 2, self.height, dot_step):
            shift = 0 if ((y // dot_step) % 2 == 0) else (dot_step // 2)
            for x in range(shift + (dot_step // 2), self.width, dot_step):
                pygame.draw.circle(surface, dot_color, (x, y), 1)

        ring_center = (self.width // 2, self.height // 2)
        ring_color = self._mix(self.accent_color, self.fg_color, 0.24)
        for idx in range(3):
            radius = max(self._scale_px(90), int(min(self.width, self.height) * (0.18 + (idx * 0.12))))
            pygame.draw.circle(surface, ring_color, ring_center, radius, 1)

    def _paint_scanlines(self, surface: pygame.Surface, mix_ratio: float) -> None:
        scan = self._mix(
            self.bg_color,
            self.fg_color,
            min(0.2, max(0.02, mix_ratio + (0.028 * self.scan_strength))),
        )
        if self.graphics_level == "low":
            step = max(6, self._scale_px(8))
        elif self.graphics_level == "high":
            step = max(2, self._scale_px(3))
        else:
            step = max(3, self._scale_px(4))
        step = max(1, int(step / max(0.6, self.scan_strength)))
        for y in range(0, self.height, step):
            pygame.draw.line(surface, scan, (0, y), (self.width, y))

    def _update_notifications(self, dt: float) -> None:
        if not self.notifications:
            return

        kept: list[ToastNotification] = []
        for toast in self.notifications:
            toast.age += dt
            if toast.age < toast.lifetime:
                kept.append(toast)
        self.notifications = kept

    def _update_ambient_effects(self, dt: float) -> None:
        if self.intro_active or self.graphics_level == "low":
            self.error_overlay_timer = max(0.0, self.error_overlay_timer - dt)
            return

        self.error_overlay_timer = max(0.0, self.error_overlay_timer - dt)
        self.ambient_glitch_cooldown -= dt
        self.error_overlay_cooldown -= dt

        if self.ambient_glitch_cooldown <= 0.0:
            self.ambient_glitch_cooldown = random.uniform(4.6, 11.2)
            if random.random() < (0.62 if self.graphics_level == "high" else 0.44):
                burst = random.uniform(0.16, 0.48)
                self.trigger_glitch(burst)

        if self.error_overlay_cooldown <= 0.0:
            self.error_overlay_cooldown = random.uniform(8.5, 14.0)
            probability = 0.32 if self.graphics_level == "high" else 0.18
            if random.random() < probability:
                self._trigger_error_overlay()

    def _trigger_error_overlay(self, force_text: str = "") -> None:
        self.error_overlay_timer = max(self.error_overlay_timer, random.uniform(0.24, 0.72))
        if force_text.strip():
            self.error_overlay_text = force_text.strip()[:32]
        else:
            self.error_overlay_text = random.choice(
                [
                    "SIGNAL DESYNC",
                    "FRAME CORRUPT",
                    "MEMORY ECHO",
                    "TRACE NOISE",
                    "SCAN FAULT",
                ]
            )

    def trigger_glitch(self, duration: float = 0.8) -> None:
        self.glitch_timer = max(self.glitch_timer, duration)

    def _play_sound(self, event: str) -> None:
        if self.audio is None:
            return
        try:
            self.audio.play(event)
        except Exception:
            pass

    def _draw(self) -> None:
        if self.intro_active:
            self._draw_intro()
            return

        self._draw_background()
        self._draw_feedback_overlay()

        shake_x = 0
        shake_y = 0
        if self.screen_shake > 0.0 and self.graphics_level != "low":
            amp = max(1, self._scale_px(2))
            wave = 0.35 + (0.65 * self.screen_shake)
            shake_x = int(math.sin(self.screen_shake_phase * 37.0) * amp * wave)
            shake_y = int(math.cos(self.screen_shake_phase * 31.0) * amp * wave)

        margin = self._scale_px(14)
        header_h = self._scale_px(52)
        status_h = self._scale_px(30)
        input_h = self._scale_px(46)
        gap = self._scale_px(10)

        max_content_w = self.width - (margin * 2)
        if self.width >= self._scale_px(1380):
            capped = self._scale_px(1380)
            max_content_w = min(max_content_w, capped)
        max_content_w = max(self._scale_px(560), max_content_w)
        actions_h = self._action_buttons_panel_height(max_content_w=max_content_w)
        min_output_h = self._scale_px(110)
        max_actions_h = max(
            0,
            self.height
            - (margin * 2)
            - header_h
            - status_h
            - input_h
            - (gap * 3)
            - min_output_h,
        )
        actions_h = min(actions_h, max_actions_h)
        content_x = ((self.width - max_content_w) // 2) + shake_x
        self._layout_rect = pygame.Rect(content_x, margin + shake_y, max_content_w, self.height - (margin * 2))

        header_rect = pygame.Rect(content_x, margin + shake_y, max_content_w, header_h)
        status_rect = pygame.Rect(
            content_x,
            self.height - margin - status_h + shake_y,
            max_content_w,
            status_h,
        )
        input_bottom = status_rect.top - gap + shake_y
        input_rect = pygame.Rect(content_x, input_bottom - input_h, max_content_w, input_h)
        actions_rect = pygame.Rect(content_x, input_rect.top - gap - actions_h, max_content_w, actions_h)
        output_rect = pygame.Rect(
            content_x,
            header_rect.bottom + gap + shake_y,
            max_content_w,
            actions_rect.top - header_rect.bottom - (gap * 2),
        )
        self._apply_panel_entry_animation(header_rect, output_rect, input_rect, status_rect)

        self._draw_panel(output_rect)
        self._draw_panel(input_rect)
        if actions_h > 0:
            self._draw_panel(actions_rect)
        self._draw_panel(header_rect)
        self._draw_panel(status_rect)

        self._draw_header(header_rect)
        self._draw_output(output_rect)
        if actions_h > 0:
            self._draw_action_buttons(actions_rect)
        else:
            self._action_button_hit_areas = []
        self._draw_input(input_rect)
        self._draw_status(status_rect)
        self._draw_notifications()
        self._draw_error_overlay()

    def _draw_background(self) -> None:
        self._rebuild_background_cache()
        if self._bg_cache_surface is not None:
            self.screen.blit(self._bg_cache_surface, (0, 0))

        moving_base = self._mix(self.accent_color, self.secondary_color, 0.38)
        glow = self._mix(
            moving_base,
            self.bg_color,
            max(0.32, min(0.75, 0.58 - ((self.glow_strength - 1.0) * 0.15))),
        )
        y1 = int((0.5 + 0.5 * math.sin(self.animation_phase * 0.7)) * max(1, self.height - 1))
        if self.theme_style == "split_v":
            x1 = int((0.5 + 0.5 * math.sin(self.animation_phase * 0.7)) * max(1, self.width - 1))
            pygame.draw.line(self.screen, glow, (x1, 0), (x1, self.height), 1)
        elif self.theme_style == "diagonal":
            span = self.height // 3
            pygame.draw.line(self.screen, glow, (0, y1), (self.width, max(0, y1 - span)), 1)
        else:
            pygame.draw.line(self.screen, glow, (0, y1), (self.width, y1), 1)
        if self.graphics_level in {"medium", "high"}:
            y2 = int((0.5 + 0.5 * math.sin((self.animation_phase * 0.9) + 1.3)) * max(1, self.height - 1))
            if self.theme_style == "split_v":
                x2 = int((0.5 + 0.5 * math.sin((self.animation_phase * 0.9) + 1.3)) * max(1, self.width - 1))
                pygame.draw.line(self.screen, self._mix(glow, self.bg_color, 0.4), (x2, 0), (x2, self.height), 1)
            else:
                pygame.draw.line(self.screen, self._mix(glow, self.bg_color, 0.4), (0, y2), (self.width, y2), 1)
        if self.graphics_level == "high":
            y3 = int((0.5 + 0.5 * math.sin((self.animation_phase * 1.25) + 0.4)) * max(1, self.height - 1))
            if self.theme_style == "diagonal":
                pygame.draw.line(
                    self.screen,
                    self._mix(glow, self.bg_color, 0.58),
                    (0, y3),
                    (self.width, max(0, y3 - (self.height // 4))),
                    1,
                )
            else:
                pygame.draw.line(self.screen, self._mix(glow, self.bg_color, 0.58), (0, y3), (self.width, y3), 1)

        if self.graphics_level in {"medium", "high"}:
            layers = 2 if self.graphics_level == "high" else 1
            for layer_idx in range(layers):
                parallax = 0.62 + (layer_idx * 0.48)
                base_count = (13 if self.graphics_level == "medium" else 19) + (layer_idx * 7)
                particle_count = max(2, int(round(base_count * self.particle_strength)))
                particle_color = self._mix(
                    self._mix(self.accent_color, self.secondary_color, 0.35),
                    self.fg_color,
                    0.22 + (0.08 * layer_idx),
                )

                for idx in range(particle_count):
                    seed = idx + (layer_idx * 53)
                    speed_x = (18.0 + ((seed % 5) * 5.0)) * parallax
                    speed_y = (11.0 + ((seed % 7) * 2.5)) * parallax
                    wobble = math.sin((self.animation_phase * (0.8 + (layer_idx * 0.16))) + (seed * 0.57)) * (16.0 + (layer_idx * 11.0))

                    px = int(((seed * 139.0) + (self.animation_phase * speed_x)) % max(1, self.width))
                    py = int((((seed * 83.0) + (self.animation_phase * speed_y)) + wobble) % max(1, self.height))

                    twinkle = 0.35 + (0.65 * (0.5 + 0.5 * math.sin((self.animation_phase * 1.7) + (seed * 0.81))))
                    radius = 1 + (1 if (self.graphics_level == "high" and (seed % 9 == 0)) else 0)
                    alpha = int((20 + (30 * parallax)) * twinkle * self.glow_strength)

                    if self.graphics_level == "high" and (seed % 4 == 0):
                        tail = int((7 + (seed % 5)) * parallax)
                        prev_x = int((px - tail) % max(1, self.width))
                        trail_color = self._mix(particle_color, self.bg_color, 0.55)
                        pygame.draw.line(
                            self.screen,
                            (trail_color.r, trail_color.g, trail_color.b, max(12, alpha // 2)),
                            (prev_x, py),
                            (px, py),
                            1,
                        )

                    layer = pygame.Surface((radius * 4, radius * 4), pygame.SRCALPHA)
                    pygame.draw.circle(
                        layer,
                        (particle_color.r, particle_color.g, particle_color.b, alpha),
                        (radius * 2, radius * 2),
                        radius,
                    )
                    self.screen.blit(layer, (px - (radius * 2), py - (radius * 2)))

    def _draw_feedback_overlay(self) -> None:
        energy = max(
            self.feedback_flash * 0.95,
            self.command_flash * 0.75,
            self.typing_glow * 0.5,
            self.status_flash * 0.62,
        )
        if energy <= 0.01:
            return

        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        glow_color = self._mix(self.accent_color, pygame.Color("#FFFFFF"), 0.28)
        alpha = int(58 * min(1.0, energy) * self.glow_strength)

        input_center = (self.width // 2, int(self.height * 0.84))
        input_radius = max(self._scale_px(120), int(self.width * 0.19))
        pygame.draw.circle(
            overlay,
            (glow_color.r, glow_color.g, glow_color.b, alpha),
            input_center,
            input_radius,
        )

        header_center = (self.width // 2, int(self._scale_px(40)))
        header_radius = max(self._scale_px(64), int(self.width * 0.11))
        pygame.draw.circle(
            overlay,
            (glow_color.r, glow_color.g, glow_color.b, int(alpha * 0.55)),
            header_center,
            header_radius,
        )

        if self.status_flash > 0.01:
            band_alpha = int(46 * min(1.0, self.status_flash) * self.scan_strength)
            band_h = max(self._scale_px(4), 2)
            band = pygame.Surface((self.width, band_h), pygame.SRCALPHA)
            pygame.draw.rect(
                band,
                (glow_color.r, glow_color.g, glow_color.b, max(12, band_alpha)),
                band.get_rect(),
                border_radius=self._scale_px(4),
            )
            top_y = self._scale_px(56)
            overlay.blit(band, (0, top_y))

        if self.feedback_flash > 0.2:
            side_alpha = int(24 * min(1.0, self.feedback_flash) * self.glow_strength)
            side_w = max(self._scale_px(2), 1)
            pygame.draw.rect(
                overlay,
                (glow_color.r, glow_color.g, glow_color.b, max(10, side_alpha)),
                pygame.Rect(0, 0, side_w, self.height),
            )
            pygame.draw.rect(
                overlay,
                (glow_color.r, glow_color.g, glow_color.b, max(10, side_alpha)),
                pygame.Rect(self.width - side_w, 0, side_w, self.height),
            )

        self.screen.blit(overlay, (0, 0))

    def _draw_panel(self, rect: pygame.Rect) -> None:
        style = self.theme_style
        radius = self._scale_px(5) if style in {"split_h", "split_v", "grid"} else self._scale_px(9)
        border_width = 2 if style in {"split_h", "split_v"} else 1
        shadow = pygame.Rect(rect.x, rect.y + self._scale_px(2), rect.width, rect.height)
        pygame.draw.rect(
            self.screen,
            self._mix(self.bg_color, pygame.Color("#000000"), 0.45),
            shadow,
            border_radius=radius,
        )
        pygame.draw.rect(self.screen, self.panel_color, rect, border_radius=radius)
        if style in {"split_h", "split_v"}:
            bar = pygame.Rect(rect)
            if style == "split_h":
                bar.height = max(self._scale_px(3), 2)
            else:
                bar.width = max(self._scale_px(3), 2)
            bar_color = self._mix(self.secondary_color, self.accent_color, 0.45)
            pygame.draw.rect(self.screen, bar_color, bar, border_radius=radius)
        if style == "grid":
            inset = rect.inflate(-self._scale_px(8), -self._scale_px(8))
            if inset.width > 8 and inset.height > 8:
                grid_color = self._mix(self.secondary_color, self.dim_color, 0.42)
                for x in range(inset.x, inset.right, max(self._scale_px(24), 12)):
                    pygame.draw.line(self.screen, grid_color, (x, inset.y), (x, inset.bottom), 1)
                for y in range(inset.y, inset.bottom, max(self._scale_px(24), 12)):
                    pygame.draw.line(self.screen, grid_color, (inset.x, y), (inset.right, y), 1)
        if style == "diagonal":
            diag = self._mix(self.secondary_color, self.accent_color, 0.32)
            pygame.draw.line(
                self.screen,
                diag,
                (rect.x + self._scale_px(2), rect.bottom - self._scale_px(2)),
                (rect.right - self._scale_px(2), rect.y + self._scale_px(2)),
                1,
            )
        if style == "blueprint":
            corner = self._mix(self.secondary_color, self.accent_color, 0.5)
            arm = self._scale_px(10)
            pygame.draw.line(self.screen, corner, (rect.x, rect.y), (rect.x + arm, rect.y), 1)
            pygame.draw.line(self.screen, corner, (rect.x, rect.y), (rect.x, rect.y + arm), 1)
            pygame.draw.line(self.screen, corner, (rect.right, rect.y), (rect.right - arm, rect.y), 1)
            pygame.draw.line(self.screen, corner, (rect.right, rect.y), (rect.right, rect.y + arm), 1)
            pygame.draw.line(self.screen, corner, (rect.x, rect.bottom), (rect.x + arm, rect.bottom), 1)
            pygame.draw.line(self.screen, corner, (rect.x, rect.bottom), (rect.x, rect.bottom - arm), 1)
            pygame.draw.line(self.screen, corner, (rect.right, rect.bottom), (rect.right - arm, rect.bottom), 1)
            pygame.draw.line(self.screen, corner, (rect.right, rect.bottom), (rect.right, rect.bottom - arm), 1)
        pygame.draw.rect(self.screen, self.accent_color, rect, width=border_width, border_radius=radius)
        if style == "terminal":
            top_bar = pygame.Rect(rect.x + self._scale_px(2), rect.y + self._scale_px(2), rect.width - self._scale_px(4), self._scale_px(2))
            glow = self._mix(self.accent_color, self.secondary_color, 0.24)
            pygame.draw.rect(self.screen, glow, top_bar, border_radius=self._scale_px(2))
        if self.feedback_flash > 0.0:
            edge_color = self._mix(self.accent_color, pygame.Color("#FFFFFF"), 0.2)
            glow_alpha = int(34 * min(1.0, self.feedback_flash) * self.glow_strength)
            if glow_alpha > 0:
                glow_layer = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
                pygame.draw.rect(
                    glow_layer,
                    (edge_color.r, edge_color.g, edge_color.b, glow_alpha),
                    glow_layer.get_rect(),
                    border_radius=radius,
                )
                self.screen.blit(glow_layer, rect.topleft)
        if self.command_flash > 0.0:
            pulse = self._mix(self.accent_color, pygame.Color("#FFFFFF"), 0.2)
            thickness = 1 + int(self.command_flash * 1.8)
            pygame.draw.rect(
                self.screen,
                pulse,
                rect.inflate(self._scale_px(2), self._scale_px(2)),
                width=thickness,
                border_radius=radius,
            )

    def _draw_header(self, rect: pygame.Rect) -> None:
        pulse = 0.45 + 0.4 * (0.5 + 0.5 * math.sin(self.animation_phase * 2.4))
        pulse += self.command_flash * 0.45
        glow = self._mix(self.accent_color, pygame.Color("#FFFFFF"), 0.15 * pulse)
        style = self.theme_style

        if style in {"split_h", "split_v"}:
            if style == "split_h":
                top_band = pygame.Rect(rect.x + self._scale_px(2), rect.y + self._scale_px(2), rect.width - self._scale_px(4), self._scale_px(4))
                pygame.draw.rect(self.screen, self._mix(self.secondary_color, self.accent_color, 0.45), top_band, border_radius=self._scale_px(2))
            else:
                left_band = pygame.Rect(rect.x + self._scale_px(2), rect.y + self._scale_px(2), self._scale_px(4), rect.height - self._scale_px(4))
                pygame.draw.rect(self.screen, self._mix(self.secondary_color, self.accent_color, 0.45), left_band, border_radius=self._scale_px(2))
        elif style == "grid":
            grid_color = self._mix(self.secondary_color, self.dim_color, 0.5)
            step = max(self._scale_px(20), 12)
            for x in range(rect.x + self._scale_px(8), rect.right - self._scale_px(8), step):
                pygame.draw.line(self.screen, grid_color, (x, rect.y + self._scale_px(6)), (x, rect.bottom - self._scale_px(6)), 1)
        elif style == "diagonal":
            diag_color = self._mix(self.secondary_color, self.accent_color, 0.42)
            pygame.draw.line(
                self.screen,
                diag_color,
                (rect.x + self._scale_px(8), rect.bottom - self._scale_px(4)),
                (rect.x + self._scale_px(44), rect.y + self._scale_px(4)),
                2,
            )
        elif style == "blueprint":
            tick = self._mix(self.secondary_color, self.accent_color, 0.5)
            tick_gap = max(self._scale_px(24), 14)
            for x in range(rect.x + self._scale_px(12), rect.right - self._scale_px(12), tick_gap):
                pygame.draw.line(
                    self.screen,
                    tick,
                    (x, rect.bottom - self._scale_px(3)),
                    (x, rect.bottom - self._scale_px(8)),
                    1,
                )

        title_x = rect.x + self._scale_px(12)
        icon_size = self._scale_px(22)
        title_icon = self.icons.get_icon("mdi:terminal", icon_size, glow)
        if title_icon is not None:
            self.screen.blit(
                title_icon,
                (
                    title_x,
                    rect.y + ((rect.height - title_icon.get_height()) // 2),
                ),
            )
            title_x += title_icon.get_width() + self._scale_px(8)

        header_surface = self.header_font.render(self.header_text, True, glow)
        self.screen.blit(header_surface, (title_x, rect.y + self._scale_px(12)))

        chip_text = self._contrast_text(self.accent_color)
        chip_surface = self.chip_font.render(self.mode_chip_text, True, chip_text)
        chip_padding_x = self._scale_px(14)
        chip_w = chip_surface.get_width() + (chip_padding_x * 2)
        chip_h = rect.height - self._scale_px(14)
        chip_rect = pygame.Rect(rect.right - chip_w - self._scale_px(10), rect.y + self._scale_px(7), chip_w, chip_h)
        chip_bg = self._mix(self.accent_color, self.secondary_color, 0.22)
        pygame.draw.rect(self.screen, chip_bg, chip_rect, border_radius=self._scale_px(8))
        pygame.draw.rect(
            self.screen,
            self._mix(self.fg_color, self.accent_color, 0.18),
            chip_rect,
            width=1,
            border_radius=self._scale_px(8),
        )
        self.screen.blit(
            chip_surface,
            (
                chip_rect.x + chip_padding_x,
                chip_rect.y + (chip_rect.height - chip_surface.get_height()) // 2,
            ),
        )

    def _draw_output(self, rect: pygame.Rect) -> None:
        char_w = max(1, self.text_font.size("M")[0])
        max_chars = max(8, (rect.width - self._scale_px(18)) // char_w)
        wrapped = self._get_wrapped_output(max_chars=max_chars)

        line_h = self.text_font.get_linesize()
        max_lines = max(1, (rect.height - self._scale_px(14)) // line_h)
        max_scroll = max(0, len(wrapped) - max_lines)
        self.output_scroll = min(self.output_scroll, max_scroll)

        end_index = len(wrapped) - self.output_scroll
        start_index = max(0, end_index - max_lines)
        visible = wrapped[start_index:end_index]

        allow_glitch = self.graphics_level != "low"
        offset_x = random.randint(-2, 2) if (self.glitch_timer > 0 and allow_glitch) else 0
        offset_y = random.randint(-1, 1) if (self.glitch_timer > 0 and allow_glitch) else 0

        is_rogue_screen = any("ROGUELIKE //" in line for line in self.output_lines[:6])
        is_snake_screen = any(line.startswith("SNAKE |") for line in self.output_lines[:8])
        is_ttt_screen = any(
            ("TIC-TAC-TOE" in line)
            or ("GATO / TRES EN RAYA" in line)
            or ("JOGO DA VELHA" in line)
            for line in self.output_lines[:8]
        )
        y = rect.y + self._scale_px(8) + offset_y
        x = rect.x + self._scale_px(10) + offset_x
        for line in visible:
            if is_rogue_screen and self._draw_rogue_tile_row(
                line=line,
                x=x,
                y=y,
                char_w=char_w,
                line_h=line_h,
            ):
                y += line_h
                continue
            if is_snake_screen and self._draw_snake_tile_row(
                line=line,
                x=x,
                y=y,
                char_w=char_w,
                line_h=line_h,
            ):
                y += line_h
                continue
            if is_ttt_screen and self._draw_ttt_tile_row(
                line=line,
                x=x,
                y=y,
                char_w=char_w,
                line_h=line_h,
            ):
                y += line_h
                continue
            if is_ttt_screen and self._draw_ttt_separator_row(
                line=line,
                x=x,
                y=y,
                char_w=char_w,
                line_h=line_h,
            ):
                y += line_h
                continue
            text_surface = self._render_cached_line(line)
            self.screen.blit(text_surface, (x, y))
            y += line_h

        if self.graphics_level in {"medium", "high"}:
            sweep_ratio = 0.5 + (0.5 * math.sin((self.animation_phase * 0.8) + 1.4))
            sweep_y = rect.y + int(sweep_ratio * max(1, rect.height - 1))
            sweep_color = self._mix(self.accent_color, self.bg_color, 0.62)
            sweep_alpha = int((38 + (42 * self.feedback_flash)) * self.scan_strength)
            sweep_layer = pygame.Surface((rect.width - self._scale_px(10), self._scale_px(2)), pygame.SRCALPHA)
            pygame.draw.rect(
                sweep_layer,
                (sweep_color.r, sweep_color.g, sweep_color.b, max(16, sweep_alpha)),
                sweep_layer.get_rect(),
                border_radius=self._scale_px(2),
            )
            self.screen.blit(sweep_layer, (rect.x + self._scale_px(5), sweep_y))

    def _draw_rogue_tile_row(
        self,
        line: str,
        x: int,
        y: int,
        char_w: int,
        line_h: int,
    ) -> bool:
        if len(line) < 3 or not line.startswith("|") or not line.endswith("|"):
            return False

        content = line[1:-1]
        if not content:
            return False

        allowed = set("#.@gswB$!*^> ")
        for ch in content:
            if ch not in allowed:
                return False

        tile_h = max(1, line_h - 1)
        for idx, ch in enumerate(content):
            tile_surface = self._get_rogue_tile_surface(ch, char_w, tile_h)
            self.screen.blit(tile_surface, (x + (idx * char_w), y))
        return True

    def _get_rogue_tile_surface(self, symbol: str, width: int, height: int) -> pygame.Surface:
        key = (
            symbol,
            width,
            height,
            self.bg_color.r,
            self.bg_color.g,
            self.bg_color.b,
            self.fg_color.r,
            self.fg_color.g,
            self.fg_color.b,
            self.accent_color.r,
            self.accent_color.g,
            self.accent_color.b,
        )
        cached = self._rogue_tile_cache.get(key)
        if cached is not None:
            return cached

        file_tile = self._get_rogue_file_tile(symbol, width, height)
        if file_tile is not None:
            self._rogue_tile_cache[key] = file_tile
            return file_tile

        style = self._rogue_tile_style(symbol)
        surface = pygame.Surface((max(1, width), max(1, height)), pygame.SRCALPHA)
        surface.fill(style["bg"])
        pygame.draw.rect(
            surface,
            style["border"],
            surface.get_rect(),
            width=1,
            border_radius=max(2, min(width, height) // 6),
        )

        icon_key = style["icon"]
        icon_size = int(min(width, height) * 0.84)
        icon = None
        if icon_key:
            icon = self.icons.get_icon(icon_key, max(10, icon_size), style["icon_color"])

        if icon is not None:
            surface.blit(
                icon,
                (
                    (width - icon.get_width()) // 2,
                    (height - icon.get_height()) // 2,
                ),
            )
        else:
            glyph = style["glyph"]
            if glyph:
                tile_font_size = max(9, min(height - 1, int(height * 0.74)))
                font_name = pygame.font.match_font(self.font_family) or pygame.font.match_font("consolas")
                tile_font = pygame.font.Font(font_name, tile_font_size)
                glyph_surface = tile_font.render(glyph, True, style["icon_color"])
                surface.blit(
                    glyph_surface,
                    (
                        (width - glyph_surface.get_width()) // 2,
                        (height - glyph_surface.get_height()) // 2,
                    ),
                )

        self._rogue_tile_cache[key] = surface
        return surface

    def _get_rogue_file_tile(self, symbol: str, width: int, height: int) -> pygame.Surface | None:
        file_map = {
            " ": "fog.png",
            "#": "wall.png",
            ".": "floor.png",
            "@": "player.png",
            ">": "exit.png",
            "$": "gold.png",
            "!": "potion.png",
            "*": "relic.png",
            "^": "trap.png",
            "g": "enemy_g.png",
            "s": "enemy_s.png",
            "w": "enemy_w.png",
            "B": "enemy_b.png",
        }
        file_name = file_map.get(symbol, "")
        if not file_name:
            return None

        raw = self._rogue_asset_raw_cache.get(file_name)
        if raw is None:
            path = self._rogue_tiles_dir / file_name
            if not path.exists():
                return None
            try:
                loaded = pygame.image.load(str(path))
                raw = loaded.convert_alpha() if loaded.get_alpha() is not None else loaded.convert()
            except Exception:
                return None
            self._rogue_asset_raw_cache[file_name] = raw

        if raw.get_width() == width and raw.get_height() == height:
            return raw.copy()
        return pygame.transform.smoothscale(raw, (max(1, width), max(1, height)))

    def _rogue_tile_style(self, symbol: str) -> dict[str, object]:
        floor_bg = self._mix(self.bg_color, self.panel_color, 0.62)
        wall_bg = self._mix(self.bg_color, self.dim_color, 0.34)
        fog_bg = self._mix(self.bg_color, pygame.Color("#000000"), 0.48)

        base: dict[str, object] = {
            "bg": floor_bg,
            "border": self._mix(floor_bg, self.accent_color, 0.24),
            "icon": "",
            "icon_color": self.fg_color,
            "glyph": symbol,
        }

        styles: dict[str, dict[str, object]] = {
            " ": {
                "bg": fog_bg,
                "border": self._mix(fog_bg, self.bg_color, 0.28),
                "icon": "",
                "icon_color": self.dim_color,
                "glyph": "",
            },
            "#": {
                "bg": wall_bg,
                "border": self._mix(wall_bg, self.accent_color, 0.2),
                "icon": "mdi:wall",
                "icon_color": self._mix(self.fg_color, self.dim_color, 0.38),
                "glyph": "#",
            },
            ".": {
                "bg": floor_bg,
                "border": self._mix(floor_bg, self.accent_color, 0.16),
                "icon": "",
                "icon_color": self.dim_color,
                "glyph": "",
            },
            "@": {
                "bg": self._mix(self.accent_color, self.bg_color, 0.35),
                "border": self._mix(self.accent_color, self.fg_color, 0.35),
                "icon": "mdi:account",
                "icon_color": self.fg_color,
                "glyph": "@",
            },
            ">": {
                "bg": self._mix(self.accent_color, floor_bg, 0.28),
                "border": self._mix(self.accent_color, self.fg_color, 0.42),
                "icon": "mdi:stairs-up",
                "icon_color": self._mix(self.fg_color, pygame.Color("#FFFFFF"), 0.2),
                "glyph": ">",
            },
            "$": {
                "bg": self._mix(pygame.Color("#8A6A1E"), floor_bg, 0.36),
                "border": self._mix(pygame.Color("#D8AF45"), self.accent_color, 0.3),
                "icon": "mdi:cash",
                "icon_color": pygame.Color("#F7D774"),
                "glyph": "$",
            },
            "!": {
                "bg": self._mix(pygame.Color("#1E5B76"), floor_bg, 0.34),
                "border": self._mix(pygame.Color("#59C8F2"), self.accent_color, 0.3),
                "icon": "mdi:flask-round-bottom",
                "icon_color": pygame.Color("#8DDCFF"),
                "glyph": "!",
            },
            "*": {
                "bg": self._mix(pygame.Color("#4B3A73"), floor_bg, 0.34),
                "border": self._mix(pygame.Color("#D6C5FF"), self.accent_color, 0.3),
                "icon": "mdi:star-four-points",
                "icon_color": pygame.Color("#E2D4FF"),
                "glyph": "*",
            },
            "^": {
                "bg": self._mix(pygame.Color("#742727"), floor_bg, 0.34),
                "border": self._mix(pygame.Color("#F06363"), self.accent_color, 0.3),
                "icon": "mdi:alert-octagram",
                "icon_color": pygame.Color("#FF8A8A"),
                "glyph": "^",
            },
            "g": {
                "bg": self._mix(pygame.Color("#2D5D2F"), floor_bg, 0.38),
                "border": self._mix(pygame.Color("#6BC070"), self.accent_color, 0.22),
                "icon": "mdi:emoticon-devil-outline",
                "icon_color": pygame.Color("#9AE19E"),
                "glyph": "g",
            },
            "s": {
                "bg": self._mix(pygame.Color("#315E2F"), floor_bg, 0.38),
                "border": self._mix(pygame.Color("#7ED778"), self.accent_color, 0.22),
                "icon": "mdi:snake",
                "icon_color": pygame.Color("#ABF09F"),
                "glyph": "s",
            },
            "w": {
                "bg": self._mix(pygame.Color("#564039"), floor_bg, 0.38),
                "border": self._mix(pygame.Color("#D4AA88"), self.accent_color, 0.22),
                "icon": "mdi:wolf-outline",
                "icon_color": pygame.Color("#E8C6A8"),
                "glyph": "w",
            },
            "B": {
                "bg": self._mix(pygame.Color("#5E1E26"), floor_bg, 0.3),
                "border": self._mix(pygame.Color("#F16A7A"), self.accent_color, 0.28),
                "icon": "mdi:skull",
                "icon_color": pygame.Color("#FFC4CC"),
                "glyph": "B",
            },
        }
        return styles.get(symbol, base)

    def _draw_snake_tile_row(
        self,
        line: str,
        x: int,
        y: int,
        char_w: int,
        line_h: int,
    ) -> bool:
        if len(line) < 3 or not line.startswith("|") or not line.endswith("|"):
            return False

        content = line[1:-1]
        if not content:
            return False

        allowed = set("o@* ")
        if any(ch not in allowed for ch in content):
            return False

        tile_h = max(1, line_h - 1)
        for idx, ch in enumerate(content):
            tile_surface = self._get_snake_tile_surface(ch, char_w, tile_h)
            self.screen.blit(tile_surface, (x + (idx * char_w), y))
        return True

    def _get_snake_tile_surface(self, symbol: str, width: int, height: int) -> pygame.Surface:
        phase_bucket = (int(self.animation_phase * 12.0) % 8) if symbol == "*" else 0
        key = (
            symbol,
            width,
            height,
            self.bg_color.r,
            self.bg_color.g,
            self.bg_color.b,
            self.fg_color.r,
            self.fg_color.g,
            self.fg_color.b,
            self.accent_color.r,
            self.accent_color.g,
            self.accent_color.b,
            phase_bucket,
        )
        cached = self._snake_tile_cache.get(key)
        if cached is not None:
            return cached

        file_tile = self._get_snake_file_tile(symbol, width, height)
        if file_tile is not None:
            if symbol == "*":
                pulse = 0.88 + (0.12 * (0.5 + (0.5 * math.sin(self.animation_phase * 6.0))))
                tw = max(1, int(width * pulse))
                th = max(1, int(height * pulse))
                lit = pygame.transform.smoothscale(file_tile, (tw, th))
                surface = pygame.Surface((width, height), pygame.SRCALPHA)
                surface.blit(lit, ((width - tw) // 2, (height - th) // 2))
            else:
                surface = file_tile
            self._snake_tile_cache[key] = surface
            return surface

        style = self._snake_tile_style(symbol)
        surface = pygame.Surface((max(1, width), max(1, height)), pygame.SRCALPHA)
        surface.fill(style["bg"])
        pygame.draw.rect(
            surface,
            style["border"],
            surface.get_rect(),
            width=1,
            border_radius=max(2, min(width, height) // 5),
        )

        icon_key = style["icon"]
        icon_size = int(min(width, height) * 0.8)
        icon = None
        if icon_key:
            icon = self.icons.get_icon(icon_key, max(9, icon_size), style["icon_color"])
        if icon is not None:
            surface.blit(
                icon,
                (
                    (width - icon.get_width()) // 2,
                    (height - icon.get_height()) // 2,
                ),
            )
        else:
            glyph = style["glyph"]
            if glyph:
                tile_font_size = max(9, min(height - 1, int(height * 0.72)))
                font_name = pygame.font.match_font(self.font_family) or pygame.font.match_font("consolas")
                tile_font = pygame.font.Font(font_name, tile_font_size)
                glyph_surface = tile_font.render(glyph, True, style["icon_color"])
                surface.blit(
                    glyph_surface,
                    (
                        (width - glyph_surface.get_width()) // 2,
                        (height - glyph_surface.get_height()) // 2,
                    ),
                )

        self._snake_tile_cache[key] = surface
        return surface

    def _get_snake_file_tile(self, symbol: str, width: int, height: int) -> pygame.Surface | None:
        file_map = {
            " ": "floor.png",
            "o": "body.png",
            "@": "head.png",
            "*": "food.png",
        }
        file_name = file_map.get(symbol, "")
        if not file_name:
            return None

        raw = self._snake_asset_raw_cache.get(file_name)
        if raw is None:
            path = self._snake_tiles_dir / file_name
            if not path.exists():
                return None
            try:
                loaded = pygame.image.load(str(path))
                raw = loaded.convert_alpha() if loaded.get_alpha() is not None else loaded.convert()
            except Exception:
                return None
            self._snake_asset_raw_cache[file_name] = raw

        if raw.get_width() == width and raw.get_height() == height:
            return raw.copy()
        return pygame.transform.smoothscale(raw, (max(1, width), max(1, height)))

    def _snake_tile_style(self, symbol: str) -> dict[str, object]:
        floor_bg = self._mix(self.bg_color, self.panel_color, 0.6)
        base: dict[str, object] = {
            "bg": floor_bg,
            "border": self._mix(floor_bg, self.accent_color, 0.18),
            "icon": "",
            "icon_color": self.dim_color,
            "glyph": "",
        }

        styles: dict[str, dict[str, object]] = {
            " ": base,
            "o": {
                "bg": self._mix(pygame.Color("#1D5F2A"), floor_bg, 0.38),
                "border": self._mix(pygame.Color("#76D66D"), self.accent_color, 0.22),
                "icon": "",
                "icon_color": pygame.Color("#9AF58C"),
                "glyph": "o",
            },
            "@": {
                "bg": self._mix(pygame.Color("#2C7A36"), floor_bg, 0.32),
                "border": self._mix(pygame.Color("#A5FF87"), self.accent_color, 0.2),
                "icon": "mdi:snake",
                "icon_color": pygame.Color("#CAFFB5"),
                "glyph": "@",
            },
            "*": {
                "bg": self._mix(pygame.Color("#7C2D18"), floor_bg, 0.34),
                "border": self._mix(pygame.Color("#FFB169"), self.accent_color, 0.28),
                "icon": "",
                "icon_color": pygame.Color("#FFD58B"),
                "glyph": "*",
            },
        }
        return styles.get(symbol, base)

    def _draw_ttt_tile_row(
        self,
        line: str,
        x: int,
        y: int,
        char_w: int,
        line_h: int,
    ) -> bool:
        parts = line.split("|")
        if len(parts) != 3:
            return False

        cells = [part.strip() for part in parts]
        if len(cells) != 3:
            return False
        if any((len(value) != 1) for value in cells):
            return False
        if any(value not in "XO123456789" for value in cells):
            return False

        cell_w = max(char_w * 3, self._scale_px(22))
        cell_h = max(1, line_h - 1)
        sep_w = char_w
        for col, value in enumerate(cells):
            tile = self._get_ttt_cell_surface(value, cell_w, cell_h)
            cx = x + (col * (cell_w + sep_w))
            self.screen.blit(tile, (cx, y))
            if col < 2:
                sep_x = cx + cell_w + (sep_w // 2)
                sep_color = self._mix(self.accent_color, self.fg_color, 0.2)
                pygame.draw.line(
                    self.screen,
                    sep_color,
                    (sep_x, y + self._scale_px(2)),
                    (sep_x, y + cell_h - self._scale_px(2)),
                    width=max(1, self._scale_px(1)),
                )
        return True

    def _draw_ttt_separator_row(
        self,
        line: str,
        x: int,
        y: int,
        char_w: int,
        line_h: int,
    ) -> bool:
        compact = line.replace(" ", "")
        if compact != "---+---+---":
            return False

        cell_w = max(char_w * 3, self._scale_px(22))
        sep_w = char_w
        color = self._mix(self.accent_color, self.fg_color, 0.32)
        y_line = y + (line_h // 2)
        for col in range(3):
            sx = x + (col * (cell_w + sep_w))
            ex = sx + cell_w
            pygame.draw.line(self.screen, color, (sx, y_line), (ex, y_line), width=max(1, self._scale_px(1)))
        return True

    def _get_ttt_cell_surface(self, symbol: str, width: int, height: int) -> pygame.Surface:
        key = (
            symbol,
            width,
            height,
            self.bg_color.r,
            self.bg_color.g,
            self.bg_color.b,
            self.fg_color.r,
            self.fg_color.g,
            self.fg_color.b,
            self.accent_color.r,
            self.accent_color.g,
            self.accent_color.b,
        )
        cached = self._ttt_tile_cache.get(key)
        if cached is not None:
            return cached

        file_tile = self._get_ttt_file_tile(symbol, width, height)
        if file_tile is not None:
            self._ttt_tile_cache[key] = file_tile
            return file_tile

        style = self._ttt_cell_style(symbol)
        surface = pygame.Surface((max(1, width), max(1, height)), pygame.SRCALPHA)
        surface.fill(style["bg"])
        pygame.draw.rect(
            surface,
            style["border"],
            surface.get_rect(),
            width=1,
            border_radius=max(2, min(width, height) // 5),
        )

        if symbol in {"X", "O"}:
            icon = self.icons.get_icon(style["icon"], max(10, int(min(width, height) * 0.68)), style["icon_color"])
            if icon is not None:
                surface.blit(
                    icon,
                    (
                        (width - icon.get_width()) // 2,
                        (height - icon.get_height()) // 2,
                    ),
                )
            else:
                mark_font_size = max(11, min(height - 1, int(height * 0.68)))
                font_name = pygame.font.match_font(self.font_family) or pygame.font.match_font("consolas")
                mark_font = pygame.font.Font(font_name, mark_font_size)
                mark = mark_font.render(symbol, True, style["icon_color"])
                surface.blit(
                    mark,
                    (
                        (width - mark.get_width()) // 2,
                        (height - mark.get_height()) // 2,
                    ),
                )
        elif symbol.isdigit():
            num_font_size = max(10, min(height - 1, int(height * 0.58)))
            font_name = pygame.font.match_font(self.font_family) or pygame.font.match_font("consolas")
            num_font = pygame.font.Font(font_name, num_font_size)
            num_surface = num_font.render(symbol, True, style["icon_color"])
            surface.blit(
                num_surface,
                (
                    (width - num_surface.get_width()) // 2,
                    (height - num_surface.get_height()) // 2,
                ),
            )

        self._ttt_tile_cache[key] = surface
        return surface

    def _get_ttt_file_tile(self, symbol: str, width: int, height: int) -> pygame.Surface | None:
        file_map = {
            "X": "x.png",
            "O": "o.png",
        }
        file_name = file_map.get(symbol, "empty.png")

        raw = self._ttt_asset_raw_cache.get(file_name)
        if raw is None:
            path = self._ttt_tiles_dir / file_name
            if not path.exists():
                return None
            try:
                loaded = pygame.image.load(str(path))
                raw = loaded.convert_alpha() if loaded.get_alpha() is not None else loaded.convert()
            except Exception:
                return None
            self._ttt_asset_raw_cache[file_name] = raw

        if raw.get_width() == width and raw.get_height() == height:
            surface = raw.copy()
        else:
            surface = pygame.transform.smoothscale(raw, (max(1, width), max(1, height)))

        if symbol.isdigit():
            num_font_size = max(10, min(height - 1, int(height * 0.58)))
            font_name = pygame.font.match_font(self.font_family) or pygame.font.match_font("consolas")
            num_font = pygame.font.Font(font_name, num_font_size)
            num_surface = num_font.render(symbol, True, self._mix(self.dim_color, self.fg_color, 0.24))
            surface.blit(
                num_surface,
                (
                    (width - num_surface.get_width()) // 2,
                    (height - num_surface.get_height()) // 2,
                ),
            )
        return surface

    def _ttt_cell_style(self, symbol: str) -> dict[str, object]:
        floor_bg = self._mix(self.bg_color, self.panel_color, 0.6)
        base: dict[str, object] = {
            "bg": floor_bg,
            "border": self._mix(floor_bg, self.accent_color, 0.2),
            "icon": "mdi:circle-outline",
            "icon_color": self.dim_color,
        }

        styles: dict[str, dict[str, object]] = {
            "X": {
                "bg": self._mix(pygame.Color("#12253A"), floor_bg, 0.35),
                "border": self._mix(pygame.Color("#73B8FF"), self.accent_color, 0.26),
                "icon": "mdi:close-thick",
                "icon_color": pygame.Color("#AED9FF"),
            },
            "O": {
                "bg": self._mix(pygame.Color("#1A2A18"), floor_bg, 0.35),
                "border": self._mix(pygame.Color("#8AE58D"), self.accent_color, 0.22),
                "icon": "mdi:circle-outline",
                "icon_color": pygame.Color("#BEF6B5"),
            },
        }

        if symbol.isdigit():
            return {
                "bg": self._mix(floor_bg, self.bg_color, 0.2),
                "border": self._mix(self.accent_color, self.bg_color, 0.65),
                "icon": "",
                "icon_color": self._mix(self.dim_color, self.fg_color, 0.32),
            }
        return styles.get(symbol, base)

    def _draw_input(self, rect: pygame.Rect) -> None:
        prompt_pulse = 0.65 + (0.35 * (0.5 + 0.5 * math.sin((self.animation_phase * 3.4) + 0.2)))
        prompt_color = self._mix(self.accent_color, pygame.Color("#FFFFFF"), 0.2 * prompt_pulse)
        prompt_surface = self.status_font.render(self.prompt_text, True, prompt_color)
        self.screen.blit(prompt_surface, (rect.x + self._scale_px(10), rect.y + self._scale_px(12)))

        raw_text = self.input_buffer
        display_text = ("*" * len(raw_text)) if self.input_mask else raw_text

        available_w = rect.width - prompt_surface.get_width() - self._scale_px(38)
        shown_text = self._tail_to_width(display_text, available_w, self.status_font)
        text_surface = self.status_font.render(shown_text, True, self.fg_color)
        text_x = rect.x + self._scale_px(20) + prompt_surface.get_width()
        text_y = rect.y + self._scale_px(12)
        self.screen.blit(text_surface, (text_x, text_y))

        if self.input_enabled and self.cursor_visible:
            cursor_x = text_x + text_surface.get_width() + self._scale_px(2)
            cursor_h = self.status_font.get_height() - self._scale_px(3)
            cursor_color = self._mix(self.accent_color, pygame.Color("#FFFFFF"), 0.22 * prompt_pulse)
            pygame.draw.line(
                self.screen,
                cursor_color,
                (cursor_x, text_y + self._scale_px(1)),
                (cursor_x, text_y + cursor_h),
                width=max(1, self._scale_px(2)),
            )

        glow_ratio = max(self.typing_glow, self.command_flash * 0.5)
        if glow_ratio > 0.0:
            glow_color = self._mix(self.accent_color, pygame.Color("#FFFFFF"), 0.32)
            glow_alpha = int(120 * min(1.0, glow_ratio) * self.glow_strength)
            glow_surface = pygame.Surface((rect.width - self._scale_px(16), self._scale_px(4)), pygame.SRCALPHA)
            pygame.draw.rect(
                glow_surface,
                (glow_color.r, glow_color.g, glow_color.b, glow_alpha),
                glow_surface.get_rect(),
                border_radius=self._scale_px(4),
            )
            self.screen.blit(
                glow_surface,
                (rect.x + self._scale_px(8), rect.bottom - self._scale_px(8)),
            )

        if self.graphics_level != "low" and self.scan_strength > 0.25:
            line_w = rect.width - self._scale_px(16)
            base_y = rect.bottom - self._scale_px(10)
            scan_mix = 0.12 + (0.2 * (0.5 + 0.5 * math.sin(self.animation_phase * 4.1)))
            scan_color = self._mix(self.dim_color, self.accent_color, scan_mix)
            pygame.draw.line(
                self.screen,
                scan_color,
                (rect.x + self._scale_px(8), base_y),
                (rect.x + self._scale_px(8) + line_w, base_y),
                1,
            )

    def _action_buttons_panel_height(self, max_content_w: int) -> int:
        if not self.input_enabled or not self.action_buttons:
            return 0

        pad = self._scale_px(8)
        gap = self._scale_px(8)
        button_h = self._scale_px(28)
        min_button_w = self._scale_px(90)
        usable_w = max(1, max_content_w - (pad * 2))
        max_cols = max(1, min(5, (usable_w + gap) // max(1, (min_button_w + gap))))
        cols = max(1, min(max_cols, len(self.action_buttons)))
        rows = (len(self.action_buttons) + cols - 1) // cols
        return (pad * 2) + (rows * button_h) + ((rows - 1) * gap)

    def _draw_action_buttons(self, rect: pygame.Rect) -> None:
        if not self.input_enabled or not self.action_buttons:
            self._action_button_hit_areas = []
            return

        self._action_button_hit_areas = []
        layout = self._layout_action_buttons(rect)
        mouse_pos = pygame.mouse.get_pos()

        for button, button_rect in layout:
            hovered = button.enabled and button_rect.collidepoint(mouse_pos)
            enabled_mix = 0.42 if button.enabled else 0.22
            base = self._mix(self.panel_color, self.accent_color, enabled_mix)
            if hovered:
                base = self._mix(base, self.fg_color, 0.22)
            border = self._mix(self.accent_color, self.fg_color, 0.28 if button.enabled else 0.1)
            text_color = self.fg_color if button.enabled else self._mix(self.fg_color, self.bg_color, 0.55)

            pygame.draw.rect(
                self.screen,
                base,
                button_rect,
                border_radius=self._scale_px(8),
            )
            pygame.draw.rect(
                self.screen,
                border,
                button_rect,
                width=1,
                border_radius=self._scale_px(8),
            )
            if hovered:
                glow = pygame.Surface((button_rect.width, button_rect.height), pygame.SRCALPHA)
                glow_color = self._mix(self.accent_color, pygame.Color("#FFFFFF"), 0.2)
                pygame.draw.rect(
                    glow,
                    (glow_color.r, glow_color.g, glow_color.b, 52),
                    glow.get_rect(),
                    border_radius=self._scale_px(8),
                )
                self.screen.blit(glow, button_rect.topleft)

            text_limit = button_rect.width - self._scale_px(12)
            label = self._tail_to_width(button.label, text_limit, self.chip_font)
            text_surface = self.chip_font.render(label, True, text_color)
            self.screen.blit(
                text_surface,
                (
                    button_rect.x + (button_rect.width - text_surface.get_width()) // 2,
                    button_rect.y + (button_rect.height - text_surface.get_height()) // 2,
                ),
            )
            self._action_button_hit_areas.append((button_rect, button))

    def _layout_action_buttons(self, rect: pygame.Rect) -> list[tuple[ActionButton, pygame.Rect]]:
        if not self.action_buttons:
            return []

        pad = self._scale_px(8)
        gap = self._scale_px(8)
        button_h = self._scale_px(28)
        min_button_w = self._scale_px(90)
        usable_w = max(1, rect.width - (pad * 2))
        max_cols = max(1, min(5, (usable_w + gap) // max(1, (min_button_w + gap))))
        cols = max(1, min(max_cols, len(self.action_buttons)))
        button_w = max(
            min_button_w,
            (usable_w - ((cols - 1) * gap)) // cols,
        )

        layout: list[tuple[ActionButton, pygame.Rect]] = []
        max_rows = max(1, (max(1, rect.height - (pad * 2) + gap)) // max(1, (button_h + gap)))
        total = min(len(self.action_buttons), max_rows * cols)
        rows = (total + cols - 1) // cols
        y = rect.y + pad

        for row in range(rows):
            row_start = row * cols
            row_end = min(total, row_start + cols)
            row_items = self.action_buttons[row_start:row_end]
            items_count = len(row_items)
            row_w = (items_count * button_w) + ((items_count - 1) * gap)
            x = rect.x + ((rect.width - row_w) // 2)

            for idx, button in enumerate(row_items):
                button_rect = pygame.Rect(
                    x + (idx * (button_w + gap)),
                    y,
                    button_w,
                    button_h,
                )
                layout.append((button, button_rect))
            y += button_h + gap

        return layout

    def _draw_error_overlay(self) -> None:
        if self.error_overlay_timer <= 0.0:
            return

        decay = min(1.0, self.error_overlay_timer / 0.72)
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        alert = pygame.Color("#FF5F6F")
        accent = self._mix(alert, self.accent_color, 0.32)

        bars = 3 if self.graphics_level == "medium" else 5
        for _ in range(bars):
            h = random.randint(max(2, self._scale_px(3)), max(4, self._scale_px(10)))
            y = random.randint(0, max(0, self.height - h))
            a = int((24 + random.randint(0, 26)) * decay)
            pygame.draw.rect(overlay, (accent.r, accent.g, accent.b, a), pygame.Rect(0, y, self.width, h))

        glitch_w = max(self._scale_px(120), int(self.width * 0.24))
        glitch_h = self._scale_px(28)
        gx = random.randint(0, max(0, self.width - glitch_w))
        gy = random.randint(self._scale_px(24), max(self._scale_px(25), self.height - glitch_h - self._scale_px(18)))
        pygame.draw.rect(
            overlay,
            (alert.r, alert.g, alert.b, int(72 * decay)),
            pygame.Rect(gx, gy, glitch_w, glitch_h),
            border_radius=self._scale_px(4),
        )

        if self.error_overlay_text:
            text = self._tail_to_width(self.error_overlay_text, glitch_w - self._scale_px(10), self.chip_font)
            text_surface = self.chip_font.render(text, True, pygame.Color("#FFE9EC"))
            overlay.blit(
                text_surface,
                (
                    gx + self._scale_px(6),
                    gy + (glitch_h - text_surface.get_height()) // 2,
                ),
            )

        vignette_alpha = int(38 * decay)
        pygame.draw.rect(
            overlay,
            (alert.r, alert.g, alert.b, vignette_alpha),
            overlay.get_rect(),
            width=max(1, self._scale_px(2)),
        )
        self.screen.blit(overlay, (0, 0))

    def _draw_status(self, rect: pygame.Rect) -> None:
        pulse = 0.4 + (0.6 * (0.5 + 0.5 * math.sin((self.animation_phase * 2.2) + 1.1)))
        ratio = min(1.0, self.status_flash + (self.feedback_flash * 0.55))
        status_color = self._mix(self.dim_color, self.accent_color, (0.08 * pulse) + (0.42 * ratio))
        status_surface = self.status_font.render(self.status_text, True, status_color)
        self.screen.blit(status_surface, (rect.x + self._scale_px(10), rect.y + self._scale_px(6)))

        if self.graphics_level != "low":
            dot_count = 3
            dot_gap = self._scale_px(8)
            start_x = rect.right - self._scale_px(14) - ((dot_count - 1) * dot_gap)
            cy = rect.y + (rect.height // 2)
            for idx in range(dot_count):
                phase = (self.animation_phase * 4.8) + (idx * 0.42)
                glow = 0.25 + (0.75 * (0.5 + 0.5 * math.sin(phase)))
                radius = 1 + int(glow > 0.72)
                dot_alpha = int((70 + (110 * glow * max(0.25, ratio))) * self.glow_strength)
                dot_color = self._mix(self.accent_color, self.fg_color, 0.3 + (0.25 * glow))
                layer = pygame.Surface((radius * 4, radius * 4), pygame.SRCALPHA)
                pygame.draw.circle(
                    layer,
                    (dot_color.r, dot_color.g, dot_color.b, max(28, dot_alpha)),
                    (radius * 2, radius * 2),
                    radius,
                )
                self.screen.blit(layer, (start_x + (idx * dot_gap), cy - (radius * 2)))

    def _apply_panel_entry_animation(
        self,
        header_rect: pygame.Rect,
        output_rect: pygame.Rect,
        input_rect: pygame.Rect,
        status_rect: pygame.Rect,
    ) -> None:
        if self.session_elapsed >= self.panel_intro_duration:
            return

        progress = self._ease_out_cubic(self.session_elapsed / max(0.01, self.panel_intro_duration))
        remaining = 1.0 - progress
        max_offset = self._scale_px(28)

        header_rect.y -= int(max_offset * remaining)
        output_rect.y += int((max_offset * 0.35) * remaining)
        input_rect.y += int((max_offset * 0.7) * remaining)
        status_rect.y += int(max_offset * remaining)

    def _draw_intro(self) -> None:
        base = pygame.Color("#030508")
        glow = self._mix(
            self.accent_color,
            pygame.Color("#FFFFFF"),
            min(0.5, 0.22 + (0.08 * self.glow_strength)),
        )

        self.screen.fill(base)

        top = self._mix(base, self.accent_color, min(0.2, 0.08 + (0.06 * self.scan_strength)))
        line_step = 2 if self.graphics_level == "low" else 1
        for y in range(0, self.height, line_step):
            t = y / max(1, self.height - 1)
            pulse = 0.35 + 0.25 * (0.5 + 0.5 * math.sin((self.animation_phase * 1.4) + (t * 4.2)))
            color = self._mix(base, top, (0.12 * (1.0 - t)) + (0.08 * pulse))
            pygame.draw.line(self.screen, color, (0, y), (self.width, y), width=line_step)

        center_x = self.width // 2
        center_y = int(self.height * 0.44)
        elapsed = self.intro_elapsed
        duration = max(0.1, self.intro_duration)
        progress = max(0.0, min(1.0, elapsed / (duration * 0.82)))

        fade_in = max(0.0, min(1.0, elapsed / 0.5))
        fade_out_start = max(0.0, duration - 0.45)
        if elapsed >= fade_out_start:
            fade = max(0.0, 1.0 - ((elapsed - fade_out_start) / max(0.01, duration - fade_out_start)))
        else:
            fade = 1.0
        alpha_ratio = min(fade_in, fade)

        halo_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        base_rings = {"low": 5, "medium": 8, "high": 11}.get(self.graphics_level, 8)
        halo_rings = max(3, int(round(base_rings * (0.65 + (0.35 * self.glow_strength)))))
        for idx in range(halo_rings):
            radius = int(self._scale_px(62) + (idx * self._scale_px(23)))
            a = int((18 - idx * 2) * alpha_ratio)
            if a <= 0:
                continue
            pygame.draw.circle(
                halo_surface,
                (glow.r, glow.g, glow.b, a),
                (center_x, center_y),
                radius,
            )
        self.screen.blit(halo_surface, (0, 0))

        logo_radius = self._scale_px(48)
        pygame.draw.circle(self.screen, self._mix(base, self.accent_color, 0.55), (center_x, center_y), logo_radius)
        pygame.draw.circle(self.screen, self._mix(base, self.accent_color, 0.22), (center_x, center_y), logo_radius - self._scale_px(3))
        power_icon = self.icons.get_icon("mdi:power", self._scale_px(46), self._mix(glow, pygame.Color("#FFFFFF"), 0.2))
        if power_icon is not None:
            icon_copy = power_icon.copy()
            icon_copy.set_alpha(int(245 * alpha_ratio))
            self.screen.blit(
                icon_copy,
                (
                    center_x - (icon_copy.get_width() // 2),
                    center_y - (icon_copy.get_height() // 2),
                ),
            )

        brand_text = self.brand_font.render(self.intro_title, True, self._mix(self.fg_color, pygame.Color("#FFFFFF"), 0.12))
        brand_alpha = int(255 * alpha_ratio)
        brand_text.set_alpha(brand_alpha)
        self.screen.blit(
            brand_text,
            (
                center_x - (brand_text.get_width() // 2),
                center_y + self._scale_px(86),
            ),
        )

        subtitle = self.brand_sub_font.render("booting", True, self.dim_color)
        subtitle.set_alpha(int(220 * alpha_ratio))
        self.screen.blit(
            subtitle,
            (
                center_x - (subtitle.get_width() // 2),
                center_y + self._scale_px(136),
            ),
        )

        bar_w = max(self._scale_px(260), int(self.width * 0.28))
        bar_h = self._scale_px(8)
        bar_rect = pygame.Rect(
            center_x - (bar_w // 2),
            center_y + self._scale_px(168),
            bar_w,
            bar_h,
        )
        pygame.draw.rect(self.screen, self._mix(base, self.fg_color, 0.12), bar_rect, border_radius=self._scale_px(8))
        fill_w = max(1, int(bar_rect.width * progress))
        fill_rect = pygame.Rect(bar_rect.x, bar_rect.y, fill_w, bar_rect.height)
        pygame.draw.rect(self.screen, glow, fill_rect, border_radius=self._scale_px(8))
        pygame.draw.rect(self.screen, self._mix(glow, pygame.Color("#FFFFFF"), 0.18), bar_rect, width=1, border_radius=self._scale_px(8))
        if fill_w > self._scale_px(12):
            sheen_w = self._scale_px(26)
            sweep = int((self.animation_phase * self._scale_px(170)) % max(1, fill_rect.width + sheen_w))
            sheen_rect = pygame.Rect(fill_rect.x + sweep - sheen_w, fill_rect.y, sheen_w, fill_rect.height)
            clipped = sheen_rect.clip(fill_rect)
            if clipped.width > 0 and clipped.height > 0:
                sheen = pygame.Surface((clipped.width, clipped.height), pygame.SRCALPHA)
                sheen_color = self._mix(glow, pygame.Color("#FFFFFF"), 0.45)
                pygame.draw.rect(
                    sheen,
                    (sheen_color.r, sheen_color.g, sheen_color.b, 88),
                    sheen.get_rect(),
                    border_radius=self._scale_px(6),
                )
                self.screen.blit(sheen, clipped.topleft)

    def _draw_notifications(self) -> None:
        if not self.notifications:
            return

        margin = self._scale_px(14)
        container = self._layout_rect if self._layout_rect.width > 0 else pygame.Rect(0, 0, self.width, self.height)
        width = min(self._scale_px(430), int(container.width * 0.45))
        width = max(self._scale_px(260), width)
        y = margin + self._scale_px(4)
        spacing = self._scale_px(8)
        title_color = self._mix(self.fg_color, pygame.Color("#FFFFFF"), 0.2)

        for idx, toast in enumerate(reversed(self.notifications)):
            alpha, offset = self._toast_animation(toast)
            if alpha <= 0:
                continue

            title_surface = self.status_font.render(toast.title, True, title_color)
            message_surface = None
            if toast.message:
                message_surface = self.chip_font.render(toast.message, True, self.fg_color)
            icon_surface = self.icons.get_icon(toast.icon_key, self._scale_px(18), self.accent_color)
            icon_slot_w = self._scale_px(22) if icon_surface is not None else 0

            inner_pad = self._scale_px(10)
            height = inner_pad + title_surface.get_height() + inner_pad
            if message_surface is not None:
                height += message_surface.get_height() + self._scale_px(4)

            right_edge = container.right - margin
            x = right_edge - width + offset
            card = pygame.Surface((width, height), pygame.SRCALPHA)

            panel_rgba = (self.panel_color.r, self.panel_color.g, self.panel_color.b, int(alpha * 0.9))
            border_rgba = (self.accent_color.r, self.accent_color.g, self.accent_color.b, alpha)
            pygame.draw.rect(card, panel_rgba, card.get_rect(), border_radius=self._scale_px(9))
            pygame.draw.rect(
                card,
                border_rgba,
                card.get_rect(),
                width=1,
                border_radius=self._scale_px(9),
            )

            ty = inner_pad
            text_x = inner_pad + icon_slot_w
            if icon_surface is not None:
                icon_y = inner_pad + max(0, (title_surface.get_height() - icon_surface.get_height()) // 2)
                card.blit(icon_surface, (inner_pad, icon_y))
            card.blit(title_surface, (text_x, ty))
            if message_surface is not None:
                ty += title_surface.get_height() + self._scale_px(4)
                card.blit(message_surface, (text_x, ty))

            remaining_ratio = max(0.0, min(1.0, (toast.lifetime - toast.age) / max(0.01, toast.lifetime)))
            progress_w = max(0, int((width - (inner_pad * 2)) * remaining_ratio))
            if progress_w > 0:
                bar_rect = pygame.Rect(inner_pad, height - self._scale_px(4), progress_w, self._scale_px(2))
                bar_color = self._mix(self.accent_color, pygame.Color("#FFFFFF"), 0.1)
                pygame.draw.rect(
                    card,
                    (bar_color.r, bar_color.g, bar_color.b, int(alpha * 0.9)),
                    bar_rect,
                    border_radius=self._scale_px(2),
                )

            bobbing = int(math.sin((self.animation_phase * 3.2) + (idx * 0.9)) * self._scale_px(1))
            self.screen.blit(card, (x, y + bobbing))
            y += height + spacing

    def _toast_animation(self, toast: ToastNotification) -> tuple[int, int]:
        fade_in = 0.22
        fade_out = 0.35
        alpha = 255
        offset = 0

        if toast.age < fade_in:
            ratio = max(0.0, min(1.0, toast.age / fade_in))
            alpha = int(255 * ratio)
            eased = self._ease_out_back(ratio)
            offset = int((1.0 - eased) * self._scale_px(46))
            return alpha, offset

        remaining = toast.lifetime - toast.age
        if remaining < fade_out:
            ratio = max(0.0, min(1.0, remaining / fade_out))
            alpha = int(255 * ratio)
            offset = int((1.0 - ratio) * self._scale_px(46))
            return alpha, offset

        return alpha, offset

    def _render_cached_line(self, line: str) -> pygame.Surface:
        cached = self._line_surface_cache.get(line)
        if cached is not None:
            return cached

        rendered = self.text_font.render(line, True, self.fg_color)
        self._line_surface_cache[line] = rendered
        if len(self._line_surface_cache) > self._line_surface_cache_limit:
            oldest_key = next(iter(self._line_surface_cache))
            del self._line_surface_cache[oldest_key]
        return rendered

    @staticmethod
    def _tail_to_width(text: str, width: int, font: pygame.font.Font) -> str:
        if font.size(text)[0] <= width:
            return text
        for idx in range(len(text)):
            candidate = text[idx:]
            if font.size(candidate)[0] <= width:
                return candidate
        return ""

    @staticmethod
    def _wrap_lines(lines: list[str], max_chars: int) -> list[str]:
        wrapped: list[str] = []
        for line in lines:
            if not line:
                wrapped.append("")
                continue
            chunks = textwrap.wrap(
                line,
                width=max_chars,
                replace_whitespace=False,
                drop_whitespace=False,
                break_long_words=True,
            )
            wrapped.extend(chunks or [""])
        return wrapped

    @staticmethod
    def _mix(c1: pygame.Color, c2: pygame.Color, ratio: float) -> pygame.Color:
        r = max(0.0, min(1.0, ratio))
        nr = int((c1.r * (1.0 - r)) + (c2.r * r))
        ng = int((c1.g * (1.0 - r)) + (c2.g * r))
        nb = int((c1.b * (1.0 - r)) + (c2.b * r))
        return pygame.Color(nr, ng, nb)

    @staticmethod
    def _normalize_theme_style(raw_style: object) -> str:
        if not isinstance(raw_style, str):
            return "terminal"
        token = raw_style.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "splitv": "split_v",
            "split_vertical": "split_v",
            "splith": "split_h",
            "split_horizontal": "split_h",
            "diag": "diagonal",
        }
        normalized = aliases.get(token, token)
        if normalized not in THEME_VISUAL_STYLES:
            return "terminal"
        return normalized

    @staticmethod
    def _contrast_text(color: pygame.Color) -> pygame.Color:
        luma = (0.299 * color.r) + (0.587 * color.g) + (0.114 * color.b)
        if luma >= 140:
            return pygame.Color("#0A0E14")
        return pygame.Color("#F2F7FF")

    @staticmethod
    def _derive_accent(color: pygame.Color) -> pygame.Color:
        nr = min(255, int(color.r * 0.7) + 35)
        ng = min(255, int(color.g * 0.7) + 45)
        nb = min(255, int(color.b * 0.7) + 25)
        return pygame.Color(nr, ng, nb)

    @staticmethod
    def _derive_secondary(base: pygame.Color, accent: pygame.Color) -> pygame.Color:
        return ConsoleUI._mix(base, accent, 0.18)

    @staticmethod
    def _ease_out_cubic(value: float) -> float:
        t = max(0.0, min(1.0, value))
        if pytweening is not None:
            try:
                return float(pytweening.easeOutCubic(t))
            except Exception:
                pass
        return 1.0 - ((1.0 - t) ** 3)

    @staticmethod
    def _ease_out_back(value: float) -> float:
        t = max(0.0, min(1.0, value))
        if pytweening is not None:
            try:
                return float(pytweening.easeOutBack(t))
            except Exception:
                pass
        c1 = 1.70158
        c3 = c1 + 1.0
        return 1.0 + (c3 * ((t - 1.0) ** 3)) + (c1 * ((t - 1.0) ** 2))
