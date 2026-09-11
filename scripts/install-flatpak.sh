#!/usr/bin/env bash
# Install GameSphere Import Tool from the GitHub Release Flatpak bundle.
set -euo pipefail

TAG="${GAMESPHERE_IMPORT_REF:-v1.2.5}"
BASE="https://github.com/trevlars/Gamesphere-Import-Tool/releases/download/${TAG}"
BUNDLE="${TMPDIR:-/tmp}/io.github.trevlars.GamesphereImportTool.flatpak"

echo "==> GameSphere Import Tool (${TAG}) — Flatpak install"
curl -fsSL "${BASE}/io.github.trevlars.GamesphereImportTool.flatpak" -o "${BUNDLE}"
flatpak install --user -y "${BUNDLE}"
rm -f "${BUNDLE}"

echo ""
echo "Installed. Preview: flatpak run io.github.trevlars.GamesphereImportTool --dry-run"
echo "Import:       flatpak run io.github.trevlars.GamesphereImportTool"
