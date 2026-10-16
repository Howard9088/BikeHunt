"""Bind Specialized's public PDP prices to its independent online stock response."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError
from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import evidence, money, offer_id


def _objects(value: object) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _objects(item)


def _product_data(page: Selector) -> dict | None:
    """Decode inert RSC string records without evaluating JavaScript or following references."""
    chunks = []
    marker = "self.__next_f.push("
    for script in page.css("script::text").getall():
        if not script.startswith(marker):
            continue
        try:
            value, _ = json.JSONDecoder().raw_decode(script[len(marker) :])
            if value[0] == 1 and len(value) == 2 and isinstance(value[1], str):
                chunks.append(value[1])
        except (ValueError, TypeError, IndexError):
            continue
    text = "".join(chunks)
    if len(text) > 8_000_000:
        return None
    found = []
    for line in text.splitlines():
        try:
            _, record = line.split(":", 1)
            for item in _objects(json.loads(record)):
                if isinstance(item.get("getPDP"), dict) and isinstance(
                    item.get("dynamicData"), dict
                ):
                    found.append(item)
        except (ValueError, TypeError):
            continue
    return found[0] if len(found) == 1 else None


def parse_specialized(html: str, source: dict, page_url: str, fetched_at: datetime) -> list[Offer]:
    """Match product, color, SKU, size, USD amount/minor units and independent stock."""
    page, split = Selector(html), urlsplit(page_url)
    data = _product_data(page)
    if (
        not data
        or split.scheme != "https"
        or split.hostname != "www.specialized.com"
        or not split.path.startswith("/us/en/")
    ):
        return []
    product, dynamic = data["getPDP"], data["dynamicData"]
    code = product.get("code")
    if (
        not isinstance(code, str)
        or not code.isdigit()
        or dynamic.get("code") != code
        or split.path != "/us/en" + product.get("url", "")
        or not split.path.endswith("/p/" + code)
        or product.get("isBike") is not False
        or product.get("archived") is not False
        or product.get("endOfLife") is not False
        or product.get("brand") != "SPECIALIZED"
        or product.get("showAddToCartButton") is not True
        or dynamic.get("showAddToCartButton") is not True
    ):
        return []
    colors = product.get("colors") or []
    dynamic_colors = dynamic.get("colors") or []
    if not 1 <= len(colors) <= 20 or len({x.get("code") for x in dynamic_colors}) != len(
        dynamic_colors
    ):
        return []
    stocks = {x.get("code"): x for x in dynamic_colors}
    asked = parse_qs(split.query)
    if asked and (
        set(asked) != {"color"} or len(asked["color"]) != 1 or asked["color"][0] not in stocks
    ):
        return []
    result = []
    for color in colors:
        color_code = color.get("code", "")
        stock_color = stocks.get(color_code)
        if (
            not stock_color
            or not re.fullmatch(r"\d+-" + code, color_code)
            or color.get("preOrderable") is not False
            or not color.get("colorName")
        ):
            continue
        live = stock_color.get("sizes") or []
        if not live or len(live) > 40 or len({v.get("code") for v in live}) != len(live):
            continue
        live = {v["code"]: v for v in live}
        image = next(
            (
                url
                for url in page.css("img::attr(src)").getall()
                if urlsplit(url).hostname == "resources.specialized.com"
                and any(
                    "/image/" + x.get("code", "!") + "?" in url for x in color.get("images", [])
                )
            ),
            None,
        )
        seen = set()
        for size in color.get("sizes", []):
            skus = (size.get("skus") or {}).get("values")
            if not isinstance(skus, list) or len(skus) != 1:
                continue
            sku = skus[0]
            identifier = sku.get("code")
            stock = live.get(identifier)
            prices = sku.get("prices") or {}
            current = prices.get("special") or prices.get("regular") or {}
            price = money(current.get("raw"), current.get("currency"))
            if (
                not stock
                or identifier in seen
                or not isinstance(identifier, str)
                or not identifier.isdigit()
                or sku.get("skuCode") != identifier
                or sku.get("sku") != stock.get("sku")
                or sku.get("isBike") is not False
                or size.get("name") != sku.get("size")
                or (size.get("skus") or {}).get("name") != sku.get("size")
                or price is None
                or price.currency != "USD"
                or type(current.get("minorUnits")) is not int
                or price.amount * Decimal(100) != current["minorUnits"]
                or sku.get("availability") not in {"INSTOCK", "FEW", "OUTOFSTOCK"}
                or stock.get("inboundInventory") is not False
            ):
                continue
            seen.add(identifier)
            inventory = stock.get("stock") or {}
            count = inventory.get("stockLevel")
            numeric = (
                type(count) is int and count >= 0 and inventory.get("isValueRounded") is False
            )
            status = "unknown"
            if (
                numeric
                and count > 0
                and inventory.get("stockLevelStatus") in {"inStock", "lowStock"}
                and stock.get("availability") in {"INSTOCK", "FEW"}
                and sku["availability"] in {"INSTOCK", "FEW"}
            ):
                status = "in_stock"
            elif (
                numeric
                and count == 0
                and inventory.get("stockLevelStatus") == "outOfStock"
                and stock.get("availability") == "OUTOFSTOCK"
                and sku["availability"] == "OUTOFSTOCK"
            ):
                status = "out_of_stock"
            regular = prices.get("regular") or {}
            original = money(regular.get("raw"), regular.get("currency"))
            if original and (
                original.currency != price.currency
                or original.amount <= price.amount
                or type(regular.get("minorUnits")) is not int
                or original.amount * Decimal(100) != regular["minorUnits"]
            ):
                original = None
            try:
                identity = ProductIdentity(
                    brand="Specialized",
                    model=product["name"],
                    size=sku["size"],
                    color=color["colorName"],
                    gtin=sku.get("upc"),
                    gender="female" if product["name"].startswith("Women's ") else None,
                )
            except ValidationError:
                continue
            result.append(
                Offer(
                    offer_id=offer_id(source["code"], page_url.split("?", 1)[0], identifier),
                    source_code=source["code"],
                    source_name=source["name"],
                    name=product["name"],
                    identity=identity,
                    url=split._replace(query="color=" + color_code, fragment="").geturl(),
                    image=image,
                    price=price,
                    original_price=original,
                    stock=status,
                    stock_quantity=count if status != "unknown" else None,
                    fetched_at=fetched_at,
                    family_hint="specialized:" + code + ":" + color_code,
                    sales_region="US 市场 · USD 商品报价；配送另核",
                    shipping_to_china=evidence(source, "china_shipping"),
                    china_issued_card=evidence(source, "china_credit_card"),
                    identity_evidence="Specialized官方公开PDP与独立在线库存数据；型号、配色、尺码、SKU、UPC、金额与分单位交叉核对；不把其他颜色或预订库存算为现货",
                )
            )
    return result
