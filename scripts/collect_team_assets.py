"""固化从车队官网实际取得的标志；不生成、不猜测 Logo URL。"""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import certifi
from loguru import logger
from scrapling.parser import Selector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.catalog.storage import atomic_json

SELECTORS = {
    "alpecin": ('img[alt="logo"]', "outline"),
    "bahrain": (".c-site-header__branding svg", "light"),
    "decathlon": ("#logo img", "light"),
    "ef": ("svg.ef-svg", "light"),
    "groupama": ('img[src*="logo-2026"]', "light"),
    "ineos": ('svg[aria-label="Netcompany Logo"]', "dark"),
    "lidl_trek": (".logo-lidltrek svg", "light"),
    "lotto": ("img.head-logo-image", "light"),
    "movistar": ('img[src*="movistarteam-logo-blanco"]', "dark"),
    "nsn": ("img.site-logo", "light"),
    "redbull": ('img[alt="Red Bull Bora hansgrohe logo dark"]', "light"),
    "soudal": ("img.Header-logo-image", "light"),
    "jayco": ("img.logo_image", "dark"),
    "picnic": ("img.custom-logo", "light"),
    "visma": ("img.site-logo__image--logo", "light"),
    "uae": ("img.uae-logo-img", "light"),
    "unox": ('img[alt="Uno-X Mobility"]', "light"),
    "astana": ('[class*="MainBanner_logo"] svg', "dark"),
}


def clean_svg(raw: str, white: bool = False) -> bytes:
    """恢复 HTML 解析器的小写 SVG 属性；剔除可执行或远端依赖。"""
    raw = re.sub(r"<!DOCTYPE[^>]*>", "", raw, flags=re.I)
    raw = raw.replace("viewbox=", "viewBox=").replace("preserveaspectratio=", "preserveAspectRatio=")
    raw = re.sub(r"(<svg\b[^>]*?)\s(?:width|height)=\"[^\"]*\"", r"\1", raw, count=1)
    raw = re.sub(r"(<svg\b[^>]*?)\s(?:width|height)=\"[^\"]*\"", r"\1", raw, count=1)
    for tag in ("clipPath", "linearGradient", "radialGradient"):
        raw = re.sub(r"(<\/?)" + tag.lower() + r"\b", r"\1" + tag, raw)
    for key in ("gradientUnits", "gradientTransform", "clipPathUnits"):
        raw = raw.replace(key.lower() + "=", key + "=")
    raw = re.sub(r"\s(?:class|style|width|height)=\"[^\"]*\"", "", raw, count=4) if white else raw
    if white:
        raw = raw.replace("currentColor", "#ffffff")
    if re.search(r"<script|<foreignObject|\son\w+=|<!ENTITY|(?:href|src)=\"https?", raw, re.I):
        raise ValueError("Logo SVG contains executable or external content")
    return raw.encode("utf-8")


def download(url: str) -> tuple[bytes, str]:
    """只下载官网 DOM 指定的图片，HTTPS、大小限制、指数退避。"""
    if urlsplit(url).scheme != "https":
        raise ValueError("Logo source must use HTTPS")
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent":"BikeHunt/0.4", "Accept":"image/*"})
            with urllib.request.urlopen(request, timeout=15, context=ssl.create_default_context(cafile=certifi.where())) as response:
                body = response.read(2_000_001)
                mime = response.headers.get_content_type()
            if len(body) > 2_000_000:
                raise ValueError("Logo image exceeds size limit")
            if body.startswith(b"\x89PNG"):
                extension = "png"
            elif body.startswith(b"\xff\xd8"):
                extension = "jpg"
            elif body.startswith(b"RIFF") and body[8:12] == b"WEBP":
                extension = "webp"
            elif "<svg" in body[:2000].decode("utf-8", errors="ignore"):
                body, extension = clean_svg(body.decode("utf-8")), "svg"
            else:
                raise ValueError("Logo response is not a supported image: " + mime)
            return body, extension
        except Exception as exc:
            logger.warning("Logo 下载失败 {} attempt={} {}", urlsplit(url).hostname, attempt+1, type(exc).__name__)
            if attempt == 2 or isinstance(exc, ValueError):
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Download exhausted")


def main() -> None:
    inventory = json.loads((ROOT/"storage/logo_sources/inventory.json").read_text(encoding="utf-8"))
    teams = json.loads((ROOT/"data/directories.json").read_text(encoding="utf-8"))
    assets = ROOT/"web/assets/teams"
    assets.mkdir(parents=True, exist_ok=True)
    manifest = []
    overrides = json.loads((ROOT/"data/team_logo_overrides.json").read_text(encoding="utf-8"))

    def capture(source: dict) -> dict:
        code = source["code"]
        selector, theme = SELECTORS[code]
        if code in overrides:
            override = overrides[code]
            body, extension = download(override["url"])
            digest = hashlib.sha256(body).hexdigest()[:10]
            name = f"{code}_mark_{digest}.{extension}"
            (assets/name).write_bytes(body)
            return {"code":code, "logo_images":["/web/assets/teams/"+name],
                    "logo_theme":override["theme"], "logo_source_urls":[override["url"]],
                    "logo_evidence_url":override["evidence_url"],
                    "logo_checked_at":datetime.now(timezone.utc).isoformat(),
                    "official_url":source["url"], "shops":source.get("shops",[])}
        page = Selector((ROOT/"storage/logo_sources"/f"{code}.html").read_text(encoding="utf-8"))
        nodes = page.css(selector)
        if not nodes:
            raise ValueError("Official team logo not found: " + code)
        nodes = nodes[:1]
        images, sources = [], []
        for index, node in enumerate(nodes):
            if str(node).startswith("<svg"):
                body, extension = clean_svg(str(node), theme == "dark"), "svg"
                origin = source["url"] + "#" + selector
            else:
                origin = urljoin(source["url"], node.attrib.get("data-src") or node.attrib["src"])
                body, extension = download(origin)
            digest = hashlib.sha256(body).hexdigest()[:10]
            name = f"{code}_{index}_{digest}.{extension}"
            (assets/name).write_bytes(body)
            images.append("/web/assets/teams/"+name)
            sources.append(origin)
        return {"code":code, "logo_images":images, "logo_theme":theme,
                "logo_source_urls":sources, "logo_checked_at":datetime.now(timezone.utc).isoformat(),
                "official_url":source["url"], "shops":source.get("shops",[])}

    with ThreadPoolExecutor(max_workers=4) as executor:
        for result in executor.map(capture, inventory):
            manifest.append(result)
            print(result["code"], len(result["logo_images"]), flush=True)
    for entry in teams["teams"]:
        record = next(r for r in manifest if r["code"] == entry["code"])
        entry.update({k:v for k,v in record.items() if k not in ("code", "shops")})
        shops = record["shops"]
        if shops and entry["code"] != "astana":
            entry["shop_url"] = shops[0]["url"]
            entry["shop_evidence_url"] = record["official_url"]
            entry["status"] = "verified_shop" if entry["code"] == "visma" else "official_link_found"
        elif entry["code"] == "astana":
            entry["shop_url"] = None
            entry["status"] = "shop_check_pending"
        if entry["code"] == "ineos":
            entry["name"] = "Netcompany INEOS Cycling Team"
            entry["name_zh"] = "Netcompany–英力士车队"
    atomic_json(ROOT/"data/directories.json", teams)
    atomic_json(ROOT/"storage/logo_sources/manifest.json", manifest)
    print("Saved 18 official team identities")


if __name__ == "__main__":
    main()
