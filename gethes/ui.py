from __future__ import annotations

import math
import random
import textwrap
from dataclasses import dataclass
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


@dataclass
class ToastNotification:
    title: str
    message: str
    lifetime: float
    age: float = 0.0
    icon_key: str = "mdi:information-outline"


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
        self.icons = IconPack()
        self.icons.preload(
            [
                "mdi:terminal",
                "mdi:power",
                "mdi:trophy-outline",
                "mdi:information-outline",
            ]
        )

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
        self.intro_active = False
        self.intro_elapsed = 0.0
        self.intro_duration = 2.6
        self.intro_title = "Gethes"
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

            self._update_notifications(dt)

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

        if raw.strip():
            self.history.append(raw)
            self.history_index = len(self.history)
            if self.echo_commands:
                self.write(f"{self.prompt_text} {raw}")

        self.command_handler(raw)
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

        self.accent_color = self._derive_accent(self.fg_color)
        self.panel_color = self._mix(self.bg_color, self.accent_color, 0.13)
        self.dim_color = self._mix(self.fg_color, self.bg_color, 0.45)
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

    def set_status(self, value: str) -> None:
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
            self.graphics_level,
            int(round(self.effective_ui_scale * 100)),
        )
        if self._bg_cache_surface is not None and self._bg_cache_key == key:
            return

        surface = pygame.Surface((self.width, self.height))
        base = self.bg_color
        top = self._mix(base, self.accent_color, 0.06)
        line_step = 2 if self.graphics_level == "low" else 1
        for y in range(0, self.height, line_step):
            t = y / max(1, self.height - 1)
            blend = (0.1 * (1.0 - t)) + (0.04 * (0.5 + 0.5 * math.sin(t * 5.0)))
            color = self._mix(base, top, blend)
            pygame.draw.line(surface, color, (0, y), (self.width, y), width=line_step)

        scan = self._mix(self.bg_color, self.fg_color, 0.04)
        if self.graphics_level == "low":
            step = max(6, self._scale_px(8))
        elif self.graphics_level == "high":
            step = max(2, self._scale_px(3))
        else:
            step = max(3, self._scale_px(4))
        for y in range(0, self.height, step):
            pygame.draw.line(surface, scan, (0, y), (self.width, y))

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

        self._bg_cache_surface = surface.convert()
        self._bg_cache_key = key

    def _update_notifications(self, dt: float) -> None:
        if not self.notifications:
            return

        kept: list[ToastNotification] = []
        for toast in self.notifications:
            toast.age += dt
            if toast.age < toast.lifetime:
                kept.append(toast)
        self.notifications = kept

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

        margin = self._scale_px(14)
        header_h = self._scale_px(52)
        status_h = self._scale_px(30)
        input_h = self._scale_px(46)
        gap = self._scale_px(10)

        header_rect = pygame.Rect(margin, margin, self.width - (margin * 2), header_h)
        status_rect = pygame.Rect(
            margin,
            self.height - margin - status_h,
            self.width - (margin * 2),
            status_h,
        )
        input_rect = pygame.Rect(
            margin,
            status_rect.top - gap - input_h,
            self.width - (margin * 2),
            input_h,
        )
        output_rect = pygame.Rect(
            margin,
            header_rect.bottom + gap,
            self.width - (margin * 2),
            input_rect.top - header_rect.bottom - (gap * 2),
        )
        self._apply_panel_entry_animation(header_rect, output_rect, input_rect, status_rect)

        self._draw_panel(output_rect)
        self._draw_panel(input_rect)
        self._draw_panel(header_rect)
        self._draw_panel(status_rect)

        self._draw_header(header_rect)
        self._draw_output(output_rect)
        self._draw_input(input_rect)
        self._draw_status(status_rect)
        self._draw_notifications()

    def _draw_background(self) -> None:
        self._rebuild_background_cache()
        if self._bg_cache_surface is not None:
            self.screen.blit(self._bg_cache_surface, (0, 0))

        glow = self._mix(self.accent_color, self.bg_color, 0.58)
        y1 = int((0.5 + 0.5 * math.sin(self.animation_phase * 0.7)) * max(1, self.height - 1))
        pygame.draw.line(self.screen, glow, (0, y1), (self.width, y1), 1)
        if self.graphics_level in {"medium", "high"}:
            y2 = int((0.5 + 0.5 * math.sin((self.animation_phase * 0.9) + 1.3)) * max(1, self.height - 1))
            pygame.draw.line(self.screen, self._mix(glow, self.bg_color, 0.4), (0, y2), (self.width, y2), 1)
        if self.graphics_level == "high":
            y3 = int((0.5 + 0.5 * math.sin((self.animation_phase * 1.25) + 0.4)) * max(1, self.height - 1))
            pygame.draw.line(self.screen, self._mix(glow, self.bg_color, 0.58), (0, y3), (self.width, y3), 1)

        if self.graphics_level in {"medium", "high"}:
            particle_count = 10 if self.graphics_level == "medium" else 18
            particle_color = self._mix(self.accent_color, self.fg_color, 0.25)
            for idx in range(particle_count):
                travel_x = (idx * 131.0) + (self.animation_phase * (22.0 + (idx % 4) * 6.0))
                travel_y = (idx * 79.0) + (self.animation_phase * (17.0 + (idx % 3) * 5.0))
                wobble = math.sin((self.animation_phase * 0.9) + (idx * 0.67)) * 22.0
                px = int(travel_x % max(1, self.width))
                py = int((travel_y + wobble) % max(1, self.height))
                radius = 1 if (idx % 5) else 2
                alpha = 35 if radius == 1 else 52
                layer = pygame.Surface((radius * 4, radius * 4), pygame.SRCALPHA)
                pygame.draw.circle(
                    layer,
                    (particle_color.r, particle_color.g, particle_color.b, alpha),
                    (radius * 2, radius * 2),
                    radius,
                )
                self.screen.blit(layer, (px - (radius * 2), py - (radius * 2)))

    def _draw_panel(self, rect: pygame.Rect) -> None:
        radius = self._scale_px(9)
        shadow = pygame.Rect(rect.x, rect.y + self._scale_px(2), rect.width, rect.height)
        pygame.draw.rect(
            self.screen,
            self._mix(self.bg_color, pygame.Color("#000000"), 0.45),
            shadow,
            border_radius=radius,
        )
        pygame.draw.rect(self.screen, self.panel_color, rect, border_radius=radius)
        pygame.draw.rect(self.screen, self.accent_color, rect, width=1, border_radius=radius)
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

        chip_surface = self.chip_font.render(self.mode_chip_text, True, self.bg_color)
        chip_padding_x = self._scale_px(14)
        chip_w = chip_surface.get_width() + (chip_padding_x * 2)
        chip_h = rect.height - self._scale_px(14)
        chip_rect = pygame.Rect(rect.right - chip_w - self._scale_px(10), rect.y + self._scale_px(7), chip_w, chip_h)
        pygame.draw.rect(self.screen, self.accent_color, chip_rect, border_radius=self._scale_px(8))
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

        y = rect.y + self._scale_px(8) + offset_y
        for line in visible:
            text_surface = self._render_cached_line(line)
            self.screen.blit(text_surface, (rect.x + self._scale_px(10) + offset_x, y))
            y += line_h

    def _draw_input(self, rect: pygame.Rect) -> None:
        prompt_surface = self.status_font.render(self.prompt_text, True, self.accent_color)
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
            pygame.draw.line(
                self.screen,
                self.accent_color,
                (cursor_x, text_y + self._scale_px(1)),
                (cursor_x, text_y + cursor_h),
                width=max(1, self._scale_px(2)),
            )

        glow_ratio = max(self.typing_glow, self.command_flash * 0.5)
        if glow_ratio > 0.0:
            glow_color = self._mix(self.accent_color, pygame.Color("#FFFFFF"), 0.32)
            glow_alpha = int(120 * min(1.0, glow_ratio))
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

    def _draw_status(self, rect: pygame.Rect) -> None:
        status_surface = self.status_font.render(self.status_text, True, self.dim_color)
        self.screen.blit(status_surface, (rect.x + self._scale_px(10), rect.y + self._scale_px(6)))

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
        glow = self._mix(self.accent_color, pygame.Color("#FFFFFF"), 0.28)

        self.screen.fill(base)

        top = self._mix(base, self.accent_color, 0.1)
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
        halo_rings = {"low": 5, "medium": 8, "high": 11}.get(self.graphics_level, 8)
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
        width = min(self._scale_px(430), int(self.width * 0.43))
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

            x = self.width - width - margin + offset
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
    def _derive_accent(color: pygame.Color) -> pygame.Color:
        nr = min(255, int(color.r * 0.7) + 35)
        ng = min(255, int(color.g * 0.7) + 45)
        nb = min(255, int(color.b * 0.7) + 25)
        return pygame.Color(nr, ng, nb)

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
