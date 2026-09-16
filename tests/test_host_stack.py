"""Installer-shipped couch-coop helpers — no live host required."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class HostStackArtifactTests(unittest.TestCase):
    def test_udev_hides_steam_clones_only(self):
        path = os.path.join(ROOT, "scripts", "udev", "99-gamesphere-hide-steam-clones.rules")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("28de", text)
        self.assertIn("11ff", text)
        self.assertIn('MODE="000"', text)
        self.assertNotIn("47990", text)
        blob = text.lower()
        self.assertNotIn("dualsense", blob)
        self.assertNotIn("gemma", blob)

    def test_hide_helper_and_firewall_scripts_exist(self):
        hide = os.path.join(ROOT, "scripts", "gamesphere-hide-steam-clones.sh")
        fw = os.path.join(ROOT, "scripts", "gamesphere-host-firewall.sh")
        self.assertTrue(os.path.isfile(hide))
        self.assertTrue(os.path.isfile(fw))
        with open(hide, encoding="utf-8") as fh:
            hide_txt = fh.read()
        with open(fw, encoding="utf-8") as fh:
            fw_txt = fh.read()
        self.assertIn("28de", hide_txt)
        self.assertIn("47998", fw_txt)
        self.assertIn("48020", fw_txt)
        self.assertIn("47990", fw_txt)
        self.assertIn("never", fw_txt.lower())
        joined = (hide_txt + fw_txt).lower()
        self.assertNotIn("dualsense", joined)
        self.assertNotIn("gemma", joined)
        self.assertNotIn("bazzite-hide", joined)

    def test_port_lists_never_include_web_ui(self):
        from host_tuning import host_stack

        self.assertNotIn(47990, host_stack.TCP_PORTS)
        self.assertNotIn(47990, host_stack.UDP_PORTS)
        self.assertIn(47990, host_stack.NEVER_PORTS)
        self.assertIn(47998, host_stack.TCP_PORTS)
        self.assertIn(48020, host_stack.UDP_PORTS)


if __name__ == "__main__":
    unittest.main()
