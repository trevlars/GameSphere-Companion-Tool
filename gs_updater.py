"""Check GitHub Releases and apply an in-app update (no token; public repo)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from gs_version import (
    GITHUB_LATEST_API,
    GITHUB_OWNER,
    GITHUB_RELEASES_API,
    GITHUB_RELEASES_PAGE,
    GITHUB_REPO,
    __version__,
)

USER_AGENT = f"GameSphere-Import-Tool/{__version__}"


def parse_version(tag: str) -> Tuple[int, int, int]:
    raw = (tag or "").strip().lstrip("vV")
    parts: List[int] = []
    for chunk in raw.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits or "0"))
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def _http_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str, dest: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)


def current_platform() -> str:
    if sys.platform == "win32":
        return "win"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "mac"
    return sys.platform


def pick_asset(assets: List[Dict[str, Any]], platform: str) -> Optional[Dict[str, Any]]:
    named = [(a.get("name") or "", a) for a in assets if a.get("browser_download_url")]
    if platform == "win":
        for name, asset in named:
            if name.lower() == "gamesphereimporttool.exe":
                return asset
        for name, asset in named:
            if name.lower().endswith(".exe"):
                return asset
    if platform == "linux":
        for name, asset in named:
            if name == "io.github.trevlars.GamesphereImportTool.flatpak":
                return asset
        for name, asset in named:
            if name.lower().endswith(".appimage"):
                return asset
        for name, asset in named:
            if name.lower() == "install-linux.sh":
                return asset
    return None


def fetch_newest_release() -> Optional[Dict[str, Any]]:
    """Highest non-draft, non-prerelease tag (not only GitHub's Latest flag)."""
    releases: List[Dict[str, Any]] = []
    try:
        latest = _http_json(GITHUB_LATEST_API)
        if isinstance(latest, dict) and latest.get("tag_name"):
            releases.append(latest)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        pass
    try:
        more = _http_json(GITHUB_RELEASES_API + "?per_page=20")
        if isinstance(more, list):
            releases.extend(more)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        if not releases:
            return None
    best: Optional[Dict[str, Any]] = None
    best_ver = (0, 0, 0)
    seen = set()
    for rel in releases:
        tag = str(rel.get("tag_name") or "")
        if not tag or tag in seen:
            continue
        seen.add(tag)
        if rel.get("draft") or rel.get("prerelease"):
            continue
        ver = parse_version(tag)
        if best is None or ver > best_ver:
            best = rel
            best_ver = ver
    return best


def check_for_update() -> Dict[str, Any]:
    """Return a status dict: current, latest, newer, notes, asset, html_url, error."""
    out: Dict[str, Any] = {
        "current": __version__,
        "latest": None,
        "newer": False,
        "notes": "",
        "asset": None,
        "html_url": GITHUB_RELEASES_PAGE,
        "error": None,
        "platform": current_platform(),
    }
    try:
        rel = fetch_newest_release()
    except Exception as exc:
        out["error"] = str(exc)
        return out
    if not rel:
        out["error"] = "Could not read GitHub Releases"
        return out
    tag = str(rel.get("tag_name") or "")
    out["latest"] = tag.lstrip("vV")
    out["notes"] = (rel.get("body") or "").strip()
    out["html_url"] = rel.get("html_url") or GITHUB_RELEASES_PAGE
    out["newer"] = is_newer(tag, __version__)
    out["asset"] = pick_asset(rel.get("assets") or [], out["platform"])
    out["tag"] = tag
    return out


def linux_install_dir() -> str:
    return os.path.expanduser(
        os.environ.get("GAMESPHERE_IMPORT_DIR") or "~/.local/share/gamesphere-import-tool"
    )


def apply_windows_update(asset: Dict[str, Any]) -> str:
    """Download the new exe and spawn a helper that replaces this process after exit."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Windows auto-update replaces GamesphereImportTool.exe (frozen build).")
    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("Release has no Windows .exe asset yet.")
    target = os.path.abspath(sys.executable)
    tmp_dir = tempfile.mkdtemp(prefix="gs-import-upd-")
    new_exe = os.path.join(tmp_dir, "GamesphereImportTool.exe")
    _download(url, new_exe)
    bat = os.path.join(tmp_dir, "apply-update.bat")
    # Wait for this PID to exit, swap the exe, relaunch.
    bat_body = (
        "@echo off\r\n"
        "setlocal\r\n"
        f"set TARGET={target}\r\n"
        f"set SOURCE={new_exe}\r\n"
        f"set PID={os.getpid()}\r\n"
        ":wait\r\n"
        "tasklist /FI \"PID eq %PID%\" 2>nul | findstr /I /C:\" %PID% \" >nul\r\n"
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        "copy /Y \"%SOURCE%\" \"%TARGET%\" >nul\r\n"
        "start \"\" \"%TARGET%\"\r\n"
        "del \"%SOURCE%\" >nul 2>&1\r\n"
        "del \"%~f0\" >nul 2>&1\r\n"
    )
    with open(bat, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(bat_body)
    flags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        flags |= subprocess.DETACHED_PROCESS
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        ["cmd.exe", "/c", bat],
        close_fds=True,
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return target


def apply_linux_update(tag: str, asset: Optional[Dict[str, Any]] = None) -> str:
    """Apply update via Flatpak bundle, AppImage-friendly shell installer, or git checkout."""
    if asset and asset.get("browser_download_url"):
        name = (asset.get("name") or "").lower()
        url = asset["browser_download_url"]
        if name.endswith(".flatpak"):
            bundle = os.path.join(tempfile.mkdtemp(prefix="gs-import-upd-"), "update.flatpak")
            _download(url, bundle)
            subprocess.run(
                ["flatpak", "install", "--user", "-y", bundle],
                check=True,
            )
            return "flatpak:io.github.trevlars.GamesphereImportTool"
        if name.endswith(".appimage"):
            dest = os.path.expanduser("~/.local/bin/GameSphere-Import-Tool.AppImage")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            _download(url, dest)
            os.chmod(dest, 0o755)
            return dest
        if name == "install-linux.sh":
            tmp = tempfile.mkdtemp(prefix="gs-import-upd-")
            script = os.path.join(tmp, "install-linux.sh")
            _download(url, script)
            os.chmod(script, 0o755)
            env = os.environ.copy()
            env["GAMESPHERE_IMPORT_REF"] = tag
            env["GAMESPHERE_IMPORT_DIR"] = linux_install_dir()
            subprocess.run(["bash", script], check=True, env=env)
            return linux_install_dir()

    # Fallback: shell installer from tag
    install_dir = linux_install_dir()
    script = None
    if asset and asset.get("browser_download_url"):
        tmp = tempfile.mkdtemp(prefix="gs-import-upd-")
        script = os.path.join(tmp, "install-linux.sh")
        _download(asset["browser_download_url"], script)
        os.chmod(script, 0o755)
    elif os.path.isfile(os.path.join(install_dir, "scripts", "install-linux.sh")):
        script = os.path.join(install_dir, "scripts", "install-linux.sh")
    else:
        # Last resort: fetch the raw installer from the tag.
        raw = (
            f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
            f"{tag}/scripts/install-linux.sh"
        )
        tmp = tempfile.mkdtemp(prefix="gs-import-upd-")
        script = os.path.join(tmp, "install-linux.sh")
        _download(raw, script)
        os.chmod(script, 0o755)
    env = os.environ.copy()
    env["GAMESPHERE_IMPORT_REF"] = tag
    env["GAMESPHERE_IMPORT_DIR"] = install_dir
    subprocess.run(["bash", script], check=True, env=env)
    return install_dir


def apply_update(info: Dict[str, Any]) -> str:
    tag = str(info.get("tag") or info.get("latest") or "")
    if not tag:
        raise RuntimeError("No release tag to install.")
    if not tag.startswith("v"):
        tag = "v" + tag
    platform = info.get("platform") or current_platform()
    asset = info.get("asset")
    if platform == "win":
        return apply_windows_update(asset or {})
    if platform == "linux":
        return apply_linux_update(tag, asset)
    raise RuntimeError(
        f"In-app update is not wired for this platform. Download from {GITHUB_RELEASES_PAGE}"
    )


def format_notice(info: Dict[str, Any]) -> str:
    if info.get("error"):
        return f"Update check failed: {info['error']}"
    if not info.get("newer"):
        return f"GameSphere Import Tool {info['current']} is up to date."
    latest = info.get("latest") or info.get("tag")
    return (
        f"Version {latest} is available (you have {info['current']}).\n"
        f"{info.get('html_url') or GITHUB_RELEASES_PAGE}"
    )


def cli_check(apply: bool = False) -> int:
    info = check_for_update()
    print(format_notice(info))
    if info.get("error"):
        return 1
    if not info.get("newer"):
        return 0
    if not apply:
        print("Run with --apply-update to install, or use Check for updates in the GUI.")
        return 0
    try:
        dest = apply_update(info)
        print(f"Updated to {info.get('latest')}. Installed at {dest}")
        return 0
    except Exception as exc:
        print(f"Update failed: {exc}", file=sys.stderr)
        print(f"Download manually: {info.get('html_url') or GITHUB_RELEASES_PAGE}", file=sys.stderr)
        return 1
