"""Steam voice input preference for GameSphere Mic."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from host_tuning import steam_voice


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
                out = steam_voice.configure_steam_voice_mic("gamesphere_mic")
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
                out = steam_voice.configure_steam_voice_mic("gamesphere_mic")
            finally:
                steam_voice.STEAM_USERDATA = old_root
            self.assertEqual(out["updated"], [])


if __name__ == "__main__":
    unittest.main()
