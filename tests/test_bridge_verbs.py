"""Bridge verb helpers — no live host or psutil required."""

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
    """Import a host_tuning submodule without pulling host_tuning.__init__ (psutil)."""
    import importlib.util

    path = os.path.join(ROOT, "host_tuning", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"host_tuning.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class InputRelayTests(unittest.TestCase):
    def test_merge_flag_roundtrip(self):
        input_relay = _load("input_relay")

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GAMESPHERE_CONFIG_DIR"] = tmp
            out = input_relay.handle({"merge": True, "buddySlot": 2})
            self.assertTrue(out.get("ok"))
            self.assertTrue(out.get("merge"))
            self.assertEqual(out.get("buddySlot"), 2)
            st = input_relay.status()
            self.assertTrue(st.get("merge"))
            out2 = input_relay.handle({"merge": False})
            self.assertFalse(out2.get("merge"))


class CoopSessionTests(unittest.TestCase):
    def test_kick_and_session_end_events(self):
        coop_session = _load("coop_session")

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GAMESPHERE_CONFIG_DIR"] = tmp
            kick = coop_session.kick({"uuid": "guest-abc", "reason": "test"})
            self.assertTrue(kick.get("ok"))
            end = coop_session.session_end({"reason": "host_quit"})
            self.assertTrue(end.get("ok"))
            fields = coop_session.coopstate_fields()
            events = fields.get("sessionEvents") or []
            types = [e.get("type") for e in events]
            self.assertIn("kick", types)
            self.assertIn("session_end", types)
            self.assertTrue(fields.get("sessionEndedAt"))


class MetadataCatalogTests(unittest.TestCase):
    def test_cached_empty_before_scan(self):
        metadata_catalog = _load("metadata_catalog")

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GAMESPHERE_CONFIG_DIR"] = tmp
            meta = metadata_catalog.cached(kick=False)
            self.assertIn("ownedApps", meta)
            self.assertIn("romHashes", meta)
            self.assertFalse(meta.get("ready"))

    def test_parse_vdf_pairs(self):
        metadata_catalog = _load("metadata_catalog")
        _parse_vdf_pairs = metadata_catalog._parse_vdf_pairs

        text = '"appid" "123"\n"name" "Test Game"'
        pairs = _parse_vdf_pairs(text)
        self.assertEqual(pairs.get("appid"), "123")
        self.assertEqual(pairs.get("name"), "Test Game")


class LaunchWatcherTests(unittest.TestCase):
    def test_idle_launch_result(self):
        launch_watcher = _load("launch_watcher")

        launch_watcher._LAST_LAUNCH = None  # noqa: SLF001 — test reset
        launch_watcher._LAST_RESULT.update(  # noqa: SLF001
            {"state": "idle", "game": "", "cmd": "", "detail": "", "startedAt": 0.0, "updatedAt": 0.0, "attempts": 0}
        )
        raw = launch_watcher.launch_result_json([])
        payload = json.loads(raw)
        self.assertEqual(payload.get("state"), "idle")
        self.assertIn("steamReady", payload)
        self.assertIn("message", payload)


class ZerotierGuardTests(unittest.TestCase):
    def test_lan_route_conflict_detect(self):
        zerotier = _load("zerotier")
        with mock.patch.object(zerotier, "_run", return_value=(0, "10.0.5.0/24 dev ztabc123")):
            self.assertIsNotNone(zerotier.lan_route_conflict())
        with mock.patch.object(zerotier, "_run", return_value=(0, "10.0.5.0/24 dev enp3s0")):
            self.assertIsNone(zerotier.lan_route_conflict())


if __name__ == "__main__":
    unittest.main()
