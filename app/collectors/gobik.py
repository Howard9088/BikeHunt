"""Gobik's public, size-bound HTML quotes for an explicitly scoped ES/EUR sample.

No Storefront credentials, API calls, browser state or historical stock are used.
The product's own size-picker JSON is checked against its JSON-LD by variant ID,
SKU, price and availability. Every network request belongs to PublicPageFetcher.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

from pydantic import ValidationError
from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.fetch_policy import CapturedPage, FetchPolicy
from app.collectors.parsers import evidence, money, offer_id, stock_status
from app.collectors.shopify import shopify_market_country, shopify_market_currency
from app.collectors.transport import CollectionError, PublicPageFetcher, SourceDeferred

MAX_PRODUCTS = 25
MAX_VARIANTS = 40
_SIZE_LABELS = {"choose the size", "choose your size"}

# Deliberately finite diagnostics: CI may reveal a failure category, never page
# HTML, arbitrary exception text, request parameters, cookies or source tokens.
_DIAGNOSTIC_MESSAGES = {
    "gobik_market_currency_unverified": {"Gobik active market currency is unverified"},
    "gobik_market_country_unverified": {"Gobik active market country is unverified"},
    "gobik_market_currency_mismatch": {"Gobik active market currency is not EUR"},
    "gobik_market_country_mismatch": {"Gobik active market country is not ES"},
    "gobik_localization_form_unverified": {"Gobik official Spain localization form is missing or ambiguous"},
    "gobik_localization_failed": {"Gobik official Spain localization failed"},
    "gobik_localization_not_persistent": {"Gobik Spain localization did not persist"},
    "gobik_product_identity_unverified": {
        "Gobik requires an exact official English product URL",
        "Gobik canonical product identity is missing or different",
        "Gobik product information container is ambiguous",
        "Gobik product name or official brand is missing",
        "Gobik product ID is missing or contradictory",
        "Gobik structured offer belongs to another product",
    },
    "gobik_structured_data_unverified": {
        "Gobik product JSON-LD is missing or ambiguous",
        "Gobik per-variant structured offers are missing",
        "Gobik per-variant structured offer is malformed",
    },
    "gobik_size_picker_unverified": {
        "Gobik size-picker does not belong to this product",
        "Gobik size-picker JSON is malformed",
        "Gobik size-picker variants are missing or unbounded",
        "Gobik requires one explicitly labelled size dimension",
        "Gobik size controls are missing or duplicated",
        "Gobik variant list does not match the size controls",
    },
    "gobik_variant_identity_unverified": {
        "Gobik structured variant ID is missing or duplicated",
        "Gobik structured and picker variant counts differ",
        "Gobik picker variant is malformed",
        "Gobik exact variant/size identity is missing or ambiguous",
        "Gobik exact variant SKU does not match structured evidence",
        "Gobik exact variant barcode conflicts with structured evidence",
        "Gobik exact variant GTIN is invalid",
    },
    "gobik_variant_price_unverified": {"Gobik variant price/currency does not match structured evidence"},
    "gobik_color_unverified": {
        "Gobik product color is malformed", "Gobik color picker is ambiguous",
        "Gobik selected color does not match the exact product",
        "Gobik selected color is missing or contradictory",
    },
    "gobik_reconciliation_unverified": {
        "Gobik fresh product has ambiguous size identities",
        "Gobik previous product family or size match is ambiguous",
        "Gobik previous family is not semantically identical to the current product",
        "Gobik previous manufacturer variant identity conflicts",
    },
    "gobik_collection_scope_unverified": {
        "Gobik parser requires the Gobik source",
        "Gobik observation time requires a timezone",
        "Gobik reconciliation received another source",
        "Gobik max_products must be from 1 to 25",
        "Gobik requires a unique, bounded explicit product URL list",
        "Gobik product remains paused after an unresolved access failure",
        "Gobik product redirected outside the exact source/market path",
    },
}
GOBIK_DIAGNOSTIC_CODES = frozenset(_DIAGNOSTIC_MESSAGES) | {"gobik_validation_failed"}
PUBLIC_DIAGNOSTICS = GOBIK_DIAGNOSTIC_CODES


class GobikCollectionError(CollectionError):
    """A normal closed-failure exception with one safe public classification."""

    def __init__(self, message: str):
        super().__init__(message)
        self.diagnostic_code = next((code for code, messages in _DIAGNOSTIC_MESSAGES.items()
                                     if message in messages), "gobik_validation_failed")
        self.diagnostics = [self.diagnostic_code]


@dataclass
class GobikCollectionResult:
    offers: list[Offer] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)


def _text(value: str) -> str:
    return " ".join(value.split())


def _product_url(url: str, *, variant_allowed: bool = True) -> str:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (parsed.scheme != "https" or parsed.netloc != "gobik.com"
            or parsed.fragment
            or not re.fullmatch(r"/en/products/[a-z0-9][a-z0-9-]*", parsed.path)
            or (parsed.query and (not variant_allowed or set(query) != {"variant"}
                or len(query["variant"]) != 1 or not query["variant"][0].isdigit()))):
        raise GobikCollectionError("Gobik requires an exact official English product URL")
    return "https://gobik.com" + parsed.path


def _objects(value):
    if isinstance(value, dict):
        yield value
        for key in ("@graph", "mainEntity", "hasVariant"):
            yield from _objects(value.get(key))
    elif isinstance(value, list):
        for item in value:
            yield from _objects(item)


def _active_market(html: str) -> tuple[str, str]:
    try:
        currency = shopify_market_currency(html)
    except CollectionError as exc:
        raise GobikCollectionError("Gobik active market currency is unverified") from exc
    try:
        country = shopify_market_country(html)
    except CollectionError as exc:
        raise GobikCollectionError("Gobik active market country is unverified") from exc
    if country is None:
        raise GobikCollectionError("Gobik active market country is unverified")
    return country, currency


def _spain_localization_form(html: str, product_url: str) -> tuple[str, dict[str, str]]:
    """Read the exposed Spain option; never construct cookies or guess a route."""
    expected_action = 'https://gobik.com/en/localization'
    required = {'form_type': 'localization', 'utf8': '✓', '_method': 'put',
                'return_to': urlsplit(product_url).path, 'country_code': 'ES'}
    candidates = []
    for form in Selector(html).css('form[action]'):
        if (urljoin(product_url, form.attrib.get('action', '')) != expected_action
                or form.attrib.get('method', '').casefold() != 'post'
                or form.attrib.get('enctype', '').casefold() != 'multipart/form-data'
                or not form.css('[name="country_code"]')):
            continue
        choices = form.css('option[value="ES"], a[data-value="ES"]')
        if not any(re.search(r'\bSpain\b', choice.get_all_text(strip=True), re.I)
                   and re.search(r'\bEUR\b', choice.get_all_text(strip=True)) for choice in choices):
            continue
        fields = {}
        invalid = False
        for node in form.css('input[name]'):
            key, value = node.attrib.get('name'), node.attrib.get('value', '')
            if node.attrib.get('type', '').casefold() != 'hidden' or key in fields or key not in required:
                invalid = True
                break
            fields[key] = value
        # The only changed field is the exact published Spain country option.
        fields['country_code'] = 'ES'
        if not invalid and fields == required:
            candidates.append((expected_action, fields))
    signatures = {(action, tuple(sorted(fields.items()))) for action, fields in candidates}
    if len(signatures) != 1:
        raise GobikCollectionError('Gobik official Spain localization form is missing or ambiguous')
    return candidates[0]


def fetch_gobik_product(fetcher: PublicPageFetcher, url: str) -> CapturedPage:
    """Select the exposed Spain market once, then return fresh ES/EUR evidence.

    All requests, including the one public country form, use the same permitted
    transport/session. A failed selection is remembered for this fetcher only;
    no alternate route, cookie preset or repeated form submission is attempted.
    """
    _product_url(url, variant_allowed=False)
    cached_error = getattr(fetcher, '_gobik_localization_error', None)
    if cached_error is not None:
        raise cached_error
    capture = fetcher.fetch(url, policy=FetchPolicy(mode='static'))
    if capture.url != url:
        raise GobikCollectionError('Gobik product redirected outside the exact source/market path')
    html = capture.body.decode('utf-8-sig', errors='replace')
    country, currency = _active_market(html)
    if currency != 'EUR':
        raise GobikCollectionError('Gobik active market currency is not EUR')
    if country == 'ES':
        return capture
    try:
        if getattr(fetcher, '_gobik_localization_attempted', False):
            raise GobikCollectionError('Gobik Spain localization did not persist')
        action, fields = _spain_localization_form(html, url)
        fetcher._gobik_localization_attempted = True
        try:
            selected = fetcher.submit_public_localization(action, fields, url)
        except SourceDeferred:
            raise
        except CollectionError as exc:
            raise GobikCollectionError('Gobik official Spain localization failed') from exc
        selected_country, selected_currency = _active_market(selected.body.decode('utf-8-sig', errors='replace'))
        if selected.url != url or selected_country != 'ES' or selected_currency != 'EUR':
            raise GobikCollectionError('Gobik Spain localization did not persist')
        return selected
    except CollectionError as exc:
        fetcher._gobik_localization_error = exc
        raise


def _product_data(page: Selector, url: str) -> dict:
    products = []
    for block in page.css('script[type="application/ld+json"]::text').getall():
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        for item in _objects(data):
            if item.get("@type") != "Product":
                continue
            try:
                if _product_url(item.get("url", ""), variant_allowed=False) == url:
                    products.append(item)
            except (CollectionError, TypeError, ValueError):
                continue
    if len(products) != 1:
        raise GobikCollectionError("Gobik product JSON-LD is missing or ambiguous")
    return products[0]


def parse_gobik_product(html: str, source: dict, page_url: str,
                        fetched_at: datetime) -> list[Offer]:
    """Parse only the official ES/EUR product's published size variants.

    A design without an explicit color attribute stays in the complete product
    name and exact product URL; a color is never guessed from pictures or SKUs.
    Quantity is optional, and only belongs to the currently selected variant.
    """
    url = _product_url(page_url)
    if source.get("code") != "gobik":
        raise GobikCollectionError("Gobik parser requires the Gobik source")
    if fetched_at.tzinfo is None:
        raise GobikCollectionError("Gobik observation time requires a timezone")
    country, currency = _active_market(html)
    if currency != "EUR":
        raise GobikCollectionError("Gobik active market currency is not EUR")
    if country != "ES":
        raise GobikCollectionError("Gobik active market country is not ES")
    page = Selector(html)
    canonicals = page.css('link[rel="canonical"]::attr(href)').getall()
    if canonicals != [url]:
        raise GobikCollectionError("Gobik canonical product identity is missing or different")
    containers = [node for node in page.css('.product__info-container')
                  if urljoin(url, node.attrib.get("data-url", "")) == url]
    if len(containers) != 1:
        raise GobikCollectionError("Gobik product information container is ambiguous")
    container = containers[0]
    pickers = [node for node in container.css('variant-radios.size-variant-picker')
               if urljoin(url, node.attrib.get("data-url", "")) == url]
    if len(pickers) != 1:
        raise GobikCollectionError("Gobik size-picker does not belong to this product")
    picker = pickers[0]
    blocks = picker.css('script[type="application/json"]::text').getall()
    try:
        variants = json.loads(blocks[0]) if len(blocks) == 1 else None
    except (ValueError, TypeError) as exc:
        raise GobikCollectionError("Gobik size-picker JSON is malformed") from exc
    if not isinstance(variants, list) or not 1 <= len(variants) <= MAX_VARIANTS:
        raise GobikCollectionError("Gobik size-picker variants are missing or unbounded")
    fields = picker.css('fieldset')
    if len(fields) != 1 or _text(fields[0].css('legend::text').get("")).casefold() not in _SIZE_LABELS:
        raise GobikCollectionError("Gobik requires one explicitly labelled size dimension")
    controls = {}
    for node in fields[0].css('input[type="radio"]'):
        size = node.attrib.get("value", "")
        if not size or size in controls or node.attrib.get("name", "").casefold() not in _SIZE_LABELS:
            raise GobikCollectionError("Gobik size controls are missing or duplicated")
        controls[size] = node
    if len(controls) != len(variants):
        raise GobikCollectionError("Gobik variant list does not match the size controls")
    product = _product_data(page, url)
    name = _text(str(product.get("name") or ""))
    brand = product.get("brand") or {}
    brand = brand.get("name") if isinstance(brand, dict) else brand
    if not name or str(brand).casefold() != "gobik":
        raise GobikCollectionError("Gobik product name or official brand is missing")
    product_ids = set(container.css('input[name="product-id"]::attr(value)').getall())
    if len(product_ids) != 1 or not next(iter(product_ids)).isdigit():
        raise GobikCollectionError("Gobik product ID is missing or contradictory")
    product_id = next(iter(product_ids))
    quoted = product.get("offers")
    if not isinstance(quoted, list) or not quoted:
        raise GobikCollectionError("Gobik per-variant structured offers are missing")
    quotes = {}
    for quote in quoted:
        if not isinstance(quote, dict) or quote.get("@type") != "Offer":
            raise GobikCollectionError("Gobik per-variant structured offer is malformed")
        quote_url = quote.get("url", "")
        if _product_url(quote_url) != url:
            raise GobikCollectionError("Gobik structured offer belongs to another product")
        ids = parse_qs(urlsplit(quote_url).query).get("variant", [])
        if len(ids) != 1 or ids[0] in quotes:
            raise GobikCollectionError("Gobik structured variant ID is missing or duplicated")
        quotes[ids[0]] = quote
    if len(quotes) != len(variants):
        raise GobikCollectionError("Gobik structured and picker variant counts differ")
    image = product.get("image")
    image = image[0] if isinstance(image, list) and image else image
    image = image if isinstance(image, str) and urlsplit(image).scheme == "https" else None
    genders = {value for token, value in (("UNISEX", "unisex"), ("MEN", "male"), ("WOMEN", "female"))
               if re.search(r"\b" + token + r"\b", name, re.I)}
    gender = next(iter(genders)) if len(genders) == 1 else None
    color = product.get("color")
    if color is not None and (not isinstance(color, str) or not color.strip()):
        raise GobikCollectionError("Gobik product color is malformed")
    # The color picker links separate products. Only its explicitly current
    # swatch, bound to this exact URL/product ID, may describe these sizes.
    color_pickers = container.css('variant-radios.product-variant-picker__container')
    if color_pickers:
        if len(color_pickers) != 1:
            raise GobikCollectionError("Gobik color picker is ambiguous")
        current = color_pickers[0].css('fieldset.current-pick')
        if (len(current) != 1
                or _text(color_pickers[0].css('label.form__label::text').get("")).casefold() != "color"
                or current[0].css('a::attr(href)').getall() != [urlsplit(url).path]
                or current[0].css('a > div::attr(id)').getall() != [product_id]):
            raise GobikCollectionError("Gobik selected color does not match the exact product")
        label = _text(current[0].css('legend::text').get(""))
        if not label or (color and color.casefold() != label.casefold()):
            raise GobikCollectionError("Gobik selected color is missing or contradictory")
        color = label
    result, seen, sizes = [], set(), set()
    for variant in variants:
        if not isinstance(variant, dict):
            raise GobikCollectionError("Gobik picker variant is malformed")
        vid = str(variant.get("id", ""))
        size = variant.get("option1")
        if (not vid.isdigit() or vid in seen or not isinstance(size, str) or size not in controls
                or size in sizes or variant.get("option2") is not None or variant.get("option3") is not None
                or variant.get("title") != size or variant.get("public_title") != size
                or variant.get("options") != [size]):
            raise GobikCollectionError("Gobik exact variant/size identity is missing or ambiguous")
        seen.add(vid)
        sizes.add(size)
        quote = quotes.get(vid)
        if quote is None or not variant.get("sku") or str(quote.get("sku", "")) != variant["sku"]:
            raise GobikCollectionError("Gobik exact variant SKU does not match structured evidence")
        minor = variant.get("price")
        price = money(quote.get("price"), quote.get("priceCurrency"))
        if type(minor) is not int or minor < 0 or price is None or price.currency != "EUR" or price.amount * 100 != minor:
            raise GobikCollectionError("Gobik variant price/currency does not match structured evidence")
        available = variant.get("available")
        picker_stock = "in_stock" if available is True else "out_of_stock" if available is False else "unknown"
        control = controls[size]
        control_stock = "out_of_stock" if ("disabled" in control.attrib or "disabled" in control.attrib.get("class", "").split()) else "in_stock"
        stock = picker_stock if picker_stock == stock_status(quote.get("availability")) == control_stock else "unknown"
        gtin = quote.get("gtin13") or quote.get("gtin")
        barcode = variant.get("barcode")
        if gtin is not None and barcode and str(gtin) != str(barcode):
            raise GobikCollectionError("Gobik exact variant barcode conflicts with structured evidence")
        try:
            identity = ProductIdentity(brand="Gobik", model=name, size=size, color=color,
                                       gender=gender, gtin=str(gtin) if gtin is not None else None)
        except ValidationError as exc:
            raise GobikCollectionError("Gobik exact variant GTIN is invalid") from exc
        original_minor = variant.get("compare_at_price")
        original = money(Decimal(original_minor) / 100, "EUR") if type(original_minor) is int and original_minor > minor else None
        result.append(Offer(
            offer_id=offer_id("gobik", url, vid), source_code="gobik", source_name=source["name"],
            identity=identity, name=name, url=url + "?variant=" + vid, image=image,
            price=price, original_price=original, stock=stock, fetched_at=fetched_at,
            family_hint=url, collection_url=url, sales_region="西班牙站 EUR 报价",
            shipping_to_china=evidence(source, "china_shipping"),
            china_issued_card=evidence(source, "china_credit_card"),
            identity_evidence="官网 ES/EUR 商品页：逐变体 ID、SKU、尺码、价格与 JSON-LD 交叉核对；可购买状态同时核对尺码控件"
                + (f"；当前商品颜色选项：{color}，与商品 URL 和商品 ID 一致" if color else "；未标注的颜色不推测")
                + ("；库存证据冲突，待核实" if stock == "unknown" else ""),
            purchase_requirements=["西班牙站欧元报价；其他地区的价格、配送、税费及付款资格须重新核实。",
                                   "官网库存为本次抓取时的对应尺码状态；下单前请重新确认。"],
        ))
    # A static page can publish a precise quantity for its selected size only.
    # Do not propagate that selected-size quantity to every picker variant.
    selected = container.css('#quantity-stock_inventory')
    quantity_nodes = container.css('#quantity_stock')
    selected_controls = [size for size, node in controls.items() if "checked" in node.attrib]
    if len(selected) == len(quantity_nodes) == len(selected_controls) == 1:
        attrs = selected[0].attrib
        count_match = re.fullmatch(r"(\d+) In stock", _text(quantity_nodes[0].get_all_text(strip=True)), re.I)
        selected_id = attrs.get("value")
        if (attrs.get("data-value") == selected_id and attrs.get("product-id") == product_id
                and count_match):
            count = int(count_match[1])
            for row in result:
                if row.url.endswith("?variant=" + str(selected_id)) and row.identity.size == selected_controls[0] and row.stock == "in_stock" and count > 0:
                    row.stock_quantity = count
    return result


def _semantic_name(value: str) -> str:
    """Gobik headings omit sleeve descriptors and the trailing chamois code."""
    value = re.sub(r"^the\s+", "", value, flags=re.I)
    value = re.sub(r"\b(?:long|short) sleeve\s+", "", value, flags=re.I)
    value = re.sub(r"\s*-\s*K\d+\s*$", "", value, flags=re.I)
    return _text(value).casefold()


def reconcile_gobik_offers(fresh_rows: list[Offer], old_rows: list[Offer]) -> list[Offer]:
    """Preserve established listing/card identities, never old observations.

    Reconciliation requires one exact product URL and size, one compatible
    product family and unchanged semantic name/market. Ambiguity fails closed.
    New sizes inherit the established family dimensions, but not a sibling GTIN.
    """
    fresh_groups, old_groups = defaultdict(list), defaultdict(list)
    for row in fresh_rows:
        if row.source_code != "gobik":
            raise GobikCollectionError("Gobik reconciliation received another source")
        fresh_groups[_product_url(row.url)].append(row)
    for row in old_rows:
        if row.source_code == "gobik":
            old_groups[_product_url(row.url)].append(row)
    output = []
    family_fields = ("brand", "model", "color", "year", "gender")
    for url, fresh in fresh_groups.items():
        old = old_groups.get(url, [])
        if len({row.identity.size for row in fresh}) != len(fresh):
            raise GobikCollectionError("Gobik fresh product has ambiguous size identities")
        if not old:
            output.extend(fresh)
            continue
        old_by_size = {row.identity.size: row for row in old}
        family_keys = {(row.family_hint, *(getattr(row.identity, key) for key in family_fields)) for row in old}
        if len(old_by_size) != len(old) or len(family_keys) != 1:
            raise GobikCollectionError("Gobik previous product family or size match is ambiguous")
        representative = old[0]
        for row in fresh:
            if (row.price.currency != "EUR" or representative.price.currency != "EUR"
                    or row.sales_region != "西班牙站 EUR 报价" or representative.sales_region != "西班牙站 EUR 报价"
                    or row.identity.brand.casefold() != representative.identity.brand.casefold()
                    or _semantic_name(row.identity.model) != _semantic_name(representative.identity.model)
                    or (representative.identity.color is not None and row.identity.color != representative.identity.color)
                    or row.identity.gender != representative.identity.gender
                    or row.identity.year != representative.identity.year):
                raise GobikCollectionError("Gobik previous family is not semantically identical to the current product")
            prior = old_by_size.get(row.identity.size)
            family = {key: getattr(representative.identity, key) for key in family_fields}
            identity = row.identity.model_copy(update=family)
            if prior:
                # Existing variant IDs include their historical lack of GTIN/MPN.
                # Conflicting explicit manufacturer identifiers must not be hidden.
                for key in ("gtin", "mpn"):
                    if getattr(prior.identity, key) and getattr(prior.identity, key) != getattr(row.identity, key):
                        raise GobikCollectionError("Gobik previous manufacturer variant identity conflicts")
                identity = prior.identity.model_copy()
            output.append(row.model_copy(update={
                "offer_id": prior.offer_id if prior else row.offer_id,
                "family_hint": representative.family_hint,
                "identity": identity, "name": representative.name,
            }))
    return output


# Generic collect_variants/refresh pipeline integration names.
parse_gobik = parse_gobik_product
preserve_gobik_identity = reconcile_gobik_offers


def collect_gobik_catalog(fetcher: PublicPageFetcher, settings: dict, source: dict,
                          fetched_at: datetime, raw_dir: Path | None = None,
                          existing_offers: list[Offer] | None = None) -> GobikCollectionResult:
    """Refresh an explicit, bounded list; failures retain caller-owned snapshots."""
    result = GobikCollectionResult()
    urls = settings.get("urls")
    limit = settings.get("max_products", MAX_PRODUCTS)
    result.coverage = {"method": "gobik_public_size_picker_plus_jsonld", "scope": "explicit_product_sample",
        "scope_note": settings.get("scope_note", "仅自动刷新明确列出的官网商品及其尺码，不代表完整 Gobik 目录。"),
        "currency": "EUR", "market_country": "ES", "collected_product_count": 0,
        "discovered_product_count": len(urls) if isinstance(urls, list) else 0,
        "offer_count": 0, "complete": False, "partial": True, "catalog_complete": False}
    try:
        if type(limit) is not int or not 1 <= limit <= MAX_PRODUCTS:
            raise GobikCollectionError("Gobik max_products must be from 1 to 25")
        if not isinstance(urls, list) or not 1 <= len(urls) <= limit or len(set(urls)) != len(urls):
            raise GobikCollectionError("Gobik requires a unique, bounded explicit product URL list")
        for url in urls:
            _product_url(url, variant_allowed=False)
    except (CollectionError, TypeError, ValueError) as exc:
        result.errors.append({"url": "https://gobik.com/en", "error": str(exc)})
        return result
    for index, url in enumerate(urls):
        try:
            if url in settings.get("excluded_urls", []):
                raise GobikCollectionError("Gobik product remains paused after an unresolved access failure")
            capture = fetch_gobik_product(fetcher, url)
            if capture.url != url:
                raise GobikCollectionError("Gobik product redirected outside the exact source/market path")
            if raw_dir is not None:
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / ("gobik_" + hashlib.sha256(url.encode()).hexdigest()[:16] + ".html")).write_bytes(capture.body)
            rows = parse_gobik_product(capture.body.decode("utf-8-sig", errors="replace"), source, url, capture.observed_at)
            if existing_offers is not None:
                rows = reconcile_gobik_offers(rows, existing_offers)
            result.offers.extend(row.model_copy(update={"fetch_mode": capture.fetch_mode,
                "evidence_sha256": capture.evidence_sha256}) for row in rows)
            result.coverage["collected_product_count"] += 1
        except SourceDeferred as exc:
            result.errors.extend({"url": pending, "error": str(exc), "retry_at": exc.retry_at.isoformat()} for pending in urls[index:])
            break
        except Exception as exc:
            result.errors.append({"url": url, "error": str(exc)})
    result.coverage.update({"offer_count": len(result.offers), "configured_scope_complete": not result.errors,
        "complete": not result.errors, "partial": bool(result.errors), "fetch_mode": "static"})
    return result
