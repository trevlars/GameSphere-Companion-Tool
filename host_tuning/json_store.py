"""Crash-safe JSON/text writes for config and daemon state.

A killed process (reboot, power loss, taskkill) must never leave a truncated
``apps.json`` or half-written state file. Serialize first, write a sibling temp
file, fsync, then ``os.replace`` — atomic on POSIX and Windows.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Optional

_log = logging.getLogger(__name__)


def write_text_atomic(path: str, text: str, *, newline: Optional[str] = None) -> str:
    """Replace ``path`` with ``text`` atomically. Returns the path written."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".gs-tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        tmp = ""
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return path


def write_json_atomic(path: str, data: Any, *, indent: Optional[int] = 2) -> str:
    """Serialize before touching the target so a bad payload cannot truncate it."""
    text = json.dumps(data, indent=indent, ensure_ascii=False)
    return write_text_atomic(path, text)


def read_json(path: str, default: Any = None) -> Any:
    """Tolerant read. Corrupt or missing state returns ``default`` instead of raising."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        _log.warning("unreadable JSON at %s (%s) — using defaults", path, exc)
        return default
