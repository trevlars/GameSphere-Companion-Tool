"""UPnP IGD / NAT-PMP / PCP port mapping + STUN public IP.

Companion owns WAN mappings so Sunshine UPnP is not required and 47990 is never
published. No third-party native libs — SSDP/SOAP and UDP packets only.
"""

from __future__ import annotations

import logging
import os
import re
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

DO_NOT_MAP = frozenset({47990})
SUNSHINE_TCP = (47984, 47989, 48010, 47998)
SUNSHINE_UDP = (47998, 47999, 48000, 48002, 48010)
VOICE_UDP = 48020
LEASE_SECONDS = 3600
SSDP_ADDR = ("239.255.255.250", 1900)
STUN_MAGIC = 0x2112A442
STUN_SERVERS = (
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
)

_log = logging.getLogger(__name__)


def mapping_ports(*, voice: bool = False) -> List[Tuple[int, str]]:
    """(port, TCP|UDP) pairs. Never includes 47990."""
    out: List[Tuple[int, str]] = []
    for port in SUNSHINE_TCP:
        out.append((int(port), "TCP"))
    for port in SUNSHINE_UDP:
        out.append((int(port), "UDP"))
    if voice:
        out.append((int(VOICE_UDP), "UDP"))
    return [(p, proto) for p, proto in out if p not in DO_NOT_MAP]


def is_cgnat_ipv4(ip: str) -> bool:
    parts = (ip or "").split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return False
    if nums[0] == 100 and 64 <= nums[1] <= 127:
        return True
    if nums[0] == 10:
        return True
    if nums[0] == 192 and nums[1] == 168:
        return True
    if nums[0] == 172 and 16 <= nums[1] <= 31:
        return True
    if nums[0] == 127:
        return True
    return False


def is_rfc1918(ip: str) -> bool:
    parts = (ip or "").split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return False
    if nums[0] == 10:
        return True
    if nums[0] == 192 and nums[1] == 168:
        return True
    if nums[0] == 172 and 16 <= nums[1] <= 31:
        return True
    return False


def default_gateway() -> str:
    if os.name == "nt":
        return _gateway_windows()
    path = "/proc/net/route"
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                next(fh, None)
                for line in fh:
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    dest, gateway = parts[1], parts[2]
                    if dest == "00000000" and gateway != "00000000":
                        raw = int(gateway, 16)
                        return socket.inet_ntoa(struct.pack("<I", raw))
        except OSError:
            pass
    try:
        result = __import__("subprocess").run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            m = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", result.stdout)
            if m:
                return m.group(1)
    except (FileNotFoundError, OSError):
        pass
    return ""


def _gateway_windows() -> str:
    try:
        result = __import__("subprocess").run(
            ["route", "print", "-4"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return ""
        for line in result.stdout.splitlines():
            if "0.0.0.0" not in line:
                continue
            parts = line.split()
            ips = [p for p in parts if re.match(r"^\d+\.\d+\.\d+\.\d+$", p)]
            if len(ips) >= 2 and ips[0] == "0.0.0.0":
                return ips[1]
    except (FileNotFoundError, OSError):
        pass
    return ""


def stun_public_ip(timeout: float = 1.8) -> str:
    txn = os.urandom(12)
    req = struct.pack("!HHI", 0x0001, 0, STUN_MAGIC) + txn
    for host, port in STUN_SERVERS:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(req, (host, port))
            data, _ = sock.recvfrom(1024)
            sock.close()
            ip = _parse_stun_mapped(data, txn)
            if ip:
                return ip
        except OSError:
            try:
                sock.close()
            except Exception:
                pass
    return ""


def _parse_stun_mapped(data: bytes, txn: bytes) -> str:
    if len(data) < 20:
        return ""
    if data[4:8] != struct.pack("!I", STUN_MAGIC):
        return ""
    if data[8:20] != txn:
        return ""
    length = struct.unpack("!H", data[2:4])[0]
    pos = 20
    end = min(len(data), 20 + length)
    while pos + 4 <= end:
        atype, alen = struct.unpack("!HH", data[pos : pos + 4])
        aval = data[pos + 4 : pos + 4 + alen]
        pos += 4 + alen
        pos += (4 - alen % 4) % 4
        if atype in (0x0020, 0x8020) and len(aval) >= 8:  # XOR-MAPPED-ADDRESS
            family = aval[1]
            xport = struct.unpack("!H", aval[2:4])[0] ^ (STUN_MAGIC >> 16)
            del xport
            if family == 0x01:
                xip = struct.unpack("!I", aval[4:8])[0] ^ STUN_MAGIC
                return socket.inet_ntoa(struct.pack("!I", xip))
        if atype == 0x0001 and len(aval) >= 8:  # MAPPED-ADDRESS
            family = aval[1]
            if family == 0x01:
                return socket.inet_ntoa(aval[4:8])
    return ""


def ipify_public_ip(timeout: float = 2.5) -> str:
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=timeout) as resp:
            ip = resp.read().decode("utf-8", errors="replace").strip()
            if ip and len(ip) < 64 and re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
                return ip
    except Exception:
        pass
    return ""


def public_ip() -> str:
    ip = stun_public_ip()
    if ip and not is_rfc1918(ip):
        return ip
    fallback = ipify_public_ip()
    return fallback or ip


class MapResult:
    def __init__(self) -> None:
        self.ok = False
        self.mapper = ""
        self.public_ip = ""
        self.mapped: List[Tuple[int, str]] = []
        self.failed: List[Tuple[int, str]] = []
        self.error = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "mapper": self.mapper,
            "public_ip": self.public_ip,
            "mapped": [{"port": p, "proto": proto} for p, proto in self.mapped],
            "failed": [{"port": p, "proto": proto} for p, proto in self.failed],
            "error": self.error,
        }


