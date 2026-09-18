"""Check GitHub Releases and apply an in-app update (no token; public repo)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
FLATPAK_ID = "io.github.trevlars.GamesphereImportTool"
APPIMAGE_RELEASE_NAME = "GameSphere-Import-Tool-x86_64.AppImage"
APPIMAGE_LEGACY_NAME = "GameSphere-Import-Tool.AppImage"


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


def auto_update_mode() -> str:
    """How unattended updates should behave: off | prompt | apply."""
    if os.environ.get("GAMESPHERE_SKIP_UPDATE_CHECK", "").strip() == "1":
        return "off"
    val = os.environ.get("GAMESPHERE_AUTO_UPDATE", "").strip().lower()
    if val in ("0", "false", "no", "off"):
        return "off"
    if val in ("apply", "force"):
        return "apply"
    return "prompt"


def auto_update_enabled() -> bool:
    return auto_update_mode() != "off"


_UPDATE_SERVICE_BODY = """[Unit]
Description=GameSphere Import Tool auto-update from GitHub Releases
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Nice=10
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=%h/.local/bin/gamesphere-import-update.sh

[Install]
WantedBy=default.target
"""

_UPDATE_TIMER_BODY = """[Unit]
Description=Daily GameSphere Import Tool update check

[Timer]
OnBootSec=5min
OnUnitActiveSec=24h
Persistent=true
RandomizedDelaySec=10min

