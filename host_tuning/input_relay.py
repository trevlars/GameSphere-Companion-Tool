"""Buddy-mode input relay flag (INPUTRELAY verb).

Stream agent UI merges guest input into host P1 when merge=true. Host Companion
stores the flag in runtime JSON — no Sunshine restart required.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict

from host_tuning.couch_coop import runtime_json_path

_lock = threading.Lock()
_state: Dict[str, Any] = {"merge": False, "buddySlot": 1, "updatedAt": 0.0}


def _load_runtime() -> Dict[str, Any]:
    path = runtime_json_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_runtime(extra: Dict[str, Any]) -> None:
    path = runtime_json_path()
    data = _load_runtime()
    data.update(extra)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        if payload.get("query") or payload.get("status"):
            return status()
        if "merge" in payload:
            _state["merge"] = bool(payload.get("merge"))
        if payload.get("buddySlot") is not None:
            try:
                _state["buddySlot"] = max(1, min(3, int(payload.get("buddySlot"))))
            except (TypeError, ValueError):
                pass
        _state["updatedAt"] = time.time()
        _save_runtime(
            {
                "inputRelay": {
                    "merge": _state["merge"],
                    "buddySlot": _state["buddySlot"],
                    "updatedAt": _state["updatedAt"],
                }
            }
        )
    return status()


def status() -> Dict[str, Any]:
    runtime = _load_runtime().get("inputRelay") or {}
    with _lock:
        merge = bool(runtime.get("merge")) if runtime else bool(_state.get("merge"))
        slot = int(runtime.get("buddySlot") or _state.get("buddySlot") or 1)
    return {
        "ok": True,
        "merge": merge,
        "buddySlot": slot,
        "inputRelay": merge,
        "note": "Buddy mode merges guest input into host P1 when merge=true.",
    }
