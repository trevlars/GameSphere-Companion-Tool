"""Guest kick + session-end broadcast for co-op bridge verbs."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from host_tuning.config import config_dir
from host_tuning import couch_coop
from host_tuning import join_request

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_events: List[Dict[str, Any]] = []
_SESSION_PATH = lambda: os.path.join(config_dir(), "coop_session.json")


def _load() -> Dict[str, Any]:
    path = _SESSION_PATH()
    if not os.path.isfile(path):
        return {"events": [], "endedAt": 0.0}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data.setdefault("events", [])
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"events": [], "endedAt": 0.0}


def _save(data: Dict[str, Any]) -> None:
    from host_tuning.json_store import write_json_atomic

    write_json_atomic(_SESSION_PATH(), data)


def _push(event: Dict[str, Any]) -> None:
    with _lock:
        data = _load()
        events: List[Dict[str, Any]] = list(data.get("events") or [])
        events.append(event)
        data["events"] = events[-32:]
        _save(data)
        _events.clear()
        _events.extend(data["events"][-8:])


def kick(payload: Dict[str, Any]) -> Dict[str, Any]:
    uuid = str(payload.get("uuid") or payload.get("clientId") or payload.get("guestUuid") or "").strip()
    slot = payload.get("slot")
    reason = str(payload.get("reason") or "host_kick").strip() or "host_kick"
    target = uuid
    if slot is not None:
        try:
            idx = int(slot) - 1
            coop = couch_coop.status()
            players = coop.get("players") or []
            if 0 <= idx < len(players):
                target = str(players[idx].get("clientId") or players[idx].get("key") or uuid)
        except (TypeError, ValueError):
            pass
    if not target:
        return {"ok": False, "error": "missing_target"}
    event = {"type": "kick", "uuid": target, "reason": reason, "at": time.time()}
    _push(event)
    # Clear pending join requests from kicked guest.
    try:
        join_request.expire_for_uuid(target)
    except Exception:
        _log.debug("join_request expire failed", exc_info=True)
    return {"ok": True, "uuid": target, "reason": reason}


def session_end(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    reason = str(payload.get("reason") or "session_end").strip() or "session_end"
    now = time.time()
    event = {"type": "session_end", "reason": reason, "at": now}
    _push(event)
    with _lock:
        data = _load()
        data["endedAt"] = now
        data["lastReason"] = reason
        _save(data)
    try:
        from host_tuning import wanna_play

        wanna_play.end_session()
    except Exception:
        _log.debug("wanna_play end failed", exc_info=True)
    try:
        couch_coop.clear_stream_active()
    except Exception:
        pass
    if reason in ("host_quit", "quit", "user_quit"):
        try:
            from host_tuning import sunshine_quit

            sunshine_quit.close_current_game_async()
        except Exception:
            _log.debug("sunshine_quit on session_end failed", exc_info=True)
    return {"ok": True, "reason": reason, "endedAt": now}


def coopstate_fields() -> Dict[str, Any]:
    data = _load()
    events = list(data.get("events") or [])[-8:]
    ended = float(data.get("endedAt") or 0)
    return {
        "sessionEvents": events,
        "sessionEndedAt": ended if ended else None,
        "sessionEndReason": data.get("lastReason") or "",
    }
