#!/usr/bin/env bash
# Legacy wrapper — Mic to PC no longer uses VBAN on Linux.
# Forwards to gamesphere-pc-mic-setup.sh and removes any VBAN PipeWire drop-in.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
NEW="$HERE/gamesphere-pc-mic-setup.sh"
if [[ ! -x "$NEW" ]]; then
  chmod +x "$NEW" 2>/dev/null || true
fi
ACTION="${1:-install}"
case "$ACTION" in
  install|status|uninstall|info|help|-h|--help)
    exec bash "$NEW" "$ACTION"
    ;;
  *)
    exec bash "$NEW" install
    ;;
esac
