import os
import json
import re
import xml.etree.ElementTree as ET
import vdf
import requests
import glob
from PIL import Image
import io
import subprocess
import time
import psutil
import logging
import argparse
import sys
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin
from dotenv import load_dotenv

from platform_paths import apply_detected_paths, detect_paths, paths_to_env, write_env_file
from gs_version import __version__
from store_scanners import (
    STEAM_TOOL_EXCLUSIONS,
    build_windows_display_name_lookup,
    discover_xbox_roots,
    enhance_epic_entry,
    epic_launch_detached,
    load_all_third_party_stores,
    parse_xbox_config,
    resolve_display_name,
    store_key,
)
from store_covers import fetch_store_cover

# Configuration and logging setup
def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('sunshine_automation.log')
        ]
    )

def normalize_path(path: str) -> str:
    """Normalize path and handle escape sequences properly."""
    if not path:
        return path
    
    # Handle raw string paths (common in Windows)
    # Replace double backslashes with single backslashes
    path = path.replace('\\\\', '\\')
    
    # Normalize the path
    path = os.path.normpath(path)
    
    # Expand environment variables and user home
    path = os.path.expandvars(path)
    path = os.path.expanduser(path)
    
    return path

def validate_config(auto_detect: bool = True) -> Dict[str, str]:
    """Load and validate configuration from environment variables."""
    load_dotenv()

    if auto_detect:
        detected = apply_detected_paths()
        if detected:
            logging.info(
                "Auto-detected paths for %s (%s Steam, %s Sunshine restart)",
                detected.host_label,
                detected.steam_mode,
                detected.sunshine_restart,
            )
    
    required_vars = {
        'steam_library_vdf_path': 'Steam library VDF file path',
        'sunshine_apps_json_path': 'Sunshine apps.json file path',
        'sunshine_grids_folder': 'Sunshine thumbnails folder path',
    }
    # Optional: SteamGridDB API key; if missing, thumbnails use Steam CDN (no signup)
    optional_vars = {'steamgriddb_api_key': 'SteamGridDB API key'}

    config = {}
    missing_vars = []

    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value:
            missing_vars.append(f"{var} ({description})")
        else:
            if 'PATH' in var or 'FOLDER' in var:
                value = normalize_path(value)
                logging.debug(f"Normalized {var}: {value}")
        config[var] = value or ''
        config[var.upper()] = value or ''

    for var, description in optional_vars.items():
        value = os.getenv(var) or ''
        config[var] = value
        config[var.upper()] = value
    
    # Optional: Epic Games Store manifests path (Windows); empty = skip Epic
    epic_manifests = os.getenv('EPIC_MANIFESTS_PATH', '')
    if not epic_manifests and os.name == 'nt':
        epic_manifests = os.path.join(os.getenv('ProgramData', 'C:\\ProgramData'), 'Epic', 'EpicGamesLauncher', 'Data', 'Manifests')
    config['EPIC_MANIFESTS_PATH'] = normalize_path(epic_manifests) if epic_manifests else ''
    # Optional: custom games JSON path (name + cmd + optional image per game)
    custom_games_path = os.getenv('CUSTOM_GAMES_JSON_PATH', '')
    config['CUSTOM_GAMES_JSON_PATH'] = normalize_path(custom_games_path) if custom_games_path else ''
    # Optional: Xbox/Windows games root folder(s), comma-separated (e.g. C:\XboxGames,D:\XboxGames)
    xbox_folders = os.getenv('XBOX_GAMES_FOLDERS', '')
    if not xbox_folders and os.name == 'nt':
        xbox_folders = 'C:\\XboxGames'
    config['XBOX_GAMES_FOLDERS'] = xbox_folders.strip()
    # Optional: folder for auto-generated .lnk shortcuts (Windows); if set, Epic/Xbox/custom use shortcuts and Sunshine runs those
    shortcuts_folder = os.getenv('SUNSHINE_SHORTCUTS_FOLDER', '')
    config['SUNSHINE_SHORTCUTS_FOLDER'] = normalize_path(shortcuts_folder) if shortcuts_folder else ''

    # Optional variables with defaults
    steam_exe = os.getenv('STEAM_EXE_PATH', '')
    sunshine_exe = os.getenv('SUNSHINE_EXE_PATH', '')
    
    config['STEAM_EXE_PATH'] = normalize_path(steam_exe) if steam_exe else ''
    config['SUNSHINE_EXE_PATH'] = normalize_path(sunshine_exe) if sunshine_exe else ''
    
    if missing_vars:
        logging.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)
    
    # Validate paths exist
    if not os.path.exists(config['STEAM_LIBRARY_VDF_PATH']):
        logging.error(f"Steam library VDF file not found: {config['STEAM_LIBRARY_VDF_PATH']}")
        sys.exit(1)
    
    # Validate parent directories exist for output paths
    apps_dir = os.path.dirname(config['SUNSHINE_APPS_JSON_PATH'])
    if not os.path.exists(apps_dir):
        logging.error(f"Sunshine config directory not found: {apps_dir}")
        logging.info(f"Please ensure Sunshine is installed and has created its config directory")
        sys.exit(1)
    
    return config


def _steam_mode() -> str:
    """Return configured Steam launch mode: windows, native, flatpak, or macos."""
    mode = (os.getenv("GAMESPHERE_STEAM_MODE") or "").strip().lower()
    if mode:
        return mode
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "native"


def _steam_launch_cmd(app_id: str) -> str:
    """Build a platform-appropriate Steam launch command for an app id."""
    if os.name == "nt":
        return f"steam://rungameid/{app_id}"

    mode = _steam_mode()
    if mode == "flatpak":
        return f"flatpak run com.valvesoftware.Steam steam://rungameid/{app_id}"
    if mode == "macos":
        return f"open steam://rungameid/{app_id}"
    return f"setsid steam steam://rungameid/{app_id}"


def _extract_steam_app_id(cmd: str) -> Optional[str]:
    """Extract a Steam app id from Windows or Linux launch commands."""
    if not cmd:
        return None
    if "rungameid/" in cmd:
        return cmd.split("rungameid/")[-1].split("?")[0].split()[0].strip()
    if cmd.startswith("steam://rungameid/"):
        return cmd.split("/")[-1].split("?")[0].strip()
    return None


def _app_steam_app_id(app: Dict) -> Optional[str]:
    """Extract Steam app id from cmd and/or detached fields."""
    app_id = _extract_steam_app_id((app.get("cmd") or "").strip())
    if app_id:
        return app_id
    detached = app.get("detached")
    if isinstance(detached, list):
        for item in detached:
            app_id = _extract_steam_app_id(str(item))
            if app_id:
                return app_id
    elif isinstance(detached, str) and detached.strip():
        return _extract_steam_app_id(detached.strip())
    return None


def _linux_stream_prep_cmds() -> List[Dict]:
    """Return stream-prep hooks when the Bazzite helper script is present."""
    if os.name == "nt" or sys.platform == "darwin":
        return []
    script = os.path.expanduser("~/.local/bin/sunshine-stream-prep.sh")
    if os.path.isfile(script) and os.access(script, os.X_OK):
        return [{"do": f"{script} start", "undo": f"{script} stop", "elevated": False}]
    return []


def _steam_environ_app_id(app_id: str) -> Optional[str]:
    """
    App id used in process environ (SteamAppId).

    Store titles use the normal AppID. Non-Steam shortcuts launch via a 64-bit
    rungameid `(short << 32) | 0x02000000`, but child processes usually expose
    the 32-bit shortcuts.vdf appid — prefer that for kill matching.
    """
    aid = (app_id or "").strip()
    if not aid.isdigit():
        return None
    value = int(aid)
    if value > 0xFFFFFFFF:
        return str(value >> 32)
    return aid


def _scripts_dir() -> Optional[str]:
    """Directory that ships gamesphere-steam-close helpers (repo or frozen exe)."""
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(os.path.join(meipass, "scripts"))
        candidates.append(os.path.join(os.path.dirname(sys.executable), "scripts"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "scripts"))
    candidates.append(os.path.expanduser("~/.local/share/gamesphere-import-tool/scripts"))
    for path in candidates:
        if os.path.isdir(path):
            return path
    return None


def _steam_close_helper_path() -> Optional[str]:
    """Return the installed (or repo) close helper path without writing files."""
    if os.name == "nt":
        dest = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
            "GameSphere",
            "gamesphere-steam-close.ps1",
        )
        if os.path.isfile(dest):
            return dest
        src_dir = _scripts_dir()
        src = os.path.join(src_dir, "gamesphere-steam-close.ps1") if src_dir else ""
        return src if src and os.path.isfile(src) else None
    dest_sh = os.path.expanduser("~/.local/bin/gamesphere-steam-close.sh")
    if os.path.isfile(dest_sh) and os.access(dest_sh, os.X_OK):
        return dest_sh
    src_dir = _scripts_dir()
    src_sh = os.path.join(src_dir, "gamesphere-steam-close.sh") if src_dir else ""
    if src_sh and os.path.isfile(src_sh):
        return src_sh
    return None


def ensure_steam_close_helper() -> Optional[str]:
    """Install/refresh the Quit App close helper; return the command path to invoke."""
    src_dir = _scripts_dir()
    if os.name == "nt":
        dest_dir = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "GameSphere")
        dest = os.path.join(dest_dir, "gamesphere-steam-close.ps1")
        src = os.path.join(src_dir, "gamesphere-steam-close.ps1") if src_dir else ""
        if src and os.path.isfile(src):
            try:
                os.makedirs(dest_dir, exist_ok=True)
                with open(src, "rb") as fh:
                    data = fh.read()
                existing = b""
                if os.path.isfile(dest):
                    with open(dest, "rb") as fh:
                        existing = fh.read()
                if existing != data:
                    with open(dest, "wb") as fh:
                        fh.write(data)
                    logging.info("Installed Quit App helper %s", dest)
            except OSError as exc:
                logging.warning("Could not install Windows close helper: %s", exc)
                if os.path.isfile(src):
                    return src
        return dest if os.path.isfile(dest) else (src if src and os.path.isfile(src) else None)

    dest_dir = os.path.expanduser("~/.local/bin")
    dest_sh = os.path.join(dest_dir, "gamesphere-steam-close.sh")
    dest_py = os.path.join(dest_dir, "gamesphere-steam-close.py")
    src_sh = os.path.join(src_dir, "gamesphere-steam-close.sh") if src_dir else ""
    src_py = os.path.join(src_dir, "gamesphere-steam-close.py") if src_dir else ""
    try:
        os.makedirs(dest_dir, exist_ok=True)
        for src, dest in ((src_py, dest_py), (src_sh, dest_sh)):
            if not src or not os.path.isfile(src):
                continue
            with open(src, "rb") as fh:
                data = fh.read()
            existing = b""
            if os.path.isfile(dest):
                with open(dest, "rb") as fh:
                    existing = fh.read()
            if existing != data:
                with open(dest, "wb") as fh:
                    fh.write(data)
                os.chmod(dest, 0o755)
                logging.info("Installed Quit App helper %s", dest)
    except OSError as exc:
        logging.warning("Could not install close helper: %s", exc)
    if os.path.isfile(dest_sh) and os.access(dest_sh, os.X_OK):
        return dest_sh
    if src_sh and os.path.isfile(src_sh):
        return src_sh
    return None


