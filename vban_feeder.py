"""
GameSphere VBAN → Windows playback feeder.

Listens for GameSphere's VBAN PCM (stream name GameSphere, UDP 6980) and plays
it into VB-CABLE's render device ("CABLE Input"). Discord/OBS pick "CABLE Output".

No VoiceMeeter. No extra Python audio packages — WASAPI via ctypes.
"""

from __future__ import annotations

import argparse
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

STREAM_NAME = os.environ.get("GAMESPHERE_VBAN_STREAM", "GameSphere")
PORT = int(os.environ.get("GAMESPHERE_VBAN_PORT", "6980"))
PLAYBACK_MATCH = os.environ.get("GAMESPHERE_VBAN_PLAYBACK_DEVICE", "CABLE Input")
MUTEX_NAME = "Local\\GameSphereVBANFeeder"
RUN_VALUE_NAME = "GameSphereVBANFeeder"
TASK_HINT = "GameSphere VBAN Feeder"

VBAN_HEADER_SIZE = 28
VBAN_MAGIC = b"VBAN"
VBAN_SAMPLE_RATES = [
    6000, 12000, 24000, 48000, 96000, 192000, 384000,
    8000, 16000, 32000, 64000, 128000, 256000, 512000,
    11025, 22050, 44100, 88200, 176400, 352800, 705600,
]
VBAN_SUBPROTOCOL_AUDIO = 0
VBAN_DATATYPE_INT16 = 1
VBAN_CODEC_PCM = 0

LogFn = Callable[[str], None]


@dataclass
class VbanAudioPacket:
    sample_rate: int
    channels: int
    samples_per_channel: int
    stream_name: str
    frame_number: int
    pcm_s16le: bytes


def _log_path() -> str:
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(root, "GameSphere")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "vban-feeder.log")


class _FileLog:
    def __init__(self) -> None:
        self.path = _log_path()
        self._lock = threading.Lock()

    def __call__(self, msg: str) -> None:
        line = msg if msg.endswith("\n") else msg + "\n"
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        text = f"{stamp} {line}"
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except Exception:
            pass
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(text)
            except Exception:
                pass


