"""Couch co-op pad classification + connect-order (no live host required)."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "couch_coop",
    os.path.join(ROOT, "host_tuning", "couch_coop.py"),
)
cc = importlib.util.module_from_spec(_spec)
sys.modules["couch_coop"] = cc
_spec.loader.exec_module(cc)

DEVICES = """
I: Bus=0003 Vendor=26ce Product=01a2 Version=0110
N: Name="ASRock LED Controller"
P: Phys=usb-0000:00:14.0-11/input0
S: Sysfs=/devices/pci0000:00/0000:00:14.0/usb1/1-11/1-11:1.0/input/input7
U: Uniq=
H: Handlers=kbd event7 js0

I: Bus=0003 Vendor=beef Product=dead Version=0111
N: Name="Mouse passthrough (absolute)"
P: Phys=
S: Sysfs=/devices/virtual/input/input480
U: Uniq=
H: Handlers=mouse2 event20 js1

I: Bus=0003 Vendor=045e Product=02ea Version=0408
N: Name="Sunshine X-Box One (virtual) pad"
P: Phys=
S: Sysfs=/devices/virtual/input/input624
U: Uniq=
H: Handlers=event24 js2

I: Bus=0003 Vendor=045e Product=02ea Version=0408
N: Name="Sunshine X-Box One (virtual) pad"
P: Phys=
S: Sysfs=/devices/virtual/input/input635
U: Uniq=
H: Handlers=event27 js3

I: Bus=0003 Vendor=28de Product=11ff Version=0001
N: Name="Microsoft X-Box 360 pad 0"
P: Phys=
S: Sysfs=/devices/virtual/input/input640
U: Uniq=
H: Handlers=event28 js4

I: Bus=0003 Vendor=28de Product=11ff Version=0001
N: Name="Microsoft X-Box 360 pad 1"
P: Phys=
S: Sysfs=/devices/virtual/input/input641
U: Uniq=
H: Handlers=event29 js5

I: Bus=0003 Vendor=045e Product=028e Version=0114
N: Name="Microsoft X-Box 360 pad"
P: Phys=
S: Sysfs=/devices/virtual/input/input99
U: Uniq=
H: Handlers=event30 js6

I: Bus=0006 Vendor=28de Product=0000 Version=0000
N: Name="steamos-manager"
P: Phys=
S: Sysfs=/devices/virtual/input/input18
U: Uniq=
H: Handlers=kbd event18
"""


class CouchCoopTests(unittest.TestCase):
    def test_connect_order_sunshine_is_p1_then_p2(self):
        pads = cc.parse_input_devices(DEVICES)
        sun = cc.sunshine_pads(pads)
        self.assertEqual(len(sun), 2)
        self.assertEqual(sun[0].input_n, 624)
        self.assertEqual(sun[1].input_n, 635)
        self.assertTrue(sun[0].event_nodes[0].endswith("event24"))
        self.assertTrue(sun[1].event_nodes[0].endswith("event27"))

    def test_steam_clones_are_player_slots(self):
        pads = cc.parse_input_devices(DEVICES)
        slots = cc.steam_slots_from_clones(pads)
        self.assertEqual([s["player"] for s in slots], [1, 2])
        self.assertEqual(len(cc.steam_clones(pads)), 2)

    def test_physical_x360_is_not_sunshine(self):
        pads = cc.parse_input_devices(DEVICES)
        kinds = {p.kind for p in pads}
        self.assertIn("other", kinds)
        self.assertEqual(len(cc.sunshine_pads(pads)), 2)
        physical = [p for p in pads if p.vendor == "045e" and p.product == "028e"]
        self.assertEqual(len(physical), 1)
        self.assertEqual(physical[0].kind, "other")

    def test_junk_and_steamos_filtered(self):
        pads = cc.parse_input_devices(DEVICES)
        junk = [p.name for p in pads if p.kind == "junk"]
        self.assertIn("ASRock LED Controller", junk)
        self.assertIn("Mouse passthrough (absolute)", junk)
        self.assertFalse(any(p.name == "steamos-manager" for p in pads))

    def test_on_sunshine_hint_gamepad1(self):
        # apply() is a no-op-ish on machines without /proc pads; just ensure hint gates.
        self.assertIsNone(cc.on_sunshine_hint("info: hello"))
        # Gamepad 1 should arm + attempt apply (ok even if no devices).
        result = cc.on_sunshine_hint("Info: Gamepad 1 will be Xbox One controller (default)")
        self.assertIsNotNone(result)
        self.assertTrue(cc.armed())

    def test_stabilize_does_not_swap_live_players(self):
        lock = ["host-a", "guest-b", None, None]
        # input_n reordered: guest device now enumerates first
        live = ["guest-b", "host-a"]
        out = cc.stabilize_slots(lock, live)
        self.assertEqual(out, ["host-a", "guest-b", None, None])

    def test_stabilize_does_not_compact_on_blip(self):
        lock = ["host-a", "guest-b", None, None]
        live = ["host-a"]
        out = cc.stabilize_slots(lock, live)
        self.assertEqual(out[0], "host-a")
        self.assertIsNone(out[1])

    def test_new_pad_fills_empty_slot(self):
        lock = ["host-a", None, None, None]
        live = ["host-a", "guest-b"]
        out = cc.stabilize_slots(lock, live)
        self.assertEqual(out, ["host-a", "guest-b", None, None])

    def test_four_players_and_explicit_swap(self):
        lock = ["a", "b", "c", "d"]
        out = cc.stabilize_slots(lock, ["d", "c", "b", "a"])
        self.assertEqual(out, ["a", "b", "c", "d"])
        swapped = cc.remap_slots(lock, [1, 0, 2, 3])
        self.assertEqual(swapped, ["b", "a", "c", "d"])

    def test_gamepad_2_and_3_arm(self):
        result = cc.on_sunshine_hint("Info: Gamepad 2 will be Xbox One controller (default)")
        self.assertIsNotNone(result)
        result3 = cc.on_sunshine_hint("Info: Gamepad 3 will be Xbox One controller (default)")
        self.assertIsNotNone(result3)

    def test_runtime_payload_is_generic(self):
        self.assertFalse(hasattr(cc, "gemma_dualsense_usb"))
        pads = cc.parse_input_devices(DEVICES)
        payload = cc.write_runtime(pads, ["a", "b", None, None])
        self.assertNotIn("gemma_dualsense_usb", payload)
        self.assertNotIn("remote_xbox_p1", payload)
        env_path = cc.runtime_env_path()
        if os.path.isfile(env_path):
            with open(env_path, encoding="utf-8") as fh:
                env = fh.read()
            self.assertNotIn("BAZZITE_REMOTE", env)
            self.assertIn("0x28de/0x11ff", env)


if __name__ == "__main__":
    unittest.main()
