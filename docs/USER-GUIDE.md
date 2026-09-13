# User guide

Plain-language help for **GameSphere Import Tool**. If you just want download links, start with the [README](../README.md).

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

That command also enables **`gamesphere-import-update.timer`**. Downloading only the `.flatpak` bundle does not; use the install script for unattended updates.

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

The installer enables **`gamesphere-import-update.timer`** (and linger when needed) so later GitHub Releases apply without SSH. Opt out: `GAMESPHERE_AUTO_UPDATE=0`.

**Optional — GameSphere bridge on boot** (session stats / store badges for GameSphere clients):

```bash
GAMESPHERE_ENABLE_HOST_BRIDGE=1 curl -fsSL https://github.com/trevlars/Gamesphere-Import-Tool/releases/latest/download/install-linux.sh | bash
```

Check bridge status:

```bash
systemctl --user status gamesphere-host-bridge.service
```

### What Linux detects automatically

On typical Bazzite / SteamOS / desktop setups you should **not** need a `.env` file:

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

There is **no `.app` bundle and no launchd / calendar timer**. To pick up a new GitHub Release:

```bash
uv run main.py --apply-update
```

(`git pull` on your clone also works.) There is no unattended macOS timer.

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
- **Linux / Bazzite:** PipeWire OSS VBAN module.

Full detail: **[MIC-TO-PC.md](MIC-TO-PC.md)**.

---

## Host tuning (optional)

Advanced host-side tweaks (link speed, HDR/audio prep, session logs, custom tiles). **Not required** for basic library sync.

```bash
gamesphere-import --host-tuning-only   # apply tuning without re-importing games
gamesphere-import --host-tuning          # import + tuning
gamesphere-import --host-bridge          # TCP bridge on port 47998 (GameSphere clients)
```

Config file:

- Linux: `~/.config/gamesphere-import-tool/host_tuning.json`
- Windows: `%LOCALAPPDATA%\GameSphere\host_tuning.json`

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
gamesphere-import --setup-mic-info
gamesphere-import --setup-mic                                    # Linux PipeWire
gamesphere-import --setup-mic --accept-vbaudio-license           # Windows VB-CABLE + feeder
```

From a git checkout, prefix with `uv run main.py` instead of `gamesphere-import`.
