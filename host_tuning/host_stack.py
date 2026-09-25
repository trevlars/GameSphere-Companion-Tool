"""Linux host stack shipped with Companion: hide Steam clones, firewall, Sunshine conf.

Any Sunshine PC — not a leftover host-specific script. Never restarts Sunshine.
Never prints Sunshine passwords.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

UDEV_NAME = "99-gamesphere-hide-steam-clones.rules"
HIDE_BIN = "gamesphere-hide-steam-clones.sh"
FIREWALL_BIN = "gamesphere-host-firewall.sh"
UDEV_DEST = f"/etc/udev/rules.d/{UDEV_NAME}"

TCP_PORTS = (47984, 47989, 48010, 47998)
UDP_PORTS = (47998, 47999, 48000, 48002, 48010, 48020)
NEVER_PORTS = (47990,)


def repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def _bin_dir() -> str:
    return os.path.expanduser("~/.local/bin")


def _copy_script(name: str, dest_name: str = "") -> str:
    src = os.path.join(repo_root(), "scripts", name)
    dest = os.path.join(_bin_dir(), dest_name or os.path.basename(name))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.isfile(src):
        shutil.copy2(src, dest)
        os.chmod(dest, 0o755)
    return dest


def _run(cmd: List[str], *, timeout: int = 20) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return False


def install_hide_helper() -> Dict[str, Any]:
    dest = _copy_script(HIDE_BIN)
    return {"ok": os.path.isfile(dest), "path": dest}


def retire_udev_rules() -> Dict[str, Any]:
    """Disable the always-on clone-hiding rule older releases installed.

    Proton / native Steam games read only Steam Input's 28de:11ff clones, so a
    global MODE=000 rule leaves them without a controller. The host daemon now
    hides clones only while an emulator runs (host_tuning.couch_coop).
    """
    user_copy = os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
        "gamesphere-import-tool",
        "udev",
        UDEV_NAME,
    )
    try:
        os.remove(user_copy)
    except OSError:
        pass
    if not os.path.isfile(UDEV_DEST):
        return {"ok": True, "path": UDEV_DEST, "active": False}
    prefix: List[str] = [] if os.geteuid() == 0 else ["sudo", "-n"]
    retired = _run(prefix + ["mv", "-f", UDEV_DEST, UDEV_DEST + ".disabled"])
    if retired:
        _run(prefix + ["udevadm", "control", "--reload-rules"])
        return {"ok": True, "path": UDEV_DEST, "retired": True}
    return {
        "ok": False,
        "path": UDEV_DEST,
        "hint": f"sudo mv {UDEV_DEST} {UDEV_DEST}.disabled && sudo udevadm control --reload-rules",
    }


def open_linux_firewall() -> Dict[str, Any]:
    dest = _copy_script(FIREWALL_BIN)
    ran = _run([dest], timeout=40) if os.path.isfile(dest) else False
    return {
        "ok": True,
        "script": dest,
        "applied": ran,
        "tcp": list(TCP_PORTS),
        "udp": list(UDP_PORTS),
        "never": list(NEVER_PORTS),
    }


def open_windows_firewall() -> Dict[str, Any]:
    if sys.platform != "win32":
        return {"ok": True, "skipped": "not windows"}
    results: List[Dict[str, Any]] = []
    for port in TCP_PORTS:
        name = f"GameSphere Companion TCP {port}"
        cmd = [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={name}",
            "dir=in",
            "action=allow",
            "protocol=TCP",
            f"localport={port}",
        ]
        results.append({"port": port, "proto": "TCP", "ok": _run(cmd)})
    for port in UDP_PORTS:
        name = f"GameSphere Companion UDP {port}"
        cmd = [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={name}",
            "dir=in",
            "action=allow",
            "protocol=UDP",
            f"localport={port}",
        ]
        results.append({"port": port, "proto": "UDP", "ok": _run(cmd)})
    return {"ok": True, "rules": results, "never": list(NEVER_PORTS)}


def apply_sunshine_recommended() -> Dict[str, Any]:
    try:
        from host_tuning import sunshine_wan

        return sunshine_wan.apply_recommended()
    except Exception as exc:
        _log.debug("sunshine recommended: %s", exc)
        return {"ok": False, "error": str(exc), "needsRestart": False}


def install_linux_stack() -> Dict[str, Any]:
    """Enable couch-coop helpers on any Linux Sunshine host. Does not restart Sunshine."""
    out: Dict[str, Any] = {
        "hideHelper": install_hide_helper(),
        "udev": retire_udev_rules(),
        "firewall": open_linux_firewall(),
        "sunshine": apply_sunshine_recommended(),
        "sunshine_touched": False,
    }
    try:
        from host_tuning.couch_coop import hide_steam_clones

        out["hiddenClones"] = hide_steam_clones()
    except Exception as exc:
        out["hiddenClones"] = 0
        out["hideError"] = str(exc)
    return out


def install_windows_stack() -> Dict[str, Any]:
    return {
        "firewall": open_windows_firewall(),
        "sunshine": apply_sunshine_recommended(),
        "sunshine_touched": False,
    }