def _steam_close_undo_cmd(app_id: str) -> Optional[str]:
    """
    Sunshine prep-cmd undo that closes a detached Steam game when the client
    sends Quit App (/cancel). Detached steam:// launches are not process-tracked
    by Sunshine, so without this undo the game keeps running on the host.

    Passes the original launch id to gamesphere-steam-close (handles 64-bit
    Non-Steam rungameids, install-dir/exe match, and late-spawn watch).
    Inline fallbacks match the 32-bit environ id if the helper is missing.
    """
    aid = (app_id or "").strip()
    if not aid.isdigit():
        return None
    short = _steam_environ_app_id(aid)
    if not short:
        return None

    helper = _steam_close_helper_path()
    if helper:
        if helper.lower().endswith(".ps1"):
            return (
                'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
                f'-File "{helper}" {aid}'
            )
        return f"{helper} {aid}"

    if os.name == "nt":
        return None

    if sys.platform == "darwin":
        return (
            f"bash -c 'aid={short}; "
            f"ps eww -A -o pid= -o command= 2>/dev/null | while read -r pid rest; do "
            f"case \"$rest\" in *SteamAppId=$aid*|*"
            f"SteamGameId=$aid*) "
            f"case \"$rest\" in *Steam.app*|*steam_osx*|*steamwebhelper*) continue ;; esac; "
            f"kill \"$pid\" 2>/dev/null || true ;; esac; done; sleep 1; "
            f"ps eww -A -o pid= -o command= 2>/dev/null | while read -r pid rest; do "
            f"case \"$rest\" in *SteamAppId=$aid*|*SteamGameId=$aid*) "
            f"case \"$rest\" in *Steam.app*|*steam_osx*|*steamwebhelper*) continue ;; esac; "
            f"kill -9 \"$pid\" 2>/dev/null || true ;; esac; done'"
        )

    # Linux (native / Flatpak Steam games still expose SteamAppId on host procs)
    return (
        f"bash -c 'aid={short}; "
        f"kill_app(){{ sig=\"$1\"; for d in /proc/[0-9]*; do pid=${{d##*/}}; "
        f"grep -Fzqx -- \"SteamAppId=$aid\" \"$d/environ\" 2>/dev/null || "
        f"grep -Fzqx -- \"SteamGameId=$aid\" \"$d/environ\" 2>/dev/null || continue; "
        f"cmd=$(tr \"\\0\" \" \" < \"$d/cmdline\" 2>/dev/null || true); "
        f"case \"$cmd\" in *ubuntu12_32/steam\\ *|*ubuntu12_64/steam\\ *|"
        f"*/steam.sh\\ *|*steamwebhelper*) continue ;; esac; "
        f"kill -$sig \"$pid\" 2>/dev/null || true; done; }}; "
        f"kill_app TERM; sleep 1; kill_app KILL'"
    )


def _steam_close_prep_entry(app_id: str) -> Optional[Dict]:
    """Prep entry whose undo closes the Steam game (do is intentionally empty)."""
    undo = _steam_close_undo_cmd(app_id)
    if not undo:
        return None
    return {"do": "", "undo": undo, "elevated": False}


def _prep_has_steam_close(prep_cmds: List[Dict], app_id: str) -> bool:
    """True if prep-cmd already includes a close-by-AppID undo."""
    short = _steam_environ_app_id(app_id) or app_id
    needles = (
        f"gamesphere-steam-close.sh {app_id}",
        f"gamesphere-steam-close.sh {short}",
        f"gamesphere-steam-close.ps1\" {app_id}",
        f"gamesphere-steam-close.ps1 {app_id}",
        f"gamesphere-steam-close.py {app_id}",
    )
    for entry in prep_cmds or []:
        undo = str((entry or {}).get("undo") or "")
        if any(n in undo for n in needles):
            return True
        if (app_id in undo or short in undo) and (
            "SteamAppId" in undo or "SteamGameId" in undo or "gamesphere-steam-close" in undo
        ):
            return True
    return False


def _merge_steam_prep_cmds(app_id: str, existing: Optional[List] = None) -> List[Dict]:
    """Stream-prep + host tuning prep + Steam close undo; keep other custom prep entries."""
    close_entry = _steam_close_prep_entry(app_id)
    merged: List[Dict] = []
    short = _steam_environ_app_id(app_id) or app_id

    # Prefer freshly detected stream-prep so path stays current.
    stream_prep = _linux_stream_prep_cmds()
    stream_undo = stream_prep[0]["undo"] if stream_prep else None
    if stream_prep:
        merged.extend(stream_prep)

    try:
        from host_tuning.service import global_prep_cmds, write_prep_scripts

        write_prep_scripts()
        host_prep = global_prep_cmds()
        host_undo = host_prep[0]["undo"] if host_prep else None
        if host_prep:
            merged.extend(host_prep)
    except Exception as exc:
        logging.debug("Host tuning prep unavailable: %s", exc)
        host_undo = None

    for entry in existing or []:
        if not isinstance(entry, dict):
            continue
        undo = str(entry.get("undo") or "")
        do = str(entry.get("do") or "")
        # Drop stale stream-prep / close-game entries; we re-add canonical ones.
        if stream_undo and undo == stream_undo:
            continue
        if host_undo and undo == host_undo:
            continue
        if "sunshine-stream-prep.sh" in do or "sunshine-stream-prep.sh" in undo:
            continue
        if "gamesphere-host-prep" in do or "gamesphere-host-prep" in undo:
            continue
        if "gamesphere-steam-close" in undo or (
            (app_id in undo or short in undo)
            and ("SteamAppId" in undo or "SteamGameId" in undo)
        ):
            continue
        merged.append(entry)

    if close_entry and not _prep_has_steam_close(merged, app_id):
        merged.append(close_entry)
    return merged


def _build_steam_app(app_id: str, game_name: str, grid_path: Optional[str]) -> Dict:
    """Build a Sunshine app entry using platform-correct cmd/detached fields."""
    launch = _steam_launch_cmd(app_id)
    app: Dict = {
        "name": game_name,
        "output": "",
        "elevated": "false",
        "hidden": "true",
        "wait-all": "true",
        "exit-timeout": "5",
        "image-path": grid_path or "",
    }
    if os.name == "nt":
        app["cmd"] = launch
        app["detached"] = ""
    else:
        # Sunshine docs: Steam must be detached on Linux/macOS (Steam respawns itself).
        app["cmd"] = ""
        app["detached"] = [launch]
    prep_cmds = _merge_steam_prep_cmds(app_id)
    if prep_cmds:
        app["prep-cmd"] = prep_cmds
    return app


def _repair_steam_app_entry(app: Dict) -> Dict:
    """Fix Steam entries: detached launch + Quit App close undo."""
    app_id = _app_steam_app_id(app)
    if not app_id:
        return app
    repaired = _build_steam_app(app_id, app.get("name", ""), app.get("image-path"))
    repaired["name"] = app.get("name", repaired["name"])
    # Rebuild prep from existing customs + canonical stream-prep/close undo.
    repaired["prep-cmd"] = _merge_steam_prep_cmds(app_id, app.get("prep-cmd"))
    if not repaired["prep-cmd"]:
        repaired.pop("prep-cmd", None)
    return repaired


def _is_steam_running() -> bool:
    """Return True if Steam is already running."""
    steam_names = {"steam.exe", "steam", "steam_osx"}
    try:
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name in steam_names:
                return True
    except Exception:
        pass
    return False


