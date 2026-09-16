# Changelog

All notable changes to GameSphere Companion Tool (formerly Import Tool) are documented here.

## [Unreleased]

## [1.5.0] — 2026-09-16

### Added
- **Bridge verbs** — `LAUNCHRESULT` (rich launch status for phone UI), `INPUTRELAY` (buddy merge flag), `COOPKICK`, `SESSIONEND`, `BUDDYSET` (seat role + UDP 48021 buddy relay).
- **`--setup` / `--doctor`** — idempotent first-run repair + JSON health report (Sunshine, Steam, bridge 47998, mic, WAN, ZeroTier LAN guard, owned Steam apps + ROM hashes).
- **ZeroTier guard** — detects `zerotierHost` for HOSTINFO/COOPSTATE; removes home-LAN routes stolen by `zt*` (never kills Sunshine).
- **Metadata catalog** — background Steam owned-apps + ROM MD5 scan surfaced on HOSTINFO as `ownedApps` / `romHashes` / `catalogReady`.
- **Co-op session events** — kick + session-end broadcast on COOPSTATE for guest polling.

### Changed
- HOSTINFO and COOPSTATE include `zerotierHost`, catalog fields, input-relay state, buddy relay port, and session events.
- Launch watcher tracks attempts/timeouts for clearer `LAUNCHRESULT` messages.

## [1.4.4] — 2026-09-16

### Added
- **Steam clone hide helper + udev** — `gamesphere-hide-steam-clones.sh` and `99-gamesphere-hide-steam-clones.rules` are **shipped and enabled by the installer** (not a leftover host-specific script). Steam Input `28de:11ff` clones are hidden from SDL; Sunshine `045e:02ea` pads stay P1–P4.
- **Host firewall helper** — TCP 47984/47989/48010/47998 and UDP 47998–48000/48002/48010/48020 (never 47990) via firewalld/ufw/Windows Firewall.
- **Sunshine recommended conf** now includes `gamepad = x360` plus WAN-safe `upnp` / `origin_web_ui_allowed` / `wan_encryption` (still never restarts Sunshine mid-game).
- **PLAYREPLY echo** — guest I'm in / You're going down / Can't right now is accepted on TCP 47998 and attached to `COOPSTATE` as `coopChat[]` / `playReplies[]` / `playReply` (last 8, TTL ~30s) so P1 sees bubbles.
- Product branding on GitHub Releases: **GameSphere Companion Tool** (repo/binary IDs unchanged).

### Changed
- Couch co-op is generic Sunshine x360 + Companion slot lock. Host-specific pad/mic scripts are not part of Companion.
- **Always-on host daemon** — Companion stays running as `gamesphere-host-bridge` so JOINPIN, TRUSTED/JOINREQ, couch-coop slots, WAN UPnP, voice UDP 48020, and WANNAPLAY survive closing the import GUI. Linux: systemd user service + linger (default on). Windows: Task Scheduler logon task (hidden, restart on failure) + HKCU Run fallback + tray. macOS source checkouts: LaunchAgent. Restarting the bridge never restarts Sunshine. Opt out: `GAMESPHERE_ENABLE_HOST_BRIDGE=0`.
- **Automagic WAN** — Companion maps Sunshine + JOINPIN ports via UPnP/NAT-PMP/PCP on invite, Wanna play, and stream start; STUN fills `wan=`; unmaps after idle. Never maps 47990. `WANSETUP` / `wan` is one status sentence (enable router UPnP if mapping fails), not a port-forward checklist. Sunshine `upnp=disabled` + `origin_web_ui_allowed=pc` written without restarting a live session.
- **Wanna-play APNs** — Companion sends lock-screen Apple Push from the host daemon (token auth `.p8`, not Firebase / not ASC upload keys). `PLAYREG` stores `apnsToken` + sandbox vs production. No `.p8` → poll still works; `pushStatus` is one sentence. See [APNS.md](docs/APNS.md).

## [1.4.3] — 2026-09-14

### Fixed
- **P1–P4 slot stability** — join-order seats are locked. Pad blips, Steam `28de:11ff` clones, and the watcher no longer reshuffle two live players. Host Swap (`SLOTSWAP`) is the only remap.

