#!/usr/bin/env bash
# Build Linux portable artifacts: PyInstaller CLI, AppImage, Flatpak bundle.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OUT="$ROOT/dist"
STAGE="$ROOT/build/flatpak-input"
APPDIR="$ROOT/build/AppDir"

mkdir -p "$OUT" "$STAGE" "$APPDIR"

echo "==> PyInstaller CLI (gamesphere-import)"
uv sync --extra build
uv run build_cli.py
test -x "$OUT/gamesphere-import"

echo "==> AppImage"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/metainfo"
cp "$OUT/gamesphere-import" "$APPDIR/usr/bin/"
cp flatpak/io.github.trevlars.GamesphereImportTool.desktop "$APPDIR/usr/share/applications/"
cp flatpak/io.github.trevlars.GamesphereImportTool.metainfo.xml "$APPDIR/usr/share/metainfo/"
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "${HERE}/usr/bin/gamesphere-import" "$@"
EOF
chmod +x "$APPDIR/AppRun" "$APPDIR/usr/bin/gamesphere-import"
ln -sf usr/share/applications/io.github.trevlars.GamesphereImportTool.desktop "$APPDIR/"

APPIMAGETOOL="$ROOT/build/appimagetool-x86_64.AppImage"
if [[ ! -x "$APPIMAGETOOL" ]]; then
  curl -fsSL -o "$APPIMAGETOOL" \
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x "$APPIMAGETOOL"
fi
VER="${GAMESPHERE_VERSION:-1.0.0}"
VER="${VER#v}"
TAG="${GAMESPHERE_IMPORT_REF:-v${VER}}"
ARCH=x86_64 VERSION="$VER" "$APPIMAGETOOL" "$APPDIR" "$OUT/GameSphere-Import-Tool-x86_64.AppImage"

echo "==> Flatpak bundle"
rm -rf "$STAGE" "$ROOT/build/flatpak-repo" "$ROOT/build/flatpak-build"
mkdir -p "$STAGE"
cp "$OUT/gamesphere-import" "$STAGE/"
cp flatpak/io.github.trevlars.GamesphereImportTool.desktop "$STAGE/"
cp flatpak/io.github.trevlars.GamesphereImportTool.metainfo.xml "$STAGE/"
cp flatpak/io.github.trevlars.GamesphereImportTool.yml "$STAGE/manifest.yml"

flatpak-builder --force-clean --user --install-deps-from=flathub \
  --repo="$ROOT/build/flatpak-repo" \
  "$ROOT/build/flatpak-build" \
  "$STAGE/manifest.yml"

flatpak build-bundle "$ROOT/build/flatpak-repo" \
  "$OUT/io.github.trevlars.GamesphereImportTool.flatpak" \
  io.github.trevlars.GamesphereImportTool

cat > "$OUT/GameSphere-Import-Tool.flatpakref" << EOF
[Flatpak Ref]
Title=GameSphere Import Tool
Name=io.github.trevlars.GamesphereImportTool
Branch=stable
IsRuntime=false
Url=https://github.com/trevlars/Gamesphere-Import-Tool/releases/download/${TAG}/io.github.trevlars.GamesphereImportTool.flatpak
RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo
EOF

echo "==> Built:"
ls -la "$OUT/gamesphere-import" "$OUT/GameSphere-Import-Tool-x86_64.AppImage" \
  "$OUT/io.github.trevlars.GamesphereImportTool.flatpak" "$OUT/GameSphere-Import-Tool.flatpakref"
