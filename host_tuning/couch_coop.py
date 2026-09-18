"""Game-agnostic couch co-op P1–P4 via Sunshine connect-order + Steam Input.

Sunshine (`gamepad = x360`) allocates Gamepad 0 (host) then 1–3 as guests join.
Steam Input clones those as VID 28de / PID 11ff "Microsoft X-Box 360 pad N"
— those *are* Steam player slots. The clones also show up as extra SDL pads and
steal later players unless they are hidden from the joystick subsystem.

Slots are assigned once on join (connect-order). Re-apply never swaps two live
players when a pad blips, Steam clones reappear, or the watcher fires. Host Swap
is the only explicit remap.
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

STEAM_CLONE_VENDOR = "28de"
STEAM_CLONE_PRODUCT = "11ff"
SUNSHINE_XBOX_ONE = ("045e", "02ea")
PHYSICAL_X360 = ("045e", "028e")

_JUNK_NAMES = (
    "asrock led controller",
    "mouse passthrough (absolute)",
    "mouse passthrough (relative)",
)

_RUNTIME_JSON = "gamesphere-couch-coop.json"
_RUNTIME_ENV = "gamesphere-couch-coop.env"
_ARM_SECONDS = 180.0
_APPLY_DEBOUNCE = 0.8
MAX_PLAYERS = 4

_lock = threading.Lock()
_armed_until = 0.0
_last_apply = 0.0
_last_sig = ""
_slot_lock: List[Optional[str]] = [None] * MAX_PLAYERS
_slot_meta: List[Dict[str, Any]] = [{} for _ in range(MAX_PLAYERS)]
_last_live_keys: List[str] = []


@dataclass
class Pad:
    name: str
    vendor: str
    product: str
    handlers: List[str] = field(default_factory=list)
    sysfs: str = ""
    uniq: str = ""
    kind: str = ""  # sunshine | steam_clone | junk | other

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
    if vendor == PHYSICAL_X360[0] and product == PHYSICAL_X360[1] and "sunshine" not in low:
        # Physical / OS x360 pad — not a Sunshine virtual stream pad (045e:02ea).
        return "other"
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


def _stream_flag_path() -> str:
    return os.path.join(_runtime_dir(), "gamesphere-stream-active")


def mark_stream_active() -> None:
    path = _stream_flag_path()
    try:
        with open(path, "a", encoding="utf-8"):
            pass
    except OSError:
        pass


def clear_stream_active() -> None:
    try:
        os.remove(_stream_flag_path())
    except OSError:
        pass


def stream_active() -> bool:
    runtime = _runtime_dir()
    for name in ("gamesphere-stream-active", "sunshine-stream-active"):
        if os.path.isfile(os.path.join(runtime, name)):
            return True
    return False


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
    """Hide Steam Input 28de:11ff clones from SDL. Do not touch Sunshine virtual pads."""
    hidden = 0
    for pad in steam_clones(pads):
        for node in pad.nodes:
            if _chmod_000(node):
                hidden += 1
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
    """CouchCoopWatch in the host daemon is the product clone hider (plus udev)."""
    return os.name != "nt"


def _steam_slot_name(index: int) -> str:
    return f"Microsoft X-Box 360 pad {index}"


def pad_key(pad: Pad) -> str:
    """Identity for slot lock. Prefer uniq; else event nodes + name (not input_n)."""
    if pad.uniq:
        return f"u:{pad.uniq}"
    events = ",".join(pad.event_nodes) or ",".join(pad.nodes)
    return f"n:{events}|{pad.vendor}:{pad.product}|{pad.name}"


def _host_seat_reserved() -> bool:
    """During a live co-op session, slot 0 stays reserved for P1 even when the pad blips."""
    if not (stream_active() or armed()):
        return False
    meta = _slot_meta[0] if _slot_meta else {}
    role = (meta.get("role") or "host").lower()
    return role in ("", "host")


def stabilize_slots(
    lock: List[Optional[str]],
    live_keys: List[str],
    max_players: int = MAX_PLAYERS,
) -> List[Optional[str]]:
    """Keep occupied live players in their seats. Fill empty seats. Never swap two live keys."""
    size = max(1, int(max_players))
    new_lock: List[Optional[str]] = list(lock[:size]) if lock else []
    while len(new_lock) < size:
        new_lock.append(None)
    new_lock = new_lock[:size]
    live = [k for k in live_keys if k]
    live_set = set(live)
    occupied: Dict[str, int] = {}
    for i, key in enumerate(new_lock):
        if key and key in live_set:
            occupied[key] = i
        else:
            new_lock[i] = None
    unmatched = [k for k in live if k not in occupied]
    # When P1 is reserved but disconnected, a lone reconnecting pad is P2 — not slot 0.
    empties = [
        i
        for i, k in enumerate(new_lock)
        if not k and not (i == 0 and _host_seat_reserved())
    ]
    for key, slot in zip(unmatched, empties):
        new_lock[slot] = key
    return new_lock


def remap_slots(lock: List[Optional[str]], order: List[int], max_players: int = MAX_PLAYERS) -> List[Optional[str]]:
    """Explicit host Swap. `order[i]` is the old slot that should become new slot i."""
    size = max(1, int(max_players))
    src = list(lock[:size]) if lock else []
    while len(src) < size:
        src.append(None)
    out: List[Optional[str]] = [None] * size
    seen = set()
    for new_i, old_i in enumerate(order[:size]):
        try:
            idx = int(old_i)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= size or idx in seen:
            continue
        seen.add(idx)
        out[new_i] = src[idx]
    return out


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
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
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


def _pads_by_key(pads: List[Pad]) -> Dict[str, Pad]:
    return {pad_key(p): p for p in sunshine_pads(pads)}


def _ordered_sunshine(pads: List[Pad], lock: List[Optional[str]]) -> List[tuple]:
    by_key = _pads_by_key(pads)
    ordered = []
    for i, key in enumerate(lock):
        pad = by_key.get(key) if key else None
        ordered.append((i, key, pad))
    return ordered


def write_runtime(pads: List[Pad], lock: Optional[List[Optional[str]]] = None) -> Dict[str, Any]:
    sun = sunshine_pads(pads)
    clones = steam_clones(pads)
    slot_lock = list(lock if lock is not None else _slot_lock)
    while len(slot_lock) < MAX_PLAYERS:
        slot_lock.append(None)
    ordered = _ordered_sunshine(pads, slot_lock)
    event_pin = []
    sunshine_rows = []
    for i, key, pad in ordered:
        meta = _slot_meta[i] if i < len(_slot_meta) else {}
        row = {
            "player": i + 1,
            "slot": i,
            "key": key,
            "name": pad.name if pad else (meta.get("name") or ""),
            "input": pad.input_n if pad else None,
            "nodes": pad.nodes if pad else [],
            "present": pad is not None,
            "clientId": meta.get("clientId") or "",
            "clientName": meta.get("name") or ("Host" if i == 0 else ""),
            "role": meta.get("role") or ("host" if i == 0 else ("guest" if key else "")),
        }
        sunshine_rows.append(row)
        if pad:
            event_pin.extend(pad.event_nodes)
    filled = sum(1 for _i, key, pad in ordered if pad)
    payload: Dict[str, Any] = {
        "v": 2,
        "mechanism": "sunshine_connect_order + steam_input_slots + hide_28de_11ff + sticky_slots",
        "max_players": MAX_PLAYERS,
        "sunshine_count": len(sun),
        "steam_clone_count": len(clones),
        "slot_lock": slot_lock,
        "sunshine": sunshine_rows,
        "steam_slots": steam_slots_from_clones(pads),
        "sdl_joystick_device": ":".join(event_pin) if filled >= 2 else "",
        "harbourmasters_exception": (
            "SpaghettiKart / SOH / 2S2H map every SDL pad to Port 1. "
            "Steam Input cannot rematerialize HM ports. Use 2P GAME if the engine offers it."
        ),
    }
    try:
        from host_tuning.json_store import write_json_atomic

        write_json_atomic(runtime_json_path(), payload)
    except OSError as exc:
        logging.warning("couch_coop: write json failed: %s", exc)

    env_lines = [
        "# Written by GameSphere Companion (host_tuning.couch_coop). Game-agnostic P1-P4.",
        "export GAMESPHERE_COUCH_COOP=1",
        "export SDL_GAMECONTROLLER_IGNORE_DEVICES=0x28de/0x11ff",
        "export SDL_HIDAPI_IGNORE_DEVICES=0x28de/0x11ff",
        "export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0",
        "export SDL_JOYSTICK_HIDAPI_STEAMXBOX=0",
    ]
    if filled >= 2 and event_pin:
        env_lines.append(f"export SDL_JOYSTICK_DEVICE={':'.join(event_pin)}")
    try:
        with open(runtime_env_path(), "w", encoding="utf-8") as fh:
            fh.write("\n".join(env_lines) + "\n")
    except OSError as exc:
        logging.warning("couch_coop: write env failed: %s", exc)
    return payload


def _signature(pads: List[Pad]) -> str:
    parts = [f"{p.kind}:{p.vendor}:{p.product}:{p.input_n}:{p.name}" for p in pads]
    return "|".join(parts)


def _live_keys(pads: List[Pad]) -> List[str]:
    return [pad_key(p) for p in sunshine_pads(pads)]


def _should_sync_player_order(reason: str) -> bool:
    return reason in ("joinack", "host_swap", "cli")


def apply(reason: str = "manual", force: bool = False) -> Dict[str, Any]:
    """Hide Steam clones and pin locked Sunshine slots. Never swap two live players."""
    global _last_apply, _last_sig, _slot_lock, _last_live_keys
    if os.name == "nt":
        return {"ok": True, "skipped": "windows", "reason": reason}

    now = time.time()
    pads = read_live_pads()
    live = _live_keys(pads)
    sig = _signature(pads)
    with _lock:
        if not force and sig == _last_sig and (now - _last_apply) < _APPLY_DEBOUNCE:
            return {"ok": True, "debounced": True, "reason": reason}
        prev_lock = list(_slot_lock)
        new_lock = stabilize_slots(_slot_lock, live)
        lock_changed = new_lock != prev_lock
        clones_only = (not lock_changed) and live == _last_live_keys and reason in (
            "pad_arrival",
            "sunshine_log",
            "bridge_start",
        )
        _last_apply = now
        _last_sig = sig
        _slot_lock = new_lock
        _last_live_keys = live

    if reason in ("session_start", "prep_start"):
        mark_stream_active()
    hidden_clones = hide_steam_clones(pads)
    hidden_junk = hide_junk_joysticks(pads)
    watch = ensure_clone_watch() if (stream_active() or armed() or sunshine_pads(pads)) else False
    synced = False
    if (not clones_only) and _should_sync_player_order(reason):
        if reason == "host_swap":
            _write_player_slot_led(_active_steam_account_id(), 0)
    payload = write_runtime(pads, _slot_lock)
    payload.update(
        {
            "ok": True,
            "reason": reason,
            "hidden_clones": hidden_clones,
            "hidden_junk": hidden_junk,
            "clone_watch": watch,
            "player_order_sync": synced,
            "lock_changed": lock_changed,
            "clones_only": clones_only,
        }
    )
    logging.info(
        "couch_coop apply reason=%s sunshine=%s clones=%s hidden=%s lock=%s swapped=%s",
        reason,
        payload.get("sunshine_count"),
        payload.get("steam_clone_count"),
        hidden_clones,
        _slot_lock,
        False,
    )
    return payload


def note_client(slot: int, client_id: str = "", name: str = "", role: str = "", uuid: str = "") -> None:
    if slot < 0 or slot >= MAX_PLAYERS:
        return
    meta = dict(_slot_meta[slot])
    if client_id:
        meta["clientId"] = client_id
    if uuid:
        meta["uuid"] = uuid
    if name:
        meta["name"] = name
    if role:
        meta["role"] = role
    elif slot == 0:
        meta.setdefault("role", "host")
        meta.setdefault("name", "Host")
    _slot_meta[slot] = meta


def next_empty_slot() -> int:
    """Guests occupy seats 1–3. Slot 0 is always host."""
    for i in range(1, MAX_PLAYERS):
        if not _slot_lock[i]:
            return i
    return MAX_PLAYERS - 1


def on_join_accepted(client_id: str = "", name: str = "", role: str = "guest", uuid: str = "") -> Dict[str, Any]:
    arm_late_join()
    slot = next_empty_slot()
    if client_id or name:
        note_client(slot, client_id=client_id, name=name, role=role or "guest", uuid=uuid)
    note_client(0, role="host", name="Host")
    return apply("joinack", force=True)


def set_slot_role(slot: int, role: str) -> Dict[str, Any]:
    """Host toggles a seat between a real P2–P4 pad and a buddy who shares P1.

    A buddy seat is metadata only: the buddy device never creates a Sunshine
    gamepad, so the pad slot lock is untouched. Sunshine input comes from the
    host phone's merged report.
    """
    role = (role or "guest").strip().lower()
    if role not in ("guest", "buddy"):
        return {"ok": False, "error": "bad_role"}
    if slot <= 0 or slot >= MAX_PLAYERS:
        return {"ok": False, "error": "bad_slot"}
    note_client(slot, role=role)
    logging.info("couch_coop set_slot_role slot=%s role=%s", slot, role)
    return {"ok": True, "slot": slot, "role": role, "players": status().get("players")}


def set_role_for_client(client_id: str, role: str) -> Dict[str, Any]:
    client_id = (client_id or "").strip()
    if not client_id:
        return {"ok": False, "error": "missing_client"}
    for i in range(1, MAX_PLAYERS):
        meta = _slot_meta[i]
        if client_id in ((meta.get("clientId") or ""), (meta.get("uuid") or "")):
            return set_slot_role(i, role)
    return {"ok": False, "error": "not_seated"}


def host_swap(order: List[int]) -> Dict[str, Any]:
    """Host-only explicit P1–P4 remap. The one time swapping live players is allowed."""
    global _slot_lock, _slot_meta
    with _lock:
        new_lock = remap_slots(_slot_lock, order)
        new_meta = [{} for _ in range(MAX_PLAYERS)]
        for new_i, old_i in enumerate(list(order)[:MAX_PLAYERS]):
            try:
                idx = int(old_i)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < MAX_PLAYERS:
                new_meta[new_i] = dict(_slot_meta[idx])
        _slot_lock = new_lock
        _slot_meta = new_meta
    logging.info("couch_coop host_swap order=%s lock=%s", order, _slot_lock)
    return apply("host_swap", force=True)


def on_sunshine_hint(line: str) -> Optional[Dict[str, Any]]:
    low = line.lower()
    if re.search(r"gamepad\s+[1-3]\b", low) or re.search(r"active sessions:\s*[2-9]", low):
        arm_late_join()
        return apply("sunshine_log")
    if "gamepad 0" in low and (stream_active() or armed()):
        # Host pad blip — hide clones / fill empty only; do not reshuffle.
        return apply("sunshine_log")
    return None


def status() -> Dict[str, Any]:
    pads = read_live_pads()
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
        "max_players": MAX_PLAYERS,
        "slot_lock": list(_slot_lock),
        "players": [
            {
                "player": i + 1,
                "slot": i,
                "key": _slot_lock[i] if i < len(_slot_lock) else None,
                "name": (_slot_meta[i].get("name") if i < len(_slot_meta) else "") or "",
                "role": (_slot_meta[i].get("role") if i < len(_slot_meta) else "") or "",
                "clientId": (_slot_meta[i].get("clientId") if i < len(_slot_meta) else "") or "",
                "uuid": (_slot_meta[i].get("uuid") if i < len(_slot_meta) else "") or "",
            }
            for i in range(MAX_PLAYERS)
        ],
        "sunshine": [
            {"name": p.name, "key": pad_key(p), "nodes": p.nodes, "input": p.input_n}
            for p in sunshine_pads(pads)
        ],
        "steam_slots": steam_slots_from_clones(pads),
        "junk": [{"name": p.name, "nodes": p.js_nodes} for p in pads if p.kind == "junk"],
        "runtime": saved,
        "verify": (
            "Sunshine pads stay in join-order seats (P1–P4). Steam clones 28de:11ff "
            "should be mode 000 (ls -l /dev/input/js*). Host Swap is the only remap. "
            "HarbourMasters still binds all SDL pads to Port 1."
        ),
    }


class CouchCoopWatch:
    """Hide clones and fill empty seats. Never reshuffle occupied P1–P4."""

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
        last_keys: List[str] = []
        while not self._stop.is_set():
            try:
                if stream_active() or armed():
                    pads = read_live_pads()
                    keys = _live_keys(pads)
                    if keys != last_keys:
                        # New/missing pad: fill empty or mark empty. Do not swap occupied seats.
                        apply("pad_arrival", force=True)
                        last_keys = keys
                    else:
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
