"""NVIDIA driver profile snapshot / restore (best-effort, Windows + Linux)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from host_tuning.config import config_dir


def snapshot_dir() -> str:
    path = os.path.join(config_dir(), "nvidia")
    os.makedirs(path, exist_ok=True)
    return path


def capture_snapshot() -> Tuple[bool, str, Optional[str]]:
    """Return (ok, message, snapshot_path)."""
    if os.name == "nt":
        return _capture_windows()
    return _capture_linux()


def restore_snapshot(path: Optional[str] = None) -> Tuple[bool, str]:
    snap = path or _latest_snapshot()
    if not snap:
        return False, "no snapshot found"
    if os.name == "nt":
        return _restore_windows(snap)
    return _restore_linux(snap)


def driver_info() -> Dict[str, Any]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version,name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            return {"driver_version": parts[0] if parts else "", "gpu_name": parts[1] if len(parts) > 1 else ""}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return {}


def _latest_snapshot() -> Optional[str]:
    folder = snapshot_dir()
    files = sorted(
        [os.path.join(folder, f) for f in os.listdir(folder) if f.startswith("snapshot_")],
        reverse=True,
    )
    return files[0] if files else None


def _capture_windows() -> Tuple[bool, str, Optional[str]]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = os.path.join(snapshot_dir(), f"snapshot_{ts}.json")
    meta = {"platform": "windows", "driver": driver_info(), "profiles": {}}

    # NVIDIA Profile Inspector CLI if installed
    for exe in (
        os.path.join(os.environ.get("ProgramFiles", ""), "NVIDIA Corporation", "NVIDIA Profile Inspector", "nvidiaProfileInspector.exe"),
        shutil.which("nvidiaProfileInspector") or "",
    ):
        if exe and os.path.isfile(exe):
            nip = out.replace(".json", ".nip")
            try:
                subprocess.run([exe, "/export", nip], capture_output=True, timeout=60, check=False)
                if os.path.isfile(nip):
                    meta["nip_path"] = nip
                    break
            except (subprocess.TimeoutExpired, OSError):
                pass

    # Fallback: nvidia-smi -q subset
    try:
        result = subprocess.run(["nvidia-smi", "-q", "-d", "COMPUTE,UTILIZATION"], capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            meta["nvidia_smi_q"] = result.stdout[:8000]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    with open(out, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return True, f"saved {out}", out


def _restore_windows(path: str) -> Tuple[bool, str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False, "invalid snapshot"
    nip = meta.get("nip_path")
    if nip and os.path.isfile(nip):
        for exe in (shutil.which("nvidiaProfileInspector") or "",):
            if exe:
                subprocess.run([exe, "/import", nip], capture_output=True, timeout=60, check=False)
                return True, f"imported {nip}"
    return False, "install NVIDIA Profile Inspector for full profile restore; snapshot metadata only"


def _capture_linux() -> Tuple[bool, str, Optional[str]]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = os.path.join(snapshot_dir(), f"snapshot_{ts}.txt")
    try:
        result = subprocess.run(
            ["nvidia-settings", "-q", "all"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False, "nvidia-settings not available", None
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(result.stdout)
        meta_path = out.replace(".txt", ".json")
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump({"platform": "linux", "query_dump": out, "driver": driver_info()}, fh, indent=2)
        return True, f"saved {out}", meta_path
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc), None


def _restore_linux(path: str) -> Tuple[bool, str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        dump = meta.get("query_dump")
        if dump and os.path.isfile(dump):
            return True, f"snapshot at {dump} — re-apply manually with nvidia-settings (full auto-restore not supported on Linux)"
    except (OSError, json.JSONDecodeError):
        pass
    return False, "no Linux snapshot to restore"
