#!/usr/bin/env bash
# GameSphere Companion host daemon (JOINPIN, couch coop, WAN, voice, WANNAPLAY).
# Long-running. Never restarts Sunshine/Apollo. Invoked by systemd user unit.
set -euo pipefail

INSTALL_DIR="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}"
FLATPAK_ID="io.github.trevlars.GamesphereImportTool"
APPIMAGE="${GAMESPHERE_APPIMAGE:-$HOME/.local/bin/GameSphere-Import-Tool-x86_64.AppImage}"
if [[ ! -x "$APPIMAGE" && -x "$HOME/.local/bin/GameSphere-Import-Tool.AppImage" ]]; then
  APPIMAGE="$HOME/.local/bin/GameSphere-Import-Tool.AppImage"
fi
export PATH="${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

run_py() {
  local py="$1"
  shift
  cd "$INSTALL_DIR"
  exec "$py" -u "$INSTALL_DIR/main.py" --host-bridge "$@"
}

if [[ -x "$INSTALL_DIR/.venv/bin/python3" && -f "$INSTALL_DIR/main.py" ]]; then
  run_py "$INSTALL_DIR/.venv/bin/python3"
fi

if command -v uv >/dev/null 2>&1 && [[ -f "$INSTALL_DIR/main.py" ]]; then
  cd "$INSTALL_DIR"
  exec uv run python3 -u main.py --host-bridge
fi

if [[ -x "${HOME}/.local/bin/gamesphere-import" ]]; then
  exec "${HOME}/.local/bin/gamesphere-import" --host-bridge
fi

if command -v flatpak >/dev/null 2>&1 && flatpak info --user "$FLATPAK_ID" >/dev/null 2>&1; then
  exec flatpak run "$FLATPAK_ID" --host-bridge
fi

if [[ -x "$APPIMAGE" ]]; then
  exec "$APPIMAGE" --host-bridge
fi

echo "gamesphere-host-bridge: no Companion install found (looked in $INSTALL_DIR)" >&2
exit 1
