# GameSphere Companion Tool

Formerly **GameSphere Import Tool**. Same GitHub repo and `gamesphere-import` command for now.

**Fill Sunshine or Apollo with your game library, then keep the host paired with GameSphere** — cover art, always-on host daemon, couch co-op pads, WAN invites, and in-stream voice.

No manual `apps.json` editing. Someone who is not the original author can download a release, install, and get the full stack.

<p align="center">
  <img src="assets/readme-screenshot.png" alt="GameSphere Companion Tool on Windows — pick Sunshine or Apollo and click Run importer" width="720">
  <br>
  <sub><b>Windows</b> — download the <code>.exe</code>, run as administrator, click <b>Run importer</b>.</sub>
</p>

<p align="center">
  <a href="https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest"><strong>⬇ Download latest release</strong></a>
  &nbsp;·&nbsp;
  <a href="docs/USER-GUIDE.md">Full user guide</a>
  &nbsp;·&nbsp;
  <a href="CHANGELOG.md">What's new</a>
</p>

---

## New Sunshine PC — from download to Invite

1. **Download** the latest [release](https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest).
2. **Install** (Windows `.exe` as administrator, or Linux `install-linux.sh` / Flatpak script below).
3. The **host daemon starts automatically** (`gamesphere-host-bridge`). Closing the importer does not stop it.
4. Companion writes recommended Sunshine settings (`gamepad = x360`, never publish **47990**, `upnp` / `wan_encryption` / `origin_web_ui_allowed`) and opens game ports via **UPnP / NAT-PMP** when someone invites or a stream starts. Turn **UPnP** on on the router once.
5. Run **import** once so Moonlight / GameSphere sees your library.
6. **Pair GameSphere** on the LAN, then **Invite / Wanna play / WAN** works. Couch P2–P4 seats lock in join order; Steam Input `28de:11ff` clones are hidden.

