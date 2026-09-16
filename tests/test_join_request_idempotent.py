"""JOINREQ idempotency — retries must not orphan guest JOINSTATUS polls."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class JoinRequestIdempotentTests(unittest.TestCase):
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
            return_value={
                "hostSteamId": "",
                "hostPersona": "Host",
                "hostAvatarUrl": "",
                "wanHost": "",
                "lanHost": "10.0.5.42",
                "zerotierHost": "",
                "maxPlayers": 4,
            },
        )
        ident.start()
        self.addCleanup(ident.stop)
        preauth = mock.patch("host_tuning.join_request._should_auto_joinack", return_value=False)
        preauth.start()
        self.addCleanup(preauth.stop)
        from host_tuning import join_request

        self.jr = join_request

    def test_retry_reuses_pending_reqid(self):
        first = self.jr.create(
            {
                "friendName": "iPad",
                "uuid": "guest-uuid-1",
                "appId": "9",
                "appName": "Test",
            }
        )
        self.assertTrue(first.get("ok"))
        req_id = first.get("reqId")
        self.assertTrue(req_id)

        second = self.jr.create(
            {
                "friendName": "iPad",
                "uuid": "guest-uuid-1",
                "appId": "9",
                "appName": "Test",
            }
        )
        self.assertEqual(second.get("reqId"), req_id)
        pending = self.jr.pending()
        ids = [r.get("reqId") for r in pending.get("requests") or []]
        self.assertEqual(ids.count(req_id), 1)


if __name__ == "__main__":
    unittest.main()
