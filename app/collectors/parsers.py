"""Scrapling Selector 提取真实 JSON-LD 与 Team Cycles 公开商品数据。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

from loguru import logger
from pydantic import ValidationError
from scrapling.parser import Selector

from app.catalog.models import Evidence, Money, Offer, ProductIdentity

SIZE_CODE = re.compile(r"^(.+)_((?:XX)?[SL]|XS|XL|XXL|XXXL|M)$", re.I)


def manufacturer_identity(brand: str, name: str, sku: str,
                          size: str | None = None) -> ProductIdentity:
    """MAAP 官网 SKU 与经其官方代码核对的经销商代码归一；不用于任意商家 SKU。"""
    match = SIZE_CODE.fullmatch(sku)
    mpn = match.group(1) if match else sku
    variant_size = match.group(2).upper() if match else size
    color_code = mpn.rsplit("_", 1)[-1] if "_" in mpn else None
    return ProductIdentity(brand=brand, model=name, mpn=mpn or None,
                           size=variant_size, color=color_code)


def money(value, currency: str | None) -> Money | None:
    try:
        return Money(amount=Decimal(str(value)), currency=str(currency).upper())
    except (ValidationError, InvalidOperation, ValueError, TypeError):
        return None


def evidence(source: dict, key: str) -> Evidence:
    entry = source.get(key) or {}
    status = entry.get("status", "unknown")
    if status not in ("yes", "no"):
        status = "unknown"
    # 既有来源仅有文字/网址，未有时间的 yes 不可升级为核实通过。
    if status == "yes" and not entry.get("checked_at"):
        status = "unknown"
    return Evidence(status=status, url=entry.get("evidence_url"),
                    checked_at=entry.get("checked_at"), note=entry.get("note", ""),
                    content_hash=entry.get("content_hash"),
                    scope="site")


def stock_status(value: str | None) -> str:
    label = (value or "").rsplit("/", 1)[-1]
    return {"InStock": "in_stock", "OutOfStock": "out_of_stock",
            "SoldOut": "out_of_stock", "Discontinued": "out_of_stock"}.get(label, "unknown")


def offer_id(source: str, url: str, sku: str) -> str:
    return hashlib.sha256(f"{source}|{url}|{sku}".encode()).hexdigest()[:20]


def _nodes(data, parent: dict | None = None):
    if isinstance(data, list):
        for item in data:
            yield from _nodes(item, parent)
    elif isinstance(data, dict):
        kind = data.get("@type")
        types = kind if isinstance(kind, list) else [kind]
        if "Product" in types:
            yield data, parent or {}
        for field in ("@graph", "mainEntity", "hasVariant", "itemListElement"):
            if field in data:
                yield from _nodes(data[field], data)
        if "item" in data and isinstance(data["item"], dict):
            yield from _nodes(data["item"], parent)


def parse_jsonld(html: str, source: dict, page_url: str,
                 fetched_at: datetime) -> list[Offer]:
    """输出逐规格报价，忽略 AggregateOffer 的区间价格及非中国运费。"""
    page = Selector(html)
    result: list[Offer] = []
    for block in page.css('script[type="application/ld+json"]::text').getall():
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("无效 JSON-LD invalid_structured_data")
            continue
        for product, parent in _nodes(data):
            offers = product.get("offers", [])
            offers = offers if isinstance(offers, list) else [offers]
            brand = product.get("brand") or parent.get("brand") or source.get("brand", "")
            brand = brand.get("name", "") if isinstance(brand, dict) else str(brand)
            name = product.get("name") or parent.get("name") or ""
            if source.get("prefer_page_heading"):
                headings = page.css("h1")
                if headings:
                    name = str(headings[0].get_all_text(strip=True))
            image = product.get("image") or parent.get("image")
            image = image[0] if isinstance(image, list) and image else image
            if isinstance(image, dict):
                image = image.get("url")
            for quoted in offers:
                if not isinstance(quoted, dict) or "price" not in quoted:
                    continue
                price = money(quoted.get("price"), quoted.get("priceCurrency"))
                if price is None or not name or not brand:
                    logger.warning("隔离无效价格/名称/品牌 {}", page_url)
                    continue
                sku = str(quoted.get("sku") or product.get("sku") or "")
                official_maap_team = (source.get("manufacturer_sku_scheme") == "maap"
                                      and brand.casefold() == "maap"
                                      and urlsplit(page_url).hostname == "maap.cc")
                if source["code"] == "maap" or official_maap_team:
                    identity = manufacturer_identity(brand, name, sku)
                    identity_note = "MAAP 官网逐规格制造商 SKU"
                else:
                    gtin = next((str(product[k]) for k in
                                 ("gtin", "gtin13", "gtin14", "gtin12", "gtin8")
                                 if product.get(k)), None)
                    try:
                        identity = ProductIdentity(
                            brand=brand, model=parent.get("name") or name,
                            gtin=gtin, mpn=product.get("mpn"), size=product.get("size"),
                            color=product.get("color"),
                        )
                    except ValidationError:
                        logger.warning("忽略无效 GTIN {} {}", page_url, gtin)
                        identity = ProductIdentity(brand=brand, model=name,
                                                   size=product.get("size"),
                                                   color=product.get("color"))
                    identity_note = "公开 JSON-LD；商家 SKU 不用作跨站型号"
                url = urljoin(page_url, quoted.get("url") or product.get("url") or page_url)
                if official_maap_team:
                    # Headless MAAP JSON-LD declares a global canonical URL even
                    # when the actual quote was observed in a localized market.
                    url = page_url
                if urlsplit(url).hostname != urlsplit(page_url).hostname:
                    logger.warning("隔离跨来源商品链接 {}", url)
                    continue
                spec = quoted.get("priceSpecification") or {}
                original = money(spec.get("price"), spec.get("priceCurrency")) if isinstance(spec, dict) else None
                # MAAP 当前原价标签币种与现价不同，不能据此计算折扣。
                if original and original.currency != price.currency:
                    original = None
                shipping = None
                delivery = Evidence()
                details = quoted.get("shippingDetails") or []
                for detail in details if isinstance(details, list) else [details]:
                    dest = detail.get("shippingDestination", {}) if isinstance(detail, dict) else {}
                    if dest.get("addressCountry") == "CN":
                        rate = detail.get("shippingRate", {})
                        shipping = money(rate.get("value"), rate.get("currency"))
                        delivery = Evidence(status="yes", url=page_url,
                                            checked_at=fetched_at, scope="offer",
                                            note="商品结构化配送目的地为 CN；品牌限制仍需核实")
                site_delivery = evidence(source, "china_shipping")
                if site_delivery.status == "no" or (site_delivery.status == "yes" and source.get("type") in ("team_official", "brand_official")):
                    delivery = site_delivery
                    if site_delivery.status == "yes" and source.get("china_shipping_cost"):
                        shipping = money(source["china_shipping_cost"]["amount"],source["china_shipping_cost"]["currency"])
                result.append(Offer(
                    offer_id=offer_id(source["code"], url, sku),
                    source_code=source["code"], source_name=source["name"],
                    identity=identity, name=name, url=url,
                    image=urljoin(page_url, image) if isinstance(image, str) else None,
                    price=price, original_price=original, shipping=shipping,
                    stock=stock_status(quoted.get("availability")),
                    shipping_to_china=delivery,
                    china_issued_card=evidence(source, "china_credit_card"),
                    fetched_at=fetched_at, price_valid_until=quoted.get("priceValidUntil"),
                    family_hint=str(parent.get("productGroupID") or product.get("url") or page_url),
                    identity_evidence=identity_note,
                ))
    return list({item.offer_id: item for item in result}.values())


def parse_teamcycles(html: str, source: dict, page_url: str,
                     fetched_at: datetime) -> list[Offer]:
    """解析公开埋点 JSON 与选定 SKU；只解析数据，不执行远端脚本。"""
    page = Selector(html)
    product = None
    sku = None
    for script in page.css("script::text").getall():
        match = re.search(r'google_base_offer_id"\s*,\s*"([^"]+)"', script)
        if match:
            sku = match.group(1)
        marker = '"properties":'
        if marker in script and '"viewed product"' in script:
            try:
                properties, _ = json.JSONDecoder().raw_decode(script.split(marker, 1)[1])
                product = properties.get("product")
            except (json.JSONDecodeError, AttributeError, TypeError) as exc:
                logger.warning("Team Cycles 商品数据格式变更 invalid_structured_data")
    if not product or not sku:
        return []
    # 公开 summaryCode 与 MAAP 代码前缀必须一致，避免误用跟踪脚本的旧 SKU。
    visible_code = page.css("#summaryCode::text").get("").split(":", 1)[-1].strip()
    if not sku.startswith(visible_code + "_") or product.get("id") != visible_code:
        logger.warning("Team Cycles SKU 与公开型号冲突 {}", page_url)
        return []
    price = money(product.get("price"), product.get("currency"))
    if not price:
        return []
    identity = manufacturer_identity(product.get("productVendor", ""),
                                     product.get("title", ""), sku)
    return [Offer(
        offer_id=offer_id(source["code"], page_url, sku),
        source_code=source["code"], source_name=source["name"],
        identity=identity, name=product["title"], url=page_url,
        image=product.get("imageUrl"), price=price,
        original_price=money(product.get("oldPrice"), product.get("currency")),
        stock="out_of_stock" if product.get("status") == "notAvailable" else "unknown",
        shipping_to_china=evidence(source, "china_shipping"),
        china_issued_card=evidence(source, "china_credit_card"),
        fetched_at=fetched_at, family_hint=visible_code,
        identity_evidence="公开 summaryCode、选定 SKU 与 MAAP 官网制造商代码一致",
    )]
