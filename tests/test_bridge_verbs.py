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

    def test_rom_row_ra_hash_lowercase_md5(self):
        metadata_catalog = _load("metadata_catalog")

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GAMESPHERE_CONFIG_DIR"] = tmp
            rom = os.path.join(tmp, "demo.nes")
            with open(rom, "wb") as fh:
                fh.write(b"NES\x1a\x00\x00")
            row = metadata_catalog._rom_row(rom, "demo.nes", "nes")
            self.assertIsNotNone(row)
            self.assertEqual(row["raHashKind"], "md5")
            self.assertEqual(len(row["raHash"]), 32)
            self.assertEqual(row["raHash"], row["raHash"].lower())
            self.assertEqual(row["hash"], row["raHash"].upper())

    def test_disk_hash_cache_reuses_mtime(self):
        metadata_catalog = _load("metadata_catalog")

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GAMESPHERE_CONFIG_DIR"] = tmp
            rom = os.path.join(tmp, "cached.gba")
            with open(rom, "wb") as fh:
                fh.write(b"test-rom-bytes")
            first = metadata_catalog._cached_ra_hash(rom)
            second = metadata_catalog._cached_ra_hash(rom)
            self.assertEqual(first, second)
            metadata_catalog._save_disk_cache()
            cache_path = metadata_catalog._cache_path()
            self.assertTrue(os.path.isfile(cache_path))


class HostIdentityTests(unittest.TestCase):
    def test_steamid64_from_loginusers_vdf(self):
        host_identity = _load("host_identity")

        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "config")
            os.makedirs(cfg)
            vdf = os.path.join(cfg, "loginusers.vdf")
            with open(vdf, "w", encoding="utf-8") as fh:
                fh.write(
                    '"users"\n{\n'
                    '"76561198012345678"\n{\n'
                    '"AccountName"\t"testuser"\n'
                    '"MostRecent"\t"1"\n'
                    "}\n}\n"
                )
            sid = host_identity._vdf_most_recent_steamid64(vdf)
            self.assertEqual(sid, "76561198012345678")

    def test_snapshot_includes_steam_id64(self):
        host_identity = _load("host_identity")

        with mock.patch.object(host_identity, "steamid64", return_value="76561198012345678"):
            with mock.patch.object(host_identity, "_community_profile", return_value={}):
                payload = host_identity.snapshot(force=True)
        self.assertEqual(payload.get("hostSteamId"), "76561198012345678")
        self.assertEqual(payload.get("steamId64"), "76561198012345678")


class DoctorMicTests(unittest.TestCase):
    def _mic_check_with_mocks(self, *, stream_active: bool, voice_status: dict):
        doctor = _load("doctor")
        fake_coop = mock.MagicMock()
        fake_coop.stream_active.return_value = stream_active
        fake_voice = mock.MagicMock()
        fake_voice.status.return_value = voice_status
        with mock.patch.dict(
            sys.modules,
            {
                "host_tuning.couch_coop": fake_coop,
                "host_tuning.voice_bridge": fake_voice,
            },
        ):
            return doctor._mic_check()

    def test_mic_idle_passes_without_pc_mic(self):
        check = self._mic_check_with_mocks(
            stream_active=False,
            voice_status={"running": True, "pcMicReady": False, "clients": 0},
        )
        self.assertTrue(check.get("ok"))
        self.assertTrue(check.get("info"))

    def test_mic_fails_during_session(self):
        check = self._mic_check_with_mocks(
            stream_active=True,
            voice_status={
                "running": True,
                "pcMicReady": False,
                "clients": 1,
                "pcMicError": "missing source",
            },
        )
        self.assertFalse(check.get("ok"))


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
