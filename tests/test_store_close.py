"""sunshine_apps + store close routing tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class SunshineAppsTests(unittest.TestCase):
    def test_app_for_sunshine_id_one_based(self):
        from host_tuning import sunshine_apps

        apps = [
            {"name": "Desktop"},
            {"name": "Hades", "_gamesphere_store_key": "epic:Hades"},
        ]
        self.assertEqual(sunshine_apps.app_for_sunshine_id("2", apps)["name"], "Hades")

    def test_close_metadata_prefers_store_fields(self):
        from host_tuning import sunshine_apps

        meta = sunshine_apps.close_metadata_from_app(
            {
                "name": "Forza",
                "_gamesphere_store": "Xbox",
                "_gamesphere_store_key": "xbox:forza",
                "_gamesphere_exe_path": "C:\\XboxGames\\Forza\\Content\\Forza.exe",
            }
        )
        self.assertEqual(meta["store"], "Xbox")
        self.assertEqual(meta["store_key"], "xbox:forza")
        self.assertIn("Forza.exe", meta["exe_path"])


class SunshineQuitRoutingTests(unittest.TestCase):
    def test_routes_store_app_to_store_close(self):
        from host_tuning import sunshine_quit

        app = {
            "name": "Hades",
            "_gamesphere_store": "Epic Games",
            "_gamesphere_store_key": "epic:Hades",
            "_gamesphere_exe_path": "C:\\Epic\\Hades\\Hades.exe",
        }
        with mock.patch("host_tuning.sunshine_apps.app_for_sunshine_id", return_value=app):
            with mock.patch.object(sunshine_quit, "close_store_app", return_value=True) as store_close:
                with mock.patch.object(sunshine_quit, "close_steam_app_id") as steam_close:
                    self.assertTrue(sunshine_quit.close_sunshine_app("42"))
                    store_close.assert_called_once()
                    steam_close.assert_not_called()

    def test_session_end_passes_payload(self):
        import importlib.util

        path = os.path.join(ROOT, "host_tuning", "coop_session.py")
        spec = importlib.util.spec_from_file_location("host_tuning.coop_session", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        payload = {"reason": "host_quit", "game": "Hades", "store": "Epic Games"}
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GAMESPHERE_CONFIG_DIR"] = tmp
            with mock.patch("host_tuning.sunshine_quit.close_current_game_async") as close_async:
                result = mod.session_end(payload)
                self.assertTrue(result.get("ok"))
                close_async.assert_called_once_with(payload)


class LaunchWatcherProcessAliveTests(unittest.TestCase):
    def test_game_state_includes_process_alive(self):
        import importlib.util

        path = os.path.join(ROOT, "host_tuning", "launch_watcher.py")
        spec = importlib.util.spec_from_file_location("host_tuning.launch_watcher", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        with mock.patch.object(mod, "_proc_matches", return_value=False):
            payload = json.loads(mod.game_state_json())
            self.assertIn("processAlive", payload)
            self.assertFalse(payload["processAlive"])


class StorePrepTests(unittest.TestCase):
    def test_store_close_undo_windows(self):
        import main

        with mock.patch("main.os.name", "nt"):
            with mock.patch.object(main, "ensure_store_close_helper", return_value="C:\\GameSphere\\gamesphere-store-close.sh"):
                undo = main._store_close_undo_cmd("epic:Hades")
                self.assertIn("gamesphere-store-close", undo or "")
                self.assertIn("epic:Hades", undo or "")


if __name__ == "__main__":
    unittest.main()
