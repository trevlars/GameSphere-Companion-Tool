"""
Multi-store game discovery for Windows hosts.

Store detection and launch-command patterns are adapted from
StreamTweak (https://github.com/FoggyBytes/StreamTweak) by FoggyBytes —
GPL-3.0, used with attribution in README.md.
"""

from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

import logging

if sys.platform == "win32":
    import winreg

STEAM_TOOL_EXCLUSIONS = {
    "steamworks common redistributables",
    "steamvr",
    "steam linux runtime",
    "proton experimental",
    "steam client",
}

BNET_SKIP_IDS = {"bna", "agent", "bnetlauncher", "bnet"}

UBISOFT_SYSTEM_EXE = (
    "ubisoft",
    "uplay",
    "crashreport",
    "uninst",
    "upc.exe",
    "easyanticheat.exe",
    "vcredist_x64.exe",
)

EA_SYSTEM_EXE_PARTS = (
    "cleanup",
    "uninstall",
    "eadesktop",
    "eainstaller",
    "vcredist",
    "directx",
)


def store_key(store: str, identifier: str) -> str:
    return f"{store.lower()}:{identifier}"


def _stable_path_id(path: str) -> str:
    """Deterministic id for a game folder.

    ``hash()`` is salted per process, so using it here gave a title a new
    store_key on every run — the importer then removed the old tile (deleting
    its artwork) and re-added an identical one.
    """
    import hashlib

    normalized = _normalize_win_path(path).lower().encode("utf-8", errors="replace")
    return hashlib.sha1(normalized).hexdigest()[:16]


def _normalize_win_path(path: str) -> str:
    if not path:
        return path
    path = os.path.normpath(path)
    if len(path) >= 3 and path[1] == ":":
        path = path[0].upper() + path[1:]
    return path


def build_windows_display_name_lookup() -> List[Tuple[str, str]]:
    """InstallLocation → DisplayName from Windows Uninstall registry."""
    if sys.platform != "win32":
        return []
    result: List[Tuple[str, str]] = []
    hives = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, subpath in hives:
        try:
            with winreg.OpenKey(hive, subpath) as hive_key:
                for i in range(winreg.QueryInfoKey(hive_key)[0]):
                    try:
                        subname = winreg.EnumKey(hive_key, i)
                        with winreg.OpenKey(hive_key, subname) as app_key:
                            display = winreg.QueryValueEx(app_key, "DisplayName")[0]
                            install = winreg.QueryValueEx(app_key, "InstallLocation")[0]
                            try:
                                if winreg.QueryValueEx(app_key, "SystemComponent")[0] == 1:
                                    continue
                            except OSError:
                                pass
                            if not display or not install:
                                continue
                            norm = _normalize_win_path(install)
                            if len(norm) > 3:
                                result.append((norm + os.sep, display))
                    except OSError:
                        continue
        except OSError:
            continue
    result.sort(key=lambda item: len(item[0]), reverse=True)
    return result


def resolve_display_name(install_path: str, fallback: str, lookup: List[Tuple[str, str]]) -> str:
    if not install_path or not lookup:
        return fallback
    norm = _normalize_win_path(install_path)
    if not norm.endswith(os.sep):
        norm += os.sep
    for prefix, name in lookup:
        if norm.lower().startswith(prefix.lower()):
            return name
    return fallback


def discover_xbox_roots(extra_folders: str = "") -> List[str]:
    """Find Xbox/Game Pass install roots via .GamingRoot and optional overrides."""
    roots: List[str] = []
    seen = set()

    def add(path: str) -> None:
        path = _normalize_win_path(path.strip())
        if path and os.path.isdir(path):
            key = path.lower()
            if key not in seen:
                seen.add(key)
                roots.append(path)

    if extra_folders:
        for part in extra_folders.split(","):
            add(part)

    if sys.platform != "win32":
        return roots

    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{letter}:\\"
        if not os.path.isdir(drive):
            continue
        gaming_root = os.path.join(drive, ".GamingRoot")
        if not os.path.isfile(gaming_root):
            continue
        try:
            with open(gaming_root, "rb") as fh:
                data = fh.read()
            if len(data) <= 8 or data[0:4] != b"RGBX":
                continue
            rel = data[8:].decode("utf-16-le", errors="ignore").strip("\x00")
            if rel:
                add(os.path.join(drive, rel))
        except OSError:
            continue

    if not roots and sys.platform == "win32":
        add("C:\\XboxGames")
    return roots


