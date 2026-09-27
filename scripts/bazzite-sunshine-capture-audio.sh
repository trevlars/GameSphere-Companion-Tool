#!/usr/bin/env bash
# HDMI → Sunshine capture tap (games stay on real HDMI 5.1 AVR/TV).
#
# Default: 5.1 surround tap so Moonlight/GameSphere can request LPCM 5.1.
# Rollback to stereo (phones that crackled on 6ch): BAZZITE_STREAM_AUDIO=stereo
set -euo pipefail

RUNTIME="${XDG_RUNTIME_DIR:-/run/user/1000}"
FLAG="$RUNTIME/bazzite-sunshine-capture.active"
MODE_FLAG="$RUNTIME/bazzite-sunshine-capture.mode"
HDMI_SINK='alsa_output.pci-0000_01_00.1.hdmi-surround'
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/sunshine/sunshine.conf"
ACTION="${1:-status}"

# stereo | surround51  (default surround51)
MODE="${BAZZITE_STREAM_AUDIO:-surround51}"
case "$MODE" in
  stereo|2|Stereo) MODE=stereo ;;
  surround51|5.1|51|surround|Surround51) MODE=surround51 ;;
  *) MODE=surround51 ;;
esac

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

# PipeWire/Pulse uses this for an unconnected stream.
PA_INVALID=4294967295

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

# True when a loopback module exists AND its source-output is still attached
# to a real monitor (not PA_INVALID). A "present but detached" loopback is what
# made Moonlight streams silent while HDMI still had game audio.
loop_healthy() {
  pactl list short modules 2>/dev/null | grep -F "module-loopback" | grep -Fq "sink=${CAPTURE_SINK}" \
    || return 1
  pactl list short modules 2>/dev/null | grep -F "module-loopback" | grep -Fq "source=${HDMI_SINK}.monitor" \
    || return 1
  local src
  src="$(pactl list source-outputs 2>/dev/null | awk '
    function flush() {
      if (loop && src != "" && src != "4294967295") { print src; exit 0 }
    }
    /^Source Output #/ { flush(); src=""; loop=0; next }
    /Source: / { src=$2; next }
    /node\.name/ && /input\.loopback/ { loop=1; next }
    /media\.name/ && /loopback-.* input/ { loop=1; next }
    END { flush() }
  ')"
  [[ -n "$src" ]]
}

ensure_conf_sink() {
  touch "$CONF"
  if grep -qE '^[[:space:]]*audio_sink[[:space:]]*=' "$CONF"; then
    sed -i -E "s|^[[:space:]]*audio_sink[[:space:]]*=.*|audio_sink = ${CAPTURE_SINK}|" "$CONF"
  else
    printf 'audio_sink = %s\n' "$CAPTURE_SINK" >>"$CONF"
  fi
  if grep -qE '^[[:space:]]*virtual_sink[[:space:]]*=' "$CONF"; then
    sed -i -E "s|^[[:space:]]*virtual_sink[[:space:]]*=.*|virtual_sink =|" "$CONF"
  else
    printf 'virtual_sink =\n' >>"$CONF"
  fi
  # Comment the audio block so the mode is obvious in sunshine.conf.
  if grep -qE '^# Audio:' "$CONF"; then
    sed -i -E "s|^# Audio:.*|# Audio: ${CAPTURE_CH}ch tap (${CAPTURE_SINK}); games stay on HDMI 5.1 AVR/TV.|" "$CONF"
  fi
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
  # remix=true: HDMI 5.1 → capture layout (and stereo downmix if CAPTURE_CH=2).
  pactl load-module module-loopback \
    source="${HDMI_SINK}.monitor" sink="$CAPTURE_SINK" \
    latency_msec=120 rate=48000 channels="$CAPTURE_CH" remix=true \
    source_dont_move=true sink_dont_move=true \
    sink_properties="media.name=${LOOP_NAME}" \
    >/dev/null
}

drop_other_mode_taps() {
  # Only one capture mode active — unload the unused tap so Sunshine cannot
  # keep pointing at a stale stereo sink after we switch to 5.1.
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
  install|start|ensure)
    install_capture
    tune_fec_for_client
    ;;
  surround51|5.1)
    exec env BAZZITE_STREAM_AUDIO=surround51 "$0" install
    ;;
  stereo)
    exec env BAZZITE_STREAM_AUDIO=stereo "$0" install
    ;;
  repair)
    unload_matching 'bazzite-hdmi-to-stream-stereo'
    unload_matching 'bazzite-hdmi-to-stream-surround51'
    while read -r id rest; do
      echo "$rest" | grep -q 'module-loopback' || continue
      echo "$rest" | grep -qE 'bazzite-stream-(stereo|surround51)' || continue
      pactl unload-module "$id" 2>/dev/null || true
    done < <(pactl list short modules 2>/dev/null)
    install_capture
    tune_fec_for_client
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
    grep -E '^[[:space:]]*audio_sink[[:space:]]*=' "$CONF" 2>/dev/null || true
    pactl list short sinks 2>/dev/null | awk '/bazzite-stream/ {print "sink",$1,$2,$NF}'
    ;;
  *)
    echo "usage: $0 install|ensure|repair|stop|status|stereo|surround51" >&2
    exit 2
    ;;
esac
