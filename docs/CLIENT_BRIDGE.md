# Client bridge protocol (TCP 47998)

GameSphere Import Tool exposes a **TCP** bridge on port **47998** when you run:

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
| `GAMESTATE` | `GAMESTATE` | JSON launch heuristic |
| `LOCKSTATE` | `LOCKSTATE` | JSON `{ "locked": true/false }` |

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
- Stream session — probes `CAPS`, sends `SESSIONDATA` every 15 s, `RESTORE` on exit

Moonlight, StreamLight, or your fork can reuse the same verbs without importing GameSphere code.

---

## Host setup checklist

1. Install Import Tool (`install-linux.sh` or Windows GUI).
2. Run `host_tuning_cli.py init --enable-all` (enables bridge in config).
3. Start bridge: `--host-bridge` or systemd user service (see `scripts/systemd/gamesphere-host-bridge.service`).
4. Import library so `apps.json` includes `_gamesphere_store` for `APPSTORES`.

See [HOST_INTEGRATION.md](HOST_INTEGRATION.md) for embedding in Sunshine, Apollo, Vibeshine, and other hosts.
