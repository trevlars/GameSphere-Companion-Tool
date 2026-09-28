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

    def test_busy_alone_is_not_other_clients(self):
        """Host phone still attached during SESSIONEND — must not skip quit."""
        from host_tuning import sunshine_quit

        with mock.patch("host_tuning.couch_coop.status", return_value={"sunshine": [{"name": "pad0"}]}):
            with mock.patch.object(
                sunshine_quit,
                "_serverinfo",
                return_value={"state": "SUNSHINE_SERVER_BUSY", "currentgame": "12"},
            ):
                self.assertFalse(sunshine_quit._other_stream_clients_connected())

    def test_host_quit_closes_while_sunshine_busy(self):
        from host_tuning import sunshine_quit

        with mock.patch.object(sunshine_quit, "_other_stream_clients_connected", return_value=False):
            with mock.patch.object(
                sunshine_quit,
                "_serverinfo",
                return_value={"state": "SUNSHINE_SERVER_BUSY", "currentgame": "12"},
            ):
                with mock.patch.object(sunshine_quit, "close_sunshine_app", return_value=True) as close:
                    self.assertTrue(
                        sunshine_quit.close_current_game({"reason": "host_quit", "game": "Hades"})
                    )
                    close.assert_called_once_with("12", {"reason": "host_quit", "game": "Hades"})

    def test_closes_by_game_name_when_currentgame_cleared(self):
        from host_tuning import sunshine_quit

        app = {
            "name": "Hades",
            "cmd": "steam steam://rungameid/1145360",
        }
        with mock.patch.object(sunshine_quit, "_other_stream_clients_connected", return_value=False):
            with mock.patch.object(
                sunshine_quit,
                "_serverinfo",
                return_value={"state": "SUNSHINE_SERVER_FREE", "currentgame": "0"},
            ):
                with mock.patch("host_tuning.sunshine_apps.load_apps", return_value=[app]):
                    with mock.patch.object(sunshine_quit, "close_steam_app_id", return_value=True) as close:
                        self.assertTrue(
                            sunshine_quit.close_current_game(
                                {"reason": "host_quit", "game": "Hades"}
                            )
                        )
                        close.assert_called_once_with("1145360")


if __name__ == "__main__":
    unittest.main()
