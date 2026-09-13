#!/usr/bin/env bash
# Shared Linux auto-update helpers for install-linux.sh / install-flatpak.sh.
# Enables gamesphere-import-update.timer for new users (Game Mode / SSH / reboot).
# Opt out: GAMESPHERE_AUTO_UPDATE=0
# shellcheck disable=SC2034

gs_update_service_body() {
  cat <<'EOF'
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
}

gs_update_timer_body() {
  cat <<'EOF'
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
# GameSphere Import Tool — git/Decky checkout.
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
