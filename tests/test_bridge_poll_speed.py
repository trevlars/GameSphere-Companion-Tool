"""COOPSTATE/HOSTINFO poll handlers must stay sub-second (no Tailscale shell per poll)."""

from __future__ import annotations

import tempfile
import time
import unittest
from unittest import mock

from host_tuning import bridge, wan_setup


class BridgePollSpeedTests(unittest.TestCase):
    def test_status_fast_skips_tailscale(self):
        slow = mock.Mock(return_value="100.64.1.1")
        with mock.patch("host_tuning.wan_setup._tailscale_ip", slow):
            t = time.time()
            wan_setup.status(fast=True)
            self.assertLess(time.time() - t, 0.05)
            slow.assert_not_called()

    def test_coopstate_json_is_fast(self):
        with mock.patch("host_tuning.wan_setup._tailscale_ip", mock.Mock(return_value="")):
            t = time.time()
            out = bridge._coopstate_json("")
            elapsed = time.time() - t
        self.assertTrue(out.get("ok"))
        self.assertLess(elapsed, 0.25, f"COOPSTATE took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
