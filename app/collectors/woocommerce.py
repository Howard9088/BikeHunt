"""Evidence-strict WooCommerce variations from the EF official team's shop.

Only the observed public product-page format is supported: a product-bound
variation form, matching analytics identity and an explicitly selected currency.
No remote JavaScript is executed, options are never expanded into invented
variants, and a store/default currency alone is not an active-market quote.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import evidence, money, offer_id


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _https_url(value: str):
    """Keep actual page URLs, excluding credentials, query/fragment and bad ports."""
    if not isinstance(value, str) or not value or re.search(r"[\s\\]", value):
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme != "https" or not parts.hostname or parts.username
                or parts.password or parts.port not in (None, 443)
                or parts.query or parts.fragment):
            return None
    except ValueError:
        return None
    return parts.hostname, parts.path.rstrip("/")


def _assignments(page: Selector, variable: str) -> list:
    """Decode JSON literals after a named assignment; never eval page scripts."""
    values = []
    pattern = re.compile(r"\b" + re.escape(variable) + r"\s*=\s*")
    for script in page.css("script::text").getall():
        for match in pattern.finditer(script):
            try:
                value, _ = json.JSONDecoder().raw_decode(script[match.end():])
            except (ValueError, TypeError):
                return []
            values.append(value)
    return values


def _stock(variant: dict) -> tuple[str, list[str]]:
    """Missing or non-boolean inventory is unknown, not false or truthy."""
    requirements = []
    if variant.get("is_in_stock") is False:
        return "out_of_stock", requirements
    if variant.get("is_purchasable") is False:
        requirements.append("官方当前不可购买，现货状态需核实")
    if variant.get("backorders_allowed") is True:
        requirements.append("官方允许缺货预订，现货状态需核实")
    if (all(variant.get(key) is True for key in
            ("is_in_stock", "is_purchasable", "variation_is_active", "variation_is_visible"))
            and variant.get("backorders_allowed") is False):
        return "in_stock", requirements
    return "unknown", requirements


def parse_woocommerce(html: str, source: dict, page_url: str,
                      fetched_at: datetime) -> list[Offer]:
    """Parse verified EF WooCommerce variants; reject conflicting page evidence.

    ``source`` supplies the reviewed official-shop brand and source metadata.
    Its currency is only an expected value, never evidence for a missing quote.
    Offer URLs remain the actual canonical PDP; variation IDs distinguish rows.
    """
    target = _https_url(page_url)
    base = _https_url(source.get("base_url", ""))
    brand = _text(source.get("brand"))
    if (not target or not base or not brand or not source.get("code")
            or not source.get("name") or target[0] != base[0]
            or not target[1].startswith(base[1] + "/product/")
            or not re.fullmatch(r"[^/]+", target[1][len(base[1] + "/product/"):])):
        return []
    page = Selector(html)
    canonical = page.css('link[rel="canonical"]::attr(href)').getall()
    forms = page.css("form.variations_form[data-product_id][data-product_variations]")
    headings = page.css("h1.product_title")
    if (len(canonical) != 1 or _https_url(canonical[0]) != target
            or len(forms) != 1 or len(headings) != 1):
        return []
    form = forms[0]
    product_id = form.attrib.get("data-product_id", "")
    name = str(headings[0].get_all_text(strip=True)).strip()
    if (not name or not re.fullmatch(r"[1-9][0-9]*", product_id)
            or _https_url(form.attrib.get("action", "")) != target):
        return []
    # Hidden form IDs bind the publicly serialized variations to this product.
    for key in ("product_id", "add-to-cart"):
        ids = form.css(f'input[name="{key}"]::attr(value)').getall()
        if ids != [product_id]:
            return []

    selected = {str(node.get_all_text(strip=True)).strip()
                for node in page.css(".yay-currency-selected-option")}
    if len(selected) != 1:
        return []
    currency = next(iter(selected))
    if not re.fullmatch(r"[A-Z]{3}", currency) or source.get("currency", currency) != currency:
        return []
    common = _assignments(page, "wcAnalytics.commonProps")
    if (not common or any(not isinstance(props, dict)
            or props.get("store_currency") != currency
            or _https_url(props.get("url", "")) != base for props in common)):
        return []
    queues = _assignments(page, "wcAnalytics.eventQueue")
    views = []
    for queue in queues:
        if not isinstance(queue, list):
            return []
        views.extend(event.get("props") for event in queue
                     if isinstance(event, dict) and event.get("eventName") == "product_view")
    if (not views or any(not isinstance(props, dict)
            or type(props.get("pi")) is not int or str(props["pi"]) != product_id
            or props.get("pn") != name or props.get("pt") != "variable" for props in views)):
        return []

    options: dict[str, dict[str, str]] = {}
    for select in form.css('select[name^="attribute_"]'):
        key = select.attrib["name"]
        if key not in ("attribute_pa_size", "attribute_pa_color") or key in options:
            return []
        choices = {}
        for option in select.css("option[value]"):
            value = option.attrib["value"]
            if not value:  # The visible "Choose an option" prompt is not a size.
                continue
            label = str(option.get_all_text(strip=True)).strip()
            if not label or len(label) > 100 or value in choices:
                return []
            choices[value] = label
        if not choices:
            return []
        options[key] = choices
    if "attribute_pa_size" not in options:
        return []
    try:
        variants = json.loads(form.attrib["data-product_variations"])
    except (ValueError, TypeError):
        return []
    if not isinstance(variants, list) or not variants:
        return []

    result, seen_ids, seen_options = [], set(), set()
    for variant in variants:
        if not isinstance(variant, dict):
            return []
        variant_id = variant.get("variation_id")
        attributes = variant.get("attributes")
        if (type(variant_id) is not int or variant_id <= 0 or variant_id in seen_ids
                or not isinstance(attributes, dict) or set(attributes) != set(options)):
            return []
        labels = {}
        for key, value in attributes.items():
            # Empty attributes mean "any" in WooCommerce, not a real size/color.
            if not isinstance(value, str) or not value or value not in options[key]:
                return []
            labels[key] = options[key][value]
        option_key = tuple(sorted(attributes.items()))
        if option_key in seen_options:
            return []
        seen_ids.add(variant_id)
        seen_options.add(option_key)
        price = money(variant.get("display_price"), currency)
        if price is None or price.amount <= 0:
            return []
        # Hidden/inactive variants are not current public offers. Unknown flags
        # may preserve an evidenced quote but can never assert in-stock status.
        if (variant.get("variation_is_active") is False
                or variant.get("variation_is_visible") is False):
            continue
        original = money(variant.get("display_regular_price"), currency)
        original = original if original and original.amount > price.amount else None
        stock, requirements = _stock(variant)
        image_data = variant.get("image")
        image = _text(image_data.get("url")) if isinstance(image_data, dict) else ""
        if not _https_url(image):
            image = None
        result.append(Offer(
            offer_id=offer_id(source["code"], canonical[0], str(variant_id)),
            source_code=source["code"], source_name=source["name"],
            name=name, url=canonical[0], fetched_at=fetched_at,
            identity=ProductIdentity(brand=brand, model=name,
                                     size=labels["attribute_pa_size"],
                                     color=labels.get("attribute_pa_color")),
            price=price, original_price=original, image=image, stock=stock,
            sales_region=source.get("sales_region", ""), family_hint=product_id,
            purchase_requirements=requirements,
            shipping_to_china=evidence(source, "china_shipping"),
            china_issued_card=evidence(source, "china_credit_card"),
            identity_evidence=("官方 WooCommerce 商品表单：商品 ID " + product_id
                + "、规格 ID " + str(variant_id)
                + "；尺码/颜色与页面选项一致，选定币种与店铺数据一致；独立报价及明确库存字段；商家 SKU 不作跨站型号"),
        ))
    return result
