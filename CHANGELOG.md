# Changelog

All notable changes to GameSphere Import Tool are documented here.

## [1.2.4] — 2026-09-11

### Fixed
- **Flatpak `.flatpakref`** — manifest `branch: stable` and bundle export uses stable ref (one-step install)

## [1.2.3] — 2026-09-11

### Added
- **Flatpak bundle** — `io.github.trevlars.GamesphereImportTool.flatpak` + `GameSphere-Import-Tool.flatpakref` on every release (recommended Linux install on Bazzite / Deck)
- **AppImage** — `GameSphere-Import-Tool-x86_64.AppImage` portable CLI (download & run)
- **PyInstaller Linux CLI** — `build_cli.py` + `GamesphereImportTool-cli.spec`; CI job `build-linux-portable`

### Changed
- **GitHub Releases** — Linux assets: Flatpak, AppImage, `.flatpakref`, and `install-linux.sh` (shell installer demoted to advanced / Decky path)
- **README Quick Start** — Flatpak first, AppImage second, shell script third
- **`gs_updater`** — Linux `--apply-update` prefers Flatpak bundle, then AppImage, then shell installer

## [1.2.2] — 2026-09-11

### Added
- **DeckyLoader plugin v1.2.1** — status panel, import toggles (dry run, skip restart, host tuning, verbose), host tuning init/apply, GameSphere bridge systemd toggle, update checks, path refresh
- **`decky/test_backend.py`** — SSH/CI smoke test without Decky runtime
- Prebuilt **`decky/dist/`** in repo (no Node required on Deck/Bazzite)

### Fixed
- **`host_tuning_cli.py bridge`** — missing `import os`
- **`install-linux.sh`** — optional Decky plugin symlink (sudo when `~/homebrew/plugins` is root-owned on Bazzite)

### Changed
- **GitHub Releases CI** — every `v*` tag publishes `GamesphereImportTool.exe` + pinned `install-linux.sh`; README install URLs point at release assets

## [1.2.1] — 2026-09-11

### Added
- **Bridge verbs** — `APPSTORES` (store badges from `apps.json`), `GAMESTATE` (launch heuristic), `LOCKSTATE` (screen lock)
- **`docs/STREAMTWEAK_PARITY.md`** — explicit feature matrix vs StreamTweak
- **Host-agnostic integration docs** — expanded [HOST_INTEGRATION.md](docs/HOST_INTEGRATION.md) for Sunshine, Apollo, Vibeshine, Vibepollo, GameSphere, shortcuts/custom games, bridge embedding
- **`docs/CLIENT_BRIDGE.md`** — TCP 47998 wire protocol for Moonlight clients
- **`scripts/systemd/gamesphere-host-bridge.service`** — optional user service (`GAMESPHERE_ENABLE_HOST_BRIDGE=1` on install)

### Fixed
- **APPSTORES bridge verb** — class-bound lambda received `self` and returned `ERR`; provider now lives on the TCP server instance
- **`--host-bridge` apps.json path** — reads lowercase `sunshine_apps_json_path` from auto-detect / `.env`
- README — “Works with every Moonlight host” welcome section and integration quick links
- `platform_paths.py` — Vibeshine / Vibepollo config roots

## [1.2.0] — 2026-09-11

### Added
- **`host_tuning/` module** — StreamTweak-inspired host-side streaming tuning with Linux adaptations
- **Link-speed control** — wired adapter discovery + client `SETSPEED`/`RESTORE` via TCP bridge (Windows PowerShell; Linux `ethtool`)
- **HDR + spatial audio** — session prep hooks (Windows registry/device selection; Linux `wlr-randr` / PipeWire)
- **NVIDIA Sentinel (best-effort)** — driver snapshot to config dir (Profile Inspector `.nip` on Windows when installed; `nvidia-settings` dump on Linux)
- **Session telemetry** — Sunshine log tail → `sessions.json`, client `SESSIONDATA` grading (Excellent/Good/Poor)
- **TCP bridge** on port **47998** — `CAPS`, `NETINFO`, `SETSPEED`, `RESTORE`, `STATUS`, `STATS`, `TAILSCALE`, `LASTSESSION`, `SESSIONDATA`
- **Tailscale detection** — `tailscale ip -4` + interface scan
- **Managed apps** — kill on stream start, relaunch on end (configurable list in `host_tuning.json`)
- **Host tile replacement** — reversible swap of Sunshine `desktop.png` / `steam.png`
- **`gamesphere-host-prep.sh` / `.ps1`** — merged into every imported Steam app’s `prep-cmd` alongside Bazzite `sunshine-stream-prep.sh`
- **CLI**: `--host-tuning`, `--host-tuning-only`, `--host-bridge`, and `host_tuning_cli.py` subcommands

## [1.1.0] — 2026-09-11

