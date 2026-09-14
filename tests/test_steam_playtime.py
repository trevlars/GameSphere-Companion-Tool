"""Local Steam playtime parsing + apps.json stamp."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "steam_playtime",
    os.path.join(ROOT, "host_tuning", "steam_playtime.py"),
)
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)


LOCALCONFIG = """
"UserLocalConfigStore"
{
	"Software"
	{
		"Valve"
		{
			"Steam"
			{
				"apps"
				{
					"1145360"
					{
						"LastPlayed"		"1710000000"
						"Playtime"		"840"
					}
					"3344556677"
					{
						"LastPlayed"		"1711000000"
						"Playtime"		"45"
					}
				}
			}
		}
	}
}
"""


class SteamPlaytimeTests(unittest.TestCase):
    def test_alias_shortcut_ids(self):
        short = "3344556677"
        aliases = set(sp._alias_ids(short))
        self.assertIn(short, aliases)
        rungame = sp._shortcut_rungameid(int(short))
        self.assertIn(rungame, aliases)
        self.assertIn(short, set(sp._alias_ids(rungame)))

    def test_localconfig_minutes(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam_root = tmp
            user = os.path.join(steam_root, "userdata", "123456", "config")
            os.makedirs(user)
            path = os.path.join(user, "localconfig.vdf")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(LOCALCONFIG)
            records = sp.load_localconfig_playtimes(steam_root)
            hades = sp.lookup_record(records, "1145360", "Hades")
            self.assertIsNotNone(hades)
            self.assertEqual(hades["minutes"], 840)
            self.assertEqual(hades["lastPlayed"], 1710000000)
            emu = sp.lookup_record(records, "3344556677", "")
            self.assertEqual(emu["minutes"], 45)
            rungame = sp._shortcut_rungameid(3344556677)
            self.assertEqual(sp.lookup_record(records, rungame, "")["minutes"], 45)

    def test_stamp_prefers_local_hours(self):
        records = {
            "1145360": {"minutes": 840, "lastPlayed": 1710000000, "name": "Hades"},
        }
        apps = [
            {
                "name": "Hades",
                "cmd": "",
                "detached": ["setsid steam steam://rungameid/1145360"],
            },
            {"name": "Desktop", "cmd": "desktop"},
        ]
        changed = sp.stamp_apps(apps, records)
        self.assertGreaterEqual(changed, 1)
        self.assertEqual(apps[0][sp.PLAYTIME_MINUTES_KEY], 840)
        self.assertEqual(apps[0][sp.LAST_PLAYED_KEY], 1710000000)
        self.assertNotIn(sp.PLAYTIME_MINUTES_KEY, apps[1])

    def test_name_match_for_nonsteam(self):
        records = {
            "999": {"minutes": 12, "lastPlayed": 50, "name": "Animal Crossing: New Horizons"},
        }
        row = sp.lookup_record(records, None, "Animal Crossing: New Horizons (Switch)")
        self.assertEqual(row["minutes"], 12)
        row = sp.lookup_record(records, None, "Animal Crossing: New Horizons")
        self.assertEqual(row["minutes"], 12)


if __name__ == "__main__":
    unittest.main()