def parse_vban_packet(data: bytes) -> Optional[VbanAudioPacket]:
    """Parse a VBAN audio PCM INT16 packet. Returns None if not usable."""
    if len(data) < VBAN_HEADER_SIZE:
        return None
    if data[0:4] != VBAN_MAGIC:
        return None
    format_sr = data[4]
    sub_protocol = (format_sr >> 5) & 0x07
    if sub_protocol != VBAN_SUBPROTOCOL_AUDIO:
        return None
    sr_index = format_sr & 0x1F
    if sr_index >= len(VBAN_SAMPLE_RATES):
        return None
    sample_rate = VBAN_SAMPLE_RATES[sr_index]
    samples_per_channel = data[5] + 1
    channels = data[6] + 1
    format_bit = data[7]
    codec = (format_bit >> 4) & 0x0F
    datatype = format_bit & 0x07
    if codec != VBAN_CODEC_PCM or datatype != VBAN_DATATYPE_INT16:
        return None
    raw_name = data[8:24]
    stream_name = raw_name.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    frame_number = struct.unpack_from("<I", data, 24)[0]
    payload = data[VBAN_HEADER_SIZE:]
    expected = samples_per_channel * channels * 2
    if expected <= 0:
        return None
    if len(payload) < expected:
        usable = (len(payload) // (channels * 2)) * (channels * 2)
        if usable <= 0:
            return None
        payload = payload[:usable]
        samples_per_channel = usable // (channels * 2)
    else:
        payload = payload[:expected]
    return VbanAudioPacket(
        sample_rate=sample_rate,
        channels=channels,
        samples_per_channel=samples_per_channel,
        stream_name=stream_name,
        frame_number=frame_number,
        pcm_s16le=payload,
    )


def build_vban_packet(
    pcm_s16le: bytes,
    *,
    sample_rate: int = 44100,
    channels: int = 1,
    stream_name: str = STREAM_NAME,
    frame_number: int = 0,
) -> bytes:
    """Build a GameSphere-compatible VBAN INT16 packet (for tests / loopback)."""
    try:
        sr_index = VBAN_SAMPLE_RATES.index(sample_rate)
    except ValueError:
        sr_index = VBAN_SAMPLE_RATES.index(44100)
    bytes_per_frame = channels * 2
    samples = len(pcm_s16le) // bytes_per_frame if bytes_per_frame else 0
    samples = max(0, min(samples, 256))
    payload = pcm_s16le[: samples * bytes_per_frame]
    name = stream_name.encode("ascii", errors="replace")[:15]
    name = name + b"\x00" * (16 - len(name))
    header = bytearray(VBAN_HEADER_SIZE)
    header[0:4] = VBAN_MAGIC
    header[4] = VBAN_SUBPROTOCOL_AUDIO | sr_index
    header[5] = (samples - 1) & 0xFF if samples else 0
    header[6] = (channels - 1) & 0xFF
    header[7] = VBAN_DATATYPE_INT16
    header[8:24] = name
    struct.pack_into("<I", header, 24, frame_number & 0xFFFFFFFF)
    return bytes(header) + payload


def pcm16_to_stereo(pcm: bytes, channels: int) -> bytes:
    """Return interleaved stereo s16le from 1- or 2-channel interleaved s16le."""
    if channels <= 0:
        return b""
    if channels == 2:
        return pcm
    if channels == 1:
        out = bytearray(len(pcm) * 2)
        j = 0
        for i in range(0, len(pcm) - 1, 2):
            out[j : j + 2] = pcm[i : i + 2]
            out[j + 2 : j + 4] = pcm[i : i + 2]
            j += 4
        return bytes(out)
    frame = channels * 2
    frames = len(pcm) // frame
    out = bytearray(frames * 4)
    o = 0
    for i in range(frames):
        base = i * frame
        out[o : o + 2] = pcm[base : base + 2]
        if channels >= 2:
            out[o + 2 : o + 4] = pcm[base + 2 : base + 4]
        else:
            out[o + 2 : o + 4] = pcm[base : base + 2]
        o += 4
    return bytes(out)


class PcmRing:
    def __init__(self, maxlen_bytes: int) -> None:
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._maxlen = maxlen_bytes

    def push(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            self._buf.extend(data)
            overflow = len(self._buf) - self._maxlen
            if overflow > 0:
                # Drop oldest complete stereo frames (4 bytes).
                overflow += overflow % 4
                del self._buf[:overflow]

    def pull(self, nbytes: int) -> bytes:
        n = nbytes - (nbytes % 4)
        if n <= 0:
            return b""
        with self._lock:
            n = min(n, len(self._buf) - (len(self._buf) % 4))
            if n <= 0:
                return b""
            chunk = bytes(self._buf[:n])
            del self._buf[:n]
            return chunk

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)


def feeder_argv() -> List[str]:
    """Command that starts this feeder in a detached process."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--vban-feeder"]
    here = os.path.abspath(__file__)
    py = sys.executable
    if sys.platform == "win32" and py.lower().endswith("python.exe"):
        pythonw = py[:-10] + "pythonw.exe"
        if os.path.isfile(pythonw):
            py = pythonw
    return [py, here]


def feeder_command_line() -> str:
    parts = []
    for p in feeder_argv():
        if " " in p or "\t" in p:
            parts.append(f'"{p}"')
        else:
            parts.append(p)
    return " ".join(parts)


def list_feeder_pids(exclude_self: bool = True) -> List[int]:
    pids: List[int] = []
    self_pid = os.getpid()
    try:
        import psutil
    except Exception:
        return pids
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            pid = int(proc.info["pid"])
            if exclude_self and pid == self_pid:
                continue
            cmd = proc.info.get("cmdline") or []
            joined = " ".join(str(x) for x in cmd)
            if "--vban-feeder" in joined or "vban_feeder.py" in joined:
                pids.append(pid)
        except (psutil.Error, TypeError, ValueError):
            continue
    return pids


def stop_feeder(log: Optional[LogFn] = None) -> int:
    pids = list_feeder_pids()
    if not pids:
        if log:
            log("No GameSphere VBAN feeder process found.")
        return 0
    try:
        import psutil
    except Exception as exc:
        if log:
            log(f"Cannot stop feeder (psutil missing): {exc}")
        return 1
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            if log:
                log(f"Stopped feeder pid {pid}")
        except psutil.Error as exc:
            if log:
                log(f"Could not stop pid {pid}: {exc}")
    gone, alive = psutil.wait_procs(
        [psutil.Process(p) for p in pids if psutil.pid_exists(p)],
        timeout=4,
    )
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass
    return 0


def start_feeder_detached(log: Optional[LogFn] = None) -> bool:
    """Spawn the feeder in the background. Returns True if a feeder is running."""
    existing = list_feeder_pids()
    if existing:
        if log:
            log(f"VBAN feeder already running (pid {existing[0]}).")
        return True
    argv = feeder_argv()
    if log:
        log(f"Starting VBAN feeder: {feeder_command_line()}")
    kwargs = {}
    if sys.platform == "win32":
        flags = 0
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        kwargs["creationflags"] = flags
        kwargs["close_fds"] = True
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
        kwargs["stdin"] = subprocess.DEVNULL
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        kwargs["startupinfo"] = startup
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(argv, **kwargs)
    except Exception as exc:
        if log:
            log(f"Failed to start feeder: {exc}")
        return False
    time.sleep(0.6)
    return bool(list_feeder_pids())


def register_autostart(log: Optional[LogFn] = None) -> bool:
    if sys.platform != "win32":
        return False
    cmd = feeder_command_line()
    try:
        import winreg

        key = winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
        )
        winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        if log:
            log(f"Registered logon autostart ({RUN_VALUE_NAME}).")
        return True
    except Exception as exc:
        if log:
            log(f"Could not register autostart: {exc}")
        return False


def unregister_autostart(log: Optional[LogFn] = None) -> None:
    if sys.platform != "win32":
        return
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, RUN_VALUE_NAME)
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
        if log:
            log("Removed logon autostart.")
    except Exception as exc:
        if log:
            log(f"Could not remove autostart: {exc}")


# --- WASAPI (Windows) -------------------------------------------------------

_GUID = None


def _guid_class():
    global _GUID
    if _GUID is None:
        from ctypes import Structure, c_byte, c_ulong, c_ushort

        class GUID(Structure):
            _fields_ = [
                ("Data1", c_ulong),
                ("Data2", c_ushort),
                ("Data3", c_ushort),
                ("Data4", c_byte * 8),
            ]

        _GUID = GUID
    return _GUID


def _guid(s: str):
    import uuid

    GUID = _guid_class()
    g = GUID()
    u = uuid.UUID(s)
    g.Data1 = u.time_low
    g.Data2 = u.time_mid
    g.Data3 = u.time_hi_version
    for i, b in enumerate(u.bytes[8:]):
        g.Data4[i] = b
    return g


class _WasapiPlayer:
    """Shared-mode WASAPI render client targeting VB-CABLE Input."""

    CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
    IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
    IID_IMMDevice = "{D666063F-1587-4E43-81F1-B948E807363F}"
    IID_IAudioClient = "{1CB9AD4C-DBFA-4C40-B59F-6E4300A8AB48}"
    IID_IAudioRenderClient = "{F294ACFC-3146-4483-A7BF-ADD0CAE8B4BB}"
    IID_IPropertyStore = "{886d8eeb-8cf2-4446-8d02-cdba1dbdcf99}"
    PKEY_NAME_FMTID = "{A45C254E-DF1C-4EFD-8020-67D146A850E0}"
    CLSCTX_ALL = 23
    DEVICE_STATE_ACTIVE = 1
    eRender = 0
    STGM_READ = 0
    VT_LPWSTR = 31
    AUDCLNT_SHAREMODE_SHARED = 0
    AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
    AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
    AUDCLNT_BUFFERFLAGS_SILENT = 0x2
    WAVE_FORMAT_PCM = 1
    REFTIME_100MS = 1_000_000  # 100 ms in 100-ns units
    COINIT_MULTITHREADED = 0

    def __init__(self) -> None:
        import ctypes
        from ctypes import POINTER, Structure, c_uint32, c_ushort, c_void_p, wintypes

        self.ctypes = ctypes
        self.c_void_p = c_void_p
        self.HRESULT = ctypes.HRESULT
        self.enumerator = None
        self.device = None
        self.client = None
        self.render = None
        self.buffer_frames = 0
        self.block_align = 4
        self.sample_rate = 44100
        self.device_name = ""
        self._ole32 = ctypes.windll.ole32
        self._ole32.CoInitializeEx.argtypes = [c_void_p, wintypes.DWORD]
        self._ole32.CoInitializeEx.restype = ctypes.HRESULT
        self._ole32.CoCreateInstance.argtypes = [
            c_void_p,
            c_void_p,
            wintypes.DWORD,
            c_void_p,
            POINTER(c_void_p),
        ]
        self._ole32.CoCreateInstance.restype = ctypes.HRESULT
        self._ole32.CoUninitialize.argtypes = []
        self._ole32.PropVariantClear.argtypes = [c_void_p]
        self._ole32.PropVariantClear.restype = ctypes.HRESULT

        class WAVEFORMATEX(Structure):
            _fields_ = [
                ("wFormatTag", c_ushort),
                ("nChannels", c_ushort),
                ("nSamplesPerSec", c_uint32),
                ("nAvgBytesPerSec", c_uint32),
                ("nBlockAlign", c_ushort),
                ("wBitsPerSample", c_ushort),
                ("cbSize", c_ushort),
            ]

        class PROPERTYKEY(Structure):
            _fields_ = [("fmtid", _guid_class()), ("pid", c_uint32)]

        class PROPVARIANT(Structure):
            _fields_ = [
                ("vt", wintypes.USHORT),
                ("wReserved1", wintypes.USHORT),
                ("wReserved2", wintypes.USHORT),
                ("wReserved3", wintypes.USHORT),
                ("data", c_void_p),
            ]

        self.WAVEFORMATEX = WAVEFORMATEX
        self.PROPERTYKEY = PROPERTYKEY
        self.PROPVARIANT = PROPVARIANT
        hr = self._ole32.CoInitializeEx(None, self.COINIT_MULTITHREADED)
        # S_OK, S_FALSE, RPC_E_CHANGED_MODE are all usable.
        if hr not in (0, 1, 0x80010106):
            # ctypes HRESULT can be signed
            if hr not in (-2147417850,):
                pass
        self._com_ready = True

    def _vtbl(self, obj):
        return self.ctypes.cast(obj, self.ctypes.POINTER(self.ctypes.POINTER(self.c_void_p))).contents

    def _call(self, obj, index, restype, *args):
        fn = self.ctypes.WINFUNCTYPE(restype, self.c_void_p, *self._argtypes_of(args))(self._vtbl(obj)[index])
        return fn(obj, *[self._unwrap(a) for a in args])

    def _argtypes_of(self, args):
        types = []
        for a in args:
            if isinstance(a, tuple):
                types.append(a[1])
            else:
                types.append(self.c_void_p)
        return tuple(types)

    def _unwrap(self, a):
        return a[0] if isinstance(a, tuple) else a

    def _release(self, obj) -> None:
        if not obj:
            return
        try:
            self.ctypes.WINFUNCTYPE(self.ctypes.c_ulong, self.c_void_p)(self._vtbl(obj)[2])(obj)
        except Exception:
            pass

    def _qi_ok(self, hr: int) -> bool:
        return hr == 0

    def _device_name(self, device) -> str:
        from ctypes import POINTER, byref, c_void_p, wintypes

        store = c_void_p()
        iid = _guid(self.IID_IPropertyStore)
        hr = self.ctypes.WINFUNCTYPE(
            self.HRESULT, c_void_p, wintypes.DWORD, POINTER(_guid_class()), POINTER(c_void_p)
        )(self._vtbl(device)[4])(device, self.STGM_READ, byref(iid), byref(store))
        if hr != 0 or not store:
            return ""
        try:
            pk = self.PROPERTYKEY()
            pk.fmtid = _guid(self.PKEY_NAME_FMTID)
            pk.pid = 14
            pv = self.PROPVARIANT()
            hr = self.ctypes.WINFUNCTYPE(
                self.HRESULT, c_void_p, POINTER(self.PROPERTYKEY), POINTER(self.PROPVARIANT)
            )(self._vtbl(store)[5])(store, byref(pk), byref(pv))
            name = ""
            if hr == 0 and pv.vt == self.VT_LPWSTR and pv.data:
                name = self.ctypes.wstring_at(pv.data)
            self._ole32.PropVariantClear(byref(pv))
            return name
        finally:
            self._release(store)

    def _ensure_enumerator(self) -> None:
        from ctypes import byref, c_void_p

        if self.enumerator is not None:
            return
        enumerator = c_void_p()
        clsid = _guid(self.CLSID_MMDeviceEnumerator)
        iid = _guid(self.IID_IMMDeviceEnumerator)
        hr = self._ole32.CoCreateInstance(
            byref(clsid), None, self.CLSCTX_ALL, byref(iid), byref(enumerator)
        )
        if hr != 0 or not enumerator:
            raise OSError(hr, "CoCreateInstance(MMDeviceEnumerator) failed")
        self.enumerator = enumerator

    def _iter_render_devices(self):
        from ctypes import POINTER, byref, c_void_p, wintypes

        self._ensure_enumerator()
        collection = c_void_p()
        hr = self.ctypes.WINFUNCTYPE(
            self.HRESULT, c_void_p, wintypes.DWORD, wintypes.DWORD, POINTER(c_void_p)
        )(self._vtbl(self.enumerator)[3])(
            self.enumerator, self.eRender, self.DEVICE_STATE_ACTIVE, byref(collection)
        )
        if hr != 0 or not collection:
            return
        try:
            count = wintypes.UINT()
            self.ctypes.WINFUNCTYPE(self.HRESULT, c_void_p, POINTER(wintypes.UINT))(
                self._vtbl(collection)[3]
            )(collection, byref(count))
            for i in range(int(count.value)):
                dev = c_void_p()
                hr = self.ctypes.WINFUNCTYPE(
                    self.HRESULT, c_void_p, wintypes.UINT, POINTER(c_void_p)
                )(self._vtbl(collection)[4])(collection, i, byref(dev))
                if hr != 0 or not dev:
                    continue
                name = self._device_name(dev) or f"Render device {i}"
                yield dev, name
        finally:
            self._release(collection)

    def list_render_devices(self) -> List[str]:
        names: List[str] = []
        for dev, name in self._iter_render_devices():
            names.append(name)
            self._release(dev)
        return names

    def pick_device(self, match: str) -> Tuple[object, str]:
        needle = (match or "CABLE Input").casefold()
        ranked: List[Tuple[int, object, str]] = []
        leftovers: List[object] = []
        names: List[str] = []
        for dev, name in self._iter_render_devices():
            names.append(name)
            n = name.casefold()
            if "cable output" in n:
                leftovers.append(dev)
                continue
            score = -1
            if needle in n:
                score = 100
                if "vb-audio" in n:
                    score += 10
                if n.startswith("cable input"):
                    score += 5
            elif "cable input" in n:
                score = 50
            if score >= 0:
                ranked.append((score, dev, name))
            else:
                leftovers.append(dev)
        for dev in leftovers:
            self._release(dev)
        if not ranked:
            listed = ", ".join(names) or "(none)"
            raise RuntimeError(
                f'No playback device matching "{match}". Active render devices: {listed}'
            )
        ranked.sort(key=lambda t: t[0], reverse=True)
        _score, chosen, chosen_name = ranked[0]
        for _s, dev, _n in ranked[1:]:
            self._release(dev)
        return chosen, chosen_name

    def open(self, match: str, sample_rate: int) -> None:
        from ctypes import POINTER, byref, c_uint32, c_void_p, wintypes

        self.close_stream()
        if self.device:
            self._release(self.device)
            self.device = None
        self.device, self.device_name = self.pick_device(match)
        iid_client = _guid(self.IID_IAudioClient)
        client = c_void_p()
        hr = self.ctypes.WINFUNCTYPE(
            self.HRESULT,
            c_void_p,
            POINTER(_guid_class()),
            wintypes.DWORD,
            c_void_p,
            POINTER(c_void_p),
        )(self._vtbl(self.device)[3])(
            self.device, byref(iid_client), self.CLSCTX_ALL, None, byref(client)
        )
        if hr != 0 or not client:
            raise OSError(hr, "IMMDevice.Activate(IAudioClient) failed")
        wfx = self.WAVEFORMATEX()
        wfx.wFormatTag = self.WAVE_FORMAT_PCM
        wfx.nChannels = 2
        wfx.nSamplesPerSec = int(sample_rate)
        wfx.wBitsPerSample = 16
        wfx.nBlockAlign = 4
        wfx.nAvgBytesPerSec = int(sample_rate) * 4
        wfx.cbSize = 0
        flags = self.AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | self.AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY
        hr = self.ctypes.WINFUNCTYPE(
            self.HRESULT,
            c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            self.ctypes.c_longlong,
            self.ctypes.c_longlong,
            POINTER(self.WAVEFORMATEX),
            c_void_p,
        )(self._vtbl(client)[3])(
            client,
            self.AUDCLNT_SHAREMODE_SHARED,
            flags,
            2000000,  # 200 ms
            0,
            byref(wfx),
            None,
        )
        if hr != 0:
            self._release(client)
            raise OSError(hr, f"IAudioClient.Initialize failed (0x{hr & 0xFFFFFFFF:08X})")
        frames = c_uint32()
        hr = self.ctypes.WINFUNCTYPE(self.HRESULT, c_void_p, POINTER(c_uint32))(
            self._vtbl(client)[4]
        )(client, byref(frames))
        if hr != 0:
            self._release(client)
            raise OSError(hr, "GetBufferSize failed")
        iid_render = _guid(self.IID_IAudioRenderClient)
        render = c_void_p()
        hr = self.ctypes.WINFUNCTYPE(
            self.HRESULT, c_void_p, POINTER(_guid_class()), POINTER(c_void_p)
        )(self._vtbl(client)[14])(client, byref(iid_render), byref(render))
        if hr != 0 or not render:
            self._release(client)
            raise OSError(hr, "GetService(IAudioRenderClient) failed")
        hr = self.ctypes.WINFUNCTYPE(self.HRESULT, c_void_p)(self._vtbl(client)[10])(client)
        if hr != 0:
            self._release(render)
            self._release(client)
            raise OSError(hr, "IAudioClient.Start failed")
        self.client = client
        self.render = render
        self.buffer_frames = int(frames.value)
        self.block_align = 4
        self.sample_rate = int(sample_rate)

    def write_available(self, ring: PcmRing) -> None:
        from ctypes import POINTER, byref, c_byte, c_uint32

        if not self.client or not self.render:
            return
        padding = c_uint32()
        hr = self.ctypes.WINFUNCTYPE(self.HRESULT, self.c_void_p, POINTER(c_uint32))(
            self._vtbl(self.client)[6]
        )(self.client, byref(padding))
        if hr != 0:
            return
        avail = self.buffer_frames - int(padding.value)
        if avail < 64:
            return
        ptr = self.c_void_p()
        hr = self.ctypes.WINFUNCTYPE(
            self.HRESULT, self.c_void_p, c_uint32, POINTER(self.c_void_p)
        )(self._vtbl(self.render)[3])(self.render, avail, byref(ptr))
        if hr != 0 or not ptr:
            return
        nbytes = avail * self.block_align
        chunk = ring.pull(nbytes)
        if not chunk:
            self.ctypes.memset(ptr, 0, nbytes)
            flags = self.AUDCLNT_BUFFERFLAGS_SILENT
        else:
            self.ctypes.memmove(ptr, chunk, len(chunk))
            if len(chunk) < nbytes:
                self.ctypes.memset(int(ptr.value) + len(chunk), 0, nbytes - len(chunk))
            flags = 0
        self.ctypes.WINFUNCTYPE(self.HRESULT, self.c_void_p, c_uint32, c_uint32)(
            self._vtbl(self.render)[4]
        )(self.render, avail, flags)

    def close_stream(self) -> None:
        if self.client:
            try:
                self.ctypes.WINFUNCTYPE(self.HRESULT, self.c_void_p)(self._vtbl(self.client)[11])(
                    self.client
                )
            except Exception:
                pass
        self._release(self.render)
        self._release(self.client)
        self.render = None
        self.client = None

    def close(self) -> None:
        self.close_stream()
        self._release(self.device)
        self._release(self.enumerator)
        self.device = None
        self.enumerator = None
        try:
            self._ole32.CoUninitialize()
        except Exception:
            pass


def list_playback_device_names() -> List[str]:
    if sys.platform != "win32":
        return []
    player = _WasapiPlayer()
    try:
        return player.list_render_devices()
    finally:
        player.close()


def cable_input_present(match: str = PLAYBACK_MATCH) -> bool:
    if sys.platform != "win32":
        return False
    try:
        names = list_playback_device_names()
    except Exception:
        return False
    needle = (match or "CABLE Input").casefold()
    for name in names:
        n = name.casefold()
        if "cable output" in n:
            continue
        if needle in n or "cable input" in n:
            return True
    return False


def run_feeder(
    *,
    port: int = PORT,
    stream_name: str = STREAM_NAME,
    playback_match: str = PLAYBACK_MATCH,
    log: Optional[LogFn] = None,
) -> int:
    if sys.platform != "win32":
        print("The VBAN feeder plays into VB-CABLE on Windows only.", file=sys.stderr)
        return 1
    logger = log or _FileLog()
    if not _acquire_mutex():
        logger("Feeder already running in this session.")
        return 0

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.settimeout(0.02)
    except OSError as exc:
        logger(f"Could not bind UDP {port}: {exc}")
        return 1

    logger(
        f"GameSphere VBAN feeder listening on UDP {port}, stream '{stream_name}', "
        f"playback '{playback_match}'."
    )
    logger(f"Log: {_log_path()}")

    # ~500 ms of stereo s16 @ 48 kHz
    ring = PcmRing(maxlen_bytes=48000 * 4)
    stop = threading.Event()
    format_lock = threading.Lock()
    current_rate = {"hz": 0}

    def net_loop() -> None:
        packets = 0
        last_note = 0.0
        while not stop.is_set():
            try:
                data, _addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            pkt = parse_vban_packet(data)
            if pkt is None:
                continue
            if stream_name and pkt.stream_name != stream_name:
                continue
            stereo = pcm16_to_stereo(pkt.pcm_s16le, pkt.channels)
            ring.push(stereo)
            with format_lock:
                current_rate["hz"] = pkt.sample_rate
            packets += 1
            now = time.monotonic()
            if now - last_note > 5:
                logger(f"Receiving '{pkt.stream_name}' {pkt.sample_rate} Hz {pkt.channels}ch ({packets} packets)")
                last_note = now

    net = threading.Thread(target=net_loop, name="vban-udp", daemon=True)
    net.start()

    player = None
    opened_rate = 0
    try:
        player = _WasapiPlayer()
        logger("Waiting for VBAN packets (start Mic in GameSphere)…")
        while not stop.is_set():
            with format_lock:
                rate = current_rate["hz"]
            if rate and (player.client is None or rate != opened_rate):
                try:
                    player.open(playback_match, rate)
                    opened_rate = rate
                    logger(f"Playing into '{player.device_name}' at {rate} Hz stereo PCM16.")
                except Exception as exc:
                    logger(f"WASAPI open failed: {exc}")
                    time.sleep(1.5)
                    continue
            if player.client:
                try:
                    player.write_available(ring)
                except Exception as exc:
                    logger(f"WASAPI write failed: {exc}")
                    player.close_stream()
                    opened_rate = 0
                    time.sleep(0.2)
                    continue
            time.sleep(0.005)
    except KeyboardInterrupt:
        logger("Stopping feeder.")
    finally:
        stop.set()
        try:
            sock.close()
        except Exception:
            pass
        if player:
            player.close()
    return 0


def _acquire_mutex() -> bool:
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.GetLastError.restype = wintypes.DWORD
    handle = k32.CreateMutexW(None, True, MUTEX_NAME)
    if not handle:
        return True
    ERROR_ALREADY_EXISTS = 183
    if k32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False
    # Keep handle alive for process lifetime.
    run_feeder._mutex_handle = handle  # type: ignore[attr-defined]
    return True


def self_check() -> None:
    """Sanity-check VBAN parse against GameSphere's packet layout."""
    tone = struct.pack("<" + "h" * 8, 0, 1000, 2000, 3000, 0, -1000, -2000, -3000)
    pkt = build_vban_packet(tone, sample_rate=44100, channels=1, stream_name="GameSphere", frame_number=7)
    parsed = parse_vban_packet(pkt)
    assert parsed is not None
    assert parsed.stream_name == "GameSphere"
    assert parsed.sample_rate == 44100
    assert parsed.channels == 1
    assert parsed.frame_number == 7
    assert parsed.pcm_s16le == tone
    stereo = pcm16_to_stereo(parsed.pcm_s16le, 1)
    assert len(stereo) == len(tone) * 2
    assert parse_vban_packet(b"NOPE") is None
    assert parse_vban_packet(pkt[:10]) is None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Receive GameSphere VBAN and play it into VB-CABLE (CABLE Input)."
    )
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--stream-name", default=STREAM_NAME)
    parser.add_argument("--playback-device", default=PLAYBACK_MATCH)
    parser.add_argument("--stop", action="store_true", help="Stop a running feeder and exit")
    parser.add_argument("--list-devices", action="store_true", help="List Windows playback devices")
    parser.add_argument("--self-check", action="store_true", help="Run packet parser checks and exit")
    args = parser.parse_args(argv)
    if args.self_check:
        self_check()
        print("vban_feeder self-check ok")
        return 0
    if args.stop:
        return stop_feeder(print)
    if args.list_devices:
        if sys.platform != "win32":
            print("Device listing is Windows-only.")
            return 1
        for name in list_playback_device_names():
            print(name)
        return 0
    return run_feeder(
        port=args.port,
        stream_name=args.stream_name,
        playback_match=args.playback_device,
    )


if __name__ == "__main__":
    raise SystemExit(main())
