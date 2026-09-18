"""Invite-link JOINREQ auto-accept (fresh token within TTL)."""

from __future__ import annotations

import tempfile
import time
import unittest
from unittest import mock

from host_tuning import invite as guest_invite
from host_tuning import join_request


class InviteJoinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.invite_cfg = mock.patch(
            "host_tuning.invite.config_dir", return_value=self.tmp.name
        )
        self.join_cfg = mock.patch(
            "host_tuning.join_request.config_dir", return_value=self.tmp.name
        )
        self.invite_cfg.start()
        self.join_cfg.start()
        self.addCleanup(self.invite_cfg.stop)
        self.addCleanup(self.join_cfg.stop)
        self.addCleanup(self.tmp.cleanup)
        ident = mock.patch(
            "host_tuning.join_request._identity_fields",
            return_value={
                "hostSteamId": "",
                "hostPersona": "Trevor",
                "hostAvatarUrl": "",
                "wanHost": "203.0.113.9",
                "lanHost": "10.0.5.42",
                "zerotierHost": "",
                "maxPlayers": 4,
            },
        )
        ident.start()
        self.addCleanup(ident.stop)
        from host_tuning import couch_coop

        couch_coop.reset_slots()
        self.addCleanup(couch_coop.reset_slots)
        joined = mock.patch(
            "host_tuning.couch_coop.on_join_accepted", return_value={"ok": True}
        )
        joined.start()
        self.addCleanup(joined.stop)
        creds = mock.patch("host_tuning.sunshine_admin.has_credentials", return_value=True)
        creds.start()
        self.addCleanup(creds.stop)
        clients = mock.patch(
            "host_tuning.sunshine_admin.list_clients", return_value=[]
        )
        clients.start()
        self.addCleanup(clients.stop)
        wan = mock.patch(
            "host_tuning.wan_setup.hosts_for_join",
            return_value={"wanHost": "203.0.113.9", "wanReady": False, "zerotierHost": ""},
        )
        wan.start()
        self.addCleanup(wan.stop)
        ident_snap = mock.patch("host_tuning.host_identity.snapshot", return_value={})
        ident_snap.start()
        self.addCleanup(ident_snap.stop)
        lan = mock.patch("host_tuning.invite._local_lan_ip", return_value="10.0.5.42")
        lan.start()
        self.addCleanup(lan.stop)

    def test_active_invite_token_auto_joinacks(self):
        minted = guest_invite.mint({"appId": "9", "appName": "Celeste", "hostId": "host1"})
        token = minted["token"]
        self.assertTrue(guest_invite.is_active_invite_token(token))

        auto = join_request.create(
            {
                "friendName": "Guest iPad",
                "uuid": "guest-uuid",
                "sessionId": token,
                "appId": "9",
                "appName": "Celeste",
            }
        )
        self.assertTrue(auto.get("ok"), auto)
        self.assertTrue(auto.get("preauth"))
        self.assertEqual(auto.get("status"), "accepted")
        # First guest of the session takes the first free seat.
        self.assertEqual(auto.get("playerSlot"), 1)
        pending = join_request.pending()
        ids = [r.get("reqId") for r in pending.get("requests") or []]
        self.assertNotIn(auto["reqId"], ids)

    def test_expired_invite_token_stays_pending(self):
        minted = guest_invite.mint({"appId": "9", "appName": "Celeste"})
        token = minted["token"]
        data = guest_invite._load()
        data["invites"][0]["expires"] = time.time() - 1
        guest_invite._save(data)
        self.assertFalse(guest_invite.is_active_invite_token(token))

        pending = join_request.create(
            {
                "friendName": "Guest",
                "uuid": "guest-uuid",
                "sessionId": token,
                "appId": "9",
            }
        )
        self.assertTrue(pending.get("ok"))
        self.assertFalse(pending.get("preauth"))
        self.assertNotEqual(pending.get("status"), "accepted")
        open_reqs = join_request.pending()
        self.assertIn(pending["reqId"], [r.get("reqId") for r in open_reqs.get("requests") or []])

    def test_no_token_requires_host_accept(self):
        pending = join_request.create(
            {
                "friendName": "Buddy tap",
                "uuid": "some-friend",
                "appId": "9",
                "appName": "Celeste",
            }
        )
        self.assertTrue(pending.get("ok"))
        self.assertFalse(pending.get("preauth"))
        self.assertNotEqual(pending.get("status"), "accepted")


if __name__ == "__main__":
    unittest.main()
