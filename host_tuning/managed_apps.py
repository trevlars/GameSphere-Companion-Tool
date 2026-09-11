"""Kill / relaunch managed apps around streaming sessions."""

from __future__ import annotations

import logging
import os
from typing import List

import psutil

from host_tuning.config import HostTuningConfig, ManagedAppEntry, load_config, save_config


def load_managed_apps(cfg: HostTuningConfig | None = None) -> List[ManagedAppEntry]:
    cfg = cfg or load_config()
    return [a for a in cfg.managed_apps if a.path]


def save_managed_apps(apps: List[ManagedAppEntry], cfg: HostTuningConfig | None = None) -> None:
    cfg = cfg or load_config()
    cfg.managed_apps = apps
    save_config(cfg)


def kill_running(cfg: HostTuningConfig | None = None) -> List[str]:
    killed: List[str] = []
    for app in load_managed_apps(cfg):
        if not app.auto_manage:
            continue
        try:
            if _kill_by_path(app.path):
                killed.append(app.path)
                logging.info("Managed app stopped: %s", app.name or app.path)
        except Exception as exc:
            logging.debug("Managed app kill failed %s: %s", app.path, exc)
    return killed


def start_apps(paths: List[str]) -> None:
    import subprocess

    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        try:
            subprocess.Popen([path], shell=False, close_fds=True)
            logging.info("Managed app restarted: %s", path)
        except OSError as exc:
            logging.warning("Failed to restart %s: %s", path, exc)


def _kill_by_path(exe_path: str) -> bool:
    exe_path = os.path.normpath(exe_path)
    exe_name = os.path.basename(exe_path)
    name_no_ext = os.path.splitext(exe_name)[0]
    found = False
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            pinfo = proc.info
            proc_exe = pinfo.get("exe") or ""
            if proc_exe and os.path.normpath(proc_exe).lower() == exe_path.lower():
                proc.kill()
                found = True
                continue
            if pinfo.get("name", "").lower() == name_no_ext.lower():
                if proc_exe and os.path.normpath(proc_exe).lower() == exe_path.lower():
                    proc.kill()
                    found = True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return found
