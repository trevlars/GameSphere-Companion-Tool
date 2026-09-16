"""Host-initiated 'Wanna play' — session-scoped pre-auth for trusted clients.

P1 pings already-paired / TRUSTED GameSphere devices. Those UUIDs are
auto-JOINACK'd for this Sunshine session only. A friend who was not pinged
still needs a normal Accept.

Does not permanently skip Accept. Stream stop / INVITEEND / WANNAPLAY end
clears the session.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from host_tuning.config import config_dir
from host_tuning import invite as guest_invite
from host_tuning import join_request

SESSION_TTL = 4 * 3600
_lock = threading.Lock()


def _path() -> str:
    return os.path.join(config_dir(), "wanna_play.json")


def _load() -> Dict[str, Any]:
    path = _path()
    if not os.path.isfile(path):
        return {"session": None, "devices": [], "pings": []}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data.setdefault("session", None)
            data.setdefault("devices", [])
            data.setdefault("pings", [])
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"session": None, "devices": [], "pings": []}


def _save(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _q(value: str) -> str:
    return quote(value or "", safe="")


def _play_url(
    session_id: str,
    app_id: str,
    app_name: str,
    host_id: str,
    lan: str,
    wan: str,
    https_port: int,
    zt: str = "",
) -> str:
    join_host = lan or wan
    query = (
        f"session={_q(session_id)}&preauth=1&token={_q(session_id)}"
        f"&host={_q(join_host)}&httpsPort={https_port}"
        f"&appId={_q(app_id)}&hostId={_q(host_id)}&name={_q(app_name)}"
    )
    if lan:
        query += f"&lan={_q(lan)}"
    if wan:
        query += f"&wan={_q(wan)}"
    if zt:
        query += f"&zt={_q(zt)}"
    return f"gamesphere://play?{query}"


def _identity() -> Dict[str, str]:
    try:
        from host_tuning import host_identity

        ident = host_identity.snapshot()
    except Exception:
        ident = {}
    return {
        "hostSteamId": ident.get("hostSteamId") or "",
        "hostPersona": ident.get("hostPersona") or "",
        "hostAvatarUrl": ident.get("hostAvatarUrl") or "",
    }


def _push_status() -> Dict[str, Any]:
    try:
        from host_tuning import apns

        return apns.status_public()
    except Exception:
        return {
            "pushReady": False,
            "pushStatus": (
                "Lock-screen Wanna play needs an APNs Auth Key (.p8) on this PC — "
                "friends still get the ping if GameSphere is open."
            ),
        }


def register_device(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Friend GameSphere registers so WANNAPLAY can ping this TRUSTED uuid."""
    uuid = str(payload.get("uuid") or payload.get("guestUuid") or "").strip()
    if not uuid:
        return {"ok": False, "error": "missing_uuid"}
    name = str(payload.get("name") or payload.get("clientName") or "GameSphere").strip()
    ntfy = str(payload.get("ntfyTopic") or payload.get("pushTopic") or "").strip()
    try:
        from host_tuning import apns

        token = apns.normalize_token(payload.get("apnsToken") or payload.get("deviceToken") or "")
        environment = apns.parse_environment(payload)
    except Exception:
        token = str(payload.get("apnsToken") or "").strip()
        environment = "development"
    now = time.time()
    with _lock:
        data = _load()
        devices: List[Dict[str, Any]] = []
        found = False
        for d in data.get("devices") or []:
            if d.get("uuid") == uuid:
                d["name"] = name or d.get("name")
                d["ntfyTopic"] = ntfy or d.get("ntfyTopic") or ""
                if token:
                    d["apnsToken"] = token
                    d["apnsEnvironment"] = environment
                d["lastSeen"] = now
                found = True
            devices.append(d)
        if not found:
            devices.append(
                {
                    "uuid": uuid,
                    "name": name,
                    "ntfyTopic": ntfy,
                    "apnsToken": token,
                    "apnsEnvironment": environment if token else "",
                    "lastSeen": now,
                }
            )
        data["devices"] = devices[-64:]
        _save(data)
    try:
        from host_tuning import device_profiles

        if any(payload.get(k) for k in ("name", "color", "avatarUrl", "avatarURL", "artworkKey", "steamId", "profileId")):
            device_profiles.upsert(payload)
    except Exception:
        logging.debug("PLAYREG profile upsert failed", exc_info=True)
    join_request.mark_trusted(uuid)
    return {"ok": True, "uuid": uuid, "apns": bool(token)}


