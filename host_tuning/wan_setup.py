"""Automagic WAN: map Sunshine + Companion ports, STUN public IP, one-line status.

Never maps or recommends forwarding 47990. Does not print Sunshine passwords.
Join URLs still carry host= + lan= + wan= (LAN first, then WAN — no hairpin).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from host_tuning import nat_map
from host_tuning import sunshine_wan
from host_tuning.config import load_config

SUNSHINE_TCP = list(nat_map.SUNSHINE_TCP)
SUNSHINE_UDP = list(nat_map.SUNSHINE_UDP)
VOICE_UDP = nat_map.VOICE_UDP
DO_NOT_FORWARD = list(nat_map.DO_NOT_MAP)

IDLE_HOLD_SECONDS = 20 * 60
STREAM_GRACE_SECONDS = 120
REFRESH_AFTER = 25 * 60

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_state: Dict[str, Any] = {
    "mapped": False,
    "mapper": "",
    "wanHost": "",
    "lanHost": "",
    "mappedPorts": [],
    "failed": [],
    "voiceMapped": False,
    "reason": "",
    "error": "",
    "status": "",
    "holdUntil": 0.0,
    "mappedAt": 0.0,
    "leaseUntil": 0.0,
    "wanReady": False,
}
_watch: Optional[threading.Thread] = None
_stop = threading.Event()
_stun_cache = {"ip": "", "at": 0.0}


def lan_ip() -> str:
    from host_tuning import invite as guest_invite

    return guest_invite._local_lan_ip()


def public_ip() -> str:
    now = time.time()
    cached = _stun_cache.get("ip") or ""
    if cached and now - float(_stun_cache.get("at") or 0) < 45:
        return cached
    ip = ""
    try:
        ip = nat_map.public_ip()
    except Exception:
        _log.debug("public_ip failed", exc_info=True)
    with _lock:
        if ip:
            _stun_cache["ip"] = ip
            _stun_cache["at"] = now
            if not _state.get("wanHost"):
                _state["wanHost"] = ip
        elif _state.get("wanHost"):
            ip = str(_state.get("wanHost") or "")
    return ip


def _sentence(*, ready: bool, mapper: str, error: str, cgnat: bool, tailscale_ip: str) -> str:
    if ready:
        how = {"upnp": "UPnP", "natpmp": "NAT-PMP", "pcp": "PCP"}.get(mapper, mapper or "the router")
        return f"Remote join is on — game ports mapped via {how} for this session only."
    if cgnat:
        extra = f" Tailscale is running ({tailscale_ip}) if both devices are on it." if tailscale_ip else ""
        return (
            "This network is behind carrier NAT, so UPnP cannot publish a public address."
            + extra
        )
    if error in ("no_igd", "natpmp_timeout", "pcp_timeout", "upnp_add_failed", "natpmp_failed", "pcp_failed"):
        extra = f" Tailscale is running ({tailscale_ip}) if both devices are on it." if tailscale_ip else ""
        return (
            "Remote join needs UPnP (or NAT-PMP) enabled on the router — Companion couldn’t open the game ports."
            + extra
        )
    if error == "no_lan_or_ports":
        return "Remote join isn’t ready — Companion couldn’t find this PC’s LAN address."
    if error:
        return "Remote join needs UPnP (or NAT-PMP) enabled on the router — Companion couldn’t open the game ports."
    return "Remote join is off until someone invites, starts Wanna play, or a stream begins."


def _tailscale_ip() -> str:
    try:
        from host_tuning import tailscale

        detected, ip = tailscale.detect_tailscale()
        if detected and ip:
            return ip
    except Exception:
        pass
    return ""


def _critical_ok(mapped: List[Dict[str, Any]]) -> bool:
    have = {(int(row["port"]), str(row["proto"]).upper()) for row in mapped}
    need = {
        (47984, "TCP"),
        (47989, "TCP"),
        (47998, "TCP"),
        (48010, "TCP"),
        (47998, "UDP"),
        (47999, "UDP"),
        (48000, "UDP"),
        (48010, "UDP"),
    }
    return need.issubset(have)


def _voice_wanted() -> bool:
    try:
        from host_tuning import voice_bridge

        return bool(voice_bridge.status().get("running"))
    except Exception:
        return False


def _stream_active() -> bool:
    try:
        from host_tuning import stream_sockets

        return bool(stream_sockets.stream_sockets_active())
    except Exception:
        return False


def _invite_hold_until(now: float) -> float:
    hold = 0.0
    try:
        from host_tuning import invite as guest_invite

        for row in guest_invite._load().get("invites") or []:
            if row.get("ended"):
                continue
            exp = float(row.get("expires") or 0)
            if exp > now:
                hold = max(hold, exp)
    except Exception:
        pass
    try:
        from host_tuning import wanna_play

        session = wanna_play.current_session()
        if session:
            # Pre-auth can last hours; mappings stay only a short window unless streaming.
            hold = max(hold, now + min(IDLE_HOLD_SECONDS, 15 * 60))
    except Exception:
        pass
    return hold


def _start_watch() -> None:
    global _watch
    if _watch and _watch.is_alive():
        return
    _stop.clear()
    _watch = threading.Thread(target=_watch_loop, name="gs-wan-map", daemon=True)
    _watch.start()


def _watch_loop() -> None:
    while not _stop.is_set():
        try:
            _tick()
        except Exception:
            _log.debug("wan map watch", exc_info=True)
        _stop.wait(20)


def _tick() -> None:
    now = time.time()
    with _lock:
        mapped = bool(_state.get("mapped"))
        hold_until = float(_state.get("holdUntil") or 0)
        lease_until = float(_state.get("leaseUntil") or 0)
        reason = str(_state.get("reason") or "")
        voice = bool(_state.get("voiceMapped"))
    if not mapped:
        return
    if _stream_active():
        with _lock:
            _state["holdUntil"] = now + STREAM_GRACE_SECONDS
        if lease_until and now > lease_until - 600:
            ensure(reason=reason or "refresh", voice=_voice_wanted() or voice)
        return
    extra = _invite_hold_until(now)
    if extra > hold_until:
        with _lock:
            _state["holdUntil"] = extra
        hold_until = extra
    if now < hold_until:
        if lease_until and now > lease_until - 600:
            ensure(reason=reason or "refresh", voice=_voice_wanted() or voice)
        return
    release(reason="idle")


def ensure(reason: str = "session", *, voice: Optional[bool] = None) -> Dict[str, Any]:
    """Map Sunshine + Companion ports. Safe to call often. Never maps 47990."""
    cfg = load_config()
    if not getattr(cfg, "wan_auto_map", True):
        return status()

    lan = lan_ip()
    voice_on = _voice_wanted() if voice is None else bool(voice)
    ports = nat_map.mapping_ports(voice=voice_on)
    now = time.time()
    _start_watch()

    reuse = False
    with _lock:
        already = bool(_state.get("mapped"))
        same_voice = bool(_state.get("voiceMapped")) == voice_on
        lease_until = float(_state.get("leaseUntil") or 0)
        if already and same_voice and lease_until - now > 600:
            _state["holdUntil"] = max(float(_state.get("holdUntil") or 0), now + IDLE_HOLD_SECONDS)
            _state["reason"] = reason
            _state["lanHost"] = lan or _state.get("lanHost") or ""
            reuse = True
            need_wan = not _state.get("wanHost")
        else:
            need_wan = False
    if reuse:
        if need_wan:
            wan = public_ip()
            if wan:
                with _lock:
                    if not _state.get("wanHost"):
                        _state["wanHost"] = wan
        return status()

    sunshine = {}
    try:
        sunshine = sunshine_wan.apply_recommended()
    except Exception as exc:
        _log.debug("sunshine WAN conf: %s", exc)
        sunshine = {"ok": False, "error": str(exc)}

    nat_map.revoke_web_ui_if_mapped()
    result = nat_map.map_ports(lan, ports, lease=nat_map.LEASE_SECONDS)
    stun = public_ip()
    igd_ip = result.public_ip or ""
    if igd_ip and not nat_map.is_cgnat_ipv4(igd_ip):
        wan = igd_ip
    else:
        wan = stun or igd_ip
    mapped_rows = [{"port": p, "proto": proto} for p, proto in result.mapped]
    failed_rows = [{"port": p, "proto": proto} for p, proto in result.failed]
    ready = bool(result.ok) and _critical_ok(mapped_rows) and bool(wan) and not nat_map.is_cgnat_ipv4(wan)
    cgnat = bool(wan) and nat_map.is_cgnat_ipv4(wan)
    ts = _tailscale_ip()
    sentence = _sentence(ready=ready, mapper=result.mapper, error=result.error, cgnat=cgnat, tailscale_ip=ts)

    with _lock:
        _state.update(
            {
                "mapped": bool(result.ok),
                "mapper": result.mapper,
                "wanHost": wan,
                "lanHost": lan,
                "mappedPorts": mapped_rows,
                "failed": failed_rows,
                "voiceMapped": voice_on and any(p == VOICE_UDP for p, proto in result.mapped),
                "reason": reason,
                "error": result.error if not ready else "",
                "status": sentence,
                "holdUntil": now + IDLE_HOLD_SECONDS,
                "mappedAt": now,
                "leaseUntil": now + nat_map.LEASE_SECONDS if result.ok else 0.0,
                "wanReady": ready,
                "sunshine": sunshine,
            }
        )
        if wan:
            _stun_cache["ip"] = wan
            _stun_cache["at"] = now
    _log.info("WAN map ready=%s mapper=%s reason=%s ports=%s", ready, result.mapper, reason, len(mapped_rows))
    return status()


def release(reason: str = "stop") -> Dict[str, Any]:
    """Drop mappings unless a stream is still up."""
    if reason != "idle" and _stream_active() and reason not in ("force", "cli"):
        _log.info("WAN unmap skipped — Sunshine stream still active")
        return status()
    lan = lan_ip()
    voice = True  # delete voice mapping too if we created it
    ports = nat_map.mapping_ports(voice=voice)
    try:
        nat_map.unmap_ports(lan, ports)
        nat_map.revoke_web_ui_if_mapped()
    except Exception:
        _log.debug("WAN unmap", exc_info=True)
    ts = _tailscale_ip()
    with _lock:
        _state.update(
            {
                "mapped": False,
                "mapper": "",
                "mappedPorts": [],
                "failed": [],
                "voiceMapped": False,
                "reason": reason,
                "error": "",
                "status": _sentence(ready=False, mapper="", error="", cgnat=False, tailscale_ip=ts),
                "holdUntil": 0.0,
                "leaseUntil": 0.0,
                "wanReady": False,
            }
        )
    _log.info("WAN mappings released (%s)", reason)
    return status()


def on_session_start() -> Dict[str, Any]:
    """Kick off WAN mapping without blocking Sunshine prep-cmd (15s cap)."""

    def _bg() -> None:
        try:
            ensure(reason="stream", voice=_voice_wanted())
        except Exception:
            _log.debug("WAN map on_session_start", exc_info=True)

    threading.Thread(target=_bg, name="gs-wan-map-start", daemon=True).start()
    return status()


def on_session_stop() -> None:
    with _lock:
        _state["holdUntil"] = time.time() + STREAM_GRACE_SECONDS
        if _state.get("mapped"):
            _state["reason"] = "stream_end"
    _start_watch()


def ensure_voice(running: bool) -> None:
    if not running:
        lan = lan_ip()
        try:
            nat_map.unmap_ports(lan, [(VOICE_UDP, "UDP")])
        except Exception:
            pass
        with _lock:
            _state["voiceMapped"] = False
        return
    if _state.get("mapped") or _stream_active():
        ensure(reason="voice", voice=True)


def cached_hosts() -> Dict[str, str]:
    """LAN/WAN already known — never STUN. JOINACK must not block on this."""
    lan = lan_ip()
    with _lock:
        wan = str(_state.get("wanHost") or "")
        lan = str(_state.get("lanHost") or "") or lan
    return {"lanHost": lan, "wanHost": wan}


def status() -> Dict[str, Any]:
    lan = lan_ip()
    with _lock:
        wan = str(_state.get("wanHost") or "")
    if not wan:
        wan = public_ip()
    ts = _tailscale_ip()
    zt_host = ""
    zt_status = ""
    try:
        from host_tuning import zerotier

        zt = zerotier.status()
        zt_host = str(zt.get("zerotierHost") or "")
        zt_status = str(zt.get("zerotierStatus") or "")
    except Exception:
        pass
    sunshine = {}
    try:
        sunshine = sunshine_wan.snapshot()
    except Exception:
        sunshine = {}
    with _lock:
        mapped = bool(_state.get("mapped"))
        mapper = str(_state.get("mapper") or "")
        error = str(_state.get("error") or "")
        ready = bool(_state.get("wanReady"))
        if _state.get("wanHost"):
            wan = str(_state.get("wanHost") or wan)
        if _state.get("lanHost"):
            lan = str(_state.get("lanHost") or lan)
        cgnat = bool(wan) and nat_map.is_cgnat_ipv4(wan)
        sentence = str(_state.get("status") or "") or _sentence(
            ready=ready, mapper=mapper, error=error, cgnat=cgnat, tailscale_ip=ts
        )
        payload = {
            "ok": True,
            "wanReady": ready,
            "status": sentence,
            "mapped": mapped,
            "mapper": mapper,
            "lanHost": lan,
            "wanHost": wan,
            "maxPlayers": 4,
            "tcp": SUNSHINE_TCP,
            "udp": SUNSHINE_UDP,
            "voiceUdp": VOICE_UDP,
            "voiceMapped": bool(_state.get("voiceMapped")),
            "doNotForward": DO_NOT_FORWARD,
            "mappedPorts": list(_state.get("mappedPorts") or []),
            "failed": list(_state.get("failed") or []),
            "holdUntil": int(_state.get("holdUntil") or 0),
            "leaseUntil": int(_state.get("leaseUntil") or 0),
            "reason": str(_state.get("reason") or ""),
            "tailscaleHost": ts,
            "zerotierHost": zt_host,
            "zerotierStatus": zt_status,
            "hairpin": (
                "LAN clients use lan= (private IP). Join URLs carry host= + lan= + wan= "
                "so GameSphere tries LAN serverinfo first, then WAN — never hairpin."
            ),
            "sunshine": sunshine,
            "sunshineConf": sunshine_wan.snippet(),
        }
    # Never leak Sunshine web login.
    payload.pop("sunshine_password", None)
    payload.pop("password", None)
    return payload


def checklist() -> Dict[str, Any]:
    """WANSETUP payload — status, not a router copy-paste checklist."""
    return status()


def print_text() -> str:
    data = status()
    lines = [
        data.get("status") or "",
        f"LAN: {data.get('lanHost') or '(unknown)'}    public: {data.get('wanHost') or '(unknown)'}",
    ]
    if data.get("mapped"):
        lines.append(
            f"Mapped via {data.get('mapper') or '?'} — TCP {', '.join(str(p) for p in SUNSHINE_TCP)}; "
            f"UDP {', '.join(str(p) for p in SUNSHINE_UDP)}"
            + (f" + UDP {VOICE_UDP} voice" if data.get("voiceMapped") else "")
        )
    lines.append("Never 47990 (Sunshine web UI is localhost only).")
    if data.get("tailscaleHost"):
        lines.append(f"Tailscale (optional): {data['tailscaleHost']}")
    lines.extend(["", "Sunshine (applied on next Sunshine restart, never mid-game):", data["sunshineConf"]])
    return "\n".join(lines) + "\n"
