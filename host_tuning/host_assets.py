"""Swap Sunshine/Apollo Desktop and Steam Big Picture tile PNGs (reversible)."""

from __future__ import annotations

import logging
import os
import shutil
from typing import Optional, Tuple


def find_assets_dir(sunshine_apps_json: str = "") -> Optional[str]:
    candidates = []
    if sunshine_apps_json:
        cfg_dir = os.path.dirname(os.path.abspath(sunshine_apps_json))
        candidates.append(os.path.join(os.path.dirname(cfg_dir), "assets"))
        candidates.append(os.path.join(cfg_dir, "assets"))
    for env_key in ("SUNSHINE_EXE_PATH", "APOLLO_EXE_PATH"):
        exe = os.environ.get(env_key, "")
        if exe and os.path.isfile(exe):
            candidates.append(os.path.join(os.path.dirname(exe), "assets"))
    if os.name == "nt":
        for root in (
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Sunshine", "assets"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Sunshine", "assets"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Apollo", "assets"),
        ):
            candidates.append(root)
    else:
        home = os.path.expanduser("~")
        candidates.extend([
            os.path.join(home, ".config", "sunshine", "assets"),
            os.path.join(home, ".var", "app", "dev.lizardbyte.app.Sunshine", "config", "sunshine", "assets"),
            os.path.join(home, ".local", "share", "sunshine", "assets"),
        ])
    for path in candidates:
        if path and os.path.isdir(path):
            return os.path.normpath(path)
    return None


def is_applied(assets_dir: str) -> bool:
    if not assets_dir:
        return False
    return (
        os.path.isfile(os.path.join(assets_dir, "desktop_backup.png"))
        or os.path.isfile(os.path.join(assets_dir, "steam_backup.png"))
    )


def swap_tiles(assets_dir: str, desktop_source: str, steam_source: str) -> Tuple[bool, str]:
    if not assets_dir or not os.path.isdir(assets_dir):
        return False, "assets directory not found"
    if not os.path.isfile(desktop_source) or not os.path.isfile(steam_source):
        return False, "source tile PNGs must exist"
    try:
        _backup_and_copy(assets_dir, desktop_source, "desktop.png")
        _backup_and_copy(assets_dir, steam_source, "steam.png")
        return True, f"swapped tiles in {assets_dir}"
    except OSError as exc:
        return False, str(exc)


def restore_tiles(assets_dir: str) -> Tuple[bool, str]:
    if not assets_dir or not os.path.isdir(assets_dir):
        return False, "assets directory not found"
    try:
        _restore_one(assets_dir, "desktop.png")
        _restore_one(assets_dir, "steam.png")
        return True, "restored stock host tiles"
    except OSError as exc:
        return False, str(exc)


def ensure_default_tiles(config_dir: str) -> Tuple[str, str]:
    """Create simple branded placeholder tiles if user has not configured custom paths."""
    from PIL import Image, ImageDraw

    os.makedirs(config_dir, exist_ok=True)
    desktop = os.path.join(config_dir, "gamesphere_desktop.png")
    steam = os.path.join(config_dir, "gamesphere_steam.png")
    for path, label, color in (
        (desktop, "Desktop", (30, 30, 40)),
        (steam, "Steam", (27, 40, 56)),
    ):
        if os.path.isfile(path):
            continue
        img = Image.new("RGB", (600, 900), color)
        draw = ImageDraw.Draw(img)
        draw.text((40, 420), f"GameSphere\n{label}", fill=(220, 220, 230))
        img.save(path, "PNG")
    return desktop, steam


def _backup_and_copy(assets_dir: str, source: str, tile_name: str) -> None:
    original = os.path.join(assets_dir, tile_name)
    backup = os.path.join(assets_dir, tile_name.replace(".png", "_backup.png"))
    if os.path.isfile(original) and not os.path.isfile(backup):
        shutil.move(original, backup)
    elif os.path.isfile(original) and os.path.isfile(backup):
        os.remove(original)
    shutil.copy2(source, original)
    logging.info("Host tile %s ← %s", tile_name, source)


def _restore_one(assets_dir: str, tile_name: str) -> None:
    original = os.path.join(assets_dir, tile_name)
    backup = os.path.join(assets_dir, tile_name.replace(".png", "_backup.png"))
    if os.path.isfile(original):
        os.remove(original)
    if os.path.isfile(backup):
        shutil.move(backup, original)