def map_ports(
    internal_ip: str,
    ports: Sequence[Tuple[int, str]],
    lease: int = LEASE_SECONDS,
) -> MapResult:
    wanted = [(int(p), proto.upper()) for p, proto in ports if int(p) not in DO_NOT_MAP]
    result = MapResult()
    if not internal_ip or not wanted:
        result.error = "no_lan_or_ports"
        return result

    remaining = list(wanted)
    mappers = (
        ("upnp", _upnp_map),
        ("natpmp", _natpmp_map),
        ("pcp", _pcp_map),
    )
    for mapper, fn in mappers:
        if not remaining:
            break
        try:
            mapped, public_ip, err = fn(internal_ip, remaining, lease)
        except Exception as exc:
            _log.debug("WAN map %s: %s", mapper, exc)
            continue
        if public_ip and not result.public_ip:
            result.public_ip = public_ip
        if mapped:
            result.ok = True
            if not result.mapper:
                result.mapper = mapper
            have = set(result.mapped)
            for row in mapped:
                if row not in have:
                    result.mapped.append(row)
                    have.add(row)
            remaining = [row for row in remaining if row not in have]
        elif err and not result.ok:
            result.error = err
    result.failed = remaining
    if result.ok:
        result.public_ip = result.public_ip or public_ip_cached_or_stun()
        result.error = ""
        return result
    if not result.error:
        result.error = "no_igd"
    return result


def unmap_ports(internal_ip: str, ports: Sequence[Tuple[int, str]]) -> None:
    wanted = [(int(p), proto.upper()) for p, proto in ports if int(p) not in DO_NOT_MAP]
    try:
        _natpmp_map(internal_ip, wanted, lifetime=0)
    except Exception:
        _log.debug("NAT-PMP unmap failed", exc_info=True)
    try:
        _pcp_map(internal_ip, wanted, lifetime=0)
    except Exception:
        _log.debug("PCP unmap failed", exc_info=True)
    try:
        _upnp_delete(internal_ip, wanted)
    except Exception:
        _log.debug("UPnP unmap failed", exc_info=True)
    try:
        _upnp_delete_web_ui()
    except Exception:
        pass


def revoke_web_ui_if_mapped() -> None:
    """If an IGD already published Sunshine's web UI, drop it."""
    try:
        _upnp_delete_web_ui()
    except Exception:
        _log.debug("revoke 47990 failed", exc_info=True)


def public_ip_cached_or_stun() -> str:
    ip = stun_public_ip()
    if ip:
        return ip
    return ipify_public_ip()


# --- NAT-PMP (RFC 6886) -----------------------------------------------------

