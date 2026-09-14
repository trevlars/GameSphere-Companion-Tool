"""Local Steam playtime for GameSphere — no Web API key.

Reads `userdata/*/config/localconfig.vdf` (Playtime minutes + LastPlayed),
`userdata/*/7/remote/sharedconfig.vdf` (LastPlayed), and shortcut
`LastPlayTime` from `shortcuts.vdf`. Covers Steam-owned titles and Non-Steam
shortcuts (32-bit appid and 64-bit steam://rungameid).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import vdf
except ImportError:  # pragma: no cover
    vdf = None  # type: ignore


_RUNGAME = re.compile(r"rungameid/(\d+)", re.I)
_PLATFORM_SUFFIX = re.compile(
    r"\s*\((Switch(?:\s*2)?|Wii\s*U|Wii|GameCube|N64|SNES|NES|PS[1-5]|PSP|Vita|"
    r"Xbox(?:\s*(?:360|One|Series[^)]*))?|3DS|DS|Genesis|Dreamcast|Arcade|PC)\)\s*$",
    re.I,
)

# Sunshine extra keys — ignored by the host, read by the client bridge.
PLAYTIME_MINUTES_KEY = "_gamesphere_playtime_minutes"
LAST_PLAYED_KEY = "_gamesphere_last_played"


def _u32(value: int) -> int:
    return int(value) & 0xFFFFFFFF


def _shortcut_rungameid(short_appid: int) -> str:
    return str((int(short_appid) << 32) | 0x02000000)


def _as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text or not re.fullmatch(r"-?\d+", text):
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _walk_ci(node: Any, *names: str) -> Any:
    cur = node
    for name in names:
        if not isinstance(cur, dict):
            return None
        want = name.casefold()
        nxt = None
        for key, val in cur.items():
            if str(key).casefold() == want:
                nxt = val
                break
        if nxt is None:
            return None
        cur = nxt
    return cur


def _steam_root_from_library_vdf(library_vdf_path: str) -> str:
    steamapps = os.path.dirname(os.path.abspath(library_vdf_path or ""))
    return os.path.dirname(steamapps)


def _extract_steam_app_id(cmd: str) -> Optional[str]:
    if not cmd:
        return None
    match = _RUNGAME.search(cmd)
    if match:
        return match.group(1)
    return None


def app_steam_app_id(app: Dict[str, Any]) -> Optional[str]:
    aid = _extract_steam_app_id(str(app.get("cmd") or ""))
    if aid:
        return aid
    detached = app.get("detached")
    if isinstance(detached, list):
        for item in detached:
            aid = _extract_steam_app_id(str(item))
            if aid:
                return aid
    elif isinstance(detached, str) and detached.strip():
        return _extract_steam_app_id(detached.strip())
    return None


def _alias_ids(app_id: str) -> List[str]:
    """32-bit, signed-decimal, and 64-bit shortcut forms for one Steam id."""
    text = str(app_id or "").strip()
    if not text.isdigit():
        return [text] if text else []
    value = int(text)
    aliases = {text, str(value)}
    if value > 0xFFFFFFFF:
        short = value >> 32
        aliases.add(str(short))
        aliases.add(str(_u32(short)))
        aliases.add(str(_shortcut_rungameid(short)))
    else:
        short = _u32(value)
        aliases.add(str(short))
        signed = short - 0x100000000 if short >= 0x80000000 else short
        aliases.add(str(signed))
        aliases.add(str(_shortcut_rungameid(short)))
    return [a for a in aliases if a]


def _merge_record(dest: Dict[str, Dict[str, Any]], app_id: str, minutes: Optional[int], last_played: Optional[int], name: str = "") -> None:
    if not app_id:
        return
    mins = minutes if minutes is not None and minutes > 0 else 0
    last = last_played if last_played is not None and last_played > 0 else 0
    if mins <= 0 and last <= 0 and not name:
        return
    for key in _alias_ids(app_id):
        row = dest.setdefault(key, {"minutes": 0, "lastPlayed": 0, "name": ""})
        if mins > int(row.get("minutes") or 0):
            row["minutes"] = mins
        if last > int(row.get("lastPlayed") or 0):
            row["lastPlayed"] = last
        if name and not row.get("name"):
            row["name"] = name


def _parse_apps_block_fallback(text: str) -> Dict[str, Any]:
    """Minimal apps { id { Playtime LastPlayed } } reader when the vdf package is missing."""
    apps: Dict[str, Any] = {}
    idx = text.lower().find('"apps"')
    if idx < 0:
        return apps
    body = text[idx:]
    current_id: Optional[str] = None
    current: Dict[str, str] = {}
    for raw in body.splitlines():
        line = raw.strip()
        if current_id and line == "}":
            apps[current_id] = current
            current_id = None
            current = {}
            continue
        id_match = re.match(r'"(\d+)"\s*$', line)
        if id_match and current_id is None:
            current_id = id_match.group(1)
            current = {}
            continue
        kv = re.match(r'"([^"]+)"\s+"([^"]*)"', line)
        if kv and current_id:
            current[kv.group(1)] = kv.group(2)
    return apps


def _load_text_vdf(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return None
    if vdf:
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                with open(path, "r", encoding=enc, errors="replace") as handle:
                    data = vdf.load(handle)
                return data if isinstance(data, dict) else None
            except Exception:
                continue
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None
    apps = _parse_apps_block_fallback(text)
    if not apps:
        logging.debug("Could not parse VDF %s", path)
        return None
    return {"UserLocalConfigStore": {"Software": {"Valve": {"Steam": {"apps": apps}}}}}


def _apps_node(root: Any) -> Dict[str, Any]:
    for path in (
        ("UserLocalConfigStore", "Software", "Valve", "Steam", "apps"),
        ("UserRoamingConfigStore", "Software", "Valve", "Steam", "apps"),
        ("UserRoamingConfigStore", "Software", "Valve", "Steam", "Apps"),
        ("UserLocalConfigStore", "Software", "valve", "Steam", "apps"),
    ):
        node = _walk_ci(root, *path)
        if isinstance(node, dict) and node:
            return node
    # Some builds nest Software/Valve one level deeper.
    if isinstance(root, dict):
        for top in root.values():
            node = _walk_ci(top, "Software", "Valve", "Steam", "apps")
            if isinstance(node, dict) and node:
                return node
    return {}


def _minutes_from_app_block(block: Any) -> Optional[int]:
    if not isinstance(block, dict):
        return None
    for key in ("Playtime", "playtime", "PlaytimeForever", "playtime_forever"):
        minutes = _as_int(block.get(key))
        if minutes is not None and minutes > 0:
            return minutes
    return None


def _last_played_from_app_block(block: Any) -> Optional[int]:
    if not isinstance(block, dict):
        return None
    for key in ("LastPlayed", "lastplayed", "LastPlayTime", "lastplaytime"):
        last = _as_int(block.get(key))
        if last is not None and last > 0:
            return last
    return None


def _ingest_apps_node(dest: Dict[str, Dict[str, Any]], apps: Dict[str, Any]) -> None:
    for raw_id, block in apps.items():
        aid = str(raw_id).strip()
        if not aid:
            continue
        _merge_record(
            dest,
            aid,
            _minutes_from_app_block(block),
            _last_played_from_app_block(block),
        )


def _userdata_dirs(steam_root: str) -> Iterable[str]:
    userdata = os.path.join(steam_root, "userdata")
    if not os.path.isdir(userdata):
        return
    for entry in sorted(os.listdir(userdata)):
        if not entry.isdigit() or entry == "0":
            continue
        yield os.path.join(userdata, entry)


def load_localconfig_playtimes(steam_root: str) -> Dict[str, Dict[str, Any]]:
    """Merge Playtime / LastPlayed from every Steam user's local + shared config."""
    dest: Dict[str, Dict[str, Any]] = {}
    if not steam_root or not os.path.isdir(steam_root):
        return dest
    files_read = 0
    for user_dir in _userdata_dirs(steam_root):
        for rel in (
            os.path.join("config", "localconfig.vdf"),
            os.path.join("7", "remote", "sharedconfig.vdf"),
        ):
            path = os.path.join(user_dir, rel)
            data = _load_text_vdf(path)
            if not data:
                continue
            files_read += 1
            _ingest_apps_node(dest, _apps_node(data))
    if files_read:
        logging.info(
            "Steam local playtime: %d title(s) from %d config file(s)",
            len({k for k in dest if dest[k].get("minutes")}),
            files_read,
        )
    return dest


