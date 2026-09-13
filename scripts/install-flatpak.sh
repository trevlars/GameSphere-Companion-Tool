#!/usr/bin/env bash
# Install GameSphere Import Tool from the GitHub Release Flatpak bundle.
set -euo pipefail

TAG="${GAMESPHERE_IMPORT_REF:-}"
if [[ -n "$TAG" ]]; then
  BASE="https://github.com/trevlars/Gamesphere-Import-Tool/releases/download/${TAG}"
  RAW="https://raw.githubusercontent.com/trevlars/Gamesphere-Import-Tool/${TAG}"
else
  BASE="https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest/download"
  RAW="https://raw.githubusercontent.com/trevlars/Gamesphere-Import-Tool/main"
fi
BUNDLE="${TMPDIR:-/tmp}/io.github.trevlars.GamesphereImportTool.flatpak"

echo "==> GameSphere Import Tool (${TAG:-latest}) — Flatpak install"
curl -fsSL "${BASE}/io.github.trevlars.GamesphereImportTool.flatpak" -o "${BUNDLE}"
flatpak install --user -y "${BUNDLE}"
rm -f "${BUNDLE}"

UPDATE_BIN="${GAMESPHERE_UPDATE_BIN:-$HOME/.local/bin/gamesphere-import-update.sh}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$(dirname "$UPDATE_BIN")"
if curl -fsSL "${BASE}/gamesphere-import-update.sh" -o "$UPDATE_BIN" 2>/dev/null \
  || curl -fsSL "${RAW}/scripts/gamesphere-import-update.sh" -o "$UPDATE_BIN"; then
  chmod +x "$UPDATE_BIN"
fi

if [[ "${GAMESPHERE_SKIP_UPDATE_TIMER:-}" != "1" ]] \
  && [[ ! "${GAMESPHERE_AUTO_UPDATE:-1}" =~ ^(0|false|no|off)$ ]] \
  && command -v systemctl >/dev/null 2>&1; then
  mkdir -p "$UNIT_DIR"
  curl -fsSL "${RAW}/scripts/systemd/gamesphere-import-update.service" \
    -o "$UNIT_DIR/gamesphere-import-update.service" 2>/dev/null || true
  curl -fsSL "${RAW}/scripts/systemd/gamesphere-import-update.timer" \
    -o "$UNIT_DIR/gamesphere-import-update.timer" 2>/dev/null || true
  if [[ -f "$UNIT_DIR/gamesphere-import-update.timer" ]]; then
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now gamesphere-import-update.timer 2>/dev/null || true
    echo "==> Enabled gamesphere-import-update.timer (GitHub Releases; opt out: GAMESPHERE_AUTO_UPDATE=0)"
  fi
fi

echo ""
echo "Installed. Preview: flatpak run io.github.trevlars.GamesphereImportTool --dry-run"
echo "Import:       flatpak run io.github.trevlars.GamesphereImportTool"
