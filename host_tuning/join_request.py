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

JOIN_TTL_SECONDS = 45
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
    lan_hint = guest_invite._strip_host_port(str(payload.get("lanHost") or "").strip())

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
        "lanHost": lan_hint or guest_invite._local_lan_ip(),
        "httpsPort": int(payload.get("httpsPort") or 47984),
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
            # One pending request per steam/friend name — replace older
            if (
                r.get("status") == "pending"
                and steam_id
                and r.get("steamId") == steam_id
            ):
                r["status"] = "expired"
                continue
            requests.append(r)
        requests.append(req)
        data["requests"] = requests[-30:]
        _save(data)
    logging.info("JOINREQ id=%s friend=%s app=%s", req_id, friend_name, app_name or app_id)
    return {"ok": True, "reqId": req_id, "expiresIn": JOIN_TTL_SECONDS}


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
                        "expiresIn": max(0, int(float(r.get("expires") or 0) - now)),
                    }
                )
        if changed:
            _save(data)
    return {"ok": True, "requests": out}


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
    now = time.time()
    with _lock:
        data = _load()
        found = None
        for r in data.get("requests", []):
            if r.get("reqId") == req_id:
                found = r
                break
        if not found:
            return {"ok": False, "error": "not_found"}
        if found.get("status") != "pending":
            return {"ok": False, "error": "already_" + str(found.get("status") or "done")}
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
        _save(data)
        result = {
            "ok": True,
            "reqId": req_id,
            "accept": accept,
            "status": found["status"],
            "appId": found.get("appId") or "",
            "appName": found.get("appName") or "",
            "lanHost": found.get("lanHost") or lan_host,
            "httpsPort": found.get("httpsPort") or https_port,
            "hostId": found.get("hostId") or host_id,
        }
    logging.info("JOINACK id=%s accept=%s", req_id, accept)
    if accept:
        try:
            from host_tuning import couch_coop

            couch_coop.on_join_accepted()
        except Exception:
            logging.exception("couch_coop after JOINACK")
    return result


def status(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Friend polls for Accept/Decline."""
    req_id = str(payload.get("reqId") or "").strip()
    if not req_id:
        return {"ok": False, "error": "missing_reqId"}
    now = time.time()
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
            return {
                "ok": True,
                "reqId": req_id,
                "status": st,
                "appId": r.get("appId") or "",
                "appName": r.get("appName") or "",
                "lanHost": r.get("lanHost") or "",
                "httpsPort": int(r.get("httpsPort") or 47984),
                "hostId": r.get("hostId") or "",
            }
    return {"ok": False, "error": "not_found", "status": "not_found"}
