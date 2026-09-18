# GameSphere Companion Tool

Formerly **GameSphere Import Tool**. Install names are unchanged: `gamesphere-import`, Flatpak `io.github.trevlars.GamesphereImportTool`, Windows `GamesphereImportTool.exe`.

Desktop companion for **[GameSphere](https://github.com/trevlars/GameSphere)** on iOS, iPadOS, and tvOS — and any Moonlight client — when you stream from a **Sunshine** or **Apollo** PC. It fills your host with games and cover art, then keeps the PC paired for invites, couch co-op, voice, and session features.

<p align="center">
  <a href="https://github.com/trevlars/GameSphere-Companion-Tool/releases/latest"><strong>⬇ Download latest release</strong></a>
  &nbsp;·&nbsp;
  <a href="docs/USER-GUIDE.md">User guide</a>
  &nbsp;·&nbsp;
  <a href="CHANGELOG.md">What's new</a>
  &nbsp;·&nbsp;
  <a href="https://testflight.apple.com/join/yPRfgBVj">GameSphere TestFlight</a>
</p>

<p align="center">
  <img src="assets/readme-screenshot.png" alt="GameSphere Companion Tool on Windows" width="720">
  <br>
  <sub><b>Windows</b> — download <code>GamesphereImportTool.exe</code>, run as administrator, click <b>Run importer</b>.</sub>
</p>

---

## What it does

| Area | What you get |
|------|----------------|
| **Library sync** | Scans Steam + Non-Steam shortcuts (emulators, ROMs, etc.). On Windows: Epic, GOG, Ubisoft, Battle.net, EA, Xbox / Game Pass. Writes Sunshine-style `apps.json`, downloads box art, keeps Desktop / Big Picture entries. |
| **Host bridge** | Always-on daemon on TCP **47998** (`gamesphere-host-bridge`). Handles JOINPIN, INVITE, JOINREQ/JOINACK, WANNAPLAY, PLAYREG/PLAYREPLY, HOSTINFO/PROFILE, COOPSTATE, SLOTSWAP, SESSIONDATA, WAN setup, and in-stream voice on UDP **48020**. |
| **Couch co-op** | P1–P4 seats from Sunshine x360 connect order + slot lock. Linux installer hides Steam Input clones (`28de:11ff`) via udev. |
| **WAN / invites** | UPnP/NAT-PMP port mapping when someone invites or a stream starts — never publishes Sunshine web UI **47990**. Optional ZeroTier and Tailscale hints for guests. |
| **Wanna play** | Friend pings, lock-screen push (optional APNs `.p8`), PLAYPENDING poll. |
| **Session telemetry** | Pause-on-lag, grades, playtime from local Steam `localconfig.vdf` (no Web API key). |
| **Host tuning** *(optional)* | Link speed, HDR/audio prep, NVIDIA snapshot, managed apps — off until you opt in. |

Built for [GameSphere](https://github.com/trevlars/GameSphere). Works with official Moonlight and other Moonlight-compatible clients for library sync; bridge features need GameSphere (or a host that speaks the same protocol — see [CLIENT_BRIDGE.md](docs/CLIENT_BRIDGE.md)).

---

## Who it's for

You run **Sunshine**, **Apollo**, **Vibeshine**, or **Vibepollo** on a Windows or Linux gaming PC (Steam Deck, Bazzite, desktop) and use **GameSphere** (or Moonlight for library-only) on Apple devices. You want one installer that sets up `apps.json` *and* the always-on host daemon — no hand-editing config or copying one-off scripts.

---

## Quick install

### Windows

1. [Download `GamesphereImportTool.exe`](https://github.com/trevlars/GameSphere-Companion-Tool/releases/latest).
2. **Right-click → Run as administrator** (writes under Program Files).
3. Pick **Sunshine** or **Apollo**, click **Run importer**.

The host daemon registers at logon automatically. Closing the wizard does not stop it. Opt out: `GAMESPHERE_ENABLE_HOST_BRIDGE=0` or `GamesphereImportTool.exe --host-daemon-uninstall`.

### Linux — Flatpak (recommended)

```bash
curl -fsSL https://github.com/trevlars/GameSphere-Companion-Tool/releases/latest/download/install-flatpak.sh | bash
flatpak run io.github.trevlars.GamesphereImportTool
```

### Linux — shell installer (git checkout, systemd, udev, Decky)

```bash
curl -fsSL https://github.com/trevlars/GameSphere-Companion-Tool/releases/latest/download/install-linux.sh | bash
```

### Linux — AppImage (portable, no daemon)

```bash
curl -fsSL https://github.com/trevlars/GameSphere-Companion-Tool/releases/latest/download/GameSphere-Import-Tool-x86_64.AppImage -O
chmod +x GameSphere-Import-Tool-x86_64.AppImage
./GameSphere-Import-Tool-x86_64.AppImage
```

Use Flatpak or the shell installer for the full stack (daemon, linger, auto-update timer).

### Steam Deck Game Mode

Install once with Flatpak or `install-linux.sh`, then enable the [Decky plugin](decky/README.md) to sync from Game Mode without a keyboard.

### macOS

Steam-only CLI from source — see [User guide → macOS](docs/USER-GUIDE.md#macos). `--host-daemon-install` writes a LaunchAgent.

---

## Host bridge and autostart

The **host daemon** is the always-on piece. The import GUI is only needed when your library changes.

| Platform | Default autostart | Check status |
|----------|-------------------|--------------|
| **Windows** | Task Scheduler + tray (`--host-daemon-install` on first run) | `GamesphereImportTool.exe --host-daemon-status` |
| **Linux** | `gamesphere-host-bridge.service` (user systemd + linger) | `systemctl --user status gamesphere-host-bridge.service` |
| **macOS** | LaunchAgent via `--host-daemon-install` | `gamesphere-import --host-daemon-status` |

Restart the **bridge only** after config changes — it never restarts Sunshine mid-stream:

```bash
systemctl --user restart gamesphere-host-bridge.service   # Linux
```

First-run checklist: [docs/USER-GUIDE.md#first-run-checklist](docs/USER-GUIDE.md#first-run-checklist). WAN detail: [docs/WAN.md](docs/WAN.md).

---

## Requirements

- **Streaming host:** [Sunshine](https://github.com/LizardByte/Sunshine) or [Apollo](https://github.com/ClassicOldSong/Apollo) (Vibeshine/Vibepollo auto-detected).
- **Steam** library with valid `libraryfolders.vdf` (Linux/macOS: Steam running or paths detectable).
- **Router:** UPnP or NAT-PMP enabled for WAN invites (Companion maps game ports per session).
- **GameSphere client:** [TestFlight](https://testflight.apple.com/join/yPRfgBVj) or App Store when available. Pair on LAN before WAN.
- **Optional:** SteamGridDB API key for missing art; APNs Auth Key (`.p8`) for lock-screen Wanna play — [APNS.md](docs/APNS.md).

You usually do **not** need a `.env` on a standard install.

---

## After install

| Step | Action |
|------|--------|
| First run | Import once; wait for host restart. Daemon keeps running after. |
| Client | Open GameSphere or Moonlight — games appear with art. Pair on LAN. |
| Co-op / WAN / voice | Leave the daemon running; you do not keep the import window open. |
| New games | Re-run import when you install something new. |
| Preview | **Dry run** in the GUI or `--dry-run` on CLI. |

**Updates:** [GitHub Releases](https://github.com/trevlars/GameSphere-Companion-Tool/releases/latest). Windows GUI checks on launch; Linux Flatpak/git installs use `gamesphere-import-update.timer`. Set `GAMESPHERE_AUTO_UPDATE=apply` to install without prompting, or `GAMESPHERE_AUTO_UPDATE=0` to disable.

---

## Ports (never 47990)

Companion maps these when Invite / Wanna play / a stream starts, then drops them after idle. Do **not** forward Sunshine web UI **47990**.

| Direction | Ports | Purpose |
|-----------|-------|---------|
| TCP | **47984**, **47989**, **48010**, **47998** | Pairing / RTSP / control / bridge |
| UDP | **47998–48000**, **48002**, **48010** | Moonlight media |
| UDP | **48020** | In-stream voice (session only) |
| Never | **47990** | Sunshine web UI (localhost only) |

---

## Optional extras

- **Host tuning** — [User guide](docs/USER-GUIDE.md#host-tuning-optional)
- **Mic to PC** — `--setup-mic` for Discord/OBS (separate from in-stream voice) — [MIC-TO-PC.md](docs/MIC-TO-PC.md)
- **Decky plugin** — [decky/README.md](decky/README.md)
- **APNs** — lock-screen Wanna play — [APNS.md](docs/APNS.md)

---

## For developers

**Embed sync, scheduled import, or bridge integration in your fork:**

[HOST_INTEGRATION.md](docs/HOST_INTEGRATION.md) · [CLIENT_BRIDGE.md](docs/CLIENT_BRIDGE.md) · [STREAMTWEAK_PARITY.md](docs/STREAMTWEAK_PARITY.md)

**Run from source** (Python 3.12+, [uv](https://docs.astral.sh/uv/)):

```bash
git clone https://github.com/trevlars/GameSphere-Companion-Tool.git
cd GameSphere-Companion-Tool
uv sync
uv run main.py --print-config          # detect paths
uv run main.py --dry-run               # preview import
uv run main.py --host-daemon-install   # install bridge autostart
uv run gui.py                          # Windows-style GUI (CustomTkinter)
```

CLI flags: [User guide → Command reference](docs/USER-GUIDE.md#command-reference). Health check: `uv run main.py --doctor`.

---

## Troubleshooting

| Problem | Try |
|---------|-----|
| Games missing in Moonlight | Re-run import. Windows: run as administrator. |
| Invite / JOINPIN dead after closing importer | `gamesphere-import --host-daemon-status` or `systemctl --user status gamesphere-host-bridge.service` |
| P2 pad steals P1 (Linux) | Confirm udev rule + `gamesphere-hide-steam-clones.sh` from installer |
| Exit on phone doesn't close PC game | Re-run import (quit helper, v1.0.2+) |

More: [User guide → Troubleshooting](docs/USER-GUIDE.md#troubleshooting)

---

## What's new

Latest: **v1.5.16** — display rename to GameSphere Companion Tool; stability fixes. Full history: [CHANGELOG.md](CHANGELOG.md).

---

## Acknowledgements and license

Fork of [Sunshine-App-Automation](https://github.com/CommonMugger/Sunshine-App-Automation) by [CommonMugger](https://github.com/CommonMugger). Multi-store discovery and host QOL patterns adapted from [StreamTweak](https://github.com/FoggyBytes/StreamTweak) (GPL-3.0, with attribution). StreamTweak-derived modules in `host_tuning/` and `store_scanners.py` are used under GPL-3.0.

Use at your own risk. Not affiliated with Valve, LizardByte, or Apollo. The tool backs up `apps.json` before writing.
