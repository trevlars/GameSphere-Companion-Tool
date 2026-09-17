"""PLAYREPLY echo onto COOPSTATE — no live host required."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from host_tuning import play_reply


class PlayReplyTests(unittest.TestCase):
    def setUp(self):
        play_reply.reset()

    def tearDown(self):
        play_reply.reset()

    def test_record_requires_phrase(self):
        result = play_reply.record({"uuid": "abc", "accepted": True})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_phrase")
        self.assertEqual(play_reply.recent(), [])

    def test_record_and_coopstate_shape(self):
        result = play_reply.record(
            {
                "uuid": "friend-a",
                "sessionId": "sess1",
                "phrase": "I'm in",
                "accepted": True,
                "persona": "Alex",
                "avatarUrl": "https://example.com/g.jpg",
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["phrase"], "I'm in")
        self.assertTrue(result["accepted"])
        self.assertEqual(result["persona"], "Alex")
        self.assertEqual(result["avatarUrl"], "https://example.com/g.jpg")
        fields = play_reply.coopstate_fields()
        self.assertEqual(len(fields["coopChat"]), 1)
        self.assertEqual(fields["playReplies"], fields["coopChat"])
        self.assertEqual(fields["playReply"]["phrase"], "I'm in")
        self.assertEqual(fields["lastReply"]["id"], fields["playReply"]["id"])
        self.assertEqual(fields["playReply"]["uuid"], "friend-a")
        self.assertEqual(fields["playReply"]["sessionId"], "sess1")
        self.assertEqual(fields["playReply"]["name"], "Alex")

    def test_decline_phrase(self):
        result = play_reply.record(
            {
                "uuid": "kid",
                "sessionId": "s2",
                "phrase": "Can't right now",
                "accepted": False,
                "persona": "Theo",
            }
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["accepted"])
        last = play_reply.coopstate_fields()["playReply"]
        self.assertEqual(last["phrase"], "Can't right now")
        self.assertFalse(last["accepted"])

    def test_drops_file_avatar_and_caps_phrase(self):
        result = play_reply.record(
            {
                "uuid": "u",
                "phrase": "x" * 200,
                "avatarUrl": "file:///tmp/secret.png",
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["phrase"]), play_reply.PHRASE_MAX)
        self.assertEqual(result["avatarUrl"], "")

    def test_upsert_same_uuid_session_phrase(self):
        first = play_reply.record(
            {"uuid": "a", "sessionId": "s", "phrase": "I'm in", "accepted": True, "persona": "G"}
        )
        second = play_reply.record(
            {"uuid": "a", "sessionId": "s", "phrase": "I'm in", "accepted": True, "persona": "Alex"}
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(play_reply.recent()), 1)
        self.assertEqual(play_reply.recent()[0]["persona"], "Alex")

    def test_two_guests_two_bubbles(self):
        play_reply.record({"uuid": "a", "sessionId": "s", "phrase": "I'm in", "accepted": True})
        play_reply.record(
            {"uuid": "b", "sessionId": "s", "phrase": "You're going down", "accepted": True}
        )
        rows = play_reply.recent()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["phrase"], "You're going down")

    def test_ttl_expires(self):
        with mock.patch("host_tuning.play_reply.time.time", return_value=1_000.0):
            play_reply.record({"uuid": "a", "phrase": "I'm in", "accepted": True})
            self.assertEqual(len(play_reply.recent()), 1)
        with mock.patch("host_tuning.play_reply.time.time", return_value=1_000.0 + play_reply.TTL_SEC + 1):
            self.assertEqual(play_reply.recent(), [])
            fields = play_reply.coopstate_fields()
            self.assertEqual(fields["coopChat"], [])
            self.assertIsNone(fields["playReply"])

    def test_last_n_cap(self):
        for i in range(play_reply.MAX_REPLIES + 5):
            play_reply.record(
                {
                    "uuid": f"u{i}",
                    "sessionId": "s",
                    "phrase": f"I'm in {i}",
                    "accepted": True,
                }
            )
        rows = play_reply.recent()
        self.assertEqual(len(rows), play_reply.MAX_REPLIES)
        self.assertTrue(rows[-1]["phrase"].endswith(str(play_reply.MAX_REPLIES + 4)))

    def test_coopstate_json_keeps_slots_and_wannaplay(self):
        play_reply.record({"uuid": "a", "sessionId": "sess", "phrase": "Bring it", "accepted": True})
        from host_tuning import bridge

        ident = {"hostPersona": "Trevor", "hostSteamId": "76561198012345678", "steamId64": "76561198012345678"}
        with mock.patch("host_tuning.coop_pause.snapshot", return_value={"pauseRecommended": False, "paused": False, "reason": "", "clientCount": 1, "multiplayer": False, "clients": []}), mock.patch(
            "host_tuning.host_identity.cached_snapshot", return_value=ident
        ), mock.patch(
            "host_tuning.host_identity.snapshot", return_value=ident
        ), mock.patch(
            "host_tuning.wan_setup.status",
            return_value={"lanHost": "10.0.5.42", "wanHost": "", "wanReady": False, "status": ""},
        ), mock.patch(
            "host_tuning.voice_bridge.status", return_value={"port": 48020, "running": True}
        ), mock.patch(
            "host_tuning.couch_coop.status",
            return_value={"players": [{"player": 1}], "slot_lock": [0, 1, 2, 3]},
        ), mock.patch(
            "host_tuning.wanna_play.public_session",
            return_value={"sessionId": "sess", "appName": "Hades"},
        ), mock.patch(
            "host_tuning.bridge._push_fields",
            return_value={"pushReady": False, "pushStatus": "no key"},
        ):
            state = bridge._coopstate_json("")
        self.assertTrue(state["ok"])
        self.assertEqual(state["slot_lock"], [0, 1, 2, 3])
        self.assertEqual(state["wannaPlay"]["sessionId"], "sess")
        self.assertEqual(state["coopChat"][0]["phrase"], "Bring it")
        self.assertEqual(state["playReplies"][0]["phrase"], "Bring it")
        self.assertEqual(state["playReply"]["phrase"], "Bring it")
        self.assertFalse(state["wanReady"])
        self.assertEqual(state["hostPersona"], "Trevor")


if __name__ == "__main__":
    unittest.main()
