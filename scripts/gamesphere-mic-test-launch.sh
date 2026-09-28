#!/usr/bin/env bash
# Launch the Game Mode Mic Test UI (level meter + record→playback).
# Called from the Decky plugin; also usable from Desktop / SSH with a display.
set -euo pipefail

LOG="${TMPDIR:-/tmp}/gamesphere-mic-test.log"
{
  echo "===== $(date -Iseconds) ====="
  echo "DISPLAY=${DISPLAY-} WAYLAND_DISPLAY=${WAYLAND_DISPLAY-}"
} >>"$LOG" 2>&1

# Clear Steam/Proton runtime vars so system Python + Qt + GStreamer work.
unset LD_LIBRARY_PATH LD_PRELOAD STEAM_OVERLAY_PIPE STEAM_RUNTIME \
  STEAM_RUNTIME_LIBRARY_PATH PRESSURE_VESSEL_FILESYSTEMS_RO \
  PRESSURE_VESSEL_FILESYSTEMS_RW || true

export PATH="/usr/bin:/bin:/usr/local/bin:${HOME}/.local/bin:${PATH:-}"
export PYTHONUNBUFFERED=1

if [[ -n "${DISPLAY:-}" ]]; then
  export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
elif [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
  export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland}"
fi

# Prefer HTPC mic-test install, then Companion-shipped script, then PATH.
CANDIDATES=(
  "${HOME}/.local/share/mic-test/mic-test.py"
  "${HOME}/.local/bin/bazzite-mic-test.py"
  "${HOME}/.local/share/gamesphere-import-tool/scripts/bazzite-mic-test.py"
  "${HOME}/.local/bin/mic-test"
)

for c in "${CANDIDATES[@]}"; do
  if [[ -x "$c" ]] || [[ -f "$c" && "$c" == *.py ]]; then
    if [[ "$c" == *.py ]]; then
      exec /usr/bin/python3 -u "$c" >>"$LOG" 2>&1
    else
      exec "$c" >>"$LOG" 2>&1
    fi
  fi
done

echo "Mic Test UI not found. Install Companion (scripts/bazzite-mic-test.py) or ~/.local/bin/mic-test." | tee -a "$LOG" >&2
exit 1
