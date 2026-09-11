# GameSphere Import — DeckyLoader plugin

Import your Steam library into Sunshine from **Game Mode**, apply **host tuning**, and toggle the **GameSphere bridge** (TCP 47998) — same automagic CLI as the desktop host.

## Prerequisites

1. Install the CLI on the host:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/trevlars/Gamesphere-Import-Tool/main/scripts/install-linux.sh | bash
   ```

   Optional bridge auto-enable on install:

   ```bash
   GAMESPHERE_ENABLE_HOST_BRIDGE=1 bash scripts/install-linux.sh
   ```

2. Sunshine user service running: `systemctl --user status sunshine`

## Build & install

On a machine with Node 18+:

```bash
cd decky
npm install
npm run build
```

Symlink into Decky (Steam Deck / Bazzite Game Mode):

```bash
ln -sfn "$HOME/.local/share/gamesphere-import-tool/decky" \
  "$HOME/homebrew/plugins/gamesphere-import"
```

Reload Decky: **Quick Access → Decky icon → reload plugins**, or restart the Plugin Loader service.

## Plugin panels

### Status
- Import Tool version and detected `apps.json` path
- Bridge service state (`active` / `inactive`)
- Host tuning summary (link speed, session count)

### Sync Steam library
| Toggle | CLI flag |
|--------|----------|
| Dry run | `--dry-run` |
| Skip Sunshine restart | `--no-restart` |
| Apply host tuning after import | `--host-tuning` |
| Verbose log | `--verbose` |

### Host tuning
- **Initialize host tuning** — `host_tuning_cli.py init --enable-all`
- **Apply host tuning only** — `--host-tuning-only`
- **GameSphere bridge service** — enables/disables `gamesphere-host-bridge.service` (TCP 47998 for GameSphere session stats + store badges)

### Maintenance
- Regenerate `.env` from detected paths (`--auto-config`)
- Check / install GitHub updates
- Remove all games (stock Desktop + Big Picture only)

## Notes

- Linux import covers **Steam + Non-Steam shortcuts** (Eden, emulators, etc.). Multi-store Epic/GOG/Xbox remains Windows-only in the CLI.
- Bazzite `sunshine-stream-prep.sh` hooks are preserved on normal import; only **Remove all games** resets to stock apps.
- The bridge toggle installs `~/.config/systemd/user/gamesphere-host-bridge.service` if missing.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| CLI not installed | Run `install-linux.sh` from Game Mode terminal or SSH |
| Bridge toggle fails | Ensure Import Tool 1.2.1+ and `scripts/systemd/gamesphere-host-bridge.service` exists |
| Import hangs | Try **Skip Sunshine restart**; restart Sunshine from terminal |
| Plugin UI empty after update | Re-run `npm run build` in `decky/` and reload Decky |
