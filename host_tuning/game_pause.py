"""Pause the host game when a Moonlight/Sunshine stream drops without host_quit.

GameSphere normally pulses Start/Menu over the stream (PLAY_FLAG). When the phone
disconnects abruptly, that path is gone — inject Start/Menu locally instead.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Optional

_log = logging.getLogger(__name__)

_GRACEFUL_QUIT_TTL = 12.0
_PAUSE_COOLDOWN = 4.0
_lock = threading.Lock()
_last_graceful_quit = 0.0
_last_pause_at = 0.0

_GRACEFUL_REASONS = frozenset({"host_quit", "quit", "user_quit"})


def mark_graceful_quit(reason: str = "host_quit") -> None:
    """Phone sent SESSIONEND host_quit — do not auto-pause (game may be closing)."""
    global _last_graceful_quit
    with _lock:
        _last_graceful_quit = time.monotonic()
    _log.info("game_pause: graceful quit marked (%s)", reason)


def _graceful_quit_recent() -> bool:
    with _lock:
        return (time.monotonic() - _last_graceful_quit) < _GRACEFUL_QUIT_TTL


def _enabled() -> bool:
    try:
        from host_tuning.config import load_config

        cfg = load_config()
        return bool(getattr(cfg, "stream_pause_on_drop", True))
    except Exception:
        return True


def pause_on_stream_drop(reason: str = "stream_drop") -> bool:
    """Queue a host Start/Menu pulse unless the user explicitly quit."""
    if not _enabled():
        return False
    if _graceful_quit_recent():
        _log.info("game_pause: skipped (%s) — recent graceful host_quit", reason)
        return False
    global _last_pause_at
    with _lock:
        now = time.monotonic()
        if now - _last_pause_at < _PAUSE_COOLDOWN:
            _log.debug("game_pause: skipped (%s) — cooldown", reason)
            return False
        _last_pause_at = now
    _log.info("game_pause: pulsing Start/Menu (%s)", reason)
    threading.Thread(
        target=_pulse_start_menu,
        name="game_pause",
        daemon=True,
    ).start()
    return True


def _host_python() -> str:
    if os.name == "nt":
        return sys.executable
    if os.path.isfile("/usr/bin/python3"):
        return "/usr/bin/python3"
    return sys.executable


def _pulse_script_path() -> Optional[str]:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = (
        os.path.join(here, "scripts", "gamesphere-pulse-start.py"),
        os.path.expanduser("~/.local/bin/gamesphere-pulse-start.py"),
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _pulse_start_menu() -> None:
    if os.name == "nt":
        _pulse_windows()
        return
    script = _pulse_script_path()
    if not script:
        _log.warning("game_pause: gamesphere-pulse-start.py not found")
        return
    try:
        proc = subprocess.run(
            [_host_python(), script],
            capture_output=True,
            text=True,
            timeout=8,
            env=_subprocess_env(),
        )
        if proc.returncode == 0:
            return
        _log.warning(
            "game_pause: pulse script exit %s stderr=%s",
            proc.returncode,
            (proc.stderr or "").strip()[:200],
        )
    except (subprocess.SubprocessError, OSError) as exc:
        _log.warning("game_pause: pulse failed: %s", exc)


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV", None)
    env.pop("UV_RUN_RECURSION_DEPTH", None)
    parts = [p for p in env.get("PATH", "").split(":") if ".venv/bin" not in p]
    if parts:
        env["PATH"] = ":".join(parts)
    return env


def _pulse_windows() -> None:
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # VK_ESCAPE — common pause in fullscreen PC games when stream pad is gone.
        VK_ESCAPE = 0x1B
        KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(VK_ESCAPE, 0, 0, 0)
        time.sleep(0.08)
        user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0)
    except Exception as exc:
        _log.warning("game_pause: windows pulse failed: %s", exc)
