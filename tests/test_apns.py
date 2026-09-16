"""APNs Auth Key helper — no live Apple calls."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class ApnsHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch("host_tuning.apns.config_dir", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        load = mock.patch(
            "host_tuning.apns.load_config",
            return_value=mock.Mock(
                apns_key_id="",
                apns_team_id="ABG342Z7V2",
                apns_bundle_id="com.moonlight.gamesphere",
                apns_key_path="",
            ),
        )
        load.start()
        self.addCleanup(load.stop)
        pkg = mock.patch("host_tuning.apns._package_dir", return_value=self.tmp.name)
        pkg.start()
        self.addCleanup(pkg.stop)
        inst = mock.patch("host_tuning.apns._install_host_tuning_dir", return_value=self.tmp.name)
        inst.start()
        self.addCleanup(inst.stop)

    def test_status_without_key_is_one_sentence(self):
        from host_tuning import apns

        info = apns.status_public()
        self.assertFalse(info["pushReady"])
        self.assertIn(".p8", info["pushStatus"])
        blob = json_blob(info)
        self.assertNotIn("BEGIN", blob)
        self.assertNotIn("PRIVATE KEY", blob)

    def test_parse_environment_debug_is_sandbox(self):
        from host_tuning import apns

        self.assertEqual(apns.parse_environment({"apnsEnvironment": "development"}), "development")
        self.assertEqual(apns.parse_environment({"apnsSandbox": True}), "development")
        self.assertEqual(apns.parse_environment({}), "development")
        self.assertEqual(apns.parse_environment({"apnsEnvironment": "production"}), "production")
        self.assertEqual(apns.parse_environment({"apnsSandbox": False}), "production")

    def test_normalize_token(self):
        from host_tuning import apns

        hex64 = "ab" * 32
        self.assertEqual(apns.normalize_token(hex64.upper()), hex64)
        self.assertEqual(apns.normalize_token("not-a-token"), "")
        self.assertEqual(apns.normalize_token(""), "")

    def test_payload_has_mutable_content_and_play_url(self):
        from host_tuning import apns

        payload = apns.build_payload(
            title="Wanna play?",
            body="Want to play Celeste with Trevor",
            play_url="gamesphere://play?session=abc&preauth=1",
            cover_url="https://images.igdb.com/celeste.jpg",
            session_id="tok",
            app_name="Celeste",
            host_persona="Trevor",
        )
        self.assertEqual(payload["aps"]["mutable-content"], 1)
        self.assertEqual(payload["aps"]["sound"], "default")
        self.assertEqual(payload["aps"]["alert"]["body"], "Want to play Celeste with Trevor")
        self.assertEqual(payload["playURL"], "gamesphere://play?session=abc&preauth=1")
        self.assertEqual(payload["coverUrl"], "https://images.igdb.com/celeste.jpg")
        self.assertTrue(payload["playURL"].startswith("gamesphere://play"))
        self.assertNotIn("file://", str(payload))

    def test_file_cover_stripped(self):
        from host_tuning import apns

        payload = apns.build_payload(
            title="Wanna play?",
            body="x",
            play_url="gamesphere://play?session=1",
            cover_url="file:///tmp/box.png",
        )
        self.assertNotIn("coverUrl", payload)

    def test_der_to_jose(self):
        from host_tuning import apns

        der = bytes.fromhex("3006020101020102")
        raw = apns._der_ecdsa_to_jose(der)
        self.assertEqual(len(raw), 64)
        self.assertEqual(raw[31], 1)
        self.assertEqual(raw[63], 2)

    def test_key_id_from_apple_filename(self):
        from host_tuning import apns

        self.assertEqual(apns._key_id_from_filename("/tmp/AuthKey_ABCD123456.p8"), "ABCD123456")
        self.assertEqual(apns._key_id_from_filename("/tmp/apns.p8"), "")

    def test_authkey_filename_is_enough_for_ready(self):
        from host_tuning import apns

        path = os.path.join(self.tmp.name, "AuthKey_ABCD123456.p8")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----\n")
        info = apns.key_config()
        self.assertTrue(info["hasKey"])
        self.assertEqual(info["keyId"], "ABCD123456")
        self.assertTrue(info["ready"])
        public = apns.status_public()
        self.assertTrue(public["pushReady"])
        self.assertNotIn("BEGIN PRIVATE", json_blob(public))
        self.assertNotIn("MIIB", json_blob(public))


def json_blob(data) -> str:
    import json

    return json.dumps(data)


if __name__ == "__main__":
    unittest.main()
