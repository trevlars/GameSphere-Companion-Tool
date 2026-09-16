"""
TCP bridge for GameSphere clients (StreamTweak-compatible subset on port 47998).

Supported verbs: CAPS, NETINFO, SETSPEED, RESTORE, STATUS, STATS, TAILSCALE,
LASTSESSION, SESSIONDATA, APPSTORES, PLAYTIMES, GAMESTATE, LAUNCHRESULT, LOCKSTATE,
INVITE, JOINPIN, INVITEEND, JOINREQ, JOINPENDING, JOINACK, JOINSTATUS, TRUSTED,
HOSTINFO, COOPSTATE, SLOTSWAP, WANSETUP, VOICE, WANNAPLAY, PLAYREG, PLAYPENDING,
PLAYCLAIM, PLAYREPLY, PROFILE, INPUTRELAY, COOPKICK, SESSIONEND.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import socketserver
import subprocess
import threading
from typing import Any, Callable, Dict, Optional

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
            "LASTSESSION SESSIONDATA APPSTORES PLAYTIMES GAMESTATE LAUNCHRESULT LOCKSTATE "
            "INVITE JOINPIN INVITEEND JOINREQ JOINPENDING JOINACK JOINSTATUS TRUSTED "
            "HOSTINFO COOPSTATE SLOTSWAP WANSETUP VOICE "
            "WANNAPLAY PLAYREG PLAYPENDING PLAYCLAIM PLAYREPLY PROFILE "
            "INPUTRELAY COOPKICK SESSIONEND BUDDYSET"
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
                    try:
                        from host_tuning import coop_pause

                        coop_pause.note_sample(batch)
                    except Exception:
                        logging.debug("coop_pause sample failed", exc_info=True)
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
            elif verb == "LAUNCHRESULT":
                recent = monitor._recent_lines if monitor else []
                self._reply(launch_watcher.launch_result_json(recent))
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
                try:
                    from host_tuning import couch_coop

                    couch_coop.clear_stream_active()
                except Exception:
                    pass
                try:
                    from host_tuning import wanna_play

                    wanna_play.end_session()
                except Exception:
                    pass
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
            elif verb == "HOSTINFO":
                self._reply(json.dumps(_hostinfo_json()))
            elif verb == "COOPSTATE":
                self._reply(json.dumps(_coopstate_json(arg)))
            elif verb == "SLOTSWAP":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    self._reply(json.dumps(_slotswap(payload)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "WANSETUP":
                from host_tuning import wan_setup

                payload = {}
                if arg:
                    try:
                        parsed = json.loads(arg)
                        if isinstance(parsed, dict):
                            payload = parsed
                    except json.JSONDecodeError:
                        payload = {}
                if payload.get("map") or payload.get("ensure"):
                    result = wan_setup.ensure(reason="wansetup")
                elif payload.get("unmap") or payload.get("release"):
                    result = wan_setup.release(reason="cli")
                else:
                    result = wan_setup.status()
                self._reply(json.dumps(result))
            elif verb == "VOICE":
                self._reply(json.dumps(_voice_cmd(arg)))
            elif verb == "WANNAPLAY":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    self._reply(json.dumps(_wannaplay(payload)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "PLAYREG":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    from host_tuning import wanna_play

                    self._reply(json.dumps(wanna_play.register_device(payload)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "PLAYPENDING":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    from host_tuning import wanna_play

                    uuid = str(payload.get("uuid") or payload.get("guestUuid") or "").strip()
                    self._reply(json.dumps(wanna_play.pending_for(uuid)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "PLAYCLAIM":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    from host_tuning import wanna_play

                    self._reply(json.dumps(wanna_play.claim(payload)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "PLAYREPLY":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    from host_tuning import play_reply

                    self._reply(json.dumps(play_reply.record(payload)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "PROFILE":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    from host_tuning import device_profiles

                    self._reply(json.dumps(device_profiles.handle(payload)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "BUDDYSET":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    self._reply(json.dumps(_buddyset(payload)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "INPUTRELAY":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    from host_tuning import input_relay

                    self._reply(json.dumps(input_relay.handle(payload)))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "COOPKICK":
                try:
                    payload = json.loads(arg or "{}") if arg else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    from host_tuning import coop_session

                    result = coop_session.kick(payload)
                    logging.info("COOPKICK ok=%s uuid=%s", result.get("ok"), result.get("uuid"))
                    self._reply(json.dumps(result))
                except json.JSONDecodeError:
                    self._reply(json.dumps({"ok": False, "error": "bad_json"}))
            elif verb == "SESSIONEND":
                payload: Dict[str, Any] = {}
                if arg:
                    try:
                        parsed = json.loads(arg)
                        if isinstance(parsed, dict):
                            payload = parsed
                    except json.JSONDecodeError:
                        payload = {"reason": arg.strip()}
                from host_tuning import coop_session

                result = coop_session.session_end(payload)
                logging.info("SESSIONEND reason=%s", result.get("reason"))
                self._reply(json.dumps(result))
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
            couch_coop.clear_stream_active()

        def _on_start(_e):
            couch_coop.mark_stream_active()
            couch_coop.arm_late_join()
            couch_coop.apply("session_start")
            try:
                from host_tuning import wan_setup

                wan_setup.on_session_start()
            except Exception:
                logging.debug("wan map on stream start", exc_info=True)

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
        try:
            from host_tuning import nat_map

            nat_map.revoke_web_ui_if_mapped()
        except Exception:
            logging.debug("revoke 47990 on bridge start", exc_info=True)
        try:
            from host_tuning import voice_bridge

            voice_bridge.start()
        except Exception:
            logging.exception("voice_bridge start")
        try:
            from host_tuning import buddy_relay

            buddy_relay.start()
        except Exception:
            logging.exception("buddy_relay start")
        try:
            from host_tuning import zerotier

            # LAN guard: ZeroTier must never own 10.0.5.0/24 or voice/LAN discovery dies.
            zerotier.start_guard_timer()
        except Exception:
            logging.debug("zerotier guard start", exc_info=True)
        try:
            from host_tuning import metadata_catalog

            # Warm owned-apps + ROM hashes off-thread so the first HOSTINFO is not empty.
            metadata_catalog.cached(kick=True)
        except Exception:
            logging.debug("metadata_catalog warm", exc_info=True)
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

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._server)

    def stop(self) -> None:
        if self._coop_watch:
            self._coop_watch.stop()
            self._coop_watch = None
        try:
            from host_tuning import voice_bridge

            voice_bridge.stop()
        except Exception:
            pass
        try:
            from host_tuning import buddy_relay

            buddy_relay.stop()
        except Exception:
            pass
        if self.monitor:
            self.monitor.stop()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        self._server = None


def _push_fields() -> Dict[str, Any]:
    try:
        from host_tuning import apns

        info = apns.status_public()
        return {
            "pushReady": bool(info.get("pushReady")),
            "pushStatus": str(info.get("pushStatus") or ""),
        }
    except Exception:
        return {
            "pushReady": False,
            "pushStatus": (
                "Lock-screen Wanna play needs an APNs Auth Key (.p8) on this PC — "
                "friends still get the ping if GameSphere is open."
            ),
        }


def _hostinfo_json() -> str:
    from host_tuning import host_identity
    from host_tuning import wan_setup
    from host_tuning import voice_bridge

    ident = host_identity.snapshot()
    wan = wan_setup.status()
    voice = voice_bridge.status()
    push = _push_fields()
    payload = {
        "ok": True,
        "maxPlayers": 4,
        "lanHost": wan.get("lanHost") or "",
        "wanHost": wan.get("wanHost") or "",
        "wanReady": bool(wan.get("wanReady")),
        "wanStatus": wan.get("status") or "",
        "voicePort": voice.get("port") or 48020,
        "voiceRunning": bool(voice.get("running")),
        "tailscaleHost": wan.get("tailscaleHost") or "",
        "zerotierHost": wan.get("zerotierHost") or "",
        "zerotierStatus": wan.get("zerotierStatus") or "",
        **push,
        **ident,
    }
    try:
        from host_tuning import device_profiles

        host_profile = device_profiles.host_profile()
        profiles = device_profiles.public_list()
        if host_profile:
            payload["hostProfile"] = host_profile
            if host_profile.get("avatarUrl"):
                payload["profileAvatarUrl"] = host_profile.get("avatarUrl")
            if host_profile.get("name"):
                payload["profileName"] = host_profile.get("name")
        if profiles:
            payload["profiles"] = profiles
    except Exception:
        logging.debug("device_profiles hostinfo failed", exc_info=True)
    payload.update(_catalog_fields())
    return payload


def _catalog_fields() -> Dict[str, Any]:
    """Owned Steam apps + ROM hashes. Never blocks HOSTINFO: the scan runs in the
    background and this returns whatever is cached (``catalogReady`` says whether
    a full scan has completed yet)."""
    try:
        from host_tuning import metadata_catalog

        meta = metadata_catalog.cached(kick=True)
    except Exception:
        logging.debug("metadata_catalog hostinfo failed", exc_info=True)
        return {"catalogReady": False, "ownedApps": [], "romHashes": []}
    return {
        "catalogReady": bool(meta.get("ready")),
        "ownedApps": meta.get("ownedApps") or [],
        "romHashes": meta.get("romHashes") or [],
    }


def _coopstate_json(arg: str) -> Dict:
    from host_tuning import coop_pause
    from host_tuning import host_identity
    from host_tuning import wan_setup
    from host_tuning import voice_bridge

    if arg:
        try:
            payload = json.loads(arg)
            if isinstance(payload, dict) and payload.get("hostUnpaused"):
                coop_pause.host_unpaused()
        except json.JSONDecodeError:
            pass
    pause = coop_pause.snapshot()
    ident = host_identity.snapshot()
    wan = wan_setup.status()
    voice = voice_bridge.status()
    coop = couch_coop.status()
    try:
        from host_tuning import wanna_play

        wp = wanna_play.public_session()
    except Exception:
        wp = None
    try:
        from host_tuning import play_reply

        chat = play_reply.coopstate_fields()
    except Exception:
        chat = {
            "coopChat": [],
            "playReplies": [],
            "playReply": None,
            "lastReply": None,
        }
    out = {
        "ok": True,
        "maxPlayers": 4,
        "players": coop.get("players") or [],
        "slot_lock": coop.get("slot_lock") or [],
        "streamActive": bool(couch_coop.stream_active()),
        "pauseRecommended": pause.get("pauseRecommended"),
        "paused": pause.get("paused"),
        "reason": pause.get("reason") or "",
        "clientCount": pause.get("clientCount") or 0,
        "multiplayer": pause.get("multiplayer"),
        "clients": pause.get("clients") or [],
        "voicePort": voice.get("port") or 48020,
        "voiceRunning": bool(voice.get("running")),
        **_buddy_fields(),
        "lanHost": wan.get("lanHost") or "",
        "wanHost": wan.get("wanHost") or "",
        "wanReady": bool(wan.get("wanReady")),
        "wanStatus": wan.get("status") or "",
        "wannaPlay": wp,
        **chat,
        **_push_fields(),
        **_session_fields(),
        "zerotierHost": wan.get("zerotierHost") or "",
        **ident,
    }
    try:
        from host_tuning import device_profiles

        host_profile = device_profiles.host_profile()
        profiles = device_profiles.public_list()
        if host_profile:
            out["hostProfile"] = host_profile
        if profiles:
            out["profiles"] = profiles
    except Exception:
        logging.debug("device_profiles coopstate failed", exc_info=True)
    try:
        from host_tuning import input_relay

        relay = input_relay.status()
        out["inputRelay"] = bool(relay.get("merge"))
        out["inputRelayBuddySlot"] = relay.get("buddySlot") or 1
    except Exception:
        logging.debug("input_relay coopstate failed", exc_info=True)
    return out


def _session_fields() -> Dict[str, Any]:
    """COOPKICK / SESSIONEND events for guests polling COOPSTATE."""
    try:
        from host_tuning import coop_session

        return coop_session.coopstate_fields()
    except Exception:
        logging.debug("coop_session coopstate failed", exc_info=True)
        return {"sessionEvents": [], "sessionEndedAt": None, "sessionEndReason": ""}


def _buddy_fields() -> Dict:
    """COOPSTATE additions for buddy mode. Safe when the relay never started."""
    try:
        from host_tuning import buddy_relay

        st = buddy_relay.status()
    except Exception:
        st = {}
    return {
        "buddyPort": st.get("port") or 48021,
        "buddyRelayRunning": bool(st.get("running")),
        "buddyHostPresent": bool(st.get("hostPresent")),
        "buddyIds": st.get("buddies") or [],
    }


def _buddyset(payload: Dict) -> Dict:
    """Host toggles a seat: {"slot": 2, "buddy": true} or {"reqId": "...", "buddy": false}.

    {"status": true} returns relay status only. The relay is started on demand so
    a buddy toggle on an older bridge start still works without a restart.
    """
    from host_tuning import buddy_relay

    if payload.get("status") or payload.get("query"):
        return buddy_relay.status()
    try:
        started = buddy_relay.start()
    except OSError as exc:
        started = {"ok": False, "error": str(exc)}
    role = "buddy" if payload.get("buddy", True) else "guest"
    if payload.get("role") in ("buddy", "guest"):
        role = str(payload.get("role"))
    result: Dict = {"ok": False, "error": "missing_slot"}
    if payload.get("slot") is not None:
        try:
            result = couch_coop.set_slot_role(int(payload.get("slot")), role)
        except (TypeError, ValueError):
            result = {"ok": False, "error": "bad_slot"}
    elif payload.get("reqId") or payload.get("clientId") or payload.get("uuid"):
        ident = str(payload.get("reqId") or payload.get("clientId") or payload.get("uuid"))
        result = couch_coop.set_role_for_client(ident, role)
    elif not payload:
        result = {"ok": True}
    result["relay"] = started
    result.update(_buddy_fields())
    return result


def _slotswap(payload: Dict) -> Dict:
    order = payload.get("order") or payload.get("slots") or []
    if not isinstance(order, list) or len(order) < 2:
        return {"ok": False, "error": "missing_order"}
    ints = []
    for item in order:
        try:
            ints.append(int(item))
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad_order"}
    return couch_coop.host_swap(ints)


def _wannaplay(payload: Dict) -> Dict:
    from host_tuning import wanna_play

    if payload.get("end") or str(payload.get("action") or "").lower() == "end":
        wanna_play.end_session()
        return {"ok": True, "ended": True}
    return wanna_play.start(payload)


def _voice_cmd(arg: str) -> Dict:
    from host_tuning import voice_bridge

    cmd = (arg or "status").strip().split()
    action = (cmd[0] if cmd else "status").lower()
    if action == "start":
        return voice_bridge.start()
    if action == "stop":
        voice_bridge.stop()
        return {"ok": True, "stopped": True}
    return voice_bridge.status()


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
