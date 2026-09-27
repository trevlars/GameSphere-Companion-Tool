#!/usr/bin/env bash
# GameSphere phone mic → PipeWire "GameSphere Mic" with optional HDMI-monitor AEC.
#
# Architecture (speaker-friendly, Sunshine-safe):
#   phone PCM → gamesphere_mic_sink → gamesphere_mic_raw
#   HDMI.monitor ──loopback──► gamesphere_aec_ref  (reference copy only)
#   WebRTC AEC(raw, ref) → gamesphere_mic          (what Steam/Discord select)
#
# Never use sink_master=<HDMI>. That inserts into the HDMI graph and crackles
# Sunshine. Reference is a null-sink fed from the HDMI *monitor* tap only.
#
# No VBAN. Fed by Companion voice_bridge (GSVC UDP 48020, slot 0).
set -euo pipefail

SINK_NAME="${GAMESPHERE_PC_MIC_SINK:-gamesphere_mic_sink}"
RAW_SOURCE="${GAMESPHERE_PC_MIC_RAW:-gamesphere_mic_raw}"
SOURCE_NAME="${GAMESPHERE_PC_MIC_SOURCE:-gamesphere_mic}"
DEVICE_NAME="${GAMESPHERE_PC_MIC_NAME:-GameSphere Mic}"
AEC_REF="${GAMESPHERE_AEC_REF_SINK:-gamesphere_aec_ref}"
AEC_SINK="${GAMESPHERE_AEC_SINK:-gamesphere_aec_sink}"
AEC_LOOP_NAME="gamesphere-hdmi-aec-ref"
# 1 = WebRTC AEC against HDMI monitor (default). 0 = raw remap only.
USE_AEC="${GAMESPHERE_MIC_AEC:-1}"
VBAN_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/pipewire/pipewire.conf.d/50-gamesphere-vban-recv.conf"
ACTION="${1:-install}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [install|status|uninstall|info|aec-on|aec-off]

  install    Create GameSphere Mic (+ HDMI-monitor AEC when GAMESPHERE_MIC_AEC=1)
  status     Show devices / AEC state
  uninstall  Remove GameSphere Mic + AEC modules
  info       Print how Steam should select the mic
  aec-on     Force AEC stack on (same as GAMESPHERE_MIC_AEC=1 install)
  aec-off    Install raw mic only (no HDMI cancel)

Env:
  GAMESPHERE_MIC_AEC=0|1          default 1
  GAMESPHERE_AEC_HDMI_SINK=...    override HDMI sink name
  GAMESPHERE_PC_MIC_NAME / _SINK / _SOURCE / _RAW
Docs: docs/MIC-TO-PC.md
EOF
}

lan_ips() {
  if command -v ip >/dev/null 2>&1; then
    ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | sort -u
  fi
}

node_present() {
  local kind="$1" name="$2"
  pactl list short "$kind" 2>/dev/null | awk '{print $2}' | grep -qx "$name"
}

find_hdmi_sink() {
  if [[ -n "${GAMESPHERE_AEC_HDMI_SINK:-}" ]]; then
    echo "$GAMESPHERE_AEC_HDMI_SINK"
    return 0
  fi
  local def
  def=$(pactl get-default-sink 2>/dev/null || true)
  if [[ "$def" == *hdmi* || "$def" == *HDMI* ]]; then
    echo "$def"
    return 0
  fi
  pactl list short sinks 2>/dev/null | awk '
    tolower($2) ~ /hdmi/ { print $2; exit }
  '
}

unload_matching() {
  local pat="$1" n=0
  while read -r id rest; do
    echo "$rest" | grep -qE "$pat" || continue
    pactl unload-module "$id" 2>/dev/null || true
    n=$((n + 1))
  done < <(pactl list short modules 2>/dev/null)
  [[ "$n" -gt 0 ]]
}

retire_vban() {
  if [[ -f "$VBAN_CONF" ]]; then
    rm -f "$VBAN_CONF"
    echo "==> Removed legacy VBAN config $VBAN_CONF"
  fi
}

strip_gamesphere_aec() {
  while unload_matching 'module-echo-cancel.*(gamesphere_mic|gamesphere_aec)'; do :; done
  while unload_matching "module-loopback.*${AEC_LOOP_NAME}|module-loopback.*sink=${AEC_REF}"; do :; done
  while unload_matching "module-null-sink.*sink_name=${AEC_REF}"; do :; done
  while unload_matching "module-null-sink.*${AEC_SINK}|module-echo-cancel.*sink_name=${AEC_SINK}"; do :; done
}

