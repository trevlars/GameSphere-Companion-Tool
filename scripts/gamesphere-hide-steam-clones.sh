#!/usr/bin/env bash
# Hide Steam Input 28de:11ff clones from SDL. Sunshine virtual pads stay visible.
# Shipped by GameSphere Companion (install-linux.sh). Safe to run repeatedly.
set -euo pipefail

INSTALL_DIR="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}"
DEVICES="${GAMESPHERE_INPUT_DEVICES:-/proc/bus/input/devices}"

if [[ -f "$INSTALL_DIR/host_tuning/couch_coop.py" ]]; then
  export PATH="${HOME}/.local/bin:/usr/bin:/bin:${PATH:-}"
  if [[ -x "$INSTALL_DIR/.venv/bin/python3" ]]; then
    (cd "$INSTALL_DIR" && "$INSTALL_DIR/.venv/bin/python3" -c "from host_tuning.couch_coop import hide_steam_clones; hide_steam_clones()") && exit 0
  fi
  if command -v uv >/dev/null 2>&1; then
    (cd "$INSTALL_DIR" && uv run python3 -c "from host_tuning.couch_coop import hide_steam_clones; hide_steam_clones()") && exit 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    (cd "$INSTALL_DIR" && PYTHONPATH="$INSTALL_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -c "from host_tuning.couch_coop import hide_steam_clones; hide_steam_clones()") && exit 0
  fi
fi

[[ -r "$DEVICES" ]] || exit 0

chmod_hide() {
  local node="$1"
  [[ -e "$node" ]] || return 0
  local mode
  mode="$(stat -c '%a' "$node" 2>/dev/null || echo 999)"
  [[ "$mode" == "0" ]] && return 0
  if [[ "$(id -u)" == "0" ]]; then
    chmod 000 "$node" 2>/dev/null || true
    command -v setfacl >/dev/null 2>&1 && setfacl -b "$node" 2>/dev/null || true
    return 0
  fi
  sudo -n chmod 000 "$node" 2>/dev/null || chmod 000 "$node" 2>/dev/null || true
  sudo -n setfacl -b "$node" 2>/dev/null || true
}

vendor="" product="" handlers=""
flush() {
  if [[ "${vendor}" == "28de" && "${product}" == "11ff" ]]; then
    for h in $handlers; do
      case "$h" in
        event*|js*) chmod_hide "/dev/input/$h" ;;
      esac
    done
  fi
  vendor="" product="" handlers=""
}
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ -z "$line" ]]; then
    flush
    continue
  fi
  case "$line" in
    I:*)
      v="${line#*Vendor=}"; v="${v%% *}"; vendor="$(printf '%04x' "0x${v}" 2>/dev/null || echo "${v}" | tr 'A-F' 'a-f')"
      p="${line#*Product=}"; p="${p%% *}"; product="$(printf '%04x' "0x${p}" 2>/dev/null || echo "${p}" | tr 'A-F' 'a-f')"
      ;;
    H:*)
      handlers="${line#H: Handlers=}"
      ;;
  esac
done < "$DEVICES"
flush
