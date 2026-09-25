#!/usr/bin/env bash
# Hide Steam Input 28de:11ff clones from SDL/evdev readers. Sunshine virtual pads stay visible.
# Shipped by GameSphere Companion (install-linux.sh). Safe to run repeatedly.
#
# Proton / native Steam games only see the clones, so by default this hides them only
# while an emulator is running or on the Steam Link profile (host_tuning.couch_coop).
#   --force            hide now regardless (emulator launchers, before the emulator starts)
#                      also: GAMESPHERE_FORCE_HIDE_CLONES=1 or BAZZITE_FORCE_HIDE_CLONES=1
#   --owner-pid PID    keep them hidden until PID exits (launcher passes $$, then execs)
#   --restore          make hidden clones readable again
#   --sync             hide or restore to match the current policy
set -euo pipefail

INSTALL_DIR="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}"
DEVICES="${GAMESPHERE_INPUT_DEVICES:-/proc/bus/input/devices}"
RUNTIME="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

usage() { echo "usage: $0 [--force] [--owner-pid PID] | --restore | --sync" >&2; exit 2; }

cmd=(hide)
force=0
owner=""
while (( $# )); do
  case "$1" in
    --force) force=1 ;;
    --owner-pid) owner="${2:-}"; [[ "$owner" =~ ^[0-9]+$ ]] || usage; shift ;;
    --restore) cmd=(restore) ;;
    --sync) cmd=(sync) ;;
    *) usage ;;
  esac
  shift
done
for var in GAMESPHERE_FORCE_HIDE_CLONES BAZZITE_FORCE_HIDE_CLONES; do
  case "${!var:-}" in 1|true|yes|on) force=1 ;; esac
done
if [[ "${cmd[0]}" == "hide" ]]; then
  (( force )) && cmd+=(--force)
  [[ -n "$owner" ]] && cmd+=(--owner-pid "$owner")
fi

if [[ -f "$INSTALL_DIR/host_tuning/couch_coop.py" ]]; then
  export PATH="${HOME}/.local/bin:/usr/bin:/bin:${PATH:-}"
  if [[ -x "$INSTALL_DIR/.venv/bin/python3" ]]; then
    (cd "$INSTALL_DIR" && "$INSTALL_DIR/.venv/bin/python3" -m host_tuning.couch_coop "${cmd[@]}") && exit 0
  fi
  if command -v uv >/dev/null 2>&1; then
    (cd "$INSTALL_DIR" && uv run python3 -m host_tuning.couch_coop "${cmd[@]}") && exit 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    (cd "$INSTALL_DIR" && PYTHONPATH="$INSTALL_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -m host_tuning.couch_coop "${cmd[@]}") && exit 0
  fi
fi

# Fallback without a Companion install: no emulator detection, so only hide when
# forced or on the Steam Link profile. Restore needs the Companion module.
[[ "${cmd[0]}" == "hide" ]] || exit 0
remote="$(tr -d '[:space:]' 2>/dev/null <"$RUNTIME/bazzite-sunshine-remote-xbox-p1" || true)"
if (( ! force )) && [[ "$remote" != "always" ]]; then
  exit 0
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
