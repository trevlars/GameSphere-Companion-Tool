# Wanna-play lock-screen push (APNs)

Companion sends a real Apple Push so a paired iPhone/iPad can wake with:

**Want to play {game} with {Steam name}** plus box art, tap → `gamesphere://play?…`.

This is **token-based APNs** from the host daemon. Not Firebase. **Do not** use the App Store Connect upload keys in `GameSphere/keys/` (those are for TestFlight, not push).

One Auth Key works for **both** sandbox and production. The device token picks the server:

| GameSphere build | `PLAYREG` environment | APNs host |
|---|---|---|
| Debug (current **1(115)**) | `development` / sandbox | `api.sandbox.push.apple.com` |
| TestFlight / App Store | `production` | `api.push.apple.com` |

Without a `.p8` on the PC, **nothing crashes**. Friends still get Wanna play via `PLAYPENDING` poll while GameSphere is open. `wanna status` / `pushStatus` / `wanStatus` say one sentence that lock-screen push needs the key.

---

## One-time: create the APNs Auth Key

1. Sign in at [https://developer.apple.com/account](https://developer.apple.com/account) (GameSphere team **ABG342Z7V2**).
2. Open **Certificates, Identifiers & Profiles**.
3. Left sidebar → **Keys**.
4. Click **+** (Create a key).
5. **Key Name:** `GameSphere Companion APNs` (any label is fine).
6. Enable **Apple Push Notifications service (APNs)** — that checkbox only. Do **not** enable In-App Purchase, DeviceCheck, or MusicKit.
7. **Continue** → **Register**.
8. **Download** the `.p8`. Apple shows it **once**. Filename looks like `AuthKey_XXXXXXXXXX.p8`.
9. Copy the **Key ID** (10 characters) on that page.
10. Confirm **Team ID** under **Membership details**: `ABG342Z7V2`.
11. Bundle ID is `com.moonlight.gamesphere` (not the Notification Service Extension id).

If Keys is missing, the account holder must enable Access to Certificates, Identifiers & Profiles.

---

## Drop the key on the Sunshine host

Prefer the Companion config dir so a later update of Python files cannot clobber it. Copy the file locally (USB, AirDrop, scp to **this** PC — not a hardcoded host).

**Linux:**

```bash
mkdir -p ~/.config/gamesphere-import-tool
chmod 700 ~/.config/gamesphere-import-tool
cp /path/to/AuthKey_XXXXXXXXXX.p8 ~/.config/gamesphere-import-tool/apns.p8
```

**Windows:** `%LOCALAPPDATA%\GameSphere\apns.p8`

If you keep Apple’s filename (`AuthKey_XXXXXXXXXX.p8`) in that folder, Companion reads the Key ID from the name.

Or put it next to the daemon (never commit this file):

```
~/.local/share/gamesphere-import-tool/host_tuning/apns.p8
```

Then set Key ID + Team ID. Easiest sidecar (no PEM inside):

`~/.config/gamesphere-import-tool/apns.json` (Windows: `%LOCALAPPDATA%\GameSphere\apns.json`)

```json
{
  "keyId": "YOUR10CHARID",
  "teamId": "ABG342Z7V2",
  "bundleId": "com.moonlight.gamesphere"
}
```

Same three fields can live in `host_tuning.json` as `apns_key_id`, `apns_team_id`, `apns_bundle_id`, `apns_key_path`. A one-line `apns.keyid` file next to the `.p8` also works.

```bash
chmod 600 ~/.config/gamesphere-import-tool/apns.p8 ~/.config/gamesphere-import-tool/apns.json
```

Restart **the bridge only** (do not restart Sunshine):

```bash
systemctl --user restart gamesphere-host-bridge.service
uv run python3 host_tuning_cli.py wanna
# pushReady true → lock-screen is armed
```

Windows: `GamesphereImportTool.exe --host-daemon-install` (already running) then check `wanna` status. Never print or log the PEM.

---

## What Companion sends

HTTP/2 POST to `/3/device/{token}`:

- Title `Wanna play?`
- Body `Want to play {game} with {Steam name}`
- `aps.mutable-content: 1` so the Notification Service Extension can attach box art
- `coverUrl` / `thumbnailUrl` (HTTPS IGDB/Steam/shortcut URL)
- `playURL` = `gamesphere://play?session=…&preauth=1&host=…`
- Sound `default`, category `GS_WANNA_PLAY`

Paired devices send `apnsToken` + `apnsEnvironment` on `PLAYREG`. Companion stores both in `wanna_play.json`.

---

## Checklist if lock-screen is silent

- On the phone/iPad: Settings → GameSphere → **Allow Notifications**.
- Debug 115 → sandbox. TestFlight → production. Same `.p8`.
- `PLAYREG` must have run after the token was granted (open GameSphere on the friend device on LAN).
- `curl --http2` and `openssl` talk to Apple (installed on typical Linux Sunshine hosts).
- Bridge log line `APNs sent env=development http=200` (never prints the key).
