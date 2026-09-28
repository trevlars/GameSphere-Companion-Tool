"""DeckyLoader backend for GameSphere Companion Tool."""

from __future__ import annotations

import asyncio
import json
import os
import pwd
import re
import shutil
import subprocess

import decky


def _user_home() -> str:
    """Home of the Steam/Bazzite user — not /root when PluginLoader is privileged.

    Root-flagged plugins get HOME=/root, so expanduser("~") misses the Companion
    install under /home/<user>. Prefer Decky's DECKY_USER_HOME.
    """
    for key in ("DECKY_USER_HOME",):
        value = (os.environ.get(key) or "").strip()
        if value and os.path.isdir(value):
            return value
    homebrew = (os.environ.get("DECKY_HOME") or os.environ.get("UNPRIVILEGED_PATH") or "").strip()
    if homebrew:
        parent = os.path.dirname(os.path.abspath(homebrew))
        if parent and os.path.isdir(parent) and os.path.basename(parent) != "root":
            return parent
    for key in ("DECKY_USER",):
        user = (os.environ.get(key) or "").strip()
        if user and user != "root":
            try:
                return pwd.getpwnam(user).pw_dir
            except KeyError:
                pass
    # Last resort: if we are root, prefer a real login home over /root.
    expanded = os.path.expanduser("~")
    if expanded in ("/root", "/") or os.geteuid() == 0:
        for name in ("bazzite", "deck", "steam"):
            try:
                return pwd.getpwnam(name).pw_dir
            except KeyError:
                continue
    return expanded


def _user_name() -> str:
    for key in ("DECKY_USER",):
        user = (os.environ.get(key) or "").strip()
        if user:
            return user
    try:
        return pwd.getpwuid(os.stat(_user_home()).st_uid).pw_name
    except (KeyError, OSError):
        return os.environ.get("USER") or os.environ.get("LOGNAME") or "deck"


_USER_HOME = _user_home()
INSTALL_DIR = os.path.join(_USER_HOME, ".local/share/gamesphere-import-tool")
BIN_CANDIDATES = [
    os.path.join(_USER_HOME, ".local/bin/gamesphere-import"),
    os.path.join(INSTALL_DIR, "main.py"),
]
BRIDGE_UNIT_NAME = "gamesphere-host-bridge.service"
BRIDGE_UNIT_SRC = os.path.join(INSTALL_DIR, "scripts/systemd/gamesphere-host-bridge.service")
BRIDGE_UNIT_DST = os.path.join(_USER_HOME, f".config/systemd/user/{BRIDGE_UNIT_NAME}")
BRIDGE_WRAPPER_SRC = os.path.join(INSTALL_DIR, "scripts/gamesphere-host-bridge.sh")
BRIDGE_WRAPPER_DST = os.path.join(_USER_HOME, ".local/bin/gamesphere-host-bridge")
UPDATE_UNIT_NAME = "gamesphere-import-update.timer"
UPDATE_SERVICE_SRC = os.path.join(INSTALL_DIR, "scripts/systemd/gamesphere-import-update.service")
UPDATE_TIMER_SRC = os.path.join(INSTALL_DIR, "scripts/systemd/gamesphere-import-update.timer")
UPDATE_SCRIPT_SRC = os.path.join(INSTALL_DIR, "scripts/gamesphere-import-update.sh")
UPDATE_BIN_DST = os.path.join(_USER_HOME, ".local/bin/gamesphere-import-update.sh")
SYNC_UNIT_NAME = "gamesphere-library-sync.timer"
SYNC_SERVICE_SRC = os.path.join(INSTALL_DIR, "scripts/systemd/gamesphere-library-sync.service")
SYNC_TIMER_SRC = os.path.join(INSTALL_DIR, "scripts/systemd/gamesphere-library-sync.timer")
UPDATE_UNIT_DIR = os.path.join(_USER_HOME, ".config/systemd/user")
FLATPAK_APP_ID = "io.github.trevlars.GamesphereImportTool"