[Install]
WantedBy=timers.target
"""


def _linux_unit_dir() -> str:
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(xdg, "systemd", "user")


def _linux_update_bin() -> str:
    return os.path.expanduser(
        os.environ.get("GAMESPHERE_UPDATE_BIN") or "~/.local/bin/gamesphere-import-update.sh"
    )


def _copy_or_write(src: Optional[str], dest: str, body: str, mode: int = 0o644) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if src and os.path.isfile(src):
        shutil.copy2(src, dest)
    elif body:
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(body)
    else:
        return
    os.chmod(dest, mode)


def _enable_linger() -> str:
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if not user:
        try:
            import pwd

            user = pwd.getpwuid(os.getuid()).pw_name
        except Exception:
            return ""
    loginctl = shutil.which("loginctl")
    if not loginctl:
        return ""
    try:
        shown = subprocess.run(
            [loginctl, "show-user", user, "-p", "Linger", "--value"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if (shown.stdout or "").strip() == "yes":
            return "linger=yes"
        subprocess.run(
            [loginctl, "enable-linger", user],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        os.environ.setdefault("XDG_RUNTIME_DIR", runtime)
        os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
        bus = os.path.join(runtime, "bus")
        for _ in range(10):
            if os.path.exists(bus):
                break
            time.sleep(0.4)
        return f"linger-enabled:{user}"
    except Exception:
        return ""


def ensure_linux_unattended_update() -> str:
    """Install the systemd user timer so new Linux installs update without SSH."""
    if not sys.platform.startswith("linux"):
        return ""
    if auto_update_mode() == "off":
        return "auto-update off"
    if os.environ.get("GAMESPHERE_SKIP_UPDATE_TIMER", "").strip() == "1":
        return "timer enable skipped (self-update)"
    if not shutil.which("systemctl"):
        return "no systemctl"
    checkout = source_checkout_dir() or linux_install_dir()
    scripts = os.path.join(checkout, "scripts")
    unit_src = os.path.join(scripts, "systemd")
    update_src = os.path.join(scripts, "gamesphere-import-update.sh")
    unit_dir = _linux_unit_dir()
    update_bin = _linux_update_bin()
    try:
        if os.path.isfile(update_src):
            _copy_or_write(update_src, update_bin, "", 0o755)
        elif not os.path.isfile(update_bin):
            raw = (
                f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
                "main/scripts/gamesphere-import-update.sh"
            )
            _download(raw, update_bin)
            os.chmod(update_bin, 0o755)
        if not os.path.isfile(update_bin):
            return "update script missing"
        _copy_or_write(
            os.path.join(unit_src, "gamesphere-import-update.service")
            if os.path.isfile(os.path.join(unit_src, "gamesphere-import-update.service"))
            else None,
            os.path.join(unit_dir, "gamesphere-import-update.service"),
            _UPDATE_SERVICE_BODY,
        )
        _copy_or_write(
            os.path.join(unit_src, "gamesphere-import-update.timer")
            if os.path.isfile(os.path.join(unit_src, "gamesphere-import-update.timer"))
            else None,
            os.path.join(unit_dir, "gamesphere-import-update.timer"),
            _UPDATE_TIMER_BODY,
        )
        if os.path.isdir(os.path.join(checkout, ".git")):
            env_dir = os.path.join(
                os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                "environment.d",
            )
            os.makedirs(env_dir, exist_ok=True)
            env_file = os.path.join(env_dir, "50-gamesphere-import-path.conf")
            home = os.path.expanduser("~")
            with open(env_file, "w", encoding="utf-8") as fh:
                fh.write(
                    "# Prefer git/Decky ~/.local/bin/gamesphere-import over leftover Flatpak.\n"
                    f"PATH={home}/.local/bin:$PATH\n"
                )
        linger = _enable_linger()
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            timeout=15,
            check=False,
        )
        enabled = subprocess.run(
            ["systemctl", "--user", "enable", "--now", "gamesphere-import-update.timer"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        extra = f" ({linger})" if linger else ""
        timer_msg = ""
        if enabled.returncode == 0:
            timer_msg = f"gamesphere-import-update.timer enabled{extra}"
        else:
            err = (enabled.stderr or enabled.stdout or "").strip()
            timer_msg = f"timer not enabled: {err or 'systemctl --user failed'}"
        try:
            from host_tuning.host_daemon import ensure_running

            daemon = ensure_running()
            if daemon.get("skipped"):
                return f"{timer_msg}; host-bridge skipped"
            if daemon.get("ok") or daemon.get("enabled"):
                return f"{timer_msg}; gamesphere-host-bridge enabled"
            return f"{timer_msg}; host-bridge: {daemon.get('output') or daemon}"
        except Exception as exc:
            return f"{timer_msg}; host-bridge skipped: {exc}"
    except Exception as exc:
        return f"timer install skipped: {exc}"


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


def _download(url: str, dest: str, expected_size: int = 0) -> None:
    """Download to ``dest`` and refuse to accept a truncated or empty file.

    A half-downloaded asset used to be installed as if it were valid, which
    could leave the user with an unlaunchable binary.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    written = os.path.getsize(dest)
    if written <= 0:
        raise RuntimeError(f"Download was empty: {url}")
    if expected_size and written != expected_size:
        raise RuntimeError(
            f"Download is incomplete ({written} of {expected_size} bytes). "
            "Check the connection and try again."
        )


def _asset_size(asset: Optional[Dict[str, Any]]) -> int:
    try:
        return int((asset or {}).get("size") or 0)
    except (TypeError, ValueError):
        return 0


def _verify_windows_exe(path: str) -> None:
    """Reject anything that is not a Windows executable (e.g. an HTML error page)."""
    try:
        with open(path, "rb") as fh:
            magic = fh.read(2)
    except OSError as exc:
        raise RuntimeError(f"Could not read the downloaded update: {exc}") from exc
    if magic != b"MZ":
        raise RuntimeError(
            "The downloaded file is not a Windows program. "
            f"Download it manually from {GITHUB_RELEASES_PAGE}"
        )


def current_platform() -> str:
    if sys.platform == "win32":
        return "win"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "mac"
    return sys.platform


def linux_install_dir() -> str:
    return os.path.expanduser(
        os.environ.get("GAMESPHERE_IMPORT_DIR") or "~/.local/share/gamesphere-import-tool"
    )


