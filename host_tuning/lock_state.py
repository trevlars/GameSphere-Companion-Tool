"""Host lock-screen detection for bridge LOCKSTATE (StreamTweak subset)."""

from __future__ import annotations

import json
import os
import subprocess
import sys


def is_workstation_locked() -> bool:
    if sys.platform == "win32":
        return _locked_windows()
    if sys.platform.startswith("linux"):
        return _locked_linux()
    return False


def lock_state_json() -> str:
    return json.dumps({"v": 1, "locked": is_workstation_locked()})


def _locked_windows() -> bool:
    try:
        ps = (
            "Add-Type @'\nusing System; using System.Runtime.InteropServices;\n"
            "public class W { [DllImport(\"user32.dll\")] public static extern bool GetForegroundWindow(); }\n'@; "
            "$s = Get-Process -Name LogonUI -ErrorAction SilentlyContinue; "
            "if ($s) { 'locked' } else { 'unlocked' }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "locked" in (result.stdout or "").lower()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _locked_linux() -> bool:
    for cmd in (
        ["loginctl", "show-session", "self", "-p", "LockedHint"],
        ["gnome-screensaver-command", "-q"],
    ):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            out = (result.stdout or "").lower()
            if "lockedhint=yes" in out.replace(" ", ""):
                return True
            if "is active" in out and "lock" in out:
                return True
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            break
    return False
