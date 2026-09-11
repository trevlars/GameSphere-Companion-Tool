"""
Store-native cover art fetching (no API keys required for most stores).

Cover resolution order adapted from StreamTweak
(https://github.com/FoggyBytes/StreamTweak) StoreCoverFetcher.cs — GPL-3.0.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import sqlite3
from typing import Dict, Optional
from urllib.parse import quote

import requests
from PIL import Image

GOOD_COVER_HEIGHT = 600
STEAM_CDN_LIBRARY_2X = "https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_600x900_2x.jpg"


def _save_image_bytes(content: bytes, dest_path: str, min_height: int = 0) -> bool:
    try:
        if len(content) < 500:
            return False
        image = Image.open(io.BytesIO(content))
        if min_height and image.height < min_height:
            pass
        image = Image.open(io.BytesIO(content))
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        image.save(dest_path, "PNG")
        return min_height == 0 or image.height >= min_height
    except Exception:
        return False


def _download_url(url: str, dest_path: str, min_height: int = 0) -> bool:
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return _save_image_bytes(response.content, dest_path, min_height)
    except Exception as exc:
        logging.debug("Cover download failed for %s: %s", url, exc)
        return False


def load_epic_catalog_urls() -> Dict[str, str]:
    result: Dict[str, str] = {}
    bin_path = os.path.join(
        os.environ.get("ProgramData", "C:\\ProgramData"),
        "Epic",
        "EpicGamesLauncher",
        "Data",
        "Catalog",
        "catcache.bin",
    )
    if not os.path.isfile(bin_path):
        return result
    try:
        with open(bin_path, "r", encoding="utf-8") as fh:
            raw = base64.b64decode(fh.read().strip())
        items = json.loads(raw.decode("utf-8"))
        if not isinstance(items, list):
            return result
        for item in items:
            catalog_id = item.get("id")
            if not catalog_id:
                continue
            best = None
            for img in item.get("keyImages") or []:
                url = img.get("url")
                if not url:
                    continue
                img_type = img.get("type")
                if img_type == "DieselGameBoxTall":
                    best = url
                    break
                if img_type == "DieselGameBox":
                    best = best or url
                else:
                    best = best or url
            if best:
                result[catalog_id] = best
    except Exception as exc:
        logging.debug("Epic catcache.bin read failed: %s", exc)
    return result


def load_ubisoft_thumb_images() -> Dict[str, str]:
    result: Dict[str, str] = {}
    config_path = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Ubisoft Game Launcher",
        "cache",
        "configuration",
        "configurations",
    )
    if not os.path.isfile(config_path):
        return result
    try:
        with open(config_path, "rb") as fh:
            content = fh.read().decode("iso-8859-1", errors="ignore")
        install_refs = re.finditer(r"Installs[\\/](\d+)[\\/]InstallDir", content)
        thumb_re = re.compile(r"thumb_image:\s*([a-f0-9]{20,}\.(?:jpg|png|webp))", re.I)
        for match in install_refs:
            install_id = match.group(1)
            if install_id in result:
                continue
            start = max(0, match.start() - 5000)
            before = content[start:match.start()]
            thumbs = list(thumb_re.finditer(before))
            if thumbs:
                result[install_id] = thumbs[-1].group(1)
    except OSError:
        pass
    return result


def load_battlenet_cover_urls() -> Dict[str, str]:
    result: Dict[str, str] = {}
    agg_path = os.path.join(
        os.environ.get("ProgramData", "C:\\ProgramData"),
        "Battle.net",
        "Agent",
        "aggregate.json",
    )
    if not os.path.isfile(agg_path):
        return result
    try:
        with open(agg_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for item in data.get("installed") or []:
            uid = item.get("product_id")
            if not uid:
                continue
            url = item.get("logo_art_uri") or item.get("box_art_uri")
            if url:
                result[uid] = url
    except (OSError, json.JSONDecodeError):
        pass
    return result


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def fetch_cover_via_steam_search(game_name: str, dest_path: str) -> bool:
    if not game_name:
        return False
    try:
        url = (
            "https://store.steampowered.com/api/storesearch/"
            f"?term={quote(game_name)}&l=english&cc=US"
        )
        data = requests.get(url, timeout=15).json()
        items = data.get("items") or []
        if not items:
            return False
        target = _normalize_name(game_name)
        app_id = None
        for item in items:
            result_name = item.get("name") or ""
            if _normalize_name(result_name) == target:
                app_id = item.get("id")
                break
        if not app_id:
            for item in items:
                result_name = item.get("name") or ""
                rn = _normalize_name(result_name)
                if target in rn or rn in target:
                    app_id = item.get("id")
                    break
        if not app_id:
            return False
        cdn = STEAM_CDN_LIBRARY_2X.format(app_id=app_id)
        return _download_url(cdn, dest_path, GOOD_COVER_HEIGHT)
    except Exception as exc:
        logging.debug("Steam search cover failed for %s: %s", game_name, exc)
        return False


def _try_gog_local_cover(product_id: str, dest_path: str) -> bool:
    program_data = os.environ.get("ProgramData", "C:\\ProgramData")
    db_path = os.path.join(program_data, "GOG.com", "Galaxy", "storage", "galaxy-2.0.db")
    if not os.path.isfile(db_path):
        return False
    release_key = f"gog_{product_id}"
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM WebCacheResourceTypes WHERE type = 'verticalCover' LIMIT 1"
        )
        row = cur.fetchone()
        vertical_type = row[0] if row else 3
        cur.execute(
            "SELECT id, userId FROM WebCache WHERE releaseKey = ?",
            (release_key,),
        )
        for web_cache_id, user_id in cur.fetchall():
            cur.execute(
                "SELECT filename FROM WebCacheResources WHERE webCacheId = ? "
                "AND webCacheResourceTypeId = ? LIMIT 1",
                (web_cache_id, vertical_type),
            )
            fname_row = cur.fetchone()
            if not fname_row:
                continue
            local_path = os.path.join(
                program_data,
                "GOG.com",
                "Galaxy",
                "webcache",
                str(user_id),
                "gog",
                product_id,
                fname_row[0],
            )
            if os.path.isfile(local_path):
                with open(local_path, "rb") as fh:
                    if _save_image_bytes(fh.read(), dest_path, GOOD_COVER_HEIGHT):
                        conn.close()
                        return True
        conn.close()
    except sqlite3.Error as exc:
        logging.debug("GOG local cover DB read failed: %s", exc)
    return False


def _try_gog_remote_cover(product_id: str, game_name: str, dest_path: str) -> bool:
    try:
        api_url = f"https://api.gog.com/products/{quote(product_id)}"
        data = requests.get(api_url, timeout=15).json()
        logo = (data.get("images") or {}).get("logo")
        if logo:
            cover_url = f"https:{logo.replace('glx_logo', 'glx_vertical_cover')}"
            return _download_url(cover_url, dest_path, GOOD_COVER_HEIGHT)
    except Exception:
        pass
    try:
        search_url = (
            "https://catalog.gog.com/v1/catalog?productType=in:game&limit=5"
            f"&query=like:{quote(game_name)}"
        )
        data = requests.get(search_url, timeout=15).json()
        for product in data.get("products") or []:
            if str(product.get("id")) != str(product_id):
                continue
            cover = product.get("coverVertical")
            if cover:
                return _download_url(cover, dest_path, GOOD_COVER_HEIGHT)
    except Exception:
        pass
    return False


def fetch_store_cover(
    game_info: dict,
    grids_folder: str,
    file_safe_id: str,
    fallback_fetch_by_name=None,
) -> Optional[str]:
    """
    Fetch cover art using store-native sources first, then Steam Store search.
    fallback_fetch_by_name(name, api_key, grids_folder, file_safe_id) is optional
    (SteamGridDB / existing Import Tool helper).
    """
    dest = os.path.join(grids_folder, f"{file_safe_id}.png")
    if os.path.isfile(dest):
        try:
            with Image.open(dest) as img:
                if img.height >= GOOD_COVER_HEIGHT:
                    return dest
        except Exception:
            pass

    store = (game_info.get("store") or "").strip()
    store_id = game_info.get("store_id") or game_info.get("catalog_item_id")
    name = game_info.get("name") or ""

    epic_urls = load_epic_catalog_urls() if store == "Epic Games" else {}
    ubisoft_thumbs = load_ubisoft_thumb_images() if store == "Ubisoft Connect" else {}
    bnet_urls = load_battlenet_cover_urls() if store == "Battle.net" else {}

    if store == "Epic Games" and store_id and store_id in epic_urls:
        if _download_url(epic_urls[store_id], dest, GOOD_COVER_HEIGHT):
            return dest

    if store == "GOG" and store_id:
        if _try_gog_local_cover(store_id, dest):
            return dest
        if fetch_cover_via_steam_search(name, dest):
            return dest
        if _try_gog_remote_cover(store_id, name, dest):
            return dest

    if store == "Ubisoft Connect" and store_id:
        if fetch_cover_via_steam_search(name, dest):
            return dest
        thumb = ubisoft_thumbs.get(store_id)
        if thumb:
            url = f"https://ubistatic3-a.akamaihd.net/orbit/uplay_launcher_3_0/assets/{thumb}"
            if _download_url(url, dest):
                return dest

    if store == "Battle.net" and store_id:
        if fetch_cover_via_steam_search(name, dest):
            return dest
        url = bnet_urls.get(store_id)
        if url and _download_url(url, dest):
            return dest

    if store in ("Xbox", "EA App", "Epic Games"):
        if fetch_cover_via_steam_search(name, dest):
            return dest

    if fallback_fetch_by_name:
        path = fallback_fetch_by_name(name, file_safe_id)
        if path:
            return path
    return dest if os.path.isfile(dest) else None
