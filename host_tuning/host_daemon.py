"""Always-on GameSphere Companion host daemon.

Import GUI is optional. This process stays up for JOINPIN / TRUSTED / JOINREQ,
couch-coop slots, WAN UPnP, voice UDP 48020, and WANNAPLAY.

Never restarts Sunshine or Apollo. Restarting the bridge must not take down
an active stream.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Sequence

UNIT_NAME = "gamesphere-host-bridge.service"
WRAPPER_NAME = "gamesphere-host-bridge"
TASK_NAME = "GameSphereHostBridge"
RUN_VALUE_NAME = "GameSphereHostBridge"
LAUNCH_LABEL = "io.github.trevlars.gamesphere-host-bridge"
FLATPAK_ID = "io.github.trevlars.GamesphereImportTool"

# Process names we must never taskkill / systemctl restart from this module.
SUNSHINE_NAMES = (
    "sunshine",
    "sunshine.exe",
    "sunshine-runtime",
    "apollo",
    "apollo.exe",
)

DAEMON_FLAGS = (
    "--host-bridge",
    "--host-daemon",
    "--host-daemon-install",
    "--host-daemon-uninstall",
    "--host-daemon-status",
)


def host_bridge_enabled() -> bool:
    val = os.environ.get("GAMESPHERE_ENABLE_HOST_BRIDGE", "1").strip().lower()
    return val not in ("0", "false", "no", "off")


def repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def linux_install_dir() -> str:
    return os.path.expanduser(
        os.environ.get("GAMESPHERE_IMPORT_DIR") or "~/.local/share/gamesphere-import-tool"
    )


def linux_unit_dir() -> str:
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(xdg, "systemd", "user")


def linux_wrapper_path() -> str:
    return os.path.expanduser(
        os.environ.get("GAMESPHERE_HOST_BRIDGE_BIN") or f"~/.local/bin/{WRAPPER_NAME}"
    )


def pid_path() -> str:
    from host_tuning.config import config_dir

    return os.path.join(config_dir(), "host-bridge.pid")


def _write_pid() -> None:
    path = pid_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))


def _read_pid() -> Optional[int]:
    try:
        with open(pid_path(), encoding="utf-8") as fh:
            return int((fh.read() or "0").strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    if sys.platform == "win32":
        return True
    try:
        with open(f"/proc/{pid}/cmdline", "r", encoding="utf-8", errors="ignore") as fh:
            cmdline = fh.read()
    except OSError:
        return True
    blob = cmdline.lower()
    if any(name in blob for name in SUNSHINE_NAMES) and "gamesphere" not in blob and "host-bridge" not in blob:
        return False
    return True


def argv_touches_sunshine(argv: Sequence[str]) -> bool:
    """True if a subprocess argv would start/stop/restart Sunshine or Apollo."""
    joined = " ".join(str(a).lower() for a in argv)
    if "gamesphere-host-bridge" in joined:
        return False
    if "--host-bridge" in joined or "--host-daemon" in joined:
        return False
    tokens = [str(a).lower() for a in argv]
    if any(t in SUNSHINE_NAMES or t.rstrip(".exe") in ("sunshine", "apollo") for t in tokens):
        if "restart" in tokens or "stop" in tokens or "kill" in tokens or "start" in tokens:
            return True
    if "systemctl" in joined and ("sunshine" in joined or "apollo" in joined):
        return True
    if "taskkill" in joined and ("sunshine" in joined or "apollo" in joined):
        return True
    return False


def daemon_command() -> List[str]:
    """Foreground command used by systemd / LaunchAgent / Task Scheduler."""
    if getattr(sys, "frozen", False):
        return [os.path.abspath(sys.executable), "--host-daemon"]
    main_py = os.path.join(repo_root(), "main.py")
    return [sys.executable, main_py, "--host-bridge"]


def _linux_unit_working_dir() -> str:
    """systemd WorkingDirectory for the unit.

    Keeps the portable ``%h`` form for a default install, but honours a custom
    ``GAMESPHERE_IMPORT_DIR`` so the daemon does not start in the wrong tree.
    """
    default = os.path.expanduser("~/.local/share/gamesphere-import-tool")
    install_dir = linux_install_dir()
    if os.path.normpath(install_dir) == os.path.normpath(default):
        return "%h/.local/share/gamesphere-import-tool"
    return install_dir


def linux_unit_body() -> str:
    return (
        "[Unit]\n"
        "Description=GameSphere Companion host daemon (TCP 47998)\n"
        "Documentation=https://github.com/trevlars/Gamesphere-Import-Tool/blob/main/docs/HOST_INTEGRATION.md\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "# Ordering only — never BindsTo/PartOf Sunshine. Restarting this unit must\n"
        "# not restart or stop sunshine.service.\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory=-{_linux_unit_working_dir()}\n"
        "Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin\n"
        "Environment=PYTHONUNBUFFERED=1\n"
        f"ExecStart=%h/.local/bin/{WRAPPER_NAME}\n"
        "Restart=always\n"
        "RestartSec=3\n"
        "TimeoutStopSec=15\n"
        "KillMode=process\n"
        "SuccessExitStatus=0 SIGTERM SIGINT\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n"
        "SyslogIdentifier=gamesphere-host-bridge\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def macos_plist_body(program_args: Sequence[str], working_dir: str) -> str:
    args_xml = "".join(f"    <string>{_xml_escape(a)}</string>\n" for a in program_args)
    work = _xml_escape(working_dir)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "  <key>Label</key>\n"
        f"  <string>{LAUNCH_LABEL}</string>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array>\n"
        f"{args_xml}"
        "  </array>\n"
        "  <key>WorkingDirectory</key>\n"
        f"  <string>{work}</string>\n"
        "  <key>RunAtLoad</key>\n"
        "  <true/>\n"
        "  <key>KeepAlive</key>\n"
        "  <true/>\n"
        "  <key>ThrottleInterval</key>\n"
        "  <integer>3</integer>\n"
        "  <key>ProcessType</key>\n"
        "  <string>Background</string>\n"
        "</dict>\n"
        "</plist>\n"
    )


def windows_task_xml(command: str, arguments: str) -> str:
    """Logon task, hidden, restart on failure. Limited rights — no Windows Service."""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>GameSphere Companion host daemon (TCP 47998). Does not restart Sunshine.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT2M</Interval>
      <Count>10</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{_xml_escape(command)}</Command>
      <Arguments>{_xml_escape(arguments)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _xml_escape(value: str) -> str:
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _copy_or_write(src: Optional[str], dest: str, body: str, mode: int = 0o644) -> None:
    import shutil

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if src and os.path.isfile(src):
        shutil.copy2(src, dest)
    elif body:
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(body)
    else:
        raise FileNotFoundError(dest)
    os.chmod(dest, mode)


def _enable_linger() -> str:
    if not sys.platform.startswith("linux"):
        return ""
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if not user:
        try:
            import pwd

            user = pwd.getpwuid(os.getuid()).pw_name
        except Exception:
            return ""
    loginctl = _which("loginctl")
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
        return f"linger-enabled:{user}"
    except Exception:
        return ""


def _which(name: str) -> Optional[str]:
    import shutil

    return shutil.which(name)


def _systemctl_user(args: Sequence[str], timeout: int = 20) -> subprocess.CompletedProcess:
    argv = ["systemctl", "--user", *args]
    if argv_touches_sunshine(argv):
        raise RuntimeError("refusing to invoke systemctl on Sunshine from host daemon")
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


def install_linux() -> Dict[str, Any]:
    root = repo_root()
    install_dir = linux_install_dir()
    wrapper_src = os.path.join(root, "scripts", "gamesphere-host-bridge.sh")
    if not os.path.isfile(wrapper_src) and os.path.isfile(
        os.path.join(install_dir, "scripts", "gamesphere-host-bridge.sh")
    ):
        wrapper_src = os.path.join(install_dir, "scripts", "gamesphere-host-bridge.sh")
    unit_src = os.path.join(root, "scripts", "systemd", UNIT_NAME)
    if not os.path.isfile(unit_src):
        unit_src = os.path.join(install_dir, "scripts", "systemd", UNIT_NAME)
    wrapper_dest = linux_wrapper_path()
    unit_dest = os.path.join(linux_unit_dir(), UNIT_NAME)
    if os.path.isfile(wrapper_src):
        _copy_or_write(wrapper_src, wrapper_dest, "", 0o755)
    else:
        raise RuntimeError(f"missing host-bridge wrapper ({wrapper_src})")
    unit_body = linux_unit_body()
    _copy_or_write(unit_src if os.path.isfile(unit_src) else None, unit_dest, unit_body)
    linger = _enable_linger()
    stack: Dict[str, Any] = {}
    try:
        from host_tuning import host_stack

        stack = host_stack.install_linux_stack()
    except Exception as exc:
        logging.debug("host stack install: %s", exc)
        stack = {"ok": False, "error": str(exc)}
    if not _which("systemctl"):
        return {
            "ok": True,
            "unit": unit_dest,
            "wrapper": wrapper_dest,
            "linger": linger,
            "enabled": False,
            "host_stack": stack,
            "sunshine_touched": False,
        }
    _systemctl_user(["daemon-reload"])
    enabled = _systemctl_user(["enable", "--now", UNIT_NAME])
    return {
        "ok": enabled.returncode == 0,
        "unit": unit_dest,
        "wrapper": wrapper_dest,
        "linger": linger,
        "enabled": enabled.returncode == 0,
        "output": (enabled.stderr or enabled.stdout or "").strip(),
        "host_stack": stack,
        "sunshine_touched": False,
    }


def uninstall_linux() -> Dict[str, Any]:
    if _which("systemctl"):
        _systemctl_user(["disable", "--now", UNIT_NAME])
    unit = os.path.join(linux_unit_dir(), UNIT_NAME)
    try:
        os.remove(unit)
    except OSError:
        pass
    return {"ok": True, "removed": unit}


def linux_status() -> Dict[str, Any]:
    if not _which("systemctl"):
        return {"ok": True, "state": "no-systemctl", "unit": UNIT_NAME}
    active = _systemctl_user(["is-active", UNIT_NAME])
    enabled = _systemctl_user(["is-enabled", UNIT_NAME])
    return {
        "ok": True,
        "unit": UNIT_NAME,
        "state": (active.stdout or "").strip() or "unknown",
        "unit_enabled": (enabled.stdout or "").strip() or "unknown",
    }


def macos_plist_path() -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCH_LABEL}.plist")


def install_macos() -> Dict[str, Any]:
    if sys.platform != "darwin":
        return {"ok": False, "error": "not macos"}
    cmd = daemon_command()
    work = repo_root()
    dest = macos_plist_path()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(macos_plist_body(cmd, work))
    uid = os.getuid()
    loaded = subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", dest],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    boot = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", dest],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if boot.returncode != 0:
        loaded = subprocess.run(
            ["launchctl", "load", "-w", dest],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        ok = loaded.returncode == 0
        output = (loaded.stderr or loaded.stdout or boot.stderr or "").strip()
    else:
        kick = subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{uid}/{LAUNCH_LABEL}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        ok = kick.returncode == 0 or boot.returncode == 0
        output = (kick.stderr or boot.stderr or "").strip()
    return {"ok": ok, "plist": dest, "output": output}


def uninstall_macos() -> Dict[str, Any]:
    dest = macos_plist_path()
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}", dest],
        capture_output=True,
        timeout=15,
        check=False,
    )
    subprocess.run(
        ["launchctl", "unload", "-w", dest],
        capture_output=True,
        timeout=15,
        check=False,
    )
    try:
        os.remove(dest)
    except OSError:
        pass
    return {"ok": True, "removed": dest}


def macos_status() -> Dict[str, Any]:
    dest = macos_plist_path()
    uid = os.getuid()
    listed = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{LAUNCH_LABEL}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return {
        "ok": True,
        "plist": dest,
        "installed": os.path.isfile(dest),
        "loaded": listed.returncode == 0,
    }


def _windows_exe_and_args() -> tuple[str, str]:
    cmd = daemon_command()
    return cmd[0], " ".join(f'"{a}"' if " " in a else a for a in cmd[1:])


def install_windows() -> Dict[str, Any]:
    if sys.platform != "win32":
        return {"ok": False, "error": "not windows"}
    exe, args = _windows_exe_and_args()
    if not os.path.isfile(exe):
        return {
            "ok": False,
            "error": "host_daemon_exe_missing",
            "exe": exe,
            "hint": "Reinstall GamesphereImportTool.exe or run --host-daemon-uninstall to stop broken autostart.",
        }
    # Skip re-registering only when the task is present *and* still points at
    # this exe, so an updated/moved install repairs its own autostart.
    if _windows_task_points_at(exe) and is_running():
        return {
            "ok": True,
            "skipped": True,
            "already": True,
            "exe": exe,
            "args": args,
            "task": TASK_NAME,
            "spawned": False,
            "sunshine_touched": False,
        }
    results: Dict[str, Any] = {"ok": True, "exe": exe, "args": args}
    run_ok = _windows_register_run(exe, args)
    results["hkcu_run"] = run_ok
    task_ok, task_msg = _windows_register_task(exe, args, run_now=not is_running())
    results["task"] = task_ok
    results["task_output"] = task_msg
    spawned = spawn_detached() if not is_running() else False
    results["spawned"] = spawned
    try:
        from host_tuning import host_stack

        results["host_stack"] = host_stack.install_windows_stack()
    except Exception as exc:
        logging.debug("windows host stack: %s", exc)
        results["host_stack"] = {"error": str(exc)}
    results["ok"] = bool(run_ok or task_ok or spawned)
    results["sunshine_touched"] = False
    return results


def uninstall_windows() -> Dict[str, Any]:
    _windows_unregister_run()
    subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        timeout=15,
        check=False,
    )
    stop_daemon_process()
    return {"ok": True}


def _windows_register_run(exe: str, args: str) -> bool:
    try:
        import winreg

        key = winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
        )
        cmd = f'"{exe}" {args}'.strip()
        winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        return True
    except Exception as exc:
        logging.warning("HKCU Run register failed: %s", exc)
        return False


def _windows_unregister_run() -> None:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, RUN_VALUE_NAME)
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
    except Exception:
        pass


def _windows_task_points_at(exe: str) -> Optional[bool]:
    """Does the installed logon task still launch ``exe``?

    ``None`` means the task is not installed. A task left pointing at an old
    install path silently stops starting the daemon at login.
    """
    from host_tuning.win_subprocess import run_hidden

    queried = run_hidden(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/XML"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if queried.returncode != 0:
        return None
    return os.path.normcase(exe) in os.path.normcase(queried.stdout or "")


def _windows_register_task(exe: str, args: str, *, run_now: bool = True) -> tuple[bool, str]:
    import tempfile

    from host_tuning.win_subprocess import run_hidden

    matches = _windows_task_points_at(exe)
    if matches:
        if run_now and not is_running():
            run_hidden(["schtasks", "/Run", "/TN", TASK_NAME], timeout=15)
        return True, "existing"
    if matches is False:
        logging.info("Refreshing %s — logon task pointed at a different exe", TASK_NAME)

    xml_body = windows_task_xml(exe, args)
    tmp = tempfile.NamedTemporaryFile(prefix="gs-host-bridge-", suffix=".xml", delete=False)
    try:
        tmp.write(xml_body.encode("utf-16"))
        tmp.close()
        created = run_hidden(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", tmp.name, "/F"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if created.returncode == 0:
            if run_now and not is_running():
                run_hidden(["schtasks", "/Run", "/TN", TASK_NAME], timeout=15)
            return True, (created.stdout or "").strip() or TASK_NAME
        # Fallback: ONLOGON without XML restart policy.
        tr = f'"{exe}" {args}'.strip()
        fallback = run_hidden(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", tr, "/SC", "ONLOGON", "/RL", "LIMITED", "/F"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        ok = fallback.returncode == 0
        return ok, ((fallback.stderr or created.stderr or created.stdout or "")).strip()
    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass


def windows_status() -> Dict[str, Any]:
    from host_tuning.win_subprocess import run_hidden

    queried = run_hidden(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return {
        "ok": True,
        "task": TASK_NAME,
        "task_installed": queried.returncode == 0,
        "pid": _read_pid(),
        "alive": bool(_read_pid() and _pid_alive(_read_pid() or 0)),
    }


def spawn_detached() -> bool:
    """Start the daemon in the background. Caller (GUI) does not own its lifetime."""
    if is_running():
        return True
    cmd = daemon_command()
    if argv_touches_sunshine(cmd):
        raise RuntimeError("refusing to spawn Sunshine from host daemon")
    exe = cmd[0] if cmd else ""
    if exe and os.path.isabs(exe) and not os.path.exists(exe):
        logging.warning("host daemon not spawned — missing executable %s", exe)
        return False
    kwargs: Dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        from host_tuning.win_subprocess import hidden_creationflags, hidden_startupinfo

        kwargs["creationflags"] = hidden_creationflags()
        kwargs["startupinfo"] = hidden_startupinfo()
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except Exception as exc:
        logging.warning("host daemon spawn failed: %s", exc)
        return False
    # Confirm it actually stayed up; reporting success for a process that died
    # immediately made the bridge look enabled with nothing on TCP 47998.
    for _ in range(10):
        time.sleep(0.2)
        if proc.poll() is not None:
            logging.warning(
                "host daemon exited immediately (code %s) — autostart not healthy",
                proc.returncode,
            )
            return False
        if is_running():
            return True
    return proc.poll() is None


def stop_daemon_process() -> None:
    """Stop our daemon PID only. Never taskkill Sunshine."""
    pid = _read_pid()
    if not pid or pid == os.getpid():
        return
    if not _pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    if sys.platform == "win32":
        from host_tuning.win_subprocess import run_hidden

        run_hidden(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10)


def is_running() -> bool:
    if sys.platform.startswith("linux") and _which("systemctl"):
        active = _systemctl_user(["is-active", UNIT_NAME])
        if (active.stdout or "").strip() == "active":
            return True
    pid = _read_pid()
    return bool(pid and _pid_alive(pid))


def install_autostart() -> Dict[str, Any]:
    if not host_bridge_enabled():
        return {"ok": True, "skipped": True, "reason": "GAMESPHERE_ENABLE_HOST_BRIDGE=0"}
    if sys.platform.startswith("linux"):
        return install_linux()
    if sys.platform == "win32":
        return install_windows()
    if sys.platform == "darwin":
        return install_macos()
    return {"ok": False, "error": f"unsupported platform {sys.platform}"}


def uninstall_autostart() -> Dict[str, Any]:
    if sys.platform.startswith("linux"):
        return uninstall_linux()
    if sys.platform == "win32":
        return uninstall_windows()
    if sys.platform == "darwin":
        return uninstall_macos()
    return {"ok": False, "error": f"unsupported platform {sys.platform}"}


def status() -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": True,
        "pid": _read_pid(),
        "running": is_running(),
        "platform": sys.platform,
        "enabled": host_bridge_enabled(),
    }
    if sys.platform.startswith("linux"):
        payload.update(linux_status())
    elif sys.platform == "win32":
        payload.update(windows_status())
    elif sys.platform == "darwin":
        payload.update(macos_status())
    return payload


def ensure_running() -> Dict[str, Any]:
    """Install autostart (if needed) and start the daemon. Safe from the import GUI."""
    if not host_bridge_enabled():
        return {"ok": True, "skipped": True}
    installed = install_autostart()
    if sys.platform.startswith("linux") and _which("systemctl"):
        started = _systemctl_user(["start", UNIT_NAME])
        installed["started"] = started.returncode == 0
        return installed
    if not is_running():
        installed["spawned"] = spawn_detached()
    return installed


def restart_host_bridge_only() -> Dict[str, Any]:
    """Reload the Companion daemon. Never restarts Sunshine/Apollo."""
    if sys.platform.startswith("linux") and _which("systemctl"):
        result = _systemctl_user(["restart", UNIT_NAME])
        return {
            "ok": result.returncode == 0,
            "unit": UNIT_NAME,
            "output": (result.stderr or result.stdout or "").strip(),
            "sunshine_touched": False,
        }
    stop_daemon_process()
    time.sleep(0.4)
    return {"ok": spawn_detached(), "sunshine_touched": False}


def run_bridge_forever(port: int = 0) -> int:
    """Foreground loop for systemd / LaunchAgent / --host-daemon."""
    from host_tuning.bridge import GameSphereBridge
    from host_tuning.config import load_config
    from host_tuning import session_telemetry
    from host_tuning.service import write_prep_scripts

    try:
        from platform_paths import apply_detected_paths

        apply_detected_paths()
    except Exception:
        logging.debug("apply_detected_paths skipped", exc_info=True)

    write_prep_scripts()
    cfg = load_config()
    listen = port or cfg.bridge_port or 47998
    apps_json = (
        os.environ.get("SUNSHINE_APPS_JSON_PATH")
        or os.environ.get("sunshine_apps_json_path")
        or ""
    )
    stop = threading.Event()

    def _handle_stop(_signum=None, _frame=None) -> None:
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle_stop)
        except Exception:
            pass

    _write_pid()
    tray: Optional[threading.Thread] = None
    if sys.platform == "win32" and os.environ.get("GAMESPHERE_HOST_DAEMON_TRAY", "1") != "0":
        tray = threading.Thread(target=_windows_tray, args=(stop,), daemon=True)
        tray.start()

    logging.info(
        "GameSphere Companion host daemon on TCP %s (JOINPIN/coop/WAN/voice) — not Sunshine",
        listen,
    )
    while not stop.is_set():
        bridge = GameSphereBridge()
        try:
            log_path = session_telemetry.detect_sunshine_log_path(cfg.sunshine_log_path)
            bridge.start(port=listen, log_path=log_path, apps_json_path=apps_json)
            while not stop.is_set() and bridge.is_alive():
                time.sleep(1)
            if stop.is_set():
                bridge.stop()
                break
            logging.warning("host bridge thread ended; restarting in 3s (Sunshine untouched)")
        except KeyboardInterrupt:
            stop.set()
            try:
                bridge.stop()
            except Exception:
                pass
            break
        except Exception:
            logging.exception("host bridge crashed; restarting in 3s (Sunshine untouched)")
        try:
            bridge.stop()
        except Exception:
            pass
        if not stop.is_set():
            time.sleep(3)
    try:
        session_telemetry.flush_client_telemetry()
    except Exception:
        logging.debug("telemetry flush on shutdown failed", exc_info=True)
    try:
        os.remove(pid_path())
    except OSError:
        pass
    return 0


def handle_argv(argv: Optional[Sequence[str]] = None) -> Optional[int]:
    """If argv is a daemon command, run it and return an exit code. Else None."""
    args = list(argv if argv is not None else sys.argv[1:])
    if not any(flag in args for flag in DAEMON_FLAGS):
        return None
    if "--host-daemon-status" in args:
        print(json.dumps(status(), indent=2))
        return 0
    if "--host-daemon-uninstall" in args:
        print(json.dumps(uninstall_autostart(), indent=2))
        return 0
    if "--host-daemon-install" in args:
        print(json.dumps(ensure_running(), indent=2))
        return 0
    # --host-bridge / --host-daemon: foreground
    return run_bridge_forever()


def _windows_tray(stop: threading.Event) -> None:
    """Hidden notification-area icon. Closing the import wizard does not stop us."""
    if os.environ.get("GAMESPHERE_HOST_DAEMON_TRAY", "1").strip() in ("0", "false", "no"):
        return
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32

    HWND_MESSAGE = -3
    WM_DESTROY = 0x0002
    WM_APP = 0x8000
    WM_TRAY = WM_APP + 1
    WM_LBUTTONDBLCLK = 0x0203
    NIM_ADD = 0x00000000
    NIM_DELETE = 0x00000002
    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    IDI_APPLICATION = 32512

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    class NOTIFYICONDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
        ]

    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        if msg == WM_TRAY and lparam == WM_LBUTTONDBLCLK:
            try:
                spawn_gui()
            except Exception:
                pass
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    proc = WNDPROC(wnd_proc)
    wc = WNDCLASS()
    wc.lpfnWndProc = proc
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.lpszClassName = "GameSphereHostBridgeTray"
    if not user32.RegisterClassW(ctypes.byref(wc)):
        return
    hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "", 0, 0, 0, 0, 0, HWND_MESSAGE, None, wc.hInstance, None)
    if not hwnd:
        return
    nid = NOTIFYICONDATA()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
    nid.hWnd = hwnd
    nid.uID = 1
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    nid.uCallbackMessage = WM_TRAY
    nid.hIcon = user32.LoadIconW(None, ctypes.c_wchar_p(IDI_APPLICATION))
    nid.szTip = "GameSphere Companion — host daemon"
    shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hWnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
        ]

    msg = MSG()
    while not stop.is_set():
        ret = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
        if ret:
            if msg.message == WM_DESTROY:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        else:
            time.sleep(0.2)
    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))


def spawn_gui() -> None:
    from host_tuning.win_subprocess import popen_hidden

    if getattr(sys, "frozen", False):
        cmd = [os.path.abspath(sys.executable)]
    else:
        cmd = [sys.executable, os.path.join(repo_root(), "gui.py")]
    if sys.platform == "win32":
        popen_hidden(cmd, close_fds=True)
        return
    subprocess.Popen(cmd, start_new_session=True)