def start(payload: Dict[str, Any]) -> Dict[str, Any]:
    """P1 Swap overlay — ping trusted/paired friends for this session only."""
    app_id = str(payload.get("appId") or "").strip()
    app_name = str(payload.get("appName") or payload.get("name") or "this game").strip() or "this game"
    host_id = str(payload.get("hostId") or "").strip()
    https_port = int(payload.get("httpsPort") or 47984)
    lan = guest_invite._strip_host_port(str(payload.get("lanHost") or "").strip()) or guest_invite._local_lan_ip()
    wan = ""
    wan_ready = False
    wan_status = ""
    zt_host = ""
    try:
        from host_tuning import wan_setup

        mapped = wan_setup.ensure(reason="wanna")
        wan = str(mapped.get("wanHost") or "")
        wan_ready = bool(mapped.get("wanReady"))
        wan_status = str(mapped.get("status") or "")
        zt_host = str(mapped.get("zerotierHost") or "")
    except Exception:
        pass
    wan = wan or guest_invite._public_ip()
    if not zt_host:
        try:
            from host_tuning import zerotier

            zt_host = str((zerotier.status() or {}).get("zerotierHost") or "")
        except Exception:
            zt_host = ""
    extra = payload.get("uuids") or payload.get("trustedUuids") or []
    wanted = [str(u).strip() for u in extra if str(u).strip()]
    trusted = list(join_request.trusted_uuids())
    for u in wanted:
        if u not in trusted:
            trusted.append(u)
    if not trusted:
        return {
            "ok": False,
            "error": "no_trusted_clients",
            "hint": "Friends must pair once and send TRUSTED / PLAYREG. One-shot invite strangers are not pinged.",
        }
    session_id = secrets.token_urlsafe(16)
    now = time.time()
    ident = _identity()
    persona = str(payload.get("hostPersona") or ident.get("hostPersona") or "Player 1").strip() or "Player 1"
    title = "Wanna play?"
    body = f"Want to play {app_name} with {persona}"
    play_url = _play_url(session_id, app_id, app_name, host_id, lan, wan, https_port, zt_host)
    cover = str(payload.get("coverUrl") or payload.get("coverURL") or payload.get("thumbnailUrl") or "").strip()
    if cover.startswith("file:"):
        cover = ""
    session = {
        "sessionId": session_id,
        "created": now,
        "expires": now + SESSION_TTL,
        "appId": app_id,
        "appName": app_name,
        "hostId": host_id,
        "lanHost": lan,
        "wanHost": wan,
        "httpsPort": https_port,
        "hostPersona": persona,
        "preauthUuids": trusted,
        "playURL": play_url,
        "coverUrl": cover,
        "title": title,
        "body": body,
    }
    pings = []
    with _lock:
        data = _load()
        devices = data.get("devices") or []
        for uuid in trusted:
            pings.append(
                {
                    "sessionId": session_id,
                    "uuid": uuid,
                    "created": now,
                    "expires": now + SESSION_TTL,
                    "consumed": False,
                }
            )
        data["session"] = session
        data["pings"] = pings
        _save(data)
    _notify_devices(devices, trusted, title, body, play_url, cover, session)
    logging.info("WANNAPLAY session=%s app=%s preauth=%s", session_id, app_name, len(trusted))
    push = _push_status()
    result = {
        "ok": True,
        "sessionId": session_id,
        "playURL": play_url,
        "title": title,
        "body": body,
        "coverUrl": cover,
        "preauthUuids": trusted,
        "expiresIn": SESSION_TTL,
        "lanHost": lan,
        "wanHost": wan,
        "wanReady": wan_ready,
        "wanStatus": wan_status,
        "pushReady": bool(push.get("pushReady")),
        "pushStatus": str(push.get("pushStatus") or ""),
        "httpsPort": https_port,
        "appId": app_id,
        "appName": app_name,
        "hostId": host_id,
        "hostPersona": persona,
        "maxPlayers": 4,
        **ident,
    }
    if not result["pushReady"] and result["pushStatus"]:
        # Same one-sentence pattern as wanStatus so overlay / CLI can show it.
        extra = result["pushStatus"]
        if wan_status and extra not in wan_status:
            result["wanStatus"] = f"{wan_status} {extra}".strip()
        elif not wan_status:
            result["wanStatus"] = extra
    return result


