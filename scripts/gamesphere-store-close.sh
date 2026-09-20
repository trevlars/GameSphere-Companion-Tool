#!/usr/bin/env bash
# Sunshine/Apollo prep-cmd undo → close Epic / Xbox / other non-Steam imports.
set -u
SRC="${BASH_SOURCE[0]}"
while [ -L "$SRC" ]; do
  DIR="$(cd "$(dirname "$SRC")" && pwd)"
  SRC="$(readlink "$SRC")"
  [[ $SRC != /* ]] && SRC="$DIR/$SRC"
done
DIR="$(cd "$(dirname "$SRC")" && pwd)"
PY="$DIR/gamesphere-store-close.py"
if [[ ! -f "$PY" ]]; then
  PY="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}/scripts/gamesphere-store-close.py"
fi
if [[ ! -f "$PY" ]]; then
  echo "gamesphere-store-close: missing gamesphere-store-close.py" >&2
  exit 1
fi
if [[ ! -x /usr/bin/python3 ]] && ! command -v python3 >/dev/null 2>&1; then
  echo "gamesphere-store-close: python3 is required" >&2
  exit 1
fi
PYTHON3="$(command -v python3 2>/dev/null || echo /usr/bin/python3)"
exec "$PYTHON3" "$PY" "$@"
