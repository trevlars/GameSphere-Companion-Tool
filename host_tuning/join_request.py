"""Trusted-friend join requests: JOINREQ / JOINPENDING / JOINACK / JOINSTATUS.

LAN rendezvous so a paired friend can ask the streaming host to Accept/Decline
without minting a one-shot invite token each time.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from host_tuning.config import config_dir
from host_tuning import invite as guest_invite

JOIN_TTL_SECONDS = 120
_lock = threading.Lock()


def _path() -> str:
    return os.path.join(config_dir(), "join_requests.json")


def _trusted_path() -> str:
    return os.path.join(config_dir(), "trusted_clients.json")


def _load() -> Dict[str, Any]:
    path = _path()
    if not os.path.isfile(path):
        return {"requests": []}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("requests"), list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"requests": []}


def _save(data: Dict[str, Any]) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _load_trusted() -> List[str]:
    path = _trusted_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("uuids"), list):
            return [str(u) for u in data["uuids"] if u]
        if isinstance(data, list):
            return [str(u) for u in data if u]
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _save_trusted(uuids: List[str]) -> None:
    path = _trusted_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Dedupe, keep recent
    seen = []
    for u in uuids:
        if u and u not in seen:
            seen.append(u)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"uuids": seen[-64:]}, fh, indent=2)


def mark_trusted(uuid: str) -> Dict[str, Any]:
    uuid = (uuid or "").strip()
    if not uuid:
        return {"ok": False, "error": "missing_uuid"}
    with _lock:
        uuids = _load_trusted()
        if uuid not in uuids:
            uuids.append(uuid)
            _save_trusted(uuids)
    return {"ok": True, "uuid": uuid}


def is_trusted(uuid: str) -> bool:
    if not uuid:
        return False
    return uuid in _load_trusted()


def trusted_uuids() -> List[str]:
    return _load_trusted()


def _should_auto_joinack(payload: Dict[str, Any], client_uuid: str, session_id: str) -> bool:
    """Wanna-play preauth, or a fresh gamesphere://join invite token within TTL."""
    try:
        from host_tuning import wanna_play

        if wanna_play.is_preauthorized(uuid=client_uuid, session_id=session_id):
            return True
    except Exception:
        logging.exception("JOINREQ wanna_play preauth check")
    invite_token = str(
        payload.get("token") or payload.get("inviteToken") or session_id or ""
    ).strip()
    if invite_token and guest_invite.is_active_invite_token(invite_token):
        logging.info("JOINREQ invite auto-accept token=%s", invite_token[:10] + "…" if len(invite_token) > 10 else invite_token)
        return True
    return False


