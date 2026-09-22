"""Steam voice input → GameSphere Mic (PipeWire source id on Linux)."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from typing import Dict, List

STEAM_USERDATA = os.path.expanduser("~/.steam/steam/userdata")
DEFAULT_MIC = os.environ.get("GAMESPHERE_STEAM_MIC_ID", "gamesphere_mic")


def _voice_settings_pattern(uid: str) -> str:
    return rf'"SteamVoiceSettings_{uid}"\s+"(\{{.*?\}})"'


def configure_steam_voice_mic(mic_id: str = DEFAULT_MIC) -> Dict:
    """Set SteamVoiceSettings selectedMic for every local Steam account (Linux)."""
    if os.name == "nt":
        return {"ok": True, "skipped": "windows", "updated": [], "mic": mic_id}
    if not os.path.isdir(STEAM_USERDATA):
        return {"ok": True, "skipped": "no_steam", "updated": [], "mic": mic_id}

    updated: List[str] = []
    errors: List[str] = []
    for uid in sorted(os.listdir(STEAM_USERDATA)):
        if not uid.isdigit():
            continue
        path = os.path.join(STEAM_USERDATA, uid, "config", "localconfig.vdf")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = f.read()
            m = re.search(_voice_settings_pattern(uid), data)
            if not m:
                continue
            settings = json.loads(m.group(1).replace('\\"', '"'))
            old = settings.get("selectedMic")
            if old == mic_id:
                continue
            settings["selectedMic"] = mic_id
            new_json = json.dumps(settings, separators=(",", ":"))
            escaped = new_json.replace('"', '\\"')
            new_data = data[: m.start(1)] + escaped + data[m.end(1) :]
            bak = f"{path}.bak.gs-mic-{int(time.time())}"
            shutil.copy2(path, bak)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_data)
            updated.append(f"{uid}:{old!r}->{mic_id}")
            logging.info("steam voice mic %s selectedMic %s -> %s", uid, old, mic_id)
        except Exception as exc:
            errors.append(f"{uid}:{exc}")
            logging.warning("steam voice mic %s: %s", uid, exc)

    if shutil.which("pactl") and mic_id:
        try:
            import subprocess

            subprocess.run(
                ["pactl", "set-default-source", mic_id],
                check=False,
                capture_output=True,
                timeout=5,
            )
        except OSError as exc:
            logging.debug("pactl default-source: %s", exc)

    return {
        "ok": not errors,
        "updated": updated,
        "errors": errors,
        "mic": mic_id,
    }