def load_shortcut_playtimes(steam_root: str) -> Dict[str, Dict[str, Any]]:
    """LastPlayTime (+ name) from shortcuts.vdf. Minutes stay 0 unless localconfig has them."""
    dest: Dict[str, Dict[str, Any]] = {}
    if not vdf or not steam_root:
        return dest
    for user_dir in _userdata_dirs(steam_root):
        shortcuts_path = os.path.join(user_dir, "config", "shortcuts.vdf")
        if not os.path.isfile(shortcuts_path):
            continue
        try:
            with open(shortcuts_path, "rb") as handle:
                data = vdf.binary_load(handle)
        except Exception as exc:
            logging.warning("Failed to parse shortcuts.vdf %s: %s", shortcuts_path, exc)
            continue
        shortcuts = data.get("shortcuts") or {}
        if not isinstance(shortcuts, dict):
            continue
        for item in shortcuts.values():
            if not isinstance(item, dict):
                continue
            raw_id = item.get("appid")
            if raw_id is None:
                raw_id = item.get("AppID") or item.get("appId")
            if raw_id is None:
                continue
            try:
                short_appid = _u32(int(raw_id))
            except (TypeError, ValueError):
                continue
            name = (item.get("appname") or item.get("AppName") or "").strip()
            last = None
            for key in ("LastPlayTime", "lastplaytime", "LastPlayed", "lastplayed"):
                last = _as_int(item.get(key))
                if last:
                    break
            _merge_record(dest, str(short_appid), None, last, name)
            _merge_record(dest, _shortcut_rungameid(short_appid), None, last, name)
    return dest


