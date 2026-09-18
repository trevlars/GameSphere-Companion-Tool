"""Launch state for bridge GAMESTATE / LAUNCHRESULT (StreamTweak LaunchWatcher subset)."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

import psutil

_EXECUTING = re.compile(r'^Executing:\s*\["([^"]+)"\]', re.I)
# The Sunshine log monitor writes these from its own thread while bridge
# GAMESTATE / LAUNCHRESULT handlers read them, so guard both.
_lock = threading.RLock()
_LAST_LAUNCH: Optional[str] = None
_LAST_RESULT: Dict[str, Any] = {
    "state": "idle",
    "game": "",
    "cmd": "",
    "detail": "",
    "startedAt": 0.0,
    "updatedAt": 0.0,
    "attempts": 0,
}


def note_launch_from_log_line(line: str) -> None:
    global _LAST_LAUNCH
    if "Executing Do Cmd:" in line:
        return
    m = _EXECUTING.search(line.strip())
    if m:
        with _lock:
            _LAST_LAUNCH = m.group(1)
            _touch(state="launching", game=os.path.basename(_LAST_LAUNCH), cmd=_LAST_LAUNCH)


def note_launch_attempt(*, game: str = "", cmd: str = "", detail: str = "") -> None:
    global _LAST_LAUNCH
    with _lock:
        if cmd:
            _LAST_LAUNCH = cmd
        _touch(
            state="waiting_steam" if detail == "waiting_steam" else "launching",
            game=game,
            cmd=cmd or _LAST_LAUNCH or "",
            detail=detail,
        )
        _LAST_RESULT["attempts"] = int(_LAST_RESULT.get("attempts") or 0) + 1


def note_launch_failed(detail: str) -> None:
    with _lock:
        _touch(state="failed", detail=detail)


def _touch(**fields: Any) -> None:
    """Update launch state. Caller holds ``_lock``."""
    now = time.time()
    _LAST_RESULT.update(fields)
    _LAST_RESULT["updatedAt"] = now
    if fields.get("state") in ("launching", "waiting_steam") and not _LAST_RESULT.get("startedAt"):
        _LAST_RESULT["startedAt"] = now


def _proc_matches(target: str) -> bool:
    exe_name = os.path.basename(target.replace("\\", "/"))
    stem = os.path.splitext(exe_name)[0].lower()
    for proc in psutil.process_iter(["name", "exe", "status"]):
        try:
            pinfo = proc.info
            pname = (pinfo.get("name") or "").lower()
            pexe = (pinfo.get("exe") or "").lower()
            if stem and (stem in pname or stem in pexe or exe_name.lower() in pexe):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False


def _compute_state(target: Optional[str]) -> Dict[str, Any]:
    if not target:
        return {"v": 2, "state": "idle", "game": "", "cmd": "", "detail": ""}

    state = "starting"
    exe_name = os.path.basename(target.replace("\\", "/"))
    if _proc_matches(target):
        state = "running"
    elif any(x in target.lower() for x in ("steam.exe", "battle.net", "epicgameslauncher", "steam ")):
        state = "attention"

    started = float(_LAST_RESULT.get("startedAt") or 0)
    if state in ("starting", "attention") and started and time.time() - started > 90:
        state = "failed"
        detail = "Launch timed out — Steam may still be updating or Big Picture is not ready."
    else:
        detail = str(_LAST_RESULT.get("detail") or "")

    return {
        "v": 2,
        "state": state,
        "game": exe_name,
        "cmd": target,
        "detail": detail,
        "attempts": int(_LAST_RESULT.get("attempts") or 0),
        "updatedAt": int(_LAST_RESULT.get("updatedAt") or 0),
    }


def game_state_json(last_log_lines: Optional[List[str]] = None) -> str:
    with _lock:
        target = _LAST_LAUNCH
    if last_log_lines and not target:
        for line in reversed(last_log_lines):
            note_launch_from_log_line(line)
            with _lock:
                target = _LAST_LAUNCH
            if target:
                break
    # Computed outside the lock: it scans the process table and must not block
    # the Sunshine log monitor.
    payload = _compute_state(target)
    with _lock:
        _LAST_RESULT.update(payload)
    return json.dumps(payload)


def launch_result_json(last_log_lines: Optional[List[str]] = None) -> str:
    """LAUNCHRESULT — richer status for GameSphere phone UI."""
    game_state_json(last_log_lines)
    with _lock:
        target = _LAST_LAUNCH
    base = _compute_state(target)
    steam_up = False
    try:
        for proc in psutil.process_iter(["name"]):
            if "steam" in (proc.info.get("name") or "").lower():
                steam_up = True
                break
    except Exception:
        pass
    out = {
        **base,
        "ok": base.get("state") in ("running", "idle"),
        "steamReady": steam_up,
        "LAUNCHRESULT": base.get("state"),
        "message": _message(base),
    }
    return json.dumps(out)


def _message(base: Dict[str, Any]) -> str:
    state = base.get("state")
    game = base.get("game") or "game"
    if state == "running":
        return f"{game} is running on the host."
    if state == "attention":
        return f"Waiting for {game} — check Steam Big Picture or a launcher dialog on the PC."
    if state == "failed":
        return base.get("detail") or f"{game} did not start — re-run import or check Steam."
    if state in ("starting", "launching", "waiting_steam"):
        return f"Launching {game} on the host…"
    return "No launch in progress."
