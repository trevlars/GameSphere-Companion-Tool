#!/usr/bin/env bash
# Companion stream controller prep — Sunshine gamepad mode + Steam clone hide + emulator bind.
set -euo pipefail

INSTALL_DIR="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}"
ACTION="${1:-start}"
FORCE="${2:-auto}"

run_py() {
  if [[ ! -d "$INSTALL_DIR" ]]; then
    echo "gamesphere-stream-controller-prep: missing $INSTALL_DIR" >&2
    return 1
  fi
  cd "$INSTALL_DIR"
  uv run python3 - "$ACTION" "$FORCE" <<'PY'
import json
import sys
from host_tuning.controller_policy import (
    apply_emulator_bindings_with_wait,
    clear_stream_markers,
    get_policy_json,
    prep_stream,
    resolve_context,
    deferred_emulator_sync,
)
from host_tuning.config import load_config

action = sys.argv[1] if len(sys.argv) > 1 else "start"
force = sys.argv[2] if len(sys.argv) > 2 else "auto"
cfg = load_config()

if action == "start":
    result = prep_stream(cfg, force=force)
    if result.get("ok") and result.get("actions", {}).get("context"):
        deferred_emulator_sync(result["actions"]["context"])
    print(json.dumps(result))
elif action == "bind":
    context = force if force not in {"", "auto", "sync"} else resolve_context(cfg, force="auto")
    print(json.dumps(apply_emulator_bindings_with_wait(context, cfg)))
elif action == "stop":
    clear_stream_markers()
    print(json.dumps({"ok": True, "cleared": True}))
elif action == "status":
    print(json.dumps(get_policy_json(cfg)))
else:
    print(json.dumps({"ok": False, "error": "usage: start|bind|stop|status"}))
    sys.exit(2)
PY
}

case "$ACTION" in
  start|bind|stop|status) run_py ;;
  *)
    echo "usage: $0 start|bind|stop|status [auto|ds5|x360|gamesphere-ds5|steamlink-x360]" >&2
    exit 2
    ;;
esac
