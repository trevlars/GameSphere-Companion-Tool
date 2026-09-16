"""ZeroTier detection + LAN guard for GameSphere Companion.

Reports zerotierHost for HOSTINFO/COOPSTATE. Ensures ZeroTier never owns the home
LAN prefix (e.g. 10.0.5.0/24) — that breaks voice downlink and LAN discovery.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_guard_thread: Optional[threading.Thread] = None
_stop = threading.Event()

# Home LAN prefixes that must never be routed via ZeroTier.
_LAN_PREFIXES = (
    "10.0.4.",
    "10.0.5.",
    "10.0.6.",
    "10.0.7.",
    "192.168.",
    "172.16.",
)

_ZT_NETS = ("10.147.", "10.144.", "10.241.")


def _run(cmd: List[str], timeout: float = 4.0) -> Tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def zerotier_cli() -> str:
    for name in ("zerotier-cli", "/usr/bin/zerotier-cli", "/usr/sbin/zerotier-cli"):
        if os.path.isfile(name) and os.access(name, os.X_OK):
            return name
    found = _run(["which", "zerotier-cli"])[1].splitlines()
    return found[0].strip() if found else "zerotier-cli"


def list_networks() -> List[Dict[str, Any]]:
    cli = zerotier_cli()
    code, out = _run([cli, "listnetworks", "-j"])
    if code == 0 and out.startswith("["):
        try:
            data = json.loads(out)
            return [row for row in data if isinstance(row, dict)]
        except json.JSONDecodeError:
            pass
    rows: List[Dict[str, Any]] = []
    code, out = _run([cli, "listnetworks"])
    if code != 0:
        return rows
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[0] in ("200", "listnetworks"):
            continue
        rows.append({"id": parts[1], "status": parts[2], "assignedAddresses": parts[5:] if len(parts) > 5 else []})
    return rows


def _pick_ip(addrs: List[str]) -> str:
    for raw in addrs:
        ip = raw.split("/")[0].strip()
        if not ip or ":" in ip:
            continue
        if any(ip.startswith(p) for p in _ZT_NETS):
            return ip
    for raw in addrs:
        ip = raw.split("/")[0].strip()
        if ip and ":" not in ip and not any(ip.startswith(p) for p in _LAN_PREFIXES):
            return ip
    return ""


def detect_ip() -> str:
    for net in list_networks():
        status = str(net.get("status") or "").upper()
        if status and status not in ("OK", "ACCESS_DENIED", "REQUESTING_CONFIGURATION"):
            continue
        addrs = net.get("assignedAddresses") or net.get("assigned addresses") or []
        if isinstance(addrs, str):
            addrs = addrs.split()
        ip = _pick_ip([str(a) for a in addrs])
        if ip:
            return ip
    # Fallback: parse `ip -4 addr show zt*`
    code, out = _run(["ip", "-4", "-o", "addr", "show"])
    if code == 0:
        for line in out.splitlines():
            if "zt" not in line.lower():
                continue
            m = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)", line)
            if m:
                ip = m.group(1)
                if any(ip.startswith(p) for p in _ZT_NETS):
                    return ip
    return ""


def lan_route_conflict() -> Optional[str]:
    """Return a human sentence if ZT appears to own a home LAN prefix."""
    code, out = _run(["ip", "route", "show"])
    if code != 0:
        return None
    for line in out.splitlines():
        if "zt" not in line.lower():
            continue
        parts = line.split()
        if not parts:
            continue
        dest = parts[0]
        for prefix in _LAN_PREFIXES:
            bare = prefix.rstrip(".")
            if dest.startswith(bare) or dest == bare:
                return (
                    f"ZeroTier route {dest} via zt* steals home LAN {bare}.x — "
                    "remove it or voice/LAN discovery will break."
                )
    return None


def guard_once() -> Dict[str, Any]:
    """Best-effort: delete ZT routes that cover home LAN prefixes."""
    conflict = lan_route_conflict()
    if not conflict:
        return {"ok": True, "action": "none"}
    removed: List[str] = []
    failed: List[str] = []
    code, out = _run(["ip", "route", "show"])
    if code != 0:
        return {"ok": False, "error": conflict, "removed": removed, "failed": failed}
    for line in out.splitlines():
        if "zt" not in line.lower():
            continue
        parts = line.split()
        if not parts:
            continue
        dest = parts[0]
        dev = ""
        for i, token in enumerate(parts):
            if token == "dev" and i + 1 < len(parts):
                dev = parts[i + 1]
                break
        for prefix in _LAN_PREFIXES:
            bare = prefix.rstrip(".")
            if dest.startswith(bare) or dest == bare:
                if dev:
                    rc, _ = _run(["ip", "route", "del", dest, "dev", dev])
                    if rc != 0:
                        rc, _ = _run(["sudo", "-n", "ip", "route", "del", dest, "dev", dev])
                    if rc == 0:
                        removed.append(f"{dest} dev {dev}")
                        _log.warning("ZT guard removed route %s dev %s", dest, dev)
                    else:
                        failed.append(f"{dest} dev {dev}")
                        _log.warning("ZT guard could not remove %s dev %s (needs root)", dest, dev)
    with _lock:
        _status_cache["value"] = None
    return {"ok": not failed, "conflict": conflict, "removed": removed, "failed": failed}


def _guard_loop() -> None:
    while not _stop.wait(90.0):
        try:
            guard_once()
        except Exception:
            _log.debug("ZT guard tick failed", exc_info=True)


def start_guard_timer() -> None:
    global _guard_thread
    if _guard_thread and _guard_thread.is_alive():
        return
    _stop.clear()
    _guard_thread = threading.Thread(target=_guard_loop, daemon=True, name="gamesphere-zt-guard")
    _guard_thread.start()


def stop_guard_timer() -> None:
    _stop.set()


_STATUS_TTL = 20.0
_status_cache: Dict[str, Any] = {"at": 0.0, "value": None}


def status(*, force: bool = False) -> Dict[str, Any]:
    """Read-only ZeroTier snapshot, cached so HOSTINFO/COOPSTATE polls never shell
    out more than once per ``_STATUS_TTL`` seconds. Route repair is left to
    :func:`guard_once` (timer / ``--setup``), never done from a status query."""
    now = time.time()
    with _lock:
        cached = _status_cache.get("value")
        if cached is not None and not force and now - float(_status_cache.get("at") or 0) < _STATUS_TTL:
            return dict(cached)
    ip = detect_ip()
    conflict = lan_route_conflict()
    value = {
        "ok": True,
        "zerotierHost": ip,
        "zerotierReady": bool(ip),
        "zerotierStatus": (
            f"ZeroTier overlay {ip} — use for remote join when away from home Wi‑Fi."
            if ip
            else "ZeroTier not detected — install ZeroTier One on this PC for remote play."
        ),
        "lanRouteConflict": conflict or "",
        "lanRouteGuardRunning": bool(_guard_thread and _guard_thread.is_alive()),
    }
    with _lock:
        _status_cache["at"] = time.time()
        _status_cache["value"] = dict(value)
    return value
