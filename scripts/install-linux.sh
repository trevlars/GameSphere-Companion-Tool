#!/usr/bin/env bash
# Install GameSphere Companion Tool on Linux (Bazzite, Steam Deck, generic).
set -euo pipefail

if [[ -z "${GAMESPHERE_INSTALL_FROM_FILE:-}" && ! -t 0 ]]; then
  tmp="$(mktemp "${TMPDIR:-/tmp}/gamesphere-install-linux.XXXXXX")"
  cat >"$tmp"
  chmod +x "$tmp"
  export GAMESPHERE_INSTALL_FROM_FILE=1
  exec bash "$tmp" "$@"
fi

INSTALL_DIR="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}"
BIN_LINK="${GAMESPHERE_IMPORT_BIN:-$HOME/.local/bin/gamesphere-import}"
# Pin to a release tag when auto-updating (e.g. GAMESPHERE_IMPORT_REF=v1.0.2).
REF="${GAMESPHERE_IMPORT_REF:-}"

echo "==> GameSphere Companion Tool — Linux setup"
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
    # Dirty HTPC trees (detached HEAD + leftover files) must not block release pins.
    if ! git -C "$INSTALL_DIR" reset --hard; then
      echo "==> Fixing install-dir ownership (Decky/root-owned files)..."
      sudo chown -R "$(id -un):$(id -gn)" "$INSTALL_DIR"
      git -C "$INSTALL_DIR" reset --hard
    fi
    git -C "$INSTALL_DIR" clean -fd
    git -C "$INSTALL_DIR" checkout --force "$REF"
  else
    git -C "$INSTALL_DIR" pull --ff-only || echo "==> git pull skipped (detached HEAD or offline checkout — using tree as-is)"
  fi
else
  echo "==> Cloning repository..."
  if [[ -n "$REF" ]]; then
    git clone --branch "$REF" https://github.com/trevlars/GameSphere-Companion-Tool.git "$INSTALL_DIR"
  else
    git clone https://github.com/trevlars/GameSphere-Companion-Tool.git "$INSTALL_DIR"
  fi
fi

cd "$INSTALL_DIR"
uv sync

echo "==> Writing .env from auto-detected paths..."
uv run main.py --auto-config

# PATH wrapper + environment.d so leftover Flatpak cannot steal `gamesphere-import`.
_gs_load_autoupdate_lib() {
  local lib="$INSTALL_DIR/scripts/linux-autoupdate-lib.sh"
  if [[ -f "$lib" ]]; then
    # shellcheck disable=SC1090
    source "$lib"
    return 0
  fi
  local tmp
  tmp="$(mktemp)"
  if curl -fsSL "https://raw.githubusercontent.com/trevlars/GameSphere-Companion-Tool/${REF:-main}/scripts/linux-autoupdate-lib.sh" -o "$tmp" \
    || curl -fsSL "https://raw.githubusercontent.com/trevlars/GameSphere-Companion-Tool/main/scripts/linux-autoupdate-lib.sh" -o "$tmp"; then
    # shellcheck disable=SC1090
    source "$tmp"
    return 0
  fi
  echo "==> linux-autoupdate-lib.sh missing — PATH wrapper will be written without linger helpers"
  return 1
}
if _gs_load_autoupdate_lib; then
  gs_write_git_path_wrapper "$BIN_LINK" "$INSTALL_DIR"
  gs_write_path_environment
else
  mkdir -p "$(dirname "$BIN_LINK")"
  cat >"$BIN_LINK" <<EOF
#!/usr/bin/env bash
export PATH="\$HOME/.local/bin:\${PATH}"
cd "$INSTALL_DIR"
exec uv run main.py "\$@"
EOF
  chmod +x "$BIN_LINK"
fi
echo "==> Installed PATH wrapper $BIN_LINK (git/Decky; wins over leftover Flatpak)"

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

