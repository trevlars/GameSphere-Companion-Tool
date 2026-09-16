"""WAN automagic mapping — never 47990, one-line status, STUN/NAT-PMP helpers."""

from __future__ import annotations

import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class NatMapUnitTests(unittest.TestCase):
    def test_ports_never_include_web_ui(self):
        from host_tuning import nat_map

        ports = nat_map.mapping_ports(voice=True)
        self.assertTrue(ports)
        self.assertNotIn(47990, [p for p, _ in ports])
        self.assertNotIn(47990, nat_map.SUNSHINE_TCP)
        self.assertNotIn(47990, nat_map.SUNSHINE_UDP)
        self.assertIn((47984, "TCP"), ports)
        self.assertIn((47998, "TCP"), ports)
        self.assertIn((47998, "UDP"), ports)
        self.assertIn((48020, "UDP"), ports)
        self.assertNotIn((48020, "UDP"), nat_map.mapping_ports(voice=False))

    def test_stun_xor_mapped_address(self):
        from host_tuning import nat_map

        txn = b"\x11" * 12
        ip_int = struct.unpack("!I", bytes(int(x) for x in "203.0.113.9".split(".")))[0]
        xip = ip_int ^ nat_map.STUN_MAGIC
        attr = bytes([0, 0x01, 0, 0]) + struct.pack("!I", xip)
        body = struct.pack("!HH", 0x0020, 8) + attr
        header = struct.pack("!HHI", 0x0101, len(body), nat_map.STUN_MAGIC) + txn
        ip = nat_map._parse_stun_mapped(header + body, txn)
        self.assertEqual(ip, "203.0.113.9")

    def test_cgnat_and_rfc1918(self):
        from host_tuning import nat_map

        self.assertTrue(nat_map.is_cgnat_ipv4("100.64.1.2"))
        self.assertTrue(nat_map.is_cgnat_ipv4("10.0.5.42"))
        self.assertFalse(nat_map.is_cgnat_ipv4("203.0.113.9"))
        self.assertTrue(nat_map.is_rfc1918("192.168.1.1"))
        self.assertFalse(nat_map.is_rfc1918("8.8.8.8"))

    def test_igd_service_from_xml(self):
        from host_tuning import nat_map

        xml = b"""<?xml version="1.0"?>
<root>
  <device>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>
        <controlURL>/upnp/control/WANIPConn1</controlURL>
      </service>
    </serviceList>
  </device>
</root>
"""
        with mock.patch("urllib.request.urlopen") as opener:
            resp = mock.MagicMock()
            resp.read.return_value = xml
            resp.__enter__.return_value = resp
            opener.return_value = resp
            svc = nat_map._igd_service_from_location("http://10.0.4.1:5000/root.xml")
        self.assertEqual(svc["serviceType"], "urn:schemas-upnp-org:service:WANIPConnection:1")
        self.assertEqual(svc["controlURL"], "http://10.0.4.1:5000/upnp/control/WANIPConn1")


