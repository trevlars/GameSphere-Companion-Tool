"""Detect and recover wedged Sunshine HTTPS/RTSP accept threads on Bazzite.

Symptom: plain HTTP on 47989 still answers /serverinfo, but TLS on 47989 and RTSP
on 48010 hang after a stream session. Moonlight clients see RTSP handshake error 60.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import ssl
import subprocess
import time
from typing import Any, Dict, Optional

HTTP_PORT = 47989
HTTPS_PORT = 47984  # Moonlight launch/resume TLS (HttpsPort from serverinfo)
RTSP_PORT = 48010
HOST = "127.0.0.1"

_LAST_RECOVER_TS = 0.0
_LAST_POST_STREAM_TS = 0.0
_MIN_RECOVER_INTERVAL_SEC = 90.0
_MIN_POST_STREAM_INTERVAL_SEC = 25.0


def _fetch_serverinfo(timeout: float = 2.5) -> str:
    try:
        result = subprocess.run(
            [
                "curl",
                "-sS",
                "-m",
                str(max(1, int(timeout))),
                f"http://{HOST}:{HTTP_PORT}/serverinfo",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 1,
        )
        if result.returncode == 0:
            return result.stdout or ""
    except Exception:
        pass
    return ""


def _curl_http(timeout: float = 2.5) -> bool:
    body = _fetch_serverinfo(timeout)
    return bool(body) and "status_code" in body


def _sunshine_session_active(timeout: float = 2.5) -> bool:
    """True when a client is connected or Sunshine is launching a game."""
    body = _fetch_serverinfo(timeout)
    if not body:
        return False
    if "<currentgame>0</currentgame>" in body:
        return False
    if "<currentgame>" in body and "</currentgame>" in body:
        start = body.index("<currentgame>") + len("<currentgame>")
        end = body.index("</currentgame>", start)
        game_id = body[start:end].strip()
        if game_id and game_id != "0":
            return True
    if "SUNSHINE_SERVER_BUSY" in body:
        return True
    return False


def _probe_tls(port: int, timeout: float = 2.5) -> bool:
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        raw = socket.create_connection((HOST, port), timeout=timeout)
        try:
            with ctx.wrap_socket(raw, server_hostname="localhost") as tls:
                tls.settimeout(timeout)
                tls.do_handshake()
                return True
        finally:
            try:
                raw.close()
            except Exception:
                pass
    except Exception:
        return False


def _probe_rtsp(timeout: float = 2.5) -> bool:
    try:
        raw = socket.create_connection((HOST, RTSP_PORT), timeout=timeout)
        try:
            raw.settimeout(timeout)
            raw.sendall(b"OPTIONS * RTSP/1.0\r\nCSeq: 1\r\n\r\n")
            data = raw.recv(4096)
            return b"RTSP" in data
        finally:
            raw.close()
    except Exception:
        return False


def probe() -> Dict[str, Any]:
    http_ok = _curl_http()
    https_ok = _probe_tls(HTTPS_PORT)
    # RTSP does not reliably answer OPTIONS while idle; omit from auto wedge detection.
    wedged = http_ok and not https_ok
    return {
        "ok": http_ok and https_ok,
        "wedged": wedged,
        "http47989": http_ok,
        "https47984": https_ok,
    }


def _prep_stop() -> None:
    prep = os.path.expanduser("~/.local/bin/sunshine-stream-prep.sh")
    if os.path.isfile(prep):
        subprocess.run([prep, "stop"], check=False, timeout=30)
    subprocess.run(["pkill", "-f", "sunshine-stream-prep.sh"], check=False)
    subprocess.run(["pkill", "-f", "bazzite-steam-clone-watch.sh"], check=False)


def _restart_sunshine() -> bool:
    result = subprocess.run(
        ["systemctl", "--user", "restart", "sunshine.service"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode == 0


def _restart_and_wait(reason: str) -> Dict[str, Any]:
    before = probe()
    if not before["http47989"]:
        return {"ok": False, "recovered": False, "reason": "sunshine_down", "probe": before}

    logging.warning("Sunshine recover (%s): %s", reason, before)
    _prep_stop()
    if not _restart_sunshine():
        return {"ok": False, "recovered": False, "reason": "restart_failed", "probe": before}

    deadline = time.time() + 40.0
    after = before
    while time.time() < deadline:
        time.sleep(1.0)
        after = probe()
        if after["ok"]:
            return {"ok": True, "recovered": True, "reason": reason, "probe": after}

    return {"ok": False, "recovered": False, "reason": "timeout_waiting_healthy", "probe": after}


def recover_post_stream() -> Dict[str, Any]:
    """Optional post-stream bounce — disabled by default (was killing new sessions)."""
    return {
        "ok": True,
        "recovered": False,
        "reason": "post_stream_disabled",
        "probe": probe(),
    }


def recover(force: bool = False) -> Dict[str, Any]:
    """Stop stream prep, restart Sunshine, wait until probes pass."""
    global _LAST_RECOVER_TS
    now = time.time()
    before = probe()

    if not force and _sunshine_session_active():
        return {
            "ok": True,
            "recovered": False,
            "reason": "session_active",
            "probe": before,
        }

    if force:
        if _sunshine_session_active():
            return {
                "ok": False,
                "recovered": False,
                "reason": "session_active",
                "probe": before,
            }
        result = _restart_and_wait("client_force")
        if result.get("recovered") or result.get("ok"):
            _LAST_RECOVER_TS = time.time()
        return result

    if before["ok"]:
        return {"ok": True, "recovered": False, "reason": "already_healthy", "probe": before}

    if (now - _LAST_RECOVER_TS) < _MIN_RECOVER_INTERVAL_SEC:
        return {
            "ok": False,
            "recovered": False,
            "reason": "rate_limited",
            "probe": before,
            "retry_after_sec": int(_MIN_RECOVER_INTERVAL_SEC - (now - _LAST_RECOVER_TS)),
        }

    result = _restart_and_wait("wedged_probe")
    if result.get("recovered"):
        _LAST_RECOVER_TS = time.time()
    return result


def health_json() -> str:
    return json.dumps(probe())


def recover_json(force: bool = False) -> str:
    return json.dumps(recover(force=force))


def recover_post_stream_json() -> str:
    return json.dumps(recover_post_stream())
