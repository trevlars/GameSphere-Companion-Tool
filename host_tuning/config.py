"""Persistent host tuning configuration."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def config_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "GameSphere")
    else:
        path = os.path.expanduser("~/.config/gamesphere-import-tool")
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    return os.path.join(config_dir(), "host_tuning.json")


def sessions_path() -> str:
    return os.path.join(config_dir(), "sessions.json")


def state_path() -> str:
    return os.path.join(config_dir(), "host_tuning_state.json")


@dataclass
class ManagedAppEntry:
    name: str = ""
    path: str = ""
    auto_manage: bool = True


@dataclass
class HostTuningConfig:
    enabled: bool = False
    # Link speed (wired Ethernet only)
    link_speed_enabled: bool = False
    allow_client_link_control: bool = True
    network_adapter: str = ""  # empty = auto-detect first wired
    # Display / audio
    hdr_enabled: bool = False
    hdr_monitor: str = ""  # Windows friendly name or Linux output name
    spatial_audio_enabled: bool = False
    spatial_audio_device: str = "Steam Streaming Speakers"
    spatial_audio_format: str = "dolby"  # dolby | sonic
    # NVIDIA profile snapshot (best-effort; full DRS on Windows needs Profile Inspector)
    nvidia_sentinel_enabled: bool = False
    nvidia_auto_restore: bool = False
    # Managed apps (Hue Sync, RGB tools, etc.)
    managed_apps: List[ManagedAppEntry] = field(default_factory=list)
    # Host tile swap (Sunshine assets/desktop.png + steam.png)
    host_tiles_enabled: bool = False
    host_tiles_desktop_source: str = ""
    host_tiles_steam_source: str = ""
    # TCP bridge for GameSphere / Moonlight clients (TCP 47998 — StreamTweak-compatible subset)
    bridge_enabled: bool = False
    bridge_port: int = 47998
    bridge_require_auth: bool = False
    bridge_shared_secret: str = ""
    # Session telemetry from Sunshine log
    session_telemetry_enabled: bool = False
    session_discard_empty: bool = True
    sunshine_log_path: str = ""
    # Tailscale presence in bridge NETINFO/TAILSCALE
    tailscale_enabled: bool = False
    # Sunshine / Apollo web UI (localhost) — used to inject guest PINs and unpair
    sunshine_web_url: str = "https://127.0.0.1:47990"
    sunshine_username: str = ""
    sunshine_password: str = ""
    # Auto UPnP/NAT-PMP for remote join (never maps 47990). Idle unmap.
    wan_auto_map: bool = True
    # Manual router port forwards (TCP/UDP 47984–48010 to this PC). wanReady without UPnP.
    wan_manual_forward: bool = False
    # APNs Auth Key (.p8) — lock-screen Wanna play. Never store the PEM here.
    apns_key_id: str = ""
    apns_team_id: str = "ABG342Z7V2"
    apns_bundle_id: str = "com.moonlight.gamesphere"
    apns_key_path: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HostTuningConfig":
        apps_raw = data.pop("managed_apps", []) or []
        apps = []
        for item in apps_raw:
            if isinstance(item, dict):
                apps.append(ManagedAppEntry(**{k: item.get(k, v) for k, v in ManagedAppEntry().__dict__.items()}))
        cfg = cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data and k != "managed_apps"})
        cfg.managed_apps = apps
        return cfg

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["managed_apps"] = [asdict(a) for a in self.managed_apps]
        return d


def default_config() -> HostTuningConfig:
    return HostTuningConfig()


def load_config(path: Optional[str] = None) -> HostTuningConfig:
    p = path or config_path()
    if not os.path.isfile(p):
        cfg = default_config()
        save_config(cfg, p)
        return cfg
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return HostTuningConfig.from_dict(data)
    except (OSError, json.JSONDecodeError, TypeError):
        return default_config()


def save_config(cfg: HostTuningConfig, path: Optional[str] = None) -> str:
    from host_tuning.json_store import write_json_atomic

    return write_json_atomic(path or config_path(), cfg.to_dict())
