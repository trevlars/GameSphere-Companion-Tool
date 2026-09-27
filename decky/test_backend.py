#!/usr/bin/env python3
"""Smoke-test Decky plugin backend without Decky runtime (for CI / SSH)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys

USER_HOME = os.environ.get("DECKY_USER_HOME") or os.path.expanduser("~")
INSTALL_DIR = os.path.join(USER_HOME, ".local/share/gamesphere-import-tool")
PLUGIN_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "main.py",
)
if not os.path.isfile(PLUGIN_PATH):
    PLUGIN_PATH = os.path.join(INSTALL_DIR, "decky", "main.py")


class FakeLogger:
    def info(self, msg, *args):
        print("INFO:", msg % args if args else msg)


class FakeDecky:
    logger = FakeLogger()


def load_plugin():
    os.environ.setdefault("DECKY_USER_HOME", USER_HOME)
    os.environ.setdefault("DECKY_USER", os.environ.get("USER") or os.environ.get("LOGNAME") or "")
    spec = importlib.util.spec_from_file_location("decky_plugin", PLUGIN_PATH)
    if not spec or not spec.loader:
        raise SystemExit(f"Missing plugin backend: {PLUGIN_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["decky"] = FakeDecky()
    spec.loader.exec_module(mod)
    return mod.Plugin()


def main() -> int:
    plugin = load_plugin()
    import asyncio

    async def run():
        status = await plugin.get_status()
        print("STATUS:", json.dumps(status, indent=2))
        if not status.get("installed"):
            return 1
        preview = await plugin.run_import(True, False, False, False)
        print("DRY_RUN ok:", preview["ok"], "lines:", len(preview["output"].splitlines()))
        bridge = await plugin.set_bridge_enabled(True)
        print("BRIDGE:", bridge)
        return 0

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
