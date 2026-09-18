"""Session-scoped wanna-play pre-auth (no live host required)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class WannaPlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch("host_tuning.wanna_play.config_dir", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        from host_tuning import wanna_play

        self.wp = wanna_play
        trusted = mock.patch("host_tuning.join_request.trusted_uuids", return_value=["friend-a", "friend-b"])
        trusted.start()
        self.addCleanup(trusted.stop)
        mark = mock.patch("host_tuning.join_request.mark_trusted", return_value={"ok": True})
        mark.start()
        self.addCleanup(mark.stop)
        lan = mock.patch("host_tuning.invite._local_lan_ip", return_value="10.0.5.42")
        lan.start()
        self.addCleanup(lan.stop)
        wan = mock.patch("host_tuning.invite._public_ip", return_value="203.0.113.9")
        wan.start()
        self.addCleanup(wan.stop)
        mapped = mock.patch(
            "host_tuning.wan_setup.hosts_for_join",
            return_value={
                "ok": True,
                "wanReady": True,
                "wanHost": "203.0.113.9",
                "zerotierHost": "",
                "status": "Remote join is on — game ports mapped via UPnP for this session only.",
            },
        )
        mapped.start()
        self.addCleanup(mapped.stop)
        zt = mock.patch(
            "host_tuning.zerotier.status",
            return_value={"zerotierHost": "", "zerotierStatus": ""},
        )
        zt.start()
        self.addCleanup(zt.stop)
        push = mock.patch(
            "host_tuning.apns.status_public",
            return_value={
                "pushReady": False,
                "pushStatus": (
                    "Lock-screen Wanna play needs an APNs Auth Key (.p8) on this PC — "
                    "friends still get the ping if GameSphere is open."
                ),
            },
        )
        push.start()
        self.addCleanup(push.stop)
        notify = mock.patch("host_tuning.apns.notify_devices")
        self.notify = notify.start()
        self.addCleanup(notify.stop)

    def test_start_preauths_trusted_only(self):
        result = self.wp.start({"appId": "9", "appName": "Celeste", "hostId": "HOST", "hostPersona": "Trevor"})
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["preauthUuids"]), {"friend-a", "friend-b"})
        self.assertIn("lan=10.0.5.42", result["playURL"])
        self.assertIn("wan=203.0.113.9", result["playURL"])
        self.assertIn("preauth=1", result["playURL"])
        self.assertTrue(result["playURL"].startswith("gamesphere://play?"))
        self.assertIn("Celeste", result["body"])
        self.assertIn("Trevor", result["body"])
        self.assertFalse(result["pushReady"])
        self.assertIn(".p8", result["pushStatus"])
        self.assertTrue(self.wp.is_preauthorized("friend-a", result["sessionId"]))
        self.assertTrue(self.wp.is_preauthorized("friend-a", "stale-session"))
        self.assertTrue(self.wp.is_preauthorized("friend-a", ""))
        self.assertFalse(self.wp.is_preauthorized("stranger", result["sessionId"]))

    def test_pending_and_claim(self):
        started = self.wp.start({"appId": "9", "appName": "Hades", "hostPersona": "P1"})
        pending = self.wp.pending_for("friend-a")
        self.assertEqual(len(pending["invites"]), 1)
        self.assertTrue(pending["invites"][0]["preauth"])
        self.assertEqual(self.wp.pending_for("stranger")["invites"], [])
        claimed = self.wp.claim({"uuid": "friend-a", "sessionId": started["sessionId"]})
        self.assertTrue(claimed["ok"])
        self.assertTrue(claimed["preauth"])
        leftover = self.wp.pending_for("friend-a")
        self.assertEqual(leftover["invites"], [])

    def test_end_session_drops_preauth(self):
        started = self.wp.start({"appId": "1", "appName": "Game"})
        self.assertTrue(self.wp.is_preauthorized("friend-a", started["sessionId"]))
        self.wp.end_session()
        self.assertFalse(self.wp.is_preauthorized("friend-a", started["sessionId"]))

    def test_joinreq_auto_ack_only_for_pinged_uuid(self):
        started = self.wp.start({"appId": "9", "appName": "Celeste"})
        join_cfg = mock.patch("host_tuning.join_request.config_dir", return_value=self.tmp.name)
        join_cfg.start()
        self.addCleanup(join_cfg.stop)
        ident = mock.patch(
            "host_tuning.join_request._identity_fields",
            return_value={
                "hostSteamId": "",
                "hostPersona": "Trevor",
                "hostAvatarUrl": "",
                "wanHost": "203.0.113.9",
                "lanHost": "10.0.5.42",
                "maxPlayers": 4,
            },
        )
        ident.start()
        self.addCleanup(ident.stop)
        from host_tuning import couch_coop

        couch_coop.reset_slots()
        self.addCleanup(couch_coop.reset_slots)
        joined = mock.patch("host_tuning.couch_coop.on_join_accepted", return_value={"ok": True})
        joined.start()
        self.addCleanup(joined.stop)
        from host_tuning import join_request

        auto = join_request.create(
            {
                "friendName": "Alex",
                "uuid": "friend-a",
                "sessionId": started["sessionId"],
                "appId": "9",
                "appName": "Celeste",
            }
        )
        self.assertTrue(auto.get("ok"))
        self.assertTrue(auto.get("preauth"))
        self.assertEqual(auto.get("status"), "accepted")
        self.assertEqual(auto.get("playerSlot"), 1)

        stale = join_request.create(
            {
                "friendName": "Alex",
                "uuid": "friend-a",
                "sessionId": "stale-from-previous-send-invite",
                "appId": "9",
                "appName": "Celeste",
            }
        )
        self.assertTrue(stale.get("ok"), stale)
        self.assertTrue(stale.get("preauth"))
        self.assertEqual(stale.get("status"), "accepted")

        empty_sess = join_request.create(
            {
                "friendName": "Alex",
                "uuid": "friend-a",
                "appId": "9",
            }
        )
        self.assertTrue(empty_sess.get("ok"))
        self.assertTrue(empty_sess.get("preauth"))
        self.assertEqual(empty_sess.get("status"), "accepted")

        again = join_request.ack({"reqId": auto["reqId"], "accept": True})
        self.assertTrue(again.get("ok"), again)
        self.assertEqual(again.get("status"), "accepted")
        self.assertTrue(again.get("accept"))

        stranger = join_request.create(
            {
                "friendName": "Stranger",
                "uuid": "not-pinged",
                "sessionId": started["sessionId"],
            }
        )
        self.assertTrue(stranger.get("ok"))
        self.assertFalse(stranger.get("preauth"))
        self.assertNotEqual(stranger.get("status"), "accepted")
        pending = join_request.pending()
        ids = [r.get("reqId") for r in pending.get("requests") or []]
        self.assertIn(stranger["reqId"], ids)
        self.assertNotIn(auto["reqId"], ids)

    def test_playreg_stores_apns_token_and_sandbox(self):
        registered = self.wp.register_device(
            {
                "uuid": "friend-a",
                "name": "Alex iPad",
                "apnsToken": "AB" * 32,
                "apnsEnvironment": "development",
            }
        )
        self.assertTrue(registered["ok"])
        self.assertTrue(registered["apns"])
        started = self.wp.start(
            {
                "appId": "9",
                "appName": "Celeste",
                "hostPersona": "Trevor",
                "coverUrl": "https://images.igdb.com/celeste.jpg",
            }
        )
        self.assertTrue(started["ok"])
        pending = self.wp.pending_for("friend-a")
        self.assertEqual(len(pending["invites"]), 1)
        self.assertEqual(pending["invites"][0]["coverUrl"], "https://images.igdb.com/celeste.jpg")
        self.notify.assert_called()
        kwargs = self.notify.call_args.kwargs
        self.assertTrue(kwargs["play_url"].startswith("gamesphere://play"))
        self.assertEqual(kwargs["cover_url"], "https://images.igdb.com/celeste.jpg")
        self.assertIn("Celeste", kwargs["body"])
        devices = self.notify.call_args.args[0]
        match = [d for d in devices if d.get("uuid") == "friend-a"][0]
        self.assertEqual(match["apnsToken"], "ab" * 32)
        self.assertEqual(match["apnsEnvironment"], "development")

    def test_start_without_key_poll_still_works(self):
        started = self.wp.start({"appId": "9", "appName": "Hades", "hostPersona": "P1"})
        self.assertTrue(started["ok"])
        self.assertIn(".p8", started["pushStatus"])
        self.assertIn(".p8", started["wanStatus"])
        pending = self.wp.pending_for("friend-a")
        self.assertEqual(len(pending["invites"]), 1)
        self.assertTrue(pending["invites"][0]["playURL"].startswith("gamesphere://play"))


if __name__ == "__main__":
    unittest.main()
