"""Owned Steam apps + ROM hashes for GameSphere library / achievements.

HOSTINFO carries a compact catalog so iOS can match RetroAchievements without a
Web API key on the host. ROM hashes follow the RetroAchievements MD5-of-file
convention for supported extensions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)
_CACHE: Dict[str, Any] = {"at": 0.0, "ownedApps": [], "romHashes": [], "ready": False}
_CACHE_TTL = 600.0
_lock = threading.Lock()
_scan_thread: Optional[threading.Thread] = None

_ROM_EXTS = (
    ".nes", ".sfc", ".smc", ".gb", ".gbc", ".gba", ".md", ".gen", ".sms", ".gg",
    ".n64", ".z64", ".v64", ".nds", ".3ds", ".cia", ".iso", ".cue", ".bin", ".chd",
    ".pce", ".zip",
)
_ROM_SCAN_ROOTS = (
    "~/Emulation/roms",
    "~/Games/roms",
    "~/.local/share/emulationstation-DE/downloaded_media",
    "~/.emulationstation-DE/roms",
    "~/ROMs",
    "~/roms",
)


def _steam_roots() -> List[str]:
    home = os.path.expanduser("~")
    return [
        os.path.join(home, ".local", "share", "Steam"),
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".steam", "root"),
        os.path.expanduser("~/.var/app/com.valvesoftware.Steam/data/Steam"),
    ]


def _parse_vdf_pairs(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in re.finditer(r'"([^"]+)"\s+"([^"]*)"', text):
        out[m.group(1).lower()] = m.group(2)
    return out


def owned_steam_apps(limit: int = 512) -> List[Dict[str, str]]:
    apps: List[Dict[str, str]] = []
    seen: set = set()
    for root in _steam_roots():
        steamapps = os.path.join(root, "steamapps")
        if not os.path.isdir(steamapps):
            continue
        for name in os.listdir(steamapps):
            if not name.startswith("appmanifest_") or not name.endswith(".acf"):
                continue
            path = os.path.join(steamapps, name)
            try:
                text = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            meta = _parse_vdf_pairs(text)
            app_id = meta.get("appid") or name.split("_")[1].split(".")[0]
            if not app_id or app_id in seen:
                continue
            seen.add(app_id)
            apps.append(
                {
                    "appId": app_id,
                    "name": meta.get("name") or "",
                    "store": "Steam",
                }
            )
            if len(apps) >= limit:
                return apps
    return apps


def _rom_hash(path: str) -> Optional[str]:
    try:
        size = os.path.getsize(path)
        if size <= 0 or size > 8 * 1024 * 1024 * 1024:
            return None
        h = hashlib.md5()
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest().upper()
    except OSError:
        return None


def scan_rom_hashes(limit: int = 256, max_bytes: int = 512 * 1024 * 1024) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen_hash: set = set()
    for root in _ROM_SCAN_ROOTS:
        base = os.path.expanduser(root)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                ext = os.path.splitext(name)[1].lower()
                if ext not in _ROM_EXTS:
                    continue
                path = os.path.join(dirpath, name)
                try:
                    if os.path.getsize(path) > max_bytes:
                        continue
                except OSError:
                    continue
                digest = _rom_hash(path)
                if not digest or digest in seen_hash:
                    continue
                seen_hash.add(digest)
                rows.append(
                    {
                        "hash": digest,
                        "name": name,
                        "path": path,
                        "system": os.path.basename(dirpath),
                    }
                )
                if len(rows) >= limit:
                    return rows
    return rows


def _stale(now: float) -> bool:
    return (now - float(_CACHE.get("at") or 0)) >= _CACHE_TTL


def snapshot(*, force: bool = False) -> Dict[str, Any]:
    """Blocking scan (CLI / doctor). Bridge callers should use :func:`cached`."""
    now = time.time()
    if not force and _CACHE.get("ready") and not _stale(now):
        return cached(kick=False)
    owned = owned_steam_apps()
    roms = scan_rom_hashes()
    with _lock:
        _CACHE["at"] = time.time()
        _CACHE["ownedApps"] = owned
        _CACHE["romHashes"] = roms
        _CACHE["ready"] = True
    _log.info("metadata_catalog owned=%d roms=%d", len(owned), len(roms))
    return cached(kick=False)


def _scan_worker() -> None:
    try:
        snapshot(force=True)
    except Exception:
        _log.debug("metadata_catalog background scan failed", exc_info=True)


def cached(*, kick: bool = True) -> Dict[str, Any]:
    """Return the cached catalog without blocking.

    ROM hashing can take minutes on a large library, so HOSTINFO must never wait
    on it. When the cache is empty or stale and ``kick`` is true, a single
    background scan is started; callers get the previous result immediately.
    """
    global _scan_thread
    now = time.time()
    with _lock:
        need = not _CACHE.get("ready") or _stale(now)
        out = {
            "ready": bool(_CACHE.get("ready")),
            "scannedAt": int(_CACHE.get("at") or 0),
            "ownedApps": list(_CACHE.get("ownedApps") or []),
            "romHashes": list(_CACHE.get("romHashes") or []),
        }
        if kick and need and not (_scan_thread and _scan_thread.is_alive()):
            _scan_thread = threading.Thread(
                target=_scan_worker, daemon=True, name="gamesphere-catalog-scan"
            )
            _scan_thread.start()
    return out