strip_gamesphere_all() {
  strip_gamesphere_aec
  while unload_matching "module-remap-source.*${SOURCE_NAME}|module-remap-source.*${RAW_SOURCE}"; do :; done
  while unload_matching "module-null-sink.*sink_name=${SINK_NAME}"; do :; done
  # Legacy remap named gamesphere_mic without raw
  while unload_matching 'module-remap-source.*gamesphere_mic'; do :; done
}

ensure_raw_mic() {
  if ! command -v pactl >/dev/null 2>&1; then
    echo "pactl not found — PipeWire/Pulse required" >&2
    exit 1
  fi
  retire_vban
  if ! node_present sinks "$SINK_NAME"; then
    pactl load-module module-null-sink \
      "sink_name=$SINK_NAME" \
      rate=16000 \
      channels=1 \
      "sink_properties=device.description=GameSphereMicSink" >/dev/null
    echo "==> Created sink $SINK_NAME"
  fi
  # Drop legacy remap that published gamesphere_mic directly from the sink.
  while read -r id rest; do
    echo "$rest" | grep -q 'module-remap-source' || continue
    echo "$rest" | grep -q "source_name=${SOURCE_NAME}" || continue
    echo "$rest" | grep -q "master=${SINK_NAME}.monitor" || continue
    pactl unload-module "$id" 2>/dev/null || true
  done < <(pactl list short modules 2>/dev/null)

  if ! node_present sources "$RAW_SOURCE"; then
    pactl load-module module-remap-source \
      "master=${SINK_NAME}.monitor" \
      "source_name=$RAW_SOURCE" \
      "source_properties=device.description=${DEVICE_NAME} Raw" >/dev/null
    echo "==> Created source $RAW_SOURCE"
  fi
}

