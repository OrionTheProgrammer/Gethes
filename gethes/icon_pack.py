from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
from typing import TYPE_CHECKING

import pygame
from pygame import BLEND_RGBA_MULT

from gethes.runtime_paths import resource_package_dir, user_data_dir

try:
    import pyconify
except Exception:  # pragma: no cover - fallback runtime
    pyconify = None


@dataclass(frozen=True)
class IconRequest:
    key: str
    size: int
    color_hex: str


class IconPack:
    def __init__(self) -> None:
        self.enabled = hasattr(pygame.image, "load_sized_svg")
        package_dir = resource_package_dir()
        self.local_icons_dir = package_dir / "assets" / "icons"
        self.user_cache_dir = user_data_dir() / "icon_cache"
        self.user_cache_dir.mkdir(parents=True, exist_ok=True)

        self._svg_cache: dict[str, bytes] = {}
        self._surface_cache: dict[IconRequest, pygame.Surface] = {}

    def clear_scaled_cache(self) -> None:
        self._surface_cache = {}

    def preload(self, icon_keys: list[str]) -> None:
        if not self.enabled:
            return
        for icon_key in icon_keys:
            self._get_svg_bytes(icon_key)

    def get_icon(
        self,
        icon_key: str,
        size: int,
        color: "pygame.Color",
    ) -> pygame.Surface | None:
        if not self.enabled:
            return None

        icon_size = max(10, int(size))
        req = IconRequest(
            key=icon_key,
            size=icon_size,
            color_hex=self._to_hex(color),
        )
        cached_surface = self._surface_cache.get(req)
        if cached_surface is not None:
            return cached_surface

        svg_bytes = self._get_svg_bytes(req.key)
        if svg_bytes is None:
            return None

        try:
            surface = pygame.image.load_sized_svg(io.BytesIO(svg_bytes), (req.size, req.size))
        except Exception:
            return None

        if surface.get_alpha() is not None:
            surface = surface.convert_alpha()
        else:
            surface = surface.convert()

        tinted = self._tint_surface(surface, color)
        self._surface_cache[req] = tinted
        return tinted

    def _get_svg_bytes(self, icon_key: str) -> bytes | None:
        cached = self._svg_cache.get(icon_key)
        if cached is not None:
            return cached

        safe_name = self._safe_icon_name(icon_key)
        local_path = self.local_icons_dir / f"{safe_name}.svg"
        if local_path.exists():
            try:
                payload = local_path.read_bytes()
                self._svg_cache[icon_key] = payload
                return payload
            except OSError:
                pass

        cache_path = self.user_cache_dir / f"{safe_name}.svg"
        if cache_path.exists():
            try:
                payload = cache_path.read_bytes()
                self._svg_cache[icon_key] = payload
                return payload
            except OSError:
                pass

        if pyconify is None:
            return None

        try:
            payload = pyconify.svg(icon_key, color="#FFFFFF", box=True)
        except Exception:
            return None

        try:
            cache_path.write_bytes(payload)
        except OSError:
            pass

        self._svg_cache[icon_key] = payload
        return payload

    @staticmethod
    def _to_hex(color: "pygame.Color") -> str:
        return f"#{color.r:02X}{color.g:02X}{color.b:02X}"

    @staticmethod
    def _safe_icon_name(icon_key: str) -> str:
        return icon_key.strip().replace(":", "__").replace("/", "_").replace(" ", "_")

    @staticmethod
    def _tint_surface(surface: pygame.Surface, color: "pygame.Color") -> pygame.Surface:
        if color.r == 255 and color.g == 255 and color.b == 255:
            return surface

        tinted = surface.copy()
        tint_layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        tint_layer.fill((color.r, color.g, color.b, 255))
        tinted.blit(tint_layer, (0, 0), special_flags=BLEND_RGBA_MULT)
        return tinted


if TYPE_CHECKING:
    pass
