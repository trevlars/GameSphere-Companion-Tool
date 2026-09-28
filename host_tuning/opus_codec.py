"""Thin libopus ctypes wrapper for GSVC Opus uplink (BSD-licensed Opus).

Decode is required on the host; encode is used in tests. Looks up
``libopus`` via ctypes (system / Homebrew paths).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import threading
from typing import Dict, Optional

OPUS_OK = 0
OPUS_APPLICATION_VOIP = 2048
OPUS_SET_BITRATE_REQUEST = 4002
OPUS_SET_COMPLEXITY_REQUEST = 4010
OPUS_SET_SIGNAL_REQUEST = 4024
OPUS_SIGNAL_VOICE = 3001

_lib: Optional[ctypes.CDLL] = None
_lib_err: Optional[str] = None

_decoders: Dict[str, "OpusDecoder"] = {}
_dec_lock = threading.Lock()


def _load() -> Optional[ctypes.CDLL]:
    global _lib, _lib_err
    if _lib is not None:
        return _lib
    names = []
    found = ctypes.util.find_library("opus")
    if found:
        names.append(found)
    names.extend(
        [
            "libopus.so.0",
            "libopus.so",
            "libopus.dylib",
            "/usr/lib64/libopus.so.0",
            "/usr/lib/libopus.so.0",
            "/opt/homebrew/lib/libopus.dylib",
            "/usr/local/lib/libopus.dylib",
        ]
    )
    for name in names:
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue
        lib.opus_decoder_create.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.opus_decoder_create.restype = ctypes.c_void_p
        lib.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
        lib.opus_decoder_destroy.restype = None
        lib.opus_decode.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int32,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int,
            ctypes.c_int,
        ]
        lib.opus_decode.restype = ctypes.c_int
        lib.opus_encoder_create.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.opus_encoder_create.restype = ctypes.c_void_p
        lib.opus_encoder_destroy.argtypes = [ctypes.c_void_p]
        lib.opus_encoder_destroy.restype = None
        lib.opus_encode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int32,
        ]
        lib.opus_encode.restype = ctypes.c_int
        # Fixed 3-arg form works on Linux x86_64. Apple Silicon ctypes + variadic
        # ctl is unreliable — set_bitrate treats failure as soft.
        lib.opus_encoder_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        lib.opus_encoder_ctl.restype = ctypes.c_int
        _lib = lib
        _lib_err = None
        logging.info("opus_codec: loaded %s", name)
        return _lib
    _lib_err = "libopus missing (install opus / libopus)"
    logging.warning("opus_codec: %s", _lib_err)
    return None


def available() -> bool:
    return _load() is not None


class OpusDecoder:
    """Inline mono Opus decoder."""

    def __init__(self, sample_rate: int = 48000, channels: int = 1) -> None:
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self._dec = None
        lib = _load()
        if not lib:
            raise RuntimeError(_lib_err or "libopus missing")
        err = ctypes.c_int(0)
        self._dec = lib.opus_decoder_create(self.sample_rate, self.channels, ctypes.byref(err))
        if not self._dec or err.value != OPUS_OK:
            raise RuntimeError(f"opus_decoder_create failed: {err.value}")

    def close(self) -> None:
        lib = _load()
        if lib and self._dec:
            lib.opus_decoder_destroy(self._dec)
        self._dec = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def decode(self, packet: bytes, frame_samples: int, fec: bool = False) -> Optional[bytes]:
        lib = _load()
        if not lib or not self._dec or frame_samples <= 0:
            return None
        out = (ctypes.c_int16 * (frame_samples * self.channels))()
        if not packet:
            n = lib.opus_decode(self._dec, None, 0, out, frame_samples, 0)
        else:
            buf = (ctypes.c_ubyte * len(packet)).from_buffer_copy(packet)
            n = lib.opus_decode(
                self._dec,
                buf,
                len(packet),
                out,
                frame_samples,
                1 if fec else 0,
            )
        if n < 0:
            return None
        return bytes(out)[: n * self.channels * 2]


class OpusEncoder:
    """Mono Opus encoder (tests)."""

    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 1,
        bitrate: int = 64000,
        complexity: int = 5,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self._enc = None
        lib = _load()
        if not lib:
            raise RuntimeError(_lib_err or "libopus missing")
        err = ctypes.c_int(0)
        self._enc = lib.opus_encoder_create(
            self.sample_rate, self.channels, OPUS_APPLICATION_VOIP, ctypes.byref(err)
        )
        if not self._enc or err.value != OPUS_OK:
            raise RuntimeError(f"opus_encoder_create failed: {err.value}")
        # Defaults are fine for VOIP; bitrate ctl is best-effort (see set_bitrate).
        self.set_bitrate(bitrate)
        try:
            lib.opus_encoder_ctl(self._enc, OPUS_SET_COMPLEXITY_REQUEST, int(complexity))
            lib.opus_encoder_ctl(self._enc, OPUS_SET_SIGNAL_REQUEST, OPUS_SIGNAL_VOICE)
        except Exception:
            pass

    def set_bitrate(self, bitrate: int) -> None:
        lib = _load()
        if not lib or not self._enc:
            return
        try:
            rc = lib.opus_encoder_ctl(self._enc, OPUS_SET_BITRATE_REQUEST, int(bitrate))
            if rc != OPUS_OK:
                logging.debug("opus SET_BITRATE(%s) rc=%s (ignored)", bitrate, rc)
        except Exception as exc:
            logging.debug("opus SET_BITRATE failed: %s", exc)

    def close(self) -> None:
        lib = _load()
        if lib and self._enc:
            lib.opus_encoder_destroy(self._enc)
        self._enc = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def encode(self, pcm_s16le: bytes, frame_samples: int) -> Optional[bytes]:
        lib = _load()
        if not lib or not self._enc or frame_samples <= 0:
            return None
        need = frame_samples * self.channels * 2
        if len(pcm_s16le) < need:
            pcm_s16le = pcm_s16le + (b"\x00" * (need - len(pcm_s16le)))
        pcm = (ctypes.c_int16 * (frame_samples * self.channels)).from_buffer_copy(pcm_s16le[:need])
        out_max = 4000
        out = (ctypes.c_ubyte * out_max)()
        n = lib.opus_encode(self._enc, pcm, frame_samples, out, out_max)
        if n < 0:
            return None
        return bytes(out[:n])


def decode_packet(
    key: str,
    packet: bytes,
    sample_rate: int,
    frame_samples: int,
) -> Optional[bytes]:
    """Decode Opus for ``key`` (sticky decoder state). Returns s16le PCM or None."""
    if not available():
        return None
    with _dec_lock:
        dec = _decoders.get(key)
        if dec is None or getattr(dec, "sample_rate", 0) != sample_rate:
            if dec is not None:
                try:
                    dec.close()
                except Exception:
                    pass
            try:
                dec = OpusDecoder(sample_rate=sample_rate, channels=1)
            except RuntimeError as exc:
                logging.warning("opus decode create: %s", exc)
                return None
            _decoders[key] = dec
        active = dec
    try:
        return active.decode(packet, frame_samples)
    except Exception as exc:
        logging.debug("opus decode: %s", exc)
        return None


def drop_decoder(key: str) -> None:
    with _dec_lock:
        dec = _decoders.pop(key, None)
    if dec is not None:
        try:
            dec.close()
        except Exception:
            pass


def reset_all() -> None:
    with _dec_lock:
        items = list(_decoders.items())
        _decoders.clear()
    for _, dec in items:
        try:
            dec.close()
        except Exception:
            pass