def source_checkout_dir() -> Optional[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.isdir(os.path.join(here, ".git")):
        return here
    installed = linux_install_dir()
    if os.path.isdir(os.path.join(installed, ".git")):
        return installed
    return None


def linux_appimage_path() -> str:
    env = os.environ.get("APPIMAGE") or os.environ.get("GAMESPHERE_APPIMAGE")
    if env:
        return env
    bin_dir = os.path.expanduser("~/.local/bin")
    for name in (APPIMAGE_RELEASE_NAME, APPIMAGE_LEGACY_NAME):
        path = os.path.join(bin_dir, name)
        if os.path.isfile(path):
            return path
    return os.path.join(bin_dir, APPIMAGE_RELEASE_NAME)


def _flatpak_installed() -> bool:
    if not shutil.which("flatpak"):
        return False
    r = subprocess.run(
        ["flatpak", "info", "--user", FLATPAK_ID],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return r.returncode == 0


def detect_linux_kind() -> str:
    """Primary Linux install to update. Prefer git (Decky / host helpers / PATH)."""
    if os.environ.get("APPIMAGE") or (
        getattr(sys, "frozen", False) and sys.platform.startswith("linux")
    ):
        return "frozen"
    if source_checkout_dir():
        return "git"
    if os.path.isfile(linux_appimage_path()):
        return "appimage"
    if _flatpak_installed():
        return "flatpak"
    return "git"


def pick_asset(
    assets: List[Dict[str, Any]],
    platform: str,
    kind: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    named = [(a.get("name") or "", a) for a in assets if a.get("browser_download_url")]
    if platform == "win":
        for name, asset in named:
            if name.lower() == "gamesphereimporttool.exe":
                return asset
        for name, asset in named:
            if name.lower().endswith(".exe"):
                return asset
        return None
    if platform in ("linux", "mac"):
        kind = kind or ("git" if platform == "mac" else detect_linux_kind())

        def by_name(exact: str) -> Optional[Dict[str, Any]]:
            want = exact.lower()
            for name, asset in named:
                if name.lower() == want:
                    return asset
            return None

        def by_suffix(suffix: str) -> Optional[Dict[str, Any]]:
            for name, asset in named:
                if name.lower().endswith(suffix):
                    return asset
            return None

        if kind in ("git", "source"):
            return by_name("install-linux.sh") or by_suffix(".sh")
        if kind in ("appimage", "frozen"):
            return by_suffix(".appimage")
        if kind == "flatpak":
            return by_name("io.github.trevlars.GamesphereImportTool.flatpak") or by_suffix(
                ".flatpak"
            )
        return (
            by_name("io.github.trevlars.GamesphereImportTool.flatpak")
            or by_suffix(".appimage")
            or by_name("install-linux.sh")
        )
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
    platform = current_platform()
    kind = detect_linux_kind() if platform == "linux" else None
    out: Dict[str, Any] = {
        "current": __version__,
        "latest": None,
        "newer": False,
        "notes": "",
        "asset": None,
        "html_url": GITHUB_RELEASES_PAGE,
        "error": None,
        "platform": platform,
        "kind": kind,
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
    out["asset"] = pick_asset(rel.get("assets") or [], platform, kind=kind)
    out["tag"] = tag
    return out


def apply_windows_update(asset: Dict[str, Any]) -> str:
    """Download the new exe and spawn a hidden helper that replaces this process after exit."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Windows auto-update replaces GamesphereImportTool.exe (frozen build).")
    from host_tuning.win_subprocess import popen_hidden

    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("Release has no Windows .exe asset yet.")
    target = os.path.abspath(sys.executable)
    tmp_dir = tempfile.mkdtemp(prefix="gs-import-upd-")
    new_exe = os.path.join(tmp_dir, "GamesphereImportTool.exe")
    _download(url, new_exe, _asset_size(asset))
    _verify_windows_exe(new_exe)
    backup = os.path.join(tmp_dir, "GamesphereImportTool.previous.exe")
    try:
        shutil.copy2(target, backup)
    except OSError:
        backup = ""
    ps1 = os.path.join(tmp_dir, "apply-update.ps1")
    # Copy failures restore the previous exe so a bad swap cannot leave the
    # user with nothing to launch.
    ps1_body = (
        "$ErrorActionPreference = 'Stop'\n"
        f"$target = {json.dumps(target)}\n"
        f"$source = {json.dumps(new_exe)}\n"
        f"$backup = {json.dumps(backup)}\n"
        f"$ownerPid = {os.getpid()}\n"
        "while (Get-Process -Id $ownerPid -ErrorAction SilentlyContinue) { Start-Sleep -Seconds 1 }\n"
        "Get-Process -Name GamesphereImportTool -ErrorAction SilentlyContinue | Stop-Process -Force\n"
        "Start-Sleep -Milliseconds 500\n"
        "try {\n"
        "  Copy-Item -LiteralPath $source -Destination $target -Force\n"
        "} catch {\n"
        "  if ($backup -and (Test-Path -LiteralPath $backup)) {\n"
        "    Copy-Item -LiteralPath $backup -Destination $target -Force\n"
        "  }\n"
        "}\n"
        "Start-Process -FilePath $target -ArgumentList '--host-daemon' -WindowStyle Hidden\n"
        "Remove-Item -LiteralPath $source -Force -ErrorAction SilentlyContinue\n"
        "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
    )
    with open(ps1, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(ps1_body)
    popen_hidden(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            ps1,
        ],
        close_fds=True,
    )
    return target


def _run_install_linux_sh(tag: str, script: str) -> str:
    install_dir = linux_install_dir()
    env = os.environ.copy()
    env["GAMESPHERE_IMPORT_REF"] = tag
    env["GAMESPHERE_IMPORT_DIR"] = install_dir
    # install-linux.sh clones, syncs deps, and enables units — cap it so a stalled
    # network cannot hang the GUI update worker forever.
    subprocess.run(["bash", script], check=True, env=env, timeout=1800)
    return install_dir


def _install_linux_script(tag: str, asset: Optional[Dict[str, Any]]) -> str:
    install_dir = linux_install_dir()
    if asset and (asset.get("name") or "").lower() == "install-linux.sh" and asset.get(
        "browser_download_url"
    ):
        tmp = tempfile.mkdtemp(prefix="gs-import-upd-")
        script = os.path.join(tmp, "install-linux.sh")
        _download(asset["browser_download_url"], script)
        os.chmod(script, 0o755)
        return script
    local = os.path.join(install_dir, "scripts", "install-linux.sh")
    if os.path.isfile(local):
        return local
    checkout = source_checkout_dir()
    if checkout:
        local = os.path.join(checkout, "scripts", "install-linux.sh")
        if os.path.isfile(local):
            return local
    raw = (
        f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
        f"{tag}/scripts/install-linux.sh"
    )
    tmp = tempfile.mkdtemp(prefix="gs-import-upd-")
    script = os.path.join(tmp, "install-linux.sh")
    _download(raw, script)
    os.chmod(script, 0o755)
    return script


def apply_git_update(tag: str, asset: Optional[Dict[str, Any]] = None) -> str:
    script = _install_linux_script(tag, asset)
    return _run_install_linux_sh(tag, script)


def apply_flatpak_update(asset: Dict[str, Any]) -> str:
    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("Release has no Flatpak bundle yet.")
    bundle = os.path.join(tempfile.mkdtemp(prefix="gs-import-upd-"), "update.flatpak")
    _download(url, bundle, _asset_size(asset))
    subprocess.run(
        ["flatpak", "install", "--user", "-y", bundle],
        check=True,
        timeout=1800,
    )
    return f"flatpak:{FLATPAK_ID}"


def apply_appimage_update(asset: Dict[str, Any], dest: Optional[str] = None) -> str:
    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("Release has no AppImage asset yet.")
    dest = dest or linux_appimage_path()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".new"
    try:
        _download(url, tmp, _asset_size(asset))
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
    except Exception:
        # Never leave a partial .new behind or clobber a working AppImage.
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return dest


def apply_frozen_linux_update(asset: Dict[str, Any]) -> str:
    """Replace a running AppImage / PyInstaller binary after this process exits."""
    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("Release has no Linux binary asset yet.")
    target = os.environ.get("APPIMAGE") or os.path.abspath(sys.executable)
    tmp_dir = tempfile.mkdtemp(prefix="gs-import-upd-")
    new_bin = os.path.join(tmp_dir, os.path.basename(target) or APPIMAGE_RELEASE_NAME)
    _download(url, new_bin, _asset_size(asset))
    os.chmod(new_bin, 0o755)
    backup = os.path.join(tmp_dir, "previous.bin")
    try:
        shutil.copy2(target, backup)
    except OSError:
        backup = ""
    helper = os.path.join(tmp_dir, "apply-update.sh")
    helper_body = (
        "#!/bin/sh\n"
        f"TARGET={json.dumps(target)}\n"
        f"SOURCE={json.dumps(new_bin)}\n"
        f"BACKUP={json.dumps(backup)}\n"
        f"PID={os.getpid()}\n"
        "while kill -0 \"$PID\" 2>/dev/null; do sleep 1; done\n"
        "if ! mv -f \"$SOURCE\" \"$TARGET\"; then\n"
        "  [ -n \"$BACKUP\" ] && [ -f \"$BACKUP\" ] && cp -f \"$BACKUP\" \"$TARGET\"\n"
        "fi\n"
        "chmod +x \"$TARGET\"\n"
        "nohup \"$TARGET\" >/dev/null 2>&1 &\n"
        "rm -f \"$0\"\n"
    )
    with open(helper, "w", encoding="utf-8") as fh:
        fh.write(helper_body)
    os.chmod(helper, 0o755)
    subprocess.Popen(
        ["/bin/sh", helper],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return target


def apply_linux_update(tag: str, asset: Optional[Dict[str, Any]] = None, kind: Optional[str] = None) -> str:
    """Apply update for the existing Linux install type — do not switch git ↔ Flatpak."""
    kind = kind or detect_linux_kind()
    if kind == "frozen":
        if asset and asset.get("browser_download_url"):
            return apply_frozen_linux_update(asset)
        raise RuntimeError("Frozen Linux build needs an AppImage (or CLI) on the GitHub Release.")
    if kind == "flatpak":
        if asset and asset.get("browser_download_url"):
            return apply_flatpak_update(asset)
        raise RuntimeError("Release has no Flatpak bundle yet.")
    if kind == "appimage":
        if asset and asset.get("browser_download_url"):
            return apply_appimage_update(asset)
        raise RuntimeError("Release has no AppImage asset yet.")
    # git / source — including macOS checkouts that reuse the bash installer
    if asset and (asset.get("name") or "").lower().endswith(".flatpak"):
        asset = None
    if asset and (asset.get("name") or "").lower().endswith(".appimage"):
        asset = None
    return apply_git_update(tag, asset)


def apply_macos_update(tag: str, asset: Optional[Dict[str, Any]] = None) -> str:
    if not source_checkout_dir():
        raise RuntimeError(
            "No macOS app bundle is shipped. Clone the repo and re-run, "
            f"or download from {GITHUB_RELEASES_PAGE}"
        )
    return apply_linux_update(tag, asset, kind="git")


def apply_update(info: Dict[str, Any]) -> str:
    tag = str(info.get("tag") or info.get("latest") or "")
    if not tag:
        raise RuntimeError("No release tag to install.")
    if not tag.startswith("v"):
        tag = "v" + tag
    platform = info.get("platform") or current_platform()
    asset = info.get("asset")
    kind = info.get("kind")
    if platform == "win":
        dest = apply_windows_update(asset or {})
    elif platform == "linux":
        dest = apply_linux_update(tag, asset, kind=kind)
    elif platform == "mac":
        dest = apply_macos_update(tag, asset)
    else:
        raise RuntimeError(
            f"In-app update is not wired for this platform. Download from {GITHUB_RELEASES_PAGE}"
        )
    try:
        from host_tuning.host_daemon import restart_host_bridge_only

        restart_host_bridge_only()
    except Exception:
        pass
    return dest


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
