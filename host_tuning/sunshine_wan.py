"""WAN-safe Sunshine/Apollo conf — never expose 47990, never restart a live session.

Writes recommended keys into an existing sunshine.conf. Does not change hevc/av1
codecs. Does not restart Sunshine (that would kill a game session).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Tuple

from host_tuning.config import load_config

_log = logging.getLogger(__name__)

# Sunshine UPnP would also publish 47990 (web UI). Companion maps the data ports.
# `gamepad` is not here: controller_policy sets it per stream (ds5 GameSphere, x360 Steam Link).
RECOMMENDED = {
    "upnp": "disabled",
    "origin_web_ui_allowed": "pc",
    "wan_encryption_mode": "1",
    "address_family": "both",
}

def find_sunshine_conf(apps_json: str = "") -> str:
    candidates: List[str] = []
    if apps_json:
        folder = os.path.dirname(os.path.abspath(os.path.expanduser(apps_json)))
        candidates.append(os.path.join(folder, "sunshine.conf"))
    cfg = load_config()
    log_path = (cfg.sunshine_log_path or "").strip()
    if log_path:
        folder = os.path.dirname(os.path.abspath(os.path.expanduser(log_path)))
        candidates.append(os.path.join(folder, "sunshine.conf"))
        parent = os.path.dirname(folder)
        candidates.append(os.path.join(parent, "sunshine.conf"))
    home = os.path.expanduser("~")
    candidates.extend(
        [
            os.path.join(home, ".config", "sunshine", "sunshine.conf"),
            os.path.join(home, ".config", "Apollo", "sunshine.conf"),
            os.path.join(
                home,
                ".var",
                "app",
                "dev.lizardbyte.app.Sunshine",
                "config",
                "sunshine",
                "sunshine.conf",
            ),
        ]
    )
    if os.name == "nt":
        for base in (
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Sunshine", "config"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Apollo", "config"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Sunshine", "config"),
        ):
            candidates.append(os.path.join(base, "sunshine.conf"))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def _parse(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def current_values(path: str = "") -> Dict[str, str]:
    path = path or find_sunshine_conf()
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return _parse(fh.read())
    except OSError:
        return {}


def _replace_or_append(text: str, key: str, value: str) -> str:
    replacement = f"{key} = {value}"
    active = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=.*$")
    if active.search(text):
        return active.sub(replacement, text, count=1)
    commented = re.compile(rf"(?m)^\s*#\s*{re.escape(key)}\s*=.*$")
    if commented.search(text):
        return commented.sub(replacement, text, count=1)
    suffix = "" if text.endswith("\n") or not text else "\n"
    return text + suffix + f"\n# GameSphere Companion WAN-safe (never expose 47990)\n{replacement}\n"


def apply_recommended(path: str = "", *, dry_run: bool = False) -> Dict[str, Any]:
    """Patch sunshine.conf. Never restart Sunshine."""
    path = path or find_sunshine_conf()
    if not path:
        return {"ok": False, "error": "sunshine_conf_not_found", "needsRestart": False}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            original = fh.read()
    except OSError as exc:
        return {"ok": False, "error": str(exc), "path": path, "needsRestart": False}

    parsed = _parse(original)
    changed: List[str] = []
    text = original
    missing: List[Tuple[str, str]] = []
    for key, value in RECOMMENDED.items():
        current = (parsed.get(key) or "").strip()
        if current == value:
            continue
        if re.search(rf"(?m)^\s*{re.escape(key)}\s*=", text) or re.search(
            rf"(?m)^\s*#\s*{re.escape(key)}\s*=", text
        ):
            text = _replace_or_append(text, key, value)
        else:
            missing.append((key, value))
        changed.append(key)

    if missing:
        suffix = "" if text.endswith("\n") or not text else "\n"
        block = suffix + "\n# GameSphere Companion WAN-safe (web UI stays localhost)\n"
        block += "".join(f"{k} = {v}\n" for k, v in missing)
        text = text + block

    if not changed:
        return {
            "ok": True,
            "path": path,
            "changed": [],
            "values": {k: parsed.get(k, "") for k in RECOMMENDED},
            "needsRestart": False,
        }

    if dry_run:
        return {
            "ok": True,
            "path": path,
            "changed": changed,
            "dryRun": True,
            "needsRestart": True,
        }

    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:
        _log.warning("Could not write %s: %s", path, exc)
        return {"ok": False, "error": str(exc), "path": path, "needsRestart": False}

    _log.info("Sunshine WAN keys written (%s) — restart Sunshine later if not streaming", ",".join(changed))
    return {
        "ok": True,
        "path": path,
        "changed": changed,
        "needsRestart": True,
        "values": dict(RECOMMENDED),
        "note": "Settings apply on the next Sunshine restart. Companion will not restart Sunshine while a game is running.",
    }


def snapshot() -> Dict[str, Any]:
    path = find_sunshine_conf()
    values = current_values(path)
    return {
        "path": path,
        "gamepad": values_get(values, "gamepad"),
        "upnp": values_get(values, "upnp"),
        "origin_web_ui_allowed": values_get(values, "origin_web_ui_allowed"),
        "wan_encryption_mode": values_get(values, "wan_encryption_mode"),
        "address_family": values_get(values, "address_family"),
        "recommended": dict(RECOMMENDED),
    }


def values_get(values: Dict[str, str], key: str) -> str:
    return (values.get(key) or "").strip()


def snippet() -> str:
    return (
        "# Sunshine / Apollo — Companion recommended. Do NOT change hevc/av1 for voice/mic work.\n"
        "# Companion maps game ports via UPnP/NAT-PMP. Never publish 47990.\n"
        "# gamepad is chosen per stream by the Companion controller policy.\n"
        "upnp = disabled\n"
        "origin_web_ui_allowed = pc\n"
        "wan_encryption_mode = 1\n"
        "address_family = both\n"
    )
