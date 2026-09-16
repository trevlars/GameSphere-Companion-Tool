#!/usr/bin/env bash
# GameSphere phone mic → PipeWire virtual capture "GameSphere Mic".
# Fed by Companion voice_bridge (GSVC UDP 48020, slot 0). No VBAN.
set -euo pipefail

SINK_NAME="${GAMESPHERE_PC_MIC_SINK:-gamesphere_mic_sink}"
SOURCE_NAME="${GAMESPHERE_PC_MIC_SOURCE:-gamesphere_mic}"
DEVICE_NAME="${GAMESPHERE_PC_MIC_NAME:-GameSphere Mic}"
VBAN_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/pipewire/pipewire.conf.d/50-gamesphere-vban-recv.conf"
ACTION="${1:-install}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [install|status|uninstall|info]

  install    Create PipeWire null-sink + remap-source "$DEVICE_NAME"; remove legacy VBAN conf
  status     Show whether the virtual mic exists
  uninstall  Unload GameSphere Mic modules (keeps Steam prefs until next install)
  info       Print device name + how Steam should select it

Env: GAMESPHERE_PC_MIC_NAME, GAMESPHERE_PC_MIC_SINK, GAMESPHERE_PC_MIC_SOURCE
Docs: docs/MIC-TO-PC.md
EOF
}

lan_ips() {
  if command -v ip >/dev/null 2>&1; then
    ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | sort -u
  fi
}

print_card() {
  echo ""
  echo "=== GameSphere Mic (PipeWire) ==="
  echo "Device name : $DEVICE_NAME"
  echo "Source      : $SOURCE_NAME"
  echo "Fed by      : Companion voice mixer (UDP 48020, local slot 0)"
  echo "LAN IP(s)   :"
  local any=0
  while IFS= read -r ip; do
    [[ -z "$ip" ]] && continue
    echo "  $ip"
    any=1
  done < <(lan_ips)
  if [[ "$any" -eq 0 ]]; then
    echo "  (none detected)"
  fi
  echo ""
  echo "Steam / Discord / games: set microphone input to \"$DEVICE_NAME\"."
  echo "In GameSphere: start a stream (or Send mic to PC) so Companion VOICE is running."
  echo "No VBAN. No UDP 6980."
  echo ""
}

source_present() {
  pactl list short sources 2>/dev/null | awk '{print $2}' | grep -qx "$SOURCE_NAME"
}

sink_present() {
  pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -qx "$SINK_NAME"
}

retire_vban() {
  if [[ -f "$VBAN_CONF" ]]; then
    rm -f "$VBAN_CONF"
    echo "==> Removed legacy VBAN config $VBAN_CONF"
  fi
}

ensure_device() {
  if ! command -v pactl >/dev/null 2>&1; then
    echo "pactl not found — PipeWire/Pulse required" >&2
    exit 1
  fi
  retire_vban
  if ! sink_present; then
    pactl load-module module-null-sink \
      "sink_name=$SINK_NAME" \
      rate=16000 \
      channels=1 \
      "sink_properties=device.description=GameSphereMicSink" >/dev/null
    echo "==> Created sink $SINK_NAME"
  else
    echo "==> Sink $SINK_NAME already present"
  fi
  if ! source_present; then
    pactl load-module module-remap-source \
      "master=${SINK_NAME}.monitor" \
      "source_name=$SOURCE_NAME" \
      "source_properties=device.description=$DEVICE_NAME" >/dev/null
    echo "==> Created source $SOURCE_NAME ($DEVICE_NAME)"
  else
    echo "==> Source $SOURCE_NAME already present"
  fi
  pactl set-source-property "$SOURCE_NAME" device.description "$DEVICE_NAME" 2>/dev/null || true
}

unload_gamesphere_mic() {
  local ids
  ids=$(pactl list short modules 2>/dev/null | awk -v s="$SINK_NAME" -v r="$SOURCE_NAME" '
    $0 ~ s || $0 ~ r { print $1 }
  ' | sort -u)
  if [[ -z "$ids" ]]; then
    echo "==> Nothing to unload"
    return
  fi
  for id in $ids; do
    pactl unload-module "$id" 2>/dev/null || true
    echo "==> Unloaded module $id"
  done
}

case "$ACTION" in
  -h|--help|help) usage; exit 0 ;;
  info) print_card; exit 0 ;;
  status)
    print_card
    if source_present; then echo "Source: present"; else echo "Source: missing (run install)"; fi
    if [[ -f "$VBAN_CONF" ]]; then echo "Legacy VBAN conf: still present — run install to remove"; else echo "Legacy VBAN conf: gone"; fi
    exit 0
    ;;
  uninstall)
    unload_gamesphere_mic
    retire_vban
    exit 0
    ;;
  install)
    ensure_device
    print_card
    echo "Done. Companion host-bridge feeds this device when VOICE is running."
    exit 0
    ;;
  *)
    echo "Unknown action: $ACTION" >&2
    usage >&2
    exit 1
    ;;
esac
