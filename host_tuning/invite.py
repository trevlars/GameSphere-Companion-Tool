"""Temporary GameSphere guest invites: mint token, inject PIN, unpair on host quit."""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from host_tuning.config import config_dir
from host_tuning import sunshine_admin

INVITE_TTL_SECONDS = 15 * 60


def _invites_path() -> str:
    return os.path.join(config_dir(), "invites.json")


def _load() -> Dict[str, Any]:
    path = _invites_path()
    if not os.path.isfile(path):
        return {"invites": []}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("invites"), list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"invites": []}


def _save(data: Dict[str, Any]) -> None:
    path = _invites_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _public_ip() -> str:
    try:
        from host_tuning import wan_setup

        ip = wan_setup.public_ip()
        if ip:
            return ip
    except Exception:
        pass
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=2.5) as resp:
            ip = resp.read().decode("utf-8", errors="replace").strip()
            if ip and len(ip) < 64:
                return ip
    except Exception:
        pass
    return ""


def _strip_host_port(raw: str) -> str:
    """Moonlight often sends host:47989 — bridge/JOINPIN need the IP only."""
    value = (raw or "").strip()
    if not value:
        return ""
    if value.startswith("[") and "]" in value:
        return value[1 : value.index("]")]
    if value.count(":") == 1:
        host, maybe_port = value.rsplit(":", 1)
        if maybe_port.isdigit():
            return host
    return value


