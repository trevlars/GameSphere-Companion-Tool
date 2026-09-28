"""Steam voice input → GameSphere Mic (PipeWire source id on Linux).

On a GameSphere stream, force Steam's selectedMic + Pulse default source to
``gamesphere_mic`` so Discord/Steam Voice hear the phone uplink without hunting
settings. Steam Link / DualSense paths are left alone.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from typing import Dict, List, Optional

STEAM_USERDATA = os.path.expanduser("~/.steam/steam/userdata")
DEFAULT_MIC = os.environ.get("GAMESPHERE_STEAM_MIC_ID", "gamesphere_mic")
RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"


def _stream_mic_flag() -> str:
    return os.path.join(RUNTIME_DIR, "gamesphere-stream-mic.active")


def _stream_mic_prev() -> str:
    return os.path.join(RUNTIME_DIR, "gamesphere-stream-mic.prev-source")


def _voice_settings_re(uid: str) -> re.Pattern[str]:
    # VDF: "SteamVoiceSettings_<uid>"\t\t"{...escaped json...}"
    return re.compile(
        rf'("SteamVoiceSettings_{re.escape(uid)}"\s+")(\{{.*?\}})(")',
        re.DOTALL,
    )


def _default_voice_settings(mic_id: str) -> Dict:
    # GameSphere Mic is already cleaned on the phone (Speex/HPF/gate). Steam's
    # NS/EC/AGC on top makes the uplink thin/pump-y — keep Steam DSP off.
    return {
        "inputGain": 1,
        "outputGain": 1,
        "noiseGateLevel": 0,
        "noiseCancellation": False,
        "echoCancellation": False,
        "autoGainControl": False,
        "selectedMic": mic_id,
        "selectedOutput": "default",
        "pttSoundsEnabled": True,
        "hasResetOpenMicHotKey": True,
        "useSteamAudioSpatialization": False,
    }


def _escape_vdf_json(settings: Dict) -> str:
    return json.dumps(settings, separators=(",", ":")).replace('"', '\\"')


def _set_pulse_default_source(mic_id: str) -> bool:
    if not shutil.which("pactl") or not mic_id:
        return False
    try:
        proc = subprocess.run(
            ["pactl", "set-default-source", mic_id],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode == 0
    except OSError as exc:
        logging.debug("pactl default-source: %s", exc)
        return False


def _get_pulse_default_source() -> str:
    if not shutil.which("pactl"):
        return ""
    try:
        proc = subprocess.run(
            ["pactl", "get-default-source"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return (proc.stdout or "").strip()
    except OSError:
        return ""


def configure_steam_voice_mic(
    mic_id: str = DEFAULT_MIC,
    *,
    force: bool = False,
    set_pulse_default: bool = True,
    create_missing: bool = True,
) -> Dict:
    """Set SteamVoiceSettings selectedMic for every local Steam account (Linux)."""
    if os.name == "nt":
        return {"ok": True, "skipped": "windows", "updated": [], "mic": mic_id}
    if not os.path.isdir(STEAM_USERDATA):
        return {"ok": True, "skipped": "no_steam", "updated": [], "mic": mic_id}

    updated: List[str] = []
    created: List[str] = []
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
            pat = _voice_settings_re(uid)
            m = pat.search(data)
            if not m:
                if not create_missing:
                    continue
                settings = _default_voice_settings(mic_id)
                escaped = _escape_vdf_json(settings)
                line = f'\t\t"SteamVoiceSettings_{uid}"\t\t"{escaped}"\n'
                # Insert just inside UserLocalConfigStore { … } when present.
                store = re.search(
                    r'("UserLocalConfigStore"\s*\{\s*\n)',
                    data,
                )
                if store:
                    data = data[: store.end(1)] + line + data[store.end(1) :]
                else:
                    data = data + ("\n" if not data.endswith("\n") else "") + line
                bak = f"{path}.bak.gs-mic-{int(time.time())}"
                shutil.copy2(path, bak)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(data)
                created.append(uid)
                updated.append(f"{uid}:<created>->{mic_id}")
                logging.info("steam voice mic %s created selectedMic=%s", uid, mic_id)
                continue

            raw = m.group(2).replace('\\"', '"')
            settings = json.loads(raw)
            old = settings.get("selectedMic")
            # Always keep GameSphere Mic free of Steam's second DSP pass.
            want_clean = (
                settings.get("noiseCancellation") is True
                or settings.get("echoCancellation") is True
                or settings.get("autoGainControl") is True
                or float(settings.get("inputGain") or 1) > 1.01
            )
            if old == mic_id and not force and not want_clean:
                continue
            settings["selectedMic"] = mic_id
            settings["noiseCancellation"] = False
            settings["echoCancellation"] = False
            settings["autoGainControl"] = False
            settings["noiseGateLevel"] = 0
            if float(settings.get("inputGain") or 1) > 1.01:
                settings["inputGain"] = 1
            escaped = _escape_vdf_json(settings)
            new_data = data[: m.start(2)] + escaped + data[m.end(2) :]
            bak = f"{path}.bak.gs-mic-{int(time.time())}"
            shutil.copy2(path, bak)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_data)
            updated.append(f"{uid}:{old!r}->{mic_id}")
            logging.info("steam voice mic %s selectedMic %s -> %s", uid, old, mic_id)
        except Exception as exc:
            errors.append(f"{uid}:{exc}")
            logging.warning("steam voice mic %s: %s", uid, exc)

    pulse_ok = _set_pulse_default_source(mic_id) if set_pulse_default else False

    return {
        "ok": not errors,
        "updated": updated,
        "created": created,
        "errors": errors,
        "mic": mic_id,
        "pulseDefault": pulse_ok,
    }


def is_gamesphere_stream_client() -> bool:
    """True when the active / imminent Sunshine client is GameSphere (not Steam Link)."""
    name = (os.environ.get("SUNSHINE_CLIENT_NAME") or "").strip().lower()
    if name:
        if "steam link" in name or "steamlink" in name or name in {"steamlink", "steam-link"}:
            return False
        if any(tok in name for tok in ("gamesphere", "roth", "iphone", "ipad", "ios", "apple")):
            return True

    remote = _read_runtime("bazzite-sunshine-remote-xbox-p1").strip().lower()
    if remote == "never":
        return True
    if remote == "always":
        return False

    ctx = _read_runtime("bazzite-controller-context").strip().lower()
    if "steamlink" in ctx:
        return False
    if "gamesphere" in ctx:
        return True

    # Controllers / peers: "other" = GameSphere/iPhone; "steamlink" = playroom box.
    try:
        from host_tuning import controller_policy
        from host_tuning.config import load_config

        kind = controller_policy.classify_peers(load_config())
        if kind == "steamlink":
            return False
        if kind == "other":
            return True
    except Exception:
        pass
    # Ambiguous (no markers / unknown peers): do not steal DualSense / rear mic.
    return False


def _read_runtime(name: str) -> str:
    path = os.path.join(RUNTIME_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def _write_runtime(path: str, text: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:
        logging.debug("runtime write %s: %s", path, exc)


def apply_for_gamesphere_stream(mic_id: str = DEFAULT_MIC) -> Dict:
    """Ensure GameSphere Mic exists and Steam + Pulse select it (GameSphere clients only)."""
    if os.name == "nt":
        return {"ok": True, "skipped": "windows"}
    if not is_gamesphere_stream_client():
        return {"ok": True, "skipped": "not_gamesphere_client", "mic": mic_id}

    # Make sure the PipeWire device (+ AEC) exists before Steam looks for it.
    try:
        from host_tuning import voice_bridge

        mic = voice_bridge.ensure_pc_mic_device()
    except Exception as exc:
        logging.warning("stream mic ensure device: %s", exc)
        mic = {"ok": False, "error": str(exc)}

    prev = _get_pulse_default_source()
    prev_path = _stream_mic_prev()
    if prev and prev != mic_id and not os.path.isfile(prev_path):
        _write_runtime(prev_path, prev + "\n")

    voice = configure_steam_voice_mic(
        mic_id, force=True, set_pulse_default=True, create_missing=True
    )
    _write_runtime(_stream_mic_flag(), f"mic={mic_id}\nts={time.time()}\n")

    # Re-assert Pulse default — profile-audio may race on stream start.
    pulse_ok = _set_pulse_default_source(mic_id)
    return {
        "ok": bool(mic.get("ok")) and bool(voice.get("ok")),
        "mic": mic_id,
        "device": mic,
        "steamVoice": voice,
        "pulseDefault": pulse_ok,
        "previousSource": prev,
    }


def restore_after_stream() -> Dict:
    """Clear the GameSphere stream mic pin and restore the prior Pulse default."""
    flag = _stream_mic_flag()
    prev_path = _stream_mic_prev()
    had_flag = os.path.isfile(flag)
    prev = ""
    try:
        if os.path.isfile(prev_path):
            prev = open(prev_path, encoding="utf-8").read().strip()
    except OSError:
        prev = ""
    for path in (flag, prev_path):
        try:
            os.remove(path)
        except OSError:
            pass
    restored = False
    if prev and prev != DEFAULT_MIC:
        restored = _set_pulse_default_source(prev)
    return {
        "ok": True,
        "hadFlag": had_flag,
        "restoredSource": prev if restored else "",
        "restored": restored,
    }


def stream_mic_pinned() -> bool:
    return os.path.isfile(_stream_mic_flag())
