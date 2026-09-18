"""Concurrency and cache-invalidation fixes in the always-on daemon."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class InviteStateTests(unittest.TestCase):
    """INVITE / JOINPIN / INVITEEND land on separate bridge threads."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from host_tuning import invite

        self.invite = invite
        patcher = mock.patch.object(invite, "config_dir", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_concurrent_replace_keeps_every_guest_uuid(self):
        base = {"token": "t1", "expires": 9e9, "ended": False, "guestUuids": []}
        self.invite._save({"invites": [base]})  # noqa: SLF001

        def add(uuid: str) -> None:
            for _ in range(20):
                with self.invite._lock:  # noqa: SLF001
                    row = self.invite._find("t1")  # noqa: SLF001
                    row.setdefault("guestUuids", []).append(uuid)
                    self.invite._replace(row)  # noqa: SLF001

        threads = [threading.Thread(target=add, args=(f"guest-{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        row = self.invite._find("t1")  # noqa: SLF001
        self.assertEqual(len(row["guestUuids"]), 80)

    def test_end_invite_unpairs_outside_the_lock(self):
        self.invite._save(  # noqa: SLF001
            {"invites": [{"token": "t1", "expires": 9e9, "ended": False, "guestUuids": ["g1"]}]}
        )
        held = []

        def fake_unpair(uuid):
            # If the lock were held here, INVITE would stall behind HTTP calls.
            held.append(self.invite._lock.acquire(blocking=False))  # noqa: SLF001
            if held[-1]:
                self.invite._lock.release()  # noqa: SLF001
            return True

        with mock.patch.object(self.invite, "sunshine_admin") as admin, mock.patch.object(
            self.invite, "_load_trusted_uuids", create=True
        ):
            admin.unpair.side_effect = fake_unpair
            with mock.patch("host_tuning.join_request.trusted_uuids", return_value=[]):
                result = self.invite.end_invite("t1")

        self.assertEqual(result["unpaired"], ["g1"])
        self.assertTrue(all(held), "end_invite held the lock during unpair")
        self.assertTrue(self.invite._find("t1")["ended"])  # noqa: SLF001


class LaunchWatcherTests(unittest.TestCase):
    def test_concurrent_notes_keep_attempt_count_exact(self):
        from host_tuning import launch_watcher as lw

        lw._LAST_RESULT.update({"attempts": 0, "startedAt": 0.0})  # noqa: SLF001

        def bump():
            for _ in range(50):
                lw.note_launch_attempt(game="Celeste", cmd="steam://rungameid/1")

        threads = [threading.Thread(target=bump) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(lw._LAST_RESULT["attempts"], 200)  # noqa: SLF001


class TailscaleCacheTests(unittest.TestCase):
    def test_concurrent_miss_shells_out_once(self):
        from host_tuning import tailscale

        tailscale._cache.update({"at": 0.0, "detected": False, "ip": ""})  # noqa: SLF001
        with mock.patch.object(tailscale, "_tailscale_cli_ip", return_value="100.64.0.5") as cli:
            threads = [
                threading.Thread(target=lambda: tailscale.detect_tailscale()) for _ in range(8)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(cli.call_count, 1)
        self.assertEqual(tailscale.detect_tailscale(), (True, "100.64.0.5"))


class IgdCacheTests(unittest.TestCase):
    """A replaced router must not leave us retrying a dead control URL."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from host_tuning import nat_map

        self.nat_map = nat_map
        self.cache = os.path.join(self.tmp.name, "igd.json")
        patcher = mock.patch.object(nat_map, "_igd_cache_path", return_value=self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        nat_map._IGD_CACHE.update({"at": 0.0, "svc": None})  # noqa: SLF001
        self.addCleanup(lambda: nat_map._IGD_CACHE.update({"at": 0.0, "svc": None}))  # noqa: SLF001

    def test_dead_cached_gateway_is_forgotten_not_returned(self):
        dead = {"controlURL": "http://10.0.0.1:5000/ctl", "serviceType": "x", "location": ""}
        self.nat_map._save_igd_cache(dead)  # noqa: SLF001
        with mock.patch.object(self.nat_map, "_soap_external_ip", return_value=""), mock.patch.object(
            self.nat_map, "default_gateway", return_value=""
        ), mock.patch.object(self.nat_map, "_igd_service_from_location", return_value=None):
            found = self.nat_map._discover_igd()  # noqa: SLF001
        self.assertIsNone(found)
        self.assertFalse(os.path.exists(self.cache))

    def test_live_cached_gateway_is_reused_without_ssdp(self):
        live = {"controlURL": "http://10.0.0.1:5000/ctl", "serviceType": "x", "location": ""}
        self.nat_map._save_igd_cache(live)  # noqa: SLF001
        with mock.patch.object(self.nat_map, "_soap_external_ip", return_value="203.0.113.7"):
            found = self.nat_map._discover_igd()  # noqa: SLF001
        self.assertEqual(found["controlURL"], live["controlURL"])


class SystemdUnitTests(unittest.TestCase):
    def test_custom_install_dir_is_used_as_working_directory(self):
        from host_tuning import host_daemon as hd

        with mock.patch.dict(os.environ, {"GAMESPHERE_IMPORT_DIR": "/opt/gamesphere"}):
            self.assertIn("WorkingDirectory=-/opt/gamesphere", hd.linux_unit_body())

    def test_default_install_keeps_portable_home_form(self):
        from host_tuning import host_daemon as hd

        env = {k: v for k, v in os.environ.items() if k != "GAMESPHERE_IMPORT_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIn(
                "WorkingDirectory=-%h/.local/share/gamesphere-import-tool", hd.linux_unit_body()
            )


if __name__ == "__main__":
    unittest.main()