def _is_private_ipv4(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return False
    if nums[0] == 10:
        return True
    if nums[0] == 192 and nums[1] == 168:
        return True
    if nums[0] == 172 and 16 <= nums[1] <= 31:
        return True
    return False


def _local_lan_ip() -> str:
    """Best-effort LAN IPv4 for same-network guest joins (skip Tailscale 100.x / CGNAT)."""
    candidates: List[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and _is_private_ipv4(ip):
                candidates.append(ip)
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
        if ip and not ip.startswith("127.") and _is_private_ipv4(ip):
            candidates.insert(0, ip)
    except OSError:
        pass
    # Prefer wired-style 10.x / 192.168 over Tailscale-ish ranges already filtered.
    for ip in candidates:
        if ip.startswith("10.") or ip.startswith("192.168."):
            return ip
    return candidates[0] if candidates else ""


def mint(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not sunshine_admin.has_credentials():
        return {
            "ok": False,
            "error": "missing_sunshine_credentials",
            "hint": "Set sunshine_username and sunshine_password in host_tuning.json (Sunshine web UI login).",
        }
    token = secrets.token_urlsafe(16)
    now = time.time()
    lan_host = _strip_host_port(str(payload.get("lanHost") or payload.get("host") or "").strip())
    if not lan_host or not _is_private_ipv4(lan_host):
        detected = _local_lan_ip()
        if detected:
            lan_host = detected
    https_port = int(payload.get("httpsPort") or 47984)
    app_id = str(payload.get("appId") or "")
    app_name = str(payload.get("appName") or "")
    host_id = str(payload.get("hostId") or "")
    wan_ready = False
    wan_status = ""
    zt_host = ""
    try:
        from host_tuning import wan_setup

        mapped = wan_setup.ensure(reason="invite")
        wan_host = str(mapped.get("wanHost") or "") or _public_ip()
        wan_ready = bool(mapped.get("wanReady"))
        wan_status = str(mapped.get("status") or "")
        zt_host = str(mapped.get("zerotierHost") or "")
    except Exception:
        wan_host = _public_ip()
    if not zt_host:
        try:
            from host_tuning import zerotier

            zt_host = str((zerotier.status() or {}).get("zerotierHost") or "")
        except Exception:
            zt_host = ""
    clients_before = [c["uuid"] for c in sunshine_admin.list_clients()]
    invite = {
        "token": token,
        "created": now,
        "expires": now + INVITE_TTL_SECONDS,
        "appId": app_id,
        "appName": app_name,
        "hostId": host_id,
        "lanHost": lan_host,
        "wanHost": wan_host,
        "httpsPort": https_port,
        "clientsBefore": clients_before,
        "guestUuids": [],
        "ended": False,
    }
    data = _load()
    invites: List[Dict[str, Any]] = [
        i for i in data.get("invites", []) if not i.get("ended") and i.get("expires", 0) > now
    ]
    invites.append(invite)
    data["invites"] = invites[-20:]
    _save(data)

    # Prefer LAN in host= so same-house iPads stream even if they ignore lan=.
    # Remote guests still get wan= for fallback. Never put only the public IP in host=
    # when a LAN address exists — hairpin NAT from LAN to public IP usually fails.
    join_host = lan_host or wan_host
    query = (
        f"token={token}&host={join_host}&httpsPort={https_port}"
        f"&appId={_q(app_id)}&hostId={_q(host_id)}&name={_q(app_name)}"
    )
    if lan_host:
        query += f"&lan={_q(lan_host)}"
    if wan_host:
        query += f"&wan={_q(wan_host)}"
    if zt_host:
        query += f"&zt={_q(zt_host)}"
    ident = {}
    try:
        from host_tuning import host_identity

        ident = host_identity.snapshot()
    except Exception:
        ident = {}
    logging.info(
        "INVITE minted lan=%s wan=%s zt=%s ready=%s app=%s",
        lan_host,
        wan_host,
        zt_host or "-",
        wan_ready,
        app_name,
    )
    return {
        "ok": True,
        "token": token,
        "expiresIn": INVITE_TTL_SECONDS,
        "lanHost": lan_host,
        "wanHost": wan_host,
        "zerotierHost": zt_host,
        "wanReady": wan_ready,
        "wanStatus": wan_status,
        "httpsPort": https_port,
        "joinURL": f"gamesphere://join?{query}",
        "hostSteamId": ident.get("hostSteamId") or "",
        "hostPersona": ident.get("hostPersona") or "",
        "hostAvatarUrl": ident.get("hostAvatarUrl") or "",
        "maxPlayers": 4,
    }


def _q(value: str) -> str:
    return quote(value or "", safe="")


def _wanna_play_pin_context(token: str) -> Optional[Dict[str, Any]]:
    """Wanna-play gamesphere://play?session= tokens are not stored in invites.json."""
    if not token:
        return None
    try:
        from host_tuning import wanna_play

        session = wanna_play.current_session()
        if not session or str(session.get("sessionId") or "") != token:
            return None
        expires = float(session.get("expires") or 0)
        if expires and time.time() > expires:
            return None
        return {
            "token": token,
            "expires": expires or (time.time() + INVITE_TTL_SECONDS),
            "clientsBefore": [c["uuid"] for c in sunshine_admin.list_clients()],
            "guestUuids": [],
            "ended": False,
            "wannaPlay": True,
        }
    except Exception as exc:
        logging.debug("wanna_play pin context: %s", exc)
        return None


def submit_pin(payload: Dict[str, Any]) -> Dict[str, Any]:
    token = str(payload.get("token") or "").strip()
    pin = str(payload.get("pin") or "").strip()
    name = str(payload.get("name") or "GameSphere Guest")
    invite = _find(token)
    wanna_play = False
    if not invite:
        invite = _wanna_play_pin_context(token)
        wanna_play = invite is not None
    if not invite:
        logging.info(
            "JOINPIN invite_not_found token=%s",
            token[:10] + "…" if len(token) > 10 else (token or "-"),
        )
        return {"ok": False, "error": "invite_not_found"}
    if invite.get("ended"):
        return {"ok": False, "error": "invite_ended"}
    if time.time() > float(invite.get("expires") or 0):
        return {"ok": False, "error": "invite_expired"}
    ok, message = sunshine_admin.submit_pin(pin, name)
    if not ok:
        return {"ok": False, "error": "pin_rejected", "detail": message}

    # Reply immediately after Sunshine accepts the PIN. Waiting ~3.2s for a new
    # client UUID made iOS JOINPIN (3s LAN timeout) fail while pairing still ran.
    if not wanna_play:
        before = set(invite.get("clientsBefore") or [])
        threading.Thread(
            target=_track_guest_uuid,
            args=(token, before),
            name="gs-invite-guest-uuid",
            daemon=True,
        ).start()
    return {"ok": True, "guestUuid": ""}


def _track_guest_uuid(token: str, before: set) -> None:
    for _ in range(12):
        time.sleep(0.4)
        invite = _find(token)
        if not invite or invite.get("ended"):
            return
        try:
            for client in sunshine_admin.list_clients():
                uuid = client.get("uuid") or ""
                if uuid and uuid not in before and uuid not in (invite.get("guestUuids") or []):
                    invite.setdefault("guestUuids", []).append(uuid)
                    _replace(invite)
                    return
        except Exception as exc:
            logging.debug("invite track guest: %s", exc)


def end_invite(token: str = "") -> Dict[str, Any]:
    from host_tuning import join_request as join_req

    trusted = set(join_req.trusted_uuids())
    data = _load()
    now = time.time()
    unpaired: List[str] = []
    skipped_trusted: List[str] = []
    remaining = []
    for invite in data.get("invites", []):
        match = (not token) or invite.get("token") == token
        if match or invite.get("expires", 0) < now:
            for uuid in invite.get("guestUuids") or []:
                if uuid in trusted:
                    skipped_trusted.append(uuid)
                    continue
                if sunshine_admin.unpair(uuid):
                    unpaired.append(uuid)
            invite["ended"] = True
        remaining.append(invite)
    data["invites"] = remaining[-20:]
    _save(data)
    return {"ok": True, "unpaired": unpaired, "keptTrusted": skipped_trusted}


def on_session_stop() -> None:
    """Host stream ended — clear Wanna-play session; keep invite tokens until TTL / INVITEEND.

    Ending every invite on Sunshine log stop made P2 JOINPIN fail with invite_not_found
    when the host shared a link then briefly stopped the stream (or Sunshine flickered).
    Explicit INVITEEND from the host app still unpairs guests and ends invites.
    """
    try:
        from host_tuning import wanna_play

        wanna_play.end_session()
    except Exception as exc:
        logging.debug("wanna_play on_session_stop: %s", exc)
    try:
        from host_tuning import couch_coop

        couch_coop.clear_stream_active()
    except Exception as exc:
        logging.debug("couch_coop clear_stream_active: %s", exc)
    try:
        from host_tuning import wan_setup

        wan_setup.on_session_stop()
    except Exception as exc:
        logging.debug("wan_setup on_session_stop: %s", exc)


def _find(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    for invite in _load().get("invites", []):
        if invite.get("token") == token:
            return invite
    return None


def _replace(updated: Dict[str, Any]) -> None:
    data = _load()
    invites = []
    for invite in data.get("invites", []):
        if invite.get("token") == updated.get("token"):
            invites.append(updated)
        else:
            invites.append(invite)
    data["invites"] = invites
    _save(data)
