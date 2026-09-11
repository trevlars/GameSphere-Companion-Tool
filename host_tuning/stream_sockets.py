"""Detect live Moonlight/Sunshine streams via UDP ports (StreamTweak 8.3.0 pattern)."""

from __future__ import annotations

import psutil

# Moonlight video/control ports Sunshine typically binds while streaming
STREAM_UDP_PORTS = {47998, 47999, 48000, 48002, 48010}


def stream_sockets_active() -> bool:
    try:
        for conn in psutil.net_connections(kind="udp"):
            if conn.laddr and conn.laddr.port in STREAM_UDP_PORTS:
                if conn.status in (psutil.CONN_NONE, "NONE", "LISTEN", ""):
                    return True
    except (psutil.AccessDenied, AttributeError):
        pass
    return False
