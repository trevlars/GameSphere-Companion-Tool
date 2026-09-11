"""Build APPSTORES JSON from host apps.json (game name → store label)."""

from __future__ import annotations

import json
import os
from typing import Dict


def app_stores_from_apps_json(apps_json_path: str) -> Dict[str, str]:
    if not apps_json_path or not os.path.isfile(apps_json_path):
        return {}
    try:
        with open(apps_json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    stores: Dict[str, str] = {}
    for app in data.get("apps") or []:
        name = (app.get("name") or "").strip()
        if not name:
            continue
        store = (app.get("_gamesphere_store") or "").strip()
        if not store:
            cmd = " ".join([
                str(app.get("cmd") or ""),
                str(app.get("detached") or ""),
            ]).lower()
            if "steam://rungameid" in cmd or "steam" in cmd:
                store = "Steam"
            elif "com.epicgames.launcher" in cmd:
                store = "Epic Games"
            elif "shell:appsfolder" in cmd:
                store = "Xbox"
        if store:
            stores[name] = store
    return stores


def app_stores_json(apps_json_path: str) -> str:
    return json.dumps(app_stores_from_apps_json(apps_json_path))
