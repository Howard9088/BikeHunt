"""Official ASSOS, PNS and KASK product pages; parse data, never execute scripts.

These parsers deliberately do not invent shipping, taxes, missing variant prices,
or availability. KASK publishes only the concretely selected SKU on each page;
the other displayed size buttons do not prove that those sizes are in stock.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import unquote, urljoin, urlsplit

from pydantic import ValidationError
from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import evidence, money, offer_id
from app.collectors.variants import formatted_money


def _object_after(text: str, marker: str, *, undefined: bool = False):
    """Read one literal JSON value after an observed marker, without JS eval.

    ASSOS serializes undefined values. Only that unquoted literal is replaced;
    quoted strings (including escaped quotes) are preserved verbatim.
    """
    position = text.find(marker)
    if position < 0:
        return None
    raw = text[position + len(marker):].lstrip()
    if undefined:
        raw = re.sub(r'"(?:[^"\\]|\\.)*"|\bundefined\b',
                     lambda m: "null" if m.group() == "undefined" else m.group(), raw)
    try:
        value, _ = json.JSONDecoder().raw_decode(raw)
        return value
    except (ValueError, TypeError):
        return None


def _rsc_text(page: Selector) -> str:
    chunks = []
    for script in page.css("script::text").getall():
        if not script.strip().startswith("self.__next_f.push("):
            continue
        data = _object_after(script, "self.__next_f.push(")
        if isinstance(data, list) and len(data) > 1 and isinstance(data[1], str):
            chunks.append(data[1])
    return "".join(chunks)


def _same_host(url: str, page_url: str) -> bool:
    return urlsplit(url).scheme == "https" and urlsplit(url).hostname == urlsplit(page_url).hostname


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _original(value, currency: str, current):
    result = money(value, currency)
    return result if result and result.amount > current.amount else None


def _base(source: dict, url: str, fetched_at: datetime) -> dict:
    return dict(source_code=source["code"], source_name=source["name"], url=url,
                fetched_at=fetched_at, sales_region=source.get("sales_region", ""),
                shipping_to_china=evidence(source, "china_shipping"),
                china_issued_card=evidence(source, "china_credit_card"))


def parse_pns(html: str, source: dict, page_url: str, fetched_at: datetime) -> list[Offer]:
    """PNS's product-scoped RSC commerce data, not recommendation tile prices."""
    page = Selector(html)
    rsc = _rsc_text(page)
    product = _object_after(rsc, '"shopifyProduct":')
    detail = _object_after(rsc, '"sanityProduct":')
    if not isinstance(product, dict) or not isinstance(detail, dict):
        return []
    handle = _text(product.get("handle"))
    if (not handle or handle != detail.get("handle")
            or product.get("id") != detail.get("gid")
            or unquote(urlsplit(page_url).path).rstrip("/").rsplit("/", 1)[-1] != handle):
        return []
    name = _text(detail.get("title")) or _text(product.get("title"))
    variants = product.get("variants")
    if not name or not isinstance(variants, list):
        return []
    image = (product.get("featuredImage") or {}).get("url")
    gender = (detail.get("selfProductGrid") or {}).get("gender")
    color = _text(detail.get("color")) or None
    tags = (detail.get("selfProductGrid") or {}).get("tags") or {}
    blocked = (tags.get("forceSoldOut") is True or tags.get("isComingSoon") is True
               or product.get("availableForSale") is False)
    requirements = []
    if tags.get("isComingSoon") is True:
        requirements.append("官方标注即将发售，当前不可下单")
    if "preorder_true" in (product.get("tags") or []):
        requirements.append("官方预售商品，发货时间需核实")
    icc = detail.get("iccMeta") or {}
    if icc.get("iccExclusive") is True:
        try:
            general_date = datetime.fromisoformat(icc.get("availableForEveryone", "").replace("Z", "+00:00"))
            restricted = general_date > fetched_at
        except (TypeError, ValueError):
            restricted = True
        if restricted:
            requirements.append("ICC 会员提前购或会员专享，需核对本人资格")
    result = []
    seen = set()
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_id = _text(variant.get("id"))
        options = {str(v.get("name", "")).casefold(): _text(v.get("value"))
                   for v in variant.get("selectedOptions", []) if isinstance(v, dict)}
        size = options.get("size")
        quoted = variant.get("price") or {}
        price = money(quoted.get("amount"), quoted.get("currencyCode"))
        if (not variant_id or variant_id in seen or not size or price is None
                or source.get("currency", price.currency) != price.currency):
            continue
        seen.add(variant_id)
        available = variant.get("availableForSale")
        stock = ("out_of_stock" if blocked or available is False else
                 "in_stock" if available is True and not requirements else "unknown")
        original = variant.get("compareAtPrice") or {}
        original_price = (_original(original.get("amount"), price.currency, price)
                          if original.get("currencyCode") == price.currency else None)
        # Shopify IDs are source identifiers, not manufacturer model numbers.
        identity = ProductIdentity(brand="Pas Normal Studios", model=name, size=size,
                                   color=options.get("color") or color, gender=gender)
        result.append(Offer(**_base(source, page_url, fetched_at),
                            offer_id=offer_id(source["code"], page_url, variant_id),
                            name=name, identity=identity, price=price,
                            original_price=original_price, stock=stock, image=image,
                            family_hint=handle, purchase_requirements=requirements,
                            identity_evidence="PNS 官网当前商品 RSC：逐尺码 SKU、币种、价格及 availableForSale；未推断跨站型号"))
    return result


