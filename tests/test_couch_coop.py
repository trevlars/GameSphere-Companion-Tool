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

    def test_does_not_treat_ds5_x360_bridge_as_sunshine(self):
        pads = cc.parse_input_devices(DEVICES)
        kinds = {p.kind for p in pads}
        self.assertIn("ds5_x360", kinds)
        self.assertEqual(len(cc.sunshine_pads(pads)), 2)

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


if __name__ == "__main__":
    unittest.main()
