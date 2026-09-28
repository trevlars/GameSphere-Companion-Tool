#!/usr/bin/env bash
# HDMI → Sunshine capture tap (games stay on real HDMI 5.1 AVR/TV).
#
# Default: 5.1. HDMI is already 6ch; the stereo tap downmixes that and Spatial
# has nothing real to work with. Client must request LPCM 5.1 (6ch) — not 7.1.
# A 6ch sink + 2ch/8ch client request is what silenced Sunshine (pa_simple_new).
#
# Persist mode in ~/.config so stream-prep `ensure` / reboot cannot fall back
# to stereo. Override: BAZZITE_STREAM_AUDIO=stereo or `$0 stereo`.
set -euo pipefail

RUNTIME="${XDG_RUNTIME_DIR:-/run/user/1000}"
FLAG="$RUNTIME/bazzite-sunshine-capture.active"
MODE_FLAG="$RUNTIME/bazzite-sunshine-capture.mode"
PERSIST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/gamesphere"
PERSIST_MODE="$PERSIST_DIR/bazzite-stream-audio.mode"
HDMI_SINK='alsa_output.pci-0000_01_00.1.hdmi-surround'
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/sunshine/sunshine.conf"
ACTION="${1:-status}"

normalize_mode() {
  case "${1:-}" in
    stereo|2|Stereo) echo stereo ;;
    surround51|5.1|51|surround|Surround51) echo surround51 ;;
    *) echo "" ;;
  esac
}

# Resolve: env / CLI (explicit) → persist (survives reboot) → runtime → 5.1.
# Persist beats a leftover /run stereo flag from the 2026-09-27 silent-stream revert.
MODE=""
if [[ -n "${BAZZITE_STREAM_AUDIO:-}" ]]; then
  MODE="$(normalize_mode "$BAZZITE_STREAM_AUDIO")"
fi
if [[ -z "$MODE" ]]; then
  case "$ACTION" in
    stereo) MODE=stereo ;;
    surround51|5.1) MODE=surround51 ;;
  esac
fi
if [[ -z "$MODE" && -f "$PERSIST_MODE" ]]; then
  MODE="$(normalize_mode "$(tr -d '[:space:]' <"$PERSIST_MODE")")"
fi
if [[ -z "$MODE" && -f "$MODE_FLAG" ]]; then
  MODE="$(normalize_mode "$(tr -d '[:space:]' <"$MODE_FLAG")")"
fi
if [[ -z "$MODE" ]]; then
  MODE=surround51
fi

if [[ "$MODE" == "stereo" ]]; then
  CAPTURE_SINK='bazzite-stream-stereo'
  LOOP_NAME='bazzite-hdmi-to-stream-stereo'
  CAPTURE_CH=2
  CAPTURE_DESC='BazziteStreamStereo'
else
  CAPTURE_SINK='bazzite-stream-surround51'
  LOOP_NAME='bazzite-hdmi-to-stream-surround51'
  CAPTURE_CH=6
  CAPTURE_DESC='BazziteStreamSurround51'
fi

unload_matching() {
  local pat="$1"
  while read -r id rest; do
    echo "$rest" | grep -qE "$pat" || continue
    pactl unload-module "$id" 2>/dev/null || true
  done < <(pactl list short modules 2>/dev/null)
}

sink_present() {
  pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -qx "$CAPTURE_SINK"
}

loop_module_id() {
  pactl list short modules 2>/dev/null | awk -v n="$LOOP_NAME" 'index($0,n)>0 {print $1; exit}'
}

loop_healthy() {
  pactl list short modules 2>/dev/null | grep -F "module-loopback" | grep -Fq "sink=${CAPTURE_SINK}" \
    || return 1
  pactl list short modules 2>/dev/null | grep -F "module-loopback" | grep -Fq "source=${HDMI_SINK}.monitor" \
    || return 1
  # Prefer the named loopback's source-output; fall back to any healthy loopback.
  local src
  src="$(pactl list source-outputs 2>/dev/null | awk -v want="$LOOP_NAME" '
    function flush() {
      if (loop && src != "" && src != "4294967295") { print src; exit 0 }
    }
    /^Source Output #/ { flush(); src=""; loop=0; next }
    /Source: / { src=$2; next }
    /media\.name/ && index($0, want) > 0 { loop=1; next }
    /node\.name/ && /input\.loopback/ { loop=1; next }
    /media\.name/ && /loopback-.* input/ { loop=1; next }
    END { flush() }
  ')"
  [[ -n "$src" ]]
}

