"""A Steam API outage must never prune an installed library."""

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

LIBRARY_VDF = """
"libraryfolders"
{
    "0"
    {
        "path"      "%(root)s"
        "apps"
        {
            "400"       "1234"
            "620"       "5678"
        }
    }
}
"""

MANIFEST = """
"AppState"
{
    "appid"     "%(appid)s"
    "name"      "%(name)s"
}
"""


def _steam_tree(tmp: str, apps: dict) -> str:
    """Build steamapps/ with libraryfolders.vdf + appmanifest files."""
    steamapps = os.path.join(tmp, "steamapps")
    os.makedirs(steamapps, exist_ok=True)
    vdf_path = os.path.join(steamapps, "libraryfolders.vdf")
    with open(vdf_path, "w", encoding="utf-8") as fh:
        fh.write(LIBRARY_VDF % {"root": tmp.replace("\\", "\\\\")})
    for appid, name in apps.items():
        with open(os.path.join(steamapps, f"appmanifest_{appid}.acf"), "w", encoding="utf-8") as fh:
            fh.write(MANIFEST % {"appid": appid, "name": name})
    return vdf_path


class LocalNameResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vdf = _steam_tree(self.tmp.name, {"400": "Portal", "620": "Portal 2"})

    def test_names_resolve_offline_without_calling_api(self):
        with mock.patch.object(main, "get_game_name", side_effect=AssertionError("API used")) as api:
            games = main.load_installed_games(self.vdf)
        api.assert_not_called()
        self.assertEqual(games, {"400": "Portal", "620": "Portal 2"})

    def test_api_used_only_for_apps_without_a_manifest_name(self):
        os.remove(os.path.join(self.tmp.name, "steamapps", "appmanifest_620.acf"))
        with mock.patch.object(main, "get_game_name", return_value="Portal 2") as api:
            games = main.load_installed_games(self.vdf)
        api.assert_called_once_with("620")
        self.assertEqual(games["400"], "Portal")

    def test_installed_ids_do_not_depend_on_the_api(self):
        with mock.patch.object(main, "get_game_name", return_value=None):
            ids = main.installed_steam_app_ids(self.vdf)
        self.assertEqual(ids, {"400", "620"})


class PruneGuardTests(unittest.TestCase):
    """process_existing_apps must keep installed-but-unnamed Steam tiles."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.grid = os.path.join(self.tmp.name, "400.png")
        with open(self.grid, "wb") as fh:
            fh.write(b"cover")
        self.config = {
            "apps": [
                {
                    "name": "Portal",
                    "cmd": "steam://rungameid/400",
                    "image-path": self.grid,
                    "_gamesphere_store": "Steam",
                }
            ]
        }

    def test_api_outage_keeps_app_and_artwork(self):
        pending = []
        updated, removed_steam, _, _, existing, _, _, _, _ = main.process_existing_apps(
            self.config,
            {},  # no names resolved — simulates a total Steam API outage
            installed_app_ids={"400"},
            pending_grid_deletions=pending,
        )
        self.assertEqual(removed_steam, [])
        self.assertEqual(len(updated), 1)
        self.assertIn("400", existing)
        self.assertEqual(pending, [])
        self.assertTrue(os.path.exists(self.grid))

    def test_genuinely_uninstalled_app_is_pruned(self):
        pending = []
        updated, removed_steam, _, _, _, _, _, _, _ = main.process_existing_apps(
            self.config,
            {},
            installed_app_ids=set(),  # Steam no longer lists it
            pending_grid_deletions=pending,
        )
        self.assertEqual(len(removed_steam), 1)
        self.assertEqual(updated, [])
        self.assertEqual(pending, [self.grid])
        # Deferred: artwork survives until the save succeeds.
        self.assertTrue(os.path.exists(self.grid))
        main._remove_pending_grids(pending)
        self.assertFalse(os.path.exists(self.grid))

    def test_manual_entries_are_always_preserved(self):
        config = {"apps": [{"name": "Desktop", "cmd": ""}, {"name": "Steam Big Picture", "cmd": "steam"}]}
        updated, removed_steam, _, _, _, _, _, _, _ = main.process_existing_apps(
            config, {}, installed_app_ids=set()
        )
        self.assertEqual(removed_steam, [])
        self.assertEqual(len(updated), 2)


class LibraryVdfEncodingTests(unittest.TestCase):
    def test_non_utf8_vdf_still_parses(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        steamapps = os.path.join(tmp.name, "steamapps")
        os.makedirs(steamapps)
        path = os.path.join(steamapps, "libraryfolders.vdf")
        body = LIBRARY_VDF % {"root": tmp.name.replace("\\", "\\\\")}
        with open(path, "wb") as fh:
            fh.write(body.encode("latin-1").replace(b"Portal", b"Portal\xe9"))
        self.assertEqual(main.installed_steam_app_ids(path), {"400", "620"})


if __name__ == "__main__":
    unittest.main()
