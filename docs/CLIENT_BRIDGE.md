# Client bridge protocol (TCP 47998)

GameSphere Companion Tool exposes a **TCP** bridge on port **47998**. In production this is the always-on **`gamesphere-host-bridge`** daemon (systemd user service, Windows Task Scheduler, or macOS LaunchAgent) — not a window you leave open.

```bash
gamesphere-import --host-bridge          # foreground (what the service runs)
gamesphere-import --host-daemon-install   # enable login/boot autostart
# or: uv run host_tuning_cli.py daemon install
```

This is separate from Moonlight’s **UDP** video traffic on the same port number. TCP and UDP do not conflict.

The wire format matches the subset implemented by [StreamTweak](https://github.com/FoggyBytes/StreamTweak) so one client implementation can talk to either host tool.

---

## Connection

1. Open TCP to `<host-lan-ip>:47998` (2–3 s timeout is enough).
2. Send one verb per request, terminated with `\n`.
3. Read one line response (UTF-8 text, or JSON for some verbs).

Optional shared secret (when `bridge_require_auth` is true in `host_tuning.json`):

```
CAPS
NETINFO AUTH:your-secret:
```

---

## Verbs

| Verb | Request line | Response |
|------|--------------|----------|
| `CAPS` | `CAPS` | Space-separated capability list, e.g. `CAPS NETINFO SETSPEED …` |
| `NETINFO` | `NETINFO` | JSON: wired adapter name, current/target Mbps, session active |
| `SETSPEED` | `SETSPEED 1000` | `OK`, `PENDING`, or `ERR` |
| `RESTORE` | `RESTORE` | `OK` or `ERR` |
| `STATUS` | `STATUS` | Current link Mbps or `UNKNOWN` |
| `STATS` | `STATS` | JSON host CPU/GPU snapshot |
| `TAILSCALE` | `TAILSCALE` | Tailscale IPv4 or `NOT_DETECTED` |
| `LASTSESSION` | `LASTSESSION` | JSON last finished session |
| `SESSIONDATA` | `SESSIONDATA {"rtt_ms":20,"drop_rate":0.01,…}` | `OK` or `ERR` |
| `APPSTORES` | `APPSTORES` | JSON map `{ "Game Name": "Steam", … }` |
| `PLAYTIMES` | `PLAYTIMES` | JSON `{ "games": [{ "name", "minutes", "lastPlayed", "steamAppId", "shortAppId", "sunshineId" }] }` from local Steam files |
| `GAMESTATE` | `GAMESTATE` | JSON launch heuristic |
| `LOCKSTATE` | `LOCKSTATE` | JSON `{ "locked": true/false }` |
| `INVITE` | `INVITE {"appId":"...","appName":"...","hostId":"...","lanHost":"192.168.1.50","httpsPort":47984}` | JSON invite token + `gamesphere://join?...` URL |
| `JOINPIN` | `JOINPIN {"token":"...","pin":"1234","name":"Friend iPhone"}` | JSON `{ok, guestUuid}` — Companion Tool posts the PIN to Sunshine |
| `INVITEEND` | `INVITEEND {"token":"..."}` | Unpair **ephemeral** guest certs for that invite (host quit). Trusted UUIDs (see `TRUSTED`) stay paired. |
| `JOINREQ` | `JOINREQ {"friendName":"…","uuid":"…","sessionId":"…","appId":"…"}` | Friend → PC: mint join request. If `uuid` is session-preauthed, **auto-JOINACK** (`status=accepted`, `preauth=true`). Else `{ok, reqId, preauth:false}` |
| `JOINPENDING` | `JOINPENDING` | Host polls: `{ok, requests:[{reqId,friendName,appName,…}]}` — auto-accepted preauth joins do **not** appear |
| `JOINACK` | `JOINACK {"reqId":"…","accept":true,"appId":"…","appName":"…","lanHost":"…"}` | Host Accept/Decline |
| `JOINSTATUS` | `JOINSTATUS {"reqId":"…"}` | Friend polls: `{ok, status:pending\|accepted\|declined\|expired,…}` |
| `TRUSTED` | `TRUSTED {"uuid":"<moonlight-client-uuid>"}` | Mark guest as trusted — `INVITEEND` will not unpair them |
| `HOSTINFO` | `HOSTINFO` | Host SteamID + persona + avatar URL + lan/wan + `wanReady`/`wanStatus` + voice port |
| `COOPSTATE` | `COOPSTATE` optional `{"hostUnpaused":true}` | P1–P4 seats, pauseRecommended, `wannaPlay` session, client health, `wanReady`, plus `coopChat[]` / `playReplies[]` / `playReply` (guest phrase bubbles, TTL ~30s) |
| `SLOTSWAP` | `SLOTSWAP {"order":[1,0,2,3]}` | Host-only remap. `order[i]` = old seat that becomes new seat `i`. Example P1↔P2: `[1,0,2,3]` |
| `WANSETUP` | `WANSETUP` optional `{"map":true}` / `{"unmap":true}` | JSON WAN status (`wanReady`, one-line `status`). Maps game ports via UPnP/NAT-PMP; never 47990 |
| `VOICE` | `VOICE start\|stop\|status` | UDP voice mixer (port 48020) |
| `WANNAPLAY` | `WANNAPLAY {"appId":"…","appName":"…","hostId":"…","coverUrl"?}` or `{"end":true}` | Host Swap “Wanna play”: stamp session pre-auth; HTTP/2 APNs to registered tokens; return `playURL` (`gamesphere://play?…&preauth=1`) + `pushStatus` |
| `PLAYREG` | `PLAYREG {"uuid":"…","name":"Alex iPad","apnsToken":"…","apnsEnvironment":"development"}` | Friend registers as a ping target (also marks TRUSTED). Debug 115 = `development` (sandbox). TestFlight = `production`. |
| `PLAYPENDING` | `PLAYPENDING {"uuid":"…"}` | Friend polls host-initiated pings for this session |
| `PLAYCLAIM` | `PLAYCLAIM {"uuid":"…","sessionId":"…"}` | Consume ping. Does **not** assign a pad seat — follow with `JOINREQ` |
| `PLAYREPLY` | `PLAYREPLY {"uuid":"…","sessionId":"…","phrase":"I'm in","accepted":true,"persona"?,"avatarUrl"?}` | Guest tapped I'm in / You're going down / Can't right now. Echoed on the next `COOPSTATE` as `coopChat` / `playReplies` / `playReply` (last 8, TTL ~30s). Does not gate `/resume` or change seats. |

Guest co-op (strangers): host GameSphere sends `INVITE` while streaming, share-sheets the `joinURL`. The friend's GameSphere opens `gamesphere://join`, pairs against Sunshine, and `JOINPIN`s the Companion Tool so nobody types the PIN. Host Quit sends `INVITEEND` so **ephemeral** guests are unpaired.

Trusted friends: stay paired after first successful pair (`TRUSTED` / `PLAYREG`). Later joins use `JOINREQ` → host `JOINPENDING`/`JOINACK` → friend `/resume` as P2–P4 (no new PIN).

**Wanna play (session pre-auth):** host Swap overlay sends `WANNAPLAY`. Companion stamps every current TRUSTED UUID for **this Sunshine session only** and returns `gamesphere://play?session=…&host=LAN&lan=LAN&wan=WAN&preauth=1`. Registered devices with an `apnsToken` get an HTTP/2 APNs alert (title/body + `mutable-content` cover URL). Those clients `JOINREQ` with `uuid` + `sessionId` and get **auto-JOINACK** — no Accept sheet. A trusted friend who was not pinged still needs Accept. Stream stop (or `WANNAPLAY {"end":true}`) clears pre-auth. Join-order seats stay locked; only host `SLOTSWAP` remaps. Guest phrase taps (`PLAYREPLY`) are fire-and-forget; P1 StreamFrame polls `COOPSTATE` for `coopChat` / `playReplies` / `playReply`.

If the host has no APNs Auth Key (`.p8`), `PLAYPENDING` poll still works while GameSphere is open; `pushStatus` / `wanna` CLI is one sentence that lock-screen needs the key. Setup: [APNS.md](APNS.md). Never use App Store Connect API keys.

Invite / Wanna play / stream start **auto-maps** Sunshine + Companion ports (UPnP IGD / NAT-PMP / PCP) and fills `wan=` from STUN. Mappings drop when the session is idle. Never maps Sunshine **47990**. If the router has no UPnP, `wanReady` is false and `wanStatus` is one sentence. Clients try LAN `serverinfo` first, then WAN — no hairpin. See [WAN.md](WAN.md). Set `sunshine_username` / `sunshine_password` in `host_tuning.json` to the Sunshine web login (never logged or printed).

### SESSIONDATA sample fields

The host uses these to grade sessions in `sessions.json`:

```json
{
  "client": "GameSphere",
  "game": "Hogwarts Legacy",
  "rtt_ms": 18,
  "drop_rate": 0.012,
  "bitrate_kbps": 20000,
  "target_bitrate_kbps": 25000
}
```

`drop_rate` is 0.0–1.0 (not percent). For couch pause, also send:

```json
{
  "client": "GameSphere",
  "client_id": "<moonlight-uuid>",
  "role": "host",
  "is_host": true,
  "drop_rate": 0.01,
  "client_name": "iPad"
}
```

`role` is `"host"` or `"guest"`. Host StreamFrame should poll `COOPSTATE` and `pulsePlayButton` when `pauseRecommended` is true. After the host overlay unpauses, send `COOPSTATE {"hostUnpaused":true}`.

### Wanna-play deep link (iOS sibling)

```
gamesphere://play?session=TOKEN&preauth=1&token=TOKEN
  &host=LAN&lan=LAN&wan=PUBLIC&httpsPort=47984
  &appId=…&hostId=…&name=AppName
```

Friend: `PLAYPENDING` (or open the URL) → `JOINREQ` with `uuid` + `sessionId` → if `preauth=true` / `status=accepted`, `/resume` immediately. Do not show Accept on the host for that client.

### Voice (UDP 48020)

Only after `HOSTINFO`/`COOPSTATE` shows `voiceRunning`. Header 12 bytes, network order: `GSVC` + ver(1) + slot(1) + seq(2) + samples(2) + rate(2). Payload: 16 kHz s16le mono PCM. Mix is client-to-client only — do not mix into Sunshine HDMI.

---

## Reference client

[GameSphere](https://github.com/trevlars/GameSphere) implements:

- `GSHostCompanionBridge` — TCP client (`GameSphere/Features/Stream/`)
- `GSHostStoreCatalog` — caches `APPSTORES` per host UUID
- `GSHostPlaytimeCatalog` — caches `PLAYTIMES` (local Steam + Non-Steam hours) per host UUID
- Stream session — probes `CAPS`, sends `SESSIONDATA` every 15 s, `RESTORE` on exit

Moonlight, StreamLight, or your fork can reuse the same verbs without importing GameSphere code.

---

## Host setup checklist

1. Install Companion (`install-linux.sh`, Flatpak, or Windows GUI). The host daemon is enabled on install.
2. Run `host_tuning_cli.py init --enable-all` (enables bridge in config).
3. Confirm the daemon: `systemctl --user status gamesphere-host-bridge.service` or `--host-daemon-status`.
4. Import library so `apps.json` includes `_gamesphere_store` for `APPSTORES`.

See [HOST_INTEGRATION.md](HOST_INTEGRATION.md) for embedding in Sunshine, Apollo, Vibeshine, and other hosts.
