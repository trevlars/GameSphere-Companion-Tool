#!/usr/bin/bash
# Periodic Sunshine wedge detector for Bazzite Game Mode hosts.
# HTTP 47989 ok + (HTTPS 47989 or RTSP 48010 bad) → restart Sunshine + clear stream-prep.
set -euo pipefail

MODE="${1:-watch}"
FORCE=0
case "$MODE" in
  --force|--client) FORCE=1; MODE=recover ;;
  --post-stream) MODE=post_stream ;;
  recover) FORCE=1 ;;
esac

BIN="${HOME}/.local/share/gamesphere-import-tool"
PY="${BIN}/.venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi

run_py() {
  "$PY" - "$@" <<'PY'
import json, sys
from host_tuning import sunshine_recover

mode = sys.argv[1] if len(sys.argv) > 1 else "watch"
force = sys.argv[2] == "1" if len(sys.argv) > 2 else False
if mode == "probe":
    print(json.dumps(sunshine_recover.probe()))
elif mode == "recover":
    print(json.dumps(sunshine_recover.recover(force=force)))
elif mode == "post_stream":
    print(json.dumps(sunshine_recover.recover_post_stream()))
else:
    p = sunshine_recover.probe()
    if p.get("wedged"):
        print(json.dumps(sunshine_recover.recover(force=False)))
    else:
        print(json.dumps({"ok": True, "recovered": False, "probe": p}))
PY
}

export PYTHONPATH="${BIN}${PYTHONPATH:+:$PYTHONPATH}"

case "$MODE" in
  probe)
    run_py probe
    ;;
  recover)
    run_py recover "$FORCE"
    ;;
  post_stream)
    run_py post_stream
    ;;
  watch|*)
    run_py watch 0
    ;;
esac
