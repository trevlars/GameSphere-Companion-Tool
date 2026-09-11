# Integrating GameSphere Import Tool into any Moonlight host

This document is for **maintainers of game-streaming hosts and clients** — [Sunshine](https://github.com/LizardByte/Sunshine), [Apollo](https://github.com/ClassicOldSong/Apollo), Vibeshine, Vibepollo, [GameSphere](https://github.com/trevlars/GameSphere), Decky plugins, distro images, or your own fork.

GameSphere Import Tool is a **standalone CLI** today. It does not require changes to your host to work, but wrapping it gives users a one-click “Sync my library” experience and optional StreamTweak-style host tuning.

**Related docs**

- [README](../README.md) — quick start for end users  
- [STREAMTWEAK_PARITY.md](STREAMTWEAK_PARITY.md) — feature matrix vs [StreamTweak](https://github.com/FoggyBytes/StreamTweak)

---

## Supported hosts (auto-detected paths)

| Host | `HOST` env | Typical `apps.json` (Linux) | Typical `apps.json` (Windows) |
|------|------------|-----------------------------|-------------------------------|
| Sunshine | `sunshine` (default) | `~/.config/sunshine/apps.json` | `C:/Program Files/Sunshine/config/apps.json` |
| Apollo | `apollo` | `~/.config/Apollo/apps.json` | `C:/Program Files/Apollo/config/apps.json` |
| Vibeshine | auto from path | `~/.config/vibeshine/apps.json` | `C:/Program Files/Vibeshine/config/apps.json` |
| Vibepollo | auto from path | `~/.config/vibepollo/apps.json` | `C:/Program Files/Vibepollo/config/apps.json` |
| Flatpak Sunshine | `sunshine` | `~/.var/app/dev.lizardbyte.app.Sunshine/.../apps.json` | — |
| **Custom fork** | set manually | override `sunshine_apps_json_path` in `.env` | same |

Detection logic lives in `platform_paths.py`. **PRs welcome** to add your config root — one line in the candidate list is usually enough.

```bash
gamesphere-import --print-config   # JSON dump of detected paths on this machine
```

---

## What the tool does (stable contract)

| Step | Behavior |
|------|----------|
| Discover | Steam `libraryfolders.vdf` + `userdata/*/config/shortcuts.vdf` Non-Steam tiles (+ Windows Epic/GOG/Ubisoft/Battle.net/EA/Xbox/custom sources) |
| Artwork | Steam CDN + store-native caches (Epic, GOG, …) + optional [SteamGridDB](https://www.steamgriddb.com/profile/preferences/api) |
| Merge | Updates host `apps.json` — adds new games, removes uninstalled titles |
| Preserve | Keeps Desktop, Big Picture, Virtual Display (Apollo), custom `prep-cmd`, hand-edited entries |
| Launch format | Windows: `cmd` + `steam://rungameid/…` · Linux/macOS: **`detached`** array per [Sunshine app examples](https://docs.lizardbyte.dev/projects/sunshine/latest/md_docs_2app__examples.html) |
| Quit App | Prep-cmd **undo** closes detached Steam / Non-Steam games when the client sends `/cancel` |
| Restart | Restarts the host when done (Windows exe, Linux `systemctl --user restart sunshine`, Flatpak restart) |
| Metadata | Each imported entry may include `_gamesphere_store` / `_gamesphere_store_key` for prune + bridge `APPSTORES` |

Paths are **auto-detected** when `.env` is missing.

---

## Non-Steam shortcuts & custom games

### Steam `shortcuts.vdf` (Eden, Ryujinx, emulators, …)

The importer reads:

```
Steam/userdata/<steamid>/config/shortcuts.vdf
```

Every Non-Steam shortcut becomes a host app with:

- Launch: `steam://rungameid/<64-bit id>` (Windows `cmd`, Linux `detached` + `setsid steam …`)
- Cover: local Steam grid art when present, else CDN / SteamGridDB
- Quit App undo: `gamesphere-steam-close` matches 64-bit IDs and install paths

**Host integration tip:** document that users who add shortcuts in Steam Desktop Mode get them on the next sync — no duplicate manual `apps.json` editing.

### `custom_games.json` (Windows executables, scripts, `.lnk`)

For titles outside Steam’s shortcut system, ship or point users at `custom_games.example.json`:

```json
[
  {
    "name": "My Emulator",
    "cmd": "C:\\Games\\emu\\launch.bat",
    "image-path": "optional-local.png"
  }
]
```

Set `CUSTOM_GAMES_JSON_PATH` in `.env` or pass via `--auto-config`. Entries merge like Steam games and survive re-import.

### Bazzite / stream prep hooks

When `~/.local/bin/sunshine-stream-prep.sh` exists, imported Steam apps inherit those prep commands **in addition to** `gamesphere-host-prep.sh` (host tuning). Hosts that ship their own prep scripts should document ordering: global prep → per-game prep → undo on Quit App.

---

## Integration patterns (pick one or combine)

### 1. Web UI button — “Sync Steam library” (recommended)

Add a button in the host web UI that runs the importer as a subprocess and streams log output to the page.

```bash
gamesphere-import --dry-run   # optional preview
gamesphere-import             # full import + restart
```

**Backend sketch (run off UI thread):**

```cpp
// Pseudocode — capture stdout/stderr for the log panel
std::system("gamesphere-import --no-restart 2>&1 | tee /tmp/gamesphere-import.log");
// Host reloads apps.json or restarts its own service
```

| Flag | Use when |
|------|----------|
| *(none)* | Full import + restart host |
| `--dry-run` | Preview only — safe for “what would change?” UI |
| `--no-restart` | Host reloads `apps.json` itself |
| `--verbose` | Detailed logs in UI |
| `--host-tuning` | Import + apply tiles / NVIDIA snapshot / prep scripts |
| `--host-bridge` | Background TCP bridge + session monitor (usually separate service) |

Exit code `0` = success. Parse stdout for `BANNER:` lines for user-friendly status.

---

### 2. First-run / setup wizard

On first pairing or first web UI visit:

1. Run `gamesphere-import --print-config`.
2. If Steam VDF exists, offer **“Import my Steam library”**.
3. Run `--auto-config` once, then import.

```python
from platform_paths import detect_paths, write_env_file

paths = detect_paths()
if paths:
    write_env_file(paths)
    # subprocess: gamesphere-import
```

---

### 3. Scheduled sync (set and forget)

Steam installs/uninstalls while the host keeps running. A timer keeps `apps.json` fresh.

**systemd user timer (Linux — works for Sunshine, Apollo, most forks):**

```ini
# ~/.config/systemd/user/gamesphere-import.timer
[Unit]
Description=Sync Steam library into host apps.json

[Timer]
OnBootSec=5min
OnUnitActiveSec=6h

[Install]
WantedBy=timers.target
```

```ini
# ~/.config/systemd/user/gamesphere-import.service
[Unit]
Description=GameSphere Import Tool

[Service]
Type=oneshot
ExecStart=%h/.local/bin/gamesphere-import
Environment=HOST=apollo
```

```bash
systemctl --user enable --now gamesphere-import.timer
```

Change `Environment=HOST=` for Apollo vs Sunshine. Override paths with `EnvironmentFile=%h/.config/gamesphere-import-tool/.env` if needed.

**Windows Task Scheduler:** run `GamesphereImportTool.exe` or `uv run main.py` daily after login.

---

### 4. Package / image bundling

**Linux (Bazzite, Deck, immutable distros):**

```bash
curl -fsSL https://raw.githubusercontent.com/trevlars/Gamesphere-Import-Tool/main/scripts/install-linux.sh | bash
```

Ship that one-liner in post-install, first-boot, or add a distro package that installs `/usr/bin/gamesphere-import`.

**Windows installer:**

Bundle `GamesphereImportTool.exe` from [GitHub Releases](https://github.com/trevlars/Gamesphere-Import-Tool/releases). GUI host selector sets `HOST=sunshine|apollo`.

---

### 5. DeckyLoader / Game Mode (Steam Deck, Bazzite + Decky)

```bash
ln -sfn ~/.local/share/gamesphere-import-tool/decky ~/homebrew/plugins/gamesphere-import
cd ~/.local/share/gamesphere-import-tool/decky && pnpm install && pnpm run build
```

Same subprocess contract as the web UI button — see [`decky/README.md`](../decky/README.md).

---

### 6. Import as a Python module (advanced)

```python
from platform_paths import apply_detected_paths, detect_paths
from main import validate_config

apply_detected_paths()
config = validate_config(auto_detect=True)
# subprocess main.py is still the stable public API
```

---

## Host tuning & TCP bridge (optional)

Adapted from [StreamTweak](https://github.com/FoggyBytes/StreamTweak). See [STREAMTWEAK_PARITY.md](STREAMTWEAK_PARITY.md) for the full matrix.

### When to embed

| Use case | Integration |
|----------|-------------|
| Link-speed match (wired LAN) | Run `--host-bridge`; client sends `NETINFO` / `SETSPEED` |
| Session quality grades | Client sends `SESSIONDATA` during stream; host stores `sessions.json` |
| Store badges in client UI | Client sends `APPSTORES` or reads from bridge |
| Kill Hue Sync / RGB on stream start | `host_tuning.json` → `managed_apps` + prep hooks |

### Prep scripts (merged into every imported Steam app)

After `host_tuning_cli.py init --enable-all` or `install-linux.sh`:

```bash
~/.local/bin/gamesphere-host-prep.sh start   # session start
~/.local/bin/gamesphere-host-prep.sh stop    # session end
```

Hosts that already use prep-cmd (Sunshine examples, Bazzite `sunshine-stream-prep.sh`) can **append** these instead of replacing user entries — the importer merges prep arrays.

### TCP bridge (port 47998)

```bash
gamesphere-import --host-bridge
# or: uv run host_tuning_cli.py bridge
```

| Verb | Direction | Purpose |
|------|-----------|---------|
| `CAPS` | host → client | Supported verbs |
| `NETINFO` | client → host | Wired adapter + current link speed |
| `SETSPEED` | client → host | Match client link speed |
| `RESTORE` | client → host | Restore adapter defaults |
| `STATUS` | either | Health ping |
| `STATS` | client → host | Append telemetry sample |
| `SESSIONDATA` | client → host | Bitrate, loss, grade inputs |
| `LASTSESSION` | client → host | Previous session summary |
| `TAILSCALE` | client → host | Tailscale IPv4 if present |
| `APPSTORES` | client → host | Map app name → store id from `apps.json` |
| `GAMESTATE` | client → host | Launch / running heuristic |
| `LOCKSTATE` | client → host | Screen lock detection |

**Client implementers:** connect to `<host-ip>:47998`, one verb per line, JSON payload after a blank line when required. Match StreamTweak wire format where possible so one client implementation serves multiple hosts. Full spec: [CLIENT_BRIDGE.md](CLIENT_BRIDGE.md).

Config file:

- Windows: `%LOCALAPPDATA%\GameSphere\host_tuning.json`
- Linux: `~/.config/gamesphere-import-tool/host_tuning.json`

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `HOST` | `sunshine`, `apollo`, or inferred from `apps.json` path |
| `steam_library_vdf_path` | Override Steam library file |
| `sunshine_apps_json_path` | Override host `apps.json` |
| `sunshine_grids_folder` | Cover art output directory |
| `STEAMGRIDDB_API_KEY` | Optional community artwork |
| `CUSTOM_GAMES_JSON_PATH` | Extra non-Steam executables |
| `GAMESPHERE_STEAM_MODE` | `native`, `flatpak`, `windows`, `macos` (usually auto) |
| `GAMESPHERE_SUNSHINE_RESTART` | `systemd`, `flatpak`, or `exe` (usually auto) |
| `XBOX_GAMES_FOLDERS` | Extra Xbox install roots (Windows) |

---

## Per-host notes

### Sunshine

- Linux games **must** use `detached` for Steam URIs — handled automatically since v0.3.0.
- `--remove-games` is destructive; normal import merges.
- Document that Quit App requires prep-cmd undo (included for all imported Steam / shortcut apps).

### Apollo

- Set `HOST=apollo` before import (GUI selector on Windows).
- Stock reset keeps **Virtual Display** in addition to Desktop and Big Picture.
- Same `apps.json` schema as Sunshine.

### Vibeshine / Vibepollo

- Paths auto-detected under `~/.config/vibeshine` and `~/.config/vibepollo`.
- Session log parsing includes Vibeshine/Vibepollo session UUID lines when present.
- If your fork uses a different log path, set `sunshine_log_path` in `host_tuning.json`.

### GameSphere client

- Library sync is host-side ([Import Tool](https://github.com/trevlars/Gamesphere-Import-Tool)). GameSphere implements the bridge client in `GSHostCompanionBridge` / `GSHostStoreCatalog`:
  - **`APPSTORES`** — store labels for IGDB platform hints (Steam, Epic, GOG, …)
  - **`SESSIONDATA`** — telemetry every 15 s during a stream → host session grades
  - **`RESTORE`** — link-speed restore on stream exit (when bridge is active)
- Wire protocol: [CLIENT_BRIDGE.md](CLIENT_BRIDGE.md)
- Pairing / PIN unlock: host exposes `LOCKSTATE`; client sends unlock PIN over the stream (StreamTweak pattern — future GameSphere UI).

### Custom forks

1. Add your `apps.json` path to `platform_paths.py` (PR welcome).
2. Document restart command (`systemctl`, custom binary, Flatpak).
3. If logs differ, contribute a line prefix to `session_telemetry.py`.

---

## Suggested host UI copy

> **Sync game library**  
> Adds your installed Steam titles (and Non-Steam shortcuts) to this app list with cover art. Safe to run again after installing or removing games. Desktop, Big Picture, and your custom entries are kept.

Link: `https://github.com/trevlars/Gamesphere-Import-Tool#quick-start`

Optional second button:

> **Advanced: host tuning**  
> Optional link-speed matching, session stats, and background app management. Requires GameSphere Import Tool 1.2+ and a compatible Moonlight client.

---

## Contributing integration back upstream

We want this tool **in every streaming stack**. Useful PRs:

- New host path candidates in `platform_paths.py`
- Log line patterns for session detection
- Bridge verbs your client needs (with JSON schema)
- Packaged install for your distro (Bazzite, ChimeraOS, …)
- Link from your host README to this doc

**Tool bugs:** [Gamesphere-Import-Tool issues](https://github.com/trevlars/Gamesphere-Import-Tool/issues)  
**Sunshine:** [LizardByte/Sunshine](https://github.com/LizardByte/Sunshine)  
**Apollo:** [ClassicOldSong/Apollo](https://github.com/ClassicOldSong/Apollo)  
**GameSphere client:** [trevlars/GameSphere](https://github.com/trevlars/GameSphere)
