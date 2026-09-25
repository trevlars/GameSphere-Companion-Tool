"""Couch co-op pad classification + connect-order (no live host required)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

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

    def test_reserved_host_seat_blocks_guest_reconnect_to_p1(self):
        cc.note_client(0, role="host", name="Host")
        cc.mark_stream_active()
        lock = [None, None, None, None]
        live = ["guest-b"]
        out = cc.stabilize_slots(lock, live)
        self.assertEqual(out[0], None)
        self.assertEqual(out[1], "guest-b")
        cc.clear_stream_active()

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


class ClonePolicyTests(unittest.TestCase):
    """Steam clones stay readable for Proton games; hidden for emulators / Steam Link."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(cc, "_runtime_dir", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {k: "" for k in cc.FORCE_HIDE_ENV})
        env.start()
        self.addCleanup(env.stop)
        self.pads = cc.parse_input_devices(DEVICES)

    def _touch(self, name, body=""):
        with open(os.path.join(self.tmp.name, name), "w", encoding="utf-8") as fh:
            fh.write(body)

    def test_emulator_names(self):
        for name in (
            "eden",
            "Eden-Linux-v0.0.3-amd64.AppImage",
            "Ryujinx",
            "dolphin-emu",
            "retroarch",
            "Cemu",
            "azahar",
            "soh.elf",
            "2s2h.elf",
            "Spaghettify",
            "/usr/bin/retroarch",
        ):
            self.assertTrue(cc._is_emulator_name(name), name)
        for name in ("Big Walk.exe", "steam", "steamwebhelper", "wineserver", "sohu", "edenfoo", "gamescope"):
            self.assertFalse(cc._is_emulator_name(name), name)

    def test_running_emulator_scans_comm_and_argv0(self):
        proc = os.path.join(self.tmp.name, "proc")
        for pid, comm, argv0 in (
            ("10", "steam", b"/home/u/.steam/steam"),
            ("11", "AppRun.wrapped", b"/tmp/.mount_Eden/usr/bin/eden"),
            ("self", "x", b"x"),
        ):
            os.makedirs(os.path.join(proc, pid))
            with open(os.path.join(proc, pid, "comm"), "w") as fh:
                fh.write(comm + "\n")
            with open(os.path.join(proc, pid, "cmdline"), "wb") as fh:
                fh.write(argv0 + b"\0--flag\0")
        self.assertEqual(cc.running_emulator(proc), "eden")
        os.remove(os.path.join(proc, "11", "cmdline"))
        self.assertEqual(cc.running_emulator(proc), "")

    def test_native_steam_game_keeps_clones_during_gamesphere_stream(self):
        self._touch("gamesphere-stream-active")
        self._touch("bazzite-sunshine-remote-xbox-p1", "never\n")
        self._touch("bazzite-controller-context", "gamesphere-ds5")
        with mock.patch.object(cc, "running_emulator", return_value=""), mock.patch.object(
            cc, "_chmod_000"
        ) as chmod0:
            self.assertEqual(cc.clone_hide_reason(), "")
            self.assertEqual(cc.hide_steam_clones(self.pads), 0)
            chmod0.assert_not_called()

    def test_emulator_hides_clones_not_sunshine_pads(self):
        self._touch("gamesphere-stream-active")
        with mock.patch.object(cc, "running_emulator", return_value="eden"), mock.patch.object(
            cc, "_chmod_000", return_value=True
        ) as chmod0:
            result = cc.sync_steam_clones(self.pads)
        self.assertEqual(result["policy"], "emulator:eden")
        touched = sorted(c.args[0] for c in chmod0.call_args_list)
        self.assertEqual(
            touched,
            ["/dev/input/event28", "/dev/input/event29", "/dev/input/js4", "/dev/input/js5"],
        )

    def test_steamlink_profile_keeps_legacy_hide(self):
        self._touch("gamesphere-stream-active")
        self._touch("bazzite-sunshine-remote-xbox-p1", "always\n")
        with mock.patch.object(cc, "running_emulator", return_value=""):
            self.assertEqual(cc.clone_hide_reason(), "steamlink")
        os.remove(os.path.join(self.tmp.name, "bazzite-sunshine-remote-xbox-p1"))
        self._touch("bazzite-controller-context", "steamlink-x360")
        with mock.patch.object(cc, "running_emulator", return_value=""):
            self.assertEqual(cc.clone_hide_reason(), "steamlink")

    def test_force_env_and_flag(self):
        with mock.patch.object(cc, "running_emulator", return_value=""):
            self.assertEqual(cc.clone_hide_reason(force=True), "forced")
            with mock.patch.dict(os.environ, {"BAZZITE_FORCE_HIDE_CLONES": "1"}):
                self.assertEqual(cc.clone_hide_reason(), "forced")

    def test_sync_restores_after_emulator_exits_during_stream(self):
        self._touch("gamesphere-stream-active")
        with mock.patch.object(cc, "running_emulator", return_value=""), mock.patch.object(
            cc, "_restore_node", return_value=True
        ) as restore:
            result = cc.sync_steam_clones(self.pads)
        self.assertEqual(result["policy"], "visible")
        self.assertEqual(result["restored"], 4)
        self.assertEqual(restore.call_count, 4)

    def test_sync_does_not_restore_outside_stream(self):
        with mock.patch.object(cc, "running_emulator", return_value=""), mock.patch.object(
            cc, "armed", return_value=False
        ), mock.patch.object(cc, "_restore_node") as restore:
            result = cc.sync_steam_clones(self.pads)
        self.assertEqual(result["restored"], 0)
        restore.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_restore_node_regrants_uaccess_acl(self):
        calls = []
        with mock.patch.object(cc, "_mode", return_value=0), mock.patch.object(
            cc.os.path, "exists", return_value=True
        ), mock.patch.object(cc, "_run", side_effect=lambda cmd: calls.append(cmd) or True), mock.patch.object(
            cc, "_login_user", return_value="bazzite"
        ), mock.patch.object(cc.os, "geteuid", return_value=1000):
            self.assertTrue(cc._restore_node("/dev/input/js4"))
            self.assertTrue(cc._restore_node("/dev/input/event28"))
        self.assertEqual(
            calls,
            [
                ["sudo", "-n", "chmod", "664", "/dev/input/js4"],
                ["sudo", "-n", "setfacl", "-m", "u:bazzite:rw", "/dev/input/js4"],
                ["sudo", "-n", "chmod", "660", "/dev/input/event28"],
                ["sudo", "-n", "setfacl", "-m", "u:bazzite:rw", "/dev/input/event28"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
