"""Frame-drop auto-pause hysteresis (no live host required)."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from host_tuning import coop_pause


class CoopPauseTests(unittest.TestCase):
    def setUp(self):
        coop_pause._clients.clear()
        coop_pause._paused = False
        coop_pause._pause_reason = ""
        coop_pause._last_resume = 0.0
        coop_pause._auto_pause_latched = False

    def test_solo_never_pauses(self):
        for _ in range(6):
            coop_pause.note_sample({"client_id": "host", "role": "host", "drop_rate": 0.5})
        snap = coop_pause.snapshot()
        self.assertFalse(snap["pauseRecommended"])
        self.assertLess(snap["clientCount"], 2)

    def test_two_clients_bad_then_recover(self):
        for _ in range(3):
            coop_pause.note_sample({"client_id": "host", "role": "host", "is_host": True, "drop_rate": 0.0})
            coop_pause.note_sample({"client_id": "p2", "role": "guest", "drop_rate": 0.2})
        snap = coop_pause.snapshot()
        self.assertTrue(snap["multiplayer"])
        self.assertTrue(snap["pauseRecommended"])
        for _ in range(6):
            coop_pause.note_sample({"client_id": "host", "role": "host", "is_host": True, "drop_rate": 0.0})
            coop_pause.note_sample({"client_id": "p2", "role": "guest", "drop_rate": 0.0})
        snap = coop_pause.snapshot()
        self.assertFalse(snap["pauseRecommended"])

    def test_host_unpause_clears_latch(self):
        for _ in range(3):
            coop_pause.note_sample({"client_id": "host", "role": "host", "drop_rate": 0.0})
            coop_pause.note_sample({"client_id": "p2", "role": "guest", "drop_rate": 0.3})
        self.assertTrue(coop_pause.snapshot()["pauseRecommended"])
        coop_pause.host_unpaused()
        self.assertFalse(coop_pause.snapshot()["pauseRecommended"])


if __name__ == "__main__":
    unittest.main()
