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
LIB_TMP="$(mktemp)"
cleanup() { rm -f "$LIB_TMP"; }
trap cleanup EXIT

echo "==> GameSphere Import Tool (${TAG:-latest}) — Flatpak install"
curl -fsSL "${BASE}/io.github.trevlars.GamesphereImportTool.flatpak" -o "${BUNDLE}"
flatpak install --user -y "${BUNDLE}"
rm -f "${BUNDLE}"

echo "==> Detecting Steam / Sunshine paths..."
flatpak run io.github.trevlars.GamesphereImportTool --auto-config || true

UPDATE_BIN="${GAMESPHERE_UPDATE_BIN:-$HOME/.local/bin/gamesphere-import-update.sh}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$(dirname "$UPDATE_BIN")" "$UNIT_DIR"
if curl -fsSL "${BASE}/gamesphere-import-update.sh" -o "$UPDATE_BIN" 2>/dev/null \
  || curl -fsSL "${RAW}/scripts/gamesphere-import-update.sh" -o "$UPDATE_BIN"; then
  chmod +x "$UPDATE_BIN"
fi

# Shared linger/timer helpers — release asset, then git raw, then embedded fallback.
if curl -fsSL "${BASE}/linux-autoupdate-lib.sh" -o "$LIB_TMP" 2>/dev/null \
  || curl -fsSL "${RAW}/scripts/linux-autoupdate-lib.sh" -o "$LIB_TMP"; then
  # shellcheck disable=SC1090
  source "$LIB_TMP"
else
  gs_write_update_units() {
    local unit_dir="${1:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"
    mkdir -p "$unit_dir"
    cat >"$unit_dir/gamesphere-import-update.service" <<'EOF'
[Unit]
Description=GameSphere Import Tool auto-update from GitHub Releases
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Nice=10
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=%h/.local/bin/gamesphere-import-update.sh

[Install]
WantedBy=default.target
EOF
    cat >"$unit_dir/gamesphere-import-update.timer" <<'EOF'
[Unit]
Description=Daily GameSphere Import Tool update check

[Timer]
OnBootSec=5min
OnUnitActiveSec=24h
Persistent=true
RandomizedDelaySec=10min

[Install]
WantedBy=timers.target
EOF
    chmod 644 "$unit_dir/gamesphere-import-update.service" \
      "$unit_dir/gamesphere-import-update.timer"
  }
  gs_prepare_user_systemd() {
    local uid user runtime linger
    uid="$(id -u)"
    user="$(id -un)"
    runtime="${XDG_RUNTIME_DIR:-/run/user/${uid}}"
    export XDG_RUNTIME_DIR="$runtime"
    if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
      export DBUS_SESSION_BUS_ADDRESS="unix:path=${runtime}/bus"
    fi
    if command -v loginctl >/dev/null 2>&1; then
      linger="$(loginctl show-user "$user" -p Linger --value 2>/dev/null || true)"
      if [[ "$linger" != "yes" ]]; then
        loginctl enable-linger "$user" 2>/dev/null && \
          echo "==> Enabled linger for $user (auto-update runs in Game Mode / after reboot)" || \
          echo "==> Could not enable linger — timer will run while this user is logged in"
      fi
    fi
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
      if [[ -S "${runtime}/bus" ]] || systemctl --user show-environment >/dev/null 2>&1; then
        return 0
      fi
      sleep 0.4
    done
  }
  gs_enable_update_timer() {
    local unit_dir="${1:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"
    if [[ "${GAMESPHERE_AUTO_UPDATE:-1}" =~ ^(0|false|no|off)$ ]]; then
      echo "==> Auto-update timer skipped (GAMESPHERE_AUTO_UPDATE=0)"
      return 0
    fi
    if ! command -v systemctl >/dev/null 2>&1; then
      echo "==> No systemctl — auto-update timer not installed (use --apply-update)"
      return 0
    fi
    gs_prepare_user_systemd
    if [[ "${GAMESPHERE_SKIP_UPDATE_TIMER:-}" == "1" ]]; then
      echo "==> Update timer units installed (enable skipped during self-update)"
      return 0
    fi
    systemctl --user daemon-reload || true
    if systemctl --user enable --now gamesphere-import-update.timer; then
      echo "==> Enabled gamesphere-import-update.timer (GitHub Releases; opt out: GAMESPHERE_AUTO_UPDATE=0)"
      return 0
    fi
    echo "==> Could not enable gamesphere-import-update.timer from this session."
    echo "    After a desktop login, run:"
    echo "      systemctl --user enable --now gamesphere-import-update.timer"
  }
