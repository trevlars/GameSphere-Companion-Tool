"""HDR and spatial audio hooks (Windows + best-effort Linux)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any, Dict, List, Tuple


def list_hdr_capable_displays() -> List[Dict[str, Any]]:
    if os.name == "nt":
        return _list_hdr_windows()
    return _list_hdr_linux()


def set_hdr_enabled(monitor: str, enabled: bool) -> Tuple[bool, str]:
    if os.name == "nt":
        return _set_hdr_windows(monitor, enabled)
    return _set_hdr_linux(monitor, enabled)


def enable_spatial_audio(device_name: str, fmt: str = "dolby") -> Tuple[bool, str]:
    if os.name == "nt":
        return _enable_spatial_windows(device_name, fmt)
    return _enable_spatial_linux(device_name, fmt)


def _list_hdr_windows() -> List[Dict[str, Any]]:
    ps = (
        "Get-CimInstance -Namespace root\\wmi -ClassName WmiMonitorBasicDisplayParams -ErrorAction SilentlyContinue | "
        "ForEach-Object { $_.InstanceName }"
    )
    # Simpler: use DisplayAdvancedColorSetting via reg / powershell stub
    ps = (
        "$monitors = @(); "
        "Add-Type @'\nusing System; using System.Runtime.InteropServices;\n"
        "public class D { [DllImport(\"user32.dll\")] public static extern bool EnumDisplayDevices(string a, uint b, ref DISPLAY_DEVICE c, uint d); "
        "[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Ansi)] public struct DISPLAY_DEVICE { public int cb; "
        "[MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string DeviceName; "
        "[MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceString; public int StateFlags; "
        "[MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceID; "
        "[MarshalAs(UnmanagedType.ByValTstr, SizeConst=128)] public string DeviceKey; } }\n'@ -ErrorAction SilentlyContinue; "
        "$dev = New-Object D+DISPLAY_DEVICE; $dev.cb = [System.Runtime.InteropServices.Marshal]::SizeOf($dev); "
        "$i=0; while ([D]::EnumDisplayDevices($null, $i, [ref]$dev, 0)) { "
        "if (($dev.StateFlags -band 1) -and ($dev.DeviceName -match '^\\\\.\\\\DISPLAY')) { "
        "$monitors += @{ name = $dev.DeviceName; friendly = $dev.DeviceString } }; $i++ }; "
        "$monitors | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            if isinstance(data, dict):
                data = [data]
            return [{"name": d.get("name", ""), "friendly": d.get("friendly", ""), "hdr_supported": True} for d in data]
    except (json.JSONDecodeError, subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def _set_hdr_windows(monitor: str, enabled: bool) -> Tuple[bool, str]:
    # Windows 11: ms-settings:display? HDR toggle is UI-only; use reg for Auto HDR global
    key = r"HKCU\Software\Microsoft\DirectX\UserGpuPreferences"
    value = "GpuPreference=2;" if enabled else "GpuPreference=0;"
    ps = (
        f"New-Item -Path 'HKCU:\\Software\\Microsoft\\DirectX\\UserGpuPreferences' -Force | Out-Null; "
        f"Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\DirectX\\UserGpuPreferences' "
        f"-Name 'DirectXUserGlobalSettings' -Value '{value}' -Type String -Force"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return True, f"Auto HDR preference {'on' if enabled else 'off'} (per-monitor HDR: use Settings → System → Display)"
        return False, (result.stderr or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def _list_hdr_linux() -> List[Dict[str, Any]]:
    outputs = []
    for cmd in (
        ["wlr-randr", "--json"],
        ["gamescope", "-h"],
    ):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                continue
            if cmd[0] == "wlr-randr" and result.stdout.strip().startswith("{"):
                data = json.loads(result.stdout)
                for name, info in data.items():
                    outputs.append({
                        "name": name,
                        "friendly": name,
                        "hdr_supported": bool(info.get("enabled") or info.get("make")),
                    })
                return outputs
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            continue
    return outputs


def _set_hdr_linux(output: str, enabled: bool) -> Tuple[bool, str]:
    if not output:
        return False, "no output name configured"
    for cmd in (
        ["wlr-randr", "--output", output, "--hdr", "enabled" if enabled else "disabled"],
        ["kscreen-doctor", f"output.{output}.hdr.enabled", "true" if enabled else "false"],
    ):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return True, f"HDR {'enabled' if enabled else 'disabled'} on {output}"
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            break
    return False, "install wlr-randr or configure gamescope HDR manually (Bazzite/HTPC)"


def _enable_spatial_windows(device_name: str, fmt: str) -> Tuple[bool, str]:
    # Best-effort via AudioDeviceCmdlets if present; otherwise instruct user
    ps = (
        f"$dev = Get-AudioDevice -List | Where-Object {{ $_.Name -like '*{device_name}*' }} | Select-Object -First 1; "
        "if (-not $dev) { 'NOTFOUND'; exit 1 }; "
        f"Set-AudioDevice -ID $dev.ID; "
        f"# Spatial: user may need Settings → Sound → {device_name} → Spatial sound"
        "'OK'"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if "NOTFOUND" in (result.stdout or ""):
            return False, f"device '{device_name}' not found — set default in Sound settings"
        if result.returncode == 0:
            label = "Dolby Atmos for Headphones" if fmt == "dolby" else "Windows Sonic"
            return True, f"Selected {device_name}; enable {label} in Sound → Spatial sound"
        return False, (result.stderr or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, f"Set '{device_name}' as default output, then enable spatial sound in Windows Settings"


def _enable_spatial_linux(device_name: str, fmt: str) -> Tuple[bool, str]:
    # PipeWire / PulseAudio — look for a sink matching device_name
    try:
        result = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return False, "pactl unavailable"
        sink = ""
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and device_name.lower() in parts[1].lower():
                sink = parts[0]
                break
        if not sink:
            return False, f"no sink matching '{device_name}'"
        subprocess.run(["pactl", "set-default-sink", sink], check=False, timeout=5)
        return True, f"default sink set to {device_name} (enable surround/HRIR in PipeWire if needed)"
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
