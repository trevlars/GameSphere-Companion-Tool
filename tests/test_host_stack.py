"""Installer-shipped couch-coop helpers — no live host required."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class HostStackArtifactTests(unittest.TestCase):
    def test_no_global_clone_hiding_udev_rule(self):
        # Proton games read only Steam Input clones; a global MODE=000 rule breaks them.
        path = os.path.join(ROOT, "scripts", "udev", "99-gamesphere-hide-steam-clones.rules")
        self.assertFalse(os.path.exists(path))
        with open(os.path.join(ROOT, "scripts", "linux-autoupdate-lib.sh"), encoding="utf-8") as fh:
            lib = fh.read()
        self.assertNotIn("sudo -n cp", lib)
        self.assertIn(".disabled", lib)

    def test_retire_udev_rule_moves_active_copy_aside(self):
        from host_tuning import host_stack

        calls = []
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ, {"XDG_CONFIG_HOME": tmp}
        ), mock.patch.object(host_stack.os.path, "isfile", return_value=True), mock.patch.object(
            host_stack, "_run", side_effect=lambda cmd, **_: calls.append(cmd) or True
        ), mock.patch.object(host_stack.os, "geteuid", return_value=1000):
            result = host_stack.retire_udev_rules()
        self.assertTrue(result["retired"])
        self.assertEqual(
            calls[0],
            ["sudo", "-n", "mv", "-f", host_stack.UDEV_DEST, host_stack.UDEV_DEST + ".disabled"],
        )

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
