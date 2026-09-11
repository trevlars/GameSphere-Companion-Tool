"""DeckyLoader backend for GameSphere Import Tool."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess

import decky

INSTALL_DIR = os.path.expanduser("~/.local/share/gamesphere-import-tool")
BIN_CANDIDATES = [
    os.path.expanduser("~/.local/bin/gamesphere-import"),
    os.path.join(INSTALL_DIR, "main.py"),
]
BRIDGE_UNIT_NAME = "gamesphere-host-bridge.service"
BRIDGE_UNIT_SRC = os.path.join(INSTALL_DIR, "scripts/systemd/gamesphere-host-bridge.service")
BRIDGE_UNIT_DST = os.path.expanduser(f"~/.config/systemd/user/{BRIDGE_UNIT_NAME}")


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
    return None


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


def _run_sync(args: list[str], timeout: int = 600) -> tuple[bool, str, str | None]:
    cmd = _resolve_command()
    if not cmd:
        return False, "GameSphere Import CLI not found. Run scripts/install-linux.sh on the host.", None

    full = cmd + args
    decky.logger.info("Running: %s", " ".join(full))
    try:
        result = subprocess.run(
            full,
            cwd=INSTALL_DIR if os.path.isdir(INSTALL_DIR) else None,
            capture_output=True,
            text=True,
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
        result = subprocess.run(
            full,
            cwd=INSTALL_DIR if os.path.isdir(INSTALL_DIR) else None,
            capture_output=True,
            text=True,
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
        result = subprocess.run(
            [systemctl, "--user"] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )
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
    shutil.copy2(BRIDGE_UNIT_SRC, BRIDGE_UNIT_DST)
    _run_systemctl(["daemon-reload"])
    return True, BRIDGE_UNIT_DST


def _parse_print_config(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def _parse_host_tuning_status(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


class Plugin:
    async def get_status(self):
        installed = _resolve_command() is not None
        version = ""
        paths: dict = {}
        host_tuning: dict = {}
        bridge_state = _bridge_service_state() if installed else "unknown"

        if installed:
            ok, output, _ = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _run_sync(["--version"], timeout=15)
            )
            if ok:
                version = output.strip()

            ok, output, _ = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _run_sync(["--print-config"], timeout=30)
            )
            if ok:
                paths = _parse_print_config(output)

            ok, ht_out = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _run_host_tuning_sync(["status"], timeout=30)
            )
            if ok:
                host_tuning = _parse_host_tuning_status(ht_out)

        return {
            "installed": installed,
            "version": version,
            "paths": paths,
            "host_tuning": host_tuning,
            "bridge_service": bridge_state,
            "bridge_unit_installed": os.path.isfile(BRIDGE_UNIT_DST),
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

    async def init_host_tuning(self):
        ok, output = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_host_tuning_sync(["init", "--enable-all"], timeout=60)
        )
        return {"ok": ok, "output": output}

    async def _main(self):
        decky.logger.info("GameSphere Import Decky plugin loaded")

    async def _unload(self):
        pass

    async def _uninstall(self):
        pass
