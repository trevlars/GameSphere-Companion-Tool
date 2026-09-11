#!/usr/bin/env python3
"""CLI for GameSphere host tuning (StreamTweak-inspired features)."""

from __future__ import annotations

import argparse
import json
import sys
import time

from host_tuning.bridge import GameSphereBridge
from host_tuning.config import HostTuningConfig, ManagedAppEntry, config_path, load_config, save_config
from host_tuning.service import apply_host_tuning, prep_start, prep_stop, write_prep_scripts
from host_tuning import host_assets
from host_tuning import link_speed
from host_tuning import nvidia_sentinel
from host_tuning import session_telemetry
from host_tuning import tailscale
from gs_version import __version__


def cmd_apply(args: argparse.Namespace) -> int:
    write_prep_scripts()
    cfg = load_config()
    if args.enable:
        cfg.enabled = True
    results = apply_host_tuning(cfg, sunshine_apps_json=args.apps_json or "")
    print(json.dumps(results, indent=2))
    save_config(cfg)
    return 0


def cmd_prep(args: argparse.Namespace) -> int:
    write_prep_scripts()
    if args.action == "start":
        print(json.dumps(prep_start(), indent=2))
    else:
        print(json.dumps(prep_stop(), indent=2))
    return 0


def cmd_bridge(args: argparse.Namespace) -> int:
    cfg = load_config()
    port = args.port or cfg.bridge_port
    bridge = GameSphereBridge()
    log_path = session_telemetry.detect_sunshine_log_path(cfg.sunshine_log_path)
    bridge.start(
        port=port,
        log_path=log_path,
        apps_json_path=(
            os.environ.get("SUNSHINE_APPS_JSON_PATH")
            or os.environ.get("sunshine_apps_json_path")
            or ""
        ),
    )
    print(f"Bridge listening on TCP {port} (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bridge.stop()
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    cfg = load_config()
    log_path = session_telemetry.detect_sunshine_log_path(cfg.sunshine_log_path)
    if args.tail:
        if not log_path:
            print("Sunshine log not found — set sunshine_log_path in host_tuning.json", file=sys.stderr)
            return 1
        monitor = session_telemetry.SessionLogMonitor(log_path)
        monitor.start()
        print(f"Tailing {log_path} (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            monitor.stop()
        return 0
    sessions = session_telemetry.load_sessions()
    print(json.dumps(sessions[-10:], indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    adapter = link_speed.find_wired_adapter(cfg.network_adapter)
    detected, ip = tailscale.detect_tailscale()
    payload = {
        "config": config_path(),
        "enabled": cfg.enabled,
        "adapter": adapter,
        "link": link_speed.get_link_info(adapter) if adapter else {},
        "tailscale": {"detected": detected, "ip": ip},
        "nvidia": nvidia_sentinel.driver_info(),
        "sunshine_log": session_telemetry.detect_sunshine_log_path(cfg.sunshine_log_path),
        "sessions_count": len(session_telemetry.load_sessions()),
        "host_tiles_applied": host_assets.is_applied(host_assets.find_assets_dir() or ""),
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_config_init(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.enable_all:
        cfg.enabled = True
        cfg.link_speed_enabled = True
        cfg.session_telemetry_enabled = True
        cfg.tailscale_enabled = True
        cfg.host_tiles_enabled = True
        cfg.bridge_enabled = True
    path = save_config(cfg)
    write_prep_scripts()
    print(f"Wrote {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="GameSphere host tuning")
    parser.add_argument("--version", action="version", version=f"host-tuning {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_apply = sub.add_parser("apply", help="Apply host tuning (tiles, NVIDIA snapshot, detect paths)")
    p_apply.add_argument("--enable", action="store_true")
    p_apply.add_argument("--apps-json", default="")
    p_apply.set_defaults(func=cmd_apply)

    p_prep = sub.add_parser("prep", help="Run stream prep start/stop hooks")
    p_prep.add_argument("action", choices=["start", "stop"])
    p_prep.set_defaults(func=cmd_prep)

    p_bridge = sub.add_parser("bridge", help="Run TCP bridge on port 47998")
    p_bridge.add_argument("--port", type=int, default=0)
    p_bridge.set_defaults(func=cmd_bridge)

    p_sessions = sub.add_parser("sessions", help="Show or tail session history")
    p_sessions.add_argument("--tail", action="store_true")
    p_sessions.set_defaults(func=cmd_sessions)

    sub.add_parser("status", help="Show host tuning status").set_defaults(func=cmd_status)

    p_init = sub.add_parser("init", help="Create default host_tuning.json")
    p_init.add_argument("--enable-all", action="store_true")
    p_init.set_defaults(func=cmd_config_init)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