def create(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Friend posts a join request. Host polls JOINPENDING."""
    now = time.time()
    req_id = secrets.token_urlsafe(10).replace("-", "")[:14]
    friend_name = str(payload.get("friendName") or payload.get("name") or "Friend").strip() or "Friend"
    steam_id = str(payload.get("steamId") or "").strip()
    app_id = str(payload.get("appId") or "").strip()
    app_name = str(payload.get("appName") or "").strip()
    client_name = str(payload.get("clientName") or "").strip()
    host_id = str(payload.get("hostId") or "").strip()
    client_uuid = str(payload.get("uuid") or payload.get("guestUuid") or "").strip()
    session_id = str(payload.get("sessionId") or payload.get("session") or payload.get("token") or "").strip()
    lan_hint = guest_invite._strip_host_port(str(payload.get("lanHost") or "").strip())
    role = str(payload.get("role") or "guest").strip().lower()
    if role not in ("guest", "buddy"):
        role = "guest"

    req = {
        "reqId": req_id,
        "created": now,
        "expires": now + JOIN_TTL_SECONDS,
        "friendName": friend_name,
        "steamId": steam_id,
        "appId": app_id,
        "appName": app_name,
        "clientName": client_name,
        "hostId": host_id,
        "uuid": client_uuid,
        "sessionId": session_id,
        "lanHost": lan_hint or guest_invite._local_lan_ip(),
        "httpsPort": int(payload.get("httpsPort") or 47984),
        "role": role,  # guest (own P2–P4 pad) | buddy (shares host P1 via buddy_relay)
        "status": "pending",  # pending | accepted | declined | expired
    }
    with _lock:
        data = _load()
        requests: List[Dict[str, Any]] = []
        for r in data.get("requests", []):
            if float(r.get("expires") or 0) < now:
                if r.get("status") == "pending":
                    r["status"] = "expired"
                continue
            # One pending request per steam id or Moonlight uuid — replace older
            if r.get("status") == "pending" and (
                (steam_id and r.get("steamId") == steam_id)
                or (client_uuid and r.get("uuid") == client_uuid)
            ):
                r["status"] = "expired"
                continue
            requests.append(r)
        requests.append(req)
        data["requests"] = requests[-30:]
        _save(data)
    logging.info(
        "JOINREQ id=%s friend=%s app=%s uuid=%s session=%s",
        req_id,
        friend_name,
        app_name or app_id,
        client_uuid or "-",
        session_id or "-",
    )
    try:
        if _should_auto_joinack(payload, client_uuid, session_id):
            auto = ack(
                {
                    "reqId": req_id,
                    "accept": True,
                    "appId": app_id,
                    "appName": app_name,
                    "httpsPort": req["httpsPort"],
                    "hostId": host_id,
                    "lanHost": req["lanHost"],
                }
            )
            if not auto.get("ok"):
                # Host Accept raced auto-JOINACK — still a grant, not a reject.
                st = status({"reqId": req_id})
                if str(st.get("status") or "") == "accepted":
                    auto = dict(st)
                    auto["ok"] = True
                    auto["accept"] = True
            if auto.get("ok") and str(auto.get("status") or "") == "accepted":
                auto["preauth"] = True
                auto["reqId"] = req_id
                logging.info(
                    "JOINREQ auto-JOINACK id=%s uuid=%s ok=%s status=%s",
                    req_id,
                    client_uuid,
                    auto.get("ok"),
                    auto.get("status"),
                )
                return auto
            logging.warning(
                "JOINREQ auto-JOINACK incomplete id=%s err=%s status=%s — leaving pending",
                req_id,
                auto.get("error"),
                auto.get("status"),
            )
    except Exception:
        logging.exception("JOINREQ preauth check")
    return {"ok": True, "reqId": req_id, "expiresIn": JOIN_TTL_SECONDS, "preauth": False}


def pending() -> Dict[str, Any]:
    """Host polls while streaming."""
    now = time.time()
    out: List[Dict[str, Any]] = []
    with _lock:
        data = _load()
        changed = False
        for r in data.get("requests", []):
            if r.get("status") == "pending" and float(r.get("expires") or 0) < now:
                r["status"] = "expired"
                changed = True
            if r.get("status") == "pending":
                out.append(
                    {
                        "reqId": r.get("reqId"),
                        "friendName": r.get("friendName"),
                        "steamId": r.get("steamId"),
                        "appId": r.get("appId"),
                        "appName": r.get("appName"),
                        "clientName": r.get("clientName"),
                        "role": r.get("role") or "guest",
                        "expiresIn": max(0, int(float(r.get("expires") or 0) - now)),
                    }
                )
        if changed:
            _save(data)
    return {"ok": True, "requests": out}


def _identity_fields() -> Dict[str, Any]:
    """Cache-only — JOINREQ/JOINACK must return before STUN / Steam XML / pad sync."""
    ident: Dict[str, Any] = {}
    try:
        from host_tuning import host_identity

        ident = host_identity.cached_snapshot() or {}
    except Exception:
        ident = {}
    lan = guest_invite._local_lan_ip()
    wan = ""
    try:
        from host_tuning import wan_setup

        hosts = wan_setup.cached_hosts()
        wan = str(hosts.get("wanHost") or "")
        lan = str(hosts.get("lanHost") or "") or lan
    except Exception:
        pass
    zt = ""
    try:
        from host_tuning import wan_setup

        zt = str((wan_setup.cached_hosts() or {}).get("zerotierHost") or "")
    except Exception:
        zt = ""
    return {
        "hostSteamId": ident.get("hostSteamId") or "",
        "hostPersona": ident.get("hostPersona") or "",
        "hostAvatarUrl": ident.get("hostAvatarUrl") or "",
        "wanHost": wan,
        "lanHost": lan,
        "zerotierHost": zt,
        "maxPlayers": 4,
    }


def _schedule_couch_coop(req_id: str, name: str, role: str = "guest", uuid: str = "") -> None:
    def _run() -> None:
        try:
            from host_tuning import couch_coop

            couch_coop.on_join_accepted(client_id=req_id, name=name, role=role, uuid=uuid)
        except Exception:
            logging.exception("couch_coop after JOINACK")

    threading.Thread(target=_run, daemon=True, name="gs-joinack-coop").start()


def _ack_payload_from_row(row: Dict[str, Any], *, accept: bool, ident: Dict[str, Any]) -> Dict[str, Any]:
    lan = str(row.get("lanHost") or ident.get("lanHost") or "")
    result = {
        "ok": True,
        "reqId": row.get("reqId") or "",
        "accept": accept,
        "status": row.get("status") or ("accepted" if accept else "declined"),
        "appId": row.get("appId") or "",
        "appName": row.get("appName") or "",
        "lanHost": lan,
        "httpsPort": int(row.get("httpsPort") or 47984),
        "hostId": row.get("hostId") or "",
        "playerSlot": int(row.get("playerSlot") or 0),
        "role": row.get("role") or "guest",
        "friendName": row.get("friendName") or "",
        "wanHost": ident.get("wanHost") or "",
        "zerotierHost": ident.get("zerotierHost") or "",
        "maxPlayers": 4,
        "hostSteamId": ident.get("hostSteamId") or "",
        "hostPersona": ident.get("hostPersona") or "",
        "hostAvatarUrl": ident.get("hostAvatarUrl") or "",
    }
    return result


def ack(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Host Accept/Decline."""
    req_id = str(payload.get("reqId") or "").strip()
    accept = bool(payload.get("accept"))
    app_id = str(payload.get("appId") or "").strip()
    app_name = str(payload.get("appName") or "").strip()
    https_port = int(payload.get("httpsPort") or 47984)
    host_id = str(payload.get("hostId") or "").strip()
    lan_host = guest_invite._strip_host_port(str(payload.get("lanHost") or "").strip())
    if not lan_host:
        lan_host = guest_invite._local_lan_ip()
    if not req_id:
        return {"ok": False, "error": "missing_reqId"}
    role_override = str(payload.get("role") or "").strip().lower()
    if role_override not in ("guest", "buddy"):
        role_override = ""
    now = time.time()
    ident = _identity_fields()
    schedule_coop = False
    coop_name = "Guest"
    coop_role = "guest"
    coop_uuid = ""
    with _lock:
        data = _load()
        found = None
        for r in data.get("requests", []):
            if r.get("reqId") == req_id:
                found = r
                break
        if not found:
            return {"ok": False, "error": "not_found"}
        current = str(found.get("status") or "pending")
        if current != "pending":
            if accept and current == "accepted":
                # Idempotent Accept / auto-JOINACK race with host JOINACK.
                logging.info("JOINACK id=%s already accepted — returning grant", req_id)
                return _ack_payload_from_row(found, accept=True, ident=ident)
            return {"ok": False, "error": "already_" + current}
        if float(found.get("expires") or 0) < now:
            found["status"] = "expired"
            _save(data)
            return {"ok": False, "error": "expired"}
        found["status"] = "accepted" if accept else "declined"
        if accept:
            if app_id:
                found["appId"] = app_id
            if app_name:
                found["appName"] = app_name
            found["httpsPort"] = https_port
            if host_id:
                found["hostId"] = host_id
            if lan_host:
                found["lanHost"] = lan_host
            # Give friend a bit more time to poll + resume
            found["expires"] = now + JOIN_TTL_SECONDS
            try:
                from host_tuning import couch_coop

                found["playerSlot"] = couch_coop.next_empty_slot()
            except Exception:
                found["playerSlot"] = 1
            # Host decides the seat kind at Accept time ("Player 2" vs "Buddy"); falls back to what the guest asked for.
            if role_override:
                found["role"] = role_override
            found.setdefault("role", "guest")
            schedule_coop = True
            coop_name = str(found.get("friendName") or found.get("clientName") or "Guest")
            coop_role = str(found.get("role") or "guest")
            coop_uuid = str(found.get("uuid") or "")
        _save(data)
        result = _ack_payload_from_row(found, accept=accept, ident=ident)
    logging.info("JOINACK id=%s accept=%s role=%s", req_id, accept, coop_role)
    if schedule_coop:
        _schedule_couch_coop(req_id, coop_name, coop_role, coop_uuid)
    return result


def expire_for_uuid(uuid: str) -> int:
    """Host kick: drop pending join requests from a guest uuid."""
    uuid = (uuid or "").strip()
    if not uuid:
        return 0
    count = 0
    with _lock:
        data = _load()
        for row in data.get("requests") or []:
            if row.get("status") != "pending":
                continue
            if str(row.get("uuid") or row.get("guestUuid") or "") != uuid:
                continue
            row["status"] = "expired"
            row["reason"] = "kicked"
            count += 1
        if count:
            _save(data)
    return count


def status(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Friend polls for Accept/Decline."""
    req_id = str(payload.get("reqId") or "").strip()
    if not req_id:
        return {"ok": False, "error": "missing_reqId"}
    now = time.time()
    row = None
    st_out = ""
    with _lock:
        data = _load()
        for r in data.get("requests", []):
            if r.get("reqId") != req_id:
                continue
            st = r.get("status") or "pending"
            if st == "pending" and float(r.get("expires") or 0) < now:
                r["status"] = "expired"
                st = "expired"
                _save(data)
            row = dict(r)
            st_out = st
            break
    if not row:
        return {"ok": False, "error": "not_found", "status": "not_found"}
    ident = _identity_fields()
    return {
        "ok": True,
        "reqId": req_id,
        "status": st_out,
        "appId": row.get("appId") or "",
        "appName": row.get("appName") or "",
        "lanHost": row.get("lanHost") or ident.get("lanHost") or "",
        "wanHost": ident.get("wanHost") or "",
        "zerotierHost": ident.get("zerotierHost") or "",
        "httpsPort": int(row.get("httpsPort") or 47984),
        "hostId": row.get("hostId") or "",
        "playerSlot": int(row.get("playerSlot") or 0),
        "role": row.get("role") or "guest",
        "maxPlayers": 4,
        "hostSteamId": ident.get("hostSteamId") or "",
        "hostPersona": ident.get("hostPersona") or "",
        "hostAvatarUrl": ident.get("hostAvatarUrl") or "",
    }
