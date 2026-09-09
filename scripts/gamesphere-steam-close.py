#!/usr/bin/env python3
"""Close a Steam / Non-Steam game after Sunshine/Apollo Quit App (/cancel).

Detached steam:// launches are not tracked by Sunshine, so prep-cmd undo calls
this helper. Matching is 64-bit-safe (AppIDs stay strings — no bash $(( ))).

Slow-to-start titles (Hogwarts Legacy class) often have no game process yet
when /cancel runs — launcher / EAC / shader compile / splash — and the real
exe can appear later. We:

  1. Match by Steam AppID environ/cmdline, install-dir path, and distinctive
     executables from that app's Steam folder (not a single hardcoded title).
  2. SIGTERM/KILL the matched tree children-first (never reaper-first).
  3. Keep a short foreground watch, then a detached watcher so late-spawned
     processes are still reaped without blocking Sunshine's undo.

Does not kill the Steam client, Sunshine/Apollo, or gamescope.
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

IS_LINUX = sys.platform.startswith("linux")
IS_DARWIN = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

ENV_KEYS = (
    b"SteamAppId=",
    b"SteamGameId=",
    b"STEAM_COMPAT_APP_ID=",
    b"SteamOverlayGameId=",
)
PATH_ENV_KEYS = (
    b"STEAM_COMPAT_DATA_PATH=",
    b"STEAM_COMPAT_INSTALL_PATH=",
    b"WINEPREFIX=",
)
GENERIC_EXES = {
    "crashreportclient.exe",
    "crashpad_handler.exe",
    "unitycrashhandler.exe",
    "unitycrashhandler32.exe",
    "unitycrashhandler64.exe",
    "uninstall.exe",
    "vcredist_x64.exe",
    "vcredist_x86.exe",
    "vc_redist.x64.exe",
    "vc_redist.x86.exe",
    "dxsetup.exe",
    "dotnetfx.exe",
    "easyanticheat_setup.exe",
    "easyanticheat_eos_setup.exe",
}

# Foreground must stay short so Sunshine undo does not stall the next launch.
FOREGROUND_SEC = float(os.environ.get("GAMESPHERE_CLOSE_FOREGROUND_SEC") or "8")
# Late shipping exe (launcher → EAC → real game) often appears well after /cancel.
WATCH_SEC = float(os.environ.get("GAMESPHERE_CLOSE_WATCH_SEC") or "180")
WATCH_POLL = float(os.environ.get("GAMESPHERE_CLOSE_WATCH_POLL") or "1.5")

LOG = ""
DRY = bool(os.environ.get("GAMESPHERE_CLOSE_DRYRUN"))


def log(msg: str) -> None:
    line = "gamesphere-steam-close: " + msg
    print(line, flush=True)
    if not LOG:
        return
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def id_strings(raw: str) -> set[str]:
    """Store AppID and/or Non-Steam 64-bit rungameid → strings to match."""
    out = {raw}
    try:
        n = int(raw)
    except ValueError:
        return out
    if n > 0xFFFFFFFF:
        out.add(str(n >> 32))
    else:
        out.add(str((n << 32) | 0x02000000))
    return {s for s in out if s}


def short_id(raw: str) -> str:
    try:
        n = int(raw)
    except ValueError:
        return raw
    if n > 0xFFFFFFFF:
        return str(n >> 32)
    return raw


def read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except (OSError, PermissionError):
        return b""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return ""


def cmdline_of(pid: int) -> str:
    if IS_LINUX:
        return read_bytes(Path("/proc/%d/cmdline" % pid)).replace(b"\0", b" ").decode(
            "utf-8", "replace"
        )
    return ""


def comm_of(pid: int) -> str:
    if IS_LINUX:
        return read_text(Path("/proc/%d/comm" % pid)).strip()
    return ""


def exe_of(pid: int) -> str:
    if IS_LINUX:
        try:
            return os.readlink("/proc/%d/exe" % pid)
        except OSError:
            return ""
    return ""


def cwd_of(pid: int) -> str:
    if IS_LINUX:
        try:
            return os.readlink("/proc/%d/cwd" % pid)
        except OSError:
            return ""
    return ""


def environ_of(pid: int) -> bytes:
    if IS_LINUX:
        return read_bytes(Path("/proc/%d/environ" % pid))
    return b""


def is_protected(cmd: str, exe: str = "", name: str = "") -> bool:
    blob = " ".join(x for x in (cmd, exe, name) if x).lower()
    if not blob:
        return False
    if "gamesphere-steam-close" in blob:
        return True
    if "sunshine-host" in blob or "sunshine-stream-prep" in blob:
        return True
    if name.lower() in {"sunshine", "sunshine.exe", "apollo", "apollo.exe"}:
        return True
    if exe.lower().rstrip("\\/").endswith(("sunshine", "sunshine.exe", "apollo", "apollo.exe")):
        return True
    if "steamwebhelper" in blob:
        return True
    if "gamescope-session" in blob:
        return True
    if "steamservice" in blob:
        return True
    # Steam client binary — not reaper, not steam-launch-wrapper.
    if "ubuntu12_32/steam " in cmd or "ubuntu12_64/steam " in cmd:
        return True
    if "/steam.sh " in blob or cmd.rstrip().endswith("/steam.sh"):
        return True
    if "cardwire" in blob and "launch steam" in blob:
        return True
    if "steam.app/contents/macos/steam_osx" in blob:
        return True
    base = (name or Path(exe).name if exe else "").lower()
    if base in {"steam", "steam.exe", "steam_osx", "steamservice.exe"}:
        return True
    return False


def steam_library_vdfs() -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".local/share/Steam/steamapps/libraryfolders.vdf",
        home / ".steam/steam/steamapps/libraryfolders.vdf",
        home / ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/libraryfolders.vdf",
        home / "Library/Application Support/Steam/steamapps/libraryfolders.vdf",
        Path(r"C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf"),
        Path(r"C:/Program Files/Steam/steamapps/libraryfolders.vdf"),
    ]
    if IS_WIN:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
            if steam_path:
                candidates.insert(
                    0, Path(steam_path) / "steamapps" / "libraryfolders.vdf"
                )
        except OSError:
            pass
    seen: set[str] = set()
    out: list[Path] = []
    for path in candidates:
        try:
            resolved = str(path.resolve()) if path.is_file() else ""
        except OSError:
            resolved = str(path) if path.is_file() else ""
        if resolved and resolved not in seen:
            seen.add(resolved)
            out.append(Path(resolved))
    return out


def parse_library_paths(vdf_text: str) -> list[Path]:
    paths = []
    for match in re.finditer(r'"path"\s+"([^"]+)"', vdf_text):
        raw = match.group(1).replace("\\\\", "\\")
        path = Path(os.path.expanduser(os.path.expandvars(raw)))
        if path.is_dir():
            paths.append(path)
    return paths


def read_acf_installdir(acf: Path) -> str:
    text = read_text(acf)
    match = re.search(r'"installdir"\s+"([^"]+)"', text)
    return match.group(1) if match else ""


def resolve_game_roots(raw_id: str) -> tuple[list[str], list[str]]:
    """Return (path prefixes, distinctive exe basenames) for this AppID."""
    ids = id_strings(raw_id)
    short = short_id(raw_id)
    prefixes: list[str] = []
    exes: set[str] = set()
    libraries: list[Path] = []
    for vdf in steam_library_vdfs():
        libraries.extend(parse_library_paths(read_text(vdf)))
        steamapps = vdf.parent
        if steamapps.is_dir():
            libraries.append(steamapps.parent)
    seen_lib: set[str] = set()
    unique_libs: list[Path] = []
    for lib in libraries:
        key = str(lib)
        if key not in seen_lib:
            seen_lib.add(key)
            unique_libs.append(lib)

    for lib in unique_libs:
        steamapps = lib / "steamapps"
        for aid in ids:
            acf = steamapps / ("appmanifest_%s.acf" % aid)
            if not acf.is_file():
                continue
            installdir = read_acf_installdir(acf)
            if installdir:
                common = steamapps / "common" / installdir
                if common.is_dir():
                    prefixes.append(str(common))
                    exes.update(collect_exe_names(common))
            compat = steamapps / "compatdata" / aid
            if compat.is_dir():
                prefixes.append(str(compat))
            shader = steamapps / "shadercache" / aid
            if shader.is_dir():
                prefixes.append(str(shader))
        # Proton prefix often lives on the default Steam library even when
        # the game files are on another drive.
        for aid in (short, raw_id):
            compat = steamapps / "compatdata" / aid
            if compat.is_dir():
                prefixes.append(str(compat))
            shader = steamapps / "shadercache" / aid
            if shader.is_dir():
                prefixes.append(str(shader))

    # Dedup while keeping order.
    pref_out: list[str] = []
    seen_p: set[str] = set()
    for prefix in prefixes:
        key = prefix.rstrip("\\/")
        if key and key not in seen_p:
            seen_p.add(key)
            pref_out.append(key)
    return pref_out, sorted(exes)


def collect_exe_names(root: Path) -> set[str]:
    names: set[str] = set()
    skip_dirs = {
        "movies",
        "content",
        "paks",
        "saved",
        "intermediate",
        "deriveddatacache",
        "shaders",
        "source",
        "debug",
        "symbols",
    }
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            rel = os.path.relpath(dirpath, root)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth > 5:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d.lower() not in skip_dirs]
            for name in filenames:
                low = name.lower()
                if low in GENERIC_EXES:
                    continue
                if low.endswith((".dll", ".so", ".dylib", ".pak", ".bin", ".dat")):
                    continue
                if low.endswith(".exe"):
                    names.add(low)
                elif "shipping" in low and os.access(os.path.join(dirpath, name), os.X_OK):
                    names.add(low)
            if len(names) >= 40:
                break
    except OSError:
        return names
    return names


def path_needles(prefixes: list[str]) -> list[str]:
    needles: list[str] = []
    for prefix in prefixes:
        needles.append(prefix)
        alt = prefix.replace("/", "\\")
        if alt != prefix:
            needles.append(alt)
        if prefix.startswith("/"):
            needles.append("Z:" + prefix.replace("/", "\\"))
            needles.append("Z:" + prefix)
    return needles


def distinctive_exe(name: str) -> bool:
    base = name.lower()
    if base in GENERIC_EXES:
        return False
    if base.endswith((".dll", ".so", ".dylib", ".pak", ".bin", ".dat")):
        return False
    stem = base[:-4] if base.endswith(".exe") else base
    if stem.startswith("easyanticheat"):
        return False
    # Name-only match needs a long/specific stem (HogwartsLegacy, not Game.exe).
    return len(stem) >= 10


def blob_has_id(blob: str, ids: set[str]) -> bool:
    for aid in ids:
        if (
            ("SteamAppId=" + aid) in blob
            or ("SteamGameId=" + aid) in blob
            or ("STEAM_COMPAT_APP_ID=" + aid) in blob
            or ("SteamOverlayGameId=" + aid) in blob
            or ("AppId=" + aid) in blob
            or ("AppID=" + aid) in blob
        ):
            return True
    return False


def blob_has_prefix(blob: str, needles: list[str]) -> bool:
    if not blob or not needles:
        return False
    low = blob if IS_WIN else blob
    for needle in needles:
        if needle and needle in low:
            return True
        if not IS_WIN and needle.lower() in low.lower():
            return True
    return False


def blob_has_exe(blob: str, comm: str, exes: list[str]) -> bool:
    if not exes:
        return False
    hay = (blob + " " + comm).lower()
    for exe in exes:
        if not distinctive_exe(exe):
            continue
        if exe in hay:
            return True
        stem = exe[:-4] if exe.endswith(".exe") else exe
        if comm and (comm.lower() == stem or comm.lower().startswith(stem[:12])):
            return True
    return False


def pid_matches_linux(pid: int, ids: set[str], needles: list[str], exes: list[str]) -> bool:
    env = environ_of(pid)
    cmd = cmdline_of(pid)
    exe = exe_of(pid)
    cwd = cwd_of(pid)
    comm = comm_of(pid)
    if is_protected(cmd, exe, comm):
        return False
    entries = env.split(b"\0")
    for aid in ids:
        token = aid.encode("ascii", "replace")
        for key in ENV_KEYS:
            if key + token in entries:
                return True
        if b"AppId=" + token in cmd.encode("utf-8", "replace") or b"AppID=" + token in env:
            return True
        if b"AppId=" + token in read_bytes(Path("/proc/%d/cmdline" % pid)):
            return True
    blob = " ".join(x for x in (cmd, exe, cwd) if x)
    if blob_has_id(blob, ids):
        return True
    for key in PATH_ENV_KEYS:
        for entry in entries:
            if not entry.startswith(key):
                continue
            val = entry.split(b"=", 1)[-1].decode("utf-8", "replace")
            if blob_has_prefix(val, needles):
                return True
            for aid in ids:
                if ("compatdata/" + aid) in val.replace("\\", "/") or (
                    "compatdata\\" + aid
                ) in val:
                    return True
    if blob_has_prefix(blob, needles):
        return True
    if blob_has_exe(blob, comm, exes):
        return True
    return False


def children_of(pid: int) -> list[int]:
    out: list[int] = []
    if IS_LINUX:
        task = Path("/proc/%d/task" % pid)
        if not task.is_dir():
            return out
        for t in task.iterdir():
            try:
                txt = (t / "children").read_text()
            except (OSError, PermissionError):
                continue
            out.extend(int(x) for x in txt.split() if x.isdigit())
        return out
    if IS_DARWIN:
        try:
            out_b = subprocess.check_output(
                ["pgrep", "-P", str(pid)], stderr=subprocess.DEVNULL
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return out
        out.extend(int(x) for x in out_b.split() if x.strip().isdigit())
    return out


def descendants(pid: int) -> set[int]:
    seen: set[int] = set()
    stack = [pid]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(children_of(cur))
    return seen


def darwin_pid_cmd_env() -> list[tuple[int, str]]:
    try:
        out = subprocess.check_output(
            ["ps", "eww", "-A", "-o", "pid=,command="],
            stderr=subprocess.DEVNULL,
            errors="replace",
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return []
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if not parts or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        rest = parts[1] if len(parts) > 1 else ""
        rows.append((pid, rest))
    return rows


def win_processes() -> list[tuple[int, int, str, str, str]]:
    """pid, ppid, name, exe, commandline."""
    rows: list[tuple[int, int, str, str, str]] = []
    if not IS_WIN:
        return rows
    try:
        out = subprocess.check_output(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance Win32_Process | "
                    "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | "
                    "ConvertTo-Csv -NoTypeInformation"
                ),
            ],
            stderr=subprocess.DEVNULL,
            errors="replace",
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return rows
    import csv
    from io import StringIO

    reader = csv.DictReader(StringIO(out))
    for rec in reader:
        try:
            pid = int(rec.get("ProcessId") or 0)
        except ValueError:
            continue
        if pid <= 0:
            continue
        try:
            ppid = int(rec.get("ParentProcessId") or 0)
        except ValueError:
            ppid = 0
        rows.append(
            (
                pid,
                ppid,
                rec.get("Name") or "",
                rec.get("ExecutablePath") or "",
                rec.get("CommandLine") or "",
            )
        )
    return rows


def collect_targets(
    ids: set[str], needles: list[str], exes: list[str]
) -> tuple[list[int], set[int], int]:
    self_pid = os.getpid()
    ppid = os.getppid()
    skip = {1, self_pid, ppid}
    roots: set[int] = set()
    scanned = 0
    win_rows = []
    if IS_LINUX:
        for d in Path("/proc").iterdir():
            if not d.name.isdigit():
                continue
            pid = int(d.name)
            if pid in skip:
                continue
            scanned += 1
            try:
                if pid_matches_linux(pid, ids, needles, exes):
                    roots.add(pid)
            except OSError:
                continue
    elif IS_DARWIN:
        for pid, rest in darwin_pid_cmd_env():
            scanned += 1
            if pid in skip or is_protected(rest):
                continue
            if blob_has_id(rest, ids) or blob_has_prefix(rest, needles) or blob_has_exe(
                rest, "", exes
            ):
                roots.add(pid)
    elif IS_WIN:
        win_rows = win_processes()
        for pid, _ppid, name, exe, cmd in win_rows:
            scanned += 1
            if pid in skip or is_protected(cmd, exe, name):
                continue
            blob = " ".join(x for x in (cmd, exe, name) if x)
            if blob_has_id(blob, ids) or blob_has_prefix(blob, needles) or blob_has_exe(
                blob, name, exes
            ):
                roots.add(pid)

    targets: set[int] = set()
    for root in roots:
        tree = descendants(root) if not IS_WIN else win_descendants(root, win_rows)
        for pid in tree:
            if pid in skip:
                continue
            cmd = cmdline_of(pid) if IS_LINUX else ""
            exe = exe_of(pid) if IS_LINUX else ""
            name = comm_of(pid) if IS_LINUX else ""
            if IS_WIN:
                for wpid, _ppid, wname, wexe, wcmd in win_rows:
                    if wpid == pid:
                        cmd, exe, name = wcmd, wexe, wname
                        break
            if is_protected(cmd, exe, name):
                continue
            targets.add(pid)

    def sort_key(pid: int) -> tuple[int, int]:
        cmd = cmdline_of(pid)
        if IS_WIN:
            for wpid, _ppid, _wname, _wexe, wcmd in win_rows:
                if wpid == pid:
                    cmd = wcmd
                    break
        is_reaper = 1 if ("reaper" in cmd.lower() and "steamlaunch" in cmd.lower()) else 0
        return (is_reaper, -pid)

    return sorted(targets, key=sort_key), roots, scanned


def win_descendants(pid: int, rows: list[tuple[int, int, str, str, str]]) -> set[int]:
    by_parent: dict[int, list[int]] = {}
    for wpid, ppid, _n, _e, _c in rows:
        by_parent.setdefault(ppid, []).append(wpid)
    seen: set[int] = set()
    stack = [pid]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(by_parent.get(cur, []))
    return seen


def send(pid: int, sig: int) -> bool:
    cmd = (cmdline_of(pid) or comm_of(pid))[:140]
    if DRY:
        log("dry-run kill -%s %s %s" % (sig, pid, cmd))
        return True
    if IS_WIN:
        try:
            subprocess.call(
                ["taskkill", "/PID", str(pid), "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            return False
    try:
        os.kill(pid, sig)
        return True
    except (OSError, ProcessLookupError):
        return False


def pid_alive(pid: int) -> bool:
    if IS_LINUX:
        return Path("/proc/%d" % pid).exists()
    if IS_WIN:
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
                stderr=subprocess.DEVNULL,
                errors="replace",
            )
            return str(pid) in out
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def sweep(ids: set[str], needles: list[str], exes: list[str], seconds: float) -> tuple[set[int], set[int]]:
    killed: set[int] = set()
    last_roots: set[int] = set()
    deadline = time.time() + max(0.2, seconds)
    attempt = 0
    empty_logged = False
    while time.time() < deadline:
        attempt += 1
        targets, roots, scanned = collect_targets(ids, needles, exes)
        last_roots = roots
        if not targets:
            if not empty_logged:
                log("no matching processes yet (scanned %d); watching" % scanned)
                empty_logged = True
            time.sleep(min(0.6, max(0.2, seconds / 8.0)))
            continue
        log("attempt %d roots=%s targets=%s" % (attempt, sorted(roots), targets))
        for pid in targets:
            send(pid, signal.SIGTERM if not IS_WIN else 15)
            killed.add(pid)
        time.sleep(0.45)
        for pid in targets:
            if pid_alive(pid):
                send(pid, signal.SIGKILL if not IS_WIN else 9)
        leftover, _, _ = collect_targets(ids, needles, exes)
        if not leftover:
            break
        time.sleep(0.2)
    leftover, _, _ = collect_targets(ids, needles, exes)
    if leftover:
        log("still running after sweep: %s" % leftover)
    return killed, last_roots


def watcher_lock_path(raw: str) -> Path:
    if IS_WIN:
        base = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".")
    else:
        base = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
    return base / ("gamesphere-steam-close.%s.watch.pid" % raw)


def take_watcher_lock(raw: str) -> bool:
    path = watcher_lock_path(raw)
    try:
        if path.is_file():
            old = int(read_text(path).strip() or "0")
            if old and old != os.getpid() and pid_alive(old):
                if DRY:
                    log("dry-run replace watcher pid %s" % old)
                else:
                    try:
                        if IS_WIN:
                            send(old, 9)
                        else:
                            os.kill(old, signal.SIGTERM)
                    except (OSError, ProcessLookupError):
                        pass
        path.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except (OSError, ValueError):
        return True


def spawn_watcher(raw: str) -> None:
    env = os.environ.copy()
    env["GAMESPHERE_CLOSE_WATCHER"] = "1"
    env["GAMESPHERE_CLOSE_APPID"] = raw
    cmd = [sys.executable, os.path.abspath(__file__), raw, "--watch"]
    if DRY:
        cmd.append("--dry-run")
        log("dry-run would spawn watcher %s" % cmd)
        return
    try:
        kwargs = {
            "args": cmd,
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "start_new_session": True,
        }
        if IS_WIN:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
                subprocess, "DETACHED_PROCESS", 0
            )
        subprocess.Popen(**kwargs)
        log("spawned late-spawn watcher for %ss" % int(WATCH_SEC))
    except OSError as exc:
        log("watcher spawn failed: %r" % (exc,))


def default_log_path() -> str:
    if IS_WIN:
        base = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".")
    else:
        base = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
    return str(base / "gamesphere-steam-close.log")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Close a Steam game after Sunshine /cancel")
    parser.add_argument("appid", nargs="?", default=os.environ.get("GAMESPHERE_CLOSE_APPID", ""))
    parser.add_argument("--watch", action="store_true", help="late-spawn watcher (internal)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log", default=os.environ.get("GAMESPHERE_CLOSE_LOG") or default_log_path())
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global LOG, DRY
    args = parse_args(argv if argv is not None else sys.argv[1:])
    raw = (args.appid or "").strip()
    if not raw.isdigit():
        log("invalid app id %r" % (raw,))
        return 1
    DRY = bool(args.dry_run or DRY)
    LOG = args.log or ""
    ids = id_strings(raw)
    prefixes, exes = resolve_game_roots(raw)
    needles = path_needles(prefixes)
    log(
        "request id=%s match=%s roots=%s exes=%s%s"
        % (
            raw,
            sorted(ids, key=lambda s: (len(s), s)),
            prefixes,
            exes[:12],
            " watch" if args.watch or os.environ.get("GAMESPHERE_CLOSE_WATCHER") else "",
        )
    )

    watch_mode = bool(args.watch or os.environ.get("GAMESPHERE_CLOSE_WATCHER"))
    if watch_mode:
        take_watcher_lock(raw)
        killed, last_roots = sweep(ids, needles, exes, WATCH_SEC)
        leftover, _, _ = collect_targets(ids, needles, exes)
        if leftover:
            log("watcher still running: %s" % leftover)
            return 1
        log("watcher done killed_n=%d last_roots=%s" % (len(killed), sorted(last_roots)))
        return 0

    killed, last_roots = sweep(ids, needles, exes, FOREGROUND_SEC)
    leftover, _, _ = collect_targets(ids, needles, exes)
    spawn_watcher(raw)
    log("done killed_n=%d last_roots=%s leftover=%s" % (len(killed), sorted(last_roots), leftover))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log("error %r" % (exc,))
        sys.exit(1)
