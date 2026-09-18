"""Asset selection and voice-peer eviction guards."""

from __future__ import annotations

import os
import sys
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gs_updater


def _asset(name: str) -> dict:
    return {"name": name, "browser_download_url": f"https://example.invalid/{name}", "size": 10}


class WindowsAssetPickTests(unittest.TestCase):
    def test_exact_name_is_picked(self):
        assets = [_asset("notes.txt"), _asset("GamesphereImportTool.exe")]
        picked = gs_updater.pick_asset(assets, "win")
        self.assertEqual(picked["name"], "GamesphereImportTool.exe")

    def test_unrelated_exe_is_not_substituted(self):
        # An unrelated installer must never be swapped in for our binary.
        assets = [_asset("vb-cable-setup.exe"), _asset("install-linux.sh")]
        self.assertIsNone(gs_updater.pick_asset(assets, "win"))

    def test_no_assets_returns_none(self):
        self.assertIsNone(gs_updater.pick_asset([], "win"))


class DownloadValidationTests(unittest.TestCase):
    def test_asset_size_is_tolerant_of_junk(self):
        self.assertEqual(gs_updater._asset_size({"size": 1234}), 1234)  # noqa: SLF001
        self.assertEqual(gs_updater._asset_size({"size": "nope"}), 0)  # noqa: SLF001
        self.assertEqual(gs_updater._asset_size(None), 0)  # noqa: SLF001

    def test_non_windows_binary_is_rejected(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fake.exe")
            with open(path, "wb") as fh:
                fh.write(b"<html>404</html>")
            with self.assertRaises(RuntimeError):
                gs_updater._verify_windows_exe(path)  # noqa: SLF001

            good = os.path.join(tmp, "good.exe")
            with open(good, "wb") as fh:
                fh.write(b"MZ\x90\x00")
            gs_updater._verify_windows_exe(good)  # noqa: SLF001 — must not raise


class VoiceClientEvictionTests(unittest.TestCase):
    def setUp(self):
        from host_tuning import voice_bridge

        self.vb = voice_bridge
        voice_bridge._clients.clear()  # noqa: SLF001
        self.addCleanup(voice_bridge._clients.clear)  # noqa: SLF001

    def test_idle_peers_are_dropped(self):
        now = time.time()
        self.vb._clients[("10.0.0.2", 1)] = {"at": now - 60, "pcm": b""}  # noqa: SLF001
        self.vb._clients[("10.0.0.3", 1)] = {"at": now, "pcm": b""}  # noqa: SLF001
        with self.vb._lock:  # noqa: SLF001
            self.vb._evict_stale_clients_locked(now)  # noqa: SLF001
        self.assertEqual(list(self.vb._clients), [("10.0.0.3", 1)])  # noqa: SLF001

    def test_flood_is_capped(self):
        now = time.time()
        for i in range(200):
            self.vb._clients[("10.0.0.9", i)] = {"at": now, "pcm": b""}  # noqa: SLF001
        with self.vb._lock:  # noqa: SLF001
            self.vb._evict_stale_clients_locked(now)  # noqa: SLF001
        self.assertLessEqual(len(self.vb._clients), self.vb._MAX_CLIENTS)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
