"""JOINREQ during an active stream requires session or preauth."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class JoinRequestNoSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = mock.patch("host_tuning.join_request.config_dir", return_value=self.tmp.name)
        cfg.start()
        self.addCleanup(cfg.stop)
        lan = mock.patch("host_tuning.invite._local_lan_ip", return_value="10.0.5.42")
        lan.start()
        self.addCleanup(lan.stop)
        ident = mock.patch(
            "host_tuning.join_request._identity_fields",
            return_value={"lanHost": "10.0.5.42", "maxPlayers": 4},
        )
        ident.start()
        self.addCleanup(ident.stop)
        preauth = mock.patch("host_tuning.join_request._should_auto_joinack", return_value=False)
        preauth.start()
        self.addCleanup(preauth.stop)
        stream = mock.patch("host_tuning.couch_coop.stream_active", return_value=True)
        stream.start()
        self.addCleanup(stream.stop)
        from host_tuning import join_request

        self.jr = join_request

    def test_rejects_without_session_while_streaming(self):
        out = self.jr.create({"friendName": "iPad", "uuid": "guest-1", "appId": "9"})
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "no_session")


if __name__ == "__main__":
    unittest.main()
