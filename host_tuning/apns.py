"""Token-based APNs for Wanna-play lock-screen alerts.

Uses an Apple **APNs Auth Key** (.p8) — not App Store Connect API keys, not
Firebase. Never logs the PEM, JWT, or full device token.

HTTP/2 via curl (stdlib-free). JWT ES256 via cryptography or openssl.
If the key is missing, callers keep the PLAYPENDING poll path.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from host_tuning.config import config_dir, load_config

_log = logging.getLogger(__name__)

BUNDLE_ID = "com.moonlight.gamesphere"
TEAM_ID = "ABG342Z7V2"
SANDBOX_HOST = "api.sandbox.push.apple.com"
PROD_HOST = "api.push.apple.com"
NO_KEY_SENTENCE = (
    "Lock-screen Wanna play needs an APNs Auth Key (.p8) on this PC — "
    "friends still get the ping if GameSphere is open."
)
READY_SENTENCE = "Lock-screen Wanna play is on — Apple push will wake GameSphere on paired devices."
_JWT_TTL = 50 * 60
_lock = threading.Lock()
_jwt_cache: Dict[str, Any] = {"token": "", "exp": 0.0, "sig": ""}

_HEX_RE = re.compile(r"[^0-9a-fA-F]")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def normalize_token(raw: Any) -> str:
    token = _HEX_RE.sub("", str(raw or "").strip())
    if 16 <= len(token) <= 200 and all(c in "0123456789abcdefABCDEF" for c in token):
        return token.lower()
    return ""


def parse_environment(payload: Dict[str, Any]) -> str:
    """Debug 115 / development provisioning → sandbox. TestFlight → production."""
    env = str(
        payload.get("apnsEnvironment")
        or payload.get("apsEnvironment")
        or payload.get("environment")
        or ""
    ).strip().lower()
    if env in ("development", "dev", "sandbox", "debug"):
        return "development"
    if env in ("production", "prod", "release"):
        return "production"
    sandbox = payload.get("apnsSandbox")
    if sandbox is True or str(sandbox).lower() in ("1", "true", "yes"):
        return "development"
    if sandbox is False or str(sandbox).lower() in ("0", "false", "no"):
        return "production"
    return "development"


def _package_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _install_host_tuning_dir() -> str:
    return os.path.expanduser("~/.local/share/gamesphere-import-tool/host_tuning")


def _load_sidecar(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _key_id_from_filename(path: str) -> str:
    name = os.path.basename(path or "")
    match = re.match(r"AuthKey_([A-Z0-9]{10})\.p8$", name, re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _candidate_p8_paths(cfg_path: str = "") -> List[str]:
    out: List[str] = []
    if cfg_path:
        out.append(os.path.expanduser(cfg_path))
    cfg = config_dir()
    out.append(os.path.join(cfg, "apns.p8"))
    try:
        for name in sorted(os.listdir(cfg)):
            if re.match(r"AuthKey_[A-Z0-9]{10}\.p8$", name, re.IGNORECASE):
                out.append(os.path.join(cfg, name))
    except OSError:
        pass
    out.append(os.path.join(_package_dir(), "apns.p8"))
    out.append(os.path.join(_install_host_tuning_dir(), "apns.p8"))
    seen = set()
    unique = []
    for path in out:
        if path and path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def _read_key_id_file(directory: str) -> str:
    if not directory:
        return ""
    for name in ("apns.keyid", "apns.kid"):
        path = os.path.join(directory, name)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                parts = fh.read().strip().split()
            value = (parts[0] if parts else "").strip().upper()
            if re.fullmatch(r"[A-Z0-9]{10}", value):
                return value
        except (OSError, IndexError):
            continue
    return ""


def key_config() -> Dict[str, Any]:
    """Public-safe config: paths and IDs, never the PEM."""
    cfg = load_config()
    sidecar = _load_sidecar(os.path.join(config_dir(), "apns.json"))
    sidecar.update(_load_sidecar(os.path.join(_package_dir(), "apns.json")))
    key_path = (
        str(getattr(cfg, "apns_key_path", "") or "").strip()
        or str(sidecar.get("keyPath") or sidecar.get("key_path") or "").strip()
        or os.environ.get("GAMESPHERE_APNS_KEY_PATH", "").strip()
    )
    p8 = ""
    for candidate in _candidate_p8_paths(key_path):
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 32:
            p8 = candidate
            break
    key_id = (
        str(getattr(cfg, "apns_key_id", "") or "").strip()
        or str(sidecar.get("keyId") or sidecar.get("key_id") or "").strip()
        or os.environ.get("GAMESPHERE_APNS_KEY_ID", "").strip()
        or _key_id_from_filename(p8)
        or _read_key_id_file(os.path.dirname(p8) if p8 else "")
        or _read_key_id_file(config_dir())
    ).upper()
    team_id = (
        str(getattr(cfg, "apns_team_id", "") or "").strip()
        or str(sidecar.get("teamId") or sidecar.get("team_id") or "").strip()
        or os.environ.get("GAMESPHERE_APNS_TEAM_ID", "").strip()
        or TEAM_ID
    )
    bundle = (
        str(getattr(cfg, "apns_bundle_id", "") or "").strip()
        or str(sidecar.get("bundleId") or sidecar.get("bundle_id") or "").strip()
        or os.environ.get("GAMESPHERE_APNS_BUNDLE_ID", "").strip()
        or BUNDLE_ID
    )
    return {
        "keyPath": p8,
        "keyId": key_id,
        "teamId": team_id,
        "bundleId": bundle,
        "ready": bool(p8 and key_id and team_id),
        "hasKey": bool(p8),
        "hasKeyId": bool(key_id),
    }


def status_public() -> Dict[str, Any]:
    """One-sentence status. Never includes PEM, JWT, or tokens."""
    info = key_config()
    if info.get("ready"):
        sentence = READY_SENTENCE
    elif info.get("hasKey") and not info.get("hasKeyId"):
        sentence = (
            "Lock-screen Wanna play needs the APNs Key ID next to the .p8 "
            "(apns.json keyId, or keep the AuthKey_XXXXXXXXXX.p8 filename)."
        )
    else:
        sentence = NO_KEY_SENTENCE
    return {
        "ok": True,
        "pushReady": bool(info.get("ready")),
        "pushStatus": sentence,
        "bundleId": info.get("bundleId") or BUNDLE_ID,
        "hasKey": bool(info.get("hasKey")),
        "keyIdSet": bool(info.get("hasKeyId")),
        "teamId": info.get("teamId") or TEAM_ID,
    }


def build_payload(
    *,
    title: str,
    body: str,
    play_url: str,
    cover_url: str = "",
    session_id: str = "",
    app_id: str = "",
    app_name: str = "",
    host_persona: str = "",
) -> Dict[str, Any]:
    cover = (cover_url or "").strip()
    if cover.startswith("file:"):
        cover = ""
    aps: Dict[str, Any] = {
        "alert": {
            "title": title or "Wanna play?",
            "body": body or "Wanna play?",
        },
        "sound": "default",
        "mutable-content": 1,
        "category": "GS_WANNA_PLAY",
    }
    payload: Dict[str, Any] = {
        "aps": aps,
        "playURL": play_url or "",
    }
    if cover.startswith("http://") or cover.startswith("https://"):
        payload["coverUrl"] = cover
        payload["thumbnailUrl"] = cover
    if session_id:
        payload["sessionId"] = session_id
        payload["session"] = session_id
        payload["token"] = session_id
    if app_id:
        payload["appId"] = app_id
    if app_name:
        payload["appName"] = app_name
    if host_persona:
        payload["hostPersona"] = host_persona
    return payload


def _der_ecdsa_to_jose(der: bytes) -> bytes:
    """DER SEQUENCE of two INTEGERs → raw R||S (P-256)."""
    if not der or der[0] != 0x30:
        raise ValueError("apns jwt: not a DER sequence")
    idx = 1
    length = der[idx]
    idx += 1
    if length & 0x80:
        n = length & 0x7F
        idx += n
    def _read_int(i: int) -> Tuple[bytes, int]:
        if i >= len(der) or der[i] != 0x02:
            raise ValueError("apns jwt: expected INTEGER")
        ln = der[i + 1]
        i += 2
        val = der[i : i + ln]
        return val, i + ln
    r, idx = _read_int(idx)
    s, _idx = _read_int(idx)
    r = r.lstrip(b"\x00") or b"\x00"
    s = s.lstrip(b"\x00") or b"\x00"
    return r.rjust(32, b"\x00") + s.rjust(32, b"\x00")


def _sign_es256_openssl(p8_path: str, signing_input: bytes) -> bytes:
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError("openssl not found")
    proc = subprocess.run(
        [openssl, "dgst", "-sha256", "-sign", p8_path],
        input=signing_input,
        capture_output=True,
        timeout=8,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError("openssl jwt sign failed")
    return _der_ecdsa_to_jose(proc.stdout)


def _sign_es256_cryptography(p8_path: str, signing_input: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    with open(p8_path, "rb") as fh:
        pem = fh.read()
    key = serialization.load_pem_private_key(pem, password=None)
    der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def _jwt(p8_path: str, key_id: str, team_id: str) -> str:
    now = int(time.time())
    sig = f"{p8_path}:{os.path.getmtime(p8_path)}:{key_id}:{team_id}"
    with _lock:
        if _jwt_cache.get("token") and float(_jwt_cache.get("exp") or 0) > now and _jwt_cache.get("sig") == sig:
            return str(_jwt_cache["token"])
    header = {"alg": "ES256", "kid": key_id}
    claims = {"iss": team_id, "iat": now}
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    ).encode("ascii")
    try:
        raw = _sign_es256_cryptography(p8_path, signing_input)
    except Exception:
        raw = _sign_es256_openssl(p8_path, signing_input)
    token = signing_input.decode("ascii") + "." + _b64url(raw)
    with _lock:
        _jwt_cache["token"] = token
        _jwt_cache["exp"] = now + _JWT_TTL
        _jwt_cache["sig"] = sig
    return token


def _curl_bin() -> str:
    return shutil.which("curl") or shutil.which("curl.exe") or ""


def http2_post(url: str, headers: Dict[str, str], body: bytes, timeout: float = 8.0) -> Tuple[int, bytes]:
    """POST JSON over HTTP/2. Raises on transport failure; never logs headers."""
    curl = _curl_bin()
    if not curl:
        raise RuntimeError("curl not found (needed for HTTP/2 APNs)")
    with tempfile.NamedTemporaryFile(prefix="gs-apns-", suffix=".json", delete=False) as out:
        out_path = out.name
    try:
        cmd = [
            curl,
            "-sS",
            "--http2",
            "--max-time",
            str(max(3, int(timeout))),
            "-o",
            out_path,
            "-w",
            "%{http_code}",
            "-X",
            "POST",
        ]
        for key, value in headers.items():
            cmd.extend(["-H", f"{key}: {value}"])
        cmd.extend(["--data-binary", "@-", url])
        proc = subprocess.run(
            cmd,
            input=body,
            capture_output=True,
            timeout=timeout + 3,
            check=False,
        )
        code_txt = (proc.stdout or b"").decode("ascii", "ignore").strip()
        try:
            status = int(code_txt)
        except ValueError:
            status = 0
        try:
            with open(out_path, "rb") as fh:
                resp = fh.read()
        except OSError:
            resp = b""
        if proc.returncode != 0 and status == 0:
            err = (proc.stderr or b"").decode("utf-8", "ignore").strip()
            raise RuntimeError(err or "curl http2 failed")
        return status, resp
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


def _host_for(environment: str) -> str:
    return SANDBOX_HOST if environment == "development" else PROD_HOST


def send_alert(
    token: str,
    payload: Dict[str, Any],
    *,
    environment: str = "development",
    collapse_id: str = "",
    expires: int = 0,
) -> Dict[str, Any]:
    info = key_config()
    if not info.get("ready"):
        return {"ok": False, "error": "no_apns_key", "status": status_public()["pushStatus"]}
    token = normalize_token(token)
    if not token:
        return {"ok": False, "error": "bad_token"}
    env = "development" if environment == "development" else "production"
    jwt = _jwt(info["keyPath"], info["keyId"], info["teamId"])
    headers = {
        "authorization": f"bearer {jwt}",
        "apns-topic": info["bundleId"],
        "apns-push-type": "alert",
        "apns-priority": "10",
        "content-type": "application/json",
    }
    if expires:
        headers["apns-expiration"] = str(int(expires))
    if collapse_id:
        headers["apns-collapse-id"] = collapse_id[:64]
    url = f"https://{_host_for(env)}/3/device/{token}"
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    try:
        status, raw = http2_post(url, headers, body)
    except Exception as exc:
        _log.warning("APNs transport failed env=%s: %s", env, type(exc).__name__)
        return {"ok": False, "error": "transport", "http": 0}
    reason = ""
    if raw:
        try:
            parsed = json.loads(raw.decode("utf-8", "ignore"))
            if isinstance(parsed, dict):
                reason = str(parsed.get("reason") or "")
        except json.JSONDecodeError:
            reason = ""
    ok = 200 <= status < 300
    if not ok:
        _log.info("APNs rejected env=%s http=%s reason=%s", env, status, reason or "?")
    else:
        _log.info("APNs sent env=%s http=%s", env, status)
    return {"ok": ok, "http": status, "reason": reason, "environment": env}


def notify_devices(
    devices: List[Dict[str, Any]],
    uuids: List[str],
    *,
    title: str,
    body: str,
    play_url: str,
    cover_url: str = "",
    session_id: str = "",
    app_id: str = "",
    app_name: str = "",
    host_persona: str = "",
    expires: int = 0,
) -> None:
    """Fire-and-forget APNs to registered tokens. Never raises."""
    try:
        if not key_config().get("ready"):
            return
        payload = build_payload(
            title=title,
            body=body,
            play_url=play_url,
            cover_url=cover_url,
            session_id=session_id,
            app_id=app_id,
            app_name=app_name,
            host_persona=host_persona,
        )
        by_uuid = {d.get("uuid"): d for d in devices if d.get("uuid")}
        jobs = []
        for uuid in uuids:
            row = by_uuid.get(uuid) or {}
            token = normalize_token(row.get("apnsToken") or "")
            if not token:
                continue
            env = parse_environment(row)
            jobs.append((uuid, token, env))
        if not jobs:
            return

        def _run() -> None:
            collapse = f"gs.wannaplay.{session_id}" if session_id else "gs.wannaplay"
            for uuid, token, env in jobs:
                try:
                    send_alert(
                        token,
                        payload,
                        environment=env,
                        collapse_id=collapse,
                        expires=expires,
                    )
                except Exception:
                    _log.debug("APNs send failed uuid=%s", uuid, exc_info=True)

        threading.Thread(target=_run, name="gs-apns", daemon=True).start()
    except Exception:
        _log.debug("APNs notify_devices failed", exc_info=True)
