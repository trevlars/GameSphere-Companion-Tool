"""Shortcut dedup must not cause pruning, and partial imports must say so."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import main


class ShortcutDedupPruneTests(unittest.TestCase):
    """A shortcut that loses the display-name tie-break is still installed."""

    def test_all_ids_includes_ids_dropped_by_dedup(self):
        # Two shortcuts, same display name, different appids (Eden vs Ryujinx).
        by_short = {
            111: {"name": "Zelda", "short_appid": "111", "exe": "/usr/bin/eden-game.sh", "grid_src": ""},
            222: {"name": "Zelda", "short_appid": "222", "exe": "/usr/bin/ryujinx-game.sh", "grid_src": ""},
        }
        # Exercise the dedup + all_ids contract directly on the id mapping.
        all_ids: set = set()
        result = {main._shortcut_rungameid(k): v for k, v in by_short.items()}  # noqa: SLF001
        all_ids.update(result.keys())
        self.assertEqual(len(all_ids), 2)

        # After dedup only one survives for *adding*...
        deduped = {main._shortcut_rungameid(222): by_short[222]}  # noqa: SLF001
        self.assertEqual(len(deduped), 1)

        # ...but pruning uses all_ids, so the dropped tile is preserved.
        dropped = main._shortcut_rungameid(111)  # noqa: SLF001
        config = {
            "apps": [
                {
                    "name": "Zelda (Eden)",
                    "cmd": f"steam://rungameid/{dropped}",
                    "_gamesphere_store": "Steam",
                }
            ]
        }
        updated, removed_steam, _, _, _, _, _, _, _ = main.process_existing_apps(
            config, deduped, installed_app_ids=all_ids
        )
        self.assertEqual(removed_steam, [])
        self.assertEqual(len(updated), 1)

    def test_load_shortcuts_accepts_all_ids_out_param(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        steamapps = os.path.join(tmp.name, "steamapps")
        os.makedirs(steamapps)
        vdf_path = os.path.join(steamapps, "libraryfolders.vdf")
        with open(vdf_path, "w", encoding="utf-8") as fh:
            fh.write('"libraryfolders"\n{\n}\n')
        collected: set = set()
        # No shortcuts.vdf present: must not raise, and must leave the set empty.
        result = main.load_steam_nonsteam_shortcuts(vdf_path, collected)
        self.assertEqual(result, {})
        self.assertEqual(collected, set())


class CoopPauseClientIdTests(unittest.TestCase):
    def test_guests_without_ids_are_not_merged(self):
        from host_tuning import coop_pause

        a = coop_pause._cid({"role": "guest", "client_name": "Alex"})  # noqa: SLF001
        b = coop_pause._cid({"role": "guest", "client_name": "Bo"})  # noqa: SLF001
        self.assertNotEqual(a, b)

    def test_address_distinguishes_anonymous_guests(self):
        from host_tuning import coop_pause

        a = coop_pause._cid({"role": "guest", "ip": "10.0.5.20"})  # noqa: SLF001
        b = coop_pause._cid({"role": "guest", "ip": "10.0.5.21"})  # noqa: SLF001
        self.assertNotEqual(a, b)

    def test_explicit_id_still_wins(self):
        from host_tuning import coop_pause

        cid = coop_pause._cid(  # noqa: SLF001
            {"uuid": "friend-a", "role": "guest", "client_name": "Alex"}
        )
        self.assertEqual(cid, "friend-a")


if __name__ == "__main__":
    unittest.main()