class WanSetupStatusTests(unittest.TestCase):
    def setUp(self):
        from host_tuning import wan_setup

        with wan_setup._lock:
            wan_setup._state.update(
                {
                    "mapped": False,
                    "mapper": "",
                    "wanHost": "",
                    "lanHost": "",
                    "mappedPorts": [],
                    "failed": [],
                    "voiceMapped": False,
                    "reason": "",
                    "error": "",
                    "status": "",
                    "holdUntil": 0.0,
                    "mappedAt": 0.0,
                    "leaseUntil": 0.0,
                    "wanReady": False,
                }
            )

    def test_status_one_sentence_no_password_no_forward_47990(self):
        from host_tuning import wan_setup

        with mock.patch("host_tuning.wan_setup.lan_ip", return_value="10.0.5.42"), mock.patch(
            "host_tuning.wan_setup.public_ip", return_value="203.0.113.9"
        ), mock.patch("host_tuning.wan_setup._tailscale_ip", return_value=""):
            data = wan_setup.status()
        self.assertIn("status", data)
        self.assertIsInstance(data["status"], str)
        self.assertTrue(data["status"])
        blob = str(data) + wan_setup.print_text()
        self.assertNotIn("sunshine_password", blob.lower())
        self.assertNotIn("port-forward", blob.lower())
        self.assertNotIn("eero", blob.lower())
        self.assertIn("47990", str(data["doNotForward"]))
        self.assertEqual(data["doNotForward"], [47990])

    def test_sentence_when_no_igd(self):
        from host_tuning import wan_setup

        line = wan_setup._sentence(ready=False, mapper="", error="no_igd", cgnat=False, tailscale_ip="")
        self.assertIn("UPnP", line)
        self.assertNotIn("47990", line)
        self.assertNotIn("forward", line.lower())

    def test_ensure_never_maps_web_ui(self):
        from host_tuning import nat_map
        from host_tuning import wan_setup

        captured = {}

        def fake_map(internal_ip, ports, lease=3600):
            captured["ports"] = list(ports)
            result = nat_map.MapResult()
            result.ok = True
            result.mapper = "upnp"
            result.public_ip = "203.0.113.9"
            result.mapped = list(ports)
            return result

        with mock.patch("host_tuning.wan_setup.lan_ip", return_value="10.0.5.42"), mock.patch(
            "host_tuning.wan_setup.public_ip", return_value="203.0.113.9"
        ), mock.patch("host_tuning.wan_setup._tailscale_ip", return_value=""), mock.patch(
            "host_tuning.wan_setup._voice_wanted", return_value=False
        ), mock.patch(
            "host_tuning.sunshine_wan.apply_recommended", return_value={"ok": True, "changed": []}
        ), mock.patch("host_tuning.nat_map.revoke_web_ui_if_mapped"), mock.patch(
            "host_tuning.nat_map.map_ports", side_effect=fake_map
        ):
            data = wan_setup.ensure(reason="invite")
        ports = captured["ports"]
        self.assertNotIn((47990, "TCP"), ports)
        self.assertNotIn((47990, "UDP"), ports)
        self.assertTrue(data["wanReady"])
        self.assertIn("mapped via UPnP", data["status"])
        self.assertEqual(data["wanHost"], "203.0.113.9")
        self.assertIn((47999, "UDP"), ports)
        self.assertIn((48000, "UDP"), ports)

    def test_ensure_failure_sentence(self):
        from host_tuning import nat_map
        from host_tuning import wan_setup

        result = nat_map.MapResult()
        result.ok = False
        result.error = "no_igd"
        with mock.patch("host_tuning.wan_setup.lan_ip", return_value="10.0.5.42"), mock.patch(
            "host_tuning.wan_setup.public_ip", return_value="203.0.113.9"
        ), mock.patch("host_tuning.wan_setup._tailscale_ip", return_value=""), mock.patch(
            "host_tuning.wan_setup._voice_wanted", return_value=False
        ), mock.patch(
            "host_tuning.wan_setup._manual_forward_enabled", return_value=False
        ), mock.patch(
            "host_tuning.sunshine_wan.apply_recommended", return_value={"ok": True, "changed": []}
        ), mock.patch("host_tuning.nat_map.revoke_web_ui_if_mapped"), mock.patch(
            "host_tuning.nat_map.map_ports", return_value=result
        ):
            data = wan_setup.ensure(reason="invite")
        self.assertFalse(data["wanReady"])
        self.assertIn("UPnP", data["status"])
        self.assertNotIn("47990", data["status"])
        self.assertNotIn("eero", data["status"].lower())

    def test_manual_forward_ready_without_upnp(self):
        from host_tuning import nat_map
        from host_tuning import wan_setup

        result = nat_map.MapResult()
        result.ok = False
        result.error = "no_igd"
        with mock.patch("host_tuning.wan_setup.lan_ip", return_value="10.0.5.42"), mock.patch(
            "host_tuning.wan_setup.public_ip", return_value="50.36.49.13"
        ), mock.patch("host_tuning.wan_setup._tailscale_ip", return_value=""), mock.patch(
            "host_tuning.wan_setup._voice_wanted", return_value=False
        ), mock.patch(
            "host_tuning.wan_setup._manual_forward_enabled", return_value=True
        ), mock.patch(
            "host_tuning.sunshine_wan.apply_recommended", return_value={"ok": True, "changed": []}
        ), mock.patch("host_tuning.nat_map.revoke_web_ui_if_mapped"), mock.patch(
            "host_tuning.nat_map.map_ports", return_value=result
        ):
            data = wan_setup.ensure(reason="invite")
        self.assertTrue(data["wanReady"])
        self.assertEqual(data["wanHost"], "50.36.49.13")
        self.assertIn("manual router port forwards", data["status"])


