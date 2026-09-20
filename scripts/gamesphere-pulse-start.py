#!/usr/bin/env python3
"""Inject a short gamepad Start/Menu press on the host (stream-drop auto-pause)."""

from __future__ import annotations

import sys
import time

try:
    from evdev import UInput, ecodes
except ImportError:
    print("evdev not installed", file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    keys = [
        ecodes.BTN_START,
        ecodes.BTN_MODE,
        ecodes.BTN_SELECT,
        ecodes.KEY_ESC,
    ]
    ui = UInput(
        events={
            ecodes.EV_KEY: keys,
        },
        name="GameSphere Pause Pulse",
        vendor=0x054C,
        product=0x0CE6,
    )
    try:
        ui.write(ecodes.EV_KEY, ecodes.BTN_START, 1)
        ui.syn()
        time.sleep(0.08)
        ui.write(ecodes.EV_KEY, ecodes.BTN_START, 0)
        ui.syn()
    finally:
        ui.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
