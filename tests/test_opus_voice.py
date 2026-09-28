"""GSVC Opus uplink decode + mixer smoke tests."""

from __future__ import annotations

import os
import socket
import struct
import sys
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import importlib.util

_opus_spec = importlib.util.spec_from_file_location(
    "opus_codec", os.path.join(ROOT, "host_tuning", "opus_codec.py")
)
opus_codec = importlib.util.module_from_spec(_opus_spec)
_opus_spec.loader.exec_module(opus_codec)

_vb_spec = importlib.util.spec_from_file_location(
    "voice_bridge", os.path.join(ROOT, "host_tuning", "voice_bridge.py")
)
voice_bridge = importlib.util.module_from_spec(_vb_spec)
_vb_spec.loader.exec_module(voice_bridge)


@unittest.skipUnless(opus_codec.available(), "libopus not installed")
class OpusCodecTests(unittest.TestCase):
    def test_roundtrip_speech_frame(self):
        enc = opus_codec.OpusEncoder(sample_rate=48000, bitrate=64000)
        self.addCleanup(enc.close)
        # Simple tone — not silence (Opus may emit a tiny DTX packet for silence).
        pcm = bytearray()
        for i in range(480):
            # ~440 Hz at 48 kHz
            import math

            s = int(12000 * math.sin(2 * math.pi * 440 * i / 48000))
            pcm += struct.pack("<h", s)
        pkt = enc.encode(bytes(pcm), 480)
        self.assertIsNotNone(pkt)
        self.assertGreater(len(pkt), 10)
        dec = opus_codec.OpusDecoder(sample_rate=48000)
        self.addCleanup(dec.close)
        out = dec.decode(pkt, 480)
        self.assertIsNotNone(out)
        self.assertEqual(len(out), 960)


@unittest.skipUnless(opus_codec.available(), "libopus not installed")
class OpusVoiceBridgeTests(unittest.TestCase):
    def setUp(self):
        voice_bridge.stop()
        self.port = 48031
        st = voice_bridge.start(port=self.port)
        self.assertTrue(st.get("ok"))
        self.assertTrue(st.get("opus"))

    def tearDown(self):
        voice_bridge.stop()

    def _opus_pkt(self, slot: int, seq: int, opus: bytes) -> bytes:
        return (
            voice_bridge.MAGIC
            + bytes([voice_bridge.VERSION_OPUS, slot & 0xFF])
            + struct.pack("!HHH", seq, 480, 48000)
            + opus
        )

    def test_opus_uplink_gets_reply(self):
        enc = opus_codec.OpusEncoder(sample_rate=48000, bitrate=48000)
        self.addCleanup(enc.close)
        pcm = struct.pack("<h", 2000) * 480
        opus = enc.encode(pcm, 480)
        self.assertIsNotNone(opus)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        try:
            sock.sendto(self._opus_pkt(0, 1, opus), ("127.0.0.1", self.port))
            data, _ = sock.recvfrom(2048)
            parsed = voice_bridge._parse(data)
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["ver"], voice_bridge.VERSION_PCM)
            self.assertEqual(parsed["seq"], 1)
            # Solo client → silence reply for RTT.
            self.assertEqual(len(parsed["payload"]), voice_bridge.FRAME_BYTES)
        finally:
            sock.close()

    def test_parse_rejects_unknown_version(self):
        bad = voice_bridge.MAGIC + bytes([99, 0]) + struct.pack("!HHH", 1, 0, 48000)
        self.assertIsNone(voice_bridge._parse(bad))


class VoiceBridgeAlwaysReplyTests(unittest.TestCase):
    def setUp(self):
        voice_bridge.stop()
        self.port = 48032
        st = voice_bridge.start(port=self.port)
        self.assertTrue(st.get("ok"))

    def tearDown(self):
        voice_bridge.stop()

    def test_pcm_solo_gets_silence_ack(self):
        pcm = struct.pack("<h", 1000) * voice_bridge.FRAME_SAMPLES
        pkt = (
            voice_bridge.MAGIC
            + bytes([voice_bridge.VERSION_PCM, 0])
            + struct.pack("!HHH", 7, voice_bridge.FRAME_SAMPLES, voice_bridge.SAMPLE_RATE)
            + pcm
        )
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        try:
            sock.sendto(pkt, ("127.0.0.1", self.port))
            data, _ = sock.recvfrom(2048)
            parsed = voice_bridge._parse(data)
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["seq"], 7)
            self.assertEqual(len(parsed["payload"]), voice_bridge.FRAME_BYTES)
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
