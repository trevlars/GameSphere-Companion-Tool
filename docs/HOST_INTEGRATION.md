# Integrating GameSphere Import Tool into Sunshine or Apollo

This document is for **maintainers of game-streaming hosts** ([Sunshine](https://github.com/LizardByte/Sunshine), [Apollo](https://github.com/ClassicOldSong/Apollo), or forks) who want to give users a one-click way to populate `apps.json` from Steam.

GameSphere Import Tool is a **standalone CLI** today. It does not require changes to Sunshine/Apollo to work, but hosts can wrap it for a fully automagic experience.

---

## What the tool does (contract)

| Step | Behavior |
|------|----------|
| Discover | Reads Steam `libraryfolders.vdf` + `userdata/*/config/shortcuts.vdf` Non-Steam tiles (+ Windows Epic/Xbox/custom sources) |
| Artwork | Downloads box art from Steam CDN (optional SteamGridDB API key) |
| Merge | Updates host `apps.json` — adds new games, removes uninstalled Steam/Epic titles |
| Preserve | Keeps existing non-Steam apps (Desktop, custom `prep-cmd`, etc.) on normal import |
| Launch format | Windows: `cmd` with `steam://rungameid/…` · Linux/macOS: **`detached`** array per [Sunshine app examples](https://docs.lizardbyte.dev/projects/sunshine/latest/md_docs_2app__examples.html) |
| Restart | Restarts the host when done (Windows exe, Linux `systemctl --user restart sunshine`, Flatpak restart) |

Paths are **auto-detected** when `.env` is missing — see `platform_paths.py`.

---

## Integration patterns (pick one or combine)

### 1. Web UI button — “Sync Steam library” (recommended)

Add a button in the host web UI that runs the importer as a subprocess and streams log output to the page.

```bash
# Linux / macOS (after install-linux.sh or uv sync)
gamesphere-import --dry-run   # optional preview
gamesphere-import

# Or without wrapper
cd ~/.local/share/gamesphere-import-tool && uv run main.py
```

**Backend sketch (C++ host calling shell):**

```cpp
// Pseudocode — run off the UI thread; capture stdout/stderr for the log panel
std::system("gamesphere-import --no-restart 2>&1 | tee /tmp/gamesphere-import.log");
// Then reload apps or restart sunshine from the host's own service manager
```

**Flags hosts may want:**

| Flag | Use when |
|------|----------|
| *(none)* | Full import + restart host |
| `--dry-run` | Preview only — safe for “what would change?” UI |
| `--no-restart` | Host reloads `apps.json` itself without process restart |
| `--verbose` | Show detailed logs in UI |

Exit code `0` = success. Parse stdout for `BANNER:` lines for user-friendly status text.

---

### 2. First-run / setup wizard

On first pairing or first web UI visit:

1. Check if Steam VDF exists (`platform_paths.detect_paths()` or `--print-config`).
2. If yes, offer **“Import my Steam games”** with one click.
3. Run `--auto-config` once, then import.

Python (embed in a host installer script):

```python
from platform_paths import detect_paths, write_env_file

paths = detect_paths()
if paths:
    write_env_file(paths)
    # subprocess: uv run main.py
```

---

### 3. Scheduled sync (set and forget)

Steam installs/uninstalls while the host keeps running. A timer keeps `apps.json` fresh:

**systemd user timer (Linux):**

```ini
# ~/.config/systemd/user/gamesphere-import.timer
[Unit]
Description=Sync Steam library into Sunshine apps.json

[Timer]
OnBootSec=5min
OnUnitActiveSec=6h

[Install]
WantedBy=timers.target.default
```

```ini
# ~/.config/systemd/user/gamesphere-import.service
[Unit]
Description=GameSphere Import Tool

[Service]
Type=oneshot
ExecStart=%h/.local/bin/gamesphere-import
```

```bash
systemctl --user enable --now gamesphere-import.timer
```

**Windows Task Scheduler:** run `GamesphereImportTool.exe` or `uv run main.py` daily after login.

---

### 4. Package / image bundling

**Linux (Bazzite, Deck, immutable distros):**

- Ship `scripts/install-linux.sh` in post-install or first-boot.
- Or add to distro package list: `gamesphere-import-tool` that installs to `/usr/share/gamesphere-import-tool` and `/usr/bin/gamesphere-import`.

**Windows installer:**

- Bundle `GamesphereImportTool.exe` from [GitHub Releases](https://github.com/trevlars/Gamesphere-Import-Tool/releases).
- Default paths in GUI already track Sunshine vs Apollo install locations.

---

### 5. DeckyLoader / Game Mode (Steam Deck, Bazzite + Decky)

Ship or link the plugin in `decky/`:

```bash
ln -sfn ~/.local/share/gamesphere-import-tool/decky ~/homebrew/plugins/gamesphere-import
# build frontend: cd decky && pnpm install && pnpm run build
```

The plugin shells out to `gamesphere-import` — same contract as the web UI button.

---

### 6. Import as a Python module (advanced)

Hosts written in Python (or with embedded Python) can import detection directly:

```python
from platform_paths import apply_detected_paths, detect_paths
from main import validate_config  # after apply_detected_paths()

apply_detected_paths()
config = validate_config(auto_detect=True)
# … call internal import routines or subprocess main.py
```

Keep the CLI as the stable public interface; module imports are for tight integration only.

---

## Environment variables hosts can set

Hosts may pre-set these before invoking the tool (optional — auto-detect fills gaps):

| Variable | Purpose |
|----------|---------|
| `HOST` | `sunshine` or `apollo` (stock app templates) |
| `steam_library_vdf_path` | Override Steam library file |
| `sunshine_apps_json_path` | Override `apps.json` path |
| `sunshine_grids_folder` | Cover art output directory |
| `STEAMGRIDDB_API_KEY` | Optional community artwork |
| `GAMESPHERE_STEAM_MODE` | `native`, `flatpak`, `windows`, `macos` (usually auto) |
| `GAMESPHERE_SUNSHINE_RESTART` | `systemd`, `flatpak`, or `exe` (usually auto) |

Run `gamesphere-import --print-config` on the target machine to dump detected values as JSON.

---

## Apollo-specific notes

- Set `HOST=apollo` in `.env` or environment before import (GUI host selector does this on Windows).
- Stock reset (`--remove-games`) restores Desktop, Steam Big Picture, and **Virtual Display** for Apollo.
- Default Apollo paths mirror Sunshine; adjust `sunshine_apps_json_path` if Apollo uses a different config root.

---

## Sunshine-specific notes

- **Do not overwrite** user `apps.json` wholesale — the tool merges. Document that `--remove-games` is destructive.
- Linux games **must** use `detached` for Steam URIs; the tool handles this automatically since v0.3.0.
- Detached Steam games are **not** killed by Sunshine’s process tracker. Since v0.3.1 each Steam app gets a prep-cmd **undo** (`gamesphere-steam-close.sh <appid>` / Windows `.ps1`, or inline equivalent) so client Quit App (`/cancel`) closes the game on the host. v1.0.2+ also matches the game install dir / distinctive exes and watches for late-spawned processes (long Steam launches).
- The tool can self-update from public GitHub Releases (no token): GUI **Check for updates**, or `gamesphere-import --check-update` / `--apply-update`.
- If the host ships custom `prep-cmd` (e.g. display/audio prep scripts), normal import preserves existing Desktop / Big Picture entries; new games can inherit host-specific prep when detected (e.g. `~/.local/bin/sunshine-stream-prep.sh` on Bazzite).

---

## Suggested host UI copy

> **Sync Steam games**  
> Adds your installed Steam titles to this app list with cover art. Safe to run again after installing or removing games. Existing desktop and launcher entries are kept.

Link to: `https://github.com/trevlars/Gamesphere-Import-Tool#quick-start`

---

## Support / issues

- Tool bugs: [Gamesphere-Import-Tool issues](https://github.com/trevlars/Gamesphere-Import-Tool/issues)
- Sunshine: [LizardByte/Sunshine](https://github.com/LizardByte/Sunshine)
- Apollo: [ClassicOldSong/Apollo](https://github.com/ClassicOldSong/Apollo)
- GameSphere client (Moonlight shelf): [trevlars/GameSphere](https://github.com/trevlars/GameSphere)
