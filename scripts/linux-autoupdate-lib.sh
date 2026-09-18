#!/usr/bin/env bash
# Shared Linux auto-update helpers for install-linux.sh / install-flatpak.sh.
# Enables gamesphere-import-update.timer for new users (Game Mode / SSH / reboot).
# Opt out: GAMESPHERE_AUTO_UPDATE=0
# shellcheck disable=SC2034

gs_update_service_body() {
  cat <<'EOF'
[Unit]
Description=GameSphere Companion Tool auto-update from GitHub Releases
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
}

gs_update_timer_body() {
  cat <<'EOF'
[Unit]
Description=Daily GameSphere Companion Tool update check

[Timer]
OnBootSec=5min
OnUnitActiveSec=24h
Persistent=true
RandomizedDelaySec=10min

[Install]
WantedBy=timers.target
EOF
}

gs_write_update_units() {
  local unit_dir="${1:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"
  mkdir -p "$unit_dir"
  gs_update_service_body >"$unit_dir/gamesphere-import-update.service"
  gs_update_timer_body >"$unit_dir/gamesphere-import-update.timer"
  chmod 644 "$unit_dir/gamesphere-import-update.service" \
    "$unit_dir/gamesphere-import-update.timer"
}

gs_write_git_path_wrapper() {
  local bin_link="${1:-$HOME/.local/bin/gamesphere-import}"
  local install_dir="${2:-$HOME/.local/share/gamesphere-import-tool}"
  mkdir -p "$(dirname "$bin_link")"
  cat >"$bin_link" <<EOF
#!/usr/bin/env bash
# GameSphere Companion Tool — git/Decky checkout.
# Lives in ~/.local/bin so leftover Flatpak exports cannot steal this command.
set -euo pipefail
export PATH="\$HOME/.local/bin:\${PATH}"
cd "$install_dir"
exec uv run main.py "\$@"
EOF
  chmod +x "$bin_link"
}

gs_write_path_environment() {
  local dest="${XDG_CONFIG_HOME:-$HOME/.config}/environment.d/50-gamesphere-import-path.conf"
  mkdir -p "$(dirname "$dest")"
  cat >"$dest" <<EOF
# Prefer git/Decky ~/.local/bin/gamesphere-import over leftover Flatpak exports.
PATH=$HOME/.local/bin:\$PATH
EOF
}

# User systemd + linger so the timer survives Game Mode, SSH, and reboot.
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
      if loginctl enable-linger "$user" 2>/dev/null; then
        echo "==> Enabled linger for $user (auto-update runs in Game Mode / after reboot)"
      else
        echo "==> Could not enable linger — timer will run while this user is logged in"
        echo "    Optional: loginctl enable-linger $user"
      fi
    fi
  fi
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if [[ -S "${runtime}/bus" ]] || systemctl --user show-environment >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.4
  done
  return 0
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
  if [[ ! -f "$unit_dir/gamesphere-import-update.timer" ]]; then
    echo "==> Missing $unit_dir/gamesphere-import-update.timer — skip"
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
  return 0
}

gs_host_bridge_unit_body() {
  cat <<'EOF'
[Unit]
Description=GameSphere Companion host daemon (TCP 47998)
Documentation=https://github.com/trevlars/Gamesphere-Import-Tool/blob/main/docs/HOST_INTEGRATION.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=-%h/.local/share/gamesphere-import-tool
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
ExecStart=%h/.local/bin/gamesphere-host-bridge
Restart=always
RestartSec=3
TimeoutStopSec=15
KillMode=process
SuccessExitStatus=0 SIGTERM SIGINT
StandardOutput=journal
StandardError=journal
SyslogIdentifier=gamesphere-host-bridge

[Install]
WantedBy=default.target
EOF
}

gs_write_host_bridge_wrapper() {
  local dest="${1:-$HOME/.local/bin/gamesphere-host-bridge}"
  local src="${2:-}"
  mkdir -p "$(dirname "$dest")"
  if [[ -n "$src" && -f "$src" ]]; then
    install -m 755 "$src" "$dest"
    return 0
  fi
  cat >"$dest" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
INSTALL_DIR="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}"
FLATPAK_ID="io.github.trevlars.GamesphereImportTool"
APPIMAGE="${GAMESPHERE_APPIMAGE:-$HOME/.local/bin/GameSphere-Import-Tool-x86_64.AppImage}"
if [[ ! -x "$APPIMAGE" && -x "$HOME/.local/bin/GameSphere-Import-Tool.AppImage" ]]; then
  APPIMAGE="$HOME/.local/bin/GameSphere-Import-Tool.AppImage"
fi
export PATH="${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
if [[ -x "$INSTALL_DIR/.venv/bin/python3" && -f "$INSTALL_DIR/main.py" ]]; then
  cd "$INSTALL_DIR"
  exec "$INSTALL_DIR/.venv/bin/python3" -u "$INSTALL_DIR/main.py" --host-bridge
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
echo "gamesphere-host-bridge: no Companion install found" >&2
exit 1
EOF
  chmod 755 "$dest"
}

