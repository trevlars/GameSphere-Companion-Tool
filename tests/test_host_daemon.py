"""Host daemon autostart artifacts — no live Sunshine required."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "host_daemon",
    os.path.join(ROOT, "host_tuning", "host_daemon.py"),
)
hd = importlib.util.module_from_spec(_spec)
sys.modules["host_daemon"] = hd
_spec.loader.exec_module(hd)


class HostDaemonArtifactTests(unittest.TestCase):
    def test_linux_unit_restarts_always_and_never_binds_sunshine(self):
        body = hd.linux_unit_body()
        self.assertIn("Restart=always", body)
        self.assertIn("KillMode=process", body)
        self.assertIn("gamesphere-host-bridge", body)
        self.assertNotIn("BindsTo=sunshine", body)
        self.assertNotIn("PartOf=sunshine", body)
        self.assertNotIn("systemctl restart sunshine", body.lower())
        unit_path = os.path.join(ROOT, "scripts", "systemd", "gamesphere-host-bridge.service")
        with open(unit_path, encoding="utf-8") as fh:
            on_disk = fh.read()
        self.assertIn("Restart=always", on_disk)
        self.assertIn("ExecStart=%h/.local/bin/gamesphere-host-bridge", on_disk)
        self.assertNotIn("BindsTo=", on_disk)

    def test_wrapper_script_never_restarts_sunshine(self):
        path = os.path.join(ROOT, "scripts", "gamesphere-host-bridge.sh")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("--host-bridge", text)
        self.assertNotIn("restart sunshine", text.lower())
        self.assertNotIn("systemctl", text)

    def test_windows_task_xml_hidden_restart(self):
        xml = hd.windows_task_xml(r"C:\GamesphereImportTool.exe", "--host-daemon")
        self.assertIn("<Hidden>true</Hidden>", xml)
        self.assertIn("<RestartOnFailure>", xml)
        self.assertIn("<Interval>PT2M</Interval>", xml)
        self.assertIn("LeastPrivilege", xml)
        self.assertIn("--host-daemon", xml)
        self.assertNotIn("sunshine.exe", xml.lower())
        self.assertNotIn("systemctl", xml.lower())

    def test_macos_plist_keepalive(self):
        plist = hd.macos_plist_body(
            ["/usr/bin/python3", "/tmp/main.py", "--host-bridge"],
            "/tmp/Gamesphere-Import-Tool",
        )
        self.assertIn("<key>KeepAlive</key>", plist)
        self.assertIn("<true/>", plist)
        self.assertIn("--host-bridge", plist)
        self.assertIn(hd.LAUNCH_LABEL, plist)

    def test_argv_touches_sunshine(self):
        self.assertTrue(
            hd.argv_touches_sunshine(["systemctl", "--user", "restart", "sunshine"])
        )
        self.assertTrue(
            hd.argv_touches_sunshine(["taskkill", "/IM", "sunshine.exe", "/F"])
        )
        self.assertFalse(
            hd.argv_touches_sunshine(
                ["systemctl", "--user", "restart", "gamesphere-host-bridge.service"]
            )
        )
        self.assertFalse(hd.argv_touches_sunshine(hd.daemon_command()))

    def test_host_bridge_opt_out(self):
        old = os.environ.get("GAMESPHERE_ENABLE_HOST_BRIDGE")
        os.environ["GAMESPHERE_ENABLE_HOST_BRIDGE"] = "0"
        try:
            self.assertFalse(hd.host_bridge_enabled())
            result = hd.install_autostart()
            self.assertTrue(result.get("skipped"))
        finally:
            if old is None:
                os.environ.pop("GAMESPHERE_ENABLE_HOST_BRIDGE", None)
            else:
                os.environ["GAMESPHERE_ENABLE_HOST_BRIDGE"] = old

    def test_daemon_flags(self):
        for flag in (
            "--host-bridge",
            "--host-daemon",
            "--host-daemon-install",
            "--host-daemon-uninstall",
            "--host-daemon-status",
        ):
            self.assertIn(flag, hd.DAEMON_FLAGS)


if __name__ == "__main__":
    unittest.main()
