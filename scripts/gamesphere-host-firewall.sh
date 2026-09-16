#!/usr/bin/env bash
# Open GameSphere / Sunshine game ports on the host firewall. Never 47990.
# Companion still maps the same ports via UPnP/NAT-PMP for WAN; this is LAN + local filter.
set -euo pipefail

TCP_PORTS=(47984 47989 48010 47998)
UDP_PORTS=(47998 47999 48000 48002 48010 48020)

echo "==> GameSphere Companion — host firewall (never 47990)"

if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  for p in "${TCP_PORTS[@]}"; do
    sudo -n firewall-cmd --permanent --add-port="${p}/tcp" 2>/dev/null || \
      firewall-cmd --permanent --add-port="${p}/tcp" 2>/dev/null || true
  done
  for p in "${UDP_PORTS[@]}"; do
    sudo -n firewall-cmd --permanent --add-port="${p}/udp" 2>/dev/null || \
      firewall-cmd --permanent --add-port="${p}/udp" 2>/dev/null || true
  done
  sudo -n firewall-cmd --reload 2>/dev/null || firewall-cmd --reload 2>/dev/null || true
  echo "    firewalld: game ports allowed (Sunshine web UI 47990 left closed)"
  exit 0
fi

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi "active"; then
  for p in "${TCP_PORTS[@]}"; do
    sudo -n ufw allow "${p}/tcp" comment "GameSphere" 2>/dev/null || \
      ufw allow "${p}/tcp" 2>/dev/null || true
  done
  for p in "${UDP_PORTS[@]}"; do
    sudo -n ufw allow "${p}/udp" comment "GameSphere" 2>/dev/null || \
      ufw allow "${p}/udp" 2>/dev/null || true
  done
  echo "    ufw: game ports allowed (Sunshine web UI 47990 left closed)"
  exit 0
fi

echo "    No active firewalld/ufw — skipped. Router UPnP still handles WAN."
echo "    TCP ${TCP_PORTS[*]}  UDP ${UDP_PORTS[*]}  (never 47990)"
