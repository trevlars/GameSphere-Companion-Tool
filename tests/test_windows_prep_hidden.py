"""Windows host-prep must not flash System32/powershell consoles."""

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

from host_tuning import service


class WindowsPrepHiddenTests(unittest.TestCase):
    def test_global_prep_cmds_include_windowstyle_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "gamesphere-host-prep.ps1")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write("# stub\n")
            cfg = mock.Mock()
            cfg.enabled = True
            with mock.patch.object(service, "write_prep_scripts"), mock.patch.object(
                service, "config_dir", return_value=tmp
            ), mock.patch.object(service.os, "name", "nt"):
                cmds = service.global_prep_cmds(cfg)
        self.assertEqual(len(cmds), 1)
        self.assertIn("-WindowStyle Hidden", cmds[0]["do"])
        self.assertIn("-WindowStyle Hidden", cmds[0]["undo"])
        self.assertIn("gamesphere-host-prep.ps1", cmds[0]["do"])
        self.assertTrue(cmds[0]["do"].endswith(" start") or cmds[0]["do"].endswith('" start'))

    def test_needs_hidden_host_prep(self):
        old = (
            'powershell -NoProfile -ExecutionPolicy Bypass -File '
            '"C:\\GameSphere\\gamesphere-host-prep.ps1" start'
        )
        new = (
            'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
            '-File "C:\\GameSphere\\gamesphere-host-prep.ps1" start'
        )
        self.assertTrue(service._needs_hidden_host_prep(old))
        self.assertFalse(service._needs_hidden_host_prep(new))
        self.assertFalse(service._needs_hidden_host_prep("bash gamesphere-host-prep.sh start"))

    def test_repair_rewrites_visible_host_prep(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "gamesphere-host-prep.ps1")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write("# stub\n")
            apps_path = os.path.join(tmp, "apps.json")
            old_do = (
                f'powershell -NoProfile -ExecutionPolicy Bypass -File "{script}" start'
            )
            old_undo = (
                f'powershell -NoProfile -ExecutionPolicy Bypass -File "{script}" stop'
            )
            payload = {
                "apps": [
                    {
                        "name": "Demo",
                        "prep-cmd": [{"do": old_do, "undo": old_undo, "elevated": False}],
                    }
                ]
            }
            with open(apps_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            fake_main = mock.Mock()
            fake_main.get_sunshine_config.return_value = payload
            fake_main.save_sunshine_config = mock.Mock()

            cfg = mock.Mock()
            cfg.enabled = True
            with mock.patch.object(service, "write_prep_scripts"), mock.patch.object(
                service, "config_dir", return_value=tmp
            ), mock.patch.object(service.os, "name", "nt"), mock.patch.dict(
                sys.modules, {"main": fake_main}
            ), mock.patch.object(service, "load_config", return_value=cfg):
                result = service.repair_windows_host_prep_cmds(apps_path)

            self.assertTrue(result.get("ok"))
            self.assertEqual(result.get("changed"), 1)
            fake_main.save_sunshine_config.assert_called_once()
            saved_apps = fake_main.save_sunshine_config.call_args[0][1]["apps"]
            entry = saved_apps[0]["prep-cmd"][0]
            self.assertIn("-WindowStyle Hidden", entry["do"])
            self.assertIn("-WindowStyle Hidden", entry["undo"])


if __name__ == "__main__":
    unittest.main()