def _natpmp_map(
    internal_ip: str,
    ports: Sequence[Tuple[int, str]],
    lifetime: int,
) -> Tuple[List[Tuple[int, str]], str, str]:
    gw = default_gateway()
    if not gw:
        return [], "", "no_gateway"
    public_ip = _natpmp_external_ip(gw)
    mapped: List[Tuple[int, str]] = []
    for port, proto in ports:
        op = 2 if proto == "TCP" else 1
        pkt = struct.pack("!BBHHHI", 0, op, 0, port, port, lifetime & 0xFFFFFFFF)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1.6)
            sock.sendto(pkt, (gw, 5351))
            data, _ = sock.recvfrom(64)
            sock.close()
        except OSError:
            try:
                sock.close()
            except Exception:
                pass
            if not mapped:
                return [], public_ip, "natpmp_timeout"
            continue
        if len(data) < 4:
            continue
        vers, opcode = data[0], data[1]
        if vers == 2 and not mapped:
            return [], public_ip, "pcp_only"
        if opcode != (128 + op) or len(data) < 16:
            continue
        result_code = struct.unpack("!H", data[2:4])[0]
        if result_code != 0:
            continue
        mapped.append((port, proto))
    return mapped, public_ip, "" if mapped else "natpmp_failed"


def _natpmp_external_ip(gw: str) -> str:
    pkt = struct.pack("!BB", 0, 0)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.4)
        sock.sendto(pkt, (gw, 5351))
        data, _ = sock.recvfrom(32)
        sock.close()
        if len(data) >= 12 and data[0] == 0 and data[1] == 128:
            return socket.inet_ntoa(data[8:12])
    except OSError:
        try:
            sock.close()
        except Exception:
            pass
    return ""


# --- PCP MAP (RFC 6887) -------------------------------------------------------

def _pcp_map(
    internal_ip: str,
    ports: Sequence[Tuple[int, str]],
    lifetime: int,
) -> Tuple[List[Tuple[int, str]], str, str]:
    gw = default_gateway()
    if not gw:
        return [], "", "no_gateway"
    try:
        client = socket.inet_aton(internal_ip)
    except OSError:
        return [], "", "bad_lan"
    mapped: List[Tuple[int, str]] = []
    public_ip = ""
    for port, proto in ports:
        proto_num = 6 if proto == "TCP" else 17
        nonce = os.urandom(12)
        # Header: ver=2, opcode=MAP(1), reserved, lifetime, client IPv4-mapped IPv6
        header = struct.pack("!BB2sI", 2, 1, b"\x00\x00", lifetime & 0xFFFFFFFF)
        client_ip = b"\x00" * 10 + b"\xff\xff" + client
        # MAP: nonce(12) + proto(1) + reserved(3) + int_port(2) + ext_port(2) + ext_ip(16)
        ext_ip = b"\x00" * 16
        payload = nonce + struct.pack("!B3sHH", proto_num, b"\x00\x00\x00", port, port) + ext_ip
        pkt = header + client_ip + payload
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1.6)
            sock.sendto(pkt, (gw, 5351))
            data, _ = sock.recvfrom(128)
            sock.close()
        except OSError:
            try:
                sock.close()
            except Exception:
                pass
            if not mapped:
                return [], "", "pcp_timeout"
            continue
        if len(data) < 24 or data[0] != 2:
            continue
        result_code = data[3]
        if result_code != 0:
            continue
        mapped.append((port, proto))
        if len(data) >= 56:
            ext = data[40:56]
            if ext[10:12] == b"\xff\xff":
                public_ip = socket.inet_ntoa(ext[12:16])
    return mapped, public_ip, "" if mapped else "pcp_failed"


# --- UPnP IGD ---------------------------------------------------------------

_IGD_CACHE: Dict[str, Any] = {"at": 0.0, "svc": None}
# Serializes gateway discovery so overlapping map_ports() calls do not each fire
# their own SSDP burst and then race on the shared cache.
_igd_lock = threading.Lock()


def _upnp_map(
    internal_ip: str,
    ports: Sequence[Tuple[int, str]],
    lease: int,
) -> Tuple[List[Tuple[int, str]], str, str]:
    svc = _discover_igd()
    if not svc:
        return [], "", "no_igd"
    public_ip = _soap_external_ip(svc) or ""
    _upnp_delete_web_ui(svc)

    def one(row: Tuple[int, str]) -> Optional[Tuple[int, str]]:
        port, proto = row
        if _soap_already_ours(svc, internal_ip, port, proto):
            return row
        if _soap_add(svc, internal_ip, port, proto, lease):
            return row
        _soap_delete(svc, port, proto)
        if _soap_add(svc, internal_ip, port, proto, lease):
            return row
        if lease and _soap_add(svc, internal_ip, port, proto, 0):
            return row
        if _soap_already_ours(svc, internal_ip, port, proto):
            return row
        return None

    mapped: List[Tuple[int, str]] = []
    for row in ports:
        got = one(row)
        if got:
            mapped.append(got)
    return mapped, public_ip, "" if mapped else "upnp_add_failed"