fi

if curl -fsSL "${BASE}/gamesphere-import-update.service" \
     -o "$UNIT_DIR/gamesphere-import-update.service" 2>/dev/null \
  && curl -fsSL "${BASE}/gamesphere-import-update.timer" \
     -o "$UNIT_DIR/gamesphere-import-update.timer" 2>/dev/null; then
  chmod 644 "$UNIT_DIR/gamesphere-import-update.service" \
    "$UNIT_DIR/gamesphere-import-update.timer"
elif curl -fsSL "${RAW}/scripts/systemd/gamesphere-import-update.service" \
       -o "$UNIT_DIR/gamesphere-import-update.service" 2>/dev/null \
  && curl -fsSL "${RAW}/scripts/systemd/gamesphere-import-update.timer" \
     -o "$UNIT_DIR/gamesphere-import-update.timer" 2>/dev/null; then
  chmod 644 "$UNIT_DIR/gamesphere-import-update.service" \
    "$UNIT_DIR/gamesphere-import-update.timer"
else
  gs_write_update_units "$UNIT_DIR"
fi

gs_enable_update_timer "$UNIT_DIR"

if command -v gs_enable_host_bridge >/dev/null 2>&1; then
  gs_enable_host_bridge "$UNIT_DIR"
else
  WRAPPER="${GAMESPHERE_HOST_BRIDGE_BIN:-$HOME/.local/bin/gamesphere-host-bridge}"
  mkdir -p "$(dirname "$WRAPPER")" "$UNIT_DIR"
  if curl -fsSL "${BASE}/gamesphere-host-bridge.sh" -o "$WRAPPER" 2>/dev/null \
    || curl -fsSL "${RAW}/scripts/gamesphere-host-bridge.sh" -o "$WRAPPER"; then
    chmod +x "$WRAPPER"
  fi
  if curl -fsSL "${BASE}/gamesphere-host-bridge.service" \
       -o "$UNIT_DIR/gamesphere-host-bridge.service" 2>/dev/null \
    || curl -fsSL "${RAW}/scripts/systemd/gamesphere-host-bridge.service" \
       -o "$UNIT_DIR/gamesphere-host-bridge.service" 2>/dev/null; then
    chmod 644 "$UNIT_DIR/gamesphere-host-bridge.service"
  fi
  if [[ "${GAMESPHERE_ENABLE_HOST_BRIDGE:-1}" =~ ^(0|false|no|off)$ ]]; then
    echo "==> Host daemon skipped (GAMESPHERE_ENABLE_HOST_BRIDGE=0)"
  elif command -v systemctl >/dev/null 2>&1 && [[ -f "$UNIT_DIR/gamesphere-host-bridge.service" ]]; then
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now gamesphere-host-bridge.service 2>/dev/null || true
    echo "==> Enabled gamesphere-host-bridge.service"
  fi
fi

echo ""
echo "Installed. Preview: flatpak run io.github.trevlars.GamesphereImportTool --dry-run"
echo "Import:       flatpak run io.github.trevlars.GamesphereImportTool"
echo "Updates:      gamesphere-import-update.timer (opt out: GAMESPHERE_AUTO_UPDATE=0)"
echo "Host daemon:  gamesphere-host-bridge.service (opt out: GAMESPHERE_ENABLE_HOST_BRIDGE=0)"
echo "Couch co-op:  udev + gamesphere-hide-steam-clones.sh (Steam 28de:11ff clones)"
