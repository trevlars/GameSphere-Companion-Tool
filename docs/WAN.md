# WAN remote play (GameSphere + Companion Tool)

LAN couch co-op already works. Remote join is **automagic**: Companion maps Sunshine + Companion ports when someone invites, starts Wanna play, or a stream starts — then unmaps when the session is idle. GameSphere tries **LAN `serverinfo` first**, then `wan=`. There is no “pick WAN” toggle.

```bash
uv run python3 host_tuning_cli.py wan          # one-line status
uv run python3 host_tuning_cli.py wan map      # force map now
uv run python3 host_tuning_cli.py wan unmap
# while the bridge is running:
#   echo WANSETUP | nc HOST 47998
```

## What is automatic vs what you still need

**Automatic (any Sunshine + Companion install):**

- Public IP via STUN (ipify fallback) written as `wan=` on invite / play URLs.
- UPnP IGD / NAT-PMP / PCP mapping of the game ports to this PC, scoped to the stream / invite TTL (not 24/7).
- Drop Sunshine web UI **47990** if the router already published it.
- WAN-safe Sunshine keys in `sunshine.conf` (`gamepad = x360`, `upnp = disabled` so Sunshine itself does not publish 47990, `origin_web_ui_allowed = pc`, opportunistic WAN encryption). Applied on disk; Companion **never restarts Sunshine** mid-game.
- Hairpin-safe URLs: `host=` and `lan=` stay private; only `wan=` is the public IP.

**Still needed once on the router:** either UPnP/NAT-PMP **enabled**, or **manual port forwards** to this PC. On eero, manual forwards are usually more reliable than UPnP.

Set `wan_manual_forward: true` in Companion `host_tuning.json` after you forward **TCP and UDP 47984–48010** to the PC’s LAN address (e.g. `10.0.5.42`). Companion then reports `wanReady` from STUN without waiting on UPnP. It will never tell anyone to forward 47990.

Carrier-grade NAT (no public IPv4) cannot be published with UPnP or manual forwards alone. ZeroTier or Tailscale is optional fallback: if either is running, status mentions its overlay address.

## Ports Companion maps (never 47990)

| Direction | Ports | Why |
|-----------|-------|-----|
| TCP | **47984**, **47989**, **48010**, **47998** | HTTPS pairing / RTSP / control / Companion JOINPIN |
| UDP | **47998–48000**, **48002**, **48010** | Moonlight video / audio / control |
| UDP | **48020** | In-stream voice mixer, **only while voice is running** |
| **Never mapped** | **47990** | Sunshine web UI (localhost only) |

TCP and UDP **47998** are both required (JOINPIN is TCP; video is UDP). They do not conflict.

The installer also tries to allow this list on **firewalld / ufw** (Linux) or Windows Firewall. Mappings refresh while a stream is up and drop about two minutes after the last client, or when the invite TTL ends. HTTPS pairing, client certs, and PIN are unchanged. Invite tokens are short-lived and unguessable. Wanna-play pre-auth is only for P1-pinged TRUSTED UUIDs this session.

## Sunshine

Leave codecs alone (do not change hevc/av1 for mic/voice work). `gamepad = x360`. Allow up to four clients.

Set `sunshine_username` / `sunshine_password` in Companion `host_tuning.json` to the **web login** so JOINPIN can inject against **localhost:47990**. Status / `WANSETUP` / `wan` never print that password.

## Invite

Host GameSphere → Invite while streaming. The URL looks like:

```
gamesphere://join?token=…&host=192.168.1.50&lan=192.168.1.50&wan=203.0.113.9&httpsPort=47984
```

- Same house: LAN `serverinfo` succeeds → private IP (no hairpin).
- Off-site / cellular: LAN probe fails quickly, then `wan=`.
- JOINPIN still hits Companion TCP **47998** on whichever address connected.

`HOSTINFO` / `COOPSTATE` / `WANSETUP` include `wanReady` + `wanStatus` (one sentence) for the overlay.

## Four players

The same ports support four GameSphere clients (Sunshine x360 pads 0–3). Strangers and un-pinged trusted friends still wait for host Accept, then `/resume`. Friends pinged by host `WANNAPLAY` are session-preauthed and skip Accept for that stream only.

Linux: Companion **ships and enables** udev + `gamesphere-hide-steam-clones.sh` so Steam Input `28de:11ff` clones do not appear as extra SDL pads. Join-order seats stay locked; only host `SLOTSWAP` remaps.

CLI: `uv run python3 host_tuning_cli.py wanna start --app-name "Celeste"` (or `wanna status` / `wanna end`). Lock-screen Apple Push needs an APNs Auth Key on the host — [APNS.md](APNS.md). Poll (`PLAYPENDING`) still works without the key.

## Voice isolation

UDP **48020** mixes GameSphere client mics only. It does **not** tap HDMI / Sunshine audio and does **not** attach WebRTC AEC to HDMI (that crackles the stream). Optional Discord/OBS **Mic to PC** is VBAN on UDP 6980 — [MIC-TO-PC.md](MIC-TO-PC.md).

## How to test

**Same Wi-Fi (hairpin check):** invite a second device on the house LAN. It must use `lan=` / `host=` (private). If it tried only the public IP, many consumer routers fail hairpin NAT.

**Off-LAN (cellular):** disable Wi-Fi on the guest phone, open the same invite / Wanna play URL. Pairing + JOINPIN + stream should work when `wanReady` is true (UPnP mapped **or** `wan_manual_forward` with router forwards in place). GameSphere tries the public `wan=` address first, matching stock Moonlight — ZeroTier is optional.

**gamesphere-host-bridge** is a user service (not a window you leave open). Linger is enabled by the Linux installer so it starts after reboot / Game Mode:

```bash
systemctl --user status gamesphere-host-bridge.service
loginctl show-user "$USER" -p Linger
# Restart Companion only — never Sunshine:
systemctl --user restart gamesphere-host-bridge.service
```
