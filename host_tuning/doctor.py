"""Idempotent --setup / --doctor for GameSphere Companion Tool."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional

_log = logging.getLogger(__name__)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _run(cmd: List[str], *, log: Optional[Callable[[str], None]] = None) -> int:
    if log:
        log(f"$ {' '.join(cmd)}")
    try:
        return subprocess.run(cmd, cwd=ROOT, check=False).returncode
    except OSError as exc:
        if log:
            log(f"ERR {exc}")
        return 1


def _check(path: str) -> bool:
    return bool(path) and os.path.exists(path)


def _systemd_user_unit(name: str) -> bool:
    code, out = subprocess.getstatusoutput(f"systemctl --user is-active {name}")
    return code == 0 or "active" in out


def _logrotate_ok() -> bool:
    conf = os.path.expanduser("~/.config/logrotate.d/gamesphere-companion")
    return os.path.isfile(conf)


def _sunshine_running() -> bool:
    try:
        import psutil

        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if "sunshine" in name or name == "sunshinesvc.exe":
                return True
    except Exception:
        pass
    return False


def _steam_ready() -> bool:
    try:
        import psutil

        for proc in psutil.process_iter(["name", "exe"]):
            name = (proc.info.get("name") or "").lower()
            exe = (proc.info.get("exe") or "").lower()
            if "steam" in name or "steam" in exe:
                return True
    except Exception:
        pass
    return False


def _apps_json_ok() -> bool:
    try:
        from platform_paths import detect_paths

        detected = detect_paths()
        if detected and detected.sunshine_apps_json:
            return os.path.isfile(detected.sunshine_apps_json)
    except Exception:
        pass
    return False


def _bridge_listening() -> bool:
    import socket

    try:
        with socket.create_connection(("127.0.0.1", 47998), timeout=1.5):
            return True
    except OSError:
        return False


def _mic_check() -> Dict[str, Any]:
    """GameSphere Mic is session-scoped — idle hosts pass when the bridge is up."""
    if sys.platform == "win32":
        return {"ok": True, "detail": "Windows VB-CABLE path (no PipeWire GameSphere Mic)"}
    try:
        from host_tuning import couch_coop
        from host_tuning import voice_bridge

        st = voice_bridge.status()
        voice_running = bool(st.get("running"))
        pc_ready = bool(st.get("pcMicReady"))
        clients = int(st.get("clients") or 0)
        streaming = bool(couch_coop.stream_active())

        if not streaming and clients == 0:
            if pc_ready:
                return {
                    "ok": True,
                    "detail": "GameSphere Mic ready (idle — not system default)",
                }
            return {
                "ok": True,
                "detail": "GameSphere Mic idle — virtual device appears when a voice session starts (not system default)",
                "info": True,
            }

        if voice_running and pc_ready:
            return {"ok": True, "detail": "GameSphere Mic / voice bridge active"}
        if not voice_running:
            return {"ok": False, "detail": "Voice bridge UDP not running"}
        err = st.get("pcMicError") or "PipeWire GameSphere Mic source missing"
        return {"ok": False, "detail": f"GameSphere Mic not ready during session: {err}"}
    except Exception as exc:
        return {"ok": False, "detail": f"mic check failed: {exc}"}


def diagnose(*, log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    from host_tuning import wan_setup
    from host_tuning import zerotier
    from host_tuning import host_identity
    from host_tuning import metadata_catalog

    wan = wan_setup.status()
    zt = zerotier.status(force=True)
    ident = host_identity.snapshot()
    # Kick the catalog scan and give it a few seconds; a huge ROM library must not
    # make --doctor hang, so report catalogReady=false instead of blocking.
    meta = metadata_catalog.cached(kick=True)
    deadline = time.time() + 8.0
    while not meta.get("ready") and time.time() < deadline:
        time.sleep(0.25)
        meta = metadata_catalog.cached(kick=False)
    catalog_ready = bool(meta.get("ready"))
    owned_n = len(meta.get("ownedApps") or [])
    roms_n = len(meta.get("romHashes") or [])
    checks: List[Dict[str, Any]] = [
        {"id": "sunshine", "ok": _sunshine_running(), "detail": "Sunshine/Apollo process"},
        {"id": "steam", "ok": _steam_ready(), "detail": "Steam client running (launch reliability)"},
        {"id": "apps_json", "ok": _apps_json_ok(), "detail": "Sunshine apps.json present"},
        {"id": "bridge", "ok": _bridge_listening(), "detail": "TCP 47998 host-bridge listening"},
        {"id": "mic", **_mic_check()},
        {"id": "wan", "ok": bool(wan.get("lanHost")), "detail": f"LAN {wan.get('lanHost') or '?'} WAN {wan.get('wanHost') or '?'}"},
        {"id": "zerotier", "ok": not zt.get("lanRouteConflict"), "detail": zt.get("zerotierStatus") or ""},
        {"id": "host_identity", "ok": bool(ident.get("hostSteamId")), "detail": ident.get("hostPersona") or "Steam persona"},
        {
            "id": "owned_apps",
            "ok": owned_n > 0 or not catalog_ready,
            "detail": f"{owned_n} Steam apps" if catalog_ready else "catalog scan still running — HOSTINFO fills in shortly",
        },
        {
            "id": "rom_hashes",
            "ok": True,
            "detail": f"{roms_n} ROM hashes scanned" if catalog_ready else "ROM hash scan in progress",
        },
        {"id": "systemd_bridge", "ok": _systemd_user_unit("gamesphere-host-bridge.service") or _bridge_listening(), "detail": "gamesphere-host-bridge.service"},
        {"id": "logrotate", "ok": _logrotate_ok(), "detail": "~/.config/logrotate.d/gamesphere-companion"},
    ]
    if sys.platform == "win32":
        checks = [c for c in checks if c["id"] not in ("systemd_bridge", "logrotate")]
    ok_count = sum(1 for c in checks if c["ok"])
    summary = {
        "ok": ok_count == len(checks),
        "passed": ok_count,
        "total": len(checks),
        "checks": checks,
        "wanReady": bool(wan.get("wanReady")),
        "catalogReady": catalog_ready,
        "zerotierHost": zt.get("zerotierHost") or "",
        "zerotierConflict": zt.get("lanRouteConflict") or "",
        "tailscaleHost": wan.get("tailscaleHost") or "",
        "hostSteamId": ident.get("hostSteamId") or "",
        "windowsGaps": (
            "Windows: no systemd, no PipeWire GameSphere Mic (VB-CABLE path), Task Scheduler daemon — protocol parity only."
            if sys.platform == "win32"
            else ""
        ),
    }
    if log:
        log(json.dumps(summary, indent=2))
    return summary


def _ensure_logrotate(log: Optional[Callable[[str], None]] = None) -> None:
    """Install user-level logrotate drop-in (no sudo). System logrotate may need
    ``LOGROTATE_USER=1`` or a user timer — doctor only checks the file exists."""
    dest = os.path.expanduser("~/.config/logrotate.d/gamesphere-companion")
    src = os.path.join(ROOT, "scripts", "logrotate", "gamesphere-companion")
    content = ""
    if os.path.isfile(src):
        with open(src, encoding="utf-8") as fh:
            content = fh.read()
    if not content.strip():
        content = """~/.local/share/gamesphere-import/*.log ~/.local/share/gamesphere-import/logs/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    copytruncate
}
"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(content)
    if log:
        log(f"installed logrotate {dest}")
        if not shutil.which("logrotate"):
            log(
                "note: logrotate binary not on PATH — install with "
                "`sudo dnf install logrotate` (Fedora/Bazzite) or equivalent; "
                "user configs live in ~/.config/logrotate.d/"
            )


def run_setup(*, log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Idempotent first-run / repair — mirrors install-linux.sh essentials."""
    steps: List[str] = []
    if log:
        log("==> GameSphere Companion --setup")

    from host_tuning import zerotier

    zerotier.start_guard_timer()
    zerotier.guard_once()
    steps.append("zerotier_guard")

    try:
        from host_tuning_cli import main as tuning_main

        tuning_main(["init", "--enable-all"])
        steps.append("host_tuning_init")
    except Exception as exc:
        if log:
            log(f"host_tuning init: {exc}")

    fw = os.path.join(ROOT, "scripts", "gamesphere-host-firewall.sh")
    if os.path.isfile(fw):
        _run(["bash", fw], log=log)
        steps.append("firewall")

    mic_script = os.path.join(ROOT, "scripts", "gamesphere-pc-mic-setup.sh")
    if os.name != "nt" and os.path.isfile(mic_script):
        _run(["bash", mic_script], log=log)
        steps.append("pc_mic")

    try:
        from host_tuning.host_daemon import install as daemon_install

        daemon_install()
        steps.append("host_daemon")
    except Exception as exc:
        if log:
            log(f"daemon install: {exc}")

    _ensure_logrotate(log)
    steps.append("logrotate")

    report = diagnose(log=None)
    report["setupSteps"] = steps
    return report
