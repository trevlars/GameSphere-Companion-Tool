"""Existing Companion UDP mixer (GSVC) — do not start a second mixer."""

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

_spec = importlib.util.spec_from_file_location(
    "voice_bridge",
    os.path.join(ROOT, "host_tuning", "voice_bridge.py"),
)
voice_bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(voice_bridge)


def _pkt(slot: int, seq: int, pcm: bytes) -> bytes:
    samples = len(pcm) // 2
    return (
        voice_bridge.MAGIC
        + bytes([voice_bridge.VERSION, slot & 0xFF])
        + struct.pack("!HHH", seq, samples, voice_bridge.SAMPLE_RATE)
        + pcm
    )


class VoiceBridgeTests(unittest.TestCase):
    def setUp(self):
        voice_bridge.stop()
        self.port = 48029
        st = voice_bridge.start(port=self.port)
        self.assertTrue(st.get("ok"))
        self.assertEqual(st.get("port"), self.port)

    def tearDown(self):
        voice_bridge.stop()

    def test_parse_rejects_bad_magic(self):
        self.assertIsNone(voice_bridge._parse(b"XXXX" + b"\x00" * 12))
        pcm = b"\x00\x01" * 8
        row = voice_bridge._parse(_pkt(1, 3, pcm))
        self.assertIsNotNone(row)
        self.assertEqual(row["slot"], 1)
        self.assertEqual(row["seq"], 3)
        self.assertEqual(row["pcm"], pcm)

    def test_mix_minus_two_clients(self):
        a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        a.settimeout(1.0)
        b.settimeout(1.0)
        dest = ("127.0.0.1", self.port)
        pcm_a = struct.pack("<h", 1000) * 8
        pcm_b = struct.pack("<h", 2000) * 8
        try:
            a.sendto(_pkt(0, 1, pcm_a), dest)
            time.sleep(0.05)
            b.sendto(_pkt(1, 1, pcm_b), dest)
            data, _ = b.recvfrom(2048)
            parsed = voice_bridge._parse(data)
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["pcm"], pcm_a)
            a.sendto(_pkt(0, 2, pcm_a), dest)
            data, _ = a.recvfrom(2048)
            parsed = voice_bridge._parse(data)
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["pcm"], pcm_b)
        finally:
            a.close()
            b.close()


if __name__ == "__main__":
    unittest.main()
