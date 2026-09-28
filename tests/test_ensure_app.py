"""ENSUREAPP — Push to Sphere host ensure."""

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


def _load(name: str):
    import importlib.util

    path = os.path.join(ROOT, "host_tuning", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"host_tuning.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class EnsureAppTests(unittest.TestCase):
    def test_missing_app_id(self):
        ensure_app = _load("ensure_app")
        out = ensure_app.ensure_steam_app({})
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "missing_steam_app_id")

    def test_rejects_non_digit(self):
        ensure_app = _load("ensure_app")
        out = ensure_app.ensure_steam_app({"steamAppId": "abc"})
        self.assertFalse(out.get("ok"))

    def test_already_present(self):
        ensure_app = _load("ensure_app")
        with tempfile.TemporaryDirectory() as tmp:
            apps_path = os.path.join(tmp, "apps.json")
            with open(apps_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "apps": [
                            {
                                "name": "Celeste",
                                "cmd": "",
                                "detached": ["steam steam://rungameid/504230"],
                                "_gamesphere_store": "Steam",
                                "_gamesphere_store_key": "steam:504230",
                            }
                        ]
                    },
                    fh,
                )

            def fake_config(auto_detect=True):
                return {
                    "SUNSHINE_APPS_JSON_PATH": apps_path,
                    "STEAM_LIBRARY_VDF_PATH": os.path.join(tmp, "missing.vdf"),
                    "STEAMGRIDDB_API_KEY": "",
                    "SUNSHINE_GRIDS_FOLDER": tmp,
                }

            with mock.patch.object(ensure_app, "_config_paths", side_effect=fake_config):
                with mock.patch.dict("sys.modules", {"main": mock.MagicMock()}):
                    import main as import_main  # noqa: F401 — patched below via ensure_app import path

            # Patch import inside ensure_steam_app by stubbing validate via _config_paths
            # and stubbing main module attributes used after config.
            fake_main = mock.MagicMock()
            fake_main.get_sunshine_config.side_effect = lambda path: json.load(open(path, encoding="utf-8"))
            fake_main.save_sunshine_config = mock.MagicMock()
            fake_main.get_game_name.return_value = "Celeste"
            fake_main.installed_steam_app_ids.return_value = {"504230"}
            fake_main._build_steam_app.side_effect = Exception("should not build")

            with mock.patch.object(ensure_app, "_config_paths", side_effect=fake_config):
                with mock.patch.dict(sys.modules, {"main": fake_main}):
                    out = ensure_app.ensure_steam_app({"steamAppId": 504230})
            self.assertTrue(out.get("ok"))
            self.assertEqual(out.get("state"), "already_present")
            self.assertEqual(out.get("name"), "Celeste")
            fake_main.save_sunshine_config.assert_not_called()

    def test_adds_missing_app(self):
        ensure_app = _load("ensure_app")
        with tempfile.TemporaryDirectory() as tmp:
            apps_path = os.path.join(tmp, "apps.json")
            with open(apps_path, "w", encoding="utf-8") as fh:
                json.dump({"apps": [{"name": "Desktop", "cmd": "Desktop"}]}, fh)

            def fake_config(auto_detect=True):
                return {
                    "SUNSHINE_APPS_JSON_PATH": apps_path,
                    "STEAM_LIBRARY_VDF_PATH": os.path.join(tmp, "missing.vdf"),
                    "STEAMGRIDDB_API_KEY": "",
                    "SUNSHINE_GRIDS_FOLDER": tmp,
                }

            fake_main = mock.MagicMock()

            def load_cfg(path):
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)

            def save_cfg(path, config):
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(config, fh)

            fake_main.get_sunshine_config.side_effect = load_cfg
            fake_main.save_sunshine_config.side_effect = save_cfg
            fake_main.get_game_name.return_value = "Hades"
            fake_main.fetch_grid_from_steamgriddb.return_value = None
            fake_main.installed_steam_app_ids.return_value = set()
            fake_main._build_steam_app.side_effect = lambda aid, name, grid: {
                "name": name,
                "cmd": "",
                "detached": [f"steam steam://rungameid/{aid}"],
                "image-path": grid or "",
            }

            with mock.patch.object(ensure_app, "_config_paths", side_effect=fake_config):
                with mock.patch.object(ensure_app, "_kick_steam_install"):
                    with mock.patch.dict(sys.modules, {"main": fake_main}):
                        out = ensure_app.ensure_steam_app(
                            {"steamAppId": "1145360", "name": "Hades", "install": False}
                        )

            self.assertTrue(out.get("ok"), out)
            self.assertEqual(out.get("state"), "added_installing")
            self.assertEqual(out.get("name"), "Hades")
            saved = json.load(open(apps_path, encoding="utf-8"))
            steam_apps = [
                a
                for a in saved["apps"]
                if str(a.get("_gamesphere_store_key") or "") == "steam:1145360"
            ]
            self.assertEqual(len(steam_apps), 1)

    def test_json_entry_line(self):
        ensure_app = _load("ensure_app")
        with mock.patch.object(
            ensure_app,
            "ensure_steam_app",
            return_value={"ok": True, "state": "already_present", "steamAppId": "570"},
        ):
            raw = ensure_app.ensure_steam_app_json('{"steamAppId":570}')
        payload = json.loads(raw)
        self.assertTrue(payload.get("ok"))


class EnsureAppCapsTests(unittest.TestCase):
    def test_caps_lists_ensureapp(self):
        # Source-level: bridge CAPS string includes ENSUREAPP.
        path = os.path.join(ROOT, "host_tuning", "bridge.py")
        text = open(path, encoding="utf-8").read()
        self.assertIn("ENSUREAPP", text)
        self.assertIn('elif verb == "ENSUREAPP":', text)


if __name__ == "__main__":
    unittest.main()
