"""Steam → Sunshine library auto-sync state + helpers."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from host_tuning.config import config_dir
from host_tuning.json_store import write_json_atomic


STATE_NAME = "library_sync.json"


def state_path() -> str:
    return os.path.join(config_dir(), STATE_NAME)


def read_state() -> Dict[str, Any]:
    path = state_path()
    if not os.path.isfile(path):
        return {"ok": None, "ever_run": False}
    try:
        import json

        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {"ok": None, "ever_run": False, "error": "invalid state"}
        data["ever_run"] = True
        data["path"] = path
        return data
    except Exception as exc:
        return {"ok": False, "ever_run": True, "error": str(exc), "path": path}


def record(
    *,
    ok: bool,
    message: str,
    added: int = 0,
    removed: int = 0,
    changed: bool = False,
    dry_run: bool = False,
    no_restart: bool = True,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist the result of a library sync for Decky / status."""
    payload: Dict[str, Any] = {
        "ok": bool(ok),
        "message": (message or "").strip(),
        "added": int(added),
        "removed": int(removed),
        "changed": bool(changed),
        "dry_run": bool(dry_run),
        "no_restart": bool(no_restart),
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if extra:
        payload.update(extra)
    write_json_atomic(state_path(), payload)
    return payload


def status_summary() -> Dict[str, Any]:
    """JSON for CLI / Decky: last sync + whether the systemd timer is armed."""
    out = read_state()
    out["timer"] = timer_state()
    return out


def timer_state() -> Dict[str, Any]:
    """Best-effort systemd user timer status (Linux only)."""
    if os.name == "nt":
        return {"supported": False, "active": False, "enabled": False}
    import shutil
    import subprocess

    systemctl = shutil.which("systemctl")
    if not systemctl:
        return {"supported": False, "active": False, "enabled": False, "unit": "gamesphere-library-sync.timer"}
    unit = "gamesphere-library-sync.timer"

    def _user_cmd(args: list[str]) -> tuple[int, str]:
        try:
            result = subprocess.run(
                [systemctl, "--user", *args],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()
        except Exception as exc:
            return 1, str(exc)

    active_code, active_out = _user_cmd(["is-active", unit])
    enabled_code, enabled_out = _user_cmd(["is-enabled", unit])
    return {
        "supported": True,
        "unit": unit,
        "active": active_code == 0 and active_out.strip() in ("active", "waiting"),
        "enabled": enabled_code == 0 and enabled_out.strip() in ("enabled", "enabled-runtime", "static"),
        "active_state": active_out.strip() or "unknown",
        "enabled_state": enabled_out.strip() or "unknown",
    }