def _upnp_delete(internal_ip: str, ports: Sequence[Tuple[int, str]]) -> None:
    svc = _discover_igd()
    if not svc:
        return
    for port, proto in ports:
        _soap_delete(svc, port, proto)


def _upnp_delete_web_ui(svc: Optional[Dict[str, str]] = None) -> None:
    svc = svc or _discover_igd()
    if not svc:
        return
    _soap_delete(svc, 47990, "TCP")


def _discover_igd() -> Optional[Dict[str, str]]:
    cached = _IGD_CACHE.get("svc")
    if cached and time.time() - float(_IGD_CACHE.get("at") or 0) < 120:
        return cached
    with _igd_lock:
        return _discover_igd_locked()


def _discover_igd_locked() -> Optional[Dict[str, str]]:
    now = time.time()
    # Another thread may have finished discovery while we waited.
    cached = _IGD_CACHE.get("svc")
    if cached and now - float(_IGD_CACHE.get("at") or 0) < 120:
        return cached
    persisted = _load_igd_cache()
    persisted_dead = False
    if persisted:
        # Re-validate quickly; keep if SOAP still answers.
        ip = _soap_external_ip(persisted)
        if ip:
            _IGD_CACHE["svc"] = persisted
            _IGD_CACHE["at"] = now
            return persisted
        persisted_dead = True
    locations: List[str] = []
    sts = (
        "urn:schemas-upnp-org:service:WANIPConnection:2",
        "urn:schemas-upnp-org:service:WANIPConnection:1",
        "urn:schemas-upnp-org:service:WANPPPConnection:1",
        "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    )
    targets = [SSDP_ADDR]
    gw = default_gateway()
    if gw:
        targets.append((gw, 1900))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.4)
        sock.bind(("", 0))
        for _round in range(2):
            for st in sts:
                payload = (
                    "M-SEARCH * HTTP/1.1\r\n"
                    f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
                    'MAN: "ssdp:discover"\r\n'
                    "MX: 3\r\n"
                    f"ST: {st}\r\n"
                    "\r\n"
                ).encode("ascii")
                for dest in targets:
                    try:
                        sock.sendto(payload, dest)
                    except OSError:
                        continue
            deadline = time.time() + 1.8
            while time.time() < deadline:
                try:
                    data, _addr = sock.recvfrom(8192)
                except socket.timeout:
                    sock.settimeout(0.4)
                    continue
                except OSError:
                    break
                loc = _ssdp_location(data.decode("utf-8", errors="replace"))
                if loc and loc not in locations and "://" in loc and ":" in loc:
                    locations.append(loc)
            if locations:
                break
    finally:
        sock.close()

    for loc in locations:
        svc = _igd_service_from_location(loc)
        if svc:
            _IGD_CACHE["svc"] = svc
            _IGD_CACHE["at"] = time.time()
            _save_igd_cache(svc)
            return svc
    if persisted and not persisted_dead:
        return persisted
    if persisted_dead:
        # The saved router no longer answers SOAP (replaced, new IP, UPnP off).
        # Returning it anyway made every port map wait out a 3s timeout.
        _log.info("UPnP: cached gateway no longer responds — forgetting it")
        _forget_igd_cache()
    return None


def _forget_igd_cache() -> None:
    _IGD_CACHE["svc"] = None
    _IGD_CACHE["at"] = 0.0
    path = _igd_cache_path()
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def _igd_cache_path() -> str:
    try:
        from host_tuning.config import config_dir

        return os.path.join(config_dir(), "wan_igd.json")
    except Exception:
        return ""


def _load_igd_cache() -> Optional[Dict[str, str]]:
    path = _igd_cache_path()
    if not path or not os.path.isfile(path):
        return None
    try:
        import json

        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("controlURL") and data.get("serviceType"):
            return {
                "serviceType": str(data["serviceType"]),
                "controlURL": str(data["controlURL"]),
                "location": str(data.get("location") or ""),
            }
    except Exception:
        return None
    return None