ensure_aec() {
  local hdmi ref_src
  hdmi=$(find_hdmi_sink || true)
  if [[ -z "$hdmi" ]]; then
    echo "==> No HDMI sink found — installing raw GameSphere Mic without AEC" >&2
    ensure_raw_passthrough
    return 1
  fi
  ref_src="${hdmi}.monitor"

  if ! node_present sinks "$AEC_REF"; then
    pactl load-module module-null-sink \
      "sink_name=$AEC_REF" \
      rate=48000 \
      channels=2 \
      "sink_properties=device.description=GameSphereAECRef" >/dev/null
    echo "==> Created AEC reference sink $AEC_REF"
  fi

  if ! pactl list short modules 2>/dev/null | grep -qE "module-loopback.*sink=${AEC_REF}|${AEC_LOOP_NAME}"; then
    pactl load-module module-loopback \
      "source=${ref_src}" \
      "sink=${AEC_REF}" \
      latency_msec=20 \
      rate=48000 \
      channels=2 \
      source_dont_move=true \
      sink_dont_move=true \
      remix=true \
      "sink_properties=media.name=${AEC_LOOP_NAME}" \
      "source_properties=media.name=${AEC_LOOP_NAME}" >/dev/null
    echo "==> Loopback ${ref_src} → ${AEC_REF} (monitor tap only)"
  fi

  # Replace AEC output if missing or bound to the wrong raw source.
  local bound=""
  bound=$(pactl list short modules 2>/dev/null | awk '
    /module-echo-cancel/ && /gamesphere/ {
      for (i = 2; i <= NF; i++)
        if ($i ~ /^source_master=/) { sub(/^source_master=/, "", $i); print $i; exit }
    }
  ')
  if node_present sources "$SOURCE_NAME" && [[ "$bound" == "$RAW_SOURCE" ]]; then
    echo "==> AEC source $SOURCE_NAME already bound to $RAW_SOURCE"
  else
    while unload_matching 'module-echo-cancel.*gamesphere'; do :; done
    # Also drop a stray remap still named gamesphere_mic
    while read -r id rest; do
      echo "$rest" | grep -q 'module-remap-source' || continue
      echo "$rest" | grep -q "source_name=${SOURCE_NAME}" || continue
      pactl unload-module "$id" 2>/dev/null || true
    done < <(pactl list short modules 2>/dev/null)

    pactl load-module module-echo-cancel \
      "source_master=${RAW_SOURCE}" \
      "source_name=${SOURCE_NAME}" \
      "source_properties=device.description=${DEVICE_NAME}" \
      "sink_master=${AEC_REF}" \
      "sink_name=${AEC_SINK}" \
      channels=1 \
      rate=16000 \
      use_volume_sharing=0 \
      aec_method=webrtc \
      aec_args="extended_filter=1 delay_agnostic=1 noise_suppression=1 high_pass_filter=1 voice_detection=0 analog_gain_control=0 digital_gain_control=0" >/dev/null
    echo "==> WebRTC AEC → $SOURCE_NAME (ref=$AEC_REF from $hdmi monitor)"
  fi

  # Never route game audio through the AEC playback sink.
  pactl set-sink-mute "$AEC_SINK" 1 2>/dev/null || true
  pactl set-sink-volume "$AEC_SINK" 0 2>/dev/null || true
  return 0
}

ensure_raw_passthrough() {
  # Publish SOURCE_NAME as a simple remap when AEC is off / unavailable.
  strip_gamesphere_aec
  if node_present sources "$SOURCE_NAME"; then
    # If it's already an echo-cancel source, remove it so remap can own the name.
    if pactl list short modules 2>/dev/null | grep -q "module-echo-cancel.*source_name=${SOURCE_NAME}"; then
      while unload_matching "module-echo-cancel.*source_name=${SOURCE_NAME}"; do :; done
    fi
  fi
  if ! node_present sources "$SOURCE_NAME"; then
    pactl load-module module-remap-source \
      "master=${SINK_NAME}.monitor" \
      "source_name=$SOURCE_NAME" \
      "source_properties=device.description=${DEVICE_NAME}" >/dev/null
    echo "==> Created source $SOURCE_NAME (raw, no AEC)"
  fi
  pactl set-source-property "$SOURCE_NAME" device.description "$DEVICE_NAME" 2>/dev/null || true
}

print_card() {
  local hdmi aec_on="no"
  hdmi=$(find_hdmi_sink || true)
  if pactl list short modules 2>/dev/null | grep -q "module-echo-cancel.*source_name=${SOURCE_NAME}"; then
    aec_on="yes (WebRTC vs HDMI monitor)"
  fi
  echo ""
  echo "=== GameSphere Mic (PipeWire) ==="
  echo "Device name : $DEVICE_NAME"
  echo "Source      : $SOURCE_NAME"
  echo "Raw source  : $RAW_SOURCE"
  echo "AEC         : $aec_on"
  echo "HDMI ref    : ${hdmi:-"(none)"}"
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
  echo "AEC cancels room gameplay from HDMI speakers so the phone can be used without headphones."
  echo "Reference is HDMI *monitor* only — Sunshine keeps capturing the real HDMI path."
  echo ""
}

do_install() {
  ensure_raw_mic
  if [[ "$USE_AEC" =~ ^(0|false|no|off)$ ]]; then
    ensure_raw_passthrough
  else
    ensure_aec || ensure_raw_passthrough
  fi
  print_card
  echo "Done. Companion host-bridge feeds the raw sink when VOICE is running."
}

case "$ACTION" in
  -h|--help|help) usage; exit 0 ;;
  info) print_card; exit 0 ;;
  status)
    print_card
    if node_present sources "$SOURCE_NAME"; then echo "Source: present"; else echo "Source: missing (run install)"; fi
    if node_present sources "$RAW_SOURCE"; then echo "Raw: present"; else echo "Raw: missing"; fi
    if pactl list short modules 2>/dev/null | grep -q "module-echo-cancel.*source_name=${SOURCE_NAME}"; then
      echo "AEC: active"
    else
      echo "AEC: inactive"
    fi
    if [[ -f "$VBAN_CONF" ]]; then echo "Legacy VBAN conf: still present — run install to remove"; else echo "Legacy VBAN conf: gone"; fi
    exit 0
    ;;
  uninstall)
    strip_gamesphere_all
    retire_vban
    echo "==> Removed GameSphere Mic / AEC modules"
    exit 0
    ;;
  aec-on)
    USE_AEC=1
    do_install
    exit 0
    ;;
  aec-off)
    USE_AEC=0
    do_install
    exit 0
    ;;
  install)
    do_install
    exit 0
    ;;
  *)
    echo "Unknown action: $ACTION" >&2
    usage >&2
    exit 1
    ;;
esac
