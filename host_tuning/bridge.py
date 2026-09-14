"""
TCP bridge for GameSphere clients (StreamTweak-compatible subset on port 47998).

Supported verbs: CAPS, NETINFO, SETSPEED, RESTORE, STATUS, STATS, TAILSCALE,
LASTSESSION, SESSIONDATA, APPSTORES, PLAYTIMES, GAMESTATE, LOCKSTATE,
INVITE, JOINPIN, INVITEEND, JOINREQ, JOINPENDING, JOINACK, JOINSTATUS, TRUSTED.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import socketserver
import subprocess
import threading
from typing import Callable, Optional

from host_tuning.config import load_config
from host_tuning import app_stores
from host_tuning import steam_playtime
from host_tuning import launch_watcher
from host_tuning import link_speed
from host_tuning import lock_state
from host_tuning import session_telemetry
from host_tuning import tailscale
from host_tuning import invite as guest_invite
from host_tuning import join_request
from host_tuning import couch_coop


class _BridgeHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            line = self.rfile.readline(4096).decode("utf-8", errors="ignore").strip()
            if not line:
                return
            parts = line.split(None, 1)
            verb = parts[0].upper()
            arg = parts[1] if len(parts) > 1 else ""
            cfg = load_config()
            if cfg.bridge_require_auth and verb not in ("CAPS",):
                secret = cfg.bridge_shared_secret
                if secret and arg.startswith(f"AUTH:{secret}:"):
                    arg = arg[len(secret) + 6 :]
                elif secret:
                    self._reply("ERR_UNAUTHORIZED")
                    return

            monitor = getattr(self.server, "session_monitor", None)
            app_stores_provider = getattr(self.server, "app_stores_provider", None)
            playtimes_provider = getattr(self.server, "playtimes_provider", None)

            adapter = link_speed.find_wired_adapter(cfg.network_adapter)
            active = monitor.session_active if monitor else False

            if verb == "CAPS":
                self._reply(
                    "CAPS NETINFO SETSPEED RESTORE STATUS STATS TAILSCALE "
                    "LASTSESSION SESSIONDATA APPSTORES PLAYTIMES GAMESTATE LOCKSTATE "
                    "INVITE JOINPIN INVITEEND JOINREQ JOINPENDING JOINACK JOINSTATUS TRUSTED"
                )
            elif verb == "NETINFO":
                self._reply(link_speed.netinfo_json(adapter or "", active))
            elif verb == "SETSPEED":
                try:
                    mbps = int(arg.split()[0])
                except (ValueError, IndexError):
                    self._reply("ERR")
                    return
                code, _msg = link_speed.request_client_speed(adapter or "", mbps)
                self._reply(code)
            elif verb == "RESTORE":
                if adapter:
                    ok, _ = link_speed.restore_link_speed(adapter)
                    self._reply("OK" if ok else "ERR")
                else:
                    self._reply("ERR")
            elif verb == "STATUS":
                info = link_speed.get_link_info(adapter) if adapter else {}
                self._reply(str(info.get("current_mbps") or "UNKNOWN"))
            elif verb == "STATS":
                self._reply(_host_stats_json())
            elif verb == "TAILSCALE":
                detected, ip = tailscale.detect_tailscale()
                self._reply(ip if detected and ip else "NOT_DETECTED")
            elif verb == "LASTSESSION":
                self._reply(session_telemetry.last_session_json())
            elif verb == "SESSIONDATA":
                try:
                    batch = json.loads(arg or "{}")
                    session_telemetry.append_client_telemetry(batch)
                    self._reply("OK")
                except json.JSONDecodeError:
                    self._reply("ERR")
            elif verb == "APPSTORES":
                if app_stores_provider:
                    self._reply(app_stores_provider())
                else:
                    self._reply("{}")
            elif verb == "PLAYTIMES":
                if playtimes_provider:
                    self._reply(playtimes_provider())
                else:
                    self._reply("{\"games\":[]}")
            elif verb == "GAMESTATE":
                recent = monitor._recent_lines if monitor else []
                self._reply(launch_watcher.game_state_json(recent))
            elif verb == "LOCKSTATE":
                self._reply(lock_state.lock_state_json())
            elif verb == "INVITE":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    result = guest_invite.mint(payload)
                    logging.info("INVITE ok=%s lan=%s", result.get("ok"), result.get("lanHost"))
                    self._reply(json.dumps(result))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "JOINPIN":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    result = guest_invite.submit_pin(payload)
                    logging.info("JOINPIN ok=%s error=%s", result.get("ok"), result.get("error"))
                    self._reply(json.dumps(result))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "INVITEEND":
                token = ""
                if arg:
                    try:
                        payload = json.loads(arg)
                        if isinstance(payload, dict):
                            token = str(payload.get("token") or "")
                        else:
                            token = arg.strip()
                    except json.JSONDecodeError:
                        token = arg.strip()
                self._reply(json.dumps(guest_invite.end_invite(token)))
            elif verb == "JOINREQ":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    self._reply(json.dumps(join_request.create(payload)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "JOINPENDING":
                self._reply(json.dumps(join_request.pending()))
            elif verb == "JOINACK":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    self._reply(json.dumps(join_request.ack(payload)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "JOINSTATUS":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    self._reply(json.dumps(join_request.status(payload)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "TRUSTED":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    uuid = str(payload.get("uuid") or payload.get("guestUuid") or "").strip()
                    self._reply(json.dumps(join_request.mark_trusted(uuid)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            else:
                self._reply("ERR_UNKNOWN")
        except Exception as exc:
            logging.debug("Bridge handler error: %s", exc)
            try:
                self._reply("ERR")
            except Exception:
                pass

    def _reply(self, text: str) -> None:
        self.wfile.write((text + "\n").encode("utf-8"))
        self.wfile.flush()


class GameSphereBridge:
    def __init__(self):
        self._server: Optional[socketserver.ThreadingTCPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.monitor = session_telemetry.SessionLogMonitor("")
        self._coop_watch: Optional[couch_coop.CouchCoopWatch] = None
        self.app_stores_provider: Optional[Callable[[], str]] = None
        self.playtimes_provider: Optional[Callable[[], str]] = None

    def start(self, port: int = 47998, log_path: str = "", apps_json_path: str = "") -> None:
        cfg = load_config()
        apps_path = (
            apps_json_path
            or os.environ.get("SUNSHINE_APPS_JSON_PATH")
            or os.environ.get("sunshine_apps_json_path")
            or ""
        )
        steam_vdf = ""
        try:
            from platform_paths import detect_paths

            detected = detect_paths()
            if detected:
                if not apps_path:
                    apps_path = detected.sunshine_apps_json
                steam_vdf = detected.steam_library_vdf or ""
        except Exception:
            steam_vdf = ""
        self.app_stores_provider = lambda: app_stores.app_stores_json(apps_path)
        self.playtimes_provider = lambda: steam_playtime.playtimes_json(apps_path, steam_vdf)
        def _on_stop(_e):
            adapter_name = link_speed.find_wired_adapter(cfg.network_adapter) or ""
            if adapter_name:
                link_speed.restore_link_speed(adapter_name)
            guest_invite.on_session_stop()

        def _on_start(_e):
            couch_coop.arm_late_join()
            couch_coop.apply("session_start")

        self.monitor = session_telemetry.SessionLogMonitor(
            log_path or session_telemetry.detect_sunshine_log_path(cfg.sunshine_log_path),
            on_start=_on_start,
            on_stop=_on_stop,
            on_coop_hint=couch_coop.on_sunshine_hint,
        )
        self.monitor.start()
        self._coop_watch = couch_coop.CouchCoopWatch()
        self._coop_watch.start()
        couch_coop.apply("bridge_start")
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server(("0.0.0.0", port), _BridgeHandler)
        self._server.session_monitor = self.monitor
        self._server.app_stores_provider = lambda: app_stores.app_stores_json(apps_path)
        self._server.playtimes_provider = lambda: steam_playtime.playtimes_json(apps_path, steam_vdf)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logging.info("GameSphere host bridge listening on TCP %s", port)

    def stop(self) -> None:
        if self._coop_watch:
            self._coop_watch.stop()
            self._coop_watch = None
        if self.monitor:
            self.monitor.stop()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        self._server = None


def _host_stats_json() -> str:
    import psutil

    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory().percent
    payload = {"cpu_pct": cpu, "mem_pct": mem, "gpu_pct": 0, "gpu_temp_c": 0, "enc_pct": 0}
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,utilization.encoder,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            if len(parts) >= 3:
                payload["gpu_pct"] = float(parts[0] or 0)
                payload["enc_pct"] = float(parts[1] or 0)
                payload["gpu_temp_c"] = float(parts[2] or 0)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return json.dumps(payload)
