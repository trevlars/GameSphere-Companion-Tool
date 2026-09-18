"""SESSIONDATA must not rewrite the whole session history per packet."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from host_tuning import session_telemetry as st


class ClientTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "sessions.json")
        patcher = mock.patch.object(st, "sessions_path", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        st.save_sessions([{"id": "abc", "games": [], "client_samples": []}])
        # Reset the flush timer between tests.
        st._pending_sessions = None  # noqa: SLF001 — test reset
        st._pending_flushed_at = 0.0  # noqa: SLF001
        self.addCleanup(self._reset)

    def _reset(self):
        st._pending_sessions = None  # noqa: SLF001
        st._pending_flushed_at = 0.0  # noqa: SLF001

    def _sample(self, rtt):
        return {"rtt_ms": rtt, "drop_rate": 0.0, "bitrate_kbps": 20000, "target_bitrate_kbps": 20000}

    def test_samples_are_capped(self):
        for i in range(st._CLIENT_SAMPLE_WINDOW * 3):  # noqa: SLF001
            st.append_client_telemetry(self._sample(10 + (i % 5)))
        st.flush_client_telemetry()
        samples = st.load_sessions()[-1]["client_samples"]
        self.assertLessEqual(len(samples), st._CLIENT_SAMPLE_WINDOW)  # noqa: SLF001

    def test_writes_are_throttled_not_per_packet(self):
        with mock.patch.object(st, "save_sessions", wraps=st.save_sessions) as saver:
            for _ in range(50):
                st.append_client_telemetry(self._sample(12))
            # 50 packets must not mean 50 full-history writes.
            self.assertLessEqual(saver.call_count, 2)
            st.flush_client_telemetry()
            self.assertGreaterEqual(saver.call_count, 1)

    def test_buffered_samples_survive_flush(self):
        st.append_client_telemetry(self._sample(15))
        st.append_client_telemetry(self._sample(25))
        st.flush_client_telemetry()
        session = st.load_sessions()[-1]
        self.assertEqual(len(session["client_samples"]), 2)
        self.assertEqual(session["avg_rtt_ms"], 20.0)
        self.assertEqual(session["grade"], "Good")

    def test_last_session_json_omits_raw_samples(self):
        for _ in range(10):
            st.append_client_telemetry(self._sample(5))
        st.flush_client_telemetry()
        payload = st.last_session_json()
        self.assertNotIn("client_samples", payload)
        self.assertIn("grade", payload)

    def test_garbage_batch_is_ignored(self):
        for bad in ({}, None, "nope", 5, []):
            st.append_client_telemetry(bad)
        st.flush_client_telemetry()
        self.assertEqual(st.load_sessions()[-1]["client_samples"], [])

    def test_no_active_session_is_safe(self):
        st.save_sessions([])
        self._reset()
        st.append_client_telemetry(self._sample(10))
        st.flush_client_telemetry()
        self.assertEqual(st.load_sessions(), [])


if __name__ == "__main__":
    unittest.main()
