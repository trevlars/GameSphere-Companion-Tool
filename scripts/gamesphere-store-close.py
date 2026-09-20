#!/usr/bin/env python3
"""Close Epic / Xbox / GOG / other non-Steam PC games after Sunshine /cancel.

Looks up the imported Sunshine app (by store key or Sunshine id), then kills
matching game processes under the install folder. Does not kill launchers,
Sunshine/Apollo, or Steam.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

IS_WIN = sys.platform == "win32"

PROTECTED_NAMES = {
    "epicgameslauncher.exe",
    "epicwebhelper.exe",
    "sunshine.exe",
    "apollo.exe",
    "steam.exe",
    "steamwebhelper.exe",
    "gamescope",
    "gamesphere-store-close.py",
    "gamesphere-steam-close.py",
    "explorer.exe",
}


def log(msg: str) -> None:
    print("gamesphere-store-close: " + msg, flush=True)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _import_sunshine_apps():
    root = str(_repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    from host_tuning import sunshine_apps

    return sunshine_apps


def resolve_app(args: argparse.Namespace):
    sunshine_apps = _import_sunshine_apps()
    if args.store_key:
        return sunshine_apps.app_for_store_key(args.store_key)
    if args.sunshine_id:
        return sunshine_apps.app_for_sunshine_id(args.sunshine_id)
    return None


def install_root_from_exe(exe_path: str) -> str:
    exe_path = (exe_path or "").strip().strip('"')
    if not exe_path:
        return ""
    path = Path(exe_path)
    if path.is_file():
        return str(path.parent)
    if path.is_dir():
        return str(path)
    parent = path.parent
    return str(parent) if str(parent) not in (".", "") else ""


def protected(name: str) -> bool:
    base = (name or "").lower()
    if base in PROTECTED_NAMES:
        return True
    return any(token in base for token in ("gamesphere-", "sunshine", "apollo"))


def collect_targets(install_root: str, exe_path: str) -> list[int]:
    try:
        import psutil
    except ImportError:
        log("psutil is required")
        return []

    root = os.path.normcase(os.path.normpath(install_root)) if install_root else ""
    exe_name = os.path.basename(exe_path.replace("\\", "/")).lower() if exe_path else ""
    targets: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            pinfo = proc.info
            pid = int(pinfo.get("pid") or 0)
            if pid <= 0:
                continue
            pname = (pinfo.get("name") or "").lower()
            if protected(pname):
                continue
            pexe = pinfo.get("exe") or ""
            if not pexe:
                continue
            norm = os.path.normcase(os.path.normpath(pexe))
            if root and root in norm:
                targets.append(pid)
                continue
            if exe_name and os.path.basename(norm).lower() == exe_name:
                if root and root not in norm:
                    continue
                targets.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return sorted(set(targets))


def kill_pid(pid: int, force: bool = False) -> bool:
    if IS_WIN:
        args = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            args.append("/F")
        try:
            subprocess.call(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(pid, sig)
        return True
    except OSError:
        return False


def sweep(install_root: str, exe_path: str, seconds: float = 6.0) -> int:
    killed: set[int] = set()
    deadline = time.time() + max(0.5, seconds)
    while time.time() < deadline:
        targets = collect_targets(install_root, exe_path)
        if not targets:
            if killed:
                break
            time.sleep(0.35)
            continue
        for pid in targets:
            kill_pid(pid, force=False)
            killed.add(pid)
        time.sleep(0.45)
        for pid in list(targets):
            if pid in killed:
                kill_pid(pid, force=True)
        leftover = collect_targets(install_root, exe_path)
        if not leftover:
            break
        time.sleep(0.25)
    return len(killed)


def close_uwp_shell(store_id: str) -> int:
    """Best-effort stop for Xbox shell:appsFolder launches on Windows."""
    if not IS_WIN or not store_id:
        return 0
    ps = (
        "$ids = Get-AppxPackage | Where-Object { $_.PackageFamilyName + '!' + "
        "($_.PackageFamilyName -split '_')[0] -ne $null }; "
        f"$target = '{store_id.replace(chr(39), chr(39)+chr(39))}'; "
        "Get-Process | Where-Object { $_.Path -like '*WindowsApps*' } | "
        "ForEach-Object { try { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue } catch {} }"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Close a non-Steam imported game")
    parser.add_argument("--store-key", default="", help="Stable store key from apps.json")
    parser.add_argument("--sunshine-id", default="", help="Sunshine / Moonlight app id")
    parser.add_argument("--exe-path", default="", help="Optional override install exe")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if not IS_WIN:
        log("non-Windows host — store close is a no-op here")
        return 0

    app = resolve_app(args)
    sunshine_apps = _import_sunshine_apps()
    meta = sunshine_apps.close_metadata_from_app(app) if app else {}
    exe_path = (args.exe_path or meta.get("exe_path") or "").strip()
    store = (meta.get("store") or "").strip()
    name = (meta.get("name") or args.store_key or args.sunshine_id or "game").strip()

    if meta.get("steam_id"):
        log("steam app %s — delegating to gamesphere-steam-close" % meta["steam_id"])
        helper = None
        for candidate in (
            Path.home() / ".local/bin/gamesphere-steam-close.sh",
            _repo_root() / "scripts" / "gamesphere-steam-close.sh",
        ):
            if candidate.is_file():
                helper = str(candidate)
                break
        if helper:
            return subprocess.call([helper, meta["steam_id"]])
        return 1

    if not exe_path and app:
        cmd = str(app.get("cmd") or "").strip().strip('"')
        if cmd and os.path.sep in cmd and os.path.isfile(cmd):
            exe_path = cmd

    install_root = install_root_from_exe(exe_path)
    if not install_root and not exe_path:
        store_id = ""
        if app:
            detached = app.get("detached") or ""
            if isinstance(detached, list):
                detached = detached[0] if detached else ""
            text = str(detached)
            if "shell:appsFolder\\" in text:
                store_id = text.split("shell:appsFolder\\", 1)[1].split('"', 1)[0]
        if store_id:
            log("closing Xbox shell app %s" % name)
            close_uwp_shell(store_id)
            return 0
        log("no close target for %s" % name)
        return 1

    log("closing %s (%s) root=%s exe=%s" % (name, store or "Store", install_root, exe_path))
    count = sweep(install_root, exe_path)
    log("done killed_n=%d" % count)
    return 0 if count >= 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log("error %r" % (exc,))
        sys.exit(1)