PCMIC_LINK="${GAMESPHERE_PC_MIC_SETUP_BIN:-$HOME/.local/bin/gamesphere-pc-mic-setup.sh}"
install -m 755 "$INSTALL_DIR/scripts/gamesphere-pc-mic-setup.sh" "$PCMIC_LINK"
VBAN_LINK="${GAMESPHERE_VBAN_SETUP_BIN:-$HOME/.local/bin/gamesphere-vban-setup.sh}"
install -m 755 "$INSTALL_DIR/scripts/gamesphere-vban-setup.sh" "$VBAN_LINK"
echo "==> Installed $PCMIC_LINK (GameSphere Mic PipeWire source; no VBAN)"

echo "==> Initializing host tuning config..."
uv run python3 host_tuning_cli.py init || true

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UPDATE_BIN="${GAMESPHERE_UPDATE_BIN:-$HOME/.local/bin/gamesphere-import-update.sh}"
mkdir -p "$(dirname "$UPDATE_BIN")" "$UNIT_DIR"
if [[ -f "$INSTALL_DIR/scripts/gamesphere-import-update.sh" ]]; then
  install -m 755 "$INSTALL_DIR/scripts/gamesphere-import-update.sh" "$UPDATE_BIN"
fi
if [[ -f "$INSTALL_DIR/scripts/systemd/gamesphere-import-update.timer" ]]; then
  install -m 644 "$INSTALL_DIR/scripts/systemd/gamesphere-import-update.service" \
    "$UNIT_DIR/gamesphere-import-update.service"
  install -m 644 "$INSTALL_DIR/scripts/systemd/gamesphere-import-update.timer" \
    "$UNIT_DIR/gamesphere-import-update.timer"
elif command -v gs_write_update_units >/dev/null 2>&1; then
  gs_write_update_units "$UNIT_DIR"
fi
if command -v gs_enable_update_timer >/dev/null 2>&1; then
  gs_enable_update_timer "$UNIT_DIR"
elif command -v systemctl >/dev/null 2>&1 && [[ -f "$UNIT_DIR/gamesphere-import-update.timer" ]]; then
  systemctl --user daemon-reload 2>/dev/null || true
  systemctl --user enable --now gamesphere-import-update.timer 2>/dev/null || true
fi

if command -v gs_enable_host_bridge >/dev/null 2>&1; then
  gs_enable_host_bridge "$UNIT_DIR"
else
  WRAPPER="${GAMESPHERE_HOST_BRIDGE_BIN:-$HOME/.local/bin/gamesphere-host-bridge}"
  if [[ -f "$INSTALL_DIR/scripts/gamesphere-host-bridge.sh" ]]; then
    mkdir -p "$(dirname "$WRAPPER")"
    install -m 755 "$INSTALL_DIR/scripts/gamesphere-host-bridge.sh" "$WRAPPER"
  fi
  if [[ "${GAMESPHERE_ENABLE_HOST_BRIDGE:-1}" != "0" ]] \
    && [[ -f "$INSTALL_DIR/scripts/systemd/gamesphere-host-bridge.service" ]]; then
    mkdir -p "$UNIT_DIR"
    install -m 644 "$INSTALL_DIR/scripts/systemd/gamesphere-host-bridge.service" \
      "$UNIT_DIR/gamesphere-host-bridge.service"
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now gamesphere-host-bridge.service 2>/dev/null || true
    echo "==> Enabled gamesphere-host-bridge.service (Companion host daemon)"
  fi
fi

if command -v gs_install_linux_host_stack >/dev/null 2>&1; then
  gs_install_linux_host_stack "$INSTALL_DIR"
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
echo "  gamesphere-import --apply-update"
echo ""
echo "Auto-update: gamesphere-import-update.timer (opt out: GAMESPHERE_AUTO_UPDATE=0)"
echo "Host daemon: gamesphere-host-bridge.service (opt out: GAMESPHERE_ENABLE_HOST_BRIDGE=0)"
echo "  systemctl --user status gamesphere-host-bridge.service"
echo "Couch co-op: Steam 28de:11ff clones hidden via udev + gamesphere-hide-steam-clones.sh"
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