def _save_igd_cache(svc: Dict[str, str]) -> None:
    path = _igd_cache_path()
    if not path:
        return
    try:
        from host_tuning.json_store import write_json_atomic

        write_json_atomic(path, svc, indent=None)
    except OSError:
        pass


def _ssdp_location(text: str) -> str:
    for line in text.splitlines():
        if line.lower().startswith("location:"):
            return line.split(":", 1)[1].strip()
    return ""


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _igd_service_from_location(location: str) -> Optional[Dict[str, str]]:
    try:
        req = urllib.request.Request(location, headers={"User-Agent": "GameSphere-Companion"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            xml_text = resp.read()
    except Exception:
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    wanted = {
        "urn:schemas-upnp-org:service:WANIPConnection:2",
        "urn:schemas-upnp-org:service:WANIPConnection:1",
        "urn:schemas-upnp-org:service:WANPPPConnection:1",
    }
    parsed = urlparse(location)
    base = f"{parsed.scheme}://{parsed.netloc}"
    for node in root.iter():
        if _local_name(node.tag) != "service":
            continue
        stype = ""
        control = ""
        for child in list(node):
            name = _local_name(child.tag)
            if name == "serviceType":
                stype = (child.text or "").strip()
            elif name == "controlURL":
                control = (child.text or "").strip()
        if stype not in wanted or not control:
            continue
        if control.startswith("http"):
            control_url = control
        else:
            control_url = urljoin(location if location.endswith("/") else location.rsplit("/", 1)[0] + "/", control)
            if control.startswith("/"):
                control_url = base + control
        return {"serviceType": stype, "controlURL": control_url, "location": location}
    return None


def _soap_add(svc: Dict[str, str], internal_ip: str, port: int, proto: str, lease: int) -> bool:
    body = (
        f"<NewRemoteHost></NewRemoteHost>"
        f"<NewExternalPort>{port}</NewExternalPort>"
        f"<NewProtocol>{proto}</NewProtocol>"
        f"<NewInternalPort>{port}</NewInternalPort>"
        f"<NewInternalClient>{internal_ip}</NewInternalClient>"
        f"<NewEnabled>1</NewEnabled>"
        f"<NewPortMappingDescription>GameSphere {port}/{proto}</NewPortMappingDescription>"
        f"<NewLeaseDuration>{int(lease)}</NewLeaseDuration>"
    )
    code, _ = _soap(svc, "AddPortMapping", body)
    return code in (200, 204)


def _soap_already_ours(svc: Dict[str, str], internal_ip: str, port: int, proto: str) -> bool:
    body = (
        f"<NewRemoteHost></NewRemoteHost>"
        f"<NewExternalPort>{port}</NewExternalPort>"
        f"<NewProtocol>{proto}</NewProtocol>"
    )
    code, xml_text = _soap(svc, "GetSpecificPortMappingEntry", body)
    if code not in (200, 204) or not xml_text:
        return False
    m = re.search(r"<NewInternalClient>\s*([^<]+)\s*</NewInternalClient>", xml_text)
    return bool(m) and m.group(1).strip() == internal_ip


def _soap_delete(svc: Dict[str, str], port: int, proto: str) -> bool:
    body = (
        f"<NewRemoteHost></NewRemoteHost>"
        f"<NewExternalPort>{port}</NewExternalPort>"
        f"<NewProtocol>{proto}</NewProtocol>"
    )
    code, _ = _soap(svc, "DeletePortMapping", body)
    return code in (200, 204)


def _soap_external_ip(svc: Dict[str, str]) -> str:
    _code, xml_text = _soap(svc, "GetExternalIPAddress", "")
    if not xml_text:
        return ""
    m = re.search(r"<NewExternalIPAddress>\s*([^<]+)\s*</NewExternalIPAddress>", xml_text)
    if m:
        return m.group(1).strip()
    return ""


def _soap(svc: Dict[str, str], action: str, inner: str) -> Tuple[int, str]:
    stype = svc["serviceType"]
    envelope = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f"<s:Body><u:{action} xmlns:u=\"{stype}\">{inner}</u:{action}></s:Body>"
        "</s:Envelope>"
    ).encode("utf-8")
    req = urllib.request.Request(
        svc["controlURL"],
        data=envelope,
        method="POST",
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{stype}#{action}"',
            "User-Agent": "GameSphere-Companion",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return getattr(resp, "status", 200) or 200, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, payload
    except Exception:
        return 0, ""
