# User guide

Plain-language help for **GameSphere Companion Tool** (the import wizard plus the always-on host daemon). If you just want download links, start with the [README](../README.md).

---

## First-run checklist

Any Sunshine (or Apollo) PC. You do not SSH into a specific host, and you do not copy leftover helper scripts by hand.

1. **Download** the latest [release](https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest).
2. **Install**
   - Windows: `GamesphereImportTool.exe` → Run as administrator. Daemon registers at logon (`--host-daemon-install`).
   - Linux: `install-linux.sh` or `install-flatpak.sh` (not AppImage alone). Enables `gamesphere-host-bridge.service` + linger.
3. **Confirm the daemon** (leave it running; closing the importer is fine)
   - Linux: `systemctl --user status gamesphere-host-bridge.service`
   - Any: `gamesphere-import --host-daemon-status` or `GamesphereImportTool.exe --host-daemon-status`
   - Restart Companion only: `systemctl --user restart gamesphere-host-bridge.service` — **never** restart Sunshine to refresh the bridge.
4. **Import** once so `apps.json` has your library + artwork.
5. **Sunshine recommended config** (Companion writes this; applies on the next Sunshine restart, never mid-game): `gamepad = x360`, `upnp = disabled` (Companion maps ports instead), `origin_web_ui_allowed = pc`, opportunistic WAN encryption. **Never forward 47990.**
6. **Router:** turn on UPnP or NAT-PMP. Companion maps game ports when you Invite / Wanna play / start a stream, then unmaps after idle. STUN fills `wan=`.
7. **Host firewall** (installer tries this): TCP 47984, 47989, 48010, 47998; UDP 47998–48000, 48002, 48010, 48020. Never 47990. See [WAN.md](WAN.md).
8. **Pair GameSphere** on the LAN, then try Invite. Off-LAN: guest uses cellular; LAN `serverinfo` first, then `wan=`.
9. **Couch P2–P4:** join-order seats lock. Linux installer ships and enables udev + `gamesphere-hide-steam-clones.sh` so Steam Input `28de:11ff` clones do not steal pads. Host Swap (`SLOTSWAP`) is the only remap.
10. **Voice:** UDP 48020 mixes GameSphere mics only — no HDMI tap, no WebRTC AEC on Sunshine. Optional **Mic to PC** (VBAN 6980) is a separate Discord/OBS path — [MIC-TO-PC.md](MIC-TO-PC.md).
11. **Optional APNs:** drop `apns.p8` in the Companion config dir — [APNS.md](APNS.md). Wanna play poll still works without it.
12. **Sunshine web login** in `host_tuning.json` (`sunshine_username` / `sunshine_password`) so JOINPIN can post to localhost:47990. Status / WAN / logs never print that password.

Verbs the daemon serves: JOINPIN, INVITE, JOINREQ / JOINACK, WANNAPLAY, PLAYREG / PLAYPENDING / PLAYCLAIM / PLAYREPLY, HOSTINFO / PROFILE, COOPSTATE, SLOTSWAP, SESSIONDATA, WANSETUP, VOICE. Spec: [CLIENT_BRIDGE.md](CLIENT_BRIDGE.md).

---

## Windows

### Install

1. [Download `GamesphereImportTool.exe`](https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest) from Releases.
2. **Right-click → Run as administrator.**
3. In the app, pick **Sunshine** or **Apollo** (buttons at the top).
4. Click **Run importer**.

### First time tips

- Turn on **Dry run (preview only)** to see what would change without writing files.
- Paths are pre-filled for a normal Steam + Sunshine/Apollo install. Use **Browse…** only if yours is different.
- **Check for updates** in the app (also runs on launch) downloads a newer `.exe` when a release is available. Set `GAMESPHERE_AUTO_UPDATE=apply` to skip the prompt; `GAMESPHERE_AUTO_UPDATE=0` turns the check off.
- Closing the importer does **not** stop Companion. A hidden host daemon (`GamesphereImportTool.exe --host-daemon`) is registered at logon via Task Scheduler (restart on crash) plus HKCU Run. A tray icon stays in the notification area. This is the Windows host daemon — not a Windows Service (those need elevation and would not see your user Sunshine/Steam files).

