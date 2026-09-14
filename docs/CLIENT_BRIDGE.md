# Client bridge protocol (TCP 47998)

GameSphere Companion Tool exposes a **TCP** bridge on port **47998** when you run:

```bash
gamesphere-import --host-bridge
# or: uv run host_tuning_cli.py bridge
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
| `INVITE` | `INVITE {"appId":"...","appName":"...","hostId":"...","lanHost":"10.0.5.42","httpsPort":47984}` | JSON invite token + `gamesphere://join?...` URL |
| `JOINPIN` | `JOINPIN {"token":"...","pin":"1234","name":"Gemma iPhone"}` | JSON `{ok, guestUuid}` — Companion Tool posts the PIN to Sunshine |
| `INVITEEND` | `INVITEEND {"token":"..."}` | Unpair **ephemeral** guest certs for that invite (host quit). Trusted UUIDs (see `TRUSTED`) stay paired. |
| `JOINREQ` | `JOINREQ {"friendName":"…","steamId":"…","appId":"…","appName":"…"}` | Friend → PC: mint join request `{ok, reqId}` |
| `JOINPENDING` | `JOINPENDING` | Host polls: `{ok, requests:[{reqId,friendName,appName,…}]}` |
| `JOINACK` | `JOINACK {"reqId":"…","accept":true,"appId":"…","appName":"…","lanHost":"…"}` | Host Accept/Decline |
| `JOINSTATUS` | `JOINSTATUS {"reqId":"…"}` | Friend polls: `{ok, status:pending\|accepted\|declined\|expired,…}` |
| `TRUSTED` | `TRUSTED {"uuid":"<moonlight-client-uuid>"}` | Mark guest as trusted — `INVITEEND` will not unpair them |

Guest co-op (strangers): host GameSphere sends `INVITE` while streaming, share-sheets the `joinURL`. The friend's GameSphere opens `gamesphere://join`, pairs against Sunshine, and `JOINPIN`s the Companion Tool so nobody types the PIN. Host Quit sends `INVITEEND` so **ephemeral** guests are unpaired.

Trusted friends: stay paired after first successful pair (`TRUSTED`). Later joins use `JOINREQ` → host `JOINPENDING`/`JOINACK` → friend `/resume` as P2 (no new PIN).

Forward **TCP 47998** (this bridge) in addition to Sunshine's UDP 47998 video port if the friend is off-LAN. Never forward Sunshine **47990** (web UI). Set `sunshine_username` / `sunshine_password` in `host_tuning.json` to the Sunshine web login.

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

`drop_rate` is 0.0–1.0 (not percent).

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

1. Install Import Tool (`install-linux.sh` or Windows GUI).
2. Run `host_tuning_cli.py init --enable-all` (enables bridge in config).
3. Start bridge: `--host-bridge` or systemd user service (see `scripts/systemd/gamesphere-host-bridge.service`).
4. Import library so `apps.json` includes `_gamesphere_store` for `APPSTORES`.

See [HOST_INTEGRATION.md](HOST_INTEGRATION.md) for embedding in Sunshine, Apollo, Vibeshine, and other hosts.
