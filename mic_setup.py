"""
GameSphere Mic to PC — one UX, OS-specific under the hood.

Windows: VB-CABLE (VB-Audio donationware) + bundled VBAN→CABLE feeder.
Linux: PipeWire libpipewire-module-vban-recv (MIT).

Does not change GameSphere iOS VBAN sender. Does not bundle proprietary binaries.
Does not install VoiceMeeter.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, List, Optional

STREAM_NAME = os.environ.get("GAMESPHERE_VBAN_STREAM", "GameSphere")
PORT = int(os.environ.get("GAMESPHERE_VBAN_PORT", "6980"))

LogFn = Callable[[str], None]


@dataclass
class MicSetupResult:
    ok: bool
    platform: str
    stream_name: str = STREAM_NAME
    port: int = PORT
    lan_ips: List[str] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)
    needs_license_accept: bool = False
    reboot_hint: bool = False
    recording_device_hint: str = ""
    error: Optional[str] = None

    def summary(self) -> str:
        lines = list(self.messages)
        if self.lan_ips:
            lines.append("")
            lines.append("LAN IP(s) for GameSphere → Send mic to PC:")
            for ip in self.lan_ips:
                lines.append(f"  {ip}")
            lines.append(f"Port {self.port} · stream name {self.stream_name}")
        if self.recording_device_hint:
            lines.append("")
            lines.append(self.recording_device_hint)
        if self.reboot_hint:
            lines.append("")
            lines.append("Reboot Windows once if CABLE Output is missing, then set Discord to CABLE Output.")
        if self.error:
            lines.append("")
            lines.append(f"Error: {self.error}")
        return "\n".join(lines).strip() + "\n"


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _scripts_dir() -> str:
    base = _base_dir()
    candidates = [
        os.path.join(base, "scripts"),
        os.path.join(os.path.dirname(sys.executable), "scripts") if getattr(sys, "frozen", False) else "",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"),
    ]
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return os.path.join(base, "scripts")


def detect_lan_ips() -> List[str]:
    """Best-effort IPv4 LAN addresses (no 127/link-local)."""
    ips: List[str] = []
    try:
        import socket

        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            if ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
                        "Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' "
                        "-and $_.PrefixOrigin -ne 'WellKnown' } | "
                        "Sort-Object InterfaceMetric, IPAddress | "
                        "Select-Object -ExpandProperty IPAddress -Unique"
                    ),
                ],
                text=True,
                timeout=20,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                ip = line.strip()
                if ip and ip not in ips:
                    ips.append(ip)
        except Exception:
            pass
    else:
        try:
            out = subprocess.check_output(
                ["ip", "-4", "-o", "addr", "show", "scope", "global"],
                text=True,
                timeout=10,
                stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4 and "/" in parts[3]:
                    ip = parts[3].split("/", 1)[0]
                    if ip and ip not in ips:
                        ips.append(ip)
        except Exception:
            pass
    return ips


def _log(log: Optional[LogFn], msg: str) -> None:
    if log:
        log(msg)


def _run_ps1(script: str, *args: str, log: Optional[LogFn] = None) -> subprocess.CompletedProcess:
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        script,
        *args,
    ]
    _log(log, f"$ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
    )


def _run_bash(script: str, *args: str, log: Optional[LogFn] = None) -> subprocess.CompletedProcess:
    cmd = ["bash", script, *args]
    _log(log, f"$ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _windows_recording_hint() -> str:
    return (
        "In Discord, OBS, or games: set microphone to “CABLE Output” "
        "(VB-Audio Virtual Cable). Import Tool’s feeder plays the phone into CABLE Input."
    )


def _start_windows_feeder(log: Optional[LogFn]) -> bool:
    from vban_feeder import register_autostart, start_feeder_detached

    register_autostart(log=lambda m: _log(log, m))
    return start_feeder_detached(log=lambda m: _log(log, m))


def setup_mic(
    *,
    accept_third_party: bool = False,
    info_only: bool = False,
    log: Optional[LogFn] = None,
) -> MicSetupResult:
    """
    Single entry point for Import Tool GUI / CLI.

    On Windows, accept_third_party=True means the user accepted VB-Audio donationware
    terms for VB-CABLE download/install (we never bundle the driver).
    """
    plat = sys.platform
    result = MicSetupResult(ok=False, platform=plat, lan_ips=detect_lan_ips())

    if plat == "darwin":
        result.messages.append(
            "Mic to PC one-click targets Windows (VB-CABLE + feeder) and Linux (PipeWire). "
            "On a Mac host, use a Windows/Linux Sunshine PC as the stream host."
        )
        result.ok = True if info_only else False
        result.error = None if info_only else "macOS host is not supported for one-click mic setup"
        result.recording_device_hint = (
            "Use a Windows or Linux Sunshine host for automatic setup."
        )
        return result

    scripts = _scripts_dir()

    if plat == "win32":
        ps1 = os.path.join(scripts, "gamesphere-vban-setup.ps1")
        if not os.path.isfile(ps1):
            result.error = f"Missing helper script: {ps1}"
            result.messages.append(result.error)
            return result

        result.recording_device_hint = _windows_recording_hint()

        if info_only:
            proc = _run_ps1(ps1, "-Action", "info", log=log)
            out = (proc.stdout or "") + (proc.stderr or "")
            result.messages.append(out.strip() or "Printed Windows mic defaults.")
            try:
                from vban_feeder import cable_input_present, list_feeder_pids

                if cable_input_present():
                    result.messages.append("CABLE Input: present")
                else:
                    result.messages.append("CABLE Input: not found yet (install VB-CABLE, reboot if needed)")
                pids = list_feeder_pids()
                if pids:
                    result.messages.append(f"VBAN feeder: running (pid {pids[0]})")
                else:
                    result.messages.append("VBAN feeder: not running")
            except Exception as exc:
                result.messages.append(f"(feeder status unavailable: {exc})")
            result.ok = proc.returncode == 0
            return result

        if not accept_third_party:
            result.needs_license_accept = True
            result.messages.append(
                "Windows uses VB-CABLE (VB-Audio donationware) as the virtual mic, "
                "plus Import Tool’s small VBAN feeder (OSS) that plays the phone into CABLE Input. "
                "Accept the license to continue; we download VB-CABLE from VB-Audio — "
                "nothing proprietary is bundled in this repo. VoiceMeeter is not installed."
            )
            result.ok = False
            return result

        proc = _run_ps1(ps1, "-Action", "setup", "-AcceptLicense", log=log)
        out = (proc.stdout or "") + (proc.stderr or "")
        if out.strip():
            result.messages.append(out.strip())
        result.lan_ips = detect_lan_ips() or result.lan_ips
        rc = proc.returncode
        result.reboot_hint = rc == 3010 or "reboot" in out.lower()
        # 3010 = reboot required after driver install; still treat as success.
        result.ok = rc in (0, 3010)
        if result.ok:
            started = _start_windows_feeder(log)
            if started:
                result.messages.append("VBAN feeder started and set to run at logon.")
            else:
                result.messages.append(
                    "VB-CABLE is set up, but the VBAN feeder did not stay running. "
                    "Reboot if CABLE Input is missing, then click Set up mic again."
                )
        if rc not in (0, 3010):
            result.error = f"Windows mic setup exited with code {rc}"
        return result

    # Linux / Bazzite / Steam Deck desktop
    sh = os.path.join(scripts, "gamesphere-vban-setup.sh")
    if not os.path.isfile(sh):
        which = shutil.which("gamesphere-vban-setup.sh")
        sh = which or sh
    if not os.path.isfile(sh):
        result.error = f"Missing helper script: {sh}"
        result.messages.append(result.error)
        return result

    action = "info" if info_only else "install"
    proc = _run_bash(sh, action, log=log)
    out = (proc.stdout or "") + (proc.stderr or "")
    if out.strip():
        result.messages.append(out.strip())
    result.lan_ips = detect_lan_ips() or result.lan_ips
    result.ok = proc.returncode == 0
    result.recording_device_hint = (
        'Pick “GameSphere Mic (VBAN)” (or similar PipeWire source) as the recording device.'
    )
    if proc.returncode != 0:
        result.error = f"Linux mic setup exited with code {proc.returncode}"
    return result


def platform_label() -> str:
    if sys.platform == "win32":
        return "Windows"
    if sys.platform.startswith("linux"):
        return "Linux"
    return platform.system()
