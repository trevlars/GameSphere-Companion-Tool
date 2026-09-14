"""Game-agnostic couch co-op P1/P2 via Sunshine connect-order + Steam Input.

Sunshine (`gamepad = x360`) allocates Gamepad 0 (host) then Gamepad 1 (guest).
Steam Input clones those as VID 28de / PID 11ff "Microsoft X-Box 360 pad 0/1"
— those *are* Steam player slots. The clones also show up as extra SDL pads and
steal Player 2 unless they are hidden from the joystick subsystem.

Companion applies this automatically on JOINACK, Sunshine Gamepad 1, a second
session, and pad arrival. No per-title LD_PRELOAD.

HarbourMasters (SpaghettiKart / SOH / 2S2H) maps every SDL pad to Port 1.
Steam Input cannot fix that engine. Steam-facing titles get connect-order P1/P2.

Gemma DualSense USB: never let Sunshine/Link x360 steal emu P1
(`BAZZITE_REMOTE_XBOX_P1=never`). Do not claim DualSense in VirtualHere here.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

GEMMA_ACCOUNT_ID = "708606858"
STEAM_CLONE_VENDOR = "28de"
STEAM_CLONE_PRODUCT = "11ff"
SUNSHINE_XBOX_ONE = ("045e", "02ea")
DS5_X360_BRIDGE = ("045e", "028e")
DUALSENSE = ("054c", "0ce6")

_JUNK_NAMES = (
    "asrock led controller",
    "mouse passthrough (absolute)",
    "mouse passthrough (relative)",
)

_RUNTIME_JSON = "gamesphere-couch-coop.json"
_RUNTIME_ENV = "gamesphere-couch-coop.env"
_ARM_SECONDS = 180.0
_APPLY_DEBOUNCE = 0.8

_lock = threading.Lock()
_armed_until = 0.0
_last_apply = 0.0
_last_sig = ""


@dataclass
class Pad:
    name: str
    vendor: str
    product: str
    handlers: List[str] = field(default_factory=list)
    sysfs: str = ""
    uniq: str = ""
    kind: str = ""  # sunshine | steam_clone | dualsense | ds5_x360 | junk | other

    @property
    def input_n(self) -> int:
        m = re.search(r"/input/input(\d+)", self.sysfs)
        return int(m.group(1)) if m else 10**9

    @property
    def event_nodes(self) -> List[str]:
        return [f"/dev/input/{h}" for h in self.handlers if h.startswith("event")]

    @property
    def js_nodes(self) -> List[str]:
        return [f"/dev/input/{h}" for h in self.handlers if h.startswith("js")]

    @property
    def nodes(self) -> List[str]:
        return self.event_nodes + self.js_nodes


def _runtime_dir() -> str:
    candidates = [
        os.environ.get("XDG_RUNTIME_DIR"),
        f"/run/user/{os.getuid()}" if hasattr(os, "getuid") else "",
        tempfile.gettempdir(),
    ]
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return tempfile.gettempdir()


def runtime_json_path() -> str:
    return os.path.join(_runtime_dir(), _RUNTIME_JSON)


def runtime_env_path() -> str:
    return os.path.join(_runtime_dir(), _RUNTIME_ENV)


def parse_input_devices(text: str) -> List[Pad]:
    pads: List[Pad] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        name_m = re.search(r"^N: Name=\"([^\"]*)\"", block, re.M)
        vend_m = re.search(r"Vendor=([0-9a-fA-F]+)", block)
        prod_m = re.search(r"Product=([0-9a-fA-F]+)", block)
        hand_m = re.search(r"^H: Handlers=([^\n]+)", block, re.M)
        sys_m = re.search(r"^S: Sysfs=([^\n]+)", block, re.M)
        uniq_m = re.search(r"^U: Uniq=([^\n]*)", block, re.M)
        name = name_m.group(1) if name_m else ""
        vendor = (vend_m.group(1) if vend_m else "").lower().zfill(4)
        product = (prod_m.group(1) if prod_m else "").lower().zfill(4)
        handlers = hand_m.group(1).split() if hand_m else []
        if not any(h.startswith("js") or h.startswith("event") for h in handlers):
            continue
        pad = Pad(
            name=name,
            vendor=vendor,
            product=product,
            handlers=handlers,
            sysfs=sys_m.group(1).strip() if sys_m else "",
            uniq=(uniq_m.group(1).strip() if uniq_m else ""),
            kind=_classify(name, vendor, product, handlers),
        )
        if pad.kind == "skip":
            continue
        pads.append(pad)
    return pads


def _classify(name: str, vendor: str, product: str, handlers: List[str]) -> str:
    low = name.lower()
    if any(j in low for j in _JUNK_NAMES):
        return "junk"
    if vendor == STEAM_CLONE_VENDOR and product == STEAM_CLONE_PRODUCT:
        return "steam_clone"
    if vendor == DUALSENSE[0] and product == DUALSENSE[1]:
        return "dualsense"
    if "dualsense" in low or "playstation 5" in low:
        return "dualsense"
    if vendor == DS5_X360_BRIDGE[0] and product == DS5_X360_BRIDGE[1]:
        # Gemma DS5→x360 bridge — not a Sunshine stream pad.
        if "sunshine" not in low:
            return "ds5_x360"
    if "sunshine" in low:
        return "sunshine"
    if vendor == SUNSHINE_XBOX_ONE[0] and product == SUNSHINE_XBOX_ONE[1] and "virtual" in low:
        return "sunshine"
    # Keyboard/mouse/LED-only nodes that are not joysticks
    if not any(h.startswith("js") for h in handlers):
        if any(s in low for s in ("keyboard", "mouse", "consumer", "steamos-manager")):
            return "skip"
    return "other"


def read_live_pads() -> List[Pad]:
    path = "/proc/bus/input/devices"
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return parse_input_devices(fh.read())
    except OSError:
        return []


def sunshine_pads(pads: Optional[List[Pad]] = None) -> List[Pad]:
    found = [p for p in (pads if pads is not None else read_live_pads()) if p.kind == "sunshine"]
    return sorted(found, key=lambda p: (p.input_n, p.name))


def steam_clones(pads: Optional[List[Pad]] = None) -> List[Pad]:
    found = [p for p in (pads if pads is not None else read_live_pads()) if p.kind == "steam_clone"]
    return sorted(found, key=lambda p: (p.input_n, p.name))


def _active_steam_account_id() -> str:
    helper = os.path.expanduser("~/.local/bin/get-active-steam-user.sh")
    if os.path.isfile(helper) and os.access(helper, os.X_OK):
        try:
            out = subprocess.check_output([helper], text=True, timeout=3)
            for line in out.splitlines():
                if line.startswith("account_id="):
                    return line.split("=", 1)[1].strip()
        except (subprocess.SubprocessError, OSError):
            pass
    return ""


def _lsusb_has(vid_pid: str) -> bool:
    try:
        out = subprocess.check_output(["lsusb"], text=True, timeout=3)
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return False
    return vid_pid.lower() in out.lower()


def gemma_dualsense_usb() -> bool:
    """Gemma profile + hardwired DualSense — physical pad owns P1."""
    if _active_steam_account_id() != GEMMA_ACCOUNT_ID:
        return False
    return _lsusb_has("054c:0ce6")


def stream_active() -> bool:
    flag = os.path.join(_runtime_dir(), "bazzite-sunshine-stream-active")
    return os.path.isfile(flag)


def arm_late_join(seconds: float = _ARM_SECONDS) -> None:
    global _armed_until
    _armed_until = time.time() + seconds


def armed() -> bool:
    return time.time() < _armed_until


def _run(cmd: List[str]) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def _mode(path: str) -> int:
    try:
        return os.stat(path).st_mode & 0o777
    except OSError:
        return -1


def _chmod_000(path: str) -> bool:
    if not os.path.exists(path):
        return False
    if _mode(path) == 0:
        return False
    if os.geteuid() == 0:
        ok = _run(["chmod", "000", path])
        _run(["setfacl", "-b", path])
        return ok
    if _run(["sudo", "-n", "chmod", "000", path]):
        _run(["sudo", "-n", "setfacl", "-b", path])
        return True
    try:
        os.chmod(path, 0)
        return True
    except OSError:
        return False


def hide_steam_clones(pads: Optional[List[Pad]] = None) -> int:
    """Hide Steam Input 28de:11ff clones from SDL. Do not touch DualSense or Sunshine."""
    hidden = 0
    visible = False
    for pad in steam_clones(pads):
        for node in pad.nodes:
            if _mode(node) not in (0, -1):
                visible = True
            if _chmod_000(node):
                hidden += 1
    script = os.path.expanduser("~/.local/bin/bazzite-hide-steam-x360-clones.sh")
    if visible and os.path.isfile(script) and os.access(script, os.X_OK):
        _run([script])
    return hidden


def hide_junk_joysticks(pads: Optional[List[Pad]] = None) -> int:
    """Drop LED/mouse-passthrough js nodes so they cannot steal SDL slot 0."""
    hidden = 0
    for pad in pads if pads is not None else read_live_pads():
        if pad.kind != "junk":
            continue
        for node in pad.js_nodes:
            if _chmod_000(node):
                hidden += 1
    return hidden


def ensure_clone_watch() -> bool:
    if os.name == "nt":
        return False
    flag = os.path.join(_runtime_dir(), "bazzite-sunshine-stream-active")
    try:
        with open(flag, "a", encoding="utf-8"):
            pass
    except OSError:
        return False
    try:
        out = subprocess.check_output(["pgrep", "-f", "bazzite-steam-clone-watch.sh"], text=True, timeout=2)
        if out.strip():
            return True
    except (subprocess.SubprocessError, OSError):
        pass
    watch = os.path.expanduser("~/.local/bin/bazzite-steam-clone-watch.sh")
    if not (os.path.isfile(watch) and os.access(watch, os.X_OK)):
        return False
    try:
        subprocess.Popen(
            [watch],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        return False


def _steam_slot_name(index: int) -> str:
    return f"Microsoft X-Box 360 pad {index}"


def steam_slots_from_clones(pads: Optional[List[Pad]] = None) -> List[Dict[str, Any]]:
    """Steam Input names clones 'Microsoft X-Box 360 pad N' — N is the player slot."""
    slots = []
    for pad in steam_clones(pads):
        m = re.search(r"pad\s*(\d+)", pad.name, re.I)
        slot = int(m.group(1)) if m else None
        slots.append(
            {
                "name": pad.name,
                "steam_slot": slot,
                "player": (slot + 1) if slot is not None else None,
                "nodes": pad.nodes,
            }
        )
    return slots


def _write_player_slot_led(account_id: str, slot: int) -> bool:
    """Best-effort Steam personalization LED slot (does not distinguish twin 045e:02ea)."""
    if not account_id:
        return False
    root = os.path.expanduser(
        f"~/.local/share/Steam/steamapps/common/Steam Controller Configs/{account_id}/config"
    )
    if not os.path.isdir(root):
        return False
    changed = False
    for name in os.listdir(root):
        if not name.startswith("preferences_45e-2ea") and not name.startswith("preferences_45e-28e"):
            continue
        path = os.path.join(root, name)
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if re.search(r'"player_slot_led"\s+"\d+"', text):
            new = re.sub(r'"player_slot_led"\s+"\d+"', f'"player_slot_led"\t\t"{slot}"', text, count=1)
        elif "ControllerPersonalization" in text and "{" in text:
            new = text.replace("{", '{\n\t"player_slot_led"\t\t"%d"' % slot, 1)
        else:
            continue
        if new != text:
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new)
                changed = True
            except OSError:
                pass
    return changed


def write_runtime(pads: List[Pad], gemma_ds: bool) -> Dict[str, Any]:
    sun = sunshine_pads(pads)
    clones = steam_clones(pads)
    event_pin = []
    for pad in sun:
        event_pin.extend(pad.event_nodes)
    payload: Dict[str, Any] = {
        "v": 1,
        "mechanism": "sunshine_connect_order + steam_input_slots + hide_28de_11ff",
        "gemma_dualsense_usb": gemma_ds,
        "remote_xbox_p1": "never" if gemma_ds else "auto",
        "sunshine_count": len(sun),
        "steam_clone_count": len(clones),
        "sunshine": [
            {
                "name": p.name,
                "player": i + 1,
                "input": p.input_n,
                "nodes": p.nodes,
            }
            for i, p in enumerate(sun)
        ],
        "steam_slots": steam_slots_from_clones(pads),
        "sdl_joystick_device": ":".join(event_pin) if (len(sun) >= 2 and not gemma_ds) else "",
        "harbourmasters_exception": (
            "SpaghettiKart / SOH / 2S2H map every SDL pad to Port 1. "
            "Steam Input cannot rematerialize HM ports. Use 2P GAME if the engine offers it."
        ),
    }
    try:
        with open(runtime_json_path(), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
    except OSError as exc:
        logging.warning("couch_coop: write json failed: %s", exc)

    env_lines = [
        "# Written by GameSphere Companion (host_tuning.couch_coop). Game-agnostic P1/P2.",
        "export GAMESPHERE_COUCH_COOP=1",
        "export SDL_GAMECONTROLLER_IGNORE_DEVICES=0x28de/0x11ff",
        "export SDL_HIDAPI_IGNORE_DEVICES=0x28de/0x11ff",
        "export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0",
        "export SDL_JOYSTICK_HIDAPI_STEAMXBOX=0",
    ]
    if gemma_ds:
        env_lines.append("export BAZZITE_REMOTE_XBOX_P1=never")
        env_lines.append("export BAZZITE_INCLUDE_VIRTUAL_XBOX=never")
    elif len(sun) >= 2 and event_pin:
        env_lines.append(f"export SDL_JOYSTICK_DEVICE={':'.join(event_pin)}")
        env_lines.append("export BAZZITE_REMOTE_XBOX_P1=auto")
    try:
        with open(runtime_env_path(), "w", encoding="utf-8") as fh:
            fh.write("\n".join(env_lines) + "\n")
    except OSError as exc:
        logging.warning("couch_coop: write env failed: %s", exc)
    return payload


def _signature(pads: List[Pad]) -> str:
    parts = [f"{p.kind}:{p.vendor}:{p.product}:{p.input_n}:{p.name}" for p in pads]
    return "|".join(parts)


def apply(reason: str = "manual", force: bool = False) -> Dict[str, Any]:
    """Hide Steam clones, pin connect-order Sunshine pads, write runtime state."""
    global _last_apply, _last_sig
    if os.name == "nt":
        return {"ok": True, "skipped": "windows", "reason": reason}

    now = time.time()
    pads = read_live_pads()
    sig = _signature(pads)
    with _lock:
        if not force and sig == _last_sig and (now - _last_apply) < _APPLY_DEBOUNCE:
            return {"ok": True, "debounced": True, "reason": reason}
        _last_apply = now
        _last_sig = sig

    gemma_ds = gemma_dualsense_usb()
    hidden_clones = hide_steam_clones(pads)
    hidden_junk = hide_junk_joysticks(pads)
    watch = ensure_clone_watch() if (stream_active() or armed() or sunshine_pads(pads)) else False
    if not gemma_ds:
        _write_player_slot_led(_active_steam_account_id(), 0)
    sync = os.path.expanduser("~/.local/bin/bazzite-sync-emulator-player-order.py")
    synced = False
    if os.path.isfile(sync) and os.access(sync, os.X_OK) and not gemma_ds:
        synced = _run(["python3", sync])
    payload = write_runtime(pads, gemma_ds)
    payload.update(
        {
            "ok": True,
            "reason": reason,
            "hidden_clones": hidden_clones,
            "hidden_junk": hidden_junk,
            "clone_watch": watch,
            "player_order_sync": synced,
        }
    )
    logging.info(
        "couch_coop apply reason=%s sunshine=%s clones=%s hidden=%s gemma_ds=%s",
        reason,
        payload.get("sunshine_count"),
        payload.get("steam_clone_count"),
        hidden_clones,
        gemma_ds,
    )
    return payload


def on_join_accepted() -> Dict[str, Any]:
    arm_late_join()
    return apply("joinack", force=True)


def on_sunshine_hint(line: str) -> Optional[Dict[str, Any]]:
    low = line.lower()
    if "gamepad 1" in low or re.search(r"active sessions:\s*[2-9]", low):
        arm_late_join()
        return apply("sunshine_log")
    if "gamepad 0" in low and (stream_active() or armed()):
        return apply("sunshine_log")
    return None


def status() -> Dict[str, Any]:
    pads = read_live_pads()
    gemma_ds = gemma_dualsense_usb()
    saved: Dict[str, Any] = {}
    path = runtime_json_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
        except (OSError, json.JSONDecodeError):
            saved = {}
    return {
        "ok": True,
        "stream_active": stream_active(),
        "armed": armed(),
        "gemma_dualsense_usb": gemma_ds,
        "sunshine": [
            {"name": p.name, "player": i + 1, "nodes": p.nodes, "input": p.input_n}
            for i, p in enumerate(sunshine_pads(pads))
        ],
        "steam_slots": steam_slots_from_clones(pads),
        "junk": [{"name": p.name, "nodes": p.js_nodes} for p in pads if p.kind == "junk"],
        "runtime": saved,
        "verify": (
            "Sunshine pads = connect-order P1/P2. Steam clones 28de:11ff "
            "should be mode 000 (ls -l /dev/input/js*). evtest the Sunshine event "
            "nodes. Steam-facing games use 'X-Box 360 pad 0/1' slots. "
            "HarbourMasters still binds all SDL pads to Port 1."
        ),
    }


class CouchCoopWatch:
    """Re-apply mapping when Gamepad 1 appears after the game already launched."""

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="couch-coop-watch")
        self._thread.start()
        logging.info("couch_coop watcher started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self) -> None:
        last_sun = -1
        last_clones = -1
        while not self._stop.is_set():
            try:
                if stream_active() or armed():
                    pads = read_live_pads()
                    sun = len(sunshine_pads(pads))
                    clones = len(steam_clones(pads))
                    if sun != last_sun or clones != last_clones:
                        apply("pad_arrival", force=True)
                        last_sun, last_clones = sun, clones
                    elif clones:
                        hide_steam_clones(pads)  # no-op when clones already mode 000
            except Exception:
                logging.exception("couch_coop watcher")
            self._stop.wait(self.interval)


def main(argv: Optional[List[str]] = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "status"
    if cmd == "apply":
        print(json.dumps(apply("cli", force=True), indent=2))
        return 0
    if cmd == "status":
        print(json.dumps(status(), indent=2))
        return 0
    print("usage: python3 -m host_tuning.couch_coop [status|apply]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