def _attr(product: dict, key: str):
    value = (product.get("attributes") or {}).get(key) or {}
    return value.get("value") if isinstance(value, dict) else None


def _assos_stock(inventory: dict) -> str:
    # Missing in_stock is NOT equivalent to false. Backorders are not on-hand stock.
    if inventory.get("in_stock") is False or inventory.get("saleable") is False:
        return "out_of_stock"
    if (inventory.get("in_stock") is True and inventory.get("saleable") is True
            and inventory.get("backorders") is not True):
        quantity = inventory.get("quantity")
        if isinstance(quantity, (int, float)) and not isinstance(quantity, bool) and quantity > 0:
            return "in_stock"
    return "unknown"


def parse_assos(html: str, source: dict, page_url: str, fetched_at: datetime) -> list[Offer]:
    """ASSOS Refilo state: each child carries its own price, SKU and inventory."""
    page = Selector(html)
    state = next((value for script in page.css("script::text").getall()
                  if isinstance(value := _object_after(script, "window.INITIAL_STATE =", undefined=True), dict)), None)
    if state is None:
        return []
    product = state.get("product") or {}
    name, sku = _text(product.get("name")), _text(product.get("sku"))
    store = state.get("store") or {}
    currency = (((store.get("config") or {}).get("general") or {}).get("default_currency"))
    url_key = _attr(product, "url_key")
    if (not name or not sku or product.get("enabled") != "1"
            or not url_key or urlsplit(page_url).path.rsplit("/", 1)[-1] != url_key + ".html"
            or source.get("currency", currency) != currency
            or str(_attr(product, "hide_price")) == "1"):
        return []
    # Independently verify the page's displayed structured quote currency.
    valid_ld = False
    for script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            item = json.loads(script)
        except ValueError:
            continue
        if not isinstance(item, dict) or item.get("@type") != "Product" or item.get("sku") != sku:
            continue
        quote = item.get("offers") or {}
        if isinstance(quote, dict) and quote.get("priceCurrency") == currency:
            valid_ld = money(quote.get("price"), currency) == money((product.get("pricing") or {}).get("final_price"), currency)
    if not valid_ld:
        return []
    image = page.css('meta[property="og:image"]::attr(content)').get()
    color = _text(_attr(product, "color_details")) or _text(_attr(product, "color_filter")) or None
    gender = _text(_attr(product, "gender")) or None
    children = product.get("childsProducts")
    if not isinstance(children, list):
        return []
    result, seen = [], set()
    for child in children:
        if not isinstance(child, dict):
            continue
        child_sku = _text(_attr(child, "sku"))
        size = _text(_attr(child, "size"))
        prices = child.get("pricing") or {}
        price = money(prices.get("final_price"), currency)
        if (not size or not child_sku or child_sku in seen or price is None
                or child_sku != sku + "." + size):
            continue
        seen.add(child_sku)
        identity_args = dict(brand="ASSOS", model=name, mpn=sku, size=size,
                             color=color, gender=gender)
        try:
            identity = ProductIdentity(**identity_args, gtin=_attr(child, "barcode"))
        except ValidationError:
            identity = ProductIdentity(**identity_args)
        stock = _assos_stock(child.get("inventory") or {})
        requirements = []
        if str(_attr(product, "disable_shop")) == "1" or str(_attr(child, "disable_shop")) == "1":
            stock = "out_of_stock"
        if str(_attr(product, "is_preorder")) == "1" or str(_attr(child, "is_preorder")) == "1":
            stock = "unknown"
            requirements.append("官方预售商品，发货时间需核实")
        result.append(Offer(**_base(source, page_url, fetched_at),
                            offer_id=offer_id(source["code"], page_url, child_sku),
                            name=name, identity=identity, price=price,
                            original_price=_original(prices.get("base_price"), currency, price),
                            stock=stock, image=image, family_hint=sku,
                            purchase_requirements=requirements,
                            identity_evidence="ASSOS 官网逐尺码制造商 SKU、校验条码、独立价格及库存；缺失库存不当作缺货"))
    return result


