"""Steam voice input preference for GameSphere Mic."""

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

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "steam_voice",
    os.path.join(ROOT, "host_tuning", "steam_voice.py"),
)
steam_voice = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(steam_voice)


class SteamVoiceTests(unittest.TestCase):
    def test_configure_updates_selected_mic(self):
        with tempfile.TemporaryDirectory() as tmp:
            uid = "921607934"
            cfg_dir = os.path.join(tmp, uid, "config")
            os.makedirs(cfg_dir)
            path = os.path.join(cfg_dir, "localconfig.vdf")
            settings = json.dumps(
                {"selectedMic": "default", "noiseCancellation": True},
                separators=(",", ":"),
            )
            escaped = settings.replace('"', '\\"')
            with open(path, "w", encoding="utf-8") as f:
                f.write(f'\t\t"SteamVoiceSettings_{uid}"\t\t"{escaped}"\n')
            old_root = steam_voice.STEAM_USERDATA
            steam_voice.STEAM_USERDATA = tmp
            try:
                out = steam_voice.configure_steam_voice_mic("gamesphere_mic", set_pulse_default=False)
            finally:
                steam_voice.STEAM_USERDATA = old_root
            self.assertTrue(out["ok"])
            self.assertEqual(len(out["updated"]), 1)
            with open(path, encoding="utf-8") as f:
                body = f.read()
            self.assertIn("gamesphere_mic", body)
            self.assertNotIn('"default"', body)

    def test_skips_when_already_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            uid = "708606858"
            cfg_dir = os.path.join(tmp, uid, "config")
            os.makedirs(cfg_dir)
            path = os.path.join(cfg_dir, "localconfig.vdf")
            settings = json.dumps({"selectedMic": "gamesphere_mic"}, separators=(",", ":"))
            escaped = settings.replace('"', '\\"')
            with open(path, "w", encoding="utf-8") as f:
                f.write(f'\t\t"SteamVoiceSettings_{uid}"\t\t"{escaped}"\n')
            old_root = steam_voice.STEAM_USERDATA
            steam_voice.STEAM_USERDATA = tmp
            try:
                out = steam_voice.configure_steam_voice_mic("gamesphere_mic", set_pulse_default=False)
            finally:
                steam_voice.STEAM_USERDATA = old_root
            self.assertEqual(out["updated"], [])

    def test_creates_missing_voice_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            uid = "921607934"
            cfg_dir = os.path.join(tmp, uid, "config")
            os.makedirs(cfg_dir)
            path = os.path.join(cfg_dir, "localconfig.vdf")
            with open(path, "w", encoding="utf-8") as f:
                f.write('"UserLocalConfigStore"\n{\n\t"something"\t\t"1"\n}\n')
            old_root = steam_voice.STEAM_USERDATA
            steam_voice.STEAM_USERDATA = tmp
            try:
                out = steam_voice.configure_steam_voice_mic(
                    "gamesphere_mic", set_pulse_default=False, create_missing=True
                )
            finally:
                steam_voice.STEAM_USERDATA = old_root
            self.assertTrue(out["ok"])
            self.assertEqual(out["created"], [uid])
            with open(path, encoding="utf-8") as f:
                body = f.read()
            self.assertIn(f"SteamVoiceSettings_{uid}", body)
            self.assertIn("gamesphere_mic", body)

    def test_is_gamesphere_from_remote_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            flag = os.path.join(tmp, "bazzite-sunshine-remote-xbox-p1")
            with open(flag, "w", encoding="utf-8") as f:
                f.write("never\n")
            old = steam_voice.RUNTIME_DIR
            steam_voice.RUNTIME_DIR = tmp
            try:
                with mock.patch.dict(os.environ, {"SUNSHINE_CLIENT_NAME": ""}, clear=False):
                    self.assertTrue(steam_voice.is_gamesphere_stream_client())
                with open(flag, "w", encoding="utf-8") as f:
                    f.write("always\n")
                self.assertFalse(steam_voice.is_gamesphere_stream_client())
            finally:
                steam_voice.RUNTIME_DIR = old

    def test_apply_skips_steam_link(self):
        with mock.patch.object(steam_voice, "is_gamesphere_stream_client", return_value=False):
            out = steam_voice.apply_for_gamesphere_stream()
        self.assertEqual(out.get("skipped"), "not_gamesphere_client")


if __name__ == "__main__":
    unittest.main()
