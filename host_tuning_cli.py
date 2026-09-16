#!/usr/bin/env python3
"""CLI for GameSphere host tuning (StreamTweak-inspired features)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

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
    from host_tuning.host_daemon import run_bridge_forever

    return run_bridge_forever(port=args.port or 0)


def cmd_daemon(args: argparse.Namespace) -> int:
    from host_tuning import host_daemon

    action = getattr(args, "action", None) or "status"
    if action == "install":
        print(json.dumps(host_daemon.ensure_running(), indent=2))
        return 0
    if action == "uninstall":
        print(json.dumps(host_daemon.uninstall_autostart(), indent=2))
        return 0
    if action == "restart":
        print(json.dumps(host_daemon.restart_host_bridge_only(), indent=2))
        return 0
    if action == "run":
        return host_daemon.run_bridge_forever()
    print(json.dumps(host_daemon.status(), indent=2))
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
    try:
        from host_tuning import wan_setup

        wan = wan_setup.status()
        payload["wan"] = {
            "wanReady": wan.get("wanReady"),
            "status": wan.get("status"),
            "mapper": wan.get("mapper"),
            "lanHost": wan.get("lanHost"),
            "wanHost": wan.get("wanHost"),
        }
    except Exception:
        pass
    print(json.dumps(payload, indent=2))
    return 0


def cmd_coop(args: argparse.Namespace) -> int:
    from host_tuning import couch_coop

    if args.action == "apply":
        print(json.dumps(couch_coop.apply("cli", force=True), indent=2))
    elif args.action == "swap":
        order = [int(x) for x in (args.order or "1,0,2,3").split(",")]
        print(json.dumps(couch_coop.host_swap(order), indent=2))
    else:
        print(json.dumps(couch_coop.status(), indent=2))
    return 0


def cmd_wan(args: argparse.Namespace) -> int:
    from host_tuning import wan_setup

    action = getattr(args, "action", None) or "status"
    if action == "map":
        data = wan_setup.ensure(reason="cli")
        print(json.dumps(data, indent=2) if args.json else wan_setup.print_text())
        return 0 if data.get("wanReady") else 1
    if action == "unmap":
        data = wan_setup.release(reason="cli")
        print(json.dumps(data, indent=2) if args.json else wan_setup.print_text())
        return 0
    if args.json:
        print(json.dumps(wan_setup.status(), indent=2))
        return 0
    print(wan_setup.print_text())
    return 0


def cmd_wanna(args: argparse.Namespace) -> int:
    from host_tuning import wanna_play
    from host_tuning import apns

    push = apns.status_public()
    if args.action == "end":
        wanna_play.end_session()
        print(json.dumps({"ok": True, "ended": True, **{k: push[k] for k in ("pushReady", "pushStatus")}}))
        return 0
    if args.action == "start":
        started = wanna_play.start(
            {
                "appId": args.app_id or "",
                "appName": args.app_name or "this game",
                "hostId": args.host_id or "",
            }
        )
        print(json.dumps(started, indent=2))
        return 0
    session = wanna_play.public_session()
    print(
        json.dumps(
            {
                "ok": True,
                "session": session,
                "pushReady": push.get("pushReady"),
                "pushStatus": push.get("pushStatus"),
            },
            indent=2,
        )
    )
    return 0


def cmd_voice(args: argparse.Namespace) -> int:
    from host_tuning import voice_bridge

    if args.action == "start":
        print(json.dumps(voice_bridge.start(), indent=2))
        return 0
    if args.action == "stop":
        voice_bridge.stop()
        print(json.dumps({"ok": True, "stopped": True}))
        return 0
    print(json.dumps(voice_bridge.status(), indent=2))
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

    p_bridge = sub.add_parser("bridge", help="Run TCP bridge on port 47998 (foreground daemon)")
    p_bridge.add_argument("--port", type=int, default=0)
    p_bridge.set_defaults(func=cmd_bridge)

    p_daemon = sub.add_parser("daemon", help="Install / status / restart the always-on host daemon")
    p_daemon.add_argument(
        "action",
        choices=["status", "install", "uninstall", "restart", "run"],
        nargs="?",
        default="status",
    )
    p_daemon.set_defaults(func=cmd_daemon)

    p_sessions = sub.add_parser("sessions", help="Show or tail session history")
    p_sessions.add_argument("--tail", action="store_true")
    p_sessions.set_defaults(func=cmd_sessions)

    sub.add_parser("status", help="Show host tuning status").set_defaults(func=cmd_status)

    p_coop = sub.add_parser("coop", help="Couch co-op P1–P4 (Sunshine + Steam Input slots)")
    p_coop.add_argument("action", choices=["status", "apply", "swap"], nargs="?", default="status")
    p_coop.add_argument("--order", default="", help="SLOTSWAP order, e.g. 1,0,2,3")
    p_coop.set_defaults(func=cmd_coop)

    p_wan = sub.add_parser("wan", help="Auto WAN mapping status (UPnP/NAT-PMP; never 47990)")
    p_wan.add_argument("action", choices=["status", "map", "unmap"], nargs="?", default="status")
    p_wan.add_argument("--json", action="store_true")
    p_wan.set_defaults(func=cmd_wan)

    p_wanna = sub.add_parser("wanna", help="Wanna-play session pre-auth (trusted clients)")
    p_wanna.add_argument("action", choices=["status", "start", "end"], nargs="?", default="status")
    p_wanna.add_argument("--app-id", default="")
    p_wanna.add_argument("--app-name", default="")
    p_wanna.add_argument("--host-id", default="")
    p_wanna.set_defaults(func=cmd_wanna)

    p_voice = sub.add_parser("voice", help="In-stream voice mixer (UDP PCM, no HDMI AEC)")
    p_voice.add_argument("action", choices=["status", "start", "stop"], nargs="?", default="status")
    p_voice.set_defaults(func=cmd_voice)

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
