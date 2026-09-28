"""Pin Sunshine Opus channel count to the HDMI capture tap.

Sunshine encodes at sunshine.conf `channels=` regardless of the Pulse monitor
format. A leftover `channels = 2` with a 6ch tap is what made AirPods show
"Stereo Spatial". Companion overwrites sink + channels whenever it installs or
starts the host bridge (never restarts Sunshine mid-game).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any, Dict, Optional

from host_tuning.sunshine_wan import find_sunshine_conf

_log = logging.getLogger(__name__)

CAPTURE_SCRIPT = os.path.expanduser("~/.local/bin/bazzite-sunshine-capture-audio.sh")
PERSIST_MODE = os.path.expanduser(
    os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "gamesphere",
        "bazzite-stream-audio.mode",
    )
)
ENV_DROPIN = os.path.expanduser(
    os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "environment.d",
        "90-bazzite-stream-audio.conf",
    )
)

SURROUND51 = {
    "mode": "surround51",
    "channels": "6",
    "audio_sink": "bazzite-stream-surround51",
}
STEREO = {
    "mode": "stereo",
    "channels": "2",
    "audio_sink": "bazzite-stream-stereo",
}


def _normalize_mode(raw: str) -> str:
    v = (raw or "").strip().lower()
    if v in ("stereo", "2"):
        return "stereo"
    if v in ("surround51", "5.1", "51", "surround"):
        return "surround51"
    return ""


def desired_mode() -> str:
    """Env → persist → environment.d → surround51 default."""
    for candidate in (
        _normalize_mode(os.environ.get("BAZZITE_STREAM_AUDIO", "")),
        _read_mode_file(PERSIST_MODE),
        _read_env_dropin(),
    ):
        if candidate:
            return candidate
    return "surround51"


def _read_mode_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return _normalize_mode(fh.read())
    except OSError:
        return ""


def _read_env_dropin() -> str:
    try:
        with open(ENV_DROPIN, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("BAZZITE_STREAM_AUDIO="):
                    return _normalize_mode(line.split("=", 1)[1])
    except OSError:
        return ""
    return ""


def desired_spec(mode: str = "") -> Dict[str, str]:
    m = _normalize_mode(mode) or desired_mode()
    return dict(STEREO if m == "stereo" else SURROUND51)


def should_manage_tap(conf_text: str = "") -> bool:
    """Only rewrite audio_sink on hosts that use the Bazzite HDMI tap."""
    if os.path.isfile(CAPTURE_SCRIPT):
        return True
    if os.path.isfile(PERSIST_MODE) or os.path.isfile(ENV_DROPIN):
        return True
    if "bazzite-stream-" in (conf_text or ""):
        return True
    return False


def _parse_last(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _set_keys(text: str, updates: Dict[str, str]) -> str:
    """Replace all assignments for each key (last-wins cleanup) then ensure one line."""
    lines = text.splitlines(keepends=True)
    keys = set(updates)
    # Drop every existing assignment for managed keys.
    kept = []
    for line in lines:
        m = re.match(r"^([A-Za-z0-9_]+)\s*=", line)
        if m and m.group(1) in keys:
            continue
        kept.append(line)
    text = "".join(kept)
    suffix = "" if text.endswith("\n") or not text else "\n"
    block = suffix
    if "GameSphere Companion stream audio" not in text:
        block += "\n# GameSphere Companion stream audio (Opus channels must match capture tap)\n"
    for key, value in updates.items():
        block += f"{key} = {value}\n"
    return text + block


def apply_stream_audio(
    path: str = "",
    *,
    dry_run: bool = False,
    run_capture_ensure: bool = True,
) -> Dict[str, Any]:
    """Overwrite sunshine.conf channels (+ tap sink when applicable). Never restart Sunshine."""
    path = path or find_sunshine_conf()
    if not path:
        return {"ok": False, "error": "sunshine_conf_not_found", "needsRestart": False}

    spec = desired_spec()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            original = fh.read()
    except OSError as exc:
        return {"ok": False, "error": str(exc), "path": path, "needsRestart": False}

    manage_tap = should_manage_tap(original)
    if not manage_tap:
        return {
            "ok": True,
            "path": path,
            "changed": [],
            "mode": spec["mode"],
            "skipped": True,
            "reason": "no_bazzite_capture_tap",
            "needsRestart": False,
        }

    updates: Dict[str, str] = {
        "channels": spec["channels"],
        "audio_sink": spec["audio_sink"],
        "virtual_sink": "",
    }

    parsed = _parse_last(original)
    changed = [k for k, v in updates.items() if (parsed.get(k) or "").strip() != v]
    # Also rewrite when duplicate keys exist even if last value matches.
    for key in updates:
        n = len(re.findall(rf"(?m)^\s*{re.escape(key)}\s*=", original))
        if n > 1 and key not in changed:
            changed.append(key)

    capture: Optional[Dict[str, Any]] = None
    if run_capture_ensure and manage_tap and os.path.isfile(CAPTURE_SCRIPT) and not dry_run:
        capture = _run_capture_ensure(spec["mode"])

    if not changed:
        return {
            "ok": True,
            "path": path,
            "changed": [],
            "mode": spec["mode"],
            "values": updates,
            "manageTap": manage_tap,
            "capture": capture,
            "needsRestart": False,
        }

    text = _set_keys(original, updates)
    if dry_run:
        return {
            "ok": True,
            "path": path,
            "changed": changed,
            "mode": spec["mode"],
            "dryRun": True,
            "needsRestart": True,
            "manageTap": manage_tap,
        }

    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:
        _log.warning("Could not write stream audio keys to %s: %s", path, exc)
        return {"ok": False, "error": str(exc), "path": path, "needsRestart": False}

    _log.info(
        "Sunshine stream audio pinned mode=%s channels=%s changed=%s",
        spec["mode"],
        spec["channels"],
        ",".join(changed),
    )
    return {
        "ok": True,
        "path": path,
        "changed": changed,
        "mode": spec["mode"],
        "values": updates,
        "manageTap": manage_tap,
        "capture": capture,
        "needsRestart": True,
        "note": "Opus channel count applies on the next Sunshine session. Companion does not restart Sunshine mid-game.",
    }


def _run_capture_ensure(mode: str) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            [CAPTURE_SCRIPT, "ensure"],
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ, "BAZZITE_STREAM_AUDIO": mode},
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip()[:500],
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}


def snapshot(path: str = "") -> Dict[str, Any]:
    path = path or find_sunshine_conf()
    values: Dict[str, str] = {}
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                values = _parse_last(fh.read())
        except OSError:
            values = {}
    spec = desired_spec()
    conf_ch = (values.get("channels") or "").strip()
    return {
        "path": path,
        "mode": spec["mode"],
        "desiredChannels": spec["channels"],
        "confChannels": conf_ch,
        "audioSink": (values.get("audio_sink") or "").strip(),
        "ok": conf_ch == spec["channels"] if conf_ch else False,
        "manageTap": should_manage_tap(""),
    }
