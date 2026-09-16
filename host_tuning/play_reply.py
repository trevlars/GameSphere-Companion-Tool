"""Guest PLAYREPLY echo for P1 COOPSTATE bubbles.

Guests tap I'm in / You're going down / Can't right now. Companion keeps a
short TTL ring and attaches it to COOPSTATE as coopChat[] / playReplies[] /
playReply so P1 StreamFrame can draw bubbles. Does not touch pre-auth, seats,
WAN, or APNs.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

TTL_SEC = 30.0
MAX_REPLIES = 8
PHRASE_MAX = 80
PERSONA_MAX = 64

_lock = threading.Lock()
_replies: List[Dict[str, Any]] = []


def reset() -> None:
    with _lock:
        _replies.clear()


def _prune_locked(now: float) -> None:
    keep: List[Dict[str, Any]] = []
    for row in _replies:
        if float(row.get("expires") or 0) >= now:
            keep.append(row)
    _replies[:] = keep[-MAX_REPLIES:]


def _public(row: Dict[str, Any]) -> Dict[str, Any]:
    mid = str(row.get("id") or "")
    out: Dict[str, Any] = {
        "id": mid,
        "messageId": mid,
        "phrase": str(row.get("phrase") or ""),
        "accepted": bool(row.get("accepted")),
        "uuid": str(row.get("uuid") or ""),
        "sessionId": str(row.get("sessionId") or ""),
        "persona": str(row.get("persona") or ""),
        "name": str(row.get("persona") or ""),
        "avatarUrl": str(row.get("avatarUrl") or ""),
    }
    return out


def _safe_avatar(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("https://") or url.startswith("http://"):
        return url[:512]
    return ""


def record(payload: Dict[str, Any]) -> Dict[str, Any]:
    phrase = str(payload.get("phrase") or payload.get("text") or "").strip()
    if not phrase:
        return {"ok": False, "error": "missing_phrase"}
    phrase = phrase[:PHRASE_MAX]
    accepted = payload.get("accepted")
    if accepted is None:
        declined = payload.get("declined")
        accepted = not bool(declined) if declined is not None else True
    elif isinstance(accepted, str):
        accepted = accepted.strip().lower() in ("1", "true", "yes")
    else:
        accepted = bool(accepted)
    uuid = str(payload.get("uuid") or payload.get("guestUuid") or payload.get("clientId") or "").strip()
    session_id = str(
        payload.get("sessionId") or payload.get("session") or payload.get("token") or ""
    ).strip()
    persona = str(
        payload.get("persona")
        or payload.get("name")
        or payload.get("guestName")
        or payload.get("guestPersona")
        or ""
    ).strip()[:PERSONA_MAX]
    avatar = _safe_avatar(
        str(
            payload.get("avatarUrl")
            or payload.get("avatarURL")
            or payload.get("hostAvatarUrl")
            or payload.get("guestAvatar")
            or ""
        )
    )
    now = time.time()
    with _lock:
        _prune_locked(now)
        existing: Optional[Dict[str, Any]] = None
        for row in _replies:
            if row.get("uuid") == uuid and row.get("sessionId") == session_id and row.get("phrase") == phrase:
                existing = row
                break
        if existing:
            existing["accepted"] = accepted
            existing["persona"] = persona or existing.get("persona") or ""
            if avatar:
                existing["avatarUrl"] = avatar
            existing["expires"] = now + TTL_SEC
            existing["ts"] = now
            _replies.remove(existing)
            _replies.append(existing)
            row = existing
        else:
            row = {
                "id": secrets.token_hex(8),
                "uuid": uuid,
                "sessionId": session_id,
                "phrase": phrase,
                "accepted": accepted,
                "persona": persona,
                "avatarUrl": avatar,
                "ts": now,
                "expires": now + TTL_SEC,
            }
            _replies.append(row)
            _prune_locked(now)
    logging.info(
        "PLAYREPLY accepted=%s phrase=%s uuid=%s",
        accepted,
        phrase,
        (uuid[:8] + "…") if len(uuid) > 8 else uuid,
    )
    return {"ok": True, **_public(row)}


def recent() -> List[Dict[str, Any]]:
    now = time.time()
    with _lock:
        _prune_locked(now)
        return [_public(row) for row in _replies]


def coopstate_fields() -> Dict[str, Any]:
    rows = recent()
    last = rows[-1] if rows else None
    return {
        "coopChat": rows,
        "playReplies": rows,
        "playReply": last,
        "lastReply": last,
    }
