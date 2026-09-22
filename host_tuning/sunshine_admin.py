"""Sunshine / Apollo web UI REST client (localhost). Used by guest invites."""

from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from host_tuning.config import load_config

_CTX = ssl._create_unverified_context()


def _base_url() -> str:
    cfg = load_config()
    url = (cfg.sunshine_web_url or "").strip().rstrip("/")
    return url or "https://127.0.0.1:47990"


def _creds() -> Tuple[str, str]:
    cfg = load_config()
    user = (
        os.environ.get("GAMESPHERE_SUNSHINE_USER")
        or cfg.sunshine_username
        or ""
    ).strip()
    password = (
        os.environ.get("GAMESPHERE_SUNSHINE_PASSWORD")
        or cfg.sunshine_password
        or ""
    )
    return user, password


def has_credentials() -> bool:
    user, password = _creds()
    return bool(user and password)


def _request(method: str, path: str, body: Optional[Dict[str, Any]] = None,
             timeout: int = 8) -> Tuple[int, Any]:
    user, password = _creds()
    if not user or not password:
        return 0, {"error": "missing_sunshine_credentials"}
    url = _base_url() + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        data = raw
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    password_mgr.add_password(None, _base_url(), user, password)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_CTX),
        urllib.request.HTTPBasicAuthHandler(password_mgr),
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                parsed = {"raw": payload}
            return getattr(resp, "status", 200), parsed
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            parsed = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed = {"raw": payload, "error": str(exc)}
        return exc.code, parsed
    except Exception as exc:
        logging.warning("Sunshine admin %s %s failed: %s", method, path, exc)
        return 0, {"error": str(exc)}


def pending_pairings() -> List[Dict[str, str]]:
    """Sunshine pending /pair requests. Newer builds require their id on POST /api/pin."""
    status, parsed = _request("GET", "/api/pin")
    if status != 200 or not isinstance(parsed, dict):
        return []
    rows = parsed.get("pairings")
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or "").strip()
        if pid:
            out.append({
                "id": pid,
                "name": str(row.get("name") or ""),
                "address": str(row.get("address") or ""),
            })
    return out


def _pick_pairing_id(name: str, address: str = "") -> str:
    rows = pending_pairings()
    if not rows:
        return ""
    if address:
        for row in rows:
            if row["address"] == address:
                return row["id"]
    if name:
        for row in rows:
            if row["name"] == name:
                return row["id"]
    # Sunshine appends new requests, so the newest pending pair is the joining guest.
    return rows[-1]["id"]


def submit_pin(pin: str, name: str = "GameSphere Guest", address: str = "") -> Tuple[bool, str]:
    pin = (pin or "").strip()
    if len(pin) != 4 or not pin.isdigit():
        return False, "pin_invalid"
    body = {"pin": pin, "name": name or "GameSphere Guest"}
    pairing_id = _pick_pairing_id(name or "", address or "")
    if pairing_id:
        body["pairing_id"] = pairing_id
    # Sunshine blocks this POST until the guest finishes the pair handshake.
    status, parsed = _request("POST", "/api/pin", body, timeout=25)
    if status in (200, 204) or (isinstance(parsed, dict) and parsed.get("status") in (True, "true", 1)):
        try:
            dedupe_named_devices()
        except Exception as exc:
            logging.debug("dedupe after pair failed: %s", exc)
        return True, "ok"
    message = ""
    if isinstance(parsed, dict):
        message = str(parsed.get("error") or parsed.get("status_message") or parsed.get("raw") or "")
    if not pairing_id:
        message = message or "no_pending_pairing"
    return False, message or "http_%s" % status


def _state_path() -> str:
    """Sunshine keeps paired client certs next to its log."""
    cfg = load_config()
    log_path = (getattr(cfg, "sunshine_log_path", "") or "").strip()
    if log_path:
        candidate = os.path.join(os.path.dirname(log_path), "sunshine_state.json")
        if os.path.exists(candidate):
            return candidate
    fallback = os.path.expanduser("~/.config/sunshine/sunshine_state.json")
    return fallback if os.path.exists(fallback) else ""


def dedupe_named_devices() -> int:
    """Unpair stale entries that duplicate another entry's certificate.

    Sunshine resolves a streaming client by certificate; two names holding the same
    cert make it reject the client outright. Keep the newest entry per cert.
    """
    path = _state_path()
    if not path:
        return 0
    try:
        with open(path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
        devices = (state.get("root") or {}).get("named_devices") or []
    except Exception as exc:
        logging.debug("dedupe_named_devices: cannot read %s: %s", path, exc)
        return 0
    if len(devices) < 2:
        return 0
    newest_for_cert: Dict[str, str] = {}
    for row in devices:
        if not isinstance(row, dict):
            continue
        cert = str(row.get("cert") or "")
        uuid = str(row.get("uuid") or "")
        if cert and uuid:
            newest_for_cert[cert] = uuid
    removed = 0
    for row in devices:
        if not isinstance(row, dict):
            continue
        cert = str(row.get("cert") or "")
        uuid = str(row.get("uuid") or "")
        if not cert or not uuid or newest_for_cert.get(cert) == uuid:
            continue
        if unpair(uuid):
            removed += 1
            logging.info(
                "Sunshine dropped duplicate client cert entry name=%s uuid=%s",
                row.get("name") or "-",
                uuid,
            )
    return removed


def list_clients() -> List[Dict[str, str]]:
    status, parsed = _request("GET", "/api/clients/list")
    if status != 200:
        return []
    rows = []
    if isinstance(parsed, dict):
        for key in ("named_certs", "named_devices", "clients", "devices"):
            value = parsed.get(key)
            if isinstance(value, list):
                rows = value
                break
        if not rows and isinstance(parsed.get("named_cert"), list):
            rows = parsed["named_cert"]
    elif isinstance(parsed, list):
        rows = parsed
    out: List[Dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        uuid = str(row.get("uuid") or row.get("id") or "").strip()
        name = str(row.get("name") or row.get("client_name") or "")
        if uuid:
            out.append({"uuid": uuid, "name": name})
    return out


def unpair(uuid: str) -> bool:
    uuid = (uuid or "").strip()
    if not uuid:
        return False
    status, parsed = _request("POST", "/api/clients/unpair", {"uuid": uuid})
    if status in (200, 204):
        return True
    if isinstance(parsed, dict) and parsed.get("status") in (True, "true", 1):
        return True
    logging.warning("Sunshine unpair %s failed status=%s body=%s", uuid, status, parsed)
    return False