def load_gog_games(display_lookup: Optional[List[Tuple[str, str]]] = None) -> Dict[str, Dict]:
    if sys.platform != "win32":
        return {}
    installed: Dict[str, Dict] = {}
    lookup = display_lookup or build_windows_display_name_lookup()
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games") as games_key:
            for i in range(winreg.QueryInfoKey(games_key)[0]):
                product_id = winreg.EnumKey(games_key, i)
                try:
                    with winreg.OpenKey(games_key, product_id) as game_key:
                        name = winreg.QueryValueEx(game_key, "gameName")[0]
                        exe = winreg.QueryValueEx(game_key, "exe")[0]
                except OSError:
                    continue
                if not name or not exe or not os.path.isfile(exe):
                    continue
                install_dir = os.path.dirname(exe)
                name = resolve_display_name(install_dir, name, lookup)
                key = store_key("gog", product_id)
                installed[key] = {
                    "name": name,
                    "store": "GOG",
                    "store_id": product_id,
                    "cmd": f'"{exe}"',
                    "detached": "",
                    "exe_path": exe,
                    "store_key": key,
                }
    except OSError:
        pass
    logging.info("Found %d installed GOG games", len(installed))
    return installed


def _load_ubisoft_names() -> Dict[str, str]:
    names: Dict[str, str] = {}
    config_path = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Ubisoft Game Launcher",
        "cache",
        "configuration",
        "configurations",
    )
    if not os.path.isfile(config_path):
        return names
    try:
        with open(config_path, "rb") as fh:
            content = fh.read().decode("iso-8859-1", errors="ignore")
        for section in re.split(r"(?=\bconfiguration_id\b)", content):
            id_match = re.search(r"configuration_id:\s*(\d+)", section)
            if not id_match:
                continue
            name_match = re.search(r"localizations:.*?default:.*?(?:^|\s)name:\s*(.+?)(?:\r?\n|$)", section, re.S)
            if name_match:
                names[id_match.group(1)] = name_match.group(1).strip()
    except OSError:
        pass
    return names


def _is_ubisoft_system_exe(filename: str) -> bool:
    fl = filename.lower()
    return any(
        fl.startswith(prefix) if not prefix.endswith(".exe") else fl == prefix
        for prefix in UBISOFT_SYSTEM_EXE
    )


def load_ubisoft_games(display_lookup: Optional[List[Tuple[str, str]]] = None) -> Dict[str, Dict]:
    if sys.platform != "win32":
        return {}
    installed: Dict[str, Dict] = {}
    lookup = display_lookup or build_windows_display_name_lookup()
    ubisoft_names = _load_ubisoft_names()
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"
        ) as installs_key:
            for i in range(winreg.QueryInfoKey(installs_key)[0]):
                install_id = winreg.EnumKey(installs_key, i)
                try:
                    with winreg.OpenKey(installs_key, install_id) as install_key:
                        install_dir = winreg.QueryValueEx(install_key, "InstallDir")[0]
                except OSError:
                    continue
                if not install_dir or not os.path.isdir(install_dir):
                    continue
                exes = []
                try:
                    for fname in os.listdir(install_dir):
                        if not fname.lower().endswith(".exe") or _is_ubisoft_system_exe(fname):
                            continue
                        path = os.path.join(install_dir, fname)
                        if os.path.isfile(path):
                            exes.append((os.path.getsize(path), path))
                except OSError:
                    continue
                if not exes:
                    continue
                exe = sorted(exes, reverse=True)[0][1]
                name = ubisoft_names.get(install_id)
                if not name:
                    name = os.path.splitext(os.path.basename(exe))[0]
                name = resolve_display_name(install_dir, name, lookup)
                key = store_key("ubisoft", install_id)
                installed[key] = {
                    "name": name,
                    "store": "Ubisoft Connect",
                    "store_id": install_id,
                    "cmd": f'"{exe}"',
                    "detached": "",
                    "exe_path": exe,
                    "store_key": key,
                }
    except OSError:
        pass
    logging.info("Found %d installed Ubisoft Connect games", len(installed))
    return installed


