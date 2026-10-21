"""System sleep / suspend hints for COOPSTATE — phones skip error UI when the PC sleeps."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict

from host_tuning.config import config_dir

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_sleeping = False
_sleeping_since = 0.0
_last_reason = ""
_WATCHER_STARTED = False

_SLEEP_REASONS = frozenset({"host_sleep", "system_sleep", "host_suspend", "suspend"})


def _power_path() -> str:
    return os.path.join(config_dir(), "host_power.json")


def _persist() -> None:
    from host_tuning.json_store import write_json_atomic

    with _lock:
        payload = {
            "sleeping": _sleeping,
            "since": _sleeping_since,
            "reason": _last_reason,
        }
    write_json_atomic(_power_path(), payload)


def _load_persisted() -> None:
    global _sleeping, _sleeping_since, _last_reason
    path = _power_path()
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return
        with _lock:
            _sleeping = bool(data.get("sleeping"))
            _sleeping_since = float(data.get("since") or 0.0)
            _last_reason = str(data.get("reason") or "")
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass


def mark_sleeping(reason: str = "host_sleep") -> None:
    """Called on systemd PrepareForSleep — notify phones before the NIC drops."""
    global _sleeping, _sleeping_since, _last_reason
    reason = (reason or "host_sleep").strip() or "host_sleep"
    with _lock:
        if _sleeping and _last_reason == reason:
            return
        _sleeping = True
        _sleeping_since = time.time()
        _last_reason = reason
    _persist()
    _log.info("power_state: host sleeping (%s)", reason)
    try:
        from host_tuning import coop_session

        coop_session.session_end({"reason": reason})
    except Exception:
        _log.debug("power_state: session_end on sleep failed", exc_info=True)
    try:
        from host_tuning import couch_coop

        couch_coop.clear_stream_active()
    except Exception:
        pass


def mark_awake() -> None:
    global _sleeping, _last_reason
    with _lock:
        if not _sleeping:
            return
        since = _sleeping_since
        _sleeping = False
        _last_reason = ""
    _persist()
    _log.info("power_state: host awake (was sleeping %.1fs)", time.time() - since)


def coopstate_fields() -> Dict[str, Any]:
    with _lock:
        sleeping = _sleeping
        since = _sleeping_since if _sleeping else 0.0
        reason = _last_reason if _sleeping else ""
    return {
        "hostSleeping": sleeping,
        "hostSleepSince": since if sleeping else None,
        "hostSleepReason": reason,
    }


def _linux_logind_watch() -> None:
    try:
        proc = subprocess.Popen(
            [
                "dbus-monitor",
                "--system",
                "type='signal',sender='org.freedesktop.login1',"
                "interface='org.freedesktop.login1.Manager',member='PrepareForSleep'",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError:
        _log.debug("power_state: dbus-monitor unavailable")
        return
    if not proc.stdout:
        return
    for line in proc.stdout:
        token = (line or "").strip().lower()
        if token == "boolean true":
            mark_sleeping("host_sleep")
        elif token == "boolean false":
            mark_awake()


def start_watcher() -> None:
    global _WATCHER_STARTED
    with _lock:
        if _WATCHER_STARTED:
            return
        _WATCHER_STARTED = True
    _load_persisted()
    if sys.platform.startswith("linux"):
        threading.Thread(target=_linux_logind_watch, name="gamesphere-power", daemon=True).start()
        _log.info("power_state: logind PrepareForSleep watcher started")
