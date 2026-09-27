"""In-stream voice mixer for GameSphere clients + host virtual mic.

Clients send 16 kHz s16le mono PCM over UDP. Companion mixes those packets only
and sends each client the mix minus itself.

PC mic path (Linux/PipeWire): slot 0 uplink is written into a virtual capture
device named "GameSphere Mic" so Steam / Discord / games can select it.
When AEC is enabled (default), WebRTC cancels room gameplay using an HDMI
*monitor* tap into a null-sink reference — never ``sink_master=<HDMI>``, which
inserts into the HDMI graph and crackles Sunshine. Guests (slots 1–3) stay
party-only. No VBAN.

Routing note: replies use the kernel route to each client. Do not install a
ZeroTier/VPN more-specific route for the LAN prefix (e.g. 10.0.5.0/24 via zt)
or voice uplink works while downlink never leaves the Ethernet NIC.
"""

from __future__ import annotations

import collections
import logging
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
from typing import Deque, Dict, List, Optional, Tuple

MAGIC = b"GSVC"
VERSION = 1
HEADER_SIZE = 12  # magic(4) + ver(1) + slot(1) + seq(2) + samples(2) + rate(2)
DEFAULT_PORT = int(os.environ.get("GAMESPHERE_VOICE_PORT", "48020"))
SAMPLE_RATE = 16000
# Match gamesphere-pc-mic-setup.sh. Default 16 kHz (native phone rate). Use 48000
# only when HDMI-monitor AEC is on (GAMESPHERE_MIC_AEC=1).
PC_SINK_RATE = int(os.environ.get("GAMESPHERE_PC_MIC_RATE", "16000"))
MAX_PACKET = 2048
CLIENT_TTL = 2.5
# Couch co-op is 4 seats; the cap only exists to bound an adversarial flood.
_MAX_CLIENTS = 16
PC_MIC_SLOT = int(os.environ.get("GAMESPHERE_PC_MIC_SLOT", "0"))
PC_MIC_NAME = os.environ.get("GAMESPHERE_PC_MIC_NAME", "GameSphere Mic")
PC_MIC_SINK = os.environ.get("GAMESPHERE_PC_MIC_SINK", "gamesphere_mic_sink")
PC_MIC_SOURCE = os.environ.get("GAMESPHERE_PC_MIC_SOURCE", "gamesphere_mic")
FRAME_BYTES = 640  # 320 samples * 2 bytes (20 ms @ 16 kHz)
# 20 ms @ PC_SINK_RATE mono s16le after optional upsample from the phone frame.
PC_FRAME_BYTES = FRAME_BYTES * max(1, PC_SINK_RATE // SAMPLE_RATE)
# ~100 ms of queued audio before we start draining (absorbs jitter).
_PC_PREBUFFER_FRAMES = 5
_PC_QUEUE_MAX = 12  # drop oldest beyond ~240 ms

_lock = threading.Lock()
_clients: Dict[Tuple[str, int], Dict] = {}
_thread: Optional[threading.Thread] = None
_sock: Optional[socket.socket] = None
_stop = threading.Event()
_port = DEFAULT_PORT

_pc_lock = threading.Lock()
_pc_queue: Deque[bytes] = collections.deque()
_pc_at = 0.0
_pc_feeder: Optional[threading.Thread] = None
_pc_proc: Optional[subprocess.Popen] = None
_pc_ready = False
_pc_error: Optional[str] = None


def _parse(packet: bytes):
    if len(packet) < HEADER_SIZE or packet[:4] != MAGIC:
        return None
    ver, slot = packet[4], packet[5]
    if ver != VERSION:
        return None
    seq, samples, rate = struct.unpack_from("!HHH", packet, 6)
    pcm = packet[HEADER_SIZE:]
    return {"slot": slot, "seq": seq, "samples": samples, "rate": rate, "pcm": pcm}


def _header(slot: int, seq: int, samples: int, rate: int) -> bytes:
    return MAGIC + bytes([VERSION, slot & 0xFF]) + struct.pack("!HHH", seq & 0xFFFF, samples, rate)


def _evict_stale_clients_locked(now: float) -> None:
    """Drop voice peers we have stopped hearing from. Caller holds ``_lock``."""
    for addr, row in list(_clients.items()):
        if now - row["at"] > CLIENT_TTL:
            _clients.pop(addr, None)
    # Hard cap: a flood from spoofed source addresses must not grow the dict
    # between eviction passes.
    if len(_clients) > _MAX_CLIENTS:
        for addr, _ in sorted(_clients.items(), key=lambda kv: kv[1]["at"])[
            : len(_clients) - _MAX_CLIENTS
        ]:
            _clients.pop(addr, None)


def _mix_minus(target_addr, now: float) -> bytes:
    chunks = []
    with _lock:
        _evict_stale_clients_locked(now)
        for addr, row in list(_clients.items()):
            if now - row["at"] > CLIENT_TTL:
                continue
            if addr == target_addr:
                continue
            pcm = row.get("pcm") or b""
            if pcm:
                chunks.append(pcm)
    if not chunks:
        return b""
    n = min(len(c) for c in chunks)
    n -= n % 2
    if n <= 0:
        return b""
    acc = [0] * (n // 2)
    for pcm in chunks:
        for i in range(0, n, 2):
            acc[i // 2] += struct.unpack_from("<h", pcm, i)[0]
    count = max(1, len(chunks))
    out = bytearray()
    for sample in acc:
        sample = max(-32768, min(32767, sample // count))
        out += struct.pack("<h", sample)
    return bytes(out)


def _pactl(*args: str, timeout: float = 8.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["pactl", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _source_exists(name: str) -> bool:
    try:
        proc = _pactl("list", "short", "sources")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == name:
            return True
    return False


def _sink_exists(name: str) -> bool:
    try:
        proc = _pactl("list", "short", "sinks")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == name:
            return True
    return False


def _mic_setup_script() -> Optional[str]:
    candidates = [
        os.path.expanduser("~/.local/bin/gamesphere-pc-mic-setup.sh"),
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts",
            "gamesphere-pc-mic-setup.sh",
        ),
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
        if os.path.isfile(path):
            return path
    return None


def _aec_active() -> bool:
    try:
        proc = _pactl("list", "short", "modules")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    needle = f"module-echo-cancel"
    for line in (proc.stdout or "").splitlines():
        if needle in line and PC_MIC_SOURCE in line:
            return True
    return False


def ensure_pc_mic_device() -> Dict:
    """Create GameSphere Mic (+ HDMI-monitor WebRTC AEC by default). Idempotent."""
    global _pc_ready, _pc_error
    if os.name == "nt" or not shutil.which("pactl"):
        _pc_ready = False
        _pc_error = "PipeWire/Pulse pactl not available (Linux host required for GameSphere Mic)"
        return {"ok": False, "error": _pc_error, "device": PC_MIC_NAME}

    try:
        script = _mic_setup_script()
        if script:
            proc = subprocess.run(
                ["bash", script, "install"],
                capture_output=True,
                text=True,
                timeout=45,
            )
            if proc.returncode != 0 and not _source_exists(PC_MIC_SOURCE):
                _pc_error = (proc.stderr or proc.stdout or "mic setup failed").strip()
                _pc_ready = False
                return {"ok": False, "error": _pc_error, "device": PC_MIC_NAME}
        else:
            # Minimal fallback without the setup script (no AEC).
            if not _sink_exists(PC_MIC_SINK):
                proc = _pactl(
                    "load-module",
                    "module-null-sink",
                    f"sink_name={PC_MIC_SINK}",
                    f"rate={PC_SINK_RATE}",
                    "channels=1",
                    "sink_properties=device.description=GameSphereMicSink",
                )
                if proc.returncode != 0:
                    _pc_error = (proc.stderr or proc.stdout or "null-sink failed").strip()
                    _pc_ready = False
                    return {"ok": False, "error": _pc_error, "device": PC_MIC_NAME}
            if not _source_exists(PC_MIC_SOURCE):
                proc = _pactl(
                    "load-module",
                    "module-remap-source",
                    f"master={PC_MIC_SINK}.monitor",
                    f"source_name={PC_MIC_SOURCE}",
                    f'source_properties=device.description="{PC_MIC_NAME}"',
                )
                if proc.returncode != 0 and not _source_exists(PC_MIC_SOURCE):
                    _pc_error = (proc.stderr or proc.stdout or "remap-source failed").strip()
                    _pc_ready = False
                    return {"ok": False, "error": _pc_error, "device": PC_MIC_NAME}

        _pactl("set-source-property", PC_MIC_SOURCE, "device.description", PC_MIC_NAME)
        steam_voice: Dict = {}
        try:
            from host_tuning.steam_voice import configure_steam_voice_mic

            steam_voice = configure_steam_voice_mic(PC_MIC_SOURCE)
        except Exception as exc:
            logging.debug("steam voice mic configure: %s", exc)
        _pc_ready = _source_exists(PC_MIC_SOURCE)
        _pc_error = None if _pc_ready else "GameSphere Mic source missing after setup"
        out = {
            "ok": bool(_pc_ready),
            "device": PC_MIC_NAME,
            "source": PC_MIC_SOURCE,
            "sink": PC_MIC_SINK,
            "slot": PC_MIC_SLOT,
            "aec": _aec_active(),
            "aecMode": "hdmi-monitor-webrtc" if _aec_active() else "off",
        }
        if steam_voice:
            out["steamVoice"] = steam_voice
        if not _pc_ready:
            out["error"] = _pc_error
        return out
    except Exception as exc:
        _pc_ready = False
        _pc_error = str(exc)
        logging.warning("pc mic device: %s", exc)
        return {"ok": False, "error": _pc_error, "device": PC_MIC_NAME}


def _retire_vban_conf() -> None:
    """Best-effort: remove legacy PipeWire VBAN recv drop-in so we stop using VBAN."""
    conf = os.path.expanduser("~/.config/pipewire/pipewire.conf.d/50-gamesphere-vban-recv.conf")
    try:
        if os.path.isfile(conf):
            os.remove(conf)
            logging.info("removed legacy VBAN PipeWire config %s", conf)
    except OSError as exc:
        logging.debug("vban conf remove: %s", exc)


def _upsample_phone_to_sink(pcm16: bytes) -> bytes:
    """Linear-upsample one 16 kHz mono frame to PC_SINK_RATE for PipeWire/AEC."""
    if PC_SINK_RATE == SAMPLE_RATE:
        return pcm16
    ratio = PC_SINK_RATE // SAMPLE_RATE
    if ratio < 2 or PC_SINK_RATE % SAMPLE_RATE:
        # Fallback: naive repeat (still better than feeding 16 kHz into a 48 kHz graph).
        ratio = max(1, round(PC_SINK_RATE / SAMPLE_RATE))
    n = len(pcm16) // 2
    if n <= 0:
        return b"\x00" * PC_FRAME_BYTES
    samples = struct.unpack("<" + ("h" * n), pcm16[: n * 2])
    out: List[int] = []
    for i, s in enumerate(samples):
        nxt = samples[i + 1] if i + 1 < n else s
        for k in range(ratio):
            t = k / float(ratio)
            out.append(int(s + (nxt - s) * t))
    raw = struct.pack("<" + ("h" * len(out)), *out)
    if len(raw) < PC_FRAME_BYTES:
        raw = raw + (b"\x00" * (PC_FRAME_BYTES - len(raw)))
    elif len(raw) > PC_FRAME_BYTES:
        raw = raw[:PC_FRAME_BYTES]
    return raw


def _set_pc_pcm(pcm: bytes) -> None:
    global _pc_at
    if not pcm:
        return
    # Pad / trim to one phone frame, then optionally upsample for the sink rate.
    if len(pcm) < FRAME_BYTES:
        pcm = pcm + (b"\x00" * (FRAME_BYTES - len(pcm)))
    elif len(pcm) > FRAME_BYTES:
        pcm = pcm[:FRAME_BYTES]
    frame = _upsample_phone_to_sink(pcm)
    with _pc_lock:
        _pc_queue.append(frame)
        while len(_pc_queue) > _PC_QUEUE_MAX:
            _pc_queue.popleft()
        _pc_at = time.time()


def _pc_feeder_loop() -> None:
    global _pc_proc
    logging.info(
        "pc mic feeder targeting sink %s → source %s (%s) @ %s Hz (ring buffer)",
        PC_MIC_SINK,
        PC_MIC_SOURCE,
        PC_MIC_NAME,
        PC_SINK_RATE,
    )
    silence = b"\x00" * PC_FRAME_BYTES
    next_t = time.monotonic()
    primed = False
    since_flush = 0
    while not _stop.is_set():
        if not _pc_ready:
            ensure_pc_mic_device()
            if not _pc_ready:
                time.sleep(1.0)
                next_t = time.monotonic()
                primed = False
                continue
        if _pc_proc is None or _pc_proc.poll() is not None:
            try:
                _pc_proc = subprocess.Popen(
                    [
                        "pacat",
                        "--playback",
                        "--raw",
                        "--format=s16le",
                        f"--rate={PC_SINK_RATE}",
                        "--channels=1",
                        f"--device={PC_MIC_SINK}",
                        # Bigger Pulse buffer; we pace on a monotonic clock below.
                        "--latency-msec=200",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    bufsize=0,
                )
                primed = False
                next_t = time.monotonic()
            except FileNotFoundError:
                logging.warning("pacat not found — GameSphere Mic feeder disabled")
                time.sleep(2.0)
                continue
            except OSError as exc:
                logging.warning("pacat start failed: %s", exc)
                time.sleep(1.0)
                continue

        with _pc_lock:
            qlen = len(_pc_queue)
            fresh = (time.time() - _pc_at) <= CLIENT_TTL
            if not primed:
                if qlen >= _PC_PREBUFFER_FRAMES:
                    primed = True
                    chunk = _pc_queue.popleft()
                else:
                    # Fill pacat while waiting for jitter buffer — avoid underrun spikes.
                    chunk = silence
            elif qlen:
                chunk = _pc_queue.popleft()
            else:
                # Gap: do not repeat the last frame (that sounds robotic). Soft silence.
                chunk = silence
                if not fresh:
                    primed = False

        try:
            assert _pc_proc.stdin is not None
            _pc_proc.stdin.write(chunk)
            since_flush += 1
            # Flushing every frame was starving PipeWire; batch a few.
            if since_flush >= 4:
                _pc_proc.stdin.flush()
                since_flush = 0
        except BrokenPipeError:
            _pc_proc = None
            continue
        except OSError:
            _pc_proc = None
            continue

        next_t += 0.02
        delay = next_t - time.monotonic()
        if delay > 0.0005:
            time.sleep(delay)
        elif delay < -0.06:
            # More than ~3 frames behind — resync and shed backlog.
            next_t = time.monotonic()
            with _pc_lock:
                while len(_pc_queue) > _PC_PREBUFFER_FRAMES:
                    _pc_queue.popleft()


def _start_pc_feeder() -> None:
    global _pc_feeder
    ensure_pc_mic_device()
    _retire_vban_conf()
    if _pc_feeder and _pc_feeder.is_alive():
        return
    _pc_feeder = threading.Thread(target=_pc_feeder_loop, daemon=True, name="gs-pc-mic")
    _pc_feeder.start()


def _stop_pc_feeder() -> None:
    global _pc_proc, _pc_feeder
    if _pc_proc is not None:
        try:
            if _pc_proc.stdin:
                _pc_proc.stdin.close()
        except OSError:
            pass
        try:
            _pc_proc.terminate()
        except OSError:
            pass
        _pc_proc = None
    # Device stays loaded so Steam keeps the preference; feeder stops writing.


def _loop(sock: socket.socket) -> None:
    logging.info(
        "voice_bridge listening UDP %s (PCM mix + PC mic slot %s, aec=%s)",
        _port,
        PC_MIC_SLOT,
        "hdmi-monitor" if _aec_active() else "off",
    )
    while not _stop.is_set():
        try:
            sock.settimeout(0.5)
            data, addr = sock.recvfrom(MAX_PACKET)
        except socket.timeout:
            continue
        except OSError:
            if _stop.is_set():
                break
            continue
        parsed = _parse(data)
        if not parsed:
            continue
        now = time.time()
        with _lock:
            row = _clients.get(addr) or {"seq": 0}
            row.update({"pcm": parsed["pcm"], "at": now, "slot": parsed["slot"], "seq": parsed["seq"]})
            _clients[addr] = row
            _evict_stale_clients_locked(now)
        if parsed["slot"] == PC_MIC_SLOT:
            _set_pc_pcm(parsed["pcm"])
        mix = _mix_minus(addr, now)
        if not mix:
            continue
        reply = _header(parsed["slot"], parsed["seq"], len(mix) // 2, SAMPLE_RATE) + mix
        try:
            sock.sendto(reply, addr)
        except OSError as e:
            logging.warning("voice_bridge sendto %s failed: %s", addr, e)


def start(port: int = DEFAULT_PORT) -> Dict:
    global _thread, _sock, _port
    if _thread and _thread.is_alive():
        mic = ensure_pc_mic_device()
        _start_pc_feeder()
        out = {"ok": True, "port": _port, "already": True}
        out.update(_pc_mic_status(mic))
        return out
    _stop.clear()
    _port = int(port or DEFAULT_PORT)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", _port))
    _sock = sock
    _thread = threading.Thread(target=_loop, args=(sock,), daemon=True, name="gs-voice")
    _thread.start()
    mic = ensure_pc_mic_device()
    _start_pc_feeder()
    try:
        from host_tuning import wan_setup

        wan_setup.ensure_voice(True)
    except Exception:
        logging.debug("wan voice map", exc_info=True)
    out = {
        "ok": True,
        "port": _port,
        "sampleRate": SAMPLE_RATE,
        "isolation": "client-udp-only",
    }
    out.update(_pc_mic_status(mic))
    return out


def stop() -> None:
    _stop.set()
    _stop_pc_feeder()
    if _sock:
        try:
            _sock.close()
        except OSError:
            pass
    if _thread:
        _thread.join(timeout=1)
    try:
        from host_tuning import wan_setup

        def _unmap() -> None:
            try:
                wan_setup.ensure_voice(False)
            except Exception:
                pass

        threading.Thread(target=_unmap, daemon=True, name="gs-voice-wan-unmap").start()
    except Exception:
        pass


def _pc_mic_status(mic: Optional[Dict] = None) -> Dict:
    mic = mic or {
        "ok": _pc_ready,
        "device": PC_MIC_NAME,
        "source": PC_MIC_SOURCE,
        "error": _pc_error,
    }
    aec = bool(mic.get("aec")) if "aec" in (mic or {}) else _aec_active()
    return {
        "pcMic": PC_MIC_NAME,
        "pcMicSource": PC_MIC_SOURCE,
        "pcMicSlot": PC_MIC_SLOT,
        "pcMicReady": bool(mic.get("ok")),
        "pcMicError": mic.get("error"),
        "aec": aec,
        "aecMode": "hdmi-monitor-webrtc" if aec else "off",
        "note": (
            f"Slot {PC_MIC_SLOT} → PipeWire “{PC_MIC_NAME}”. "
            + (
                "WebRTC AEC uses HDMI monitor as reference (speakers OK, Sunshine-safe)."
                if aec
                else "AEC off — raw phone uplink (set GAMESPHERE_MIC_AEC=1)."
            )
            + " No VBAN."
        ),
    }


def status() -> Dict:
    now = time.time()
    with _lock:
        n = sum(1 for row in _clients.values() if now - row["at"] <= CLIENT_TTL)
        slots: List[int] = sorted(
            {int(row.get("slot", -1)) for row in _clients.values() if now - row["at"] <= CLIENT_TTL}
        )
    out = {
        "ok": True,
        "port": _port,
        "running": bool(_thread and _thread.is_alive()),
        "clients": n,
        "slots": slots,
        "sampleRate": SAMPLE_RATE,
    }
    out.update(_pc_mic_status())
    return out
