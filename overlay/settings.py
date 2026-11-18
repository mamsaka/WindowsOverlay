"""Tiny KEY=VALUE persistence for snow and leaf settings.

Functional settings (click-through) are deliberately not stored: they always
start at their defaults.  The file lives next to the project, not inside the
package, and is ignored by git.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _base_dir() -> Path:
    """Directory that holds settings.env.

    In a PyInstaller build ``__file__`` points inside the temporary unpack
    directory, so settings stored there would be lost on exit; keep them next
    to the executable instead.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


SETTINGS_PATH = _base_dir() / "settings.env"


def load() -> dict[str, str]:
    try:
        text = SETTINGS_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def save(values: dict[str, object]) -> None:
    lines = ["# Overlay settings (auto-saved; functional settings are not stored)"]
    for key in sorted(values):
        lines.append(f"{key}={values[key]}")
    try:
        SETTINGS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
