"""Auto-pause when any of 2–4 streaming clients is dropping lots of frames.

Host GameSphere injects the same Start/Menu pulse used by the Swap overlay.
Guests never see Resume/Quit chrome from this path.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

# drop_rate is 0.0–1.0. Need several bad ticks so a hitch doesn't pause.
_BAD_DROP = 0.08
_GOOD_DROP = 0.02
_BAD_TICKS = 3
_GOOD_TICKS = 5
_SAMPLE_TTL = 8.0
_RESUME_COOLDOWN = 8.0

_lock = threading.Lock()
_clients: Dict[str, Dict[str, Any]] = {}
_paused = False
_pause_reason = ""
_last_resume = 0.0
_auto_pause_latched = False


def _cid(sample: Dict[str, Any]) -> str:
    for key in ("client_id", "clientId", "uuid", "role"):
        val = sample.get(key)
        if val:
            return str(val)
    role = str(sample.get("role") or sample.get("client") or "unknown")
    name = str(sample.get("client_name") or sample.get("clientName") or "")
    return f"{role}:{name}" if name else role


def note_sample(sample: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(sample, dict):
        return snapshot()
    cid = _cid(sample)
    try:
        drop = float(sample.get("drop_rate") if sample.get("drop_rate") is not None else 0)
    except (TypeError, ValueError):
        drop = 0.0
    now = time.time()
    with _lock:
        row = _clients.get(cid) or {"bad": 0, "good": 0}
        row.update(
            {
                "id": cid,
                "role": str(sample.get("role") or ("host" if sample.get("is_host") else "guest")),
                "is_host": bool(sample.get("is_host") or sample.get("role") == "host"),
                "drop_rate": drop,
                "at": now,
                "name": str(sample.get("client_name") or sample.get("clientName") or ""),
            }
        )
        if drop >= _BAD_DROP:
            row["bad"] = int(row.get("bad") or 0) + 1
            row["good"] = 0
        elif drop <= _GOOD_DROP:
            row["good"] = int(row.get("good") or 0) + 1
            row["bad"] = 0
        else:
            row["bad"] = 0
            row["good"] = 0
        _clients[cid] = row
        _recompute_locked(now)
    return snapshot()


def _live_clients(now: float) -> List[Dict[str, Any]]:
    live = []
    stale = []
    for cid, row in _clients.items():
        if now - float(row.get("at") or 0) > _SAMPLE_TTL:
            stale.append(cid)
            continue
        live.append(row)
    for cid in stale:
        _clients.pop(cid, None)
    return live


def _recompute_locked(now: float) -> None:
    global _paused, _pause_reason, _last_resume, _auto_pause_latched
    live = _live_clients(now)
    if len(live) < 2:
        if _paused and _auto_pause_latched:
            _paused = False
            _pause_reason = ""
            _auto_pause_latched = False
        return
    unhealthy = [c for c in live if int(c.get("bad") or 0) >= _BAD_TICKS]
    recovered = all(int(c.get("good") or 0) >= _GOOD_TICKS or int(c.get("bad") or 0) == 0 for c in live) and not unhealthy
    if unhealthy and not _paused:
        if now - _last_resume < _RESUME_COOLDOWN:
            return
        _paused = True
        _auto_pause_latched = True
        names = [c.get("name") or c.get("id") for c in unhealthy]
        _pause_reason = "frame_drop:" + ",".join(str(n) for n in names if n)
        logging.info("coop_pause: pause clients=%s reason=%s", len(live), _pause_reason)
        return
    if _paused and _auto_pause_latched and recovered:
        _paused = False
        _pause_reason = ""
        _auto_pause_latched = False
        _last_resume = now
        logging.info("coop_pause: auto-resume — all %s clients healthy", len(live))


def host_unpaused() -> None:
    """Host overlay / Start unpaused — clear latch so we don't pause-loop."""
    global _paused, _pause_reason, _last_resume, _auto_pause_latched
    with _lock:
        _paused = False
        _pause_reason = ""
        _auto_pause_latched = False
        _last_resume = time.time()


def snapshot() -> Dict[str, Any]:
    now = time.time()
    with _lock:
        live = _live_clients(now)
        return {
            "ok": True,
            "multiplayer": len(live) >= 2,
            "clientCount": len(live),
            "pauseRecommended": bool(_paused and _auto_pause_latched and len(live) >= 2),
            "paused": _paused,
            "reason": _pause_reason,
            "clients": [
                {
                    "id": c.get("id"),
                    "role": c.get("role"),
                    "drop_rate": c.get("drop_rate"),
                    "bad": c.get("bad"),
                    "good": c.get("good"),
                }
                for c in live
            ],
        }