### Added
- **COOPSTATE / auto-pause** — when 2–4 GameSphere clients are in one Sunshine session and any connection is dropping frames, the host is told to pause (Start/Menu). Hysteresis + cooldown so hitches don’t pause-loop. Guests get no Resume/Quit chrome.
- **HOSTINFO** — host SteamID + persona + avatar URL for guest “playing with” chrome.
- **WAN remote play** — invite URLs carry `host=` + `lan=` + `wan=`. `host_tuning_cli.py wan` / `WANSETUP` prints ports, firewall, hairpin notes. TCP 47984/47989/48010/47998; UDP 47998–48000, 48002, 48010; voice UDP 48020. Never 47990.
- **In-stream voice mixer** — UDP PCM on 48020. Mixes phone mics only (no HDMI tap / no WebRTC AEC on Sunshine).
- **Four players** — slots 0–3, JOINACK per guest, frame-drop pause if any client is unhealthy.
- **Wanna play session pre-auth** — `WANNAPLAY` / `PLAYREG` / `PLAYPENDING` / `PLAYCLAIM`. Pinged TRUSTED UUIDs auto-JOINACK for this Sunshine session only; stream stop clears it.

## [1.4.2] — 2026-09-14

### Added
- **Trusted-friend join** — bridge verbs `JOINREQ`, `JOINPENDING`, `JOINACK`, `JOINSTATUS`, `TRUSTED`. Friends stay paired; Accept on the host resumes them as P2.
- **Couch co-op P1/P2** — game-agnostic via Sunshine connect-order and Steam Input (not a per-game `.so`). JOINACK, Sunshine Gamepad 1, and a second session hide Steam `28de:11ff` clones, slot host P1 / guest P2, and write `gamesphere-couch-coop.env`.

## [1.4.1] — 2026-09-14

### Added
- **Local playtime** — reads Steam `localconfig.vdf` / `sharedconfig.vdf` plus Non-Steam `shortcuts.vdf` `LastPlayTime` (no Web API key). Stamps `_gamesphere_playtime_minutes` / `_gamesphere_last_played` on `apps.json`.
- **`PLAYTIMES` bridge verb** — JSON `{ "games": [{ name, minutes, lastPlayed, steamAppId, shortAppId, sunshineId }] }` so GameSphere can badge emu / shortcut hours.

## [1.4.0] — 2026-09-14

### Added
- **Guest invites** — host bridge verbs `INVITE`, `JOINPIN`, `INVITEEND`. Companion Tool posts the friend's Moonlight PIN to Sunshine/Apollo and unpairs that client when the host quits.
- Product name **GameSphere Companion Tool** (binary and GitHub repo unchanged).

## [1.3.3] — 2026-09-13

### Fixed
- **New Linux installs** — `install-linux.sh` and `install-flatpak.sh` enable lingering and a user-session bus so `gamesphere-import-update.timer` actually starts from SSH / Game Mode, and no longer claim success when `systemctl --user` failed.
- **PATH** — git/Decky `~/.local/bin/gamesphere-import` wrapper plus `environment.d` so leftover Flatpak exports cannot steal the command. Auto-update still prefers git over leftover Flatpak.

### Added
- **Decky** — enables the same timer on plugin load.
- **`--auto-config`** — installs the timer as a first-run fallback if the shell installer could not.
- Release assets include systemd units and `linux-autoupdate-lib.sh`.

## [1.3.2] — 2026-09-13

### Fixed
- **Auto-update** — git/Decky installs are the primary Linux path (do not rewrite a leftover Flatpak every day). `install-linux.sh` can `chown` root-owned Decky plugin files so `git reset` is not blocked. Flatpak version parsing ignores indented `Version:` lines.

## [1.3.1] — 2026-09-13

### Added
- **Linux auto-update timer** — `install-linux.sh` and `install-flatpak.sh` enable a systemd user timer (`gamesphere-import-update.timer`) that checks GitHub Releases 5 minutes after boot and daily. Opt out: `GAMESPHERE_AUTO_UPDATE=0`.
- **`gamesphere-import-update.sh`** — bounded updater for git checkouts, Flatpak bundles, and AppImages. Does not import games or restart Sunshine/Steam.

### Fixed
- **`gs_updater`** — Linux `--apply-update` no longer switches a git/Decky install over to Flatpak. macOS source checkouts can apply the git installer from Releases.
- Windows GUI still checks on launch (**Check for updates**); set `GAMESPHERE_AUTO_UPDATE=apply` to download without the prompt. `GAMESPHERE_AUTO_UPDATE=0` disables the silent check.

## [1.3.0] — 2026-09-13

### Added
- **Mic to PC — Windows VB-CABLE** — **Set up mic for GameSphere** / `--setup-mic` installs VB-CABLE (license prompt, not bundled) and starts a bundled OSS VBAN feeder into **CABLE Input**. Discord/OBS use **CABLE Output**. No VoiceMeeter. Linux PipeWire path unchanged. See [docs/MIC-TO-PC.md](docs/MIC-TO-PC.md).

## [1.2.5] — 2026-09-11

### Added
- **`install-flatpak.sh`** — one `curl | bash` Flatpak install (replaces broken `.flatpakref` for bundle-only releases)

### Changed
- Release assets drop `.flatpakref`; use `install-flatpak.sh` or direct `.flatpak` bundle instead

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