Checklist: **[User guide](docs/USER-GUIDE.md#first-run-checklist)**. WAN detail: **[WAN.md](docs/WAN.md)**.

You do **not** SSH into someone else’s PC. You do **not** copy host-specific one-off scripts.

---

## What it does

1. **Finds your games** — Steam library + Non-Steam shortcuts (emulators, etc.). On Windows it also scans Epic, GOG, Ubisoft, Battle.net, EA, and Xbox / Game Pass.
2. **Builds your streaming list** — Writes Sunshine-style `apps.json`, downloads box art, keeps your Desktop / Big Picture entries.
3. **Restarts the host** — Sunshine or Apollo reloads so Moonlight sees everything right away. Restarting the **Companion daemon** never restarts Sunshine.
4. **Always-on Companion** — JOINPIN, JOINREQ, WANNAPLAY, PLAYREG / PLAYREPLY, PROFILE / HOSTINFO, COOPSTATE, SLOTSWAP, SESSIONDATA pause, WAN `wan=`, voice UDP **48020**.
5. **Couch P1–P4** — Sunshine x360 connect-order + slot lock. Hides Steam Input clones (`28de:11ff`) via udev + helper **shipped and enabled by the installer**.
6. **Local playtime** — reads Steam `localconfig.vdf` + Non-Steam shortcut hours (no Web API key) and serves them over the host bridge (`PLAYTIMES`).

Built for [GameSphere](https://github.com/trevlars/GameSphere) and works with **official Moonlight** and other Moonlight-compatible clients.

---

## Install (pick your platform)

### Windows — easiest if you use a gaming PC as the host

1. Open **[Releases → Latest](https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest)** and download **`GamesphereImportTool.exe`**.
2. **Right-click → Run as administrator** (needed to write Sunshine/Apollo config under Program Files).
3. Choose **Sunshine** or **Apollo**, then click **Run importer**.

The app fills in paths automatically on a normal install. Use **Dry run** first if you want a preview without changing anything. On launch the GUI checks GitHub for a newer `GamesphereImportTool.exe` (**Check for updates**). Set `GAMESPHERE_AUTO_UPDATE=apply` to install without a prompt.

Closing the wizard does **not** stop Companion. A hidden **host daemon** (`--host-daemon`) registers at logon (Task Scheduler + tray) so JOINPIN / couch-coop / WAN / voice keep working. Same as `GamesphereImportTool.exe --host-daemon-install`.

Opt out: `GAMESPHERE_ENABLE_HOST_BRIDGE=0`, or `--host-daemon-uninstall`.

### Linux — Steam Deck (desktop), Bazzite, or any distro

<p align="center">
  <img src="assets/readme-linux-install.png" alt="Linux install options: Flatpak, AppImage, or Decky plugin" width="680">
</p>

**Recommended — one command (Flatpak):**

```bash
curl -fsSL https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest/download/install-flatpak.sh | bash
flatpak run io.github.trevlars.GamesphereImportTool
```

**Portable — AppImage (no install):**

```bash
curl -fsSL https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest/download/GameSphere-Import-Tool-x86_64.AppImage -O
chmod +x GameSphere-Import-Tool-x86_64.AppImage
./GameSphere-Import-Tool-x86_64.AppImage
```

AppImage does **not** enable the daemon or udev by itself — use the Flatpak or shell installer for the full stack.

<details>
<summary><strong>Shell installer</strong> — git checkout, host daemon, linger, udev, Decky</summary>

```bash
curl -fsSL https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest/download/install-linux.sh | bash
```

That enables:

- `gamesphere-host-bridge.service` (JOINPIN, couch coop, WAN, voice) — **default on**
- `loginctl enable-linger` so the daemon starts after reboot / Game Mode
- Steam clone udev rule + `gamesphere-hide-steam-clones.sh`
- Host firewall helper (never **47990**)
- Sunshine recommended conf on disk (applied on the **next** Sunshine restart — Companion never kills a live stream)

Opt out of the daemon: `GAMESPHERE_ENABLE_HOST_BRIDGE=0`.

**Steam Deck Game Mode:** see the [Decky plugin guide](decky/README.md).

</details>

### macOS

Steam-only CLI from source — see [User guide → macOS](docs/USER-GUIDE.md#macos). `--host-daemon-install` writes a LaunchAgent.

---

## After you install

| Step | What to do |
|------|------------|
| **First run** | Import once. Wait for “Done” / Sunshine restart. The host daemon keeps running after that. |
| **On your client** | Open Moonlight or GameSphere — your games should appear with art. Pair on LAN first. |
| **Couch coop / JOINPIN / WAN** | Leave Companion as the OS service — you do not keep the import window open. |
| **Router** | Enable UPnP or NAT-PMP. Companion maps game ports for the session only. |
| **New Steam games** | Run the tool again anytime you install something new. |
| **Preview only** | Turn on **Dry run** (Windows GUI) or add `--dry-run` on Linux. |

You usually **do not** need a `.env` file on a standard Sunshine install.

**Updates** happen from [GitHub Releases](https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest):

| Platform | How it stays current |
|----------|----------------------|
| **Windows** | The GUI checks GitHub on launch and via **Check for updates**. Set `GAMESPHERE_AUTO_UPDATE=apply` to install without a prompt. |
| **Linux** (Flatpak / git install) | New installs enable `gamesphere-import-update.timer` (daily + shortly after boot, including Game Mode via linger). |
| **macOS** | Source checkout: `uv run main.py --apply-update`. `--host-daemon-install` writes a LaunchAgent (no `.app` bundle). |
| **AppImage** | Portable — no timer. Use `--apply-update`, or the Flatpak / shell installer for unattended updates. |

Opt out: `GAMESPHERE_AUTO_UPDATE=0`.

---

## Ports (never 47990)

Companion maps these when Invite / Wanna play / a stream starts, then drops them after idle. Do **not** forward Sunshine web UI **47990**.

| Direction | Ports | Why |
|-----------|-------|-----|
| TCP | **47984**, **47989**, **48010**, **47998** | HTTPS pairing / RTSP / control / Companion JOINPIN |
| UDP | **47998–48000**, **48002**, **48010** | Moonlight video / audio / control |
| UDP | **48020** | In-stream voice mixer, **only while voice is running** |
| **Never** | **47990** | Sunshine web UI (localhost only) |

The installer tries to allow the same list on **firewalld / ufw** (Linux) or Windows Firewall. Voice mixes phone mics only — it does **not** tap HDMI / Sunshine audio and does **not** attach WebRTC AEC to HDMI.

Optional lock-screen Wanna play: drop an APNs Auth Key as `~/.config/gamesphere-import-tool/apns.p8` (Windows: `%LOCALAPPDATA%\GameSphere\apns.p8`). See [APNS.md](docs/APNS.md).

---

## Works with these streaming hosts

| Host | Supported |
|------|-----------|
| [Sunshine](https://github.com/LizardByte/Sunshine) | ✅ Native + Flatpak |
| [Apollo](https://github.com/ClassicOldSong/Apollo) | ✅ Choose Apollo in the Windows GUI or set `HOST=apollo` |
| Vibeshine / Vibepollo | ✅ Auto-detected paths |
| Your fork | ✅ Point `sunshine_apps_json_path` at your config |

Clients (GameSphere, Moonlight, etc.) do **not** need changes for library sync.

---

## Common questions

| Problem | Try this |
|---------|----------|
| **Games don’t show in Moonlight** | Run import again. On Windows, confirm you used **Run as administrator**. |
| **Game won’t launch from Moonlight (Linux)** | Re-run import — the tool fixes launch commands automatically. |
| **Exit on phone doesn’t close the game on PC** | Re-run import so the Quit App helper is installed (v1.0.2+). |
| **Invite / JOINPIN / WAN dead after closing the importer** | Confirm the daemon: `systemctl --user status gamesphere-host-bridge.service` or `--host-daemon-status`. |
| **P2 pad steals P1 / extra Xbox pads** | Steam Input clones — installer udev + hide helper. `ls -l /dev/input/js*` should show `28de:11ff` as mode `000`. |
| **Permission denied on Windows** | Run the `.exe` as administrator. |
| **Missing cover for one game** | Normal for some titles; optional [SteamGridDB](https://www.steamgriddb.com) key in settings. |
| **Something else** | [User guide → Troubleshooting](docs/USER-GUIDE.md#troubleshooting) |

---

## Optional extras (power users)

These are **off by default** except the host daemon (on by default).

- **Host tuning** — link speed, HDR/audio prep, session grades ([StreamTweak](https://github.com/FoggyBytes/StreamTweak)-inspired). See [user guide](docs/USER-GUIDE.md#host-tuning-optional).
- **Mic to PC** — one button / `--setup-mic`: Windows VB-CABLE + VBAN feeder (license prompt) or Linux PipeWire. Discord uses **CABLE Output**. Separate from in-stream voice on UDP 48020. See [MIC-TO-PC.md](docs/MIC-TO-PC.md).
- **DeckyLoader plugin** — sync from Steam Deck Game Mode. See [decky/README.md](decky/README.md).
- **APNs** — lock-screen Wanna play. Poll still works without a `.p8`. See [APNS.md](docs/APNS.md).

---

## For developers & host maintainers

Embedding a “Sync library” button, scheduled sync, or bridge in Sunshine / Apollo / your fork:

→ **[docs/HOST_INTEGRATION.md](docs/HOST_INTEGRATION.md)** · **[docs/CLIENT_BRIDGE.md](docs/CLIENT_BRIDGE.md)** · **[docs/STREAMTWEAK_PARITY.md](docs/STREAMTWEAK_PARITY.md)** · **[docs/WAN.md](docs/WAN.md)**

CLI reference and all flags: **[docs/USER-GUIDE.md → Command reference](docs/USER-GUIDE.md#command-reference)**

---

## What's new

Latest: **v1.5.15** — see [CHANGELOG.md](CHANGELOG.md). Flatpak, AppImage, and Windows `.exe` on every [release](https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest).

Full history: **[CHANGELOG.md](CHANGELOG.md)**

---

## Acknowledgements

Fork of [Sunshine-App-Automation](https://github.com/CommonMugger/Sunshine-App-Automation) by [CommonMugger](https://github.com/CommonMugger). Multi-store and host QOL patterns adapted from [StreamTweak](https://github.com/FoggyBytes/StreamTweak) (GPL-3.0).

---

## Legal

Use at your own risk. Not affiliated with Valve, LizardByte, or Apollo. The tool backs up `apps.json` before writing — keep that backup if you hand-edit the host config.
