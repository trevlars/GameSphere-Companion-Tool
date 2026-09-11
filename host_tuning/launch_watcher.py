"""Launch state for bridge GAMESTATE (StreamTweak LaunchWatcher subset)."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

import psutil

# Sunshine/Apollo log: Executing: ["path"] — not Executing Do Cmd:
_EXECUTING = re.compile(r'^Executing:\s*\["([^"]+)"\]', re.I)
_LAST_LAUNCH: Optional[str] = None


def note_launch_from_log_line(line: str) -> None:
    global _LAST_LAUNCH
    if "Executing Do Cmd:" in line:
        return
    m = _EXECUTING.search(line.strip())
    if m:
        _LAST_LAUNCH = m.group(1)


def game_state_json(last_log_lines: Optional[List[str]] = None) -> str:
    """
    Report launch progress for the last game the host was asked to open.
    States: idle | starting | running | attention
    """
    target = _LAST_LAUNCH
    if last_log_lines and not target:
        for line in reversed(last_log_lines):
            note_launch_from_log_line(line)
            if _LAST_LAUNCH:
                target = _LAST_LAUNCH
                break

    if not target:
        return json.dumps({"v": 1, "state": "idle", "game": ""})

    state = "starting"
    exe_name = os.path.basename(target.replace("\\", "/"))
    stem = os.path.splitext(exe_name)[0].lower()

    for proc in psutil.process_iter(["name", "exe", "status"]):
        try:
            pinfo = proc.info
            pname = (pinfo.get("name") or "").lower()
            pexe = (pinfo.get("exe") or "").lower()
            if stem and (stem in pname or stem in pexe or exe_name.lower() in pexe):
                state = "running"
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    # Launcher-only still starting (Steam/Epic/Battle.net client without game exe yet)
    if state == "starting" and any(x in target.lower() for x in ("steam.exe", "battle.net", "epicgameslauncher")):
        state = "attention"

    return json.dumps({"v": 1, "state": state, "game": os.path.basename(target), "cmd": target})
