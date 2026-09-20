"""Resolve Sunshine apps.json entries for quit / close helpers."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

_STEAM_RUNGAME = re.compile(r"steam://rungameid/(\d+)", re.I)


def apps_json_path() -> str:
    env = (
        os.environ.get("SUNSHINE_APPS_JSON_PATH")
        or os.environ.get("sunshine_apps_json_path")
        or ""
    ).strip()
    if env and os.path.isfile(env):
        return env
    try:
        from platform_paths import detect_paths

        detected = detect_paths()
        if detected and detected.sunshine_apps_json:
            return detected.sunshine_apps_json
    except Exception:
        pass
    return ""


def load_apps(path: str = "") -> List[Dict[str, Any]]:
    apps_path = path or apps_json_path()
    if not apps_path or not os.path.isfile(apps_path):
        return []
    try:
        with open(apps_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    apps = data.get("apps") or []
    return [a for a in apps if isinstance(a, dict)]


def app_for_sunshine_id(sunshine_id: str, apps: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    raw = (sunshine_id or "").strip()
    if not raw.isdigit():
        return None
    items = apps if apps is not None else load_apps()
    if not items:
        return None
    idx = int(raw)
    # Sunshine / Moonlight app IDs are 1-based indices into apps.json.
    if 1 <= idx <= len(items):
        return items[idx - 1]
    if 0 <= idx < len(items):
        return items[idx]
    return None


def app_for_store_key(store_key: str, apps: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    key = (store_key or "").strip()
    if not key:
        return None
    for app in apps if apps is not None else load_apps():
        if (app.get("_gamesphere_store_key") or "").strip() == key:
            return app
    return None


def steam_app_id_from_app(app: Dict[str, Any]) -> Optional[str]:
    for field in ("cmd", "detached"):
        raw = app.get(field)
        if isinstance(raw, list):
            raw = " ".join(str(x) for x in raw)
        text = str(raw or "")
        match = _STEAM_RUNGAME.search(text)
        if match:
            return match.group(1)
    return None


def store_label_from_app(app: Dict[str, Any]) -> str:
    store = (app.get("_gamesphere_store") or "").strip()
    if store:
        return store
    blob = " ".join(
        [
            str(app.get("cmd") or ""),
            str(app.get("detached") or ""),
        ]
    ).lower()
    if "com.epicgames.launcher" in blob:
        return "Epic Games"
    if "shell:appsfolder" in blob:
        return "Xbox"
    if "steam://rungameid" in blob:
        return "Steam"
    return ""


def close_metadata_from_app(app: Dict[str, Any]) -> Dict[str, str]:
    store_key = (app.get("_gamesphere_store_key") or "").strip()
    exe_path = (app.get("_gamesphere_exe_path") or app.get("exe_path") or "").strip()
    store = store_label_from_app(app)
    steam_id = steam_app_id_from_app(app) or ""
    return {
        "store": store,
        "store_key": store_key,
        "exe_path": exe_path,
        "steam_id": steam_id,
        "name": (app.get("name") or "").strip(),
    }
