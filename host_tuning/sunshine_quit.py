"""Host-side quit backup when GameSphere sends SESSIONEND host_quit.

Moonlight /cancel from the phone is primary (prep-cmd undo → gamesphere-*-close).
If /cancel fails or never arrives, Companion closes the running Sunshine app locally.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

_log = logging.getLogger(__name__)

_SERVERINFO_URL = "http://127.0.0.1:47989/serverinfo"


def _serverinfo() -> dict[str, str]:
    try:
        with urllib.request.urlopen(_SERVERINFO_URL, timeout=3) as resp:
            root = ET.fromstring(resp.read())
        return {
            "state": (root.findtext("state") or "").strip(),
            "currentgame": (
                root.findtext("currentgame") or root.findtext("CurrentGame") or "0"
            ).strip(),
        }
    except Exception as exc:
        _log.debug("sunshine_quit serverinfo failed: %s", exc)
        return {}


def _close_helper(name: str) -> Optional[str]:
    sh_name = f"gamesphere-{name}-close.sh"
    for candidate in (
        shutil.which(sh_name),
        os.path.expanduser(f"~/.local/bin/{sh_name}"),
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    repo = os.path.expanduser(
        f"~/.local/share/gamesphere-import-tool/scripts/{sh_name}"
    )
    if os.path.isfile(repo):
        return repo
    return None


def _spawn_helper(helper: str, args: list[str]) -> bool:
    try:
        subprocess.Popen(
            [helper, *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _log.info("sunshine_quit: spawned %s %s", helper, " ".join(args))
        return True
    except Exception as exc:
        _log.warning("sunshine_quit: failed to spawn close helper: %s", exc)
        return False


def close_steam_app_id(app_id: str) -> bool:
    app_id = (app_id or "").strip()
    if not app_id.isdigit() or app_id == "0":
        return False
    helper = _close_helper("steam")
    if not helper:
        _log.warning("sunshine_quit: gamesphere-steam-close.sh not found")
        return False
    return _spawn_helper(helper, [app_id])


def close_store_app(
    *,
    sunshine_id: str = "",
    store_key: str = "",
    exe_path: str = "",
) -> bool:
    helper = _close_helper("store")
    if not helper:
        _log.warning("sunshine_quit: gamesphere-store-close.sh not found")
        return False
    args: list[str] = []
    if store_key:
        args.extend(["--store-key", store_key])
    elif sunshine_id:
        args.extend(["--sunshine-id", sunshine_id])
    else:
        return False
    if exe_path:
        args.extend(["--exe-path", exe_path])
    return _spawn_helper(helper, args)


def close_sunshine_app(app_id: str, payload: Optional[Dict[str, Any]] = None) -> bool:
    """Resolve apps.json entry and spawn the correct close helper."""
    payload = payload or {}
    app_id = (app_id or "").strip()
    if not app_id.isdigit() or app_id == "0":
        return False
    try:
        from host_tuning import sunshine_apps

        app = sunshine_apps.app_for_sunshine_id(app_id)
        if app:
            meta = sunshine_apps.close_metadata_from_app(app)
            if meta.get("steam_id"):
                return close_steam_app_id(meta["steam_id"])
            if meta.get("store_key"):
                return close_store_app(
                    sunshine_id=app_id,
                    store_key=meta["store_key"],
                    exe_path=meta.get("exe_path") or "",
                )
    except Exception:
        _log.debug("sunshine_quit apps.json lookup failed", exc_info=True)

    store_hint = str(payload.get("store") or "").strip().lower()
    game_name = str(payload.get("game") or "").strip()
    if store_hint and store_hint != "steam" and game_name:
        try:
            from host_tuning import sunshine_apps

            for app in sunshine_apps.load_apps():
                if (app.get("name") or "").strip() == game_name:
                    meta = sunshine_apps.close_metadata_from_app(app)
                    if meta.get("store_key"):
                        return close_store_app(
                            sunshine_id=app_id,
                            store_key=meta["store_key"],
                            exe_path=meta.get("exe_path") or "",
                        )
        except Exception:
            _log.debug("sunshine_quit name lookup failed", exc_info=True)
    # Legacy fallback — may match small Steam app ids.
    return close_steam_app_id(app_id)


def close_app_id(app_id: str) -> bool:
    return close_sunshine_app(app_id)


def _other_stream_clients_connected() -> bool:
    """True when co-op guests are still attached — do not close the host game.

    Only pad count is reliable. Sunshine ``SERVER_BUSY`` alone is *not* “other
    clients” — the host phone is still attached (or mid-teardown) when it sends
    ``SESSIONEND host_quit``, so treating BUSY as a skip left the PC game running.
    """
    try:
        from host_tuning import couch_coop

        pads = couch_coop.status().get("sunshine") or []
        if len(pads) >= 2:
            return True
    except Exception:
        _log.debug("sunshine_quit couch_coop status failed", exc_info=True)
    return False


def _close_by_game_name(payload: Dict[str, Any]) -> bool:
    """When Sunshine already cleared currentgame, use phone {game, store} hints."""
    game_name = str(payload.get("game") or "").strip()
    if not game_name:
        return False
    store_hint = str(payload.get("store") or "").strip().lower()
    try:
        from host_tuning import sunshine_apps

        for app in sunshine_apps.load_apps():
            if (app.get("name") or "").strip() != game_name:
                continue
            meta = sunshine_apps.close_metadata_from_app(app)
            if meta.get("steam_id"):
                return close_steam_app_id(meta["steam_id"])
            if meta.get("store_key"):
                return close_store_app(
                    store_key=meta["store_key"],
                    exe_path=meta.get("exe_path") or "",
                )
            # Name matched but no close metadata — keep looking.
        if store_hint and store_hint != "steam":
            # Last resort: any app with this display name already checked above.
            _log.info(
                "sunshine_quit: no close helper for game=%r store=%r",
                game_name,
                store_hint,
            )
    except Exception:
        _log.debug("sunshine_quit name close failed", exc_info=True)
    return False


def close_current_game(payload: Optional[Dict[str, Any]] = None) -> bool:
    import time

    payload = payload or {}
    if _other_stream_clients_connected():
        _log.info("sunshine_quit: skipped — other stream clients still connected")
        return False

    # Retry briefly: /cancel and SESSIONEND race; currentgame can flicker.
    for attempt in range(3):
        info = _serverinfo()
        state = info.get("state", "")
        app_id = info.get("currentgame", "0")
        if app_id not in ("", "0"):
            _log.info(
                "sunshine_quit: closing app %s (state=%s attempt=%s payload=%s)",
                app_id,
                state,
                attempt + 1,
                json.dumps(payload, sort_keys=True),
            )
            return close_sunshine_app(app_id, payload)
        if _close_by_game_name(payload):
            _log.info(
                "sunshine_quit: closed via game name hint (attempt=%s payload=%s)",
                attempt + 1,
                json.dumps(payload, sort_keys=True),
            )
            return True
        if attempt < 2:
            time.sleep(0.6)

    _log.info(
        "sunshine_quit: nothing to close (currentgame=0, no game hint matched) payload=%s",
        json.dumps(payload, sort_keys=True),
    )
    return False


def close_current_game_async(payload: Optional[Dict[str, Any]] = None) -> None:
    threading.Thread(
        target=close_current_game,
        args=(payload,),
        name="sunshine_quit",
        daemon=True,
    ).start()
