#!/usr/bin/env bash
# Unattended GameSphere Import Tool update from GitHub Releases.
# Updates git / Flatpak / AppImage installs in place. Does not import games or
# restart Sunshine/Steam. Opt out: GAMESPHERE_AUTO_UPDATE=0
set -euo pipefail

if [[ "${GAMESPHERE_AUTO_UPDATE:-1}" =~ ^(0|false|no|off)$ ]]; then
  echo "GAMESPHERE_AUTO_UPDATE disabled — skip"
  exit 0
fi

INSTALL_DIR="${GAMESPHERE_IMPORT_DIR:-$HOME/.local/share/gamesphere-import-tool}"
FLATPAK_ID="io.github.trevlars.GamesphereImportTool"
APPIMAGE="${GAMESPHERE_APPIMAGE:-$HOME/.local/bin/GameSphere-Import-Tool.AppImage}"
API="https://api.github.com/repos/trevlars/Gamesphere-Import-Tool/releases?per_page=20"

META="$(mktemp)"
cleanup() { rm -f "$META"; }
trap cleanup EXIT

python3 - "$META" "$API" <<'PY'
import json, sys, urllib.request

dest, api = sys.argv[1], sys.argv[2]
req = urllib.request.Request(
    api,
    headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "GameSphere-Import-Tool-updater",
        "X-GitHub-Api-Version": "2022-11-28",
    },
)

def parse(tag: str):
    raw = (tag or "").lstrip("vV")
    parts = []
    for chunk in raw.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit()) or "0"
        parts.append(int(digits))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])

def write(**kwargs):
    with open(dest, "w", encoding="utf-8") as fh:
        for key, value in kwargs.items():
            value = (value or "").replace("'", "'\"'\"'")
            fh.write(f"{key}='{value}'\n")

try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        rels = json.loads(resp.read().decode("utf-8"))
except Exception as exc:
    write(ERROR=str(exc), TAG="", INSTALL_SH="", FLATPAK_URL="", APPIMAGE_URL="")
    raise SystemExit(0)

best = None
best_ver = (0, 0, 0)
if isinstance(rels, list):
    for rel in rels:
        if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
            continue
        tag = rel.get("tag_name") or ""
        if not tag:
            continue
        ver = parse(tag)
        if best is None or ver > best_ver:
            best, best_ver = rel, ver

if not best:
    write(ERROR="No GitHub Releases found", TAG="", INSTALL_SH="", FLATPAK_URL="", APPIMAGE_URL="")
    raise SystemExit(0)

urls = {}
for asset in best.get("assets") or []:
    name = asset.get("name") or ""
    url = asset.get("browser_download_url") or ""
    if name and url:
        urls[name] = url

app_url = ""
for name, url in urls.items():
    if name.lower().endswith(".appimage"):
        app_url = url
        break

write(
    ERROR="",
    TAG=best.get("tag_name") or "",
    INSTALL_SH=urls.get("install-linux.sh", ""),
    FLATPAK_URL=urls.get("io.github.trevlars.GamesphereImportTool.flatpak", ""),
    APPIMAGE_URL=app_url,
)
PY

# shellcheck disable=SC1090
source "$META"
if [[ -n "${ERROR:-}" ]]; then
  echo "Update check skipped: $ERROR"
  exit 0
fi
if [[ -z "${TAG:-}" ]]; then
  echo "No release tag from GitHub"
  exit 0
fi

echo "==> Latest GitHub release: $TAG"

is_newer() {
  python3 -c "
def p(t):
    t = (t or '').lstrip('vV')
    parts = []
    for c in t.split('.'):
        n = ''.join(ch for ch in c if ch.isdigit()) or '0'
        parts.append(int(n))
    parts += [0, 0, 0]
    return tuple(parts[:3])
import sys
raise SystemExit(0 if p(sys.argv[1]) > p(sys.argv[2]) else 1)
" "$1" "$2"
}

local_git_ver() {
  python3 -c "import sys; sys.path.insert(0, sys.argv[1]); from gs_version import __version__; print(__version__)" "$1" 2>/dev/null || echo "0.0.0"
}

updated=0

if [[ -d "$INSTALL_DIR/.git" ]]; then
  LOCAL="$(local_git_ver "$INSTALL_DIR")"
  if is_newer "$TAG" "$LOCAL"; then
    echo "==> Updating git install $LOCAL → $TAG"
    TMP="$(mktemp -d)"
    SCRIPT="$INSTALL_DIR/scripts/install-linux.sh"
    if [[ -n "${INSTALL_SH:-}" ]]; then
      curl -fsSL "$INSTALL_SH" -o "$TMP/install-linux.sh"
      chmod +x "$TMP/install-linux.sh"
      SCRIPT="$TMP/install-linux.sh"
    fi
    GAMESPHERE_IMPORT_REF="$TAG" \
      GAMESPHERE_IMPORT_DIR="$INSTALL_DIR" \
      GAMESPHERE_SKIP_UPDATE_TIMER=1 \
      bash "$SCRIPT"
    updated=1
  else
    echo "==> Git install already $LOCAL"
  fi
fi

if command -v flatpak >/dev/null 2>&1 && flatpak info --user "$FLATPAK_ID" >/dev/null 2>&1; then
  CUR="$(flatpak info --user "$FLATPAK_ID" 2>/dev/null | awk -F': *' '/^Version:/ {print $2; exit}')"
  CUR="${CUR:-0.0.0}"
  if is_newer "$TAG" "$CUR" && [[ -n "${FLATPAK_URL:-}" ]]; then
    echo "==> Updating Flatpak $CUR → $TAG"
    BUNDLE="$(mktemp "${TMPDIR:-/tmp}/gs-import.XXXXXX.flatpak")"
    curl -fsSL "$FLATPAK_URL" -o "$BUNDLE"
    flatpak install --user -y "$BUNDLE"
    rm -f "$BUNDLE"
    updated=1
  else
    echo "==> Flatpak already $CUR"
  fi
fi

if [[ -f "$APPIMAGE" ]] && [[ -n "${APPIMAGE_URL:-}" ]]; then
  CUR="$("$APPIMAGE" --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
  CUR="${CUR:-0.0.0}"
  if is_newer "$TAG" "$CUR"; then
    echo "==> Updating AppImage $CUR → $TAG"
    TMP_IMG="${APPIMAGE}.new"
    curl -fsSL "$APPIMAGE_URL" -o "$TMP_IMG"
    chmod +x "$TMP_IMG"
    mv -f "$TMP_IMG" "$APPIMAGE"
    updated=1
  else
    echo "==> AppImage already $CUR"
  fi
fi

if [[ "$updated" -eq 0 ]]; then
  echo "==> Already up to date ($TAG), or no Import Tool install found."
fi
exit 0
