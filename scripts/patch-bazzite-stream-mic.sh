#!/usr/bin/env bash
# One-shot patch for HTPC sunshine-stream-prep + profile-audio (GameSphere stream mic pin).
set -euo pipefail

PREP="${HOME}/.local/bin/sunshine-stream-prep.sh"
PROF="${HOME}/.local/bin/bazzite-profile-audio.sh"
TS="$(date +%s)"

[[ -f "$PREP" ]] || { echo "missing $PREP" >&2; exit 1; }
[[ -f "$PROF" ]] || { echo "missing $PROF" >&2; exit 1; }

cp -a "$PREP" "${PREP}.bak.gs-mic-${TS}"
cp -a "$PROF" "${PROF}.bak.gs-mic-${TS}"

python3 - "$PREP" "$PROF" <<'PY'
import sys
from pathlib import Path

prep_path = Path(sys.argv[1])
prof_path = Path(sys.argv[2])

text = prep_path.read_text(encoding="utf-8")
start_hook = """
    # GameSphere clients: Steam Voice + Pulse default → GameSphere Mic (after profile-audio).
    if [[ -x "$HOME/.local/bin/gamesphere-stream-mic.sh" ]]; then
      "$HOME/.local/bin/gamesphere-stream-mic.sh" start >/dev/null 2>&1 || true
    fi
"""
stop_hook = """
    if [[ -x "$HOME/.local/bin/gamesphere-stream-mic.sh" ]]; then
      "$HOME/.local/bin/gamesphere-stream-mic.sh" stop >/dev/null 2>&1 || true
    fi
"""
if "gamesphere-stream-mic.sh" not in text:
    needle = "    start_sink_watch\n"
    if needle not in text:
        raise SystemExit("start_sink_watch needle missing in sunshine-stream-prep.sh")
    text = text.replace(needle, start_hook + needle, 1)
    stop_needle = "    stop_sink_watch\n"
    if stop_needle not in text:
        raise SystemExit("stop_sink_watch needle missing in sunshine-stream-prep.sh")
    text = text.replace(stop_needle, stop_needle + stop_hook, 1)
    prep_path.write_text(text, encoding="utf-8")
    print("patched sunshine-stream-prep.sh")
else:
    print("sunshine-stream-prep.sh already has stream-mic hook")

p = prof_path.read_text(encoding="utf-8")
if "pin_gamesphere_stream_mic" not in p:
    pin_fn = r'''
pin_gamesphere_stream_mic() {
  # While a GameSphere (non–Steam Link) stream is active, keep Pulse default on
  # gamesphere_mic so Steam/Discord hear the phone uplink. Jarvis may still use DualSense.
  local runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  local flag="$runtime/gamesphere-stream-mic.active"
  local remote="$runtime/bazzite-sunshine-remote-xbox-p1"
  local stream="$runtime/bazzite-sunshine-stream-active"
  local want=0
  [[ -f "$flag" ]] && want=1
  if [[ -f "$stream" && -f "$remote" ]]; then
    [[ "$(tr -d '[:space:]' <"$remote")" == "never" ]] && want=1
  fi
  [[ "$want" -eq 1 ]] || return 0
  ensure_gamesphere_mic
  if pactl list short sources 2>/dev/null | awk '{print $2}' | grep -qx gamesphere_mic; then
    pactl set-default-source gamesphere_mic 2>/dev/null || true
    echo "profile-audio: GameSphere stream mic pin → gamesphere_mic"
  fi
}

'''
    # Insert function before the switchfin_movie_active guard
    marker = "if switchfin_movie_active; then\n"
    if marker not in p:
        raise SystemExit("switchfin_movie_active marker missing in profile-audio")
    p = p.replace(marker, pin_fn + marker, 1)
    # Call pin after apply_gemma/apply_trevor
    tail = 'case "$AID" in\n  "$GEMMA_ID") apply_gemma || apply_trevor ;;\n  *) apply_trevor ;;\nesac\n'
    if tail not in p:
        raise SystemExit("profile-audio apply case marker missing")
    p = p.replace(tail, tail + "pin_gamesphere_stream_mic\n", 1)
    prof_path.write_text(p, encoding="utf-8")
    print("patched bazzite-profile-audio.sh")
else:
    print("bazzite-profile-audio.sh already has stream mic pin")
PY

chmod +x "$PREP" "$PROF"
echo "done"