conf_get() {
  local key="$1"
  [[ -f "$CONF" ]] || return 0
  # Last assignment wins (Sunshine can accumulate duplicates across edits).
  awk -v k="$key" '
    $0 ~ "^[[:space:]]*"k"[[:space:]]*=" {
      sub(/^[[:space:]]*[^=]+=[[:space:]]*/, "");
      gsub(/[[:space:]]+$/, "");
      v=$0
    }
    END { print v }
  ' "$CONF"
}

# Drop duplicate keys so a stale channels=2 cannot shadow channels=6.
dedupe_conf_keys() {
  local keys_csv="$1"
  [[ -f "$CONF" ]] || return 0
  python3 - "$CONF" "$keys_csv" <<'PY'
from pathlib import Path
import re, sys
p = Path(sys.argv[1])
keys = set(sys.argv[2].split(","))
lines = p.read_text().splitlines(True)
# Keep the last assignment for each tracked key.
last = {}
for i, line in enumerate(lines):
    m = re.match(r"^([A-Za-z0-9_]+)\s*=", line)
    if m and m.group(1) in keys:
        last[m.group(1)] = i
keep = set(last.values())
out = []
for i, line in enumerate(lines):
    m = re.match(r"^([A-Za-z0-9_]+)\s*=", line)
    if m and m.group(1) in keys and i not in keep:
        continue
    out.append(line)
p.write_text("".join(out))
PY
}

ensure_conf_sink() {
  touch "$CONF"
  if grep -qE '^[[:space:]]*audio_sink[[:space:]]*=' "$CONF"; then
    sed -i -E "s|^[[:space:]]*audio_sink[[:space:]]*=.*|audio_sink = ${CAPTURE_SINK}|" "$CONF"
  else
    printf 'audio_sink = %s\n' "$CAPTURE_SINK" >>"$CONF"
  fi
  # Sunshine encodes Opus at this channel count regardless of the Pulse
  # monitor. Leaving channels=2 with a 6ch tap is what made iOS Control Center
  # show "Stereo Spatial" while HDMI stayed 5.1.
  if grep -qE '^[[:space:]]*channels[[:space:]]*=' "$CONF"; then
    sed -i -E "s|^[[:space:]]*channels[[:space:]]*=.*|channels = ${CAPTURE_CH}|" "$CONF"
  else
    printf 'channels = %s\n' "$CAPTURE_CH" >>"$CONF"
  fi
  if grep -qE '^[[:space:]]*virtual_sink[[:space:]]*=' "$CONF"; then
    sed -i -E "s|^[[:space:]]*virtual_sink[[:space:]]*=.*|virtual_sink =|" "$CONF"
  else
    printf 'virtual_sink =\n' >>"$CONF"
  fi
  dedupe_conf_keys "audio_sink,channels,virtual_sink"
  if grep -qE '^# Audio:' "$CONF"; then
    sed -i -E "s|^# Audio:.*|# Audio: ${CAPTURE_CH}ch tap (${CAPTURE_SINK}); games stay on HDMI 5.1 AVR/TV.|" "$CONF"
  fi
}

# True when Pulse tap + sunshine.conf (+ persist) all agree — used by stream-prep.
audio_config_ok() {
  [[ "$(conf_get audio_sink)" == "$CAPTURE_SINK" ]] || return 1
  [[ "$(conf_get channels)" == "$CAPTURE_CH" ]] || return 1
  sink_present || return 1
  loop_healthy || return 1
  if [[ -f "${XDG_CONFIG_HOME:-$HOME/.config}/environment.d/90-bazzite-stream-audio.conf" ]]; then
    grep -qE "^BAZZITE_STREAM_AUDIO=${MODE}$" \
      "${XDG_CONFIG_HOME:-$HOME/.config}/environment.d/90-bazzite-stream-audio.conf" || return 1
  fi
  return 0
}

