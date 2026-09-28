"""ENSUREAPP — add one Steam title to Sunshine apps.json without restarting Sunshine.

Used by GameSphere "Push to Sphere": phone sends ENSUREAPP {"steamAppId":12345}
and Companion merges a steam://rungameid shortcut into apps.json (--no-restart).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from typing import Any, Dict, Optional

_STEAM_RUNGAME = re.compile(r"steam://rungameid/(\d+)", re.I)


def _parse_app_id(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text.isdigit():
        return None
    # Reject obvious shortcut / non-store ids (32-bit Non-Steam rungameid high bits).
    value = int(text)
    if value <= 0 or value > 2_000_000_000:
        return None
    return str(value)


def _steam_app_id_from_app(app: Dict[str, Any]) -> Optional[str]:
    for field in ("cmd", "detached"):
        raw = app.get(field)
        if isinstance(raw, list):
            raw = " ".join(str(x) for x in raw)
        text = str(raw or "")
        match = _STEAM_RUNGAME.search(text)
        if match:
            return match.group(1)
    return None


def _find_existing(apps: list, app_id: str) -> Optional[Dict[str, Any]]:
    for app in apps or []:
        if not isinstance(app, dict):
            continue
        found = _steam_app_id_from_app(app)
        if found and str(found) == app_id:
            return app
        key = str(app.get("_gamesphere_store_key") or "")
        if key == f"steam:{app_id}":
            return app
    return None


def _resolve_name(app_id: str, hint: Optional[str]) -> str:
    hint_name = (hint or "").strip()
    if hint_name:
        return hint_name
    try:
        # Lazy import — main.py pulls Steam/Sunshine helpers.
        import main as import_main

        name = import_main.get_game_name(app_id)
        if name:
            return name
    except Exception as exc:
        logging.debug("ENSUREAPP name lookup failed for %s: %s", app_id, exc)
    return f"Steam App {app_id}"


def _config_paths() -> Dict[str, str]:
    import main as import_main

    return import_main.validate_config(auto_detect=True)


def _kick_steam_install(app_id: str) -> None:
    """Best-effort: ask Steam to start downloading the title in the background."""
    uri = f"steam://install/{app_id}"
    try:
        if os.name == "nt":
            os.startfile(uri)  # type: ignore[attr-defined]
            return
        # Linux / macOS: prefer `steam` CLI when present.
        steam = None
        for candidate in ("steam", "xdg-open", "open"):
            from shutil import which

            steam = which(candidate)
            if steam:
                break
        if not steam:
            return
        subprocess.Popen(
            [steam, uri] if os.path.basename(steam) == "steam" else [steam, uri],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        logging.debug("ENSUREAPP steam install kick failed for %s: %s", app_id, exc)


def ensure_steam_app(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ensure one Steam store appid exists in Sunshine apps.json (no host restart)."""
    payload = payload or {}
    app_id = _parse_app_id(
        payload.get("steamAppId")
        or payload.get("steam_app_id")
        or payload.get("appId")
        or payload.get("appid")
    )
    if not app_id:
        return {"ok": False, "error": "missing_steam_app_id", "state": "error"}

    name_hint = payload.get("name") or payload.get("gameName") or payload.get("title")
    kick_install = payload.get("install", True)
    if isinstance(kick_install, str):
        kick_install = kick_install.strip().lower() not in ("0", "false", "no")

    try:
        config = _config_paths()
    except Exception as exc:
        logging.exception("ENSUREAPP config failed")
        return {"ok": False, "error": f"config:{exc}", "steamAppId": app_id, "state": "error"}

    apps_path = config.get("SUNSHINE_APPS_JSON_PATH") or ""
    if not apps_path:
        return {"ok": False, "error": "missing_apps_json_path", "steamAppId": app_id, "state": "error"}

    try:
        import main as import_main

        sunshine_config = import_main.get_sunshine_config(apps_path)
        apps = list(sunshine_config.get("apps") or [])
        existing = _find_existing(apps, app_id)
        if existing:
            return {
                "ok": True,
                "state": "already_present",
                "steamAppId": app_id,
                "name": (existing.get("name") or "").strip() or _resolve_name(app_id, name_hint),
                "appsPath": apps_path,
                "noRestart": True,
            }

        game_name = _resolve_name(app_id, str(name_hint) if name_hint else None)
        grid_path = ""
        try:
            api_key = (config.get("STEAMGRIDDB_API_KEY") or "").strip()
            grids = (config.get("SUNSHINE_GRIDS_FOLDER") or "").strip()
            if api_key and grids:
                grid_path = import_main.fetch_grid_from_steamgriddb(app_id, api_key, grids) or ""
        except Exception as exc:
            logging.debug("ENSUREAPP grid fetch skipped: %s", exc)

        new_app = import_main._build_steam_app(app_id, game_name, grid_path or None)
        new_app["_gamesphere_store"] = "Steam"
        new_app["_gamesphere_store_key"] = f"steam:{app_id}"
        apps.append(new_app)
        sunshine_config["apps"] = apps
        import_main.save_sunshine_config(apps_path, sunshine_config)

        installed = False
        try:
            vdf = config.get("STEAM_LIBRARY_VDF_PATH") or ""
            if vdf:
                installed = app_id in import_main.installed_steam_app_ids(vdf)
        except Exception:
            installed = False

        if kick_install and not installed:
            threading.Thread(
                target=_kick_steam_install,
                args=(app_id,),
                name=f"ensure-steam-install-{app_id}",
                daemon=True,
            ).start()

        return {
            "ok": True,
            "state": "added" if installed else "added_installing",
            "steamAppId": app_id,
            "name": game_name,
            "installed": installed,
            "appsPath": apps_path,
            "noRestart": True,
        }
    except Exception as exc:
        logging.exception("ENSUREAPP failed for %s", app_id)
        return {"ok": False, "error": str(exc), "steamAppId": app_id, "state": "error"}


def ensure_steam_app_json(arg: str) -> str:
    """Bridge entry: parse ENSUREAPP JSON arg → JSON response line."""
    payload: Dict[str, Any] = {}
    text = (arg or "").strip()
    if text:
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                payload = loaded
            elif isinstance(loaded, (int, float, str)):
                payload = {"steamAppId": loaded}
        except json.JSONDecodeError:
            if text.isdigit():
                payload = {"steamAppId": text}
            else:
                return json.dumps({"ok": False, "error": "bad_json", "state": "error"})
    return json.dumps(ensure_steam_app(payload))
