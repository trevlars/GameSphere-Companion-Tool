"""In-stream voice mixer for GameSphere clients + host virtual mic.

Clients send 16 kHz s16le mono PCM over UDP. Companion mixes those packets only
and sends each client the mix minus itself. Game / HDMI audio is never captured
here — do not attach WebRTC AEC to HDMI (crackles Sunshine).

PC mic path (Linux/PipeWire): slot 0 uplink is also written into a virtual
capture device named "GameSphere Mic" so Steam / Discord / games can select it.
Guests (slots 1–3) stay party-only. No VBAN.

Routing note: replies use the kernel route to each client. Do not install a
ZeroTier/VPN more-specific route for the LAN prefix (e.g. 10.0.5.0/24 via zt)
or voice uplink works while downlink never leaves the Ethernet NIC.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

MAGIC = b"GSVC"
VERSION = 1
HEADER_SIZE = 12  # magic(4) + ver(1) + slot(1) + seq(2) + samples(2) + rate(2)
DEFAULT_PORT = int(os.environ.get("GAMESPHERE_VOICE_PORT", "48020"))
SAMPLE_RATE = 16000
MAX_PACKET = 2048
CLIENT_TTL = 2.5
# Couch co-op is 4 seats; the cap only exists to bound an adversarial flood.
_MAX_CLIENTS = 16
PC_MIC_SLOT = int(os.environ.get("GAMESPHERE_PC_MIC_SLOT", "0"))
PC_MIC_NAME = os.environ.get("GAMESPHERE_PC_MIC_NAME", "GameSphere Mic")
PC_MIC_SINK = os.environ.get("GAMESPHERE_PC_MIC_SINK", "gamesphere_mic_sink")
PC_MIC_SOURCE = os.environ.get("GAMESPHERE_PC_MIC_SOURCE", "gamesphere_mic")
FRAME_BYTES = 640  # 320 samples * 2 bytes (20 ms @ 16 kHz)

_lock = threading.Lock()
_clients: Dict[Tuple[str, int], Dict] = {}
_thread: Optional[threading.Thread] = None
_sock: Optional[socket.socket] = None
_stop = threading.Event()
_port = DEFAULT_PORT

_pc_lock = threading.Lock()
_pc_pcm = b"\x00" * FRAME_BYTES
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


def ensure_pc_mic_device() -> Dict:
    """Create PipeWire/Pulse null-sink + remap-source named GameSphere Mic (idempotent)."""
    global _pc_ready, _pc_error
    if os.name == "nt" or not shutil.which("pactl"):
        _pc_ready = False
        _pc_error = "PipeWire/Pulse pactl not available (Linux host required for GameSphere Mic)"
        return {"ok": False, "error": _pc_error, "device": PC_MIC_NAME}

    try:
        if not _sink_exists(PC_MIC_SINK):
            desc = "GameSphere Mic Sink"
            proc = _pactl(
                "load-module",
                "module-null-sink",
                f"sink_name={PC_MIC_SINK}",
                "rate=16000",
                "channels=1",
                f"sink_properties=device.description={desc}",
            )
            if proc.returncode != 0:
                _pc_error = (proc.stderr or proc.stdout or "null-sink failed").strip()
                _pc_ready = False
                return {"ok": False, "error": _pc_error, "device": PC_MIC_NAME}

        if not _source_exists(PC_MIC_SOURCE):
            # device.description may contain spaces — quote for pactl.
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

        # Friendly card name in pavucontrol / Steam
        _pactl("set-source-property", PC_MIC_SOURCE, "device.description", PC_MIC_NAME)
        _pc_ready = True
        _pc_error = None
        return {
            "ok": True,
            "device": PC_MIC_NAME,
            "source": PC_MIC_SOURCE,
            "sink": PC_MIC_SINK,
            "slot": PC_MIC_SLOT,
        }
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


def _set_pc_pcm(pcm: bytes) -> None:
    global _pc_pcm, _pc_at
    if not pcm:
        return
    # Pad / trim to one frame for steady pacat clock.
    if len(pcm) < FRAME_BYTES:
        pcm = pcm + (b"\x00" * (FRAME_BYTES - len(pcm)))
    elif len(pcm) > FRAME_BYTES:
        pcm = pcm[:FRAME_BYTES]
    with _pc_lock:
        _pc_pcm = pcm
        _pc_at = time.time()


def _pc_feeder_loop() -> None:
    global _pc_proc
    logging.info("pc mic feeder targeting sink %s → source %s (%s)", PC_MIC_SINK, PC_MIC_SOURCE, PC_MIC_NAME)
    silence = b"\x00" * FRAME_BYTES
    while not _stop.is_set():
        if not _pc_ready:
            ensure_pc_mic_device()
            if not _pc_ready:
                time.sleep(1.0)
                continue
        if _pc_proc is None or _pc_proc.poll() is not None:
            try:
                _pc_proc = subprocess.Popen(
                    [
                        "pacat",
                        "--playback",
                        "--raw",
                        "--format=s16le",
                        f"--rate={SAMPLE_RATE}",
                        "--channels=1",
                        f"--device={PC_MIC_SINK}",
                        "--latency-msec=60",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                logging.warning("pacat not found — GameSphere Mic feeder disabled")
                time.sleep(2.0)
                continue
            except OSError as exc:
                logging.warning("pacat start failed: %s", exc)
                time.sleep(1.0)
                continue
        now = time.time()
        with _pc_lock:
            chunk = _pc_pcm if (now - _pc_at) <= CLIENT_TTL else silence
        try:
            assert _pc_proc.stdin is not None
            _pc_proc.stdin.write(chunk)
            _pc_proc.stdin.flush()
        except BrokenPipeError:
            _pc_proc = None
            continue
        except OSError:
            _pc_proc = None
            continue
        # Pace ~20 ms frames
        time.sleep(0.02)


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
    logging.info("voice_bridge listening UDP %s (PCM mix + PC mic slot %s, no HDMI AEC)", _port, PC_MIC_SLOT)
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
    return {
        "pcMic": PC_MIC_NAME,
        "pcMicSource": PC_MIC_SOURCE,
        "pcMicSlot": PC_MIC_SLOT,
        "pcMicReady": bool(mic.get("ok")),
        "pcMicError": mic.get("error"),
        "note": (
            f"Mixes GameSphere mics only. Slot {PC_MIC_SLOT} → PipeWire “{PC_MIC_NAME}”. "
            "Does not tap HDMI / Sunshine audio. No VBAN."
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
