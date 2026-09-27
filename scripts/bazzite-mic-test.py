#!/usr/bin/env python3
"""Game Mode mic tester: level meter + hear-yourself via record→playback.

Live mic→speaker echo howls (GameSphere Mic / Moonlight / room AVR). Instead:
listen with a meter, record a few seconds, then play that clip back so you can
judge your voice without a feedback loop.

Controls:
  Speak during the countdown — clip plays automatically after.
  A / Y / Space  — record another clip
  B / Esc       — quit
"""

from __future__ import annotations

import glob
import os
import struct
import subprocess
import sys
import tempfile
import wave

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QLinearGradient
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

RECORD_SECS = float(os.environ.get("MIC_TEST_SECS", "4"))
PLAY_GAP_SECS = 0.8


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def default_source() -> str:
    return _run(["pactl", "get-default-source"])


def default_sink() -> str:
    return _run(["pactl", "get-default-sink"])


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
            f"Speak for {RECORD_SECS:.0f}s — then you'll hear the playback.\n"
            "A / Y = test again · B / Esc = quit"
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
        self._meter = None
        self._rec_proc: subprocess.Popen | None = None
        self._play_proc: subprocess.Popen | None = None
        self._wav_path = os.path.join(tempfile.gettempdir(), "bazzite-mic-test-ui.wav")
        self._phase = "idle"  # idle | record | play
        self._busy = False
        self._source = default_source()
        self._sink = default_sink()
        self._countdown = 0.0

        self._bus_timer = QTimer(self)
        self._bus_timer.setInterval(30)
        self._bus_timer.timeout.connect(self._poll_bus)

        self._tick = QTimer(self)
        self._tick.setInterval(100)
        self._tick.timeout.connect(self._on_tick)

        self._pad_timer = QTimer(self)
        self._pad_timer.setInterval(50)
        self._pad_timer.timeout.connect(self._poll_gamepad)
        self._pad_timer.start()

        Gst.init(None)
        QTimer.singleShot(150, self._start_cycle)

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

    def _start_meter(self) -> None:
        self._stop_meter()
        desc = (
            "pulsesrc ! audioconvert ! audioresample ! "
            "level interval=50000000 post-messages=true ! fakesink sync=false"
        )
        try:
            self._meter = Gst.parse_launch(desc)
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Meter failed: {exc}", False)
            return
        if self._meter.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self._set_status("Could not open the microphone.", False)
            self._meter = None
            return
        self._bus_timer.start()

    def _stop_meter(self) -> None:
        self._bus_timer.stop()
        if self._meter:
            self._meter.set_state(Gst.State.NULL)
            self._meter = None

    def _poll_bus(self) -> None:
        if not self._meter:
            return
        bus = self._meter.get_bus()
        while True:
            msg = bus.pop_filtered(
                Gst.MessageType.ELEMENT | Gst.MessageType.ERROR | Gst.MessageType.EOS
            )
            if msg is None:
                break
            if msg.type == Gst.MessageType.ERROR:
                err, _dbg = msg.parse_error()
                self._set_status(f"Audio error: {err.message}", False)
                self._stop_meter()
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

    def _kill_proc(self, proc: subprocess.Popen | None) -> None:
        if not proc:
            return
        try:
            proc.terminate()
            proc.wait(timeout=1.5)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def _start_cycle(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._source = default_source() or "default"
        self._sink = default_sink() or "default"
        self._kill_proc(self._rec_proc)
        self._kill_proc(self._play_proc)
        self._rec_proc = None
        self._play_proc = None
        try:
            if os.path.isfile(self._wav_path):
                os.remove(self._wav_path)
        except OSError:
            pass

        # Unmute / wake devices
        _run(["pactl", "suspend-source", self._source, "0"])
        _run(["pactl", "set-source-mute", self._source, "0"])
        _run(["pactl", "suspend-sink", self._sink, "0"])
        _run(["pactl", "set-sink-mute", self._sink, "0"])

        self._start_meter()
        self._phase = "record"
        self._countdown = RECORD_SECS
        self._set_status(
            f"TALK NOW — recording {RECORD_SECS:.0f}s\nMic: {self._source}",
            True,
        )
        self.hint.setText(
            f"Speak clearly for {RECORD_SECS:.0f}s.\n"
            "You'll hear playback next (no live echo / no feedback)."
        )

        # parecord to wav
        cmd = [
            "parecord",
            f"--device={self._source}",
            "--file-format=wav",
            "--rate=48000",
            "--channels=1",
            "--latency-msec=200",
            self._wav_path,
        ]
        try:
            self._rec_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except OSError as exc:
            self._set_status(f"Record failed: {exc}", False)
            self._busy = False
            self._phase = "idle"
            return
        self._tick.start()

    def _on_tick(self) -> None:
        if self._phase == "record":
            self._countdown -= 0.1
            left = max(0.0, self._countdown)
            self._set_status(
                f"TALK NOW — {left:.1f}s left\nMic: {self._source}",
                True,
            )
            if self._countdown > 0:
                return
            self._tick.stop()
            self._finish_record()
        elif self._phase == "play":
            if self._play_proc and self._play_proc.poll() is None:
                return
            self._tick.stop()
            self._phase = "idle"
            self._busy = False
            peak = self._wav_peak()
            note = "Good level" if peak >= 3000 else ("Quiet — speak louder" if peak >= 500 else "Very quiet / silence")
            self._set_status(
                f"Done — {note} (peak {peak}).\nA / Y = test again · B = quit\nPlay: {self._sink}",
                peak >= 500,
            )
            self.hint.setText(
                "That was your mic, played back once.\nA / Y = record again · B / Esc = quit"
            )

    def _finish_record(self) -> None:
        self._kill_proc(self._rec_proc)
        self._rec_proc = None
        self._stop_meter()
        self.level_changed.emit(0.0)

        if not os.path.isfile(self._wav_path) or os.path.getsize(self._wav_path) < 1000:
            self._set_status("No audio captured — check the mic source.", False)
            self._busy = False
            self._phase = "idle"
            return

        self._phase = "play"
        self._set_status(f"Playing back on {self._sink}…", True)
        self.hint.setText("Listen — this is what the PC heard.")
        QTimer.singleShot(int(PLAY_GAP_SECS * 1000), self._start_playback)

    def _start_playback(self) -> None:
        if self._phase != "play":
            return
        cmd = ["paplay", f"--device={self._sink}", self._wav_path]
        try:
            self._play_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except OSError as exc:
            self._set_status(f"Playback failed: {exc}", False)
            self._busy = False
            self._phase = "idle"
            return
        self._tick.start()

    def _wav_peak(self) -> int:
        try:
            with wave.open(self._wav_path, "rb") as w:
                data = w.readframes(w.getnframes())
            samples = struct.unpack("<" + "h" * (len(data) // 2), data)
            return max((abs(s) for s in samples), default=0)
        except Exception:  # noqa: BLE001
            return 0

    def _poll_gamepad(self) -> None:
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
                    if number in (1, 6, 7, 8, 9, 10):
                        self.close()
                        return
                    if number in (0, 2, 3) and self._phase == "idle":
                        self._start_cycle()
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
        elif event.key() in (Qt.Key.Key_Y, Qt.Key.Key_A, Qt.Key.Key_Return, Qt.Key.Key_Space):
            if self._phase == "idle":
                self._start_cycle()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self._tick.stop()
        self._stop_meter()
        self._kill_proc(self._rec_proc)
        self._kill_proc(self._play_proc)
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Mic Test")
    win = MicTestWindow()
    win.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
