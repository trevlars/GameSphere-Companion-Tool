# Mic to PC

GameSphere can send your **phone mic to the streaming PC** so Discord, OBS, and games on the host hear you. One Import Tool action sets this up — same button / flag on every OS.

| Setting | Value |
|---------|--------|
| Stream name | `GameSphere` |
| Port | `6980` (UDP) |
| Sample rate | `44100` Hz (mono PCM, converted to stereo on Windows) |

**How it works:** the GameSphere app sends VBAN (documented network audio). Stock Sunshine / Apollo / Moonlight still has **no** official client→host mic channel. Import Tool provides the host receiver:

- **Windows:** VB-CABLE virtual cable + a small OSS feeder that plays VBAN into **CABLE Input**. Apps pick **CABLE Output**.
- **Linux:** PipeWire `vban-recv` source named **GameSphere Mic (VBAN)**.

---

## One-click (recommended)

### Windows GUI

1. Open **GameSphere Import Tool**.
2. Click **Set up mic for GameSphere**.
3. Accept **VB-Audio Cable** terms when prompted (donationware — we download it; we do **not** ship their driver).
4. When finished, note the **LAN IP** shown (also opens a small status page). Reboot once if Windows has not listed CABLE devices yet.
5. On the phone: GameSphere → **Send mic to PC** → enter that IP (port `6980`, stream `GameSphere`).
6. Start a stream → **Mic** chip on. In Discord/OBS, pick **CABLE Output**.

No VoiceMeeter. The feeder starts at logon after setup.

### CLI (any platform)

```bash
# Preview IPs / defaults only
gamesphere-import --setup-mic-info

# Linux / Bazzite — PipeWire OSS receiver
gamesphere-import --setup-mic

# Windows — installs VB-CABLE + starts the VBAN feeder (requires license accept)
gamesphere-import --setup-mic --accept-vbaudio-license
```

PowerShell (Windows, from a checkout):

```powershell
.\scripts\gamesphere-vban-setup.ps1 -Action setup -AcceptLicense
# then start the feeder (Import Tool does this automatically):
python vban_feeder.py
```

Linux helper (after `install-linux.sh`):

```bash
gamesphere-vban-setup.sh          # same as --setup-mic
gamesphere-vban-setup.sh info
```

---

## What happens under the hood

Same UX; different engines:

| Host OS | Receiver | Virtual mic | License |
|---------|----------|-------------|---------|
| **Windows** | Bundled OSS VBAN feeder (`vban_feeder.py`) → **CABLE Input** + firewall UDP `6980` | **CABLE Output** | VB-CABLE is VB-Audio **donationware** (user accepts; not bundled). Feeder is OSS in this repo. |
| **Linux / Bazzite** | PipeWire `libpipewire-module-vban-recv` | “GameSphere Mic (VBAN)” source | **MIT** (OSS) |

Firewall: allow **UDP 6980** inbound on the host (the Windows script tries to add this automatically).

---

## Sunshine / Apollo note

Stock **Sunshine does not ingest GameSphere’s VBAN mic**. Apps on the host (Discord, in-game voice, OBS) must select the **virtual recording device** (CABLE Output or PipeWire). Experimental Moonlight/Apollo/Foundation mic passthrough is a different stack and is **not** what GameSphere uses today.

---

## Why VB-CABLE instead of VoiceMeeter?

VoiceMeeter is a full mixer UI. Testers should not have to learn it. VB-CABLE is one virtual cable — the same pattern VoidLink / Moonlight V+ Windows testers already use — plus a tiny feeder so GameSphere can keep its existing phone VBAN sender (works with stock Sunshine on Bazzite, not only Foundation hosts).

Creating a Windows **recording device** still needs a signed virtual audio driver. There is no mature, license-clean OSS package that both receives VBAN and registers a mic. Embedding VB-CABLE would violate VB-Audio distribution rules — so Import Tool **downloads the official zip** with an explicit license prompt, then runs our OSS feeder.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Phone can’t connect | Confirm LAN IP, UDP `6980`, same Wi‑Fi/Ethernet segment; check firewall |
| CABLE Output missing | Reboot after VB-CABLE install; confirm **CABLE Input** exists in Windows sound playback devices |
| Discord hears nothing | Discord input = **CABLE Output**; feeder running (`GamesphereImportTool.exe --vban-feeder` or logon autostart); Mic chip on in GameSphere |
| Feeder log | `%LOCALAPPDATA%\GameSphere\vban-feeder.log` |
| Linux no device | Update PipeWire; confirm `libpipewire-module-vban-recv` exists; re-run `gamesphere-vban-setup.sh` |
| Download failed | Install from [vb-audio.com/Cable](https://vb-audio.com/Cable/), reboot, then **Set up mic** again |

---

## License cheat sheet

| Piece | Status |
|-------|--------|
| VBAN protocol (PCM) | Public / free to implement ([spec PDF](https://vb-audio.com/Voicemeeter/VBANProtocol_Specifications.pdf)) |
| VB-CABLE | Proprietary donationware — **not** bundled here; official zip downloaded at setup |
| Import Tool VBAN feeder | OSS in this repo (`vban_feeder.py`) |
| PipeWire `vban-recv` | MIT |
| [quiniouben/vban](https://github.com/quiniouben/vban) | GPL-3.0 (optional Linux CLI alt) |
