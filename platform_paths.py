"""Auto-detect Steam and Sunshine paths on Linux (Bazzite, Steam Deck), macOS, and Windows."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class PlatformPaths:
    steam_library_vdf: str
    sunshine_apps_json: str
    sunshine_grids_folder: str
    steam_exe: str
    steam_mode: str  # native | flatpak | windows | macos
    sunshine_restart: str  # systemd | flatpak | exe
    host_label: str


def _expand(path: str) -> str:
    return os.path.normpath(os.path.expanduser(os.path.expandvars(path)))


def _first_existing(candidates: List[str]) -> Optional[str]:
    for candidate in candidates:
        path = _expand(candidate)
        if os.path.exists(path):
            return path
    return None


def _flatpak_installed(app_id: str) -> bool:
    try:
        result = subprocess.run(
            ["flatpak", "list", "--app", "--columns=application"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and app_id in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _systemd_user_unit_active(unit: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "active"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _detect_host_label() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            content = handle.read().lower()
        if "bazzite" in content:
            return "bazzite"
        if "steamos" in content or "steam deck" in content:
            return "steamos"
    except OSError:
        pass
    if sys_platform_is_linux():
        return "linux"
    if os.name == "nt":
        return "windows"
    if sys_platform_is_darwin():
        return "macos"
    return "unknown"


def sys_platform_is_linux() -> bool:
    import sys

    return sys.platform.startswith("linux")


def sys_platform_is_darwin() -> bool:
    import sys

    return sys.platform == "darwin"


def detect_paths() -> Optional[PlatformPaths]:
    """Return best-effort paths for the current machine, or None if Steam is missing."""
    host_label = _detect_host_label()
    home = os.path.expanduser("~")

    steam_candidates = [
        os.path.join(home, ".local/share/Steam/steamapps/libraryfolders.vdf"),
        os.path.join(
            home,
            ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/libraryfolders.vdf",
        ),
        os.path.join(
            home, "Library/Application Support/Steam/steamapps/libraryfolders.vdf"
        ),
        "C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf",
        "C:/Program Files/Steam/steamapps/libraryfolders.vdf",
    ]
    steam_vdf = _first_existing(steam_candidates)
    if not steam_vdf:
        return None

    sunshine_apps_candidates = [
        os.path.join(home, ".config/sunshine/apps.json"),
        os.path.join(home, ".config/Apollo/apps.json"),
        os.path.join(home, ".config/vibeshine/apps.json"),
        os.path.join(home, ".config/vibepollo/apps.json"),
        os.path.join(
            home, ".var/app/dev.lizardbyte.app.Sunshine/config/sunshine/apps.json"
        ),
        os.path.join(home, "Library/Application Support/Sunshine/apps.json"),
        "C:/Program Files/Sunshine/config/apps.json",
        "C:/Program Files (x86)/Sunshine/config/apps.json",
        "C:/Program Files/Apollo/config/apps.json",
        "C:/Program Files/Vibeshine/config/apps.json",
        "C:/Program Files/Vibepollo/config/apps.json",
    ]
    sunshine_apps = _first_existing(sunshine_apps_candidates)
    if not sunshine_apps:
        return None

    sunshine_dir = os.path.dirname(sunshine_apps)
    grids_candidates = [
        os.path.join(sunshine_dir, "covers"),
        os.path.join(sunshine_dir, "grids"),
        os.path.join(sunshine_dir, "assets"),
        "C:/Sunshine_Thumbnails",
    ]
    grids_folder = _first_existing(grids_candidates) or os.path.join(
        sunshine_dir, "covers"
    )

    steam_mode = "windows"
    steam_exe = ""
    sunshine_restart = "exe"

    if os.name == "nt":
        steam_exe_candidates = [
            "C:/Program Files (x86)/Steam/steam.exe",
            "C:/Program Files/Steam/steam.exe",
        ]
        steam_exe = _first_existing(steam_exe_candidates) or ""
    elif sys_platform_is_darwin():
        steam_mode = "macos"
        steam_exe = _first_existing(
            [
                "/Applications/Steam.app/Contents/MacOS/steam_osx",
                os.path.join(home, "Applications/Steam.app/Contents/MacOS/steam_osx"),
            ]
        ) or shutil.which("steam") or ""
    else:
        flatpak_steam = _flatpak_installed("com.valvesoftware.Steam")
        native_steam = shutil.which("steam")
        if flatpak_steam and ".var/app/com.valvesoftware.Steam" in steam_vdf:
            steam_mode = "flatpak"
            steam_exe = "flatpak"
        elif native_steam:
            steam_mode = "native"
            steam_exe = native_steam
        elif flatpak_steam:
            steam_mode = "flatpak"
            steam_exe = "flatpak"
        else:
            steam_exe = ""

        if _systemd_user_unit_active("sunshine.service"):
            sunshine_restart = "systemd"
        elif _flatpak_installed("dev.lizardbyte.app.Sunshine"):
            sunshine_restart = "flatpak"
        else:
            sunshine_exe = shutil.which("sunshine") or shutil.which("Apollo")
            if sunshine_exe:
                steam_exe = steam_exe or ""
                sunshine_restart = "exe"

    return PlatformPaths(
        steam_library_vdf=steam_vdf,
        sunshine_apps_json=sunshine_apps,
        sunshine_grids_folder=grids_folder,
        steam_exe=steam_exe,
        steam_mode=steam_mode,
        sunshine_restart=sunshine_restart,
        host_label=host_label,
    )


def _host_env_name(apps_json_path: str) -> str:
    low = apps_json_path.lower()
    if "apollo" in low:
        return "apollo"
    if "vibeshine" in low:
        return "vibeshine"
    if "vibepollo" in low:
        return "vibepollo"
    return "sunshine"


def paths_to_env(paths: PlatformPaths) -> Dict[str, str]:
    env = {
        "steam_library_vdf_path": paths.steam_library_vdf,
        "sunshine_apps_json_path": paths.sunshine_apps_json,
        "sunshine_grids_folder": paths.sunshine_grids_folder,
        "HOST": _host_env_name(paths.sunshine_apps_json),
    }
    if paths.steam_exe:
        env["STEAM_EXE_PATH"] = paths.steam_exe
    if paths.sunshine_restart == "exe":
        sunshine_exe = shutil.which("sunshine")
        if sunshine_exe:
            env["SUNSHINE_EXE_PATH"] = sunshine_exe
    env["GAMESPHERE_STEAM_MODE"] = paths.steam_mode
    env["GAMESPHERE_SUNSHINE_RESTART"] = paths.sunshine_restart
    env["GAMESPHERE_HOST_LABEL"] = paths.host_label
    return env


def apply_detected_paths() -> Optional[PlatformPaths]:
    """Fill missing os.environ entries from auto-detected paths."""
    paths = detect_paths()
    if not paths:
        return None

    for key, value in paths_to_env(paths).items():
        upper = key.upper()
        if not os.getenv(key) and not os.getenv(upper):
            os.environ[key] = value
    return paths


def write_env_file(paths: PlatformPaths, env_path: str = ".env") -> str:
    """Write a .env file from detected paths."""
    lines = [
        "# Generated by GameSphere Companion Tool (platform_paths.py)",
        f"# Host profile: {paths.host_label} ({paths.steam_mode} Steam, {paths.sunshine_restart} Sunshine)",
        "",
        f"steam_library_vdf_path={paths.steam_library_vdf}",
        f"sunshine_apps_json_path={paths.sunshine_apps_json}",
        f"sunshine_grids_folder={paths.sunshine_grids_folder}",
        "",
        "# Optional: SteamGridDB API key for community art; leave blank for Steam CDN thumbnails",
        "# steamgriddb_api_key=",
        "",
    ]
    if paths.steam_exe:
        lines.append(f"STEAM_EXE_PATH={paths.steam_exe}")
    if paths.sunshine_restart == "exe":
        sunshine_exe = shutil.which("sunshine")
        if sunshine_exe:
            lines.append(f"SUNSHINE_EXE_PATH={sunshine_exe}")
    lines.extend(
        [
            "",
            f"GAMESPHERE_STEAM_MODE={paths.steam_mode}",
            f"GAMESPHERE_SUNSHINE_RESTART={paths.sunshine_restart}",
            f"GAMESPHERE_HOST_LABEL={paths.host_label}",
            "",
        ]
    )
    with open(env_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return env_path
