"""Apply host tuning and stream prep hooks."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from host_tuning.config import HostTuningConfig, config_dir, load_config, save_config
from host_tuning import display_audio
from host_tuning import host_assets
from host_tuning import link_speed
from host_tuning import managed_apps
from host_tuning import nvidia_sentinel
from host_tuning import session_telemetry
from host_tuning import tailscale


_killed_managed: List[str] = []


def apply_host_tuning(
    cfg: Optional[HostTuningConfig] = None,
    sunshine_apps_json: str = "",
) -> Dict[str, Any]:
    """One-shot apply: tiles, NVIDIA snapshot, log path detection."""
    cfg = cfg or load_config()
    results: Dict[str, Any] = {"ok": True, "steps": []}

    if not cfg.enabled:
        results["steps"].append({"step": "disabled", "ok": True})
        return results

    if not cfg.sunshine_log_path:
        detected = session_telemetry.detect_sunshine_log_path()
        if detected:
            cfg.sunshine_log_path = detected
            save_config(cfg)

    if cfg.host_tiles_enabled:
        assets = host_assets.find_assets_dir(sunshine_apps_json)
        desktop = cfg.host_tiles_desktop_source
        steam = cfg.host_tiles_steam_source
        if not desktop or not steam:
            desktop, steam = host_assets.ensure_default_tiles(config_dir())
            cfg.host_tiles_desktop_source = desktop
            cfg.host_tiles_steam_source = steam
            save_config(cfg)
        if assets:
            ok, msg = host_assets.swap_tiles(assets, desktop, steam)
            results["steps"].append({"step": "host_tiles", "ok": ok, "message": msg})
        else:
            results["steps"].append({"step": "host_tiles", "ok": False, "message": "assets dir not found"})

    if cfg.nvidia_sentinel_enabled:
        ok, msg, _path = nvidia_sentinel.capture_snapshot()
        results["steps"].append({"step": "nvidia_snapshot", "ok": ok, "message": msg})

    if cfg.tailscale_enabled:
        detected, ip = tailscale.detect_tailscale()
        results["steps"].append({"step": "tailscale", "ok": detected, "ip": ip})

    if cfg.link_speed_enabled:
        adapter = link_speed.find_wired_adapter(cfg.network_adapter)
        if adapter and not cfg.network_adapter:
            cfg.network_adapter = adapter
            save_config(cfg)
        info = link_speed.get_link_info(adapter) if adapter else {}
        results["steps"].append({"step": "link_speed", "ok": bool(adapter), "adapter": adapter, "info": info})

    return results


def prep_start(cfg: Optional[HostTuningConfig] = None) -> Dict[str, Any]:
    """Called when a Sunshine stream session starts (prep-cmd do)."""
    global _killed_managed
    cfg = cfg or load_config()
    log: Dict[str, Any] = {"actions": []}
    if not cfg.enabled:
        return log

    _killed_managed = managed_apps.kill_running(cfg)
    log["actions"].append({"managed_apps_killed": len(_killed_managed)})

    if cfg.hdr_enabled:
        ok, msg = display_audio.set_hdr_enabled(cfg.hdr_monitor, True)
        log["actions"].append({"hdr": ok, "message": msg})

    if cfg.spatial_audio_enabled:
        ok, msg = display_audio.enable_spatial_audio(cfg.spatial_audio_device, cfg.spatial_audio_format)
        log["actions"].append({"spatial_audio": ok, "message": msg})

    try:
        from host_tuning import controller_policy

        if cfg.controller_policy_enabled:
            ctrl = controller_policy.prep_stream(cfg)
            log["actions"].append({"controller_policy": ctrl})
            if ctrl.get("ok") and ctrl.get("actions", {}).get("context"):
                controller_policy.deferred_emulator_sync(ctrl["actions"]["context"])
    except Exception as exc:
        logging.warning("controller_policy prep_start: %s", exc)

    try:
        from host_tuning import couch_coop

        log["actions"].append({"couch_coop": couch_coop.apply("prep_start")})
    except Exception as exc:
        logging.warning("couch_coop prep_start: %s", exc)

    try:
        from host_tuning import wan_setup

        log["actions"].append({"wan": wan_setup.on_session_start()})
    except Exception as exc:
        logging.warning("wan map prep_start: %s", exc)

    return log


def prep_stop(cfg: Optional[HostTuningConfig] = None) -> Dict[str, Any]:
    """Called when a Sunshine stream session ends (prep-cmd undo)."""
    global _killed_managed
    cfg = cfg or load_config()
    log: Dict[str, Any] = {"actions": []}
    if not cfg.enabled:
        return log

    if _killed_managed:
        managed_apps.start_apps(_killed_managed)
        log["actions"].append({"managed_apps_restarted": len(_killed_managed)})
        _killed_managed = []

    if cfg.hdr_enabled:
        ok, msg = display_audio.set_hdr_enabled(cfg.hdr_monitor, False)
        log["actions"].append({"hdr_off": ok, "message": msg})

    adapter = link_speed.find_wired_adapter(cfg.network_adapter)
    if adapter and cfg.link_speed_enabled:
        ok, msg = link_speed.restore_link_speed(adapter)
        log["actions"].append({"link_restore": ok, "message": msg})

    try:
        from host_tuning import controller_policy

        if cfg.controller_policy_enabled:
            controller_policy.clear_stream_markers()
            log["actions"].append({"controller_policy_cleared": True})
    except Exception as exc:
        logging.warning("controller_policy prep_stop: %s", exc)

    try:
        from host_tuning import wan_setup

        wan_setup.on_session_stop()
        log["actions"].append({"wan": "hold_then_unmap"})
    except Exception as exc:
        logging.warning("wan map prep_stop: %s", exc)

    try:
        from host_tuning import couch_coop

        couch_coop.clear_stream_active()
    except Exception:
        pass

    return log


def global_prep_cmds(cfg: Optional[HostTuningConfig] = None) -> List[Dict[str, str]]:
    """Return Sunshine prep-cmd entries to merge into every imported app."""
    cfg = cfg or load_config()
    if not cfg.enabled:
        return []
    write_prep_scripts()
    if os.name == "nt":
        script = os.path.join(config_dir(), "gamesphere-host-prep.ps1")
        if not os.path.isfile(script):
            return []
        return [{
            "do": f'powershell -NoProfile -ExecutionPolicy Bypass -File "{script}" start',
            "undo": f'powershell -NoProfile -ExecutionPolicy Bypass -File "{script}" stop',
            "elevated": False,
        }]
    script = os.path.expanduser("~/.local/bin/gamesphere-host-prep.sh")
    if not os.path.isfile(script):
        return []
    return [{"do": f"{script} start", "undo": f"{script} stop", "elevated": False}]


def write_prep_scripts(repo_root: str = "") -> None:
    """Install host prep wrapper scripts next to gamesphere-steam-close."""
    here = repo_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_sh = os.path.join(here, "scripts", "gamesphere-host-prep.sh")
    src_ps1 = os.path.join(here, "scripts", "gamesphere-host-prep.ps1")
    if os.name == "nt":
        dest = os.path.join(config_dir(), "gamesphere-host-prep.ps1")
        if os.path.isfile(src_ps1):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(src_ps1, "r", encoding="utf-8") as fh:
                content = fh.read()
            with open(dest, "w", encoding="utf-8", newline="\r\n") as fh:
                fh.write(content)
    else:
        dest = os.path.expanduser("~/.local/bin/gamesphere-host-prep.sh")
        if os.path.isfile(src_sh):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(src_sh, "r", encoding="utf-8") as fh:
                content = fh.read()
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.chmod(dest, 0o755)