def _find_battlenet_client() -> Optional[str]:
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Battle.net",
        ) as key:
            loc = winreg.QueryValueEx(key, "InstallLocation")[0]
            if loc:
                exe = os.path.join(loc, "Battle.net.exe")
                if os.path.isfile(exe):
                    return exe
    except OSError:
        pass
    fallback = os.path.join(
        os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
        "Battle.net",
        "Battle.net.exe",
    )
    return fallback if os.path.isfile(fallback) else None


def load_battlenet_games() -> Dict[str, Dict]:
    if sys.platform != "win32":
        return {}
    agg_path = os.path.join(
        os.environ.get("ProgramData", "C:\\ProgramData"),
        "Battle.net",
        "Agent",
        "aggregate.json",
    )
    if not os.path.isfile(agg_path):
        return {}
    installed: Dict[str, Dict] = {}
    client_exe: Optional[str] = None
    try:
        with open(agg_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for item in data.get("installed") or []:
            uid = (item.get("product_id") or "").strip()
            if not uid or uid.lower() in BNET_SKIP_IDS:
                continue
            name = (item.get("name") or uid).strip()
            icon_path = (item.get("icon_path") or "").replace("/", os.sep)
            if icon_path and os.path.isfile(icon_path):
                exe = icon_path
            else:
                client_exe = client_exe or _find_battlenet_client()
                if not client_exe:
                    continue
                exe = client_exe
            key = store_key("battlenet", uid)
            installed[key] = {
                "name": name,
                "store": "Battle.net",
                "store_id": uid,
                "cmd": f'"{exe}"',
                "detached": "",
                "exe_path": exe,
                "store_key": key,
            }
    except (OSError, json.JSONDecodeError) as exc:
        logging.debug("Battle.net scan failed: %s", exc)
    logging.info("Found %d installed Battle.net games", len(installed))
    return installed


def _read_ea_content_id(install_path: str) -> Optional[str]:
    xml_path = os.path.join(install_path, "__Installer", "installerdata.xml")
    if not os.path.isfile(xml_path):
        return None
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for tag in ("contentID", "ContentID", "productid"):
            el = root.find(f".//{tag}")
            if el is not None and (el.text or "").strip():
                return el.text.strip()
    except ET.ParseError:
        pass
    return None


def _is_ea_system_exe(filename: str) -> bool:
    fl = filename.lower()
    return any(part in fl for part in EA_SYSTEM_EXE_PARTS)


def load_ea_games(display_lookup: Optional[List[Tuple[str, str]]] = None) -> Dict[str, Dict]:
    if sys.platform != "win32":
        return {}
    installed: Dict[str, Dict] = {}
    lookup = display_lookup or build_windows_display_name_lookup()
    seen_paths: set = set()
    hives = [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_32KEY", 0)),
        (winreg.HKEY_CURRENT_USER, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)),
        (winreg.HKEY_CURRENT_USER, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_32KEY", 0)),
    ]
    for hive, access in hives:
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0, access) as uninstall_key:
                for i in range(winreg.QueryInfoKey(uninstall_key)[0]):
                    try:
                        subname = winreg.EnumKey(uninstall_key, i)
                        with winreg.OpenKey(uninstall_key, subname, 0, access) as app_key:
                            uninstall = winreg.QueryValueEx(app_key, "UninstallString")[0]
                            display = winreg.QueryValueEx(app_key, "DisplayName")[0]
                            install_path = winreg.QueryValueEx(app_key, "InstallLocation")[0]
                    except OSError:
                        continue
                    if not uninstall or "eainstaller" not in uninstall.lower():
                        continue
                    if "cleanup.exe" not in uninstall.lower():
                        continue
                    if not display or not install_path or not os.path.isdir(install_path):
                        continue
                    norm = _normalize_win_path(install_path).lower()
                    if norm in seen_paths:
                        continue
                    seen_paths.add(norm)
                    exes = []
                    try:
                        for fname in os.listdir(install_path):
                            if not fname.lower().endswith(".exe") or _is_ea_system_exe(fname):
                                continue
                            path = os.path.join(install_path, fname)
                            if os.path.isfile(path):
                                exes.append((os.path.getsize(path), path))
                    except OSError:
                        continue
                    exe = sorted(exes, reverse=True)[0][1] if exes else install_path
                    content_id = _read_ea_content_id(install_path) or _stable_path_id(install_path)
                    name = resolve_display_name(install_path, display, lookup)
                    key = store_key("ea", content_id)
                    installed[key] = {
                        "name": name,
                        "store": "EA App",
                        "store_id": content_id,
                        "cmd": f'"{exe}"',
                        "detached": "",
                        "exe_path": exe,
                        "store_key": key,
                    }
        except OSError:
            continue
    logging.info("Found %d installed EA App games", len(installed))
    return installed