def _flatpak_installed() -> bool:
    flatpak = shutil.which("flatpak")
    if not flatpak:
        return False
    result = subprocess.run(
        [flatpak, "info", "--user", FLATPAK_APP_ID],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return result.returncode == 0


def _resolve_command() -> list[str] | None:
    for candidate in BIN_CANDIDATES:
        if candidate.endswith("main.py") and os.path.isfile(candidate):
            uv = shutil.which("uv")
            if uv:
                return [uv, "run", candidate]
            python = shutil.which("python3") or shutil.which("python")
            if python:
                return [python, candidate]
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return [candidate]
    if _flatpak_installed():
        return ["flatpak", "run", FLATPAK_APP_ID]
    return None


def _install_kind() -> str:
    if os.path.isfile(BIN_CANDIDATES[0]) and os.access(BIN_CANDIDATES[0], os.X_OK):
        return "wrapper"
    if os.path.isfile(BIN_CANDIDATES[1]):
        return "git"
    if _flatpak_installed():
        return "flatpak"
    return "none"


def _host_tuning_cmd() -> list[str] | None:
    cli = os.path.join(INSTALL_DIR, "host_tuning_cli.py")
    if not os.path.isfile(cli):
        return None
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", cli]
    python = shutil.which("python3") or shutil.which("python")
    if python:
        return [python, cli]
    return None


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = _USER_HOME
    env["USER"] = _user_name()
    env["LOGNAME"] = env["USER"]
    try:
        uid = pwd.getpwnam(env["USER"]).pw_uid
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    except KeyError:
        pass
    return env


def _run_as_user(args: list[str], *, cwd: str | None, timeout: int) -> subprocess.CompletedProcess[str]:
    """Run a command as the Decky/Steam user when the plugin process is root."""
    env = _subprocess_env()
    if os.geteuid() == 0:
        user = _user_name()
        try:
            pw = pwd.getpwnam(user)
        except KeyError:
            pw = None
        if pw is not None:
            def _preexec() -> None:
                os.setgid(pw.pw_gid)
                os.setuid(pw.pw_uid)

            return subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                preexec_fn=_preexec,
            )
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _run_sync(args: list[str], timeout: int = 600) -> tuple[bool, str, str | None]:
    cmd = _resolve_command()
    if not cmd:
        return False, (
            "GameSphere Companion Tool not found. Run install-flatpak.sh or install-linux.sh on the host."
        ), None

    full = cmd + args
    decky.logger.info("Running: %s", " ".join(full))
    try:
        result = _run_as_user(
            full,
            cwd=INSTALL_DIR if os.path.isdir(INSTALL_DIR) else None,
            timeout=timeout,
        )
        output = (result.stdout or "") + (result.stderr or "")
        banner = None
        match = re.search(r"^BANNER:(.+)$", output, re.MULTILINE)
        if match:
            banner = match.group(1).strip()
        ok = result.returncode == 0
        if not ok and not output.strip():
            output = f"Exit code {result.returncode}"
        return ok, output.strip(), banner
    except subprocess.TimeoutExpired:
        return False, "Command timed out.", None
    except Exception as exc:
        return False, str(exc), None


def _run_host_tuning_sync(args: list[str], timeout: int = 120) -> tuple[bool, str]:
    cmd = _host_tuning_cmd()
    if not cmd:
        return False, "Host tuning CLI not found."
    full = cmd + args
    decky.logger.info("Running host tuning: %s", " ".join(full))
    try:
        result = _run_as_user(
            full,
            cwd=INSTALL_DIR if os.path.isdir(INSTALL_DIR) else None,
            timeout=timeout,
        )
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        if result.returncode != 0 and not output:
            output = f"Exit code {result.returncode}"
        return result.returncode == 0, output
    except Exception as exc:
        return False, str(exc)


