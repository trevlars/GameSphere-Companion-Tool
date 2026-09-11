#!/usr/bin/env bash
# Install GameSphere Import Tool on Linux (Bazzite, Steam Deck, generic).
set -euo pipefail

INSTALL_DIR="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}"
BIN_LINK="${GAMESPHERE_IMPORT_BIN:-$HOME/.local/bin/gamesphere-import}"
# Pin to a release tag when auto-updating (e.g. GAMESPHERE_IMPORT_REF=v1.0.2).
REF="${GAMESPHERE_IMPORT_REF:-}"

echo "==> GameSphere Import Tool — Linux setup"
echo "    Install dir: $INSTALL_DIR"
if [[ -n "$REF" ]]; then
  echo "    Ref: $REF"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "==> Updating existing checkout..."
  git -C "$INSTALL_DIR" fetch --tags origin
  if [[ -n "$REF" ]]; then
    git -C "$INSTALL_DIR" checkout --force "$REF"
  else
    git -C "$INSTALL_DIR" pull --ff-only || echo "==> git pull skipped (detached HEAD or offline checkout — using tree as-is)"
  fi
else
  echo "==> Cloning repository..."
  if [[ -n "$REF" ]]; then
    git clone --branch "$REF" https://github.com/trevlars/Gamesphere-Import-Tool.git "$INSTALL_DIR"
  else
    git clone https://github.com/trevlars/Gamesphere-Import-Tool.git "$INSTALL_DIR"
  fi
fi

cd "$INSTALL_DIR"
uv sync

echo "==> Writing .env from auto-detected paths..."
uv run main.py --auto-config

mkdir -p "$(dirname "$BIN_LINK")"
cat >"$BIN_LINK" <<EOF
#!/usr/bin/env bash
cd "$INSTALL_DIR"
exec uv run main.py "\$@"
EOF
chmod +x "$BIN_LINK"

# Quit App helper: Sunshine does not kill detached Steam games; prep-cmd undo calls this.
CLOSE_DIR="$(dirname "${GAMESPHERE_STEAM_CLOSE_BIN:-$HOME/.local/bin/gamesphere-steam-close.sh}")"
mkdir -p "$CLOSE_DIR"
install -m 755 "$INSTALL_DIR/scripts/gamesphere-steam-close.py" "$CLOSE_DIR/gamesphere-steam-close.py"
CLOSE_LINK="${GAMESPHERE_STEAM_CLOSE_BIN:-$HOME/.local/bin/gamesphere-steam-close.sh}"
install -m 755 "$INSTALL_DIR/scripts/gamesphere-steam-close.sh" "$CLOSE_LINK"
echo "==> Installed $CLOSE_LINK (Sunshine Quit App → close Steam game, including late-spawn titles)"

HOST_PREP_LINK="${GAMESPHERE_HOST_PREP_BIN:-$HOME/.local/bin/gamesphere-host-prep.sh}"
install -m 755 "$INSTALL_DIR/scripts/gamesphere-host-prep.sh" "$HOST_PREP_LINK"
echo "==> Installed $HOST_PREP_LINK (StreamTweak-style host tuning prep hooks)"

echo "==> Initializing host tuning config..."
uv run python3 host_tuning_cli.py init --enable-all || true

if [[ "${GAMESPHERE_ENABLE_HOST_BRIDGE:-}" == "1" ]]; then
  UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  mkdir -p "$UNIT_DIR"
  install -m 644 "$INSTALL_DIR/scripts/systemd/gamesphere-host-bridge.service" "$UNIT_DIR/gamesphere-host-bridge.service"
  systemctl --user daemon-reload 2>/dev/null || true
  systemctl --user enable --now gamesphere-host-bridge.service 2>/dev/null || true
  echo "==> Enabled gamesphere-host-bridge.service (TCP 47998 — set GAMESPHERE_ENABLE_HOST_BRIDGE=1)"
fi

VER=""
if [[ -f "$INSTALL_DIR/gs_version.py" ]]; then
  VER="$(python3 -c "import sys; sys.path.insert(0, '$INSTALL_DIR'); from gs_version import __version__; print(__version__)" 2>/dev/null || true)"
fi
echo ""
echo "Done.${VER:+ Installed version $VER.}"
echo "Run:"
echo "  gamesphere-import --dry-run    # preview"
echo "  gamesphere-import              # import Steam library into Sunshine"
echo "  gamesphere-import --check-update"
echo ""
echo "Optional DeckyLoader plugin: see decky/README.md"

DECKY_PLUGINS="${DECKY_PLUGINS_DIR:-$HOME/homebrew/plugins}"
if [[ -d "$DECKY_PLUGINS" ]] && [[ -f "$INSTALL_DIR/decky/dist/index.js" ]]; then
  if [[ -w "$DECKY_PLUGINS" ]]; then
    ln -sfn "$INSTALL_DIR/decky" "$DECKY_PLUGINS/gamesphere-import"
    echo "==> Decky plugin linked → $DECKY_PLUGINS/gamesphere-import (reload Decky in Game Mode)"
  elif command -v sudo >/dev/null 2>&1; then
    sudo ln -sfn "$INSTALL_DIR/decky" "$DECKY_PLUGINS/gamesphere-import" && \
      echo "==> Decky plugin linked (sudo) → $DECKY_PLUGINS/gamesphere-import"
  fi
fi