def enhance_epic_entry(data: dict) -> Optional[dict]:
    """Add StreamTweak-style Epic launch_id and catalog metadata to a manifest dict."""
    if data.get("bIsApplication") is False:
        return None
    app_name = data.get("AppName")
    display_name = data.get("DisplayName") or app_name
    if not app_name:
        return None
    namespace = (data.get("CatalogNamespace") or "").strip()
    catalog_id = (data.get("CatalogItemId") or "").strip()
    if namespace and catalog_id:
        launch_id = f"{namespace}:{catalog_id}:{app_name}"
    else:
        launch_id = app_name
    install_location = data.get("InstallLocation") or ""
    launch_exe = data.get("LaunchExecutable") or ""
    exe_path = ""
    if install_location and launch_exe:
        candidate = os.path.join(install_location, launch_exe)
        if os.path.isfile(candidate):
            exe_path = candidate
    return {
        "name": display_name,
        "app_name": app_name,
        "launch_id": launch_id,
        "catalog_item_id": catalog_id or None,
        "exe_path": exe_path,
        "store": "Epic Games",
        "store_key": store_key("epic", app_name),
    }


def epic_launch_detached(launch_id: str) -> str:
    return f"com.epicgames.launcher://apps/{launch_id}?action=launch&silent=true"


def load_all_third_party_stores(
    epic_manifests_path: str = "",
    xbox_folders: str = "",
) -> Dict[str, Dict]:
    """Merge GOG, Ubisoft, Battle.net, EA, enhanced Epic, and Xbox scans."""
    lookup = build_windows_display_name_lookup()
    merged: Dict[str, Dict] = {}
    for loader in (
        lambda: load_gog_games(lookup),
        lambda: load_ubisoft_games(lookup),
        load_battlenet_games,
        lambda: load_ea_games(lookup),
    ):
        merged.update(loader())
    return merged


def parse_xbox_config(config_path: str, game_root: str) -> Optional[Dict]:
    """Parse MicrosoftGame.config; return metadata including shell launch id when possible."""
    ns = {"g": "http://schemas.microsoft.com/Gaming/2020/08/Game"}

    def find_el(root, tag):
        el = root.find(f"g:{tag}", ns)
        return el if el is not None else root.find(tag)

    try:
        tree = ET.parse(config_path)
        root = tree.getroot()
        identity = find_el(root, "Identity")
        package_name = identity.get("Name") if identity is not None else None
        shell = find_el(root, "ShellVisuals")
        display_name = shell.get("DefaultDisplayName") if shell is not None else None
        if display_name and display_name.lower().startswith("ms-resource:"):
            display_name = None
        exec_list = find_el(root, "ExecutableList")
        exe_name = None
        if exec_list is not None:
            for exe_el in exec_list.findall("g:Executable", ns) + exec_list.findall("Executable"):
                if exe_el.get("IsDevOnly", "false").lower() == "true":
                    continue
                exe_name = exe_el.get("Name")
                if exe_name:
                    break
        config_dir = os.path.dirname(config_path)
        app_id = None
        for manifest_name in ("appxmanifest.xml", "AppxManifest.xml"):
            manifest_path = os.path.join(config_dir, manifest_name)
            if not os.path.isfile(manifest_path):
                continue
            try:
                manifest = ET.parse(manifest_path)
                for el in manifest.getroot().iter():
                    if el.tag.endswith("Application") and el.get("Id"):
                        app_id = el.get("Id")
                        break
            except ET.ParseError:
                pass
            break
        store_id = None
        if package_name and app_id:
            store_id = f"{package_name}!{app_id}"
        elif package_name:
            store_id = package_name
        if not display_name:
            display_name = os.path.basename(game_root.rstrip(os.sep))
        return {
            "display_name": display_name.strip(),
            "exe_name": exe_name,
            "store_id": store_id,
            "config_dir": config_dir,
        }
    except ET.ParseError:
        return None
