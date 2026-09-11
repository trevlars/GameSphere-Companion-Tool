#!/usr/bin/env bash
# GameSphere host stream prep — StreamTweak-style session hooks for Linux/Bazzite.
# Installed to ~/.local/bin/gamesphere-host-prep.sh by install-linux.sh or --host-tuning-apply
set -euo pipefail

INSTALL_DIR="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}"
ACTION="${1:-}"

if [[ ! -d "$INSTALL_DIR" ]]; then
  echo "gamesphere-host-prep: install dir not found: $INSTALL_DIR" >&2
  exit 1
fi

cd "$INSTALL_DIR"
run_py() {
  uv run python3 - "$@" <<'PY'
import json
import sys
from host_tuning.service import prep_start, prep_stop, write_prep_scripts

action = sys.argv[1] if len(sys.argv) > 1 else ""
write_prep_scripts()
if action == "start":
    print(json.dumps(prep_start()))
elif action == "stop":
    print(json.dumps(prep_stop()))
else:
    print("usage: gamesphere-host-prep.sh start|stop", file=sys.stderr)
    sys.exit(2)
PY
}

case "$ACTION" in
  start|stop) run_py "$ACTION" ;;
  *)
    echo "usage: $0 start|stop" >&2
    exit 2
    ;;
esac