Opt out: `GAMESPHERE_ENABLE_HOST_BRIDGE=0`, or `GamesphereImportTool.exe --host-daemon-uninstall`.

### Which host button?

| Button | When to use |
|--------|-------------|
| **Sunshine** | [LizardByte Sunshine](https://github.com/LizardByte/Sunshine) (default) |
| **Apollo** | [Apollo](https://github.com/ClassicOldSong/Apollo) — paths switch to Apollo config folders |

---

## Linux

### Flatpak (recommended)

One command installs from the GitHub release bundle:

```bash
curl -fsSL https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest/download/install-flatpak.sh | bash
```

That command also enables **`gamesphere-import-update.timer`** and the **`gamesphere-host-bridge`** user service (login/boot, restart on crash, journal logs). Downloading only the `.flatpak` bundle does not; use the install script for unattended updates and the always-on daemon.

Run the tool:

```bash
flatpak run io.github.trevlars.GamesphereImportTool          # import + restart Sunshine
flatpak run io.github.trevlars.GamesphereImportTool --dry-run   # preview only
```

If Flatpak asks for a runtime first:

```bash
flatpak install flathub org.freedesktop.Platform//24.08
```

### AppImage (portable)

Download, make executable, run — nothing installed system-wide:

```bash
curl -fsSL https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest/download/GameSphere-Import-Tool-x86_64.AppImage -O
chmod +x GameSphere-Import-Tool-x86_64.AppImage
./GameSphere-Import-Tool-x86_64.AppImage --dry-run
./GameSphere-Import-Tool-x86_64.AppImage
```

Move the file to `~/Applications` or `~/.local/bin` if you want it always handy.

### Shell installer (Decky, bridge, git checkout)

Creates `~/.local/bin/gamesphere-import` and a full source tree under `~/.local/share/gamesphere-import-tool`:

```bash
curl -fsSL https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest/download/install-linux.sh | bash
gamesphere-import --dry-run
gamesphere-import
```

The installer enables **`gamesphere-import-update.timer`** and **`gamesphere-host-bridge.service`** (and linger when needed) so later GitHub Releases apply without SSH and couch-coop / JOINPIN keep working after you close the terminal. Opt out: `GAMESPHERE_AUTO_UPDATE=0` and/or `GAMESPHERE_ENABLE_HOST_BRIDGE=0`.

Leave Companion running is no longer a chore — **it runs as a user service**. Check:

```bash
systemctl --user status gamesphere-host-bridge.service
journalctl --user -u gamesphere-host-bridge.service -e
```

### What Linux detects automatically

On typical SteamOS / Bazzite / desktop setups you should **not** need a `.env` file:

- Native or Flatpak Steam
- Sunshine or Apollo config (`apps.json`, covers folder)
- `systemctl --user restart sunshine` when that service exists

To see what was detected:

```bash
gamesphere-import --print-config
# or: flatpak run io.github.trevlars.GamesphereImportTool --print-config
```

---

## Steam Deck Game Mode (Decky)

Use the **DeckyLoader plugin** so you can sync from the quick menu without a keyboard.

1. Install the CLI first (Flatpak or `install-linux.sh` — see above).
2. Follow **[decky/README.md](../decky/README.md)** to enable the plugin.
3. In Game Mode: **Quick Access → GameSphere Import → Sync Steam library**.

The plugin supports dry run, skip restart, host tuning, and bridge toggle — same options as the CLI.

---

## macOS

macOS is **CLI only** (no GUI). Steam library import is supported; multi-store Windows scanners are not.

```bash
git clone https://github.com/trevlars/Gamesphere-Import-Tool.git
cd Gamesphere-Import-Tool
uv sync
uv run main.py --auto-config
uv run main.py --dry-run
uv run main.py
```

Requires [uv](https://github.com/astral-sh/uv) and Python 3.12+.

There is **no `.app` bundle**. Source checkouts can install a **LaunchAgent** so the host daemon stays up after Terminal quits:

```bash
uv run main.py --host-daemon-install
launchctl print "gui/$(id -u)/io.github.trevlars.gamesphere-host-bridge"
```

To pick up a new GitHub Release:

```bash
uv run main.py --apply-update
```

(`git pull` on your clone also works.) There is no unattended macOS GitHub timer.

---

## What happens when you import

| Step | What you get |
|------|----------------|
| **Discovery** | Steam games + Non-Steam shortcuts (+ Windows store libraries) |
| **Artwork** | Steam CDN thumbnails (optional SteamGridDB for picks) |
| **Merge** | Keeps Desktop, Big Picture, and your custom entries |
| **Launch fixes** | Correct detached Steam commands on Linux |
| **Quit App** | Closing the stream can end the game on the host |
| **Backup** | Previous `apps.json` copied before overwrite |
| **Restart** | Steam started if needed; Sunshine/Apollo restarted |

Re-running import is safe — it refreshes the list and fixes older launch/quit helpers.

---

## Mic to PC

Same button on every OS: **Set up mic for GameSphere** (Windows GUI) or `gamesphere-import --setup-mic`.

GameSphere sends the phone mic over VBAN (stream `GameSphere`, UDP `6980`). The Import Tool configures the PC receiver and shows your LAN IP — then you paste that IP in GameSphere → **Send mic to PC**.

- **Windows:** installs VB-CABLE (VB-Audio donationware; you accept the license) and starts a small OSS feeder into **CABLE Input**. Discord uses **CABLE Output**. No VoiceMeeter.
- **Linux:** PipeWire OSS VBAN module.

Full detail: **[MIC-TO-PC.md](MIC-TO-PC.md)**.

---

## Host tuning (optional)

Advanced host-side tweaks (link speed, HDR/audio prep, session logs, custom tiles). **Not required** for basic library sync.

```bash
gamesphere-import --host-tuning-only   # apply tuning without re-importing games
gamesphere-import --host-tuning          # import + tuning
gamesphere-import --host-bridge          # foreground host daemon (systemd/LaunchAgent use this)
gamesphere-import --host-daemon-status
gamesphere-import --host-daemon-install   # enable login/boot service (all OS)
uv run python3 host_tuning_cli.py wan    # Auto WAN map status (UPnP/NAT-PMP; never 47990)
uv run python3 host_tuning_cli.py coop   # P1–P4 slot status (never reshuffles live players)
```

The import GUI is optional. **Leave this running** is handled by the OS service — you do not keep a terminal or wizard window open.

WAN remote play (off-LAN friends): Companion auto-maps ports and fills `wan=` — [WAN.md](WAN.md). In-stream voice mixes phone mics on UDP 48020 and does **not** tap HDMI / does **not** attach WebRTC AEC to HDMI.

Wanna play (trusted friends already paired): host GameSphere Swap overlay sends `WANNAPLAY`. Companion pre-auths those UUIDs for **this stream only** so they skip Accept. CLI: `uv run python3 host_tuning_cli.py wanna start --app-name "Celeste"`. Lock-screen push: drop an APNs Auth Key on the host — [APNS.md](APNS.md). See [CLIENT_BRIDGE.md](CLIENT_BRIDGE.md).

Config file:

- Linux: `~/.config/gamesphere-import-tool/host_tuning.json`
- Windows: `%LOCALAPPDATA%\GameSphere\host_tuning.json`

Wanna-play lock-screen: APNs Auth Key `.p8` — [APNS.md](APNS.md).

Details: [HOST_INTEGRATION.md](HOST_INTEGRATION.md) · parity vs StreamTweak: [STREAMTWEAK_PARITY.md](STREAMTWEAK_PARITY.md)

---

## Configuration (optional)

Auto-detection covers most users. Override only when paths are unusual:

```bash
gamesphere-import --auto-config   # write a starter .env from detected paths
```

See [`.env.example`](../.env.example). Common overrides:

| Variable | When |
|----------|------|
| `HOST` | Use `apollo` instead of Sunshine |
| `STEAMGRIDDB_API_KEY` | Nicer cover art picks |
| `CUSTOM_GAMES_JSON_PATH` | Extra non-Steam executables |
| `XBOX_GAMES_FOLDERS` | Windows Xbox installs not under `C:\XboxGames` |

### Path cheat sheet

| Platform | apps.json (typical) |
|----------|---------------------|
| Linux native | `~/.config/sunshine/apps.json` |
| Linux Flatpak Sunshine | under `~/.var/app/dev.lizardbyte.app.Sunshine/…` |
| Windows Sunshine | `C:\Program Files\Sunshine\config\apps.json` |
| Windows Apollo | `C:\Program Files\Apollo\config\apps.json` |

---

## Updates

New versions come from [GitHub Releases](https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest). Testers do **not** need to `git pull`.

| Platform | How |
|----------|-----|
| **Windows GUI** | Checks on launch; **Check for updates** downloads the matching `.exe`. Set `GAMESPHERE_AUTO_UPDATE=apply` to skip the prompt. |
| **Linux** | `install-linux.sh` / `install-flatpak.sh` enable `gamesphere-import-update.timer` (linger when needed) so the newest release applies daily and ~5 minutes after boot. Manual: `gamesphere-import --apply-update`. |
| **macOS** | No `.app` timer. Source tree: `uv run main.py --apply-update`. |
| **AppImage** | Portable — no timer. `--apply-update`, or use Flatpak / `install-linux.sh`. |
| **Any** | Re-run `install-flatpak.sh` / `install-linux.sh`, or download the latest [release](https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest). |

Disable the Linux timer: `systemctl --user disable --now gamesphere-import-update.timer` or `GAMESPHERE_AUTO_UPDATE=0`.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Game tile in Moonlight but **won’t launch** (Linux) | Re-run import. Check Sunshine log for `Executing [Game Name]`. |
| Game runs but **Exit on client doesn’t close it** | Re-run import (installs `gamesphere-steam-close` helper). |
| **Permission denied** writing config (Windows) | Run `.exe` as administrator. |
| **Missing games** in the list | Some Steam VDF rows are redistributables, not games — warnings are normal. |
| **No box art** for one title | Steam CDN gap; add optional SteamGridDB key. |
| **Wrong paths** | `gamesphere-import --print-config`, then edit `.env` or open a GitHub issue. |
| **Flatpak can’t restart Sunshine** | Ensure `systemctl --user status sunshine` works; try native install or `--no-restart` then restart manually. |
| **Discord hears nothing (Windows mic)** | Discord input = **CABLE Output**. Re-run **Set up mic for GameSphere**. Reboot once after VB-CABLE install. |
| **Invite / WAN / JOINPIN dead** | Daemon must be up (`--host-daemon-status`). Router UPnP on. Never forward 47990. Restart the **bridge only**. |
| **Guest pad steals host / extra Xbox pads (Linux)** | Confirm udev `99-gamesphere-hide-steam-clones.rules` and `gamesphere-hide-steam-clones.sh`. Steam `28de:11ff` nodes should be mode 000. |

Log file (CLI): `sunshine_automation.log` in the working directory.

---

## Command reference

```bash
gamesphere-import                 # import + restart host
gamesphere-import --dry-run       # preview only
gamesphere-import --verbose       # more log detail
gamesphere-import --no-restart    # skip Steam start + host restart
gamesphere-import --remove-games  # reset to stock Desktop / Big Picture only
gamesphere-import --print-config  # show detected paths (JSON)
gamesphere-import --version
gamesphere-import --check-update
gamesphere-import --apply-update
gamesphere-import --host-tuning
gamesphere-import --host-tuning-only
gamesphere-import --host-bridge
gamesphere-import --host-daemon-install
gamesphere-import --host-daemon-status
gamesphere-import --host-daemon-uninstall
gamesphere-import --setup-mic-info
gamesphere-import --setup-mic                                    # Linux PipeWire
gamesphere-import --setup-mic --accept-vbaudio-license           # Windows VB-CABLE + feeder
```

From a git checkout, prefix with `uv run main.py` instead of `gamesphere-import`.