reroute_stray_mic_playback() {
  local mic_sink='gamesphere_mic_sink'
  pactl list short sink-inputs 2>/dev/null | while read -r id sid _; do
    local app sink_name
    app="$(pactl list sink-inputs 2>/dev/null | awk -v want="$id" '
      $1=="Sink" && $2=="Input" && $3==("#"want){p=1;next}
      p && /^Sink Input #/{exit}
      p && /application\.name/{gsub(/"/,"",$3); print $3; exit}')"
    [[ "$app" == "pacat" ]] || continue
    sink_name="$(pactl list short sinks 2>/dev/null | awk -v i="$sid" '$1==i{print $2}')"
    [[ "$sink_name" == "$HDMI_SINK" ]] && pactl move-sink-input "$id" "$mic_sink" 2>/dev/null || true
  done
}

load_loopback() {
  pactl load-module module-loopback \
    source="${HDMI_SINK}.monitor" sink="$CAPTURE_SINK" \
    latency_msec=120 rate=48000 channels="$CAPTURE_CH" remix=true \
    source_dont_move=true sink_dont_move=true \
    sink_properties="media.name=${LOOP_NAME}" \
    >/dev/null
}

drop_other_mode_taps() {
  if [[ "$MODE" == "surround51" ]]; then
    unload_matching 'bazzite-hdmi-to-stream-stereo'
    unload_matching 'sink_name=bazzite-stream-stereo'
  else
    unload_matching 'bazzite-hdmi-to-stream-surround51'
    unload_matching 'sink_name=bazzite-stream-surround51'
  fi
}

install_capture() {
  command -v pactl >/dev/null 2>&1 || return 1
  drop_other_mode_taps
  if ! sink_present; then
    if [[ "$CAPTURE_CH" -eq 6 ]]; then
      pactl load-module module-null-sink \
        sink_name="$CAPTURE_SINK" rate=48000 channels=6 \
        channel_map=front-left,front-right,front-center,lfe,rear-left,rear-right \
        sink_properties="device.description=${CAPTURE_DESC},media.name=${CAPTURE_SINK}" \
        >/dev/null
    else
      pactl load-module module-null-sink \
        sink_name="$CAPTURE_SINK" rate=48000 channels=2 \
        sink_properties="device.description=${CAPTURE_DESC},media.name=${CAPTURE_SINK}" \
        >/dev/null
    fi
  fi
  if ! loop_healthy; then
    unload_matching "$LOOP_NAME"
    while read -r id rest; do
      echo "$rest" | grep -q 'module-loopback' || continue
      echo "$rest" | grep -qF "$CAPTURE_SINK" || continue
      pactl unload-module "$id" 2>/dev/null || true
    done < <(pactl list short modules 2>/dev/null)
    load_loopback
  fi
  pactl set-sink-mute "$CAPTURE_SINK" 0 2>/dev/null || true
  pactl set-sink-volume "$CAPTURE_SINK" 100% 2>/dev/null || true
  pactl set-default-sink "$HDMI_SINK" 2>/dev/null || true
  reroute_stray_mic_playback
  ensure_conf_sink
  : >"$FLAG"
  printf '%s\n' "$MODE" >"$MODE_FLAG"
  mkdir -p "$PERSIST_DIR"
  printf '%s\n' "$MODE" >"$PERSIST_MODE"
  # systemd user services inherit this; stereo here silently undoes 5.1 on every Sunshine start.
  mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/environment.d"
  printf 'BAZZITE_STREAM_AUDIO=%s\n' "$MODE" >"${XDG_CONFIG_HOME:-$HOME/.config}/environment.d/90-bazzite-stream-audio.conf"
  systemctl --user set-environment "BAZZITE_STREAM_AUDIO=${MODE}" 2>/dev/null || true
}

teardown_capture() {
  unload_matching 'bazzite-hdmi-to-stream-stereo'
  unload_matching 'bazzite-hdmi-to-stream-surround51'
  unload_matching 'sink_name=bazzite-stream-stereo'
  unload_matching 'sink_name=bazzite-stream-surround51'
  rm -f "$FLAG" "$MODE_FLAG"
  if grep -qE '^[[:space:]]*audio_sink[[:space:]]*=' "$CONF" 2>/dev/null; then
    sed -i -E "s|^[[:space:]]*audio_sink[[:space:]]*=.*|audio_sink = ${HDMI_SINK}|" "$CONF"
  fi
}

phone_stream_active() {
  local mode_file="$RUNTIME/bazzite-sunshine-gamepad-mode"
  [[ -f "$mode_file" ]] && grep -qx 'ds5' "$mode_file" && return 0
  local ip
  while read -r ip; do
    [[ -z "$ip" ]] && continue
    [[ "$ip" == "10.0.4.33" ]] && continue
    return 0
  done < <(ss -H -tn state established 2>/dev/null | awk '
    {
      split($4, l, ":");
      split($3, r, ":");
      peer=r[1]; gsub(/\[|\]/, "", peer);
      port=l[length(l)];
      if (port ~ /^(47984|47989|47990|48010)$/) print peer;
    }' | sort -u)
  return 1
}

tune_fec_for_client() {
  touch "$CONF"
  local fec=10
  if phone_stream_active; then
    fec=25
  fi
  if grep -qE '^[[:space:]]*fec_percentage[[:space:]]*=' "$CONF"; then
    sed -i -E "s|^[[:space:]]*fec_percentage[[:space:]]*=.*|fec_percentage = ${fec}|" "$CONF"
  else
    printf 'fec_percentage = %s\n' "$fec" >>"$CONF"
  fi
}

case "$ACTION" in
  install|start|ensure|repair)
    if [[ "$ACTION" == "repair" ]]; then
      unload_matching 'bazzite-hdmi-to-stream-stereo'
      unload_matching 'bazzite-hdmi-to-stream-surround51'
      while read -r id rest; do
        echo "$rest" | grep -q 'module-loopback' || continue
        echo "$rest" | grep -qE 'bazzite-stream-(stereo|surround51)' || continue
        pactl unload-module "$id" 2>/dev/null || true
      done < <(pactl list short modules 2>/dev/null)
    fi
    install_capture
    tune_fec_for_client
    ;;
  surround51|5.1)
    exec env BAZZITE_STREAM_AUDIO=surround51 "$0" install
    ;;
  stereo)
    exec env BAZZITE_STREAM_AUDIO=stereo "$0" install
    ;;
  stop)
    teardown_capture
    tune_fec_for_client
    ;;
  status)
    echo "mode=${MODE}"
    [[ -f "$MODE_FLAG" ]] && echo "active_mode=$(tr -d '[:space:]' <"$MODE_FLAG")"
    if sink_present; then echo "capture_sink=present name=${CAPTURE_SINK} ch=${CAPTURE_CH}"; else echo "capture_sink=missing name=${CAPTURE_SINK}"; fi
    if loop_healthy; then echo "loopback=healthy"; elif loop_module_id >/dev/null; then echo "loopback=broken"; else echo "loopback=missing"; fi
    echo "conf_audio_sink=$(conf_get audio_sink)"
    echo "conf_channels=$(conf_get channels)"
    if audio_config_ok; then echo "audio_ok=1"; else echo "audio_ok=0"; fi
    pactl list short sinks 2>/dev/null | awk '/bazzite-stream/ {print "sink",$1,$2}'
    pactl list short sources 2>/dev/null | awk "/${CAPTURE_SINK}\\.monitor/ {print \"monitor\",\$2}"
    ;;
  check)
    # Non-zero when tap/conf drifted (for timers / stream-prep).
    install_capture
    tune_fec_for_client
    if audio_config_ok; then
      echo "audio_ok=1 mode=${MODE} channels=${CAPTURE_CH}"
      exit 0
    fi
    echo "audio_ok=0 mode=${MODE} want_ch=${CAPTURE_CH} conf_ch=$(conf_get channels) sink=$(conf_get audio_sink)" >&2
    exit 1
    ;;
  *)
    echo "usage: $0 install|ensure|repair|stop|status|check|stereo|surround51" >&2
    exit 2
    ;;
esac
