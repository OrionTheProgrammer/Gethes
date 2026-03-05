from __future__ import annotations

import os
from pathlib import Path
import sys


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_package_dir() -> Path:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")) / "gethes"
    return Path(__file__).resolve().parent


def user_data_dir(app_name: str = "Gethes") -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        base = Path(appdata)
    else:
        base = Path.home() / ".gethes"
    path = base / app_name
    path.mkdir(parents=True, exist_ok=True)
    return path
