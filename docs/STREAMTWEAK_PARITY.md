# StreamTweak feature parity

GameSphere Import Tool adapts host-side ideas from [StreamTweak](https://github.com/FoggyBytes/StreamTweak) (FoggyBytes, GPL-3.0). This document is an honest map of what is ported, partial, or intentionally out of scope for a **cross-platform, host-agnostic CLI**.

StreamTweak targets **Windows + StreamLight**. We target **any Moonlight-compatible host** + **any Moonlight client** (including [GameSphere](https://github.com/trevlars/GameSphere)).

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Implemented (Windows + Linux where noted) |
| 🟡 | Partial / best-effort |
| ⬜ | Not planned in Import Tool (StreamTweak UI/service territory) |
| 🔌 | Bridge verb available for clients |

---

## Network

| StreamTweak | Import Tool | Notes |
|-------------|-------------|-------|
| Client-driven link speed (`NETINFO` / `SETSPEED`) | ✅ 🔌 | Windows PowerShell; Linux `ethtool` (may need root) |
| Wired-only guard | 🟡 | Client should refuse Wi‑Fi; host does not enforce Tailscale source yet |
| Manual restore | ✅ 🔌 | `RESTORE` + session-end prep hook |
| LocalSystem / no UAC service | ⬜ | Use admin once for Program Files hosts, or Linux sudoers for ethtool |
| Tailscale IP (`TAILSCALE`) | ✅ 🔌 | `tailscale ip -4` + interface scan |

---

## Launch & lock state

| StreamTweak | Import Tool | Notes |
|-------------|-------------|-------|
| Launch report (`GAMESTATE`) | 🟡 🔌 | Process + log heuristic; not full launcher-aware window watch |
| Remote PIN unlock (`LOCKSTATE`) | 🟡 🔌 | Lock detection only; client sends PIN over stream |
| Unlock sessions excluded from history | ⬜ | Client-side policy |
| Launcher login vs game appeared | ⬜ | Full LaunchWatcher port is future work |

---

## Display & audio

| StreamTweak | Import Tool | Notes |
|-------------|-------------|-------|
| Per-monitor HDR toggle | 🟡 | Windows Auto HDR preference; Linux `wlr-randr` when available |
| Auto spatial audio (Dolby / Sonic) | 🟡 | Device selection + user completes Windows spatial setting |
| Live device availability UI | ⬜ | CLI `host_tuning_cli.py status` only |

---

## NVIDIA Sentinel

| StreamTweak | Import Tool | Notes |
|-------------|-------------|-------|
| Profile snapshot (.nip) | 🟡 | If NVIDIA Profile Inspector installed on Windows |
| Auto-restore on driver reset | ⬜ | Needs background watcher + DRS port |
| Readable settings panel / DLSS version | ⬜ | Tray UI scope |
| Native DRS decrypter | ⬜ | StreamTweak-specific |

---

## Game library sync

| StreamTweak | Import Tool | Notes |
|-------------|-------------|-------|
| Multi-store discovery | ✅ | Windows: Steam, Epic, GOG, Ubisoft, Battle.net, EA, Xbox |
| Native cover art (600px+ rule) | ✅ | `store_covers.py` |
| Store-correct launch commands | ✅ | Epic triple, Xbox `shell:appsFolder`, etc. |
| Manual entries preserved | ✅ | `custom_games.json` + merge, never wipe Desktop |
| Host tile replacement | ✅ | Reversible `desktop.png` / `steam.png` swap |
| Store badges on client (`APPSTORES`) | ✅ 🔌 | From `_gamesphere_store` in `apps.json` |

---

## Streaming app manager

| StreamTweak | Import Tool | Notes |
|-------------|-------------|-------|
| Close on session start / reopen on end | ✅ | `managed_apps` in `host_tuning.json` + prep hooks |
| Per-app exclude switch | ✅ | `auto_manage: false` |

---

## Sessions & telemetry

| StreamTweak | Import Tool | Notes |
|-------------|-------------|-------|
| Session log + covers | ✅ | `sessions.json` |
| Quality grade (Excellent/Good/Poor) | ✅ | From `SESSIONDATA` client samples |
| Delivered vs target bitrate | 🟡 | Stored when client sends `target_bitrate_kbps` |
| Compare sessions / Dashboard UI | ⬜ | Export JSON; no GUI dashboard |
| Session detection 8.3.0 fixes | 🟡 | Line-prefix matching + UDP socket idle end |
| Vibeshine/Vibepollo session UUID | 🟡 | Parsed when present in log |

---

## Bridge (TCP 47998)

| Verb | Status |
|------|--------|
| `CAPS` | ✅ |
| `NETINFO` | ✅ |
| `SETSPEED` | ✅ |
| `RESTORE` | ✅ |
| `STATUS` | ✅ |
| `STATS` | ✅ |
| `TAILSCALE` | ✅ |
| `LASTSESSION` | ✅ |
| `SESSIONDATA` | ✅ |
| `APPSTORES` | ✅ |
| `GAMESTATE` | 🟡 |
| `LOCKSTATE` | 🟡 |
| `ENROLL` / `AUTH1` (RSA) | ⬜ | Optional shared secret instead |
| `SHUTDOWN` / Windows Update suite | ⬜ | Destructive; StreamTweak LocalSystem service |
| `UNLOCKBEGIN` / `UNLOCKEND` | ⬜ | Client declares unlock plumbing sessions |

---

## Contributing parity

If you maintain a Moonlight host or client and want a verb or library field supported, open an issue with:

1. Host name + `apps.json` path convention  
2. Sample log lines for session start/end (if telemetry)  
3. Expected bridge command + JSON shape  

We prefer **documented subprocess contracts** ([HOST_INTEGRATION.md](HOST_INTEGRATION.md)) over forking host code.
