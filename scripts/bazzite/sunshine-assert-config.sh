#!/usr/bin/env bash
# Keep Sunshine pinned to the hardened Moonlight/LAN profile.
# Runs as ExecStartPre for sunshine.service — must stay fast and non-fatal.
set -euo pipefail
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/sunshine/sunshine.conf"
touch "$CONF"

ensure() {
  local key="$1" val="$2"
  if grep -qE "^[[:space:]]*${key}[[:space:]]*=" "$CONF"; then
    sed -i -E "s|^[[:space:]]*${key}[[:space:]]*=.*|${key} = ${val}|" "$CONF"
  else
    printf '%s = %s\n' "$key" "$val" >>"$CONF"
  fi
}

# Drop duplicate gamepad keys (Sunshine can accumulate them across edits)
python3 - "$CONF" <<'PY'
from pathlib import Path
import re, sys
p = Path(sys.argv[1])
lines = p.read_text().splitlines(True)
out, seen = [], set()
for line in lines:
    m = re.match(r"^([A-Za-z0-9_]+)\s*=", line)
    if m and m.group(1) == "gamepad":
        if "gamepad" in seen:
            continue
        seen.add("gamepad")
    out.append(line)
p.write_text("".join(out))
PY

ensure encoder nvenc
ensure capture kms
ensure adapter_name /dev/dri/renderD128
ensure system_tray disabled
# Baseline Trevor/GameSphere profile (gyro + touchpad). Per-stream override:
# bazzite-sunshine-set-gamepad.sh switches to x360 for playroom Steam Link only.
ensure gamepad ds5
ensure motion_as_ds4 enabled
ensure touchpad_as_ds4 enabled
# Steam Link SLVideo is H.264-only; HEVC/AV1 → black screen / encoder OOM.
ensure hevc_mode 0
ensure av1_mode 0
ensure upnp disabled
ensure origin_web_ui_allowed lan
ensure fec_percentage 20
ensure nvenc_preset p4
ensure nvenc_tune ull
ensure nvenc_rc cbr
ensure nvenc_spatial_aq enabled

# Capture 5.1 HDMI tap; games still play on HDMI 5.1 (AVR/TV).
# Must also pin sunshine.conf channels= — Opus encode count is independent of
# the Pulse monitor; channels=2 → "Stereo Spatial" on AirPods.
if [[ -x "$HOME/.local/bin/bazzite-sunshine-capture-audio.sh" ]]; then
  "$HOME/.local/bin/bazzite-sunshine-capture-audio.sh" ensure >/dev/null 2>&1 || true
else
  ensure audio_sink alsa_output.pci-0000_01_00.1.hdmi-surround
  ensure channels 6
fi

# Belt-and-suspenders: if capture script was skipped/old, never leave stereo encode.
mode=""
persist="${XDG_CONFIG_HOME:-$HOME/.config}/gamesphere/bazzite-stream-audio.mode"
envf="${XDG_CONFIG_HOME:-$HOME/.config}/environment.d/90-bazzite-stream-audio.conf"
if [[ -f "$persist" ]]; then
  mode="$(tr -d '[:space:]' <"$persist")"
elif [[ -f "$envf" ]]; then
  mode="$(sed -n 's/^BAZZITE_STREAM_AUDIO=//p' "$envf" | head -1 | tr -d '[:space:]')"
fi
case "$mode" in
  stereo) ensure channels 2 ;;
  *) ensure channels 6 ;;
esac

# Games on HDMI 5.1; Sunshine captures the HDMI tap (not sink-sunshine-*).
ensure virtual_sink ""
