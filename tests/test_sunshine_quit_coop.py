"""sunshine_quit must not close the game while co-op guests are still connected."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SunshineQuitCoopTests(unittest.TestCase):
    def test_skips_when_multiple_sunshine_pads(self):
        from host_tuning import sunshine_quit

        with mock.patch.object(sunshine_quit, "_other_stream_clients_connected", return_value=True):
            self.assertFalse(sunshine_quit.close_current_game())

    def test_other_clients_true_when_two_pads(self):
        from host_tuning import sunshine_quit

        status = {"sunshine": [{"name": "pad0"}, {"name": "pad1"}]}
        with mock.patch("host_tuning.couch_coop.status", return_value=status):
            self.assertTrue(sunshine_quit._other_stream_clients_connected())


if __name__ == "__main__":
    unittest.main()
