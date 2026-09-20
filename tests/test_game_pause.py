"""Host Start pulse when stream drops without graceful quit."""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from host_tuning import game_pause


class GamePauseTests(unittest.TestCase):
    def setUp(self):
        game_pause._last_graceful_quit = 0.0
        game_pause._last_pause_at = 0.0

    def test_skips_after_graceful_quit(self):
        game_pause.mark_graceful_quit("host_quit")
        with mock.patch.object(game_pause, "_pulse_start_menu") as pulse:
            self.assertFalse(game_pause.pause_on_stream_drop("prep_stop"))
            pulse.assert_not_called()

    def test_pulses_on_abrupt_drop(self):
        with mock.patch.object(game_pause, "_enabled", return_value=True), mock.patch.object(
            game_pause.threading, "Thread"
        ) as thread_cls:
            thread_cls.return_value = mock.Mock()
            self.assertTrue(game_pause.pause_on_stream_drop("prep_stop"))
            thread_cls.assert_called_once()
            args, kwargs = thread_cls.call_args
            self.assertEqual(kwargs.get("target"), game_pause._pulse_start_menu)

    def test_cooldown_blocks_repeat(self):
        with mock.patch.object(game_pause, "_enabled", return_value=True), mock.patch.object(
            game_pause.threading, "Thread"
        ) as thread_cls:
            thread_cls.return_value = mock.Mock()
            self.assertTrue(game_pause.pause_on_stream_drop("prep_stop"))
            self.assertFalse(game_pause.pause_on_stream_drop("socket_idle"))
            self.assertEqual(thread_cls.call_count, 1)

    def test_cooldown_expires(self):
        game_pause._last_pause_at = time.monotonic() - 10.0
        with mock.patch.object(game_pause, "_enabled", return_value=True), mock.patch.object(
            game_pause.threading, "Thread"
        ) as thread_cls:
            thread_cls.return_value = mock.Mock()
            self.assertTrue(game_pause.pause_on_stream_drop("prep_stop"))


if __name__ == "__main__":
    unittest.main()
