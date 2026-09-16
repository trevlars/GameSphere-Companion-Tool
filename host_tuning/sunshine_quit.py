"""Host-side quit backup when GameSphere sends SESSIONEND host_quit.

Moonlight /cancel from the phone is primary (prep-cmd undo → gamesphere-steam-close).
If /cancel fails or never arrives, Companion closes the running Sunshine app locally.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional

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


def _steam_close_helper() -> Optional[str]:
    for candidate in (
        shutil.which("gamesphere-steam-close.sh"),
        os.path.expanduser("~/.local/bin/gamesphere-steam-close.sh"),
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    repo = os.path.expanduser("~/.local/share/gamesphere-import-tool/scripts/gamesphere-steam-close.sh")
    if os.path.isfile(repo):
        return repo
    return None


def close_app_id(app_id: str) -> bool:
    app_id = (app_id or "").strip()
    if not app_id.isdigit() or app_id == "0":
        return False
    helper = _steam_close_helper()
    if not helper:
        _log.warning("sunshine_quit: gamesphere-steam-close.sh not found")
        return False
    try:
        subprocess.Popen(
            [helper, app_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _log.info("sunshine_quit: spawned %s %s", helper, app_id)
        return True
    except Exception as exc:
        _log.warning("sunshine_quit: failed to spawn close helper: %s", exc)
        return False


def _other_stream_clients_connected() -> bool:
    """True when co-op guests are still attached — do not close the host game."""
    try:
        from host_tuning import couch_coop

        pads = couch_coop.status().get("sunshine") or []
        if len(pads) >= 2:
            return True
    except Exception:
        _log.debug("sunshine_quit couch_coop status failed", exc_info=True)
    info = _serverinfo()
    state = (info.get("state") or "").upper()
    if "BUSY" in state and info.get("currentgame", "0") not in ("", "0"):
        # Sunshine still serving a session — host phone may have dropped first.
        return True
    return False


def close_current_game() -> bool:
    if _other_stream_clients_connected():
        _log.info("sunshine_quit: skipped — other stream clients still connected")
        return False
    info = _serverinfo()
    state = info.get("state", "")
    app_id = info.get("currentgame", "0")
    if app_id in ("", "0"):
        if "BUSY" in state:
            _log.info("sunshine_quit: Sunshine busy but currentgame=0 — skip")
        return False
    _log.info("sunshine_quit: closing app %s (state=%s)", app_id, state)
    return close_app_id(app_id)


def close_current_game_async() -> None:
    threading.Thread(
        target=close_current_game,
        name="sunshine_quit",
        daemon=True,
    ).start()
