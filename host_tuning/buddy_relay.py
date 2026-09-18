"""Buddy-mode controller relay (UDP).

A "buddy" is a second GameSphere device whose gamepad is merged into the host
phone's Sunshine controller slot instead of getting its own P2 pad. The buddy
device never sends controller reports to Sunshine; it sends compact input
frames here and the host phone merges them into its own P1 report.

This module is a dumb datagram relay so buddy and host never need each other's
address (works across Wi‑Fi / Ethernet / Tailscale the same way voice does):

    buddy  --INPUT-->  Companion:48021  --INPUT-->  host phone
    host   --HELLO-->  Companion:48021              (registers host addr, 1 Hz)
    buddy  --HELLO-->  Companion:48021  --STATUS--> buddy (hostPresent flag)

Packet layout (network byte order):

    0..3   magic  b"GSBD"
    4      version 1
    5      kind    1=HOST_HELLO 2=INPUT 3=BUDDY_HELLO 4=STATUS
    6      buddyId (0 for host)
    7      reserved
    8..    kind payload

    INPUT payload (16 bytes):
        u32 seq, u32 buttons, u8 lt, u8 rt, i16 lsx, i16 lsy, i16 rsx, i16 rsy
    STATUS payload (2 bytes):
        u8 hostPresent, u8 buddyCount

Only the single most-recent HOST_HELLO sender receives INPUT frames (one host
phone per Companion host). Idle peers age out after CLIENT_TTL seconds.
"""

from __future__ import annotations

import logging
import os
import socket
import struct
import threading
import time
from typing import Dict, Optional, Tuple

MAGIC = b"GSBD"
VERSION = 1
HEADER = struct.Struct("!4sBBBB")
HEADER_SIZE = HEADER.size
KIND_HOST_HELLO = 1
KIND_INPUT = 2
KIND_BUDDY_HELLO = 3
KIND_STATUS = 4
INPUT_PAYLOAD = struct.Struct("!IIBBhhhh")
DEFAULT_PORT = int(os.environ.get("GAMESPHERE_BUDDY_PORT", "48021"))
CLIENT_TTL = 4.0
MAX_PACKET = 256

_lock = threading.Lock()
_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_sock: Optional[socket.socket] = None
_port = DEFAULT_PORT
_host: Optional[Tuple[Tuple[str, int], float]] = None
_buddies: Dict[Tuple[str, int], Dict] = {}
_forwarded = 0


# A UDP peer that only ever says HELLO must not live in _buddies forever.
_MAX_BUDDIES = 32


def _evict_stale_locked(now: float) -> None:
    """Drop peers we have not heard from. Caller holds ``_lock``."""
    stale = [k for k, row in _buddies.items() if now - row["at"] > CLIENT_TTL * 4]
    for k in stale:
        _buddies.pop(k, None)
    # Hard cap so a packet flood from spoofed addresses cannot grow the dict.
    if len(_buddies) > _MAX_BUDDIES:
        for k, _ in sorted(_buddies.items(), key=lambda kv: kv[1]["at"])[
            : len(_buddies) - _MAX_BUDDIES
        ]:
            _buddies.pop(k, None)


def _status_packet() -> bytes:
    now = time.time()
    with _lock:
        host_present = bool(_host and now - _host[1] <= CLIENT_TTL)
        buddies = sum(1 for row in _buddies.values() if now - row["at"] <= CLIENT_TTL)
    return HEADER.pack(MAGIC, VERSION, KIND_STATUS, 0, 0) + struct.pack("!BB", 1 if host_present else 0, buddies)


def _loop(sock: socket.socket) -> None:
    global _host, _forwarded
    sock.settimeout(0.5)
    while not _stop.is_set():
        try:
            data, addr = sock.recvfrom(MAX_PACKET)
        except socket.timeout:
            continue
        except OSError:
            if _stop.is_set():
                return
            continue
        if len(data) < HEADER_SIZE:
            continue
        try:
            magic, ver, kind, buddy_id, _res = HEADER.unpack_from(data, 0)
        except struct.error:
            continue
        if magic != MAGIC or ver != VERSION:
            continue
        now = time.time()
        if kind == KIND_HOST_HELLO:
            with _lock:
                _host = (addr, now)
            try:
                sock.sendto(_status_packet(), addr)
            except OSError:
                pass
        elif kind == KIND_BUDDY_HELLO:
            with _lock:
                _buddies[addr] = {"at": now, "id": buddy_id}
                _evict_stale_locked(now)
            try:
                sock.sendto(_status_packet(), addr)
            except OSError:
                pass
        elif kind == KIND_INPUT:
            with _lock:
                _buddies[addr] = {"at": now, "id": buddy_id}
                host = _host
                _evict_stale_locked(now)
            if not host or now - host[1] > CLIENT_TTL:
                continue
            if host[0] == addr:
                continue
            try:
                sock.sendto(data, host[0])
                _forwarded += 1
            except OSError as e:
                logging.debug("buddy_relay forward to %s failed: %s", host[0], e)


def start(port: int = DEFAULT_PORT) -> Dict:
    global _thread, _sock, _port
    if _thread and _thread.is_alive():
        return {"ok": True, "port": _port, "already": True}
    _stop.clear()
    _port = int(port or DEFAULT_PORT)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", _port))
    _sock = sock
    _thread = threading.Thread(target=_loop, args=(sock,), daemon=True, name="gs-buddy")
    _thread.start()
    logging.info("buddy_relay listening on UDP %s", _port)
    return {"ok": True, "port": _port}


def stop() -> None:
    global _host
    _stop.set()
    if _sock:
        try:
            _sock.close()
        except OSError:
            pass
    if _thread:
        _thread.join(timeout=2)
    # Without this, a bridge restart could forward buddy input to the previous
    # session's host phone for up to CLIENT_TTL seconds.
    with _lock:
        _host = None
        _buddies.clear()


def status() -> Dict:
    now = time.time()
    with _lock:
        host_present = bool(_host and now - _host[1] <= CLIENT_TTL)
        buddies = sorted(
            int(row.get("id", 0)) for row in _buddies.values() if now - row["at"] <= CLIENT_TTL
        )
    return {
        "ok": True,
        "port": _port,
        "running": bool(_thread and _thread.is_alive()),
        "hostPresent": host_present,
        "buddies": buddies,
        "forwarded": _forwarded,
        "note": "Relays buddy gamepad frames to the host phone; never touches Sunshine input.",
    }