def _run_systemctl(args: list[str]) -> tuple[bool, str]:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False, "systemctl not found"
    try:
        result = _run_as_user([systemctl, "--user"] + args, cwd=None, timeout=30)
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        return result.returncode == 0, output
    except Exception as exc:
        return False, str(exc)


def _bridge_service_state() -> str:
    ok, output = _run_systemctl(["is-active", BRIDGE_UNIT_NAME])
    if ok:
        return output.strip() or "active"
    if "inactive" in output:
        return "inactive"
    if "failed" in output:
        return "failed"
    return "unknown"


def _ensure_bridge_unit() -> tuple[bool, str]:
    if not os.path.isfile(BRIDGE_UNIT_SRC):
        return False, f"Missing unit template: {BRIDGE_UNIT_SRC}"
    os.makedirs(os.path.dirname(BRIDGE_UNIT_DST), exist_ok=True)
    os.makedirs(os.path.dirname(BRIDGE_WRAPPER_DST), exist_ok=True)
    shutil.copy2(BRIDGE_UNIT_SRC, BRIDGE_UNIT_DST)
    if os.path.isfile(BRIDGE_WRAPPER_SRC):
        shutil.copy2(BRIDGE_WRAPPER_SRC, BRIDGE_WRAPPER_DST)
        os.chmod(BRIDGE_WRAPPER_DST, 0o755)
    _enable_linger()
    _run_systemctl(["daemon-reload"])
    return True, BRIDGE_UNIT_DST


def _enable_linger() -> None:
    user = _user_name()
    loginctl = shutil.which("loginctl")
    if not loginctl or not user:
        return
    subprocess.run(
        [loginctl, "enable-linger", user],
        capture_output=True,
        text=True,
        timeout=15,
    )


