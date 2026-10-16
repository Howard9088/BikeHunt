"""Exact public merchandise variants from selected forms and inert storefront data."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import _nodes, evidence, money, offer_id, parse_jsonld
from app.collectors.saved_team_catalogs import _decode_cache
from app.collectors.transport import CollectionError
from app.collectors.variants import formatted_money


def parse_topfanz(html: str, source: dict, page_url: str, fetched_at: datetime) -> list[Offer]:
    """Bind the selected size, cart variant ID, GTIN, stock and displayed gross price."""
    page = Selector(html)
    forms = page.css("form#product_configure_form")
    canonical = page.css('link[rel="canonical"]::attr(href)').get()
    prices = page.css("#productpage .product-info .price-new")
    if (
        urlsplit(page_url).hostname != "shops.topfanz.com"
        or len(forms) != 1
        or not canonical
        or canonical != page_url.split("?", 1)[0]
        or len(prices) != 1
    ):
        return []
    form = forms[0]
    action = urlsplit(form.attrib.get("action", ""))
    match = re.fullmatch(r"/en/cart/add/(\d+)/", action.path)
    selected = form.css('select[name^="option["] option[selected]')
    if (
        action.hostname != "shops.topfanz.com"
        or action.scheme != "https"
        or not match
        or len(selected) != 1
    ):
        return []
    choices = form.css('select[name^="option["]')
    if len(choices) != 1 or not re.fullmatch(r"option\[\d+\]", choices[0].attrib.get("name", "")):
        return []
    size = str(selected[0].get_all_text(strip=True)).strip()
    if not size or len(size) > 40:
        return []
    parents = parse_jsonld(html, source, canonical, fetched_at)
    if len(parents) != 1:
        return []
    parent = parents[0]
    products = [
        p
        for text in page.css('script[type="application/ld+json"]::text').getall()
        for p, _ in _nodes(json.loads(text))
    ]
    if len(products) != 1 or not parent.identity.gtin:
        return []
    quoted = products[0].get("offers") or {}
    count = quoted.get("inventoryLevel")
    if not isinstance(count, str) or not re.fullmatch(r"\d+", count):
        return []
    quantity = int(count)
    available = form.css(".add-cart")
    enabled = len(available) == 1 and not any(
        "disabled" in n.attrib
        or n.attrib.get("aria-disabled") == "true"
        or "disabled" in n.attrib.get("class", "").split()
        for n in available
    )
    if (parent.stock == "in_stock") != (quantity > 0 and enabled):
        return []
    price = formatted_money(str(prices[0].get_all_text(strip=True)), parent.price.currency)
    if price is None:
        return []
    url = canonical + "?id=" + match[1]
    image = parent.image
    image_file = re.search(r"/shops/\d+/files/\d+/", image or "")
    if image_file:
        for anchor in page.css('#productpage a[data-fancybox="group"][href]'):
            candidate = urlsplit(anchor.attrib["href"])
            if (
                candidate.scheme == "https"
                and candidate.hostname == "cdn.webshopapp.com"
                and candidate.path.startswith(image_file[0])
            ):
                image = candidate.geturl()
                break
    return [
        parent.model_copy(
            update={
                "offer_id": offer_id(source["code"], canonical, match[1]),
                "url": url,
                "image": image,
                "identity": parent.identity.model_copy(update={"size": size, "mpn": None}),
                "price": price,
                "original_price": None,
                "stock_quantity": quantity,
                "family_hint": canonical,
                "sales_region": "比利时商城 EUR 页面显示价；配送费用另核",
                "identity_evidence": "官方车队链接的Topfanz合作商城；实际选码页面的表单变体ID、独立GTIN、库存数和显示价格一致；不将含税与未税差额当折扣",
            }
        )
    ]


def topfanz_page_action(captures: list[bytes], max_variants: int = 12) -> Callable:
    """Select public size options only; block every cart request defensively."""

    def action(page) -> None:
        page.route("**/cart/**", lambda route: route.abort())
        selector = 'form#product_configure_form select[name^="option["]'
        page.wait_for_selector(selector, state="attached", timeout=15000)
        choices = page.locator(selector)
        ids = choices.locator("option").evaluate_all("nodes => nodes.map(n => n.value)")
        if len(ids) > max_variants or not all(re.fullmatch(r"\d+", v) for v in ids):
            raise CollectionError("Unbounded or malformed public size choices")
        captures.append(page.content().encode("utf-8"))
        for identifier in ids:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
                choices.select_option(identifier)
            page.wait_for_selector(selector, state="attached", timeout=10000)
            if choices.input_value() != identifier:
                raise CollectionError("Selected merchandise size did not resolve")
            captures.append(page.content().encode("utf-8"))

    return action


def _redbull_product(page: Selector) -> dict | None:
    """Decode only the published, anonymous product cache; never execute script."""
    scripts = page.css("script#state-body::text").getall()
    marker = "window.__INITIAL_DATA_CACHE__ = "
    if len(scripts) != 1 or scripts[0].count(marker) != 1:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(scripts[0].split(marker, 1)[1])
        entries = _decode_cache(payload["data"])
        products = [
            (key, value)
            for key, value in entries
            if re.fullmatch(r"product:[A-Za-z0-9-]+:anonymous", key)
        ]
        if len(products) != 1:
            return None
        key, value = products[0]
        product = value["data"]["response"]
        allowed_keys = {
            "product:" + product["code"] + ":anonymous",
            "product:" + product["baseProduct"] + ":anonymous",
        }
        if key != value["key"] or key not in allowed_keys:
            return None
        return product
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def parse_redbull_product(
    html: str, source: dict, page_url: str, fetched_at: datetime
) -> list[Offer]:
    """Bind every exact-size quote to an anonymous official product's selected color."""
    page = Selector(html)
    product = _redbull_product(page)
    split = urlsplit(page_url)
    if (
        not product
        or split.scheme != "https"
        or split.hostname != "www.redbullshop.com"
        or not split.path.startswith("/en-jp/p/")
    ):
        return []
    structured = [
        p
        for block in page.css('script[type="application/ld+json"]::text').getall()
        for p, _ in _nodes(json.loads(block))
    ]
    if len(structured) != 1:
        return []
    parent = structured[0]
    sku, base = product.get("code"), product.get("baseProduct")
    canonical = urlsplit(product.get("absoluteProductUrl", ""))
    options = product.get("baseOptions")
    if (
        parent.get("sku") != sku
        or parent.get("name") != product.get("name")
        or canonical.scheme != "https"
        or canonical.hostname != split.hostname
        or canonical.path != split.path
        or not isinstance(base, str)
        or split.path.rstrip("/").rsplit("/", 1)[-1] != base
        or not isinstance(options, list)
        or len(options) != 1
    ):
        return []
    asked = parse_qs(split.query).get("preselectedVariant")
    if asked and asked != [sku]:
        return []
    group = options[0]
    selected = group.get("selected") or {}
    selected_price = product.get("price") or {}
    currency = selected_price.get("currencyIso")
    price = money(selected_price.get("value"), currency)
    ld = parent.get("offers") or {}
    if (
        selected.get("code") != sku
        or (product.get("trackingData") or {}).get("id") != sku
        or price is None
        or price != money(ld.get("price"), ld.get("priceCurrency"))
        or ld.get("url") != product.get("absoluteProductUrl")
        or selected.get("priceData") != selected_price
        or currency != source.get("currency", currency)
    ):
        return []
    colors = [
        v for v in selected.get("variantOptionQualifiers", []) if v.get("qualifier") == "color"
    ]
    if len(colors) != 1 or not colors[0].get("value"):
        return []
    color = colors[0].get("colorNameEN") or colors[0].get("colorName") or colors[0]["value"]
    sizes = group.get("sizeOptions")
    if not isinstance(sizes, list) or not sizes or len(sizes) > 30:
        return []
    result, seen = [], set()
    for variant in sizes:
        code = variant.get("code")
        labels = [
            v for v in variant.get("variantOptionQualifiers", []) if v.get("qualifier") == "size"
        ]
        quoted = variant.get("priceData") or {}
        value = money(quoted.get("value"), quoted.get("currencyIso"))
        if (
            not isinstance(code, str)
            or not re.fullmatch(re.escape(base) + r"\d{3}", code)
            or code in seen
            or len(labels) != 1
            or labels[0].get("name") != product["name"]
            or not isinstance(labels[0].get("value"), str)
            or not labels[0]["value"]
            or value is None
            or value != price
        ):
            continue
        seen.add(code)
        stock_data = variant.get("stock") or {}
        count = stock_data.get("stockLevel")
        state = stock_data.get("statusInfo")
        numeric = type(count) is int and count >= 0 and stock_data.get("isValueRounded") is False
        stock = "unknown"
        if (
            product.get("preorder") is False
            and product.get("purchasable") is True
            and product.get("hasRestrictedVariants") is False
        ):
            if numeric and count > 0 and state == "inStock":
                stock = "in_stock"
            elif numeric and count == 0 and state == "outOfStock":
                stock = "out_of_stock"
        quantity = count if numeric and stock != "unknown" else None
        original = variant.get("oldPrice") or {}
        old = money(original.get("value"), original.get("currencyIso"))
        if old and (old.currency != value.currency or old.amount <= value.amount):
            old = None
        url = split._replace(query="preselectedVariant=" + code, fragment="").geturl()
        gender = {"U": "unisex", "M": "male", "F": "female"}.get(
            (product.get("gender") or {}).get("code")
        )
        identity = ProductIdentity(
            brand="Red Bull",
            model=product["name"],
            size=labels[0]["value"],
            color=color,
            gender=gender,
            gtin=product.get("ean") if code == sku else None,
        )
        result.append(
            Offer(
                offer_id=offer_id(source["code"], url, code),
                source_code=source["code"],
                source_name=source["name"],
                identity=identity,
                name=product["name"],
                url=url,
                image=(product.get("cloudinaryPrimaryImage") or {}).get("url"),
                price=value,
                original_price=old,
                stock=stock,
                stock_quantity=quantity,
                fetched_at=fetched_at,
                family_hint="redbull:" + base + ":" + colors[0]["value"],
                sales_region=source.get("sales_region", "日本站 JPY 报价"),
                shipping_to_china=evidence(source, "china_shipping"),
                china_issued_card=evidence(source, "china_credit_card"),
                purchase_requirements=(
                    ["官方标注预售；发货时间待核实"] if product.get("preorder") is True else []
                ),
                identity_evidence="Red Bull官方商品页匿名缓存；商品型号、默认SKU、市场价格与JSON-LD一致；当前颜色下每个尺码的独立SKU、价格、库存数分别核对",
            )
        )
    return result
