"""Tailscale presence detection (Windows + Linux)."""

from __future__ import annotations

import re
import subprocess
from typing import Tuple


def detect_tailscale() -> Tuple[bool, str]:
    """Return (detected, ipv4_or_empty)."""
    ip = _tailscale_cli_ip()
    if ip:
        return True, ip
    return _detect_via_interfaces()


def _tailscale_cli_ip() -> str:
    for cmd in (["tailscale", "ip", "-4"], ["/usr/bin/tailscale", "ip", "-4"]):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                line = (result.stdout or "").strip().splitlines()[0].strip()
                if line.startswith("100."):
                    return line
        except (FileNotFoundError, subprocess.TimeoutExpired, IndexError):
            continue
    return ""


def _detect_via_interfaces() -> Tuple[bool, str]:
    try:
        import psutil  # noqa: WPS433 — optional dep already in project

        for nic, addrs in psutil.net_if_addrs().items():
            if "tailscale" not in nic.lower():
                continue
            for addr in addrs:
                if getattr(addr, "family", None) == 2:  # AF_INET
                    ip = addr.address
                    if ip.startswith("100."):
                        return True, ip
            return True, ""
    except Exception:
        pass

    # Fallback: parse `ip addr` on Linux
    try:
        result = subprocess.run(["ip", "-4", "addr", "show"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return False, ""
        current = ""
        for line in result.stdout.splitlines():
            if line.strip().startswith("inet ") and current and "tailscale" in current.lower():
                m = re.search(r"inet (100\.\d+\.\d+\.\d+)", line)
                if m:
                    return True, m.group(1)
            if ": " in line:
                current = line.split(": ", 1)[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False, ""
