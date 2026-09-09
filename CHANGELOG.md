# Changelog

All notable changes to GameSphere Import Tool are documented here.

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