### Added
- **Multi-store Windows discovery** — GOG, Ubisoft Connect, Battle.net, and EA App (patterns adapted from [StreamTweak](https://github.com/FoggyBytes/StreamTweak))
- **Store-native cover art** — Epic `catcache.bin`, GOG Galaxy SQLite cache, Ubisoft CDN, Battle.net `aggregate.json`, with Steam Store name search as portrait fallback (600px minimum height)
- **Epic launch triples** — `namespace:catalogItemId:appName` protocol URLs via Sunshine `detached` (fixes titles that cannot launch from exe alone)
- **Xbox / Game Pass improvements** — `.GamingRoot` discovery on all fixed drives; `explorer.exe shell:appsFolder\PackageFamily!AppId` when manifest metadata is available
- **Windows display-name fixup** — Uninstall-registry lookup for store titles with internal codenames
- **`store_scanners.py` / `store_covers.py`** — modular store logic with StreamTweak attribution in file headers and README

### Changed
- Epic and Xbox entries now carry `_gamesphere_store_key` / `_gamesphere_store` for reliable prune across re-imports

## [1.0.2] — 2026-09-09

### Added
- **In-app auto-update** — GUI checks GitHub Releases on launch (and via **Check for updates**) and can download the matching Windows `.exe` or Linux `install-linux.sh` without a token. CLI: `--version`, `--check-update`, `--apply-update`. Version is shown in the window title.

### Fixed
- **Quit App left slow-to-start Steam games running** (Hogwarts Legacy class) — `/cancel` often ran while the launcher / EAC / shader compile / splash was up and the real exe was not. Close undo now matches **AppID + install-dir path + distinctive exes**, keeps a short foreground watch instead of giving up on the first empty scan, and detaches a late-spawn watcher (~3 min) so the shipping process is still reaped. Windows hosts get the same prep-cmd undo via `gamesphere-steam-close.ps1`. Still 64-bit-safe; does not kill the Steam client, Sunshine/Apollo, or unrelated titles.

## [0.3.3] — 2026-09-08

### Fixed
- **Quit App still left emu/Non-Steam titles running on Bazzite Game Mode** — `gamesphere-steam-close.sh` used bash arithmetic on 64-bit `rungameid`s (overflow / no-op SteamAppId match) and killed Steam’s `reaper` before nested `bwrap`/RetroArch/Eden/Ryujinx. Undo now parses IDs in Python, matches `SteamAppId` / `SteamGameId` / `AppId=`, kills the process **tree children-first**, and retries so Steam cannot immediately relaunch. Does not touch Sunshine, Steam Big Picture, or the gamescope session.

## [0.3.2] — 2026-09-08

### Added
- **Non-Steam shortcuts** — reads Steam `userdata/*/config/shortcuts.vdf` (Eden / emu / other Non-Steam tiles) and imports them as Sunshine apps via `steam://rungameid/<64-bit id>`, with Quit App close undo and local Steam grid art when present

### Fixed
- **Quit App for Non-Steam shortcuts** — `gamesphere-steam-close.sh` accepts 64-bit rungameids and matches the 32-bit `SteamAppId` used in process environ

## [0.3.1] — 2026-09-08

### Fixed
- **Quit App leaves Steam game running on Linux/macOS** — detached `setsid steam steam://rungameid/…` launches are not tracked by Sunshine, so Moonlight/GameSphere `/cancel` only ran stream-prep undo and left the game open. Imported (and repaired) Steam apps now include a prep-cmd undo that terminates processes with matching `SteamAppId` / `SteamGameId` (helper script `gamesphere-steam-close.sh`, with inline bash fallback).

## [0.3.0] — 2026-09-03

### Added
- **Automagic path detection** on Linux, macOS, and Windows (`platform_paths.py`) — Steam VDF, Sunshine/Apollo `apps.json`, covers folder, Flatpak vs native, systemd vs exe restart
- **`--auto-config`** and **`--print-config`** CLI flags
- **`scripts/install-linux.sh`** one-liner for Bazzite, Steam Deck, and generic Linux
- **`gamesphere-import`** wrapper command after Linux install
- **DeckyLoader plugin scaffold** (`decky/`) for Game Mode import from Steam Deck / Bazzite
- **`docs/HOST_INTEGRATION.md`** — how Sunshine and Apollo can integrate this tool

### Fixed
- **Linux Steam launches** — games now use Sunshine’s required `detached` commands (not `cmd`); existing entries are repaired on re-import
- **Re-import duplicates** — Linux `steam steam://rungameid/…` commands are recognized correctly
- **Bazzite stream prep** — auto-adds `sunshine-stream-prep.sh` hooks to imported games when that script exists

### Changed
- Linux/macOS: start Steam and restart Sunshine/Apollo automatically (systemd, Flatpak, or exe)
- README rewritten around zero-config / automagic usage

## [0.2.0]

- Windows GUI, Apollo support, Epic (beta), Xbox/Game Pass discovery, custom games JSON, Remove all games

## [1.0.0] — upstream fork baseline

- Fork of [Sunshine-App-Automation](https://github.com/CommonMugger/Sunshine-App-Automation)