def _session_last_played() -> Dict[str, int]:
    """Most recent Sunshine session end per game name (seconds). Not duration."""
    try:
        from host_tuning.session_telemetry import load_sessions
    except Exception:
        return {}
    by_name: Dict[str, int] = {}
    try:
        sessions = load_sessions()
    except Exception:
        return {}
    for session in sessions:
        if not isinstance(session, dict):
            continue
        end_raw = session.get("end_time") or session.get("start_time") or ""
        last = 0
        if isinstance(end_raw, (int, float)):
            last = int(end_raw)
        elif isinstance(end_raw, str) and end_raw:
            try:
                from datetime import datetime

                last = int(datetime.fromisoformat(end_raw.replace("Z", "+00:00")).timestamp())
            except ValueError:
                last = 0
        if last <= 0:
            continue
        games = session.get("games") or []
        if isinstance(games, str):
            games = [games]
        for name in games:
            key = str(name or "").strip()
            if key and last > by_name.get(key, 0):
                by_name[key] = last
    return by_name


def collect_playtimes(library_vdf_path: str) -> Dict[str, Dict[str, Any]]:
    steam_root = _steam_root_from_library_vdf(library_vdf_path)
    dest = load_localconfig_playtimes(steam_root)
    for key, row in load_shortcut_playtimes(steam_root).items():
        _merge_record(
            dest,
            key,
            int(row.get("minutes") or 0) or None,
            int(row.get("lastPlayed") or 0) or None,
            str(row.get("name") or ""),
        )
    return dest


def _name_key(name: str) -> str:
    return _PLATFORM_SUFFIX.sub("", name or "").strip().casefold()


def lookup_record(
    records: Dict[str, Dict[str, Any]],
    steam_app_id: Optional[str],
    name: str = "",
) -> Optional[Dict[str, Any]]:
    if steam_app_id:
        for key in _alias_ids(steam_app_id):
            row = records.get(key)
            if row:
                return row
    needle = _name_key(name)
    if not needle:
        return None
    best: Optional[Dict[str, Any]] = None
    for row in records.values():
        row_name = _name_key(str(row.get("name") or ""))
        if row_name == needle:
            if not best or int(row.get("minutes") or 0) > int(best.get("minutes") or 0):
                best = row
    return best


