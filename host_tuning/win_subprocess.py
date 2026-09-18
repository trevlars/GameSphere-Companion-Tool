"""Hide console windows when spawning cmd/powershell on Windows."""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence


def hidden_creationflags() -> int:
    flags = 0
    if sys.platform != "win32":
        return flags
    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    return flags


def hidden_startupinfo() -> Optional[Any]:
    if sys.platform != "win32":
        return None
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0  # SW_HIDE
    return startup


def popen_hidden(
    cmd: Sequence[str],
    *,
    stdin=None,
    stdout=None,
    stderr=None,
    close_fds: bool = True,
    **extra: Any,
) -> subprocess.Popen:
    kwargs: Dict[str, Any] = {
        "stdin": stdin if stdin is not None else subprocess.DEVNULL,
        "stdout": stdout if stdout is not None else subprocess.DEVNULL,
        "stderr": stderr if stderr is not None else subprocess.DEVNULL,
        "close_fds": close_fds,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = hidden_creationflags()
        kwargs["startupinfo"] = hidden_startupinfo()
    kwargs.update(extra)
    return subprocess.Popen(list(cmd), **kwargs)


def run_hidden(
    cmd: Sequence[str],
    *,
    timeout: Optional[float] = None,
    capture_output: bool = False,
    text: bool = False,
    check: bool = False,
) -> subprocess.CompletedProcess:
    kwargs: Dict[str, Any] = {
        "timeout": timeout,
        "check": check,
    }
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["stdin"] = subprocess.DEVNULL
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    if text:
        kwargs["text"] = True
    if sys.platform == "win32":
        kwargs["creationflags"] = hidden_creationflags()
        kwargs["startupinfo"] = hidden_startupinfo()
    return subprocess.run(list(cmd), **kwargs)
