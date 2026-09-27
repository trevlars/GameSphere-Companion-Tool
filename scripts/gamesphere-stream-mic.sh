#!/usr/bin/env bash
# On GameSphere (iPhone/iPad) Sunshine streams: force Steam + Pulse onto GameSphere Mic.
# Steam Link / DualSense playroom paths are left alone.
set -euo pipefail

INSTALL_DIR="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}"
ACTION="${1:-start}"

run_py() {
  if [[ ! -d "$INSTALL_DIR" ]]; then
    echo "gamesphere-stream-mic: missing $INSTALL_DIR" >&2
    return 1
  fi
  cd "$INSTALL_DIR"
  uv run python3 - "$ACTION" <<'PY'
import json
import sys
from host_tuning import steam_voice

action = sys.argv[1] if len(sys.argv) > 1 else "start"
if action == "start":
    print(json.dumps(steam_voice.apply_for_gamesphere_stream()))
elif action == "stop":
    print(json.dumps(steam_voice.restore_after_stream()))
elif action == "status":
    print(json.dumps({
        "pinned": steam_voice.stream_mic_pinned(),
        "gamesphereClient": steam_voice.is_gamesphere_stream_client(),
        "defaultSource": steam_voice._get_pulse_default_source(),
    }))
else:
    print(json.dumps({"ok": False, "error": "usage: start|stop|status"}))
    sys.exit(2)
PY
}

case "$ACTION" in
  start|stop|status) run_py ;;
  *)
    echo "usage: $0 start|stop|status" >&2
    exit 2
    ;;
esac
