"""Controller policy tests for GameSphere Companion Tool."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ControllerPolicyTests(unittest.TestCase):
    def test_classify_peers_gamesphere_vs_steamlink(self):
        from host_tuning.controller_policy import classify_peers
        from host_tuning.config import HostTuningConfig

        cfg = HostTuningConfig(controller_steamlink_ips="10.0.4.33")
        self.assertEqual(classify_peers(cfg, ["10.0.5.50"]), "other")
        self.assertEqual(classify_peers(cfg, ["10.0.4.33"]), "steamlink")
        self.assertEqual(classify_peers(cfg, ["10.0.4.33", "10.0.5.50"]), "other")

    def test_resolve_context_prefers_steamlink_ip(self):
        from host_tuning.controller_policy import resolve_context
        from host_tuning.config import HostTuningConfig

        cfg = HostTuningConfig(controller_steamlink_ips="10.0.4.33")
        with mock.patch("host_tuning.controller_policy.sunshine_peer_ips", return_value=["10.0.4.33"]):
            self.assertEqual(resolve_context(cfg, force="auto"), "steamlink-x360")

    def test_resolve_context_gamesphere_ds5(self):
        from host_tuning.controller_policy import resolve_context
        from host_tuning.config import HostTuningConfig

        cfg = HostTuningConfig()
        with mock.patch("host_tuning.controller_policy.sunshine_peer_ips", return_value=["10.0.5.99"]):
            self.assertEqual(resolve_context(cfg, force="auto"), "gamesphere-ds5")

    def test_resolve_context_user_prefers_x360_for_gamesphere(self):
        from host_tuning.controller_policy import resolve_context
        from host_tuning.config import HostTuningConfig

        cfg = HostTuningConfig(controller_user_gamepad="x360")
        with mock.patch("host_tuning.controller_policy.sunshine_peer_ips", return_value=["10.0.5.99"]):
            self.assertEqual(resolve_context(cfg, force="auto"), "gamesphere-x360")

    def test_patch_sunshine_conf(self):
        from host_tuning.controller_policy import apply_sunshine_profile

        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "sunshine.conf")
            with open(conf, "w", encoding="utf-8") as f:
                f.write("gamepad = x360\nmotion_as_ds4 = disabled\n")
            with mock.patch("host_tuning.controller_policy._sunshine_conf", return_value=__import__("pathlib").Path(conf)):
                apply_sunshine_profile("gamesphere-ds5")
            body = open(conf, encoding="utf-8").read()
            self.assertIn("gamepad = ds5", body)
            self.assertIn("motion_as_ds4 = enabled", body)

    def test_get_policy_json_shape(self):
        from host_tuning.controller_policy import get_policy_json

        data = get_policy_json()
        self.assertIn("effectiveContext", data)
        self.assertIn("gamepad", data)
        self.assertIn("contexts", data)


if __name__ == "__main__":
    unittest.main()
