"""Sunshine log session monitor + quality history (StreamTweak-inspired)."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from host_tuning.config import load_config, sessions_path
from host_tuning import launch_watcher
from host_tuning import stream_sockets

# StreamTweak 8.3.0: match session markers at line start (unprefixed server lines)
_SESSION_START = re.compile(
    r"^(?:New streaming session started|Started RTSP|session_history:\s*begin_session)",
    re.I,
)
_SESSION_END = re.compile(
    r"^(?:Streaming session ended|Session ended|session_history:\s*end_session)",
    re.I,
)
_SESSION_UUID_BEGIN = re.compile(r"session_history:\s*begin_session\s+uuid=([a-f0-9-]+)", re.I)
_SESSION_UUID_END = re.compile(r"session_history:\s*end_session\s+uuid=([a-f0-9-]+)", re.I)
_EXECUTING = re.compile(r'^Executing:\s*\["([^"]+)"\]', re.I)


@dataclass
class SessionEntry:
    id: str
    start_time: str
    end_time: Optional[str] = None
    games: List[str] = field(default_factory=list)
    client_name: str = ""
    end_reason: str = ""
    grade: str = ""
    avg_rtt_ms: float = 0.0
    drop_rate: float = 0.0
    host_session_uuid: str = ""


def detect_sunshine_log_path(configured: str = "") -> str:
    if configured and os.path.isfile(configured):
        return configured
    candidates = []
    if os.name == "nt":
        for base in (
            os.path.join(os.environ.get("ProgramFiles", ""), "Sunshine"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Apollo"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Sunshine"),
        ):
            candidates.extend([
                os.path.join(base, "sunshine.log"),
                os.path.join(base, "logs", "sunshine.log"),
            ])
    else:
        home = os.path.expanduser("~")
        for parts in (
            ("sunshine",),
            ("Apollo",),
            ("vibeshine",),
            ("vibepollo",),
        ):
            candidates.append(os.path.join(home, ".config", *parts, "sunshine.log"))
        candidates.extend([
            os.path.join(home, ".var", "app", "dev.lizardbyte.app.Sunshine", "config", "sunshine", "sunshine.log"),
            os.path.join(home, ".local", "share", "sunshine", "sunshine.log"),
        ])
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""


def load_sessions() -> List[Dict[str, Any]]:
    path = sessions_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else data.get("sessions", [])
    except (OSError, json.JSONDecodeError):
        return []


def save_sessions(sessions: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(sessions_path()), exist_ok=True)
    with open(sessions_path(), "w", encoding="utf-8") as fh:
        json.dump({"sessions": sessions[-200:]}, fh, indent=2)


def last_session_json() -> str:
    sessions = load_sessions()
    if not sessions:
        return "{}"
    return json.dumps(sessions[-1])


def append_client_telemetry(batch: Dict[str, Any]) -> None:
    sessions = load_sessions()
    if not sessions:
        return
    current = sessions[-1]
    samples = current.setdefault("client_samples", [])
    samples.append(batch)
    if len(samples) > 3600:
        current["client_samples"] = samples[-3600:]
    _compute_grade(current)
    save_sessions(sessions)


def _compute_grade(session: Dict[str, Any]) -> None:
    samples = session.get("client_samples") or []
    if not samples:
        return
    rtts = [s.get("rtt_ms") for s in samples if isinstance(s.get("rtt_ms"), (int, float))]
    drops = [s.get("drop_rate") for s in samples if isinstance(s.get("drop_rate"), (int, float))]
    target = [s.get("target_bitrate_kbps") for s in samples if isinstance(s.get("target_bitrate_kbps"), (int, float))]
    delivered = [s.get("bitrate_kbps") for s in samples if isinstance(s.get("bitrate_kbps"), (int, float))]
    if rtts:
        session["avg_rtt_ms"] = sum(rtts) / len(rtts)
    if drops:
        session["drop_rate"] = sum(drops) / len(drops)
    if target and delivered:
        session["bitrate_delivery_ratio"] = (sum(delivered) / len(delivered)) / max(1, sum(target) / len(target))
    avg_rtt = session.get("avg_rtt_ms", 999)
    drop = session.get("drop_rate", 1.0)
    if avg_rtt < 20 and drop < 0.01:
        session["grade"] = "Excellent"
    elif avg_rtt < 40 and drop < 0.05:
        session["grade"] = "Good"
    else:
        session["grade"] = "Poor"


class SessionLogMonitor:
    """Tail host log; end sessions via log lines or UDP socket idle (StreamTweak 8.3.0)."""

    SOCKET_IDLE_SECONDS = 90

    def __init__(
        self,
        log_path: str,
        on_start: Optional[Callable[[SessionEntry], None]] = None,
        on_stop: Optional[Callable[[SessionEntry], None]] = None,
    ):
        self.log_path = log_path
        self.on_start = on_start
        self.on_stop = on_stop
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._watch_thread: Optional[threading.Thread] = None
        self._active: Optional[SessionEntry] = None
        self._open_uuid: str = ""
        self._recent_lines: List[str] = []

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._watch_thread = threading.Thread(target=self._socket_watch, daemon=True)
        self._watch_thread.start()

    def stop(self) -> None:
        self._stop.set()
        for t in (self._thread, self._watch_thread):
            if t:
                t.join(timeout=2)

    @property
    def session_active(self) -> bool:
        if self._active and not self._active.end_time:
            return True
        return stream_sockets.stream_sockets_active()

    def _run(self) -> None:
        if not self.log_path or not os.path.isfile(self.log_path):
            logging.warning("Session monitor: log not found at %s", self.log_path)
            return
        with open(self.log_path, "r", encoding="utf-8", errors="ignore") as fh:
            fh.seek(0, os.SEEK_END)
            while not self._stop.is_set():
                line = fh.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                self._handle_line(line.rstrip())

    def _socket_watch(self) -> None:
        last_active = time.time()
        while not self._stop.is_set():
            if stream_sockets.stream_sockets_active():
                last_active = time.time()
            elif self._active and (time.time() - last_active) > self.SOCKET_IDLE_SECONDS:
                self._end_session("socket_idle")
            time.sleep(5)

    def _handle_line(self, line: str) -> None:
        self._recent_lines.append(line)
        if len(self._recent_lines) > 50:
            self._recent_lines.pop(0)
        launch_watcher.note_launch_from_log_line(line)

        # Ignore prefixed noise (Playnite bridge, restore lines, etc.)
        core = line.split("]", 1)[-1].strip() if line.startswith("[") else line.strip()

        m_end = _SESSION_UUID_END.search(core)
        if m_end and self._open_uuid and m_end.group(1) != self._open_uuid:
            return  # end of a different session (Vibeshine/Vibepollo)

        if _SESSION_END.search(core):
            self._end_session("log")
            return

        if _SESSION_START.search(core):
            if stream_sockets.stream_sockets_active() or not self._active:
                m_begin = _SESSION_UUID_BEGIN.search(core)
                self._begin_session(m_begin.group(1) if m_begin else "")
            return

        if self._active:
            m = _EXECUTING.search(core)
            if m:
                game = os.path.basename(m.group(1))
                if game and game not in self._active.games:
                    self._active.games.append(game)

    def _begin_session(self, host_uuid: str = "") -> None:
        if self._active and not self._active.end_time:
            return
        self._open_uuid = host_uuid
        entry = SessionEntry(
            id=uuid.uuid4().hex[:8],
            start_time=datetime.now(timezone.utc).isoformat(),
            host_session_uuid=host_uuid,
        )
        self._active = entry
        sessions = load_sessions()
        sessions.append(asdict(entry))
        save_sessions(sessions)
        if self.on_start:
            self.on_start(entry)
        logging.info("Session started (%s)", entry.id)

    def _end_session(self, reason: str) -> None:
        if not self._active:
            return
        cfg = load_config()
        if cfg.session_discard_empty and not self._active.games:
            sessions = load_sessions()
            if sessions and sessions[-1].get("id") == self._active.id:
                sessions.pop()
                save_sessions(sessions)
        else:
            sessions = load_sessions()
            if sessions and sessions[-1].get("id") == self._active.id:
                sessions[-1]["end_time"] = datetime.now(timezone.utc).isoformat()
                sessions[-1]["end_reason"] = reason
                sessions[-1]["games"] = list(self._active.games)
                save_sessions(sessions)
        if self.on_stop and self._active:
            self.on_stop(self._active)
        logging.info("Session ended (%s, %s)", self._active.id, reason)
        self._active = None
        self._open_uuid = ""
