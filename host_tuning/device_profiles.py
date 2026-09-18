"""Companion-side GameSphere device profiles.

uuid → {name, color, avatarUrl, artworkKey, steamId}. Live presence only —
not a public account server. iCloud owns the same Apple ID across that user's
devices; this file is the LAN/WAN relay guests use during a session.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from host_tuning.config import config_dir

_lock = threading.Lock()


def _path() -> str:
    return os.path.join(config_dir(), "device_profiles.json")


def _load() -> Dict[str, Any]:
    path = _path()
    if not os.path.isfile(path):
        return {"profiles": {}}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data.setdefault("profiles", {})
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"profiles": {}}


def _save(data: Dict[str, Any]) -> None:
    from host_tuning.json_store import write_json_atomic

    write_json_atomic(_path(), data)


def _public_row(row: Dict[str, Any], uuid: str) -> Dict[str, Any]:
    out = {
        "uuid": uuid,
        "profileId": str(row.get("profileId") or ""),
        "name": str(row.get("name") or ""),
        "color": str(row.get("color") or ""),
        "colorIndex": row.get("colorIndex") if row.get("colorIndex") is not None else 0,
        "avatarUrl": str(row.get("avatarUrl") or ""),
        "artworkKey": str(row.get("artworkKey") or ""),
        "steamId": str(row.get("steamId") or ""),
        "role": str(row.get("role") or ""),
    }
    return {k: v for k, v in out.items() if v or k in ("uuid", "name", "colorIndex")}


def upsert(payload: Dict[str, Any]) -> Dict[str, Any]:
    uuid = str(payload.get("uuid") or payload.get("guestUuid") or "").strip()
    if not uuid:
        return {"ok": False, "error": "missing_uuid"}
    now = time.time()
    with _lock:
        data = _load()
        profiles: Dict[str, Any] = data.get("profiles") or {}
        row = dict(profiles.get(uuid) or {})
        for key in ("profileId", "name", "color", "artworkKey", "steamId", "role"):
            val = payload.get(key) or payload.get("displayName" if key == "name" else key)
            if val is not None and str(val).strip():
                row[key] = str(val).strip()
        avatar = payload.get("avatarUrl") or payload.get("avatarURL")
        if avatar:
            row["avatarUrl"] = str(avatar).strip()
        if payload.get("colorIndex") is not None:
            try:
                row["colorIndex"] = int(payload.get("colorIndex"))
            except (TypeError, ValueError):
                pass
        row["updatedAt"] = now
        profiles[uuid] = row
        if len(profiles) > 64:
            oldest = sorted(profiles.items(), key=lambda kv: float((kv[1] or {}).get("updatedAt") or 0))
            for drop, _ in oldest[: max(0, len(profiles) - 64)]:
                profiles.pop(drop, None)
        data["profiles"] = profiles
        _save(data)
    return {"ok": True, "uuid": uuid, "profile": _public_row(row, uuid)}


def get(uuid: str) -> Dict[str, Any]:
    uuid = str(uuid or "").strip()
    if not uuid:
        return {"ok": False, "error": "missing_uuid"}
    with _lock:
        row = (_load().get("profiles") or {}).get(uuid)
    if not row:
        return {"ok": False, "error": "not_found", "uuid": uuid}
    return {"ok": True, "uuid": uuid, "profile": _public_row(row, uuid)}


def public_list() -> List[Dict[str, Any]]:
    with _lock:
        profiles = dict((_load().get("profiles") or {}))
    out = [_public_row(row, uuid) for uuid, row in profiles.items() if isinstance(row, dict)]
    return out[:32]


def host_profile() -> Optional[Dict[str, Any]]:
    rows = public_list()
    for row in rows:
        if str(row.get("role") or "").lower() == "host":
            return row
    return None


def handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    if payload.get("list"):
        return {"ok": True, "profiles": public_list(), "hostProfile": host_profile()}
    uuid = str(payload.get("uuid") or payload.get("guestUuid") or "").strip()
    mutating = any(
        payload.get(k)
        for k in ("name", "displayName", "color", "avatarUrl", "avatarURL", "artworkKey", "steamId", "profileId")
    )
    if mutating:
        result = upsert(payload)
        result["profiles"] = public_list()
        result["hostProfile"] = host_profile()
        return result
    if uuid:
        result = get(uuid)
        result["profiles"] = public_list()
        result["hostProfile"] = host_profile()
        return result
    return {"ok": True, "profiles": public_list(), "hostProfile": host_profile()}