def _notify_devices(
    devices: List[Dict[str, Any]],
    uuids: List[str],
    title: str,
    body: str,
    play_url: str,
    cover_url: str = "",
    session: Optional[Dict[str, Any]] = None,
) -> None:
    session = session or {}
    try:
        from host_tuning import apns

        apns.notify_devices(
            devices,
            uuids,
            title=title,
            body=body,
            play_url=play_url,
            cover_url=cover_url,
            session_id=str(session.get("sessionId") or ""),
            app_id=str(session.get("appId") or ""),
            app_name=str(session.get("appName") or ""),
            host_persona=str(session.get("hostPersona") or ""),
            expires=int(float(session.get("expires") or 0)),
        )
    except Exception:
        logging.debug("wanna_play APNs failed", exc_info=True)
    topics = []
    by_uuid = {d.get("uuid"): d for d in devices if d.get("uuid")}
    for uuid in uuids:
        topic = (by_uuid.get(uuid) or {}).get("ntfyTopic") or ""
        if topic:
            topics.append(topic)
    for topic in topics:
        if not topic.replace("-", "").replace("_", "").isalnum():
            continue
        try:
            headers = {
                "Title": title,
                "Click": play_url,
                "Tags": "video_game",
            }
            if cover_url.startswith("http://") or cover_url.startswith("https://"):
                headers["Attach"] = cover_url
            req = urllib.request.Request(
                f"https://ntfy.sh/{topic}",
                data=body.encode("utf-8"),
                headers=headers,
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            logging.debug("wanna_play ntfy failed topic=%s", topic, exc_info=True)


def pending_for(uuid: str) -> Dict[str, Any]:
    uuid = (uuid or "").strip()
    now = time.time()
    ident = _identity()
    with _lock:
        data = _load()
        session = data.get("session") or {}
        if session and float(session.get("expires") or 0) < now:
            data["session"] = None
            data["pings"] = []
            _save(data)
            session = {}
        out = []
        for ping in data.get("pings") or []:
            if ping.get("consumed"):
                continue
            if float(ping.get("expires") or 0) < now:
                continue
            if uuid and ping.get("uuid") != uuid:
                continue
            if session.get("sessionId") and ping.get("sessionId") != session.get("sessionId"):
                continue
            out.append(
                {
                    "sessionId": ping.get("sessionId") or session.get("sessionId"),
                    "appId": session.get("appId") or "",
                    "appName": session.get("appName") or "",
                    "hostId": session.get("hostId") or "",
                    "lanHost": session.get("lanHost") or "",
                    "wanHost": session.get("wanHost") or "",
                    "httpsPort": int(session.get("httpsPort") or 47984),
                    "hostPersona": session.get("hostPersona") or ident.get("hostPersona") or "",
                    "hostSteamId": ident.get("hostSteamId") or "",
                    "hostAvatarUrl": ident.get("hostAvatarUrl") or "",
                    "playURL": session.get("playURL") or "",
                    "coverUrl": session.get("coverUrl") or "",
                    "title": session.get("title") or "Wanna play?",
                    "body": session.get("body") or "",
                    "preauth": True,
                    "maxPlayers": 4,
                }
            )
    return {"ok": True, "invites": out}


def claim(payload: Dict[str, Any]) -> Dict[str, Any]:
    uuid = str(payload.get("uuid") or payload.get("guestUuid") or "").strip()
    session_id = str(payload.get("sessionId") or payload.get("session") or payload.get("token") or "").strip()
    if not uuid:
        return {"ok": False, "error": "missing_uuid"}
    now = time.time()
    with _lock:
        data = _load()
        session = data.get("session") or {}
        if not session or float(session.get("expires") or 0) < now:
            return {"ok": False, "error": "no_session"}
        if session_id and session.get("sessionId") != session_id:
            return {"ok": False, "error": "wrong_session"}
        if uuid not in (session.get("preauthUuids") or []):
            return {"ok": False, "error": "not_preauthorized"}
        for ping in data.get("pings") or []:
            if ping.get("uuid") == uuid and ping.get("sessionId") == session.get("sessionId"):
                ping["consumed"] = True
        _save(data)
        result = {
            "ok": True,
            "preauth": True,
            "sessionId": session.get("sessionId"),
            "appId": session.get("appId") or "",
            "appName": session.get("appName") or "",
            "hostId": session.get("hostId") or "",
            "lanHost": session.get("lanHost") or "",
            "wanHost": session.get("wanHost") or "",
            "httpsPort": int(session.get("httpsPort") or 47984),
            "playURL": session.get("playURL") or "",
        }
    ident = _identity()
    result.update(ident)
    result["maxPlayers"] = 4
    return result


def is_preauthorized(uuid: str = "", session_id: str = "") -> bool:
    """True if this Moonlight uuid was pinged for the live WANNAPLAY session.

    session_id is required. Invite-path JOINREQ (no session=) must never auto-JOINACK —
    host Accept is mandatory. Session mismatch also refuses auto-accept.
    """
    uuid = (uuid or "").strip()
    session_id = (session_id or "").strip()
    if not uuid or not session_id:
        return False
    now = time.time()
    with _lock:
        session = (_load().get("session") or {})
        if not session or float(session.get("expires") or 0) < now:
            return False
        if uuid not in (session.get("preauthUuids") or []):
            return False
        live = str(session.get("sessionId") or "")
        if live and session_id != live:
            logging.info(
                "WANNAPLAY preauth uuid=%s session mismatch have=%s got=%s — require Accept",
                uuid,
                live,
                session_id,
            )
            return False
        return True


def current_session() -> Dict[str, Any]:
    now = time.time()
    with _lock:
        session = (_load().get("session") or {})
        if session and float(session.get("expires") or 0) >= now:
            return dict(session)
    return {}


def public_session() -> Optional[Dict[str, Any]]:
    session = current_session()
    if not session:
        return None
    return {
        "sessionId": session.get("sessionId") or "",
        "appId": session.get("appId") or "",
        "appName": session.get("appName") or "",
        "playURL": session.get("playURL") or "",
        "coverUrl": session.get("coverUrl") or "",
        "preauthUuids": session.get("preauthUuids") or [],
        "expiresIn": max(0, int(float(session.get("expires") or 0) - time.time())),
    }


def end_session() -> None:
    with _lock:
        data = _load()
        data["session"] = None
        data["pings"] = []
        _save(data)
    logging.info("WANNAPLAY session cleared")