def parse_kask(html: str, source: dict, page_url: str, fetched_at: datetime) -> list[Offer]:
    """Only the selected SKU; visible size alternatives do not prove stock."""
    page = Selector(html)
    nodes = page.css(".product-detail[data-pid][data-absurl]")
    if not nodes or len({(n.attrib['data-pid'], n.attrib['data-absurl']) for n in nodes}) != 1:
        return []
    node = nodes[0]
    sku = node.attrib.get("data-pid", "")
    url = urljoin(page_url, node.attrib.get("data-absurl", ""))
    selected = node.css('[data-attr="size"] button.selected[data-attr-value]')
    if (not sku or not selected or not _same_host(url, page_url)
            or len({(n.attrib['data-attr-value'], str(n.get_all_text(strip=True))) for n in selected}) != 1):
        return []
    size = str(selected[0].get_all_text(strip=True)).strip()
    if not size or not sku.endswith("." + selected[0].attrib["data-attr-value"]):
        return []
    currencies = set()
    for value in page.css('#countrySelector-language-select option[selected]::attr(value)').getall():
        try:
            currencies.add(json.loads(value)["currencyCode"])
        except (ValueError, KeyError, TypeError):
            continue
    if len(currencies) != 1:
        return []
    currency = next(iter(currencies))
    if source.get("currency", currency) != currency:
        return []
    price_nodes = node.css(".price .sales .value[content]")
    if not price_nodes or len({(n.attrib['content'], str(n.get_all_text(strip=True))) for n in price_nodes}) != 1:
        return []
    price = money(price_nodes[0].attrib["content"], currency)
    visible = formatted_money(str(price_nodes[0].get_all_text(strip=True)), currency)
    if price is None or price != visible:
        return []
    product = None
    for script in page.css("script::text").getall():
        values = _object_after(script, "window.pdpProduct =")
        if isinstance(values, list):
            product = next((v for v in values if isinstance(v, dict) and v.get("item_variant") == sku), None)
            if product:
                break
    if not product or money(product.get("price"), currency) != price:
        return []
    name = _text(product.get("item_name"))
    headings = node.css("h1")
    if not name or not headings or str(headings[0].get_all_text(strip=True)).strip() != name:
        return []
    buttons = node.css("button.add-to-cart[data-pid]")
    stock = "unknown"
    if (buttons and len({(n.attrib.get('data-pid'), str(n.get_all_text(strip=True)),
                         'disabled' in n.attrib, n.attrib.get('aria-disabled'), n.attrib.get('class')) for n in buttons}) == 1
            and buttons[0].attrib.get("data-pid") == sku):
        button = buttons[0]
        label = str(button.get_all_text(strip=True)).strip()
        inactive = ("disabled" in button.attrib or button.attrib.get("aria-disabled") == "true"
                    or "disabled" in button.attrib.get("class", "").split())
        if not inactive and label == button.attrib.get("data-in-stock-label"):
            stock = "in_stock"
        elif inactive and label == button.attrib.get("data-out-stock-label"):
            stock = "out_of_stock"
    color = node.css("[data-selected-swatch]::attr(data-selected-swatch)").get()
    image = node.css('img[itemprop="image"]::attr(src)').get()
    # The complete selected SKU includes certification and color, so strip only
    # the independently verified numeric size suffix to form a manufacturer model.
    identity = ProductIdentity(brand="KASK", model=name, mpn=sku.rsplit(".", 1)[0],
                               size=size, color=color, gender="unisex")
    original = node.css(".price .strike-through .value::attr(content)").get()
    return [Offer(**_base(source, url, fetched_at),
                  offer_id=offer_id(source["code"], url, sku), name=name, identity=identity,
                  price=price, original_price=_original(original, currency, price),
                  stock=stock, image=urljoin(page_url, image) if image else None,
                  family_hint=str(product.get("item_id") or sku),
                  identity_evidence="KASK 官网当前选中 SKU、尺码、可见价格、市场币种与购物按钮一致；其他尺码未采集")]
