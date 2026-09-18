"""Guest seats: unique per guest, reusable after they leave."""

from __future__ import annotations

import os
import sys
import threading
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from host_tuning import couch_coop as cc


class SlotReservationTests(unittest.TestCase):
    def setUp(self):
        cc.reset_slots()
        self.addCleanup(cc.reset_slots)

    def test_guests_joining_before_pads_get_distinct_seats(self):
        # Regression: every guest used to land in slot 1 because occupancy was
        # read from Sunshine pad locks, which are empty until Moonlight connects.
        first = cc.reserve_slot(uuid="friend-a", name="Alex")
        second = cc.reserve_slot(uuid="friend-b", name="Bo")
        third = cc.reserve_slot(uuid="friend-c", name="Cy")
        self.assertEqual([first, second, third], [1, 2, 3])

    def test_same_guest_rejoining_keeps_their_seat(self):
        first = cc.reserve_slot(uuid="friend-a", name="Alex")
        again = cc.reserve_slot(uuid="friend-a", name="Alex")
        self.assertEqual(first, again)

    def test_full_house_returns_minus_one(self):
        for tag in ("a", "b", "c"):
            cc.reserve_slot(uuid=f"friend-{tag}")
        self.assertEqual(cc.reserve_slot(uuid="friend-d"), -1)
        self.assertEqual(cc.next_empty_slot(), -1)

    def test_host_slot_is_never_handed_to_a_guest(self):
        for tag in ("a", "b", "c", "d"):
            self.assertNotEqual(cc.reserve_slot(uuid=f"friend-{tag}"), 0)

    def test_released_seat_is_reused(self):
        cc.reserve_slot(uuid="friend-a")
        second = cc.reserve_slot(uuid="friend-b")
        self.assertEqual(cc.release_slot(uuid="friend-a"), 1)
        self.assertEqual(cc.reserve_slot(uuid="friend-d"), 1)
        self.assertEqual(second, 2)

    def test_release_unknown_guest_is_noop(self):
        self.assertEqual(cc.release_slot(uuid="nobody"), -1)
        self.assertEqual(cc.release_slot(), -1)

    def test_stream_end_frees_guest_seats_but_keeps_host(self):
        cc.note_client(0, role="host", name="Host")
        cc.reserve_slot(uuid="friend-a", name="Alex")
        cc.reserve_slot(uuid="friend-b", name="Bo")
        cc.clear_stream_active()
        self.assertEqual(cc.next_empty_slot(), 1)
        players = cc.status().get("players") or []
        self.assertEqual(players[0].get("role"), "host")

    def test_concurrent_reservations_never_collide(self):
        cc.reset_slots()
        results = []
        lock = threading.Lock()

        def claim(tag):
            slot = cc.reserve_slot(uuid=f"friend-{tag}")
            with lock:
                results.append(slot)

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