def stamp_apps(apps: List[Dict[str, Any]], records: Dict[str, Dict[str, Any]]) -> int:
    """Write playtime extras onto Sunshine apps. Returns how many apps changed."""
    changed = 0
    session_last = _session_last_played()
    for app in apps:
        if not isinstance(app, dict):
            continue
        name = str(app.get("name") or "").strip()
        row = lookup_record(records, app_steam_app_id(app), name)
        minutes = int(row.get("minutes") or 0) if row else 0
        last = int(row.get("lastPlayed") or 0) if row else 0
        if last <= 0:
            last = int(session_last.get(name) or 0)
        new_minutes = minutes if minutes > 0 else None
        new_last = last if last > 0 else None
        old_minutes = app.get(PLAYTIME_MINUTES_KEY)
        old_last = app.get(LAST_PLAYED_KEY)
        if new_minutes is None:
            if PLAYTIME_MINUTES_KEY in app:
                app.pop(PLAYTIME_MINUTES_KEY, None)
                changed += 1
        elif old_minutes != new_minutes:
            app[PLAYTIME_MINUTES_KEY] = new_minutes
            changed += 1
        if new_last is None:
            if LAST_PLAYED_KEY in app:
                app.pop(LAST_PLAYED_KEY, None)
                changed += 1
        elif old_last != new_last:
            app[LAST_PLAYED_KEY] = new_last
            changed += 1
    return changed


def _apps_from_json(apps_json_path: str) -> List[Dict[str, Any]]:
    if not apps_json_path or not os.path.isfile(apps_json_path):
        return []
    try:
        with open(apps_json_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    apps = data.get("apps") if isinstance(data, dict) else None
    return [a for a in (apps or []) if isinstance(a, dict)]


def playtimes_payload(apps_json_path: str, library_vdf_path: str = "") -> Dict[str, Any]:
    """Bridge JSON: list of games plus id/name indexes for the iOS client."""
    if not library_vdf_path:
        try:
            from platform_paths import detect_paths

            detected = detect_paths()
            if detected:
                library_vdf_path = detected.steam_library_vdf
        except Exception:
            library_vdf_path = ""
    records = collect_playtimes(library_vdf_path) if library_vdf_path else {}
    session_last = _session_last_played()
    games: List[Dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_ids: set[str] = set()

    def _append(name: str, steam_id: str, minutes: int, last: int, sunshine_id: str = "") -> None:
        if minutes <= 0 and last <= 0:
            return
        aliases = _alias_ids(steam_id) if steam_id else []
        name_key = _name_key(name)
        if steam_id and any(a in seen_ids for a in aliases):
            return
        if name_key and name_key in seen_names and not steam_id:
            return
        if name_key:
            seen_names.add(name_key)
        seen_ids.update(aliases)
        row: Dict[str, Any] = {"minutes": minutes, "lastPlayed": last}
        if name:
            row["name"] = name
        if steam_id:
            row["steamAppId"] = steam_id
            shorts = [a for a in aliases if a.isdigit() and int(a) <= 0xFFFFFFFF]
            if shorts:
                row["shortAppId"] = shorts[0]
        if sunshine_id:
            row["sunshineId"] = sunshine_id
        games.append(row)

    for app in _apps_from_json(apps_json_path):
        name = str(app.get("name") or "").strip()
        steam_id = app_steam_app_id(app) or ""
        sunshine_id = str(app.get("uuid") or app.get("id") or "").strip()
        stamped_min = _as_int(app.get(PLAYTIME_MINUTES_KEY)) or 0
        stamped_last = _as_int(app.get(LAST_PLAYED_KEY)) or 0
        row = lookup_record(records, steam_id, name)
        minutes = max(stamped_min, int(row.get("minutes") or 0) if row else 0)
        last = max(stamped_last, int(row.get("lastPlayed") or 0) if row else 0, int(session_last.get(name) or 0))
        _append(name, steam_id, minutes, last, sunshine_id)

    # Steam / shortcut titles not yet (or no longer) named in apps.json.
    for key, row in records.items():
        name = str(row.get("name") or "").strip()
        minutes = int(row.get("minutes") or 0)
        last = int(row.get("lastPlayed") or 0)
        _append(name, str(key), minutes, last)

    return {"games": games}


def playtimes_json(apps_json_path: str, library_vdf_path: str = "") -> str:
    return json.dumps(playtimes_payload(apps_json_path, library_vdf_path), separators=(",", ":"))
