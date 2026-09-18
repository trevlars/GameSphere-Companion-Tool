"""Crash-safe state writes — a killed daemon must not corrupt config."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from host_tuning import json_store


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_write_json_creates_parent_dirs(self):
        path = os.path.join(self.tmp.name, "nested", "deeper", "state.json")
        json_store.write_json_atomic(path, {"a": 1})
        self.assertEqual(json_store.read_json(path), {"a": 1})

    def test_write_leaves_no_temp_files(self):
        path = os.path.join(self.tmp.name, "state.json")
        json_store.write_json_atomic(path, {"ok": True})
        leftovers = [n for n in os.listdir(self.tmp.name) if n.startswith(".gs-tmp-")]
        self.assertEqual(leftovers, [])

    def test_unserializable_payload_keeps_previous_file(self):
        path = os.path.join(self.tmp.name, "apps.json")
        json_store.write_json_atomic(path, {"apps": ["Celeste"]})
        with self.assertRaises(TypeError):
            json_store.write_json_atomic(path, {"apps": {1, 2, 3}})
        # Original content survives a failed write instead of being truncated.
        self.assertEqual(json_store.read_json(path), {"apps": ["Celeste"]})

    def test_overwrite_is_complete_not_appended(self):
        path = os.path.join(self.tmp.name, "state.json")
        json_store.write_json_atomic(path, {"long": "x" * 500})
        json_store.write_json_atomic(path, {"short": 1})
        self.assertEqual(json_store.read_json(path), {"short": 1})

    def test_read_json_tolerates_corrupt_and_missing(self):
        missing = os.path.join(self.tmp.name, "nope.json")
        self.assertEqual(json_store.read_json(missing, {"d": 1}), {"d": 1})
        corrupt = os.path.join(self.tmp.name, "corrupt.json")
        with open(corrupt, "w", encoding="utf-8") as fh:
            fh.write('{"truncated": ')
        self.assertIsNone(json_store.read_json(corrupt))
        self.assertEqual(json_store.read_json(corrupt, {}), {})

    def test_non_ascii_game_names_round_trip(self):
        path = os.path.join(self.tmp.name, "apps.json")
        name = "ロマンシング サガ — Café"
        json_store.write_json_atomic(path, {"apps": [{"name": name}]})
        self.assertEqual(json_store.read_json(path)["apps"][0]["name"], name)
        with open(path, encoding="utf-8") as fh:
            self.assertIn(name, fh.read())


class SunshineConfigWriteTests(unittest.TestCase):
    """save_sunshine_config must never leave a half-written apps.json."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_save_is_atomic_and_backs_up(self):
        import main

        path = os.path.join(self.tmp.name, "apps.json")
        main.save_sunshine_config(path, {"env": "", "apps": [{"name": "Hades"}]})
        main.save_sunshine_config(path, {"env": "", "apps": [{"name": "Hades"}, {"name": "Celeste"}]})

        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(len(saved["apps"]), 2)
        self.assertTrue(os.path.isfile(path + ".backup"))
        leftovers = [n for n in os.listdir(self.tmp.name) if n.startswith(".gs-tmp-")]
        self.assertEqual(leftovers, [])

    def test_failed_save_preserves_existing_apps(self):
        import main

        path = os.path.join(self.tmp.name, "apps.json")
        main.save_sunshine_config(path, {"env": "", "apps": [{"name": "Hades"}]})
        with self.assertRaises(Exception):
            main.save_sunshine_config(path, {"env": "", "apps": {"bad"}})
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["apps"], [{"name": "Hades"}])


if __name__ == "__main__":
    unittest.main()