gs_install_linux_host_stack() {
  local install_dir="${1:-${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}}"
  local hide_src="$install_dir/scripts/gamesphere-hide-steam-clones.sh"
  local fw_src="$install_dir/scripts/gamesphere-host-firewall.sh"
  local udev_src="$install_dir/scripts/udev/99-gamesphere-hide-steam-clones.rules"
  local bindir="$HOME/.local/bin"
  local raw="https://raw.githubusercontent.com/trevlars/Gamesphere-Import-Tool/main"
  mkdir -p "$bindir"
  if [[ ! -f "$hide_src" ]]; then
    hide_src="$(mktemp)"
    curl -fsSL "$raw/scripts/gamesphere-hide-steam-clones.sh" -o "$hide_src" 2>/dev/null || hide_src=""
  fi
  if [[ -n "$hide_src" && -f "$hide_src" ]]; then
    install -m 755 "$hide_src" "$bindir/gamesphere-hide-steam-clones.sh"
    echo "==> Installed $bindir/gamesphere-hide-steam-clones.sh (Steam 28de:11ff clones)"
  fi
  if [[ ! -f "$fw_src" ]]; then
    fw_src="$(mktemp)"
    curl -fsSL "$raw/scripts/gamesphere-host-firewall.sh" -o "$fw_src" 2>/dev/null || fw_src=""
  fi
  if [[ -n "$fw_src" && -f "$fw_src" ]]; then
    install -m 755 "$fw_src" "$bindir/gamesphere-host-firewall.sh"
    "$bindir/gamesphere-host-firewall.sh" || true
  fi
  if [[ ! -f "$udev_src" ]]; then
    udev_src="$(mktemp)"
    curl -fsSL "$raw/scripts/udev/99-gamesphere-hide-steam-clones.rules" -o "$udev_src" 2>/dev/null || udev_src=""
  fi
  if [[ -n "$udev_src" && -f "$udev_src" ]]; then
    local udev_user="${XDG_CONFIG_HOME:-$HOME/.config}/gamesphere-import-tool/udev/99-gamesphere-hide-steam-clones.rules"
    mkdir -p "$(dirname "$udev_user")"
    install -m 644 "$udev_src" "$udev_user"
    if sudo -n cp "$udev_src" /etc/udev/rules.d/99-gamesphere-hide-steam-clones.rules 2>/dev/null; then
      sudo -n chmod 644 /etc/udev/rules.d/99-gamesphere-hide-steam-clones.rules 2>/dev/null || true
      sudo -n udevadm control --reload-rules 2>/dev/null || true
      sudo -n udevadm trigger --subsystem-match=input 2>/dev/null || true
      echo "==> Enabled udev rule 99-gamesphere-hide-steam-clones.rules"
    else
      echo "==> udev rule copied to $udev_user (needs sudo to enable system-wide)"
      echo "    sudo cp $udev_user /etc/udev/rules.d/ && sudo udevadm control --reload-rules"
    fi
  fi
  if [[ -f "$install_dir/host_tuning/host_stack.py" ]]; then
    (
      cd "$install_dir"
      if [[ -x "$install_dir/.venv/bin/python3" ]]; then
        "$install_dir/.venv/bin/python3" -c "from host_tuning.host_stack import install_linux_stack; install_linux_stack()" 2>/dev/null || true
      elif command -v uv >/dev/null 2>&1; then
        uv run python3 -c "from host_tuning.host_stack import install_linux_stack; install_linux_stack()" 2>/dev/null || true
      fi
    )
  fi
}

gs_enable_host_bridge() {
  local unit_dir="${1:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"
  local install_dir="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}"
  local wrapper="${GAMESPHERE_HOST_BRIDGE_BIN:-$HOME/.local/bin/gamesphere-host-bridge}"
  if [[ "${GAMESPHERE_ENABLE_HOST_BRIDGE:-1}" =~ ^(0|false|no|off)$ ]]; then
    echo "==> Host daemon skipped (GAMESPHERE_ENABLE_HOST_BRIDGE=0)"
    return 0
  fi
  local src="$install_dir/scripts/gamesphere-host-bridge.sh"
  gs_write_host_bridge_wrapper "$wrapper" "$src"
  mkdir -p "$unit_dir"
  local unit_src="$install_dir/scripts/systemd/gamesphere-host-bridge.service"
  if [[ -f "$unit_src" ]]; then
    install -m 644 "$unit_src" "$unit_dir/gamesphere-host-bridge.service"
  else
    gs_host_bridge_unit_body >"$unit_dir/gamesphere-host-bridge.service"
    chmod 644 "$unit_dir/gamesphere-host-bridge.service"
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "==> No systemctl — installed $wrapper (start it yourself)"
    gs_install_linux_host_stack "$install_dir"
    return 0
  fi
  gs_prepare_user_systemd
  systemctl --user daemon-reload || true
  if systemctl --user enable --now gamesphere-host-bridge.service; then
    echo "==> Enabled gamesphere-host-bridge.service (Companion host daemon; opt out: GAMESPHERE_ENABLE_HOST_BRIDGE=0)"
    echo "    Restarting the bridge never restarts Sunshine. Linger keeps it up after reboot / Game Mode."
    gs_install_linux_host_stack "$install_dir"
    return 0
  fi
  echo "==> Could not enable gamesphere-host-bridge.service from this session."
  echo "    After a desktop login, run:"
  echo "      systemctl --user enable --now gamesphere-host-bridge.service"
  gs_install_linux_host_stack "$install_dir"
  return 0
}

gs_restart_host_bridge_only() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  if systemctl --user restart gamesphere-host-bridge.service 2>/dev/null; then
    echo "==> Restarted gamesphere-host-bridge.service (Sunshine untouched)"
  fi
}
