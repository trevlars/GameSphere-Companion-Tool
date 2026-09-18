"""Host Steam identity for guest avatars — no Web API key required.

Reads the MostRecent Steam login from loginusers.vdf, then the public
community XML for persona + avatar URL so guests do not need the host's
Steam session.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
from typing import Any, Dict, Optional
from xml.etree import ElementTree

STEAMID64_BASE = 76561197960265728
_CACHE_TTL = 300.0
_cache: Dict[str, Any] = {"at": 0.0, "payload": {}}


def _steam_roots() -> list:
    home = os.path.expanduser("~")
    return [
        os.path.join(home, ".local", "share", "Steam"),
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".steam", "root"),
        os.path.expanduser("~/.var/app/com.valvesoftware.Steam/data/Steam"),
    ]


def account_id_to_steamid64(account_id: str) -> str:
    try:
        aid = int(str(account_id).strip())
    except (TypeError, ValueError):
        return ""
    if aid <= 0:
        return ""
    if aid > STEAMID64_BASE:
        return str(aid)
    return str(STEAMID64_BASE + aid)


def _vdf_most_recent_steamid64(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""
    # loginusers.vdf: "7656…" { "MostRecent" "1" }
    blocks = re.findall(r'"(\d{16,20})"\s*\{([^}]*)\}', text, re.S)
    most = ""
    fallback = ""
    for sid, body in blocks:
        fallback = fallback or sid
        if re.search(r'"MostRecent"\s+"1"', body, re.I):
            most = sid
            break
    return most or fallback


def _active_account_id() -> str:
    helper = os.path.expanduser("~/.local/bin/get-active-steam-user.sh")
    if os.path.isfile(helper) and os.access(helper, os.X_OK):
        try:
            import subprocess

            out = subprocess.check_output([helper], text=True, timeout=3)
            for line in out.splitlines():
                if line.startswith("account_id="):
                    return line.split("=", 1)[1].strip()
        except (OSError, Exception):
            pass
    return ""


def steamid64() -> str:
    aid = _active_account_id()
    sid = account_id_to_steamid64(aid)
    if sid:
        return sid
    for root in _steam_roots():
        path = os.path.join(root, "config", "loginusers.vdf")
        sid = _vdf_most_recent_steamid64(path)
        if sid:
            return sid
    return ""


def _community_profile(sid: str) -> Dict[str, str]:
    url = f"https://steamcommunity.com/profiles/{sid}/?xml=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GameSphere-Companion/1.4"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            xml = resp.read()
    except Exception:
        return {}
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return {}

    def _text(*names: str) -> str:
        for name in names:
            node = root.find(name)
            if node is not None and (node.text or "").strip():
                return node.text.strip()
        return ""

    return {
        "persona": _text("steamID", "personaName"),
        "avatarUrl": _text("avatarFull", "avatarMedium", "avatarIcon"),
    }


def cached_snapshot() -> Dict[str, Any]:
    """In-memory Steam persona only — JOINACK must not wait on community XML."""
    payload = _cache.get("payload")
    return dict(payload) if isinstance(payload, dict) else {}


def snapshot(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    if not force and _cache.get("payload") and (now - float(_cache.get("at") or 0)) < _CACHE_TTL:
        return dict(_cache["payload"])
    sid = steamid64()
    payload: Dict[str, Any] = {
        "hostSteamId": sid,
        "steamId64": sid,
        "hostPersona": "",
        "hostAvatarUrl": "",
    }
    if sid:
        profile = _community_profile(sid)
        payload["hostPersona"] = profile.get("persona") or ""
        payload["hostAvatarUrl"] = profile.get("avatarUrl") or ""
        if payload["hostAvatarUrl"] and payload["hostAvatarUrl"].startswith("http://"):
            payload["hostAvatarUrl"] = "https://" + payload["hostAvatarUrl"][7:]
    _cache["at"] = now
    _cache["payload"] = payload
    if sid:
        logging.info("host_identity steam=%s persona=%s", sid, payload.get("hostPersona") or "?")
    return dict(payload)