def ensure_steam_running(steam_exe_path: str) -> None:
    """Start Steam only if it is not already running. Does not restart or close Steam."""
    if _is_steam_running():
        logging.info("Steam is already running. Skipping start.")
        return

    mode = _steam_mode()
    logging.info("Steam is not running. Starting Steam...")

    try:
        if os.name == "nt":
            if not steam_exe_path or not os.path.exists(steam_exe_path):
                logging.warning(
                    "Steam executable path not configured or doesn't exist. Skipping Steam start."
                )
                return
            subprocess.Popen(
                [steam_exe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        elif mode == "flatpak":
            subprocess.Popen(
                ["flatpak", "run", "com.valvesoftware.Steam"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", "-a", "Steam"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            steam_bin = steam_exe_path if steam_exe_path and os.path.exists(steam_exe_path) else "steam"
            subprocess.Popen(
                [steam_bin],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        time.sleep(5)
        logging.info("Steam start requested")
    except Exception as e:
        logging.error(f"Error starting Steam: {e}")


def restart_sunshine(sunshine_exe_path: str) -> None:
    """Restart Sunshine/Apollo (or other Sunshine-compatible host) safely."""
    restart_mode = (os.getenv("GAMESPHERE_SUNSHINE_RESTART") or "").strip().lower()

    if restart_mode == "systemd" or (
        not restart_mode and os.name != "nt" and sys.platform != "darwin"
    ):
        logging.info("Restarting Sunshine via systemd --user...")
        try:
            result = subprocess.run(
                ["systemctl", "--user", "restart", "sunshine"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                logging.info("Sunshine restart completed (systemd)")
                return
            logging.warning(
                "systemctl restart failed (%s): %s",
                result.returncode,
                (result.stderr or result.stdout).strip(),
            )
        except Exception as e:
            logging.warning(f"systemd restart failed: {e}")

    if restart_mode == "flatpak":
        logging.info("Restarting Sunshine via flatpak...")
        try:
            result = subprocess.run(
                ["flatpak", "restart", "dev.lizardbyte.app.Sunshine"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                logging.info("Sunshine restart completed (flatpak)")
                return
            logging.warning(
                "flatpak restart failed (%s): %s",
                result.returncode,
                (result.stderr or result.stdout).strip(),
            )
        except Exception as e:
            logging.warning(f"flatpak restart failed: {e}")

    if os.name != "nt" and not sunshine_exe_path:
        logging.warning(
            "Host restart skipped. Try: systemctl --user restart sunshine"
        )
        return

    if not sunshine_exe_path or not os.path.exists(sunshine_exe_path):
        logging.warning("Host executable path not configured or doesn't exist. Skipping restart.")
        return

    process_name = os.path.basename(sunshine_exe_path).lower()
    logging.info(f"Restarting host ({process_name})...")
    try:
        terminated = False
        for proc in psutil.process_iter(["name", "pid"]):
            if proc.info["name"] and proc.info["name"].lower() == process_name:
                logging.debug(f"Terminating Sunshine process (PID: {proc.info['pid']})")
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                    terminated = True
                except psutil.TimeoutExpired:
                    logging.warning(
                        f"Sunshine process (PID: {proc.info['pid']}) didn't terminate gracefully"
                    )
                    proc.kill()

        if terminated:
            time.sleep(3)

        logging.info(f"Starting host from: {sunshine_exe_path}")
        subprocess.Popen(
            [sunshine_exe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        logging.info("Host restart completed")
    except Exception as e:
        logging.error(f"Error restarting Sunshine: {e}")

@lru_cache(maxsize=1000)
def get_game_name(app_id: str) -> Optional[str]:
    """Fetch game name from Steam API with caching and retry logic."""
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
    
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if str(app_id) in data and data[str(app_id)].get('success'):
                game_data = data[str(app_id)].get('data', {})
                name = game_data.get('name')
                if name:
                    logging.debug(f"Retrieved name for AppID {app_id}: {name}")
                    return name
            
            logging.warning(f"No valid data found for AppID {app_id}")
            return None
            
        except requests.exceptions.Timeout:
            logging.warning(f"Timeout fetching name for AppID {app_id} (attempt {attempt + 1}/3)")
        except requests.exceptions.RequestException as e:
            logging.warning(f"Request error for AppID {app_id} (attempt {attempt + 1}/3): {e}")
        except Exception as e:
            logging.error(f"Unexpected error fetching name for AppID {app_id}: {e}")
            return None
        
        if attempt < 2:  # Don't sleep on last attempt
            time.sleep(2 ** attempt)  # Exponential backoff
    
    logging.error(f"Failed to fetch name for AppID {app_id} after 3 attempts")
    return None

def fetch_grid_from_steamgriddb(app_id: str, api_key: str, grids_folder: str) -> Optional[str]:
    """Fetch game grid image from SteamGridDB with retry logic."""
    url = f"https://www.steamgriddb.com/api/v2/grids/steam/{app_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            if "data" in data and len(data["data"]) > 0:
                grid_url = data["data"][0]["url"]
                grid_response = requests.get(grid_url, timeout=30)
                grid_response.raise_for_status()
                
                # Validate image data
                try:
                    image = Image.open(io.BytesIO(grid_response.content))
                    image.verify()  # Verify it's a valid image
                    
                    # Reopen for saving (verify() closes the image)
                    image = Image.open(io.BytesIO(grid_response.content))
                    grid_path = os.path.join(grids_folder, f"{app_id}.png")
                    
                    # Ensure directory exists
                    os.makedirs(grids_folder, exist_ok=True)
                    
                    image.save(grid_path, "PNG")
                    logging.debug(f"Downloaded grid for AppID {app_id}: {grid_path}")
                    return grid_path
                    
                except Exception as img_error:
                    logging.warning(f"Invalid image data for AppID {app_id}: {img_error}")
                    return None
            else:
                logging.warning(f"No grid data found for AppID {app_id}")
                return None
                
        except requests.exceptions.Timeout:
            logging.warning(f"Timeout fetching grid for AppID {app_id} (attempt {attempt + 1}/3)")
        except requests.exceptions.RequestException as e:
            logging.warning(f"Request error for AppID {app_id} (attempt {attempt + 1}/3): {e}")
        except Exception as e:
            logging.error(f"Unexpected error fetching grid for AppID {app_id}: {e}")
            return None
        
        if attempt < 2:  # Don't sleep on last attempt
            time.sleep(2 ** attempt)  # Exponential backoff
    
    logging.error(f"Failed to fetch grid for AppID {app_id} after 3 attempts")
    return None


# Steam CDN URLs (no API key, no signup) — box art (library cover) first, then header fallback
STEAM_CDN_LIBRARY_URL = "https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_600x900_2x.jpg"  # box art 1200x1800
STEAM_CDN_LIBRARY_FALLBACK_URL = "https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg"  # 600x900
STEAM_CDN_HEADER_URL = "https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"  # wide tile fallback


def _download_steam_cdn_image(url: str, app_id: str, grids_folder: str) -> Optional[str]:
    """Download image from URL to grids_folder; return path or None."""
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        if len(response.content) < 500:
            return None
        image = Image.open(io.BytesIO(response.content))
        image.verify()
        image = Image.open(io.BytesIO(response.content))
        grid_path = os.path.join(grids_folder, f"{app_id}.png")
        os.makedirs(grids_folder, exist_ok=True)
        image.save(grid_path, "PNG")
        logging.debug(f"Downloaded image from Steam CDN for AppID {app_id}: {grid_path}")
        return grid_path
    except Exception:
        return None


def fetch_grid_from_steam_cdn(app_id: str, grids_folder: str) -> Optional[str]:
    """Fetch box-art (library cover) image from Steam's public CDN. No API key or signup required."""
    for url_template in (STEAM_CDN_LIBRARY_URL, STEAM_CDN_LIBRARY_FALLBACK_URL, STEAM_CDN_HEADER_URL):
        url = url_template.format(app_id=app_id)
        path = _download_steam_cdn_image(url, app_id, grids_folder)
        if path:
            return path
    logging.warning(f"No Steam CDN image found for AppID {app_id}")
    return None


def fetch_grid(app_id: str, api_key: str, grids_folder: str) -> Optional[str]:
    """Fetch grid image: SteamGridDB if API key set (with Steam CDN fallback), else Steam CDN only."""
    if api_key and api_key.strip():
        path = fetch_grid_from_steamgriddb(app_id, api_key.strip(), grids_folder)
        if path:
            return path
        logging.debug(f"SteamGridDB failed for {app_id}, trying Steam CDN")
    return fetch_grid_from_steam_cdn(app_id, grids_folder)


def _steamgriddb_search_steam_id(game_name: str, api_key: str) -> Optional[str]:
    """Search SteamGridDB by game name; return first result's Steam app ID if any."""
    if not api_key or not api_key.strip():
        return None
    url = f"https://www.steamgriddb.com/api/v2/search/autocomplete/{requests.utils.quote(game_name)}"
    headers = {"Authorization": f"Bearer {api_key.strip()}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("success") and data.get("data"):
            first = data["data"][0]
            # API returns objects with "id" (SteamGridDB id) or "steam_app_id"
            steam_id = first.get("steam_app_id") or first.get("id")
            if steam_id is not None:
                return str(steam_id)
    except Exception as e:
        logging.debug(f"SteamGridDB search for '{game_name}': {e}")
    return None


def fetch_grid_by_name(game_name: str, api_key: str, grids_folder: str, file_safe_id: str) -> Optional[str]:
    """Fetch grid for a non-Steam game by name (SteamGridDB search then Steam grid). Returns path or None."""
    steam_id = _steamgriddb_search_steam_id(game_name, api_key)
    if steam_id:
        path = fetch_grid_from_steamgriddb(steam_id, api_key.strip(), grids_folder)
        if path:
            # Save under file_safe_id so we don't overwrite Steam grids
            dest = os.path.join(grids_folder, f"{file_safe_id}.png")
            if dest != path and os.path.exists(path):
                try:
                    import shutil
                    shutil.move(path, dest)
                    return dest
                except Exception:
                    return path
            return path
        path = fetch_grid_from_steam_cdn(steam_id, grids_folder)
        if path:
            dest = os.path.join(grids_folder, f"{file_safe_id}.png")
            if dest != path and os.path.exists(path):
                try:
                    import shutil
                    shutil.move(path, dest)
                    return dest
                except Exception:
                    return path
            return path
    return None


def get_sunshine_config(path: str) -> Dict:
    """Load Sunshine configuration with error handling."""
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as file:
                config = json.load(file)
            
            # Validate config structure
            if not isinstance(config, dict):
                raise ValueError("Config must be a dictionary")
            
            if 'apps' not in config:
                config['apps'] = []
            
            if 'env' not in config:
                config['env'] = ""
            
            logging.info(f"Loaded Sunshine config with {len(config['apps'])} apps")
            return config
        else:
            config = {"env": "", "apps": []}
            logging.info("Sunshine config not found, initializing empty config")
            return config
            
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in Sunshine config file: {e}")
        raise
    except Exception as e:
        logging.error(f"Error loading Sunshine config: {e}")
        raise

def save_sunshine_config(path: str, config: Dict) -> None:
    """Save Sunshine configuration with backup and error handling."""
    import shutil
    backup_path = f"{path}.backup"
    config_dir = os.path.dirname(path)

    try:
        # Create backup if file exists (use fallback dir if Program Files is read-only)
        if os.path.exists(path):
            try:
                shutil.copy2(path, backup_path)
                logging.debug(f"Created backup: {backup_path}")
            except OSError as e:
                if e.errno == 13:  # Permission denied
                    fallback = os.path.join(os.path.expanduser("~"), "GamesphereImportTool_backups")
                    os.makedirs(fallback, exist_ok=True)
                    backup_name = os.path.basename(path) + ".backup"
                    backup_path = os.path.join(fallback, backup_name)
                    shutil.copy2(path, backup_path)
                    logging.info(f"Backup saved to user folder (no write access to config dir): {backup_path}")
                else:
                    raise

        # Ensure directory exists
        try:
            os.makedirs(config_dir, exist_ok=True)
        except OSError as e:
            if e.errno == 13:
                raise PermissionError(
                    "Cannot write to the config directory (e.g. Program Files). "
                    "Run this tool as Administrator: right-click the app and choose 'Run as administrator'."
                ) from e
            raise

        # Write config
        try:
            with open(path, 'w', encoding='utf-8') as file:
                json.dump(config, file, indent=4, ensure_ascii=False)
        except OSError as e:
            if e.errno == 13:
                raise PermissionError(
                    "Cannot write to the config directory (e.g. Program Files). "
                    "Run this tool as Administrator: right-click the app and choose 'Run as administrator'."
                ) from e
            raise

        logging.info(f"Saved Sunshine config with {len(config.get('apps', []))} apps")

    except PermissionError:
        raise
    except Exception as e:
        logging.error(f"Error saving Sunshine config: {e}")
        raise


def _create_shortcut_win(shortcut_path: str, target: str, work_dir: Optional[str] = None) -> bool:
    """Create a Windows .lnk shortcut. target can be an exe path or a protocol URL. Returns True on success."""
    if os.name != 'nt':
        return False
    try:
        shortcut_path = os.path.normpath(shortcut_path)
        if not shortcut_path.lower().endswith('.lnk'):
            shortcut_path += '.lnk'
        if not work_dir and target and os.path.sep in target and not target.startswith('com.'):
            work_dir = os.path.dirname(target)
        work_dir = work_dir or ''
        env = os.environ.copy()
        env['SHORTCUT_PATH'] = shortcut_path
        env['TARGET_PATH'] = target
        env['WORK_DIR'] = work_dir
        script = (
            '$s = New-Object -ComObject WScript.Shell; '
            '$l = $s.CreateShortcut($env:SHORTCUT_PATH); '
            '$l.TargetPath = $env:TARGET_PATH; '
            'if ($env:WORK_DIR) { $l.WorkingDirectory = $env:WORK_DIR }; '
            '$l.Save(); [System.Runtime.Interopservices.Marshal]::ReleaseComObject($s) | Out-Null'
        )
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            env=env, capture_output=True, timeout=10, check=True
        )
        logging.debug(f"Created shortcut: {shortcut_path}")
        return True
    except Exception as e:
        logging.warning(f"Failed to create shortcut {shortcut_path}: {e}")
        return False


def _read_shortcut_target_win(shortcut_path: str) -> Optional[str]:
    """Read the target path/URL of a Windows .lnk file. Returns None on failure."""
    if os.name != 'nt' or not os.path.isfile(shortcut_path):
        return None
    try:
        env = os.environ.copy()
        env['LNK_PATH'] = shortcut_path
        out = subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
             '$s = New-Object -ComObject WScript.Shell; $s.CreateShortcut($env:LNK_PATH).TargetPath'],
            env=env, capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0 and out.stdout:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def _shortcut_launch_cmd(shortcut_path: str) -> str:
    """Return the command to run a .lnk so the shell resolves it (Windows). Sunshine may need this."""
    path_norm = os.path.normpath(shortcut_path)
    return f'cmd /c start "" "{path_norm}"'


def _extract_shortcut_path_from_cmd(cmd: str) -> Optional[str]:
    """If cmd is or contains a path to a .lnk file, return that path (normalized). Otherwise None."""
    c = (cmd or '').strip()
    # cmd /c start "" "C:\path\to\file.lnk"
    if 'start "" "' in c and '.lnk' in c:
        try:
            i = c.index('start "" "') + len('start "" "')  # opening " of path
            j = c.index('"', i + 1)
            path = c[i + 1:j]
            if path.lower().endswith('.lnk'):
                return os.path.normpath(path)
        except ValueError:
            pass
    if c.lower().endswith('.lnk') and os.path.sep in c:
        return os.path.normpath(c)
    return None


def load_installed_games(library_vdf_path: str) -> Dict[str, str]:
    """Load installed games from Steam library VDF file."""
    logging.info(f"Loading Steam library from {library_vdf_path}")
    
    try:
        with open(library_vdf_path, 'r', encoding='utf-8') as file:
            steam_data = vdf.load(file)
    except Exception as e:
        logging.error(f"Error loading Steam library VDF: {e}")
        raise
    
    logging.debug("Raw Steam library data loaded successfully")
    
    installed_games = {}
    total_apps = 0
    
    # Count total apps for progress tracking
    for folder_data in steam_data.get('libraryfolders', {}).values():
        if "apps" in folder_data:
            total_apps += len(folder_data["apps"])
    
    logging.info(f"Processing {total_apps} Steam apps...")
    
    # Use thread pool for concurrent API calls
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_app_id = {}
        
        for folder_data in steam_data.get('libraryfolders', {}).values():
            if "apps" in folder_data:
                for app_id in folder_data["apps"].keys():
                    future = executor.submit(get_game_name, app_id)
                    future_to_app_id[future] = app_id
        
        processed = 0
        for future in as_completed(future_to_app_id):
            app_id = future_to_app_id[future]
            processed += 1
            
            try:
                game_name = future.result()
                if game_name:
                    if game_name.lower() in {x.lower() for x in STEAM_TOOL_EXCLUSIONS}:
                        logging.debug(f"Skipping Steam tool/runtime: {game_name} (ID: {app_id})")
                        continue
                    installed_games[app_id] = game_name
                    logging.debug(f"Found game: {game_name} (ID: {app_id})")
            except Exception as e:
                logging.warning(f"Error processing AppID {app_id}: {e}")
            
            if processed % 50 == 0 or processed == total_apps:
                logging.info(f"Processed {processed}/{total_apps} apps...")
    
    logging.info(f"Found {len(installed_games)} installed games")
    return installed_games


def _steam_root_from_library_vdf(library_vdf_path: str) -> str:
    """Steam root directory that contains userdata/ (parent of steamapps/)."""
    steamapps = os.path.dirname(os.path.abspath(library_vdf_path))
    return os.path.dirname(steamapps)


def _u32(value: int) -> int:
    """Normalize signed VDF int32 appids to unsigned 32-bit."""
    return int(value) & 0xFFFFFFFF


def _shortcut_rungameid(short_appid: int) -> str:
    """64-bit id for steam://rungameid from shortcuts.vdf appid."""
    return str((int(short_appid) << 32) | 0x02000000)


# GameSphere shelf console tags inferred from Non-Steam shortcut exe / ROM paths.
# Client GSGameCategoryAssigner reads "(Switch)" etc. from the Sunshine app name.
_ROM_FOLDER_PLATFORM = {
    "switch": "Switch",
    "switch2": "Switch 2",
    "wiiu": "Wii U",
    "wii-u": "Wii U",
    "wii": "Wii",
    "gc": "GameCube",
    "gamecube": "GameCube",
    "ngc": "GameCube",
    "n64": "N64",
    "snes": "SNES",
    "nes": "NES",
    "gba": "Game Boy",
    "gbc": "Game Boy",
    "gb": "Game Boy",
    "nds": "DS",
    "3ds": "3DS",
    "psx": "PS1",
    "ps1": "PS1",
    "ps2": "PS2",
    "ps3": "PS3",
    "psp": "PSP",
    "psvita": "Vita",
    "vita": "Vita",
    "xbox360": "Xbox 360",
    "xbox": "Xbox",
    "genesis": "Genesis",
    "megadrive": "Genesis",
    "dreamcast": "Dreamcast",
    "saturn": "Saturn",
    "arcade": "Arcade",
    "mame": "Arcade",
    "fbneo": "Arcade",
    "pc": "PC",
}

_ROM_EXT_PLATFORM = {
    "nsp": "Switch", "xci": "Switch", "nca": "Switch", "nro": "Switch",
    "wbfs": "Wii", "wad": "Wii",
    "wua": "Wii U", "wud": "Wii U", "wux": "Wii U",
    "gcm": "GameCube", "gcz": "GameCube", "rvz": "GameCube",
    "z64": "N64", "n64": "N64", "v64": "N64",
    "sfc": "SNES", "smc": "SNES",
    "nes": "NES",
    "gba": "Game Boy", "gbc": "Game Boy", "gb": "Game Boy",
    "nds": "DS", "cia": "3DS", "3ds": "3DS",
    "pbp": "PS1", "cso": "PS2",
}


def _platform_from_shortcut_exe(exe: str) -> Optional[str]:
    """Infer GameSphere console from a Non-Steam shortcut exe / launcher line."""
    if not exe:
        return None
    blob = exe.lower().replace("\\", "/")

    # Explicit ROM library folders beat launcher name (dolphin serves GC + Wii).
    if "/roms/" in blob:
        try:
            after = blob.split("/roms/", 1)[1]
            folder = after.split("/", 1)[0].strip()
            if folder in _ROM_FOLDER_PLATFORM:
                return _ROM_FOLDER_PLATFORM[folder]
        except Exception:
            pass

    launcher_map = (
        ("ryujinx-game", "Switch"),
        ("eden-game", "Switch"),
        ("yuzu-game", "Switch"),
        ("suyu-game", "Switch"),
        ("ryujinx", "Switch"),
        ("eden", "Switch"),
        ("yuzu", "Switch"),
        ("suyu", "Switch"),
        ("cemu-game", "Wii U"),
        ("cemu", "Wii U"),
        ("dolphin-game", "GameCube"),
        ("dolphin", "GameCube"),
        ("rpcs3", "PS3"),
        ("pcsx2", "PS2"),
        ("duckstation", "PS1"),
        ("ppsspp", "PSP"),
        ("vita3k", "Vita"),
        ("xenia", "Xbox 360"),
        ("xemu", "Xbox"),
        ("citra", "3DS"),
        ("lime3ds", "3DS"),
        ("melonds", "DS"),
        ("retroarch-game", None),  # need core/path
        ("retroarch", None),
    )
    for needle, platform in launcher_map:
        if needle in blob:
            if platform:
                return platform
            break

    # File extension on the last path-looking token.
    for token in reversed(blob.replace('"', " ").split()):
        if "." not in token:
            continue
        ext = token.rsplit(".", 1)[-1]
        if ext in _ROM_EXT_PLATFORM:
            return _ROM_EXT_PLATFORM[ext]

    # RetroArch core hints.
    if "mupen" in blob or "parallel_n64" in blob:
        return "N64"
    if "snes9x" in blob or "bsnes" in blob or "mesen-s" in blob:
        return "SNES"
    if "fceumm" in blob or "nestopia" in blob or "mesen" in blob:
        return "NES"
    if "mgba" in blob or "vbam" in blob or "sameboy" in blob:
        return "Game Boy"
    if "genesis_plus" in blob or "picodrive" in blob:
        return "Genesis"
    if "flycast" in blob or "redream" in blob:
        return "Dreamcast"
    if "ppsspp" in blob:
        return "PSP"
    return None


def _ensure_platform_tag(name: str, platform: str) -> str:
    """Append '(Switch)' etc. when missing so GameSphere can categorize without exe access."""
    if not name or not platform:
        return name
    # Already tagged — leave user/Steam naming alone.
    if re.search(rf"\(\s*{re.escape(platform)}\s*\)", name, flags=re.IGNORECASE):
        return name
    if re.search(r"\(\s*PC\s*Port\s*\)", name, flags=re.IGNORECASE):
        return name
    # Don't fight an existing console tag of a different family.
    if re.search(
        r"\((Switch(?:\s*2)?|Wii\s*U|Wii|GameCube|N64|SNES|NES|PS[1-5]|PSP|Vita|"
        r"Xbox(?:\s*(?:360|One|Series[^)]*))?|3DS|DS|Genesis|Dreamcast|Arcade|PC)\)",
        name,
        flags=re.IGNORECASE,
    ):
        return name
    return f"{name.strip()} ({platform})"


def _retag_nonsteam_app_names(apps: List[Dict], shortcuts: Dict[str, Dict[str, str]]) -> int:
    """Ensure existing Sunshine Non-Steam apps carry a platform tag from shortcuts.vdf exe."""
    if not shortcuts:
        return 0
    tagged = 0
    for app in apps:
        app_id = _app_steam_app_id(app)
        if not app_id:
            continue
        info = shortcuts.get(app_id)
        if not info:
            continue
        platform = _platform_from_shortcut_exe(info.get("exe") or "")
        if not platform:
            continue
        old = (app.get("name") or "").strip()
        new = _ensure_platform_tag(old or info.get("name") or "", platform)
        if new and new != old:
            app["name"] = new
            tagged += 1
            logging.info("Tagged Non-Steam app for GameSphere: %s", new)
    return tagged


def _find_shortcut_grid_source(userdata_config_dir: str, short_appid: int) -> Optional[str]:
    """Prefer local Steam grid art already downloaded for this Non-Steam shortcut."""
    grid_dir = os.path.join(userdata_config_dir, "grid")
    if not os.path.isdir(grid_dir):
        return None
    aid = str(short_appid)
    for name in (
        f"{aid}p.png",
        f"{aid}p.jpg",
        f"{aid}.png",
        f"{aid}.jpg",
        f"{aid}_icon.png",
        f"{aid}_icon.jpg",
    ):
        path = os.path.join(grid_dir, name)
        if os.path.isfile(path):
            return path
    return None


def load_steam_nonsteam_shortcuts(library_vdf_path: str) -> Dict[str, Dict[str, str]]:
    """
    Load Non-Steam games from userdata/*/config/shortcuts.vdf.

    Returns dict keyed by 64-bit steam://rungameid string:
      { "name", "short_appid", "exe", "grid_src" (optional) }
    Merges all Steam users; skips hidden entries; dedupes by short appid.
    """
    steam_root = _steam_root_from_library_vdf(library_vdf_path)
    userdata_root = os.path.join(steam_root, "userdata")
    if not os.path.isdir(userdata_root):
        logging.info(
            "No Steam userdata directory at %s — skipping Non-Steam shortcuts",
            userdata_root,
        )
        return {}

    by_short: Dict[int, Dict[str, str]] = {}
    files_read = 0
    for entry in sorted(os.listdir(userdata_root)):
        if not entry.isdigit() or entry == "0":
            continue
        shortcuts_path = os.path.join(userdata_root, entry, "config", "shortcuts.vdf")
        if not os.path.isfile(shortcuts_path):
            continue
        files_read += 1
        try:
            with open(shortcuts_path, "rb") as handle:
                data = vdf.binary_load(handle)
        except Exception as exc:
            logging.warning("Failed to parse shortcuts.vdf %s: %s", shortcuts_path, exc)
            continue

        shortcuts = data.get("shortcuts") or {}
        config_dir = os.path.dirname(shortcuts_path)
        for item in shortcuts.values():
            if not isinstance(item, dict):
                continue
            raw_id = item.get("appid")
            if raw_id is None:
                continue
            try:
                short_appid = _u32(int(raw_id))
            except (TypeError, ValueError):
                continue
            if int(item.get("IsHidden") or 0):
                continue
            name = (item.get("appname") or item.get("AppName") or "").strip()
            exe = (item.get("exe") or item.get("Exe") or "").strip()
            if not name:
                continue
            grid_src = _find_shortcut_grid_source(config_dir, short_appid) or ""
            prev = by_short.get(short_appid)
            # Prefer entries that have local artwork / a longer display name.
            if prev and len(prev.get("name", "")) >= len(name) and (
                prev.get("grid_src") or not grid_src
            ):
                continue
            by_short[short_appid] = {
                "name": name,
                "short_appid": str(short_appid),
                "exe": exe,
                "grid_src": grid_src,
            }

    result: Dict[str, Dict[str, str]] = {}
    for short_appid, info in by_short.items():
        result[_shortcut_rungameid(short_appid)] = info

    # Collapse duplicate display names across Steam users (e.g. same emu title
    # added on Trevor + Gemma). Prefer Ryujinx over Eden for Switch titles.
    by_name: Dict[str, Tuple[str, Dict[str, str]]] = {}
    for bpid, info in result.items():
        key = (info.get("name") or "").strip().casefold()
        if not key:
            continue
        exe = (info.get("exe") or "").lower()
        prev = by_name.get(key)
        if not prev:
            by_name[key] = (bpid, info)
            continue
        prev_bpid, prev_info = prev
        prev_exe = (prev_info.get("exe") or "").lower()
        prefer_new = False
        if "ryujinx-game" in exe and "ryujinx-game" not in prev_exe:
            prefer_new = True
        elif "ryujinx-game" in prev_exe and "ryujinx-game" not in exe:
            prefer_new = False
        elif "eden-game" in prev_exe and "eden-game" not in exe:
            prefer_new = True
        elif (info.get("grid_src") and not prev_info.get("grid_src")):
            prefer_new = True
        if prefer_new:
            by_name[key] = (bpid, info)
    if len(by_name) < len(result):
        logging.info(
            "Deduped Non-Steam shortcuts by name: %d → %d",
            len(result),
            len(by_name),
        )
        result = {bpid: info for bpid, info in by_name.values()}

    logging.info(
        "Found %d Non-Steam shortcut(s) from %d shortcuts.vdf file(s)",
        len(result),
        files_read,
    )
    return result


def _copy_grid_to_sunshine(src_path: str, dest_id: str, grids_folder: str) -> Optional[str]:
    """Copy/convert a local Steam grid image into the Sunshine covers folder."""
    if not src_path or not os.path.isfile(src_path):
        return None
    os.makedirs(grids_folder, exist_ok=True)
    dest = os.path.join(grids_folder, f"{dest_id}.png")
    try:
        if src_path.lower().endswith(".png"):
            import shutil

            shutil.copy2(src_path, dest)
            return dest
        with Image.open(src_path) as img:
            img.convert("RGBA").save(dest, "PNG")
        return dest
    except Exception as exc:
        logging.debug("Could not copy shortcut grid %s: %s", src_path, exc)
        return None


def load_installed_epic_games(manifests_path: str) -> Dict[str, Dict]:
    """
    Load installed Epic Games Store games from .item manifest files.
    Uses StreamTweak-style launch_id triples and catalog metadata when present.
    Returns dict keyed by AppName.
    """
    if not manifests_path or not os.path.isdir(manifests_path):
        logging.debug("Epic manifests path not set or not a directory, skipping Epic")
        return {}
    lookup = build_windows_display_name_lookup()
    installed = {}
    for path in glob.glob(os.path.join(manifests_path, "*.item")):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            entry = enhance_epic_entry(data)
            if not entry:
                continue
            app_name = entry["app_name"]
            install_location = data.get("InstallLocation") or ""
            if install_location:
                entry["name"] = resolve_display_name(install_location, entry["name"], lookup)
            installed[app_name] = entry
        except Exception as e:
            logging.debug(f"Skip Epic manifest {path}: {e}")
    logging.info(f"Found {len(installed)} installed Epic games")
    return installed


def load_custom_games(json_path: str) -> List[Dict]:
    """
    Load custom game entries from a JSON file.
    Expected format: { "games": [ { "name": "...", "cmd": "path or command", "image_path": "" } ] }
    image_path optional; cmd required.
    """
    if not json_path or not os.path.isfile(json_path):
        return []
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        games = data.get("games") or data.get("custom_games") or []
        out = []
        for g in games:
            if isinstance(g, dict) and g.get("cmd"):
                out.append({
                    "name": (g.get("name") or "").strip() or "Custom Game",
                    "cmd": g["cmd"].strip(),
                    "image_path": (g.get("image_path") or "").strip(),
                })
        logging.info(f"Loaded {len(out)} custom game(s) from {json_path}")
        return out
    except Exception as e:
        logging.warning(f"Could not load custom games from {json_path}: {e}")
        return []


# Exe filenames (or name substrings) to never use as the main game launcher (e.g. Minecraft: GameLaunchHelper, Java, launcher)
XBOX_SKIP_EXE_NAMES = ('gamelaunchhelper', 'java', 'launcher')


def _find_exe_in_tree(root_dir: str, exe_name: str) -> Optional[str]:
    """Search for a file named exe_name anywhere under root_dir (recursive). Prefer paths not in Uninstall/Redist. Returns full path or None."""
    exe_lower = exe_name.lower()
    if any(skip in exe_lower for skip in XBOX_SKIP_EXE_NAMES):
        return None
    candidates = []
    skip_parts = ('uninstall', 'redist', 'redistribution', '_redist', 'vc_redist', 'dotnet', 'dxsetup')
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for f in filenames:
            if f.lower() == exe_lower or (exe_lower.endswith('.exe') and f.lower() == exe_lower):
                if any(skip in f.lower() for skip in XBOX_SKIP_EXE_NAMES):
                    continue
                path = os.path.join(dirpath, f)
                if os.path.isfile(path):
                    rel = os.path.relpath(dirpath, root_dir).lower()
                    is_skip = any(part in rel for part in skip_parts)
                    candidates.append((path, is_skip))
    # Prefer exe not in uninstall/redist folders
    for path, is_skip in candidates:
        if not is_skip:
            return os.path.normpath(path)
    return os.path.normpath(candidates[0][0]) if candidates else None


def _find_any_exe_in_tree(root_dir: str) -> Optional[Tuple[str, str]]:
    """Search for any .exe under root_dir (recursive). Skip Uninstall/Redist and helper exes (e.g. GameLaunchHelper). Returns (full_path, display_name_from_file) or None."""
    skip_parts = ('uninstall', 'redist', 'redistribution', '_redist', 'vc_redist', 'dotnet', 'dxsetup')
    candidates = []
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for f in filenames:
            if f.lower().endswith('.exe') and not f.lower().startswith('uninstall'):
                if any(skip in f.lower() for skip in XBOX_SKIP_EXE_NAMES):
                    continue
                path = os.path.join(dirpath, f)
                if os.path.isfile(path):
                    rel = os.path.relpath(dirpath, root_dir).lower()
                    is_skip = any(part in rel for part in skip_parts)
                    display = os.path.splitext(f)[0].replace("_", " ").replace("-", " ")
                    candidates.append((path, display, is_skip))
    for path, display, is_skip in candidates:
        if not is_skip:
            return (os.path.normpath(path), display)
    return (os.path.normpath(candidates[0][0]), candidates[0][1]) if candidates else None


def _parse_microsoft_game_config(config_path: str, game_root: str) -> Optional[Tuple[str, str]]:
    """Parse MicrosoftGame.config; return (display_name, exe_filename) or None. exe_filename is just the name, not path."""
    try:
        tree = ET.parse(config_path)
        root = tree.getroot()
        ns = {}  # no namespace in these configs usually
        display_name = None
        exe_name = None
        # ShellVisuals DefaultDisplayName or Identity Name
        for tag in ("ShellVisuals", "Identity"):
            el = root.find(tag)
            if el is not None:
                display_name = el.get("DefaultDisplayName") or el.get("Name")
                if display_name:
                    break
        if not display_name:
            display_name = os.path.basename(game_root.rstrip(os.sep))
        # First Executable in ExecutableList (skip IsDevOnly if we can)
        exec_list = root.find("ExecutableList")
        if exec_list is not None:
            for exe_el in exec_list.findall("Executable"):
                if exe_el.get("IsDevOnly", "false").lower() == "true":
                    continue
                exe_name = exe_el.get("Name")
                if exe_name:
                    break
        if display_name and exe_name:
            return (display_name.strip(), exe_name.strip())
    except Exception as e:
        logging.debug(f"Parse MicrosoftGame.config {config_path}: {e}")
    return None


def load_installed_xbox_games(folders_str: str) -> Dict[str, Dict]:
    """
    Discover Xbox/Windows Store (Game Pass) games from .GamingRoot and configured folders.
    Prefers shell:appsFolder launch (StreamTweak pattern) when PackageFamily!AppId is known.
    Returns dict keyed by store_key or normalized exe path.
    """
    if os.name != 'nt':
        return {}
    roots = discover_xbox_roots(folders_str or "")
    lookup = build_windows_display_name_lookup()
    installed = {}
    for root_dir in roots:
        if not os.path.isdir(root_dir):
            logging.debug(f"Xbox games root not found: {root_dir}")
            continue
        for entry in os.listdir(root_dir):
            game_dir = os.path.join(root_dir, entry)
            if not os.path.isdir(game_dir):
                continue
            config_path = os.path.join(game_dir, "MicrosoftGame.config")
            content_config = os.path.join(game_dir, "Content", "MicrosoftGame.config")
            if not os.path.isfile(config_path) and os.path.isfile(content_config):
                config_path = content_config
            meta = parse_xbox_config(config_path, game_dir) if os.path.isfile(config_path) else None
            display_name = meta["display_name"] if meta else entry
            exe_name = meta["exe_name"] if meta else None
            store_id = meta["store_id"] if meta else None
            search_root = meta["config_dir"] if meta else game_dir
            exe_path = _find_exe_in_tree(search_root, exe_name) if exe_name else None
            if not exe_path:
                found = _find_any_exe_in_tree(search_root)
                if found:
                    exe_path, display_from_file = found
                    if not display_name or display_name == entry:
                        display_name = display_from_file
            if store_id:
                display_name = resolve_display_name(search_root, display_name, lookup)
                key = store_key("xbox", store_id)
                if store_id and "minecraft" in store_id.lower():
                    display_name = "Minecraft for Windows"
                installed[key] = {
                    "name": display_name,
                    "store": "Xbox",
                    "store_id": store_id,
                    "store_key": key,
                    "cmd": "",
                    "detached": f"explorer.exe shell:appsFolder\\{store_id}",
                    "exe_path": exe_path or search_root,
                }
                continue
            if not exe_path or not os.path.isfile(exe_path):
                continue
            if os.path.basename(exe_path).lower() == "minecraft.windows.exe":
                display_name = "Minecraft for Windows"
            exe_path_norm = os.path.normpath(exe_path)
            key = store_key("xbox", exe_path_norm.lower())
            installed[key] = {
                "name": display_name,
                "store": "Xbox",
                "store_key": key,
                "cmd": exe_path_norm,
                "detached": "",
                "exe_path": exe_path_norm,
            }
    logging.info(f"Found {len(installed)} Xbox/Windows games")
    return installed


def _app_gamesphere_store_key(app: Dict) -> Optional[str]:
    key = (app.get("_gamesphere_store_key") or "").strip()
    return key or None


def _build_store_sunshine_app(
    info: Dict,
    grid_path: Optional[str],
    shortcuts_folder: Optional[str] = None,
) -> Dict:
    """Build a Sunshine app entry from a unified store game dict."""
    store = info.get("store") or "Store"
    store_key_val = info.get("store_key") or store_key(store.lower(), info.get("name", "game"))
    name = info.get("name") or "Game"
    cmd = (info.get("cmd") or "").strip()
    detached = info.get("detached") or ""
    safe_id = "".join(c if c.isalnum() or c in "._-" else "_" for c in store_key_val)

    if shortcuts_folder and os.name == "nt" and cmd and os.path.sep in cmd:
        exe = cmd.strip('"')
        if os.path.isfile(exe):
            os.makedirs(shortcuts_folder, exist_ok=True)
            shortcut_path = os.path.join(shortcuts_folder, safe_id + ".lnk")
            work_dir = os.path.dirname(exe)
            if _create_shortcut_win(shortcut_path, exe, work_dir):
                cmd = _shortcut_launch_cmd(shortcut_path)
                detached = ""

    app: Dict = {
        "name": name,
        "output": "",
        "elevated": "false",
        "hidden": "true",
        "wait-all": "true",
        "exit-timeout": "5",
        "image-path": grid_path or "",
        "_gamesphere_store_key": store_key_val,
        "_gamesphere_store": store,
    }
    if detached and not cmd:
        app["cmd"] = ""
        app["detached"] = [detached] if isinstance(detached, str) else list(detached)
    else:
        app["cmd"] = cmd
        app["detached"] = ""
    return app


def process_existing_apps(
    sunshine_config: Dict,
    installed_games: Dict[str, str],
    installed_epic: Optional[Dict[str, Dict]] = None,
    custom_cmds: Optional[Set[str]] = None,
    installed_xbox: Optional[Dict[str, Dict]] = None,
    shortcuts_folder: Optional[str] = None,
    installed_stores: Optional[Dict[str, Dict]] = None,
) -> Tuple[List[Dict], List[Tuple[str, str]], List[Tuple[str, str]], List[Tuple[str, str]], Set[str], Set[str], Set[str], Set[str], int]:
    """Process existing Sunshine apps and identify changes."""
    updated_apps = []
    removed_steam = []
    removed_epic: List[Tuple[str, str]] = []
    removed_stores: List[Tuple[str, str]] = []
    existing_steam_apps: Set[str] = set()
    existing_epic_apps: Set[str] = set()
    existing_xbox_cmds: Set[str] = set()
    existing_store_keys: Set[str] = set()
    repaired_steam = 0
    installed_epic = installed_epic or {}
    custom_cmds = custom_cmds or set()
    installed_xbox = installed_xbox or {}
    installed_stores = installed_stores or {}
    shortcuts_folder_norm = os.path.normpath(shortcuts_folder) if shortcuts_folder else ""

    def _delete_shortcut_if_in_folder(shortcut_path: Optional[str]) -> None:
        if not shortcut_path or not shortcuts_folder_norm:
            return
        p = os.path.normpath(shortcut_path)
        if p.startswith(shortcuts_folder_norm) and os.path.isfile(p):
            try:
                os.remove(p)
                logging.debug(f"Removed shortcut: {p}")
            except Exception as e:
                logging.warning(f"Failed to remove shortcut {p}: {e}")

    for app in sunshine_config.get('apps', []):
        store_key_val = _app_gamesphere_store_key(app)
        if store_key_val:
            if store_key_val in installed_stores:
                updated_apps.append(app)
                existing_store_keys.add(store_key_val)
                if store_key_val.startswith("epic:"):
                    existing_epic_apps.add(store_key_val.split(":", 1)[1])
                elif store_key_val.startswith("xbox:"):
                    existing_xbox_cmds.add(store_key_val)
            else:
                removed_stores.append((app.get('name', 'Unknown'), store_key_val))
                grid_path = app.get('image-path')
                if grid_path and os.path.exists(grid_path):
                    try:
                        os.remove(grid_path)
                    except Exception as e:
                        logging.warning(f"Failed to remove grid image {grid_path}: {e}")
            continue

        cmd = (app.get('cmd') or '').strip()
        cmd_norm = os.path.normpath(cmd) if os.path.sep in cmd else cmd
        shortcut_path = _extract_shortcut_path_from_cmd(cmd) if shortcuts_folder_norm else None
        if shortcut_path and shortcuts_folder_norm and shortcut_path.startswith(shortcuts_folder_norm):
            target = _read_shortcut_target_win(shortcut_path)
            if target and 'com.epicgames.launcher://' in target:
                try:
                    prefix = "com.epicgames.launcher://apps/"
                    idx = target.find(prefix)
                    if idx != -1:
                        app_name = target[idx + len(prefix):].split('?')[0].split('/')[0].strip()
                        if app_name in installed_epic:
                            updated_apps.append(app)
                            existing_epic_apps.add(app_name)
                        else:
                            removed_epic.append((app.get('name', 'Unknown'), app_name))
                            _delete_shortcut_if_in_folder(shortcut_path)
                            grid_path = app.get('image-path')
                            if grid_path and os.path.exists(grid_path):
                                try:
                                    os.remove(grid_path)
                                    logging.debug(f"Removed grid image: {grid_path}")
                                except Exception as e:
                                    logging.warning(f"Failed to remove grid image {grid_path}: {e}")
                    else:
                        updated_apps.append(app)
                except Exception:
                    updated_apps.append(app)
            elif target and os.path.sep in target:
                target_norm = os.path.normpath(target)
                if target_norm in installed_xbox or target in installed_xbox:
                    updated_apps.append(app)
                    existing_xbox_cmds.add(target_norm if target_norm in installed_xbox else target)
                elif target in custom_cmds or target_norm in custom_cmds:
                    updated_apps.append(app)
                else:
                    updated_apps.append(app)
            else:
                updated_apps.append(app)
            continue
        app_id = _app_steam_app_id(app)
        if app_id:
            if app_id in installed_games:
                fixed = _repair_steam_app_entry(app)
                if fixed != app:
                    repaired_steam += 1
                app = fixed
                updated_apps.append(app)
                existing_steam_apps.add(app_id)
            else:
                removed_steam.append((app.get('name', 'Unknown'), app_id))
                grid_path = app.get('image-path')
                if grid_path and os.path.exists(grid_path):
                    try:
                        os.remove(grid_path)
                        logging.debug(f"Removed grid image: {grid_path}")
                    except Exception as e:
                        logging.warning(f"Failed to remove grid image {grid_path}: {e}")
        elif 'com.epicgames.launcher://' in cmd:
            # Extract AppName: com.epicgames.launcher://apps/AppName?action=...
            try:
                prefix = "com.epicgames.launcher://apps/"
                idx = cmd.find(prefix)
                if idx != -1:
                    rest = cmd[idx + len(prefix):]
                    app_name = rest.split('?')[0].split('/')[0].strip()
                    if app_name in installed_epic:
                        updated_apps.append(app)
                        existing_epic_apps.add(app_name)
                    else:
                        removed_epic.append((app.get('name', 'Unknown'), app_name))
                        grid_path = app.get('image-path')
                        if grid_path and os.path.exists(grid_path):
                            try:
                                os.remove(grid_path)
                                logging.debug(f"Removed grid image: {grid_path}")
                            except Exception as e:
                                logging.warning(f"Failed to remove grid image {grid_path}: {e}")
                else:
                    updated_apps.append(app)
            except Exception:
                updated_apps.append(app)
        elif cmd_norm in installed_xbox or cmd in installed_xbox:
            updated_apps.append(app)
            key = cmd_norm if cmd_norm in installed_xbox else cmd
            existing_xbox_cmds.add(key)
            info = installed_xbox.get(key) or {}
            sk = info.get("store_key")
            if sk:
                existing_store_keys.add(sk)
        elif any(
            info.get("cmd") == cmd or info.get("detached") == cmd
            for info in installed_xbox.values()
        ):
            updated_apps.append(app)
        elif cmd in custom_cmds:
            updated_apps.append(app)
        else:
            updated_apps.append(app)

    return (
        updated_apps,
        removed_steam,
        removed_epic,
        removed_stores,
        existing_steam_apps,
        existing_epic_apps,
        existing_xbox_cmds,
        existing_store_keys,
        repaired_steam,
    )

def add_new_games(new_games: Set[str], installed_games: Dict[str, str], api_key: str, grids_folder: str) -> List[Dict]:
    """Add new games with grid images using concurrent downloads."""
    new_apps = []
    
    if not new_games:
        return new_apps
    
    logging.info(f"Adding {len(new_games)} new Steam game(s)...")
    
    def process_game(app_id: str) -> Optional[Dict]:
        try:
            game_name = installed_games[app_id]
            grid_path = fetch_grid(app_id, api_key, grids_folder)
            new_app = _build_steam_app(app_id, game_name, grid_path)
            logging.info(f"Added Steam game: {game_name}")
            return new_app
        except Exception as e:
            logging.error(f"Error adding game {app_id}: {e}")
            return None
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_game, app_id): app_id for app_id in new_games}
        for future in as_completed(futures):
            result = future.result()
            if result:
                new_apps.append(result)
    
    return new_apps


def add_shortcut_games(
    new_bpids: Set[str],
    shortcuts: Dict[str, Dict[str, str]],
    api_key: str,
    grids_folder: str,
) -> List[Dict]:
    """Add Non-Steam Steam shortcuts (Eden/emu/etc.) as Sunshine apps via steam://rungameid."""
    new_apps: List[Dict] = []
    if not new_bpids:
        return new_apps

    logging.info(f"Adding {len(new_bpids)} Non-Steam shortcut(s)...")

    def process_shortcut(bpid: str) -> Optional[Dict]:
        try:
            info = shortcuts.get(bpid) or {}
            game_name = (info.get("name") or f"Non-Steam {bpid}").strip()
            platform = _platform_from_shortcut_exe(info.get("exe") or "")
            if platform:
                game_name = _ensure_platform_tag(game_name, platform)
            short_id = info.get("short_appid") or _steam_environ_app_id(bpid) or bpid
            grid_path = _copy_grid_to_sunshine(info.get("grid_src") or "", short_id, grids_folder)
            if not grid_path:
                grid_path = fetch_grid_by_name(game_name, api_key, grids_folder, f"shortcut_{short_id}")
            new_app = _build_steam_app(bpid, game_name, grid_path)
            logging.info(f"Added Non-Steam shortcut: {game_name}")
            return new_app
        except Exception as e:
            logging.error(f"Error adding Non-Steam shortcut {bpid}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_shortcut, bpid): bpid for bpid in new_bpids}
        for future in as_completed(futures):
            result = future.result()
            if result:
                new_apps.append(result)

    return new_apps


def _epic_launch_cmd(launch_id: str) -> Tuple[str, str]:
    """Return (cmd, detached) for Epic — protocol launch via detached (StreamTweak pattern)."""
    url = epic_launch_detached(launch_id)
    return "", url


def add_epic_games(
    new_epic_ids: Set[str],
    installed_epic: Dict[str, Dict],
    api_key: str,
    grids_folder: str,
    shortcuts_folder: Optional[str] = None,
) -> List[Dict]:
    """Add new Epic Games Store games with store-native or Steam-search cover art."""
    new_apps = []
    if not new_epic_ids:
        return new_apps
    logging.info(f"Adding {len(new_epic_ids)} Epic game(s)...")

    def _fallback(name, safe_id):
        return fetch_grid_by_name(name, api_key or '', grids_folder, safe_id)

    for app_name in new_epic_ids:
        try:
            info = installed_epic.get(app_name)
            if not info:
                continue
            game_name = info["name"]
            launch_id = info.get("launch_id") or app_name
            safe_id = "epic_" + "".join(c if c.isalnum() or c in "._-" else "_" for c in app_name)
            cover_info = {
                "name": game_name,
                "store": "Epic Games",
                "store_id": info.get("catalog_item_id"),
            }
            grid_path = fetch_store_cover(cover_info, grids_folder, safe_id, _fallback)
            cmd, detached = _epic_launch_cmd(launch_id)
            if shortcuts_folder and os.name == 'nt':
                os.makedirs(shortcuts_folder, exist_ok=True)
                shortcut_path = os.path.join(shortcuts_folder, safe_id + ".lnk")
                epic_url = epic_launch_detached(launch_id)
                if _create_shortcut_win(shortcut_path, epic_url):
                    cmd = _shortcut_launch_cmd(shortcut_path)
                    detached = ""
            entry = {
                "name": game_name,
                "store": "Epic Games",
                "store_key": info.get("store_key") or store_key("epic", app_name),
                "cmd": cmd,
                "detached": detached,
            }
            new_apps.append(_build_store_sunshine_app(entry, grid_path, None))
            logging.info(f"Added Epic: {game_name}")
        except Exception as e:
            logging.error(f"Error adding Epic game {app_name}: {e}")
    return new_apps


def add_custom_games(
    custom_list: List[Dict],
    existing_cmds: Set[str],
    api_key: str,
    grids_folder: str,
    shortcuts_folder: Optional[str] = None,
) -> List[Dict]:
    """Add custom games (from JSON) that are not already in config. If shortcuts_folder set (Windows), create .lnk and use that as cmd."""
    new_apps = []
    for g in custom_list:
        exe_cmd = g.get("cmd", "").strip()
        if not exe_cmd or exe_cmd in existing_cmds:
            continue
        name = (g.get("name") or "").strip() or "Custom Game"
        image_path = (g.get("image_path") or "").strip()
        if not image_path:
            safe_id = "custom_" + str(abs(hash(exe_cmd)))[:12]
            image_path = fetch_grid_by_name(name, api_key or '', grids_folder, safe_id) or ""
        if shortcuts_folder and os.name == 'nt' and os.path.sep in exe_cmd and os.path.isfile(exe_cmd):
            os.makedirs(shortcuts_folder, exist_ok=True)
            safe_id = "custom_" + str(abs(hash(exe_cmd)))[:12]
            shortcut_path = os.path.join(shortcuts_folder, safe_id + ".lnk")
            work_dir = os.path.dirname(exe_cmd)
            if _create_shortcut_win(shortcut_path, exe_cmd, work_dir):
                cmd = _shortcut_launch_cmd(shortcut_path)
            else:
                cmd = exe_cmd
        else:
            cmd = exe_cmd
        new_apps.append({
            "name": name,
            "cmd": cmd,
            "output": "",
            "detached": "",
            "elevated": "false",
            "hidden": "true",
            "wait-all": "true",
            "exit-timeout": "5",
            "image-path": image_path,
        })
        logging.info(f"Added custom: {name}")
    return new_apps


def add_xbox_games(
    new_xbox_keys: Set[str],
    installed_xbox: Dict[str, Dict],
    api_key: str,
    grids_folder: str,
    shortcuts_folder: Optional[str] = None,
) -> List[Dict]:
    """Add discovered Xbox/Windows games with store-native or Steam-search cover art."""
    new_apps = []
    if not new_xbox_keys:
        return new_apps
    logging.info(f"Adding {len(new_xbox_keys)} Xbox/Windows game(s)...")

    def _fallback(name, safe_id):
        return fetch_grid_by_name(name, api_key or '', grids_folder, safe_id)

    for key in new_xbox_keys:
        info = installed_xbox.get(key)
        if not info:
            continue
        try:
            name = info["name"]
            safe_id = "xbox_" + "".join(c if c.isalnum() or c in "._-" else "_" for c in key.replace(":", "_"))
            cover_info = {
                "name": name,
                "store": "Xbox",
                "store_id": info.get("store_id"),
            }
            grid_path = fetch_store_cover(cover_info, grids_folder, safe_id, _fallback)
            entry = dict(info)
            entry.setdefault("store_key", key)
            new_apps.append(_build_store_sunshine_app(entry, grid_path, shortcuts_folder))
            logging.info(f"Added Xbox/Windows: {name}")
        except Exception as e:
            logging.error(f"Error adding Xbox game {key}: {e}")
    return new_apps


def add_store_games(
    new_store_keys: Set[str],
    installed_stores: Dict[str, Dict],
    api_key: str,
    grids_folder: str,
    shortcuts_folder: Optional[str] = None,
) -> List[Dict]:
    """Add GOG, Ubisoft, Battle.net, and EA App titles."""
    new_apps = []
    if not new_store_keys:
        return new_apps
    logging.info(f"Adding {len(new_store_keys)} third-party store game(s)...")

    def _fallback(name, safe_id):
        return fetch_grid_by_name(name, api_key or '', grids_folder, safe_id)

    for key in sorted(new_store_keys):
        info = installed_stores.get(key)
        if not info:
            continue
        try:
            safe_id = key.replace(":", "_").replace("\\", "_").replace("/", "_")
            grid_path = fetch_store_cover(info, grids_folder, safe_id, _fallback)
            new_apps.append(_build_store_sunshine_app(info, grid_path, shortcuts_folder))
            logging.info("Added %s: %s", info.get("store"), info.get("name"))
        except Exception as e:
            logging.error(f"Error adding store game {key}: {e}")
    return new_apps


def get_stock_default_apps(host: str) -> List[Dict]:
    """
    Return the stock app list that Sunshine/Apollo ship with (per official docs).
    Used when "Remove all games" resets to host defaults. image-path is left empty
    so the host/client use their own default icons (desktop.png, steam.png, etc.).
    """
    host = (host or "sunshine").strip().lower()
    if host not in ("sunshine", "apollo"):
        host = "sunshine"

    def _app(
        name: str,
        cmd: str = "",
        output: str = "",
        detached: str = "",
        elevated: str = "false",
        hidden: str = "true",
        wait_all: str = "true",
        exit_timeout: str = "5",
        image_path: str = "",
        prep_do: str = "",
        prep_undo: str = "",
    ) -> Dict:
        app: Dict = {
            "name": name,
            "cmd": cmd,
            "output": output,
            "detached": detached,
            "elevated": elevated,
            "hidden": hidden,
            "wait-all": wait_all,
            "exit-timeout": exit_timeout,
            "image-path": image_path,
        }
        if prep_do or prep_undo:
            app["prep-cmd"] = [{"do": prep_do, "undo": prep_undo, "elevated": False}]
        return app

    # Desktop — stream the desktop (Sunshine app examples)
    desktop = _app("Desktop")

    # Steam Big Picture — official name/structure from Sunshine docs (Windows)
    if os.name == "nt":
        steam = _app(
            "Steam Big Picture",
            detached="steam://open/bigpicture",
            prep_do="steam://close/bigpicture",
            prep_undo="steam://open/bigpicture",
        )
    elif sys.platform == "darwin":
        steam = _app(
            "Steam Big Picture",
            detached="open steam://open/bigpicture",
            prep_do="open steam://close/bigpicture",
            prep_undo="open steam://open/bigpicture",
        )
    else:
        mode = _steam_mode()
        if mode == "flatpak":
            steam_detached = "flatpak run com.valvesoftware.Steam steam://open/bigpicture"
            steam_prep_do = "flatpak run com.valvesoftware.Steam steam://close/bigpicture"
            steam_prep_undo = "flatpak run com.valvesoftware.Steam steam://open/bigpicture"
        else:
            steam_detached = "setsid steam steam://open/bigpicture"
            steam_prep_do = "setsid steam steam://close/bigpicture"
            steam_prep_undo = "setsid steam steam://open/bigpicture"
        steam = _app(
            "Steam Big Picture",
            detached=steam_detached,
            prep_do=steam_prep_do,
            prep_undo=steam_prep_undo,
        )

    if host == "apollo":
        virtual_display = _app("Virtual Display")
        return [desktop, steam, virtual_display]
    return [desktop, steam]


def remove_all_apps_from_config(
    apps_json_path: str,
    grids_folder: str,
    host: str = "sunshine",
    shortcuts_folder: Optional[str] = None,
) -> int:
    """
    Remove all games and manually added apps, then restore the stock default apps
    that Sunshine/Apollo ship with (Desktop, Steam Big Picture, and for Apollo Virtual Display).
    Uses official structure with empty image-path so the host uses its own icons.
    If shortcuts_folder is set, deletes all .lnk files in it.
    Returns the number of apps that were removed.
    """
    config = get_sunshine_config(apps_json_path)
    apps = config.get('apps', [])
    removed_count = len(apps)

    # Delete thumbnails for removed apps when they live in our grids folder
    grids_folder_abs = os.path.abspath(grids_folder) if grids_folder else ""
    for app in apps:
        grid_path = app.get('image-path')
        if grid_path and os.path.exists(grid_path):
            if grids_folder_abs and os.path.abspath(os.path.dirname(grid_path)) == grids_folder_abs:
                try:
                    os.remove(grid_path)
                    logging.debug(f"Removed grid image: {grid_path}")
                except Exception as e:
                    logging.warning(f"Failed to remove grid image {grid_path}: {e}")

    # Remove any other PNGs in the grids folder (orphaned thumbnails)
    if os.path.isdir(grids_folder):
        try:
            for name in os.listdir(grids_folder):
                if name.lower().endswith('.png'):
                    path = os.path.join(grids_folder, name)
                    try:
                        os.remove(path)
                        logging.debug(f"Removed grid image: {path}")
                    except Exception as e:
                        logging.warning(f"Failed to remove {path}: {e}")
        except OSError as e:
            logging.warning(f"Could not list grids folder {grids_folder}: {e}")

    # Remove all generated shortcuts when using a shortcuts folder
    if shortcuts_folder and os.path.isdir(shortcuts_folder):
        try:
            for name in os.listdir(shortcuts_folder):
                if name.lower().endswith('.lnk'):
                    path = os.path.join(shortcuts_folder, name)
                    try:
                        os.remove(path)
                        logging.debug(f"Removed shortcut: {path}")
                    except Exception as e:
                        logging.warning(f"Failed to remove {path}: {e}")
        except OSError as e:
            logging.warning(f"Could not list shortcuts folder {shortcuts_folder}: {e}")

    # Restore stock defaults (Desktop, Steam Big Picture, Virtual Display for Apollo)
    default_apps = get_stock_default_apps(host)
    config['apps'] = default_apps
    save_sunshine_config(apps_json_path, config)
    default_names = [a.get('name', '') for a in default_apps]
    logging.info(f"Removed {removed_count} app(s). Restored stock apps: {default_names}.")
    return removed_count


def main() -> None:
    """Main application function."""
    parser = argparse.ArgumentParser(description='Sunshine Steam Game Automation')
    parser.add_argument('--version', action='version', version=f'GameSphere Import Tool {__version__}')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--no-restart', action='store_true', help='Skip starting Steam (if not running) and skip restarting Sunshine/Apollo')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--remove-games', action='store_true', help='Remove all games (Steam + manually added); keep only stock apps Desktop, Steam, Virtual Display')
    parser.add_argument('--auto-config', action='store_true', help='Write a .env file from auto-detected paths and exit')
    parser.add_argument('--print-config', action='store_true', help='Print auto-detected paths as JSON and exit')
    parser.add_argument('--check-update', action='store_true', help='Check GitHub Releases for a newer version and exit')
    parser.add_argument('--apply-update', action='store_true', help='Install the newest GitHub Release for this platform')
    parser.add_argument('--host-tuning', action='store_true', help='Apply host tuning after import (tiles, prep scripts, NVIDIA snapshot)')
    parser.add_argument('--host-tuning-only', action='store_true', help='Apply host tuning and exit (no library import)')
    parser.add_argument('--host-bridge', action='store_true', help='Run GameSphere TCP bridge (port 47998) and session monitor')
    parser.add_argument(
        '--setup-mic',
        action='store_true',
        help='Set up Mic to PC (VBAN receive): VB-CABLE + feeder on Windows, PipeWire on Linux',
    )
    parser.add_argument(
        '--setup-mic-info',
        action='store_true',
        help='Print Mic to PC LAN IP / defaults without installing',
    )
    parser.add_argument(
        '--accept-vbaudio-license',
        action='store_true',
        help='Required with --setup-mic on Windows (accepts VB-Audio Cable donationware terms)',
    )
    parser.add_argument(
        '--vban-feeder',
        action='store_true',
        help='Run the Windows VBAN→CABLE Input feeder (started by --setup-mic)',
    )
    parser.add_argument(
        '--vban-feeder-stop',
        action='store_true',
        help='Stop a running GameSphere VBAN feeder',
    )
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.verbose)

    if args.vban_feeder or args.vban_feeder_stop:
        from vban_feeder import main as feeder_main, stop_feeder

        if args.vban_feeder_stop:
            sys.exit(stop_feeder(lambda m: logging.info("%s", m)))
        sys.exit(feeder_main([]))

    if args.setup_mic or args.setup_mic_info:
        from mic_setup import setup_mic

        result = setup_mic(
            accept_third_party=bool(args.accept_vbaudio_license),
            info_only=bool(args.setup_mic_info),
            log=lambda m: logging.info("%s", m.rstrip()),
        )
        print(result.summary())
        if result.needs_license_accept and not args.setup_mic_info:
            logging.error(
                "Windows mic setup downloads VB-CABLE (VB-Audio donationware). "
                "Re-run with --accept-vbaudio-license after you accept their terms."
            )
            sys.exit(2)
        sys.exit(0 if result.ok else 1)

    if args.check_update or args.apply_update:
        from gs_updater import cli_check
        sys.exit(cli_check(apply=args.apply_update))

    if args.host_tuning_only or args.host_bridge:
        from host_tuning.service import apply_host_tuning, write_prep_scripts
        if args.host_bridge:
            from host_tuning.bridge import GameSphereBridge
            from host_tuning import session_telemetry
            from host_tuning.config import load_config
            cfg = load_config()
            write_prep_scripts()
            apply_detected_paths()
            apps_json = (
                os.environ.get("SUNSHINE_APPS_JSON_PATH")
                or os.environ.get("sunshine_apps_json_path")
                or ""
            )
            bridge = GameSphereBridge()
            log_path = session_telemetry.detect_sunshine_log_path(cfg.sunshine_log_path)
            bridge.start(port=cfg.bridge_port, log_path=log_path, apps_json_path=apps_json)
            logging.info("Host bridge on TCP %s — Ctrl+C to stop", cfg.bridge_port)
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                bridge.stop()
            return
        config = validate_config()
        write_prep_scripts()
        results = apply_host_tuning(sunshine_apps_json=config.get('SUNSHINE_APPS_JSON_PATH', ''))
        logging.info("Host tuning: %s", results)
        if args.host_tuning_only:
            return

    if args.print_config:
        detected = detect_paths()
        if not detected:
            print(json.dumps({"error": "Could not detect Steam/Sunshine paths"}, indent=2))
            sys.exit(1)
        print(json.dumps(paths_to_env(detected), indent=2))
        return

    if args.auto_config:
        detected = detect_paths()
        if not detected:
            logging.error("Could not detect Steam/Sunshine paths on this machine")
            sys.exit(1)
        env_path = write_env_file(detected)
        logging.info("Wrote %s for %s", env_path, detected.host_label)
        print(f"Created {env_path}")
        return

    logging.info("Starting Sunshine Steam Game Automation")
    
    try:
        # Load and validate configuration
        config = validate_config()
        
        if args.remove_games:
            host_name = os.getenv("HOST", "sunshine").strip()
            if host_name.lower() not in ("sunshine", "apollo"):
                host_name = "sunshine"
            host_name = host_name.capitalize()
            logging.info(f"Removing all Steam games from {host_name}")
            removed = remove_all_apps_from_config(
                config['SUNSHINE_APPS_JSON_PATH'],
                config['SUNSHINE_GRIDS_FOLDER'],
                host=host_name.lower(),
                shortcuts_folder=config.get('SUNSHINE_SHORTCUTS_FOLDER') or '',
            )
            if not args.no_restart:
                restart_sunshine(config['SUNSHINE_EXE_PATH'])
            logging.info("Remove-games completed successfully")
            wasteland_msg = f"Games removed. Your {host_name} is now a barren wasteland where joy and whimsy go to die."
            print()
            print("=" * 70)
            print(f"  {wasteland_msg}")
            print("=" * 70)
            print()
            print(f"BANNER:{wasteland_msg}")
            return
        # ----- normal import flow below -----

        if not args.dry_run:
            helper = ensure_steam_close_helper()
            if helper:
                logging.info("Quit App close helper: %s", helper)
        
        # Start Steam only if not already running (unless disabled)
        if not args.no_restart:
            ensure_steam_running(config['STEAM_EXE_PATH'])
        
        # Load installed games (Steam store library)
        installed_games = load_installed_games(config['STEAM_LIBRARY_VDF_PATH'])
        # Non-Steam shortcuts (Eden / emu / custom Steam tiles)
        installed_shortcuts = load_steam_nonsteam_shortcuts(config['STEAM_LIBRARY_VDF_PATH'])
        # Merge so process_existing_apps keeps shortcut entries and prunes removed ones
        steam_catalog: Dict[str, str] = dict(installed_games)
        for bpid, info in installed_shortcuts.items():
            steam_catalog[bpid] = info.get("name") or bpid
        
        # Load Epic games (Windows only, if path set)
        installed_epic = {}
        if config.get('EPIC_MANIFESTS_PATH') and os.name == 'nt':
            installed_epic = load_installed_epic_games(config['EPIC_MANIFESTS_PATH'])
        
        # Load GOG, Ubisoft, Battle.net, EA (Windows)
        installed_third_party = {}
        if os.name == 'nt':
            installed_third_party = load_all_third_party_stores()
        
        # Load custom games (from JSON if path set)
        custom_list = load_custom_games(config.get('CUSTOM_GAMES_JSON_PATH', '') or '')
        custom_cmds = {g["cmd"] for g in custom_list}
        
        # Load Xbox/Windows games (.GamingRoot + configured folders)
        installed_xbox = {}
        if os.name == 'nt':
            installed_xbox = load_installed_xbox_games(config.get('XBOX_GAMES_FOLDERS', ''))

        # Unified store catalog for prune/add (Epic + Xbox + other stores)
        installed_stores: Dict[str, Dict] = {}
        for app_name, info in installed_epic.items():
            sk = info.get("store_key") or store_key("epic", app_name)
            info = dict(info)
            info["store_key"] = sk
            installed_stores[sk] = info
        installed_stores.update(installed_xbox)
        installed_stores.update(installed_third_party)
        
        # Load Sunshine configuration
        sunshine_config = get_sunshine_config(config['SUNSHINE_APPS_JSON_PATH'])
        
        # Ensure grids folder exists
        os.makedirs(config['SUNSHINE_GRIDS_FOLDER'], exist_ok=True)
        
        # Process existing apps (Steam store + Non-Steam shortcuts, Epic, custom, Xbox, other stores)
        shortcuts_folder = config.get('SUNSHINE_SHORTCUTS_FOLDER') or ''
        (
            updated_apps,
            removed_steam,
            removed_epic,
            removed_stores,
            existing_steam_apps,
            existing_epic_apps,
            existing_xbox_cmds,
            existing_store_keys,
            repaired_steam,
        ) = process_existing_apps(
            sunshine_config,
            steam_catalog,
            installed_epic,
            custom_cmds,
            installed_xbox,
            shortcuts_folder,
            installed_stores,
        )
        
        # Find new games to add
        new_games = set(installed_games.keys()) - existing_steam_apps
        new_shortcuts = set(installed_shortcuts.keys()) - existing_steam_apps
        new_epic = set(installed_epic.keys()) - existing_epic_apps
        new_xbox = set(installed_xbox.keys()) - existing_xbox_cmds
        new_store = {k for k in installed_third_party.keys() if k not in existing_store_keys}
        existing_cmds = {app.get('cmd', '').strip() for app in updated_apps}
        existing_cmds_norm = {os.path.normpath(c) for c in existing_cmds if os.path.sep in c}
        existing_cmds |= existing_cmds_norm
        new_custom = [g for g in custom_list if g["cmd"].strip() not in existing_cmds and os.path.normpath(g["cmd"].strip()) not in existing_cmds]
        
        # Log changes
        if removed_steam:
            logging.info(f"Steam games to remove: {[name for name, _ in removed_steam]}")
        if removed_epic:
            logging.info(f"Epic games to remove: {[name for name, _ in removed_epic]}")
        if removed_stores:
            logging.info(f"Store games to remove: {[name for name, _ in removed_stores]}")
        if new_games:
            logging.info(f"New Steam games to add: {[installed_games[app_id] for app_id in new_games]}")
        if new_shortcuts:
            logging.info(
                "New Non-Steam shortcuts to add: %s",
                [installed_shortcuts[b]["name"] for b in new_shortcuts],
            )
        if new_epic:
            logging.info(f"New Epic games to add: {[installed_epic[aid]['name'] for aid in new_epic]}")
        if new_xbox:
            logging.info(f"New Xbox/Windows games to add: {[installed_xbox[c]['name'] for c in new_xbox]}")
        if new_store:
            logging.info(
                "New store games to add: %s",
                [installed_third_party[k]["name"] for k in sorted(new_store)],
            )
        if new_custom:
            logging.info(f"New custom games to add: {[g['name'] for g in new_custom]}")
        
        if repaired_steam:
            logging.info(
                "Repaired %d Steam app(s) (detached launch and/or Quit App close undo)",
                repaired_steam,
            )

        # Tag existing Non-Steam Sunshine apps from shortcuts.vdf exe (Eden → Switch, etc.)
        # so GameSphere can shelf by launch backend without seeing the host cmd.
        retagged = _retag_nonsteam_app_names(updated_apps, installed_shortcuts)
        if retagged:
            logging.info("Tagged %d Non-Steam app(s) with GameSphere platform suffixes", retagged)

        if (
            not removed_steam
            and not removed_epic
            and not removed_stores
            and not new_games
            and not new_shortcuts
            and not new_epic
            and not new_xbox
            and not new_store
            and not new_custom
            and not repaired_steam
            and not retagged
        ):
            logging.info("No changes needed - all games are up to date")
            return
        
        if args.dry_run:
            logging.info("Dry run mode - no changes will be made")
            return
        
        # Add new Steam store games
        new_steam_apps = add_new_games(new_games, installed_games, config['STEAMGRIDDB_API_KEY'], config['SUNSHINE_GRIDS_FOLDER'])
        updated_apps.extend(new_steam_apps)
        # Add Non-Steam shortcuts (Eden / emu / etc.)
        new_shortcut_apps = add_shortcut_games(
            new_shortcuts,
            installed_shortcuts,
            config['STEAMGRIDDB_API_KEY'],
            config['SUNSHINE_GRIDS_FOLDER'],
        )
        updated_apps.extend(new_shortcut_apps)
        # Add new Epic games
        new_epic_apps = add_epic_games(new_epic, installed_epic, config['STEAMGRIDDB_API_KEY'], config['SUNSHINE_GRIDS_FOLDER'], shortcuts_folder)
        updated_apps.extend(new_epic_apps)
        # Add new Xbox/Windows games
        new_xbox_apps = add_xbox_games(new_xbox, installed_xbox, config['STEAMGRIDDB_API_KEY'], config['SUNSHINE_GRIDS_FOLDER'], shortcuts_folder)
        updated_apps.extend(new_xbox_apps)
        # Add GOG / Ubisoft / Battle.net / EA
        new_store_apps = add_store_games(new_store, installed_third_party, config['STEAMGRIDDB_API_KEY'], config['SUNSHINE_GRIDS_FOLDER'], shortcuts_folder)
        updated_apps.extend(new_store_apps)
        # Add new custom games
        new_custom_apps = add_custom_games(custom_list, existing_cmds, config['STEAMGRIDDB_API_KEY'], config['SUNSHINE_GRIDS_FOLDER'], shortcuts_folder)
        updated_apps.extend(new_custom_apps)
        
        # Update and save configuration
        sunshine_config['apps'] = updated_apps
        save_sunshine_config(config['SUNSHINE_APPS_JSON_PATH'], sunshine_config)
        
        # Restart Sunshine after processing (unless disabled)
        if not args.no_restart:
            restart_sunshine(config['SUNSHINE_EXE_PATH'])
        
        logging.info("Sunshine apps.json update process completed successfully")
        if args.host_tuning:
            from host_tuning.service import apply_host_tuning, write_prep_scripts
            write_prep_scripts()
            tuning = apply_host_tuning(sunshine_apps_json=config['SUNSHINE_APPS_JSON_PATH'])
            logging.info("Host tuning applied: %s", tuning)
        host_display = os.getenv("HOST", "sunshine").strip()
        if host_display.lower() not in ("sunshine", "apollo"):
            host_display = "sunshine"
        host_display = host_display.capitalize()
        spherical_msg = f"Your {host_display} is now SPHERICAL!"
        print()
        print("=" * 70)
        print(f"  {spherical_msg}")
        print("=" * 70)
        print()
        print(f"BANNER:{spherical_msg}")
        
    except KeyboardInterrupt:
        logging.info("Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
