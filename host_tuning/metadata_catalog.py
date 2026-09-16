"""Owned Steam apps + ROM hashes for GameSphere library / achievements.

HOSTINFO carries a compact catalog so iOS can match RetroAchievements without a
Web API key on the host. ROM hashes follow the RetroAchievements MD5-of-file
convention for supported extensions (``raHashKind: md5`` — iOS may apply
normalized hashing for N64/NDS locally).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

_log = logging.getLogger(__name__)
_CACHE: Dict[str, Any] = {"at": 0.0, "ownedApps": [], "romHashes": [], "ready": False}
_FILE_HASHES: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = 600.0
_DISK_VERSION = 1
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


def _cache_path() -> str:
    from host_tuning.config import config_dir

    return os.path.join(config_dir(), "metadata_catalog_cache.json")


def _load_disk_cache() -> None:
    global _FILE_HASHES
    path = _cache_path()
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, TypeError):
        return
    if int(data.get("version") or 0) != _DISK_VERSION:
        return
    files = data.get("files")
    if isinstance(files, dict):
        _FILE_HASHES = {k: v for k, v in files.items() if isinstance(v, dict)}
    catalog = data.get("catalog")
    if isinstance(catalog, dict) and catalog.get("ready"):
        with _lock:
            _CACHE["at"] = float(catalog.get("at") or 0)
            _CACHE["ownedApps"] = list(catalog.get("ownedApps") or [])
            _CACHE["romHashes"] = list(catalog.get("romHashes") or [])
            _CACHE["ready"] = True


def _save_disk_cache() -> None:
    path = _cache_path()
    try:
        with _lock:
            payload = {
                "version": _DISK_VERSION,
                "files": dict(_FILE_HASHES),
                "catalog": {
                    "at": _CACHE.get("at") or 0,
                    "ready": bool(_CACHE.get("ready")),
                    "ownedApps": list(_CACHE.get("ownedApps") or []),
                    "romHashes": list(_CACHE.get("romHashes") or []),
                },
            }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
    except OSError:
        _log.debug("metadata_catalog disk cache write failed", exc_info=True)


_load_disk_cache()


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


def _file_fingerprint(path: str) -> Optional[Tuple[int, int]]:
    try:
        st = os.stat(path)
        return int(st.st_mtime_ns), int(st.st_size)
    except OSError:
        return None


def _compute_md5(path: str) -> Optional[str]:
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
        return h.hexdigest().lower()
    except OSError:
        return None


def _cached_ra_hash(path: str) -> Optional[str]:
    fp = _file_fingerprint(path)
    if not fp:
        return None
    mtime_ns, size = fp
    row = _FILE_HASHES.get(path)
    if row and row.get("mtime_ns") == mtime_ns and row.get("size") == size:
        cached = row.get("raHash")
        if isinstance(cached, str) and len(cached) == 32:
            return cached.lower()
    digest = _compute_md5(path)
    if not digest:
        return None
    _FILE_HASHES[path] = {"mtime_ns": mtime_ns, "size": size, "raHash": digest}
    return digest


def _rom_row(path: str, name: str, system: str) -> Optional[Dict[str, Any]]:
    ra = _cached_ra_hash(path)
    if not ra:
        return None
    return {
        "hash": ra.upper(),
        "raHash": ra,
        "raHashKind": "md5",
        "name": name,
        "path": path,
        "system": system,
    }


def _paths_from_command(text: str) -> List[str]:
    if not text:
        return []
    found: List[str] = []
    for m in re.finditer(r'"([^"]+)"|(\S+)', text):
        token = (m.group(1) or m.group(2) or "").strip()
        if not token or token.startswith("-") or "://" in token:
            continue
        token = os.path.expanduser(token)
        if os.path.isfile(token):
            found.append(token)
    return found


def _rom_paths_from_apps_json(limit: int = 128) -> List[Tuple[str, str, str]]:
    """(path, display_name, system_hint) from Sunshine apps.json launch lines."""
    try:
        from platform_paths import detect_paths

        detected = detect_paths()
        apps_path = detected.sunshine_apps_json if detected else ""
    except Exception:
        apps_path = ""
    if not apps_path or not os.path.isfile(apps_path):
        return []
    try:
        with open(apps_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    rows: List[Tuple[str, str, str]] = []
    seen: Set[str] = set()
    for app in data.get("apps") or []:
        name = (app.get("name") or "").strip() or os.path.basename(str(app.get("cmd") or ""))
        blob = " ".join([str(app.get("cmd") or ""), str(app.get("detached") or "")])
        for path in _paths_from_command(blob):
            ext = os.path.splitext(path)[1].lower()
            if ext not in _ROM_EXTS or path in seen:
                continue
            seen.add(path)
            system = os.path.basename(os.path.dirname(path))
            rows.append((path, name, system))
            if len(rows) >= limit:
                return rows
    return rows


def scan_rom_hashes(limit: int = 256, max_bytes: int = 512 * 1024 * 1024) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen_hash: set = set()
    seen_path: set = set()

    def _add(path: str, name: str, system: str) -> bool:
        """Return True when the scan should stop (limit reached)."""
        if path in seen_path:
            return False
        try:
            if os.path.getsize(path) > max_bytes:
                return False
        except OSError:
            return False
        entry = _rom_row(path, name, system)
        if not entry:
            return False
        digest = entry["raHash"]
        seen_path.add(path)
        if digest in seen_hash:
            return False
        seen_hash.add(digest)
        rows.append(entry)
        return len(rows) >= limit

    for path, name, system in _rom_paths_from_apps_json(limit=limit):
        if _add(path, name, system):
            return rows

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
                if _add(path, name, os.path.basename(dirpath)):
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
    _save_disk_cache()
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
