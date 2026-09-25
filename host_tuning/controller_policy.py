"""Streaming controller policy: Sunshine gamepad mode + emulator prep (EmuDeck-style)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from host_tuning.config import HostTuningConfig, load_config, save_config

# Sunshine host virtual pad + bazzite-controller-detect stream_gamepad env.
CONTEXTS: Dict[str, Dict[str, str]] = {
    "gamesphere-ds5": {
        "label": "GameSphere (DualSense)",
        "sunshine_gamepad": "ds5",
        "motion_as_ds4": "enabled",
        "touchpad_as_ds4": "enabled",
        "stream_gamepad": "ds5",
        "remote_xbox_p1": "never",
    },
    "gamesphere-x360": {
        "label": "GameSphere (Xbox 360)",
        "sunshine_gamepad": "x360",
        "motion_as_ds4": "disabled",
        "touchpad_as_ds4": "disabled",
        "stream_gamepad": "x360",
        "remote_xbox_p1": "never",
    },
    "steamlink-x360": {
        "label": "Steam Link (Xbox 360)",
        "sunshine_gamepad": "x360",
        "motion_as_ds4": "disabled",
        "touchpad_as_ds4": "disabled",
        "stream_gamepad": "x360",
        "remote_xbox_p1": "always",
    },
    "local": {
        "label": "Local (projector)",
        "sunshine_gamepad": "ds5",
        "motion_as_ds4": "enabled",
        "touchpad_as_ds4": "enabled",
        "stream_gamepad": "ds5",
        "remote_xbox_p1": "never",
    },
}

VALID_CONTEXTS = frozenset(CONTEXTS)
VALID_GAMEPADS = frozenset({"ds5", "x360", "auto"})


@dataclass
class ControllerPolicyState:
    context: str
    gamepad: str
    label: str
    peers: List[str]
    applied: bool
    message: str = ""


def _runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))


def _sunshine_conf() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "sunshine" / "sunshine.conf"


def _steamlink_ips(cfg: HostTuningConfig) -> List[str]:
    raw = (cfg.controller_steamlink_ips or os.environ.get("BAZZITE_STEAMLINK_IPS", "10.0.4.33")).strip()
    return [ip.strip() for ip in raw.split(",") if ip.strip()]


def sunshine_peer_ips() -> List[str]:
    try:
        out = subprocess.check_output(
            ["ss", "-H", "-tn", "state", "established"],
            text=True,
            timeout=3,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    peers: List[str] = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[2]
        remote = parts[3]
        local_port = local.rsplit(":", 1)[-1]
        if local_port not in {"47984", "47989", "47990", "48010"}:
            continue
        peer = remote.rsplit(":", 1)[0].strip("[]")
        if peer:
            peers.append(peer)
    peers = sorted(set(peers))
    if peers:
        return peers
    # Moonlight often has no long-lived TCP on control ports; stream marker is reliable.
    if (_runtime_dir() / "bazzite-sunshine-stream-active").is_file():
        return ["streaming"]
    return []


def classify_peers(cfg: HostTuningConfig, peers: Optional[List[str]] = None) -> str:
    """Return steamlink | other | unknown."""
    peers = peers if peers is not None else sunshine_peer_ips()
    allow = _steamlink_ips(cfg)
    has_link = has_other = False
    for ip in peers:
        if ip in allow:
            has_link = True
        else:
            has_other = True
    if has_other:
        return "other"
    if has_link:
        return "steamlink"
    return "unknown"


def resolve_context(
    cfg: Optional[HostTuningConfig] = None,
    *,
    force: str = "",
    client_hint: str = "",
    poll_secs: float = 3.0,
) -> str:
    """Pick active controller context for an imminent or live stream."""
    cfg = cfg or load_config()
    hint = (client_hint or cfg.controller_client_hint or "").strip().lower()
    if hint in VALID_CONTEXTS:
        return hint
    if force in VALID_CONTEXTS:
        return force

    override = (cfg.controller_active_context or "").strip()
    if override in VALID_CONTEXTS and force not in {"auto", ""}:
        pass  # manual SETCONTROLLER wins until cleared
    elif override in VALID_CONTEXTS and cfg.controller_persist_override:
        return override

    gamepad = (cfg.controller_user_gamepad or "auto").strip().lower()
    if gamepad == "x360":
        return "steamlink-x360" if classify_peers(cfg) == "steamlink" else "gamesphere-x360"
    if gamepad == "ds5":
        return "gamesphere-ds5"

    deadline = time.monotonic() + max(0.0, poll_secs)
    while True:
        kind = classify_peers(cfg)
        if kind == "other":
            return cfg.controller_default_context or "gamesphere-ds5"
        if kind == "steamlink":
            return "steamlink-x360"
        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)

    default = (cfg.controller_default_context or "gamesphere-ds5").strip()
    return default if default in VALID_CONTEXTS else "gamesphere-ds5"


def _ensure_conf_key(conf: Path, key: str, value: str) -> None:
    conf.parent.mkdir(parents=True, exist_ok=True)
    text = conf.read_text(encoding="utf-8") if conf.is_file() else ""
    line = f"{key} = {value}"
    if re.search(rf"^[ \t]*{re.escape(key)}[ \t]*=", text, re.M):
        text = re.sub(rf"^[ \t]*{re.escape(key)}[ \t]*=.*$", line, text, count=1, flags=re.M)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    conf.write_text(text, encoding="utf-8")


def apply_sunshine_profile(context: str, cfg: Optional[HostTuningConfig] = None) -> ControllerPolicyState:
    cfg = cfg or load_config()
    if context not in CONTEXTS:
        context = "gamesphere-ds5"
    spec = CONTEXTS[context]
    conf = _sunshine_conf()
    rt = _runtime_dir()
    try:
        _ensure_conf_key(conf, "gamepad", spec["sunshine_gamepad"])
        _ensure_conf_key(conf, "motion_as_ds4", spec["motion_as_ds4"])
        _ensure_conf_key(conf, "touchpad_as_ds4", spec["touchpad_as_ds4"])
        rt.mkdir(parents=True, exist_ok=True)
        (rt / "bazzite-sunshine-gamepad-mode").write_text(spec["stream_gamepad"], encoding="utf-8")
        (rt / "bazzite-sunshine-remote-xbox-p1").write_text(spec["remote_xbox_p1"], encoding="utf-8")
        (rt / "bazzite-controller-context").write_text(context, encoding="utf-8")
        (rt / "bazzite-sunshine-stream-active").write_text("", encoding="utf-8")
        return ControllerPolicyState(
            context=context,
            gamepad=spec["sunshine_gamepad"],
            label=spec["label"],
            peers=sunshine_peer_ips(),
            applied=True,
        )
    except OSError as exc:
        logging.warning("apply_sunshine_profile failed: %s", exc)
        return ControllerPolicyState(
            context=context,
            gamepad=spec["sunshine_gamepad"],
            label=spec["label"],
            peers=sunshine_peer_ips(),
            applied=False,
            message=str(exc),
        )


def stream_env(context: str) -> Dict[str, str]:
    spec = CONTEXTS.get(context, CONTEXTS["gamesphere-ds5"])
    return {
        "BAZZITE_SUNSHINE_STREAM": "1",
        "BAZZITE_STREAM_GAMEPAD": spec["stream_gamepad"],
        "BAZZITE_REMOTE_XBOX_P1": spec["remote_xbox_p1"],
        "BAZZITE_CONTROLLER_CONTEXT": context,
        "BAZZITE_INCLUDE_VIRTUAL_XBOX": "auto",
    }


def _emulator_helper(name: str) -> Path | None:
    """Resolve optional per-host emulator bind scripts (Bazzite / custom ~/.local/bin)."""
    home = Path.home()
    for candidate in (
        home / ".local/bin" / name,
        Path(__file__).resolve().parent.parent / "scripts" / "emulator" / name,
    ):
        if candidate.is_file():
            return candidate
    return None


def _stream_pad_pattern(context: str) -> str:
    if CONTEXTS.get(context, {}).get("stream_gamepad") == "x360":
        return r"\"kind\":\s*\"moonlight_x360\""
    return r"\"kind\":\s*\"stream_ds5\""


def hide_steam_x360_clones() -> bool:
    script = Path.home() / ".local/bin/bazzite-hide-steam-x360-clones.sh"
    if not script.is_file():
        return False
    try:
        subprocess.run([str(script)], check=False, timeout=15)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def start_steam_clone_watch() -> bool:
    script = Path.home() / ".local/bin/bazzite-steam-clone-watch.sh"
    if not script.is_file():
        return False
    try:
        subprocess.Popen(
            ["nohup", str(script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        return False


def apply_emulator_bindings(context: str, cfg: Optional[HostTuningConfig] = None) -> Dict[str, Any]:
    cfg = cfg or load_config()
    if not cfg.controller_apply_emulators:
        return {"ok": True, "skipped": True}
    detect = Path.home() / ".local/bin/bazzite-controller-detect.py"
    if not detect.is_file():
        return {"ok": False, "error": "missing_bazzite_controller_detect"}
    ra_cfg = _runtime_dir() / "bazzite-retroarch-input.cfg"
    env = {**os.environ, **stream_env(context)}
    try:
        proc = subprocess.run(
            [
                "python3",
                str(detect),
                "--dolphin",
                "--eden",
                "--retroarch",
                str(ra_cfg),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        extra: Dict[str, Any] = {}
        cemu = _emulator_helper("bazzite-cemu-bind-controller.py")
        if cemu:
            try:
                cproc = subprocess.run(
                    ["python3", str(cemu)],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                extra["cemu_tail"] = (cproc.stdout or "")[-1000:]
                extra["cemu_ok"] = cproc.returncode == 0
            except (subprocess.SubprocessError, OSError) as exc:
                extra["cemu_error"] = str(exc)
        hark = _emulator_helper("bazzite-sync-harkinian-rumble.py")
        if hark:
            try:
                hproc = subprocess.run(
                    ["python3", str(hark)],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                extra["harkinian_tail"] = (hproc.stdout or "")[-1000:]
                extra["harkinian_ok"] = hproc.returncode == 0
            except (subprocess.SubprocessError, OSError) as exc:
                extra["harkinian_error"] = str(exc)
        return {
            "ok": proc.returncode == 0,
            "context": context,
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-1000:],
            **extra,
        }
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def prep_stream(
    cfg: Optional[HostTuningConfig] = None,
    *,
    force: str = "auto",
    client_hint: str = "",
    apply_bindings: bool = False,
) -> Dict[str, Any]:
    """Run at Sunshine stream start (before CLIENT CONNECT when possible)."""
    cfg = cfg or load_config()
    if not cfg.enabled or not cfg.controller_policy_enabled:
        return {"ok": True, "skipped": True}

    context = resolve_context(cfg, force=force, client_hint=client_hint)
    state = apply_sunshine_profile(context, cfg)
    actions: Dict[str, Any] = {
        "context": state.context,
        "label": state.label,
        "gamepad": state.gamepad,
        "peers": state.peers,
        "sunshine_applied": state.applied,
    }

    # Stream-wide clone hiding breaks Proton games (they read only Steam Input clones).
    # GameSphere streams leave it to couch_coop, which hides only while an emulator runs.
    if cfg.controller_hide_steam_clones and CONTEXTS[state.context]["remote_xbox_p1"] == "always":
        actions["hide_steam_clones"] = hide_steam_x360_clones()
        actions["clone_watch"] = start_steam_clone_watch()

    if apply_bindings:
        actions["emulators"] = apply_emulator_bindings(context, cfg)

    return {"ok": state.applied, "actions": actions}


def apply_emulator_bindings_with_wait(
    context: str,
    cfg: Optional[HostTuningConfig] = None,
    *,
    wait_secs: float = 2.0,
    poll_secs: float = 0.25,
) -> Dict[str, Any]:
    """Sync bind for game launch: wait briefly for the Sunshine virtual pad, then apply.

    Kept short because it runs inside Sunshine prep-cmd; a long wait stalls /launch.
    """
    cfg = cfg or load_config()
    detect = Path.home() / ".local/bin/bazzite-controller-detect.py"
    if not detect.is_file():
        return {"ok": False, "error": "missing_bazzite_controller_detect", "context": context}
    deadline = time.monotonic() + max(0.0, wait_secs)
    while time.monotonic() < deadline:
        try:
            out = subprocess.check_output(["python3", str(detect), "--json"], text=True, timeout=8)
            if re.search(_stream_pad_pattern(context), out):
                break
        except (subprocess.SubprocessError, OSError):
            pass
        time.sleep(poll_secs)
    return apply_emulator_bindings(context, cfg)


def deferred_emulator_sync(context: str, delay_secs: float = 3.0) -> None:
    """Background: wait for virtual pad, then re-bind emulators."""
    def _worker() -> None:
        time.sleep(max(0.5, delay_secs))
        apply_emulator_bindings(context)

    import threading

    threading.Thread(target=_worker, daemon=True).start()


def get_policy_json(cfg: Optional[HostTuningConfig] = None) -> Dict[str, Any]:
    cfg = cfg or load_config()
    rt = _runtime_dir()
    active_context = ""
    if (rt / "bazzite-controller-context").is_file():
        active_context = (rt / "bazzite-controller-context").read_text(encoding="utf-8").strip()
    effective = active_context or resolve_context(cfg, force="auto")
    spec = CONTEXTS.get(effective, CONTEXTS["gamesphere-ds5"])
    return {
        "enabled": cfg.controller_policy_enabled,
        "userGamepad": cfg.controller_user_gamepad or "auto",
        "activeContext": active_context,
        "effectiveContext": effective,
        "label": spec["label"],
        "gamepad": spec["sunshine_gamepad"],
        "contexts": {k: v["label"] for k, v in CONTEXTS.items()},
        "peers": sunshine_peer_ips(),
        "peerClass": classify_peers(cfg),
        "steamlinkIps": _steamlink_ips(cfg),
        "profiles": [
            {
                "id": "gamesphere-ds5",
                "emulators": ["dolphin", "eden", "retroarch", "ryujinx", "cemu", "harkinian"],
                "autoApply": True,
            },
            {
                "id": "gamesphere-x360",
                "emulators": ["dolphin", "eden", "retroarch", "ryujinx", "cemu", "harkinian"],
                "autoApply": True,
            },
            {
                "id": "steamlink-x360",
                "emulators": ["dolphin", "eden", "retroarch", "cemu", "harkinian"],
                "autoApply": True,
            },
        ],
    }


def set_policy_json(payload: Dict[str, Any], cfg: Optional[HostTuningConfig] = None) -> Dict[str, Any]:
    cfg = cfg or load_config()
    gamepad = str(payload.get("gamepad") or payload.get("userGamepad") or "").strip().lower()
    context = str(payload.get("context") or payload.get("activeContext") or "").strip()

    if gamepad in VALID_GAMEPADS:
        cfg.controller_user_gamepad = gamepad
    if context in VALID_CONTEXTS:
        cfg.controller_active_context = context
        cfg.controller_persist_override = bool(payload.get("persist", True))
    elif context in {"", "auto", "clear"}:
        cfg.controller_active_context = ""
        cfg.controller_persist_override = False

    hint = str(payload.get("clientHint") or "").strip().lower()
    if hint:
        cfg.controller_client_hint = hint

    save_config(cfg)

    apply_now = bool(payload.get("applyNow"))
    result = {"ok": True, "policy": get_policy_json(cfg)}
    if apply_now:
        force = context if context in VALID_CONTEXTS else "auto"
        result["stream"] = prep_stream(cfg, force=force, client_hint=hint)
    return result


def clear_stream_markers() -> None:
    rt = _runtime_dir()
    for name in (
        "bazzite-sunshine-gamepad-mode",
        "bazzite-sunshine-remote-xbox-p1",
        "bazzite-controller-context",
        "bazzite-sunshine-stream-active",
    ):
        try:
            (rt / name).unlink(missing_ok=True)
        except OSError:
            pass
