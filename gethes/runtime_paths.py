from __future__ import annotations

import os
from pathlib import Path
import sys

try:
    from platformdirs import user_data_dir as _platform_user_data_dir
except ImportError:  # pragma: no cover - optional dependency fallback
    _platform_user_data_dir = None


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_package_dir() -> Path:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")) / "gethes"
    return Path(__file__).resolve().parent


def user_data_dir(app_name: str = "Gethes") -> Path:
    normalized_name = app_name.strip() or "Gethes"

    if _platform_user_data_dir is not None:
        platform_path = _platform_user_data_dir(
            appname=normalized_name,
            appauthor=False,
            roaming=True,
        )
        path = Path(platform_path)
    else:
        appdata = os.getenv("APPDATA")
        if appdata:
            base = Path(appdata)
        else:
            base = Path.home() / ".gethes"
        path = base / normalized_name

    path.mkdir(parents=True, exist_ok=True)
    return path