class SunshineWanTests(unittest.TestCase):
    def test_apply_does_not_touch_codecs(self):
        from host_tuning import sunshine_wan

        original = (
            "hevc_mode = 1\n"
            "av1_mode = 1\n"
            "gamepad = x360\n"
            "upnp = enabled\n"
            "origin_web_ui_allowed = lan\n"
        )
        tmp = tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False)
        tmp.write(original)
        tmp.close()
        try:
            result = sunshine_wan.apply_recommended(tmp.name)
            self.assertTrue(result["ok"])
            with open(tmp.name, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("hevc_mode = 1", text)
            self.assertIn("av1_mode = 1", text)
            self.assertIn("gamepad = x360", text)
            self.assertIn("upnp = disabled", text)
            self.assertIn("origin_web_ui_allowed = pc", text)
            self.assertNotRegex(text, r"(?m)^\s*47990\s*=")
        finally:
            os.unlink(tmp.name)

    def test_writes_gamepad_when_missing(self):
        from host_tuning import sunshine_wan

        original = "upnp = enabled\nhevc_mode = 1\n"
        tmp = tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False)
        tmp.write(original)
        tmp.close()
        try:
            result = sunshine_wan.apply_recommended(tmp.name)
            self.assertTrue(result["ok"])
            self.assertIn("gamepad", result.get("changed") or [])
            with open(tmp.name, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("gamepad = x360", text)
            self.assertIn("hevc_mode = 1", text)
            self.assertIn("upnp = disabled", text)
        finally:
            os.unlink(tmp.name)


class InviteTokenTests(unittest.TestCase):
    def test_mint_maps_and_keeps_lan_in_host(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        from host_tuning import invite as guest_invite

        with mock.patch("host_tuning.invite.config_dir", return_value=tmp.name), mock.patch(
            "host_tuning.sunshine_admin.has_credentials", return_value=True
        ), mock.patch("host_tuning.sunshine_admin.list_clients", return_value=[]), mock.patch(
            "host_tuning.invite._local_lan_ip", return_value="10.0.5.42"
        ), mock.patch(
            "host_tuning.wan_setup.hosts_for_join",
            return_value={
                "wanReady": True,
                "wanHost": "203.0.113.9",
                "zerotierHost": "10.147.19.213",
                "status": "Remote join is on — game ports mapped via UPnP for this session only.",
            },
        ), mock.patch("host_tuning.host_identity.snapshot", return_value={}):
            result = guest_invite.mint({"appName": "Celeste", "appId": "9"})
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(len(result["token"]), 16)
        self.assertIn("lan=10.0.5.42", result["joinURL"])
        self.assertIn("wan=203.0.113.9", result["joinURL"])
        self.assertIn("zt=10.147.19.213", result["joinURL"])
        self.assertIn("host=10.0.5.42", result["joinURL"])
        self.assertTrue(result["wanReady"])
        self.assertNotIn("47990", result["joinURL"])


if __name__ == "__main__":
    unittest.main()
