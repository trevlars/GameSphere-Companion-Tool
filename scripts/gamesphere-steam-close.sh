#!/usr/bin/env bash
# Sunshine/Apollo prep-cmd undo → close the Steam game (including late-spawn titles).
# AppID is passed through as a string; do not use bash $(( )) on 64-bit rungameids.
set -u
SRC="${BASH_SOURCE[0]}"
while [ -L "$SRC" ]; do
  DIR="$(cd "$(dirname "$SRC")" && pwd)"
  SRC="$(readlink "$SRC")"
  [[ $SRC != /* ]] && SRC="$DIR/$SRC"
done
DIR="$(cd "$(dirname "$SRC")" && pwd)"
PY="$DIR/gamesphere-steam-close.py"
if [[ ! -f "$PY" ]]; then
  PY="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}/scripts/gamesphere-steam-close.py"
fi
if [[ ! -f "$PY" ]]; then
  echo "gamesphere-steam-close: missing gamesphere-steam-close.py" >&2
  exit 1
fi
if [[ ! -x /usr/bin/python3 ]] && ! command -v python3 >/dev/null 2>&1; then
  echo "gamesphere-steam-close: python3 is required" >&2
  exit 1
fi
PYTHON3="$(command -v python3 2>/dev/null || echo /usr/bin/python3)"
exec "$PYTHON3" "$PY" "$@"
