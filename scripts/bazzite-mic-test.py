#!/usr/bin/env python3
"""Game Mode mic tester: big level meter (no feedback by default).

Live delayed playback into room speakers caused howling — especially with
GameSphere Mic / Moonlight (phone → PC → TV → phone). Default is meter-only.

Optional hear-yourself echo:
  MIC_TEST_ECHO=1          enable delayed playback at start
  Press Y / A in the UI    toggle echo (blocked when unsafe)
Echo is refused while a Sunshine stream is active or the default source is
gamesphere_mic (those paths always feedback). Prefers headphones when present.
"""

from __future__ import annotations

import glob
import os
import struct
import subprocess
import sys

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QLinearGradient
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def default_source() -> str:
    return _run(["pactl", "get-default-source"])


def default_sink() -> str:
    return _run(["pactl", "get-default-sink"])


def list_sinks() -> list[str]:
    out = _run(["pactl", "list", "short", "sinks"])
    names: list[str] = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            names.append(parts[1])
    return names


def stream_active() -> bool:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.isfile(os.path.join(runtime, "bazzite-sunshine-stream-active"))


def echo_unsafe(source: str) -> str:
    """Return a reason string if live echo would feedback, else empty."""
    src = (source or "").lower()
    if "gamesphere" in src:
        return "GameSphere Mic — echo would loop through the phone/stream"
    if stream_active():
        return "Sunshine stream active — echo would howl through Moonlight"
    return ""


def pick_echo_sink() -> tuple[str, str]:
    """Prefer headphones over HDMI/AVR for echo. Returns (sink_name, note)."""
    sinks = list_sinks()
    for name in sinks:
        low = name.lower()
        if "dualsense" in low or "headset" in low or "headphone" in low:
            if "hdmi" not in low:
                return name, "headphones"
    sink = default_sink()
    return sink, "speakers (keep volume down)"


class LevelBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._level = 0.0
        self.setMinimumHeight(72)

    def set_level(self, value: float) -> None:
        self._level = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(2, 2, -2, -2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#172033"))
        p.drawRoundedRect(r, 16, 16)

        fill = r.adjusted(0, 0, -int(r.width() * (1.0 - self._level)), 0)
        if fill.width() > 0:
            grad = QLinearGradient(fill.topLeft(), fill.topRight())
            grad.setColorAt(0.0, QColor("#3dd68c"))
            grad.setColorAt(0.7, QColor("#f5a524"))
            grad.setColorAt(1.0, QColor("#f31260"))
            p.setBrush(grad)
            p.drawRoundedRect(fill, 16, 16)


class MicTestWindow(QWidget):
    level_changed = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Mic Test")
        self.setStyleSheet("background: #0f1419; color: #e8eef7;")

        title = QLabel("Mic Test")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 36, QFont.Weight.Bold))

        self.hint = QLabel(
            "Speak — watch the meter (no speaker echo, so no feedback).\n"
            "Y / A = try hear-yourself · B / Esc = quit"
        )
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setStyleSheet("color: #8b9bb4;")
        self.hint.setFont(QFont("Segoe UI", 18))
        self.hint.setWordWrap(True)

        self.pct = QLabel("0%")
        self.pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pct.setFont(QFont("Segoe UI", 28, QFont.Weight.DemiBold))

        self.bar = LevelBar()
        self.status = QLabel("Starting…")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("color: #8b9bb4;")
        self.status.setFont(QFont("Segoe UI", 16))
        self.status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(22)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(self.hint)
        layout.addSpacing(12)
        layout.addWidget(self.pct)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addStretch(2)

        self.level_changed.connect(self._on_level)
        self._pipeline = None
        self._echo = False
        self._source = default_source()
        want = os.environ.get("MIC_TEST_ECHO", "").strip().lower() in {"1", "yes", "true", "on"}
        unsafe = echo_unsafe(self._source)
        self._echo = bool(want and not unsafe)

        self._bus_timer = QTimer(self)
        self._bus_timer.setInterval(30)
        self._bus_timer.timeout.connect(self._poll_bus)

        self._pad_timer = QTimer(self)
        self._pad_timer.setInterval(50)
        self._pad_timer.timeout.connect(self._poll_gamepad)
        self._pad_timer.start()

        QTimer.singleShot(100, self._start)

    def _set_status(self, text: str, ok: bool | None = None) -> None:
        color = "#8b9bb4"
        if ok is True:
            color = "#3dd68c"
        elif ok is False:
            color = "#f31260"
        self.status.setStyleSheet(f"color: {color};")
        self.status.setText(text)

    def _on_level(self, value: float) -> None:
        self.bar.set_level(value)
        self.pct.setText(f"{int(value * 100)}%")

    def _pipeline_desc(self) -> str:
        # Pulse default source (gamesphere_mic / DualSense / voice-iso).
        src = 'pulsesrc device-name="" ! audioconvert ! audioresample'
        # autoaudiosrc also works; pulsesrc is more predictable on PipeWire.
        src = "pulsesrc ! audioconvert ! audioresample"
        meter = (
            f"{src} ! tee name=t "
            "t. ! queue ! level interval=50000000 post-messages=true ! fakesink sync=false"
        )
        if not self._echo:
            return meter
        sink_name, _note = pick_echo_sink()
        # ~1.2s delay + soft volume so room speakers are less likely to howl.
        sink_prop = f'device="{sink_name}"' if sink_name else ""
        return (
            f"{meter} "
            "t. ! queue max-size-time=1500000000 min-threshold-time=1200000000 "
            "leaky=downstream ! audioconvert ! volume volume=0.35 ! "
            f"pulsesink {sink_prop} sync=false"
        )

    def _start(self) -> None:
        self._source = default_source()
        Gst.init(None)
        self._rebuild_pipeline()

    def _rebuild_pipeline(self) -> None:
        self._stop_pipeline()
        self._source = default_source()
        unsafe = echo_unsafe(self._source)
        if self._echo and unsafe:
            self._echo = False
            self._set_status(f"Echo off — {unsafe}", False)

        desc = self._pipeline_desc()
        try:
            self._pipeline = Gst.parse_launch(desc)
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Failed to start audio: {exc}", False)
            return

        ret = self._pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            self._set_status("Could not open the microphone.", False)
            return

        self._bus_timer.start()
        src = self._source or "default"
        if self._echo:
            sink, note = pick_echo_sink()
            self._set_status(f"Listening + echo → {sink or 'default'} ({note})\nMic: {src}", True)
            self.hint.setText(
                "Echo on — use headphones if it howls.\nY / A = echo off · B / Esc = quit"
            )
        else:
            self._set_status(f"Meter only (no feedback) · Mic: {src}", True)
            self.hint.setText(
                "Speak — watch the meter (no speaker echo).\n"
                "Y / A = try hear-yourself · B / Esc = quit"
            )

    def _toggle_echo(self) -> None:
        self._source = default_source()
        if not self._echo:
            reason = echo_unsafe(self._source)
            if reason:
                self._set_status(f"Echo blocked — {reason}", False)
                return
        self._echo = not self._echo
        self._rebuild_pipeline()

    def _poll_bus(self) -> None:
        if not self._pipeline:
            return
        bus = self._pipeline.get_bus()
        while True:
            msg = bus.pop_filtered(
                Gst.MessageType.ELEMENT
                | Gst.MessageType.ERROR
                | Gst.MessageType.EOS
            )
            if msg is None:
                break
            if msg.type == Gst.MessageType.ERROR:
                err, _dbg = msg.parse_error()
                self._set_status(f"Audio error: {err.message}", False)
                self._stop_pipeline()
                return
            if msg.type == Gst.MessageType.ELEMENT:
                struct = msg.get_structure()
                if struct and struct.has_name("level"):
                    try:
                        rms = struct.get_value("rms")
                        peak = struct.get_value("peak")
                        db = max(float(x) for x in (peak or rms or [-60.0]))
                    except Exception:  # noqa: BLE001
                        db = -60.0
                    norm = (db + 50.0) / 50.0
                    self.level_changed.emit(max(0.0, min(1.0, norm)))

    def _stop_pipeline(self) -> None:
        self._bus_timer.stop()
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None

    def _poll_gamepad(self) -> None:
        # Xbox/Steam: B≈1 quit; A≈0 / Y≈3 toggle echo.
        for js in glob.glob("/dev/input/js*"):
            try:
                fd = os.open(js, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            try:
                while True:
                    data = os.read(fd, 8)
                    if len(data) < 8:
                        break
                    _time, value, typ, number = struct.unpack("IhBB", data)
                    if not (typ & 0x01) or value != 1:
                        continue
                    if number in (1, 6, 7, 8, 9, 10):  # B / Back / Start family
                        self.close()
                        return
                    if number in (0, 2, 3):  # A / X / Y
                        self._toggle_echo()
                        return
            except BlockingIOError:
                pass
            except OSError:
                pass
            finally:
                os.close(fd)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_B, Qt.Key.Key_Q):
            self.close()
        elif event.key() in (Qt.Key.Key_Y, Qt.Key.Key_A, Qt.Key.Key_E, Qt.Key.Key_Return):
            self._toggle_echo()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self._stop_pipeline()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Mic Test")
    win = MicTestWindow()
    win.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