def _ensure_update_timer() -> tuple[bool, str]:
    if os.environ.get("GAMESPHERE_AUTO_UPDATE", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return True, "auto-update off"
    if not os.path.isfile(UPDATE_TIMER_SRC):
        return False, f"Missing unit template: {UPDATE_TIMER_SRC}"
    os.makedirs(os.path.dirname(UPDATE_BIN_DST), exist_ok=True)
    os.makedirs(UPDATE_UNIT_DIR, exist_ok=True)
    if os.path.isfile(UPDATE_SCRIPT_SRC):
        shutil.copy2(UPDATE_SCRIPT_SRC, UPDATE_BIN_DST)
        os.chmod(UPDATE_BIN_DST, 0o755)
    if os.path.isfile(UPDATE_SERVICE_SRC):
        shutil.copy2(UPDATE_SERVICE_SRC, os.path.join(UPDATE_UNIT_DIR, "gamesphere-import-update.service"))
    shutil.copy2(UPDATE_TIMER_SRC, os.path.join(UPDATE_UNIT_DIR, UPDATE_UNIT_NAME))
    _enable_linger()
    _run_systemctl(["daemon-reload"])
    ok, output = _run_systemctl(["enable", "--now", UPDATE_UNIT_NAME])
    return ok, output or UPDATE_UNIT_NAME


def _ensure_library_sync_timer() -> tuple[bool, str]:
    if not os.path.isfile(SYNC_TIMER_SRC):
        return False, f"Missing unit template: {SYNC_TIMER_SRC}"
    os.makedirs(UPDATE_UNIT_DIR, exist_ok=True)
    if os.path.isfile(SYNC_SERVICE_SRC):
        shutil.copy2(SYNC_SERVICE_SRC, os.path.join(UPDATE_UNIT_DIR, "gamesphere-library-sync.service"))
    shutil.copy2(SYNC_TIMER_SRC, os.path.join(UPDATE_UNIT_DIR, SYNC_UNIT_NAME))
    _enable_linger()
    _run_systemctl(["daemon-reload"])
    ok, output = _run_systemctl(["enable", "--now", SYNC_UNIT_NAME])
    return ok, output or SYNC_UNIT_NAME


def _library_sync_timer_state() -> str:
    ok, output = _run_systemctl(["is-active", SYNC_UNIT_NAME])
    if ok and output.strip() in ("active", "waiting"):
        return output.strip() or "active"
    enabled_ok, enabled_out = _run_systemctl(["is-enabled", SYNC_UNIT_NAME])
    if enabled_ok and "enabled" in enabled_out:
        return "waiting"
    if "inactive" in output:
        return "inactive"
    if "failed" in output:
        return "failed"
    return "unknown"


def _parse_json(raw: str) -> dict:
    """Parse JSON, tolerating log lines before/after the object (e.g. opus_codec INFO)."""
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {"raw": text}


def _parse_print_config(raw: str) -> dict:
    return _parse_json(raw)


def _parse_host_tuning_status(raw: str) -> dict:
    return _parse_json(raw)


def _mic_setup_script() -> str | None:
    for path in (
        os.path.join(INSTALL_DIR, "scripts/gamesphere-pc-mic-setup.sh"),
        os.path.join(_USER_HOME, ".local/bin/gamesphere-pc-mic-setup.sh"),
    ):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
        if os.path.isfile(path):
            return path
    return None


def _mic_test_launch_script() -> str | None:
    for path in (
        os.path.join(INSTALL_DIR, "scripts/gamesphere-mic-test-launch.sh"),
        os.path.join(_USER_HOME, ".local/bin/mic-test"),
        os.path.join(_USER_HOME, ".local/bin/gamesphere-mic-test-launch.sh"),
    ):
        if os.path.isfile(path):
            return path
    return None


def _session_gui_env() -> dict[str, str]:
    """Environment for launching a Game Mode GUI from the plugin process."""
    env = _subprocess_env()
    uid = None
    try:
        uid = pwd.getpwnam(_user_name()).pw_uid
    except KeyError:
        pass
    if uid is not None:
        runtime = f"/run/user/{uid}"
        env.setdefault("XDG_RUNTIME_DIR", runtime)
        dbus = os.path.join(runtime, "bus")
        if os.path.exists(dbus):
            env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={dbus}")
    # Prefer gamescope/Steam session display when PluginLoader has none.
    if not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
        try:
            import glob as _glob

            for proc_env in _glob.glob("/proc/[0-9]*/environ"):
                try:
                    with open(proc_env, "rb") as fh:
                        raw = fh.read()
                except OSError:
                    continue
                pairs = dict(
                    p.split("=", 1) for p in raw.decode("utf-8", "ignore").split("\0") if "=" in p
                )
                wayland = pairs.get("WAYLAND_DISPLAY") or ""
                display = pairs.get("DISPLAY") or ""
                if wayland.startswith("gamescope") or "gamescope" in (pairs.get("_") or ""):
                    if display:
                        env["DISPLAY"] = display
                    if wayland:
                        env["WAYLAND_DISPLAY"] = wayland
                    break
                if display and not env.get("DISPLAY"):
                    env["DISPLAY"] = display
        except Exception:
            pass
    if not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
        if os.path.exists("/tmp/.X11-unix/X1"):
            env["DISPLAY"] = ":1"
        elif os.path.exists("/tmp/.X11-unix/X0"):
            env["DISPLAY"] = ":0"
    return env


def _mic_peak_test(seconds: float = 3.0) -> dict:
    """Record a short clip from the default (or GameSphere) mic and report peak level."""
    import struct
    import tempfile
    import wave

    env = _subprocess_env()
    pactl = shutil.which("pactl")
    parecord = shutil.which("parecord")
    if not pactl or not parecord:
        return {"ok": False, "detail": "pactl/parecord not found (PipeWire/Pulse required)"}

    try:
        listed = subprocess.run(
            [pactl, "list", "short", "sources"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        names = {
            line.split()[1]
            for line in (listed.stdout or "").splitlines()
            if len(line.split()) >= 2 and not line.split()[1].endswith(".monitor")
        }
        got = subprocess.run(
            [pactl, "get-default-source"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        default_src = (got.stdout or "").strip()
    except Exception as exc:
        return {"ok": False, "detail": f"Could not resolve mic source: {exc}"}

    preferred = os.environ.get("GAMESPHERE_PC_MIC_SOURCE", "gamesphere_mic")
    # Try GameSphere Mic first (phone uplink), then the system default (DualSense / Jarvis).
    candidates: list[str] = []
    for src in (preferred, default_src):
        if src and src in names and src not in candidates:
            candidates.append(src)
    if not candidates and default_src:
        candidates.append(default_src)
    if not candidates:
        return {"ok": False, "detail": "No microphone source found"}

    timeout_bin = shutil.which("timeout")

    def _record_peak(source: str) -> tuple[float, str | None]:
        out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        out_path = out.name
        out.close()
        try:
            subprocess.run(
                [pactl, "set-source-mute", source, "0"],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
            )
            rec_cmd = [
                parecord,
                f"--device={source}",
                "--file-format=wav",
                "--rate=48000",
                "--channels=1",
                "--latency-msec=50",
                out_path,
            ]
            if timeout_bin:
                subprocess.run(
                    [timeout_bin, f"{max(1, int(seconds) + 1)}"] + rec_cmd,
                    capture_output=True,
                    text=True,
                    timeout=seconds + 5,
                    env=env,
                )
            else:
                proc = subprocess.Popen(
                    rec_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                )
                try:
                    proc.wait(timeout=seconds)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            with wave.open(out_path, "rb") as wf:
                frames = wf.readframes(wf.getnframes())
                n = len(frames) // 2
                if n <= 0:
                    return 0.0, "empty"
                samples = struct.unpack("<" + "h" * n, frames)
            return max(abs(s) for s in samples) / 32768.0, None
        except Exception as exc:
            return 0.0, str(exc)
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass

    best_source = candidates[0]
    best_peak = 0.0
    last_err: str | None = None
    for source in candidates:
        peak, err = _record_peak(source)
        if err and err != "empty":
            last_err = err
            continue
        if peak >= best_peak:
            best_peak = peak
            best_source = source
        # Loud enough — stop early.
        if peak >= 0.05:
            break

    if last_err and best_peak <= 0.0:
        return {"ok": False, "detail": f"Record failed: {last_err}", "source": best_source}

    peak_pct = round(best_peak * 100.0, 1)
    if peak_pct < 1.0:
        detail = (
            f"Peak {peak_pct}% — silent on {best_source}. "
            "Speak into the pad/mic, or start a GameSphere voice session for gamesphere_mic."
        )
        ok = False
    elif peak_pct < 5.0:
        detail = f"Peak {peak_pct}% — very quiet ({best_source})"
        ok = True
    else:
        detail = f"Peak {peak_pct}% — levels look good ({best_source})"
        ok = True
    return {
        "ok": ok,
        "detail": detail,
        "source": best_source,
        "peak_pct": peak_pct,
        "seconds": seconds,
    }


def _launch_mic_test_ui() -> dict:
    script = _mic_test_launch_script()
    if not script:
        return {
            "ok": False,
            "detail": "Mic Test UI not installed (expected scripts/gamesphere-mic-test-launch.sh or ~/.local/bin/mic-test)",
        }
    env = _session_gui_env()
    try:
        # Detach so Decky doesn't wait on the fullscreen UI.
        kwargs: dict = {
            "cwd": _USER_HOME,
            "env": env,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "start_new_session": True,
        }
        if script.endswith(".sh") or os.access(script, os.X_OK):
            cmd = ["/bin/bash", script] if script.endswith(".sh") else [script]
        else:
            cmd = ["/bin/bash", script]
        if os.geteuid() == 0:
            user = _user_name()
            try:
                pw = pwd.getpwnam(user)
            except KeyError:
                pw = None
            if pw is not None:
                def _preexec() -> None:
                    os.setgid(pw.pw_gid)
                    os.setuid(pw.pw_uid)

                kwargs["preexec_fn"] = _preexec
        subprocess.Popen(cmd, **kwargs)
        return {
            "ok": True,
            "detail": "Mic Test opening fullscreen — speak, then you'll hear playback. B/Esc to quit.",
        }
    except Exception as exc:
        return {"ok": False, "detail": f"Could not launch Mic Test: {exc}"}


class Plugin:
    async def get_status(self):
        """Fast parallel status — never block the QAM on a slow host-tuning probe."""
        loop = asyncio.get_event_loop()
        installed = _resolve_command() is not None
        version = ""
        paths: dict = {}
        host_tuning: dict = {}
        library_sync: dict = {}
        mic: dict = {}

        async def _bridge() -> str:
            if not installed:
                return "unknown"
            return await loop.run_in_executor(None, _bridge_service_state)

        async def _sync_timer() -> str:
            if not installed:
                return "unknown"
            return await loop.run_in_executor(None, _library_sync_timer_state)

        async def _version() -> str:
            if not installed:
                return ""
            ok, output, _ = await loop.run_in_executor(
                None, lambda: _run_sync(["--version"], timeout=8)
            )
            return output.strip() if ok else ""

        async def _paths() -> dict:
            if not installed:
                return {}
            ok, output, _ = await loop.run_in_executor(
                None, lambda: _run_sync(["--print-config"], timeout=12)
            )
            return _parse_print_config(output) if ok else {}

        async def _ht() -> dict:
            if not installed:
                return {}
            # ethtool/link probe is slow; never stall the QAM on it.
            try:
                ok, ht_out = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, lambda: _run_host_tuning_sync(["status"], timeout=2)
                    ),
                    timeout=2.5,
                )
                return _parse_host_tuning_status(ht_out) if ok else {}
            except Exception:
                return {}

        async def _sync() -> dict:
            if not installed:
                return {}
            ok, sync_out, _ = await loop.run_in_executor(
                None, lambda: _run_sync(["--library-sync-status"], timeout=10)
            )
            return _parse_json(sync_out) if ok else {}

        async def _mic() -> dict:
            if not installed:
                return {}
            ok, mic_out, _ = await loop.run_in_executor(
                None, lambda: _run_sync(["--mic-status"], timeout=10)
            )
            return _parse_json(mic_out) if ok else {}

        try:
            (
                bridge_state,
                sync_timer,
                version,
                paths,
                host_tuning,
                library_sync,
                mic,
            ) = await asyncio.wait_for(
                asyncio.gather(
                    _bridge(),
                    _sync_timer(),
                    _version(),
                    _paths(),
                    _ht(),
                    _sync(),
                    _mic(),
                ),
                timeout=12,
            )
        except Exception as exc:
            decky.logger.warning("get_status partial failure: %s", exc)
            bridge_state = "unknown"
            sync_timer = "unknown"

        return {
            "installed": installed,
            "install_kind": _install_kind(),
            "version": version,
            "paths": paths,
            "host_tuning": host_tuning,
            "bridge_service": bridge_state,
            "bridge_unit_installed": os.path.isfile(BRIDGE_UNIT_DST),
            "library_sync_timer": sync_timer,
            "library_sync": library_sync,
            "mic": mic,
        }

    async def run_import(
        self,
        dry_run: bool = True,
        no_restart: bool = False,
        host_tuning: bool = False,
        verbose: bool = False,
    ):
        args: list[str] = []
        if dry_run:
            args.append("--dry-run")
        if no_restart:
            args.append("--no-restart")
        if host_tuning:
            args.append("--host-tuning")
        if verbose:
            args.append("--verbose")
        ok, output, banner = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_sync(args)
        )
        return {"ok": ok, "output": output, "banner": banner}

    async def run_host_tuning_only(self):
        ok, output, banner = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_sync(["--host-tuning-only"])
        )
        return {"ok": ok, "output": output, "banner": banner}

    async def run_remove(self):
        ok, output, banner = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_sync(["--remove-games"])
        )
        return {"ok": ok, "output": output, "banner": banner}

    async def run_refresh_config(self):
        ok, output, banner = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_sync(["--auto-config"], timeout=60)
        )
        return {"ok": ok, "output": output, "banner": banner}

    async def run_check_update(self):
        ok, output, _ = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_sync(["--check-update"], timeout=60)
        )
        return {"ok": ok, "output": output}

    async def run_apply_update(self):
        ok, output, _ = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_sync(["--apply-update"], timeout=600)
        )
        return {"ok": ok, "output": output}

    async def set_bridge_enabled(self, enabled: bool):
        # Only (re)install unit files when turning the bridge ON. Doing it while
        # disabling could overwrite a working unit from a stale INSTALL_DIR, or
        # fail outright and leave the toggle stuck.
        if enabled:
            ok, msg = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _ensure_bridge_unit()
            )
            if not ok:
                return {"ok": False, "output": msg, "state": _bridge_service_state()}

        if enabled:
            ok, output = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _run_systemctl(["enable", "--now", BRIDGE_UNIT_NAME]),
            )
        else:
            ok, output = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _run_systemctl(["disable", "--now", BRIDGE_UNIT_NAME]),
            )
        return {"ok": ok, "output": output, "state": _bridge_service_state()}

    async def set_library_sync_enabled(self, enabled: bool):
        if enabled:
            ok, msg = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _ensure_library_sync_timer()
            )
            return {
                "ok": ok,
                "output": msg,
                "state": _library_sync_timer_state(),
            }
        ok, output = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _run_systemctl(["disable", "--now", SYNC_UNIT_NAME]),
        )
        return {"ok": ok, "output": output, "state": _library_sync_timer_state()}

    async def run_library_sync_now(self):
        ok, output, banner = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_sync(["--library-sync", "--no-restart"], timeout=600)
        )
        return {"ok": ok, "output": output, "banner": banner}

    async def run_setup_mic(self):
        ok, output, banner = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_sync(["--setup-mic"], timeout=120)
        )
        return {"ok": ok, "output": output, "banner": banner}

    async def run_mic_peak_test(self, seconds: float = 3.0):
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _mic_peak_test(float(seconds) if seconds else 3.0)
        )
        return result

    async def launch_mic_test_ui(self):
        result = await asyncio.get_event_loop().run_in_executor(None, _launch_mic_test_ui)
        return result

    async def set_mic_aec(self, enabled: bool):
        script = _mic_setup_script()
        if not script:
            return {
                "ok": False,
                "output": "gamesphere-pc-mic-setup.sh not found — run install-linux.sh",
            }
        action = "aec-on" if enabled else "aec-off"
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _run_as_user(
                    ["/bin/bash", script, action],
                    cwd=INSTALL_DIR if os.path.isdir(INSTALL_DIR) else None,
                    timeout=120,
                ),
            )
            output = ((result.stdout or "") + (result.stderr or "")).strip()
            return {"ok": result.returncode == 0, "output": output or action}
        except Exception as exc:
            return {"ok": False, "output": str(exc)}

    async def run_doctor(self):
        ok, output, banner = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_sync(["--doctor"], timeout=90)
        )
        return {"ok": ok, "output": output, "banner": banner}

    async def init_host_tuning(self):
        ok, output = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_host_tuning_sync(["init"], timeout=60)
        )
        return {"ok": ok, "output": output}

    async def _main(self):
        decky.logger.info(
            "GameSphere Companion Decky plugin loaded (user_home=%s, no systemd side effects on reload)",
            _USER_HOME,
        )

    async def _unload(self):
        pass

    async def _uninstall(self):
        pass
