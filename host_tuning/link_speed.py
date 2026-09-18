"""
Wired link-speed management (StreamTweak-inspired).

Windows: PowerShell Get-NetAdapter / Set-NetAdapterAdvancedProperty
Linux: ethtool (read always; write requires root)
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from host_tuning.config import load_config, save_config, state_path


def _load_state() -> Dict[str, Any]:
    if not os.path.isfile(state_path()):
        return {}
    try:
        with open(state_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    from host_tuning.json_store import write_json_atomic

    write_json_atomic(state_path(), state)


def find_wired_adapter(preferred: str = "") -> Optional[str]:
    if os.name == "nt":
        return _find_wired_adapter_windows(preferred)
    return _find_wired_adapter_linux(preferred)


def get_link_info(adapter: str) -> Dict[str, Any]:
    if os.name == "nt":
        return _link_info_windows(adapter)
    return _link_info_linux(adapter)


def set_link_speed_mbps(adapter: str, mbps: int) -> Tuple[bool, str]:
    if os.name == "nt":
        return _set_speed_windows(adapter, mbps)
    return _set_speed_linux(adapter, mbps)


def restore_link_speed(adapter: str) -> Tuple[bool, str]:
    state = _load_state().get("link_speed") or {}
    if not state.get("original_setting") and not state.get("original_autoneg"):
        return True, "nothing to restore"
    if os.name == "nt":
        return _restore_windows(adapter, state)
    return _restore_linux(adapter, state)


def netinfo_json(adapter: str, session_active: bool = False) -> str:
    cfg = load_config()
    info = get_link_info(adapter) if adapter else {}
    state = _load_state().get("link_speed") or {}
    payload = {
        "adapter": adapter or "",
        "current_mbps": info.get("current_mbps", 0),
        "supported_mbps": info.get("supported_mbps", []),
        "allow_client_control": cfg.allow_client_link_control,
        "session_active": session_active,
        "state": state.get("state", "idle"),
        "switched": bool(state.get("switched")),
        "original_mbps": state.get("original_mbps", 0),
    }
    return json.dumps(payload)


def request_client_speed(adapter: str, mbps: int, client_name: str = "GameSphere") -> Tuple[str, str]:
    cfg = load_config()
    if not cfg.link_speed_enabled:
        return "ERR_NOT_ALLOWED", "host tuning disabled"
    if not cfg.allow_client_link_control:
        return "ERR_NOT_ALLOWED", "client link control disabled"
    if not adapter:
        return "ERR_NO_ADAPTER", "no wired adapter"
    info = get_link_info(adapter)
    supported = info.get("supported_mbps") or []
    if supported and mbps not in supported:
        return "ERR_UNSUPPORTED", f"supported: {supported}"
    state = _load_state()
    ls = state.setdefault("link_speed", {})
    if not ls.get("switched"):
        ls["original_mbps"] = info.get("current_mbps", 0)
        ls["original_setting"] = info.get("setting", "")
        ls["original_autoneg"] = info.get("autoneg", True)
    ok, msg = set_link_speed_mbps(adapter, mbps)
    if ok:
        ls["switched"] = True
        ls["switched_mbps"] = mbps
        ls["switched_by"] = client_name
        ls["state"] = "idle"
        _save_state(state)
        return "OK", str(mbps)
    ls["state"] = "error"
    _save_state(state)
    return "ERR", msg


def _find_wired_adapter_windows(preferred: str) -> Optional[str]:
    ps = (
        "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.MediaType -eq '802.3' "
        "-and $_.InterfaceDescription -notmatch 'Wi-Fi|Wireless|Virtual|VPN|Tailscale' } "
        "| Select-Object -ExpandProperty Name"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=15,
        )
        names = [n.strip() for n in (result.stdout or "").splitlines() if n.strip()]
        if preferred and preferred in names:
            return preferred
        return names[0] if names else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return preferred or None


def _link_info_windows(adapter: str) -> Dict[str, Any]:
    ps = (
        f"$a = Get-NetAdapter -Name '{adapter}' -ErrorAction SilentlyContinue; "
        "if (-not $a) { '{}' ; exit }; "
        "$speed = [math]::Round($a.LinkSpeed / 1000000); "
        "$props = Get-NetAdapterAdvancedProperty -Name $a.Name | "
        "Where-Object { $_.DisplayName -match 'Speed' -or $_.RegistryKeyword -match 'SpeedDuplex' }; "
        "$setting = ($props | Select-Object -First 1).DisplayValue; "
        "@{ current_mbps = $speed; setting = $setting; autoneg = ($setting -match 'Auto') } | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            data["supported_mbps"] = _common_speeds_mbps(data.get("current_mbps", 1000))
            return data
    except (json.JSONDecodeError, subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return {"current_mbps": 0, "supported_mbps": [100, 1000, 2500, 10000]}


def _set_speed_windows(adapter: str, mbps: int) -> Tuple[bool, str]:
    # Map Mbps to common SpeedDuplex display values
    duplex_map = {
        10: "*10 Mbps Full Duplex",
        100: "*100 Mbps Full Duplex",
        1000: "*1.0 Gbps Full Duplex",
        2500: "*2.5 Gbps Full Duplex",
        10000: "*10.0 Gbps Full Duplex",
    }
    display = duplex_map.get(mbps)
    if not display:
        return False, f"unsupported mbps {mbps}"
    ps = (
        f"Set-NetAdapterAdvancedProperty -Name '{adapter}' -DisplayName 'Speed & Duplex' "
        f"-DisplayValue '{display}' -ErrorAction Stop"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, display
        return False, (result.stderr or result.stdout or "set failed").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def _restore_windows(adapter: str, ls: Dict[str, Any]) -> Tuple[bool, str]:
    setting = ls.get("original_setting") or "*Auto Negotiation"
    ps = (
        f"Set-NetAdapterAdvancedProperty -Name '{adapter}' -DisplayName 'Speed & Duplex' "
        f"-DisplayValue '{setting}' -ErrorAction Stop"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=30,
        )
        state = _load_state()
        state.pop("link_speed", None)
        _save_state(state)
        return result.returncode == 0, (result.stderr or "restored").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def _find_wired_adapter_linux(preferred: str) -> Optional[str]:
    try:
        result = subprocess.run(["ip", "-o", "link", "show", "up"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return preferred or None
        candidates = []
        for line in result.stdout.splitlines():
            m = re.match(r"\d+:\s+([^:]+):", line)
            if not m:
                continue
            name = m.group(1).split("@")[0]
            low = name.lower()
            if any(x in low for x in ("wl", "wifi", "tailscale", "docker", "veth", "br-", "virbr")):
                continue
            if "state UP" in line or "LOWER_UP" in line:
                candidates.append(name)
        if preferred and preferred in candidates:
            return preferred
        # prefer en*/eth*
        for prefix in ("en", "eth", "eno", "enp"):
            for name in candidates:
                if name.startswith(prefix):
                    return name
        return candidates[0] if candidates else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return preferred or None


def _link_info_linux(adapter: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {"current_mbps": 0, "supported_mbps": [100, 1000, 2500, 10000], "autoneg": True}
    try:
        result = subprocess.run(["ethtool", adapter], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return info
        speed = 0
        autoneg = True
        supported = set()
        for line in result.stdout.splitlines():
            if line.strip().startswith("Speed:"):
                m = re.search(r"(\d+)Mb/s", line)
                if m:
                    speed = int(m.group(1))
            if "Auto-negotiation:" in line:
                autoneg = "on" in line.lower()
            if line.strip().startswith("Supported link modes:") or "baseT" in line:
                for val in re.findall(r"(\d+)baseT", line):
                    supported.add(int(val))
        info["current_mbps"] = speed
        info["autoneg"] = autoneg
        if supported:
            info["supported_mbps"] = sorted(supported)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logging.debug("ethtool unavailable for %s", adapter)
    return info


def _set_speed_linux(adapter: str, mbps: int) -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            ["ethtool", "-s", adapter, "speed", str(mbps), "duplex", "full", "autoneg", "off"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, f"{mbps}Mbps"
        return False, (result.stderr or "ethtool failed — try sudo").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def _restore_linux(adapter: str, ls: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        if ls.get("original_autoneg", True):
            cmd = ["ethtool", "-s", adapter, "autoneg", "on"]
        else:
            mbps = ls.get("original_mbps") or 1000
            cmd = ["ethtool", "-s", adapter, "speed", str(mbps), "duplex", "full", "autoneg", "off"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        state = _load_state()
        state.pop("link_speed", None)
        _save_state(state)
        return result.returncode == 0, (result.stderr or "restored").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def _common_speeds_mbps(current: int) -> List[int]:
    speeds = [100, 1000, 2500, 10000]
    if current and current not in speeds:
        speeds.append(current)
    return sorted(set(speeds))
