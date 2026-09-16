# Mic to PC

GameSphere sends your **phone mic to the streaming PC** so Steam, Discord, OBS, and games on the host hear you. On Linux/Bazzite this is a normal PipeWire capture device — **no VBAN**.

| Setting | Value |
|---------|--------|
| Device name | `GameSphere Mic` |
| Transport | Companion co-op voice (GSVC UDP **48020**) |
| Slot published | **0** (local / host seat) — guests stay party-only |
| Sample rate | 16 kHz mono PCM → PipeWire |

**How it works:** while Companion `VOICE` is running, `voice_bridge` mixes phone↔phone party audio **and** writes slot 0 into a PipeWire null-sink / remap-source named **GameSphere Mic**. Stock Sunshine still has no official client→host mic channel — apps on the host pick the virtual device.

---

## One-click (Linux / Bazzite)

```bash
gamesphere-import --setup-mic
# or:
gamesphere-pc-mic-setup.sh install
```

Creates the virtual source (idempotent), removes any legacy `50-gamesphere-vban-recv.conf`, and prints the device name.

The always-on **host-bridge** also creates/feeds the device when a client sends `VOICE start` (solo or party stream).

### Steam / Discord

1. Start a GameSphere stream (Pro) — co-op voice starts automatically — **or** open **Send mic to PC** and Start.
2. On the PC: set microphone input to **GameSphere Mic**.
3. Mic level / mute in GameSphere control the same uplink Steam hears.

---

## Windows (legacy)

Windows still offers VB-CABLE + a VBAN feeder for older builds. Current iOS sends **co-op voice**, not VBAN — prefer a Linux/Bazzite Sunshine host for PC mic. A future Windows feeder can play GSVC slot 0 into CABLE Input the same way Linux uses PipeWire.

---

## Sunshine / Apollo note

Stock **Sunshine does not ingest** this mic. Apps on the host must select **GameSphere Mic**. Do **not** attach WebRTC AEC to HDMI and do **not** change Sunshine hevc/av1 codecs for mic work.

In-stream couch voice (phone ↔ phone) and PC mic share the same uplink for seat 0.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Device missing | `gamesphere-pc-mic-setup.sh install` or start a stream (`VOICE start`) |
| Steam hears silence | Mic unmuted in GameSphere; seat is slot 0; `pactl list short sources \| grep gamesphere` |
| Party works, Steam silent | Confirm input is **GameSphere Mic**, not HDMI / DualSense / Built-in |
| Legacy VBAN still listed | Re-run `--setup-mic` (removes `50-gamesphere-vban-recv.conf`) |
