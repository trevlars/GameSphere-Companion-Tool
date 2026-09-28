# Mic to PC

GameSphere sends your **phone mic to the streaming PC** so Steam, Discord, OBS, and games on the host hear you. On Linux/Bazzite this is a normal PipeWire capture device — **no VBAN**.

| Setting | Value |
|---------|--------|
| Device name | `GameSphere Mic` |
| Transport | Companion co-op voice (GSVC UDP **48020**) |
| Slot published | **0** (local / host seat) — guests stay party-only |
| Sample rate | Phone **48 kHz** mono (10 ms GSVC frames) → PipeWire **48 kHz** |
| Codec | **Auto** (default): PCM on good LAN, Opus when RTT/loss rises · **High**: PCM · **Data saver**: Opus ~16 kbps |
| AEC | Off by default (raw uplink). Optional WebRTC vs HDMI (`aec-on`) — verify Mic Test levels after enabling |

**How it works:** while Companion `VOICE` is running, `voice_bridge` mixes phone↔phone party audio **and** writes slot 0 into a PipeWire null-sink published as **GameSphere Mic**. Optional AEC (`aec-on`) subtracts room gameplay via WebRTC against an HDMI monitor copy (Sunshine-safe).

### Why not AEC on the HDMI sink?

Older Bazzite scripts used `module-echo-cancel` with `sink_master=<HDMI>`. That inserts into the HDMI playback graph and **crackles Sunshine**. Companion never does that. Instead:

**Default (raw):** phone 48 kHz PCM → `gamesphere_mic_sink` → remap → **`gamesphere_mic`**.

**Optional AEC** (`gamesphere-pc-mic-setup.sh aec-on`): WebRTC; HDMI monitor → echo-cancel sink (reference), mic sink monitor → cleaned **`gamesphere_mic`**.

Sunshine captures a separate HDMI tap (`bazzite-stream-surround51` by default, or stereo) so games stay on the real HDMI AVR path. Companion overwrites `sunshine.conf` `channels` (+ `audio_sink`) to match the tap whenever the host bridge starts or a stream begins — a leftover `channels = 2` is what made AirPods show “Stereo Spatial”. Opt out of AEC: `GAMESPHERE_MIC_AEC=0` or `gamesphere-pc-mic-setup.sh aec-off`.

---

## One-click (Linux / Bazzite)

```bash
gamesphere-import --setup-mic
# or:
gamesphere-pc-mic-setup.sh install
gamesphere-pc-mic-setup.sh status   # shows AEC active/inactive
```

Creates the virtual source (idempotent), enables HDMI-monitor AEC when an HDMI sink is present, removes any legacy `50-gamesphere-vban-recv.conf`, and prints the device name.

The always-on **host-bridge** also creates/feeds the device when a client sends `VOICE start` (solo or party stream).

### Steam / Discord

1. Start a GameSphere stream (Pro) — co-op voice starts automatically — **or** open **Send mic to PC** and Start.
2. On a **GameSphere device** stream, Companion **auto-selects** Steam Voice + the Pulse default source as **GameSphere Mic** (`gamesphere-stream-mic.sh` / host prep). Steam Link sessions leave DualSense / rear mic alone.
3. Mic level / mute in GameSphere control the same uplink Steam hears.
4. Play on TV/AVR speakers — AEC should cancel most game bleed from the phone mic.
5. If Steam was already open, it may need one restart the first time the PipeWire device appears; after that, stream-start keeps the preference.

---

## Windows (legacy)

Windows still offers VB-CABLE + a VBAN feeder for older builds. Current iOS sends **co-op voice**, not VBAN — prefer a Linux/Bazzite Sunshine host for PC mic. A future Windows feeder can play GSVC slot 0 into CABLE Input the same way Linux uses PipeWire.

---

## Sunshine / Apollo note

Stock **Sunshine does not ingest** this mic. Apps on the host must select **GameSphere Mic**. Do **not** attach WebRTC AEC to the HDMI sink itself and do **not** change Sunshine hevc/av1 codecs for mic work.

In-stream couch voice (phone ↔ phone) and PC mic share the same uplink for seat 0.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Device missing | `gamesphere-pc-mic-setup.sh install` or start a stream (`VOICE start`) |
| Steam hears silence | Mic unmuted in GameSphere; seat is slot 0; `pactl list short sources \| grep gamesphere` |
| Party works, Steam silent | Confirm input is **GameSphere Mic**, not HDMI / DualSense / Built-in |
| Game audio still in Discord | Confirm `gamesphere-pc-mic-setup.sh status` says `AEC: active`; HDMI must be the room speakers; speak while a game is loud — WebRTC needs a moment to adapt (`delay_agnostic`) |
| Sunshine audio crackles | You must not have `sink_master=<hdmi>` AEC. Re-run `gamesphere-pc-mic-setup.sh install` (monitor-tap only). Check `pactl get-default-sink` is still HDMI |
| Want raw mic (no cancel) | `GAMESPHERE_MIC_AEC=0 gamesphere-pc-mic-setup.sh install` or `… aec-off` |
| Legacy VBAN still listed | Re-run `--setup-mic` (removes `50-gamesphere-vban-recv.conf`) |
| Profile-audio strips AEC | HTPC `bazzite-profile-audio.sh` must not unload `module-echo-cancel` modules whose names contain `gamesphere` |
| Steam still on Default / DualSense mid-stream | Confirm client is GameSphere (`remote_xbox_p1=never`); run `gamesphere-stream-mic.sh start`; Steam Link intentionally skips this pin |
