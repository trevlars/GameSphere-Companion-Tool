"""Coercion helpers for values that arrive from a paired client.

Bridge verbs parse JSON straight off the socket, so a buggy or hostile client
must not be able to fault a handler with a non-numeric port.
"""

from __future__ import annotations

from typing import Any

DEFAULT_HTTPS_PORT = 47984

# Sunshine's web UI port — never advertise it as a stream port.
_FORBIDDEN_PORTS = {47990}


def safe_port(value: Any, default: int = DEFAULT_HTTPS_PORT) -> int:
    """Return a usable TCP port, falling back to ``default`` on junk input."""
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if port <= 0 or port > 65535 or port in _FORBIDDEN_PORTS:
        return default
    return port


def safe_text(value: Any, limit: int, default: str = "") -> str:
    """Trim client-supplied text to a bounded single-line string."""
    if value is None:
        return default
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return default
    return text[:limit]
