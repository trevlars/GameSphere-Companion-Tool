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


def _request(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Any]:
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
        with opener.open(req, timeout=8) as resp:
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


def submit_pin(pin: str, name: str = "GameSphere Guest") -> Tuple[bool, str]:
    pin = (pin or "").strip()
    if len(pin) != 4 or not pin.isdigit():
        return False, "pin_invalid"
    status, parsed = _request("POST", "/api/pin", {"pin": pin, "name": name or "GameSphere Guest"})
    if status in (200, 204) or (isinstance(parsed, dict) and parsed.get("status") in (True, "true", 1)):
        return True, "ok"
    message = ""
    if isinstance(parsed, dict):
        message = str(parsed.get("error") or parsed.get("status_message") or parsed.get("raw") or "")
    return False, message or f"http_{status}"


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
