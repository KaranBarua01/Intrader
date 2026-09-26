"""Stable desktop filesystem locations for development and packaged builds."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def app_data_root() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        root = base / "Intrader"
    else:
        root = Path.cwd()
    root.mkdir(parents=True, exist_ok=True)
    return root


def database_path() -> Path:
    path = app_data_root() / "data" / "intrader.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def export_root() -> Path:
    path = app_data_root() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path
