"""Oakley US: public selected-SKU evidence, followed by bounded size-page reads.

Only a selected UPC whose market, size, colour, price and stock signals agree
becomes a current offer. Size-selector availability alone is never inventory.
No scripts are executed and all network traffic uses PublicPageFetcher.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urljoin, urlsplit

from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.fetch_policy import CapturedPage
from app.collectors.parsers import evidence, money, offer_id
from app.collectors.transport import CollectionError, PublicPageFetcher, SourceDeferred
from app.collectors.variants import formatted_money

ORIGIN = "https://www.oakley.com"
PRODUCT_PATH = re.compile(r"/en-us/product/[A-Z0-9]+")
AVAILABLE = {"Available", "Available-oneLeft", "Available-twoLeft", "Available-fewLeft"}
# Public diagnostics are a closed vocabulary: never page text, data or exceptions.
OAKLEY_DIAGNOSTICS = frozenset({
    "request_scope", "canonical_url", "canonical_missing", "canonical_blank",
    "canonical_conflicting", "canonical_rel_token_variant", "canonical_missing_product_layout",
    "canonical_relative_same_product", "canonical_protocol_relative_same_product",
    "canonical_same_product_variant_query", "canonical_same_product_selected_upc",
    "canonical_same_product_other_upc", "canonical_same_product_other_query",
    "canonical_same_product_fragment", "canonical_same_product_trailing_slash",
    "canonical_same_product_origin_variant", "canonical_same_product_non_https",
    "canonical_other_market", "canonical_other_product", "canonical_external_origin",
    "canonical_invalid", "canonical_other_path", "canonical_analytics_us",
    "canonical_analytics_other_country", "canonical_analytics_missing",
    "canonical_locale_en_us", "canonical_locale_other", "canonical_locale_missing",
    "response_empty", "response_gzip", "response_utf16", "response_json",
    "response_escaped_html", "response_non_html", "response_html_text",
    "response_script_shell", "response_html_empty", "response_hydration_marker",
    "response_javascript_required", "response_under_1k_chars", "response_1k_10k_chars",
    "response_10k_100k_chars", "response_over_100k_chars",
    "access_denied", "human_verification", "captcha_challenge", "source_access_stopped",
    "analytics_literal", "selected_controls",
    "requested_upc", "analytics_upc", "product_object", "market_country",
    "site_currency", "order_currency", "page_type", "selected_color",
    "selected_size", "product_heading", "dom_size", "analytics_size",
    "analytics_name", "analytics_model_name", "analytics_sku", "analytics_id",
    "sku_format", "article_number", "analytics_url", "dom_sku", "variant_option",
    "page_title", "color_swatch", "swatch_url", "selected_price",
    "visible_price_missing", "visible_price_mismatch", "dom_currency",
    "original_price_mismatch", "stock_state", "stock_selected_disabled",
    "stock_post_code", "stock_hidden", "stock_cart", "soldout_state",
    "soldout_selected_disabled", "soldout_cart", "offer_schema", "no_selected_offer",
})
PUBLIC_DIAGNOSTICS = frozenset("oakley_" + code for code in OAKLEY_DIAGNOSTICS)
ACCESS_DIAGNOSTICS = frozenset({
    "oakley_access_denied", "oakley_human_verification", "oakley_captcha_challenge",
})


def _text(value: str) -> str:
    return " ".join(value.split())


def _sole(values: Iterable[str]) -> str | None:
    values = {_text(value) for value in values}
    return next(iter(values)) if len(values) == 1 and "" not in values else None


def _product_url(url: str) -> tuple[str, str | None] | None:
    """Require the exact public US origin; query may only select one numeric UPC."""
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.netloc != "www.oakley.com"
                or parts.fragment or not PRODUCT_PATH.fullmatch(parts.path)):
            return None
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
        if query and (set(query) != {"variant"} or len(query["variant"]) != 1
                      or not re.fullmatch(r"[0-9]{8,14}", query["variant"][0])):
            return None
        return ORIGIN + parts.path, query.get("variant", [None])[0]
    except (ValueError, TypeError):
        return None


def _canonical_failure(page: Selector, expected: str) -> str:
    """Classify a rejected canonical shape; never return or accept its URL.

    These distinctions help diagnose response-layout and geographic differences
    without publishing arbitrary hrefs, query values, or HTML. They deliberately
    do not normalize any new canonical representation into accepted evidence.
    """
    values = page.css('link[rel="canonical"]::attr(href)').getall()
    if not values:
        alternatives = [node for node in page.css('link[rel]')
                        if "canonical" in node.attrib.get("rel", "").casefold().split()]
        if alternatives:
            return "canonical_rel_token_variant"
        if page.css('form.pdhero-form') and page.css('[data-test="sizes-selection"]'):
            return "canonical_missing_product_layout"
        return "canonical_missing"
    normalized = {_text(value) for value in values}
    if "" in normalized:
        return "canonical_blank"
    if len(normalized) != 1:
        return "canonical_conflicting"
    value = next(iter(normalized))
    try:
        actual = urlsplit(value)
        target = urlsplit(expected)
        if actual.username or actual.password:
            return "canonical_invalid"
        # Resolve only to classify relative same-product links, never to accept.
        if not actual.scheme and not actual.netloc:
            resolved = urlsplit(urljoin(expected, value))
            if resolved.hostname == target.hostname and resolved.path.rstrip("/") == target.path:
                return "canonical_relative_same_product"
            return "canonical_other_path"
        if actual.hostname not in {"oakley.com", "www.oakley.com"}:
            return "canonical_external_origin"
        if re.match(r"/[a-z]{2}-[a-z]{2}/", actual.path, re.I) and not actual.path.startswith("/en-us/"):
            return "canonical_other_market"
        if actual.path.rstrip("/") == target.path:
            if not actual.scheme:
                return "canonical_protocol_relative_same_product"
            if actual.scheme != "https":
                return "canonical_same_product_non_https"
            if actual.netloc != target.netloc:
                return "canonical_same_product_origin_variant"
            if actual.path != target.path:
                return "canonical_same_product_trailing_slash"
            if actual.fragment:
                return "canonical_same_product_fragment"
            if actual.query:
                variant = _product_url(value)
                if not variant:
                    return "canonical_same_product_other_query"
                selected = _selected(page)
                if selected:
                    return ("canonical_same_product_selected_upc" if variant[1] == selected[0]
                            else "canonical_same_product_other_upc")
                return "canonical_same_product_variant_query"
        if PRODUCT_PATH.fullmatch(actual.path.rstrip("/")):
            return "canonical_other_product"
        return "canonical_other_path"
    except (ValueError, TypeError):
        return "canonical_invalid"


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        # The live merchant script repeats Page_Type as "product" then "Pdp".
        # Repeated product/market/price fields, however, are ambiguous evidence.
        if key in result and key != "Page_Type":
            raise ValueError("Duplicate Oakley evidence key")
        result[key] = value
    return result


def _utag(page: Selector) -> dict | None:
    """Decode the literal assignment and numeric object keys, never eval JS."""
    candidates = []
    for script in page.css("script::text").getall():
        match = re.match(r"\s*var\s+utag_data\s*=\s*", script)
        if not match:
            continue
        raw = script[match.end():].strip()
        # This tokenizer leaves double-quoted string contents untouched, including
        # apparent numeric keys in a product title or other string value.
        tokens = re.compile(r'"(?:\\.|[^"\\])*"|([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)(?=\s*:)')
        def literal(match):
            if match[1]:
                if len(match[1]) > 40:
                    raise ValueError("Oversized numeric Oakley key")
                number = Decimal(match[1])
                if (not number.is_finite() or not 7 <= number.adjusted() <= 13
                        or number != number.to_integral_value()):
                    raise ValueError("Oakley key is not an exact integral UPC")
                # Live Hybris output uses 8056153349E3 for UPC 8056153349000.
                # Decimal avoids float rounding and never guesses missing digits.
                return '"' + str(int(number)) + '"'
            # Oakley's literal strings additionally use JS hexadecimal escapes.
            # Convert those to JSON escapes without interpreting any expression.
            return re.sub(r"\\(?:x([0-9a-fA-F]{2})|.)",
                          lambda escaped: "\\u00" + escaped[1] if escaped[1]
                          else ("'" if escaped[0] == "\\'" else escaped[0]), match[0])
        try:
            safe = tokens.sub(literal, raw)
            value, end = json.JSONDecoder(object_pairs_hook=_pairs).raw_decode(safe)
            if safe[end:].strip() not in ("", ";") or not isinstance(value, dict):
                return None
            candidates.append(value)
        except (ValueError, TypeError, InvalidOperation, OverflowError):
            return None
    return candidates[0] if len(candidates) == 1 else None


def _canonical_context(page: Selector) -> tuple[str, str]:
    """Finite, non-authorizing market signals accompanying a canonical rejection."""
    data = _utag(page)
    country = data.get("Page_Country") if data else None
    market = ("canonical_analytics_us" if country == "US" else
              "canonical_analytics_other_country" if isinstance(country, str) and country
              else "canonical_analytics_missing")
    locales = set()
    for script in page.css("script::text").getall():
        # Read only the merchant's observed public configuration script. This is
        # diagnostic metadata, never permission or alternate product evidence.
        if re.match(r"\s*var\s+ACC\s*=", script):
            locales.update(re.findall(r'\blanguageCountry\s*:\s*"([A-Za-z]{2}_[A-Za-z]{2})"', script))
    locale = ("canonical_locale_en_us" if locales == {"en_US"} else
              "canonical_locale_other" if locales else "canonical_locale_missing")
    return market, locale


def _access_restriction(page: Selector) -> str | None:
    """Recognize explicit restriction UI, not cookies or ordinary sensor scripts.

    A product page may legitimately embed a newsletter CAPTCHA or security JS.
    Only a non-product response can trigger this terminal source-level signal.
    Missing markup or a JavaScript requirement by themselves are not denials.
    """
    denied = {"access denied", "access to this page has been denied", "request rejected",
              "forbidden", "you have been blocked", "sorry, you have been blocked",
              "access blocked", "access restricted"}
    verification = {"just a moment", "pardon our interruption", "verify you are human",
                    "human verification", "are you a human", "are you human",
                    "are you a robot", "robot or human", "security verification",
                    "attention required! | cloudflare"}
    titles = {_text(str(node.get_all_text(strip=True))).casefold().rstrip(".!?")
              for node in page.css('title')[:4]}
    if titles & denied:
        return "access_denied"
    if titles & verification:
        return "human_verification"
    if page.css('form.pdhero-form') or page.css('[data-test="sizes-selection"]'):
        return None
    headings = {_text(str(node.get_all_text(strip=True))).casefold().rstrip(".!?")
                for node in page.css('h1, h2')[:8]}
    if headings & denied:
        return "access_denied"
    if headings & verification:
        return "human_verification"
    # Explicit challenge UI/path only. Do not match generic Akamai/bot cookies,
    # analytics strings, vendor names, or JavaScript found on ordinary pages.
    if page.css('#challenge-form, #cf-challenge-running, iframe[src*="challenges.cloudflare.com/"], '
                'script[src*="/_sec/cp_challenge/"]'):
        return "human_verification"
    if page.css('form[action*="/captcha"], .g-recaptcha, .h-captcha, '
                'iframe[src*="/recaptcha/"], iframe[src*="hcaptcha.com/captcha"]'):
        return "captcha_challenge"
    return None


def _response_shape(html: str, page: Selector) -> str:
    """Content-free description for pages lacking every expected product marker.

    This never authorizes hydration or another request. In particular a script
    shell is ambiguous and must remain unrefreshed until its role is established.
    """
    start = html.lstrip()[:256].casefold()
    if not start:
        return "response_empty"
    if html.startswith("\x1f\ufffd") or html.startswith("\x1f\x8b"):
        return "response_gzip"
    if html.startswith(("\ufffd\ufffd", "\ufeff")) and "\x00" in html[:128]:
        return "response_utf16"
    if start.startswith(("{", "[")):
        return "response_json"
    if start.startswith(("&lt;!doctype", "&lt;html", "&lt;head", "&lt;body")):
        return "response_escaped_html"
    if not re.search(r"<(?:!doctype|html|head|body|script|div|p|title)\b", html[:4096], re.I):
        return "response_non_html"
    if page.css('script#__NEXT_DATA__, script#__NUXT_DATA__, script#ng-state'):
        return "response_hydration_marker"
    # Inspect a small sample of non-script text only, never publish its contents.
    visible = _text(" ".join(page.xpath('//text()[not(ancestor::script) and not(ancestor::style)]').getall()[:64]))[:4096].casefold()
    if any(phrase in visible for phrase in ("enable javascript", "javascript is required", "turn on javascript")):
        return "response_javascript_required"
    if not visible:
        return "response_script_shell" if page.css("script") else "response_html_empty"
    return "response_html_text"


def _response_size(html: str) -> str:
    length = len(html)
    return ("response_under_1k_chars" if length < 1024 else
            "response_1k_10k_chars" if length < 10240 else
            "response_10k_100k_chars" if length < 102400 else "response_over_100k_chars")


def _selected(page: Selector) -> tuple[str, str, str] | None:
    """Both duplicated desktop/mobile controls must select the same size/UPC."""
    selections = set()
    for label in page.css('[data-test="sizes-selection"] label[data-size]'):
        checked = label.attrib.get("data-checked") == "true"
        aria = label.attrib.get("aria-checked") == "true"
        inputs = label.css('input[name="size"][data-variant]')
        if len(inputs) != 1:
            return None
        node = inputs[0]
        if checked != aria or checked != ("checked" in node.attrib):
            return None
        if not checked:
            continue
        if node.attrib.get("value") != label.attrib.get("data-size"):
            return None
        disabled = label.attrib.get("aria-disabled")
        if disabled not in ("true", "false"):
            return None
        selections.add((node.attrib.get("data-variant", ""),
                        node.attrib["value"], disabled))
    return next(iter(selections)) if len(selections) == 1 else None


def parse_oakley(html: str, source: dict, page_url: str,
                 fetched_at: datetime, *, diagnostics: list[str] | None = None) -> list[Offer]:
    """One selected variant; optional failures use a finite content-free vocabulary."""
    def reject(code: str, *context: str) -> list[Offer]:
        codes = (code, *context)
        if any(item not in OAKLEY_DIAGNOSTICS for item in codes):
            raise ValueError("Unknown Oakley diagnostic code")
        if diagnostics is not None:
            diagnostics.extend("oakley_" + item for item in codes)
        return []

    requested = _product_url(page_url)
    if (not requested or fetched_at.tzinfo is None or source.get("code") != "oakley"
            or source.get("currency", "USD") != "USD"):
        return reject("request_scope")
    canonical, requested_upc = requested
    page = Selector(html)
    restriction = _access_restriction(page)
    if restriction:
        return reject(restriction, _response_size(html))
    if _sole(page.css('link[rel="canonical"]::attr(href)').getall()) != canonical:
        failure, context = _canonical_failure(page, canonical), _canonical_context(page)
        if failure == "canonical_missing" and context == ("canonical_analytics_missing", "canonical_locale_missing"):
            return reject(failure, _response_shape(html, page), _response_size(html))
        return reject(failure, *context)
    data = _utag(page)
    selected = _selected(page)
    if not data:
        return reject("analytics_literal")
    if not selected:
        return reject("selected_controls")
    upc, size, disabled = selected
    if requested_upc and requested_upc != upc:
        return reject("requested_upc")
    products = data.get("Products")
    if not isinstance(products, dict) or set(products) != {upc}:
        return reject("analytics_upc")
    product = products[upc]
    if not isinstance(product, dict):
        return reject("product_object")
    for field, expected, code in (
        ("Page_Country", "US", "market_country"),
        ("site_currency", "USD", "site_currency"),
        ("Order_Currency", "USD", "order_currency"),
    ):
        if data.get(field) != expected:
            return reject(code)
    if data.get("Page_Type") not in ("Pdp", "product"):
        return reject("page_type")
    color = _sole(page.css('form.pdhero-form input[name="selectedColor"]::attr(value)').getall())
    dom_size = _sole(page.css('form.pdhero-form input[name="selectedSize"]::attr(value)').getall())
    name = _sole(str(node.get_all_text(strip=True)) for node in page.css('h1[data-test="product-name"]'))
    sku = product.get("Sku")
    if not color or len(color) > 150:
        return reject("selected_color")
    if not size or len(size) > 24:
        return reject("selected_size")
    if not name:
        return reject("product_heading")
    for valid, code in (
        (dom_size == size, "dom_size"),
        (data.get("product_size") == [size], "analytics_size"),
        (data.get("product_name") == [name], "analytics_name"),
        (str(product.get("ModelName", "")).replace("\\'", "'") == name, "analytics_model_name"),
        (data.get("product_sku") == [sku], "analytics_sku"),
        (data.get("product_id") == [sku], "analytics_id"),
        (isinstance(sku, str) and re.fullmatch(r"[A-Z0-9]+-[A-Z0-9]+", sku), "sku_format"),
        (_sole(page.css('.product-attributes input[name="articleNumber"]::attr(value)').getall())
         == canonical.rsplit("/", 1)[-1], "article_number"),
        (product.get("Url") == canonical, "analytics_url"),
        (_sole(page.css('.product-attributes input[name="sku"]::attr(value)').getall()) == sku, "dom_sku"),
        (_sole(page.css('input#variantOption::attr(value)').getall()) == upc, "variant_option"),
    ):
        if not valid:
            return reject(code)
    # The chosen colour swatch supplies an independent visible colour label.
    title = _sole(page.css('title::text').getall())
    if title != f"Oakley {name} in {color} | Oakley® US":
        return reject("page_title")
    swatches = page.css('[data-test="colors-box"] .selected a[title]')
    if swatches and _sole(node.attrib["title"].casefold() for node in swatches) != color.casefold():
        return reject("color_swatch")
    for swatch in swatches:
        swatch_url = _product_url(urljoin(canonical, swatch.attrib.get("href", "")))
        if not swatch_url or swatch_url[0] != canonical:
            return reject("swatch_url")
    price = money(product.get("Price"), "USD")
    visible = page.css('.pdhero-price [data-test="sale-price"]')
    if not price or price.amount <= 0:
        return reject("selected_price")
    if not visible:
        return reject("visible_price_missing")
    if any(formatted_money(str(node.get_all_text(strip=True)), "USD") != price for node in visible):
        return reject("visible_price_mismatch")
    if _sole(v for v in page.css('.pdhero-price [content]::attr(content)').getall() if v) != "USD":
        return reject("dom_currency")
    original = money(product.get("PriceFull"), "USD")
    if original and original.amount <= price.amount:
        original = None
    # PriceFull is in the exact selected UPC object. If a list price is rendered,
    # it must corroborate that object; empty placeholders are not contrary data.
    old_labels = [_text(str(node.get_all_text(strip=True)))
                  for node in page.css('.pdhero-price [data-test="original-price"]')]
    if any(label and formatted_money(label, "USD") != original for label in old_labels):
        return reject("original_price_mismatch")
    status = product.get("Status")
    state = data.get("product_state")
    hidden = set(page.css('form.pdhero-form input[name="hiddenAvailability"]::attr(value)').getall())
    post_codes = set(page.css('form.pdhero-form input[name="productCodePost"]::attr(value)').getall())
    cart = page.css('[data-test="Add_To_Cart_Button"]')
    cart_enabled = bool(cart) and all(node.attrib.get("data-isdisabled") == "false"
                                    and "disabled" not in node.attrib for node in cart)
    future = product.get("BackOrder") != "0" or product.get("Preorder") != "0"
    if not future and status in AVAILABLE:
        expected_state = "instock" if status == "Available" else "lowstock"
        for valid, code in (
            (state == expected_state, "stock_state"),
            (disabled == "false", "stock_selected_disabled"),
            (post_codes == {upc}, "stock_post_code"),
            (bool(hidden) and hidden.issubset(AVAILABLE), "stock_hidden"),
            (cart_enabled, "stock_cart"),
        ):
            if not valid:
                return reject(code)
        stock = "in_stock"
    elif not future and status in {"SoldOut", "Out-of-stock"}:
        for valid, code in (
            (state == "outofstock", "soldout_state"),
            (disabled == "true", "soldout_selected_disabled"),
            (not cart_enabled, "soldout_cart"),
        ):
            if not valid:
                return reject(code)
        stock = "out_of_stock"
    else:
        stock = "unknown"
    image = _sole(page.css('meta[property="og:image"]::attr(content)').getall())
    if image:
        image_url = urlsplit(image)
        if image_url.scheme != "https" or image_url.hostname not in {"assets.oakley.com", "assets2.oakley.com"}:
            image = None
    try:
        identity = ProductIdentity(brand="Oakley", model=name, color=color,
                                   size=size, mpn=sku, gtin=upc)
        return [Offer(
            offer_id=offer_id("oakley", canonical, upc), source_code="oakley",
            source_name=source["name"], name=name, url=canonical, image=image,
            identity=identity, price=price, original_price=original, stock=stock,
            stock_quantity=None, fetched_at=fetched_at, family_hint=canonical,
            sales_region="美国站 USD 报价", shipping_to_china=evidence(source, "china_shipping"),
            china_issued_card=evidence(source, "china_credit_card"),
            identity_evidence=(f"Oakley 美国官网已选 UPC {upc}；颜色 {color}、尺码 {size}、"
                               "USD 价格与逐规格 Products 状态及可见选项相符；Units 不作为库存数量"),
            purchase_requirements=[
                f"已核 {color} / {size}；打开官网后须重新核对并选择该规格。",
                "美国站报价；付款、税费与配送资格须另行核对。",
            ] + (["预订、延期交付或未知可售状态；不能视为现货。"] if stock == "unknown" else []),
        )]
    except (ValueError, KeyError, TypeError):
        return reject("offer_schema")


def oakley_variant_urls(html: str, page_url: str) -> list[str]:
    """Size selectors of the selected colour only; no menu/recommendation links."""
    parsed = _product_url(page_url)
    if not parsed:
        return []
    canonical = parsed[0]
    page = Selector(html)
    if _sole(page.css('link[rel="canonical"]::attr(href)').getall()) != canonical:
        return []
    urls = []
    for node in page.css('[data-test="sizes-selection"] input[name="size"][data-variant]'):
        upc = node.attrib.get("data-variant", "")
        if not re.fullmatch(r"[0-9]{8,14}", upc):
            return []
        urls.append(canonical + "?variant=" + upc)
    return list(dict.fromkeys(urls))


def _match_key(row: Offer) -> tuple | None:
    parsed = _product_url(row.url)
    identity = row.identity
    if (row.source_code != "oakley" or not parsed or row.price.currency != "USD"
            or not identity.size or not identity.color):
        return None
    return (parsed[0], *(_text(value).casefold() for value in (
        identity.brand, identity.model, identity.color, identity.size)))


def preserve_oakley_identity(offers: Iterable[Offer], existing_offers: Iterable[Offer]) -> list[Offer]:
    """Preserve display/listing identity only after an unambiguous exact match.

    Prior observations are never an evidence source. In particular no previous
    price, stock, quantity, timestamp, freshness, image or manual note is copied.
    """
    previous: dict[tuple, list[Offer]] = {}
    families: dict[tuple, list[Offer]] = {}
    for row in existing_offers:
        key = _match_key(row)
        if key is not None:
            previous.setdefault(key, []).append(row)
            families.setdefault(key[:-1], []).append(row)
    result = []
    for row in offers:
        key = _match_key(row)
        matches = previous.get(key, [])
        if len(matches) == 1:
            old = matches[0]
            row = row.model_copy(update={"offer_id": old.offer_id,
                                         "identity": old.identity.model_copy(deep=True),
                                         "family_hint": old.family_hint})
        elif not matches and key is not None:
            siblings = families.get(key[:-1], [])
            signatures = {(old.family_hint, old.identity.brand, old.identity.model,
                           old.identity.color, old.identity.mpn, old.identity.year,
                           old.identity.gender) for old in siblings}
            if len(signatures) == 1:
                old = siblings[0]
                identity = row.identity.model_copy(update={
                    attr: getattr(old.identity, attr)
                    for attr in ("brand", "model", "color", "mpn", "year", "gender")
                })
                row = row.model_copy(update={"identity": identity, "family_hint": old.family_hint})
        result.append(row)
    return result


@dataclass
class OakleyProductResult:
    offers: list[Offer] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    pages: dict[str, CapturedPage] = field(default_factory=dict)


def collect_oakley_product(fetcher: PublicPageFetcher, url: str, source: dict,
                           existing_offers: Iterable[Offer] = (), *,
                           max_variants: int = 12) -> OakleyProductResult:
    """Read every exposed size of this selected colour through normal transport.

    The base observation is not reused as fresh evidence for another size. The
    requested UPC is checked even if an HTTP redirect removes the query string.
    A transport denial or deferral stops further requests for this product.
    """
    if type(max_variants) is not int or not 1 <= max_variants <= 20:
        raise ValueError("max_variants must be an integer between 1 and 20")
    result = OakleyProductResult(coverage={
        "scope": "selected_color_sizes", "discovered_variants": 0,
        "attempted_variants": 0, "validated_variants": 0, "complete": False,
    })
    requested = _product_url(url)
    if not requested:
        result.errors.append({"url": url, "error": "Not an exact Oakley US product URL"})
        return result
    stopped = getattr(fetcher, "_oakley_access_restriction", None)
    if stopped in ACCESS_DIAGNOSTICS:
        result.errors.append({
            "url": url, "error": "Oakley source stopped after explicit access restriction; snapshot not refreshed",
            "diagnostics": [stopped, "oakley_source_access_stopped"],
        })
        result.coverage["source_stopped"] = True
        return result
    existing_offers = list(existing_offers)
    prior_colors = {_text(row.identity.color).casefold()
                    for row in existing_offers if _match_key(row) is not None
                    and _match_key(row)[0] == requested[0]}
    queue = [url]
    base_row = None
    color_redirected = False
    seen_upcs = set()
    for request_url in queue:
        if result.coverage["attempted_variants"] >= max_variants:
            result.errors.append({"url": url, "error": "Oakley size limit reached; remaining variants not refreshed"})
            break
        result.coverage["attempted_variants"] += 1
        try:
            page = fetcher.fetch(request_url)
            result.pages[request_url] = page
            final = _product_url(page.url)
            if not final or final[0] != requested[0]:
                raise ValueError("Oakley response changed product or US market")
            diagnostics: list[str] = []
            rows = parse_oakley(page.body.decode("utf-8", errors="replace"), source,
                                request_url, page.observed_at, diagnostics=diagnostics)
            if len(rows) != 1:
                restriction = next((code for code in diagnostics if code in ACCESS_DIAGNOSTICS), None)
                result.errors.append({
                    "url": request_url,
                    "error": ("Oakley source stopped after explicit access restriction; snapshot not refreshed"
                              if restriction else "No validated selected Oakley variant; snapshot not refreshed"),
                    "diagnostics": diagnostics[:3] or ["oakley_no_selected_offer"],
                })
                if restriction:
                    # The same per-run fetcher is reused for the source. Once a
                    # restriction is observed, do not request another size or
                    # product, retry through a browser, or reuse old observations.
                    fetcher._oakley_access_restriction = restriction
                    result.coverage["source_stopped"] = True
                    break
                if base_row is None:
                    break
                continue
            row = rows[0]
            if final[1] and final[1] != row.identity.gtin:
                raise ValueError("Oakley final URL disagrees with selected UPC")
            if base_row is None:
                if prior_colors and _text(row.identity.color).casefold() not in prior_colors:
                    if color_redirected or len(prior_colors) != 1:
                        raise ValueError("Oakley historical colour could not be selected unambiguously")
                    selected_color = next(iter(prior_colors))
                    dom = Selector(page.body.decode("utf-8", errors="replace"))
                    color_urls = set()
                    for swatch in dom.css('[data-test="colors-box"] a[title][href]'):
                        candidate = urljoin(requested[0], swatch.attrib["href"])
                        target = _product_url(candidate)
                        if (_text(swatch.attrib["title"]).casefold() == selected_color
                                and target and target[0] == requested[0] and target[1]):
                            color_urls.add(candidate)
                    if len(color_urls) != 1:
                        raise ValueError("Oakley historical colour has no exact exposed variant link")
                    queue.append(color_urls.pop())
                    color_redirected = True
                    result.coverage["color_selection_pages"] = 1
                    result.coverage["attempted_variants"] -= 1
                    continue
                base_row = row
                candidates = oakley_variant_urls(page.body.decode("utf-8", errors="replace"), request_url)
                if not candidates:
                    raise ValueError("Oakley exposed size identifiers are incomplete")
                queue.extend(candidate for candidate in candidates
                             if _product_url(candidate)[1] != row.identity.gtin)
                result.coverage["discovered_variants"] = len(candidates)
            elif (row.identity.color != base_row.identity.color
                  or row.identity.model != base_row.identity.model):
                raise ValueError("Oakley size URL changed colour or model")
            if row.identity.gtin in seen_upcs:
                raise ValueError("Oakley returned a previously observed UPC")
            seen_upcs.add(row.identity.gtin)
            result.offers.append(row.model_copy(update={
                "fetch_mode": page.fetch_mode, "evidence_sha256": page.evidence_sha256,
                "collection_url": request_url,
            }))
        except CollectionError as exc:
            error = {"url": request_url, "error": str(exc)}
            if isinstance(exc, SourceDeferred):
                error["retry_at"] = exc.retry_at.isoformat()
            result.errors.append(error)
            break
        except (ValueError, KeyError, TypeError) as exc:
            result.errors.append({"url": request_url, "error": str(exc)})
            if base_row is None:
                break
    result.offers = preserve_oakley_identity(result.offers, existing_offers)
    result.coverage["validated_variants"] = len(result.offers)
    result.coverage["complete"] = bool(result.offers) and not result.errors
    return result
