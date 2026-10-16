"""解析经过浏览器渲染并有明确逐规格证据的商品。"""

from __future__ import annotations

import json
import re
import hashlib
from datetime import datetime
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.embedded_catalogs import parse_kask
from app.collectors.fetch_policy import CapturedPage
from app.collectors.parsers import evidence, money, offer_id, parse_jsonld
from app.collectors.transport import CollectionError
from app.collectors.variants import formatted_money
from app.collectors.woocommerce import _stock


def parse_unox(html: str, source: dict, page_url: str, fetched_at: datetime) -> list[Offer]:
    """Uno-X 公共俱乐部会话中的 WooCommerce 商品；只使用实际序列化的变体。"""
    page = Selector(html)
    canonical = page.css('link[rel="canonical"]::attr(href)').get()
    forms = page.css("form.variations_form[data-product_id][data-product_variations]")
    if canonical != page_url or len(forms) != 1:
        return []
    base = parse_jsonld(html, source, page_url, fetched_at)
    if len(base) != 1 or source.get("currency", base[0].price.currency) != base[0].price.currency:
        return []
    parent = base[0]
    form = forms[0]
    pid = form.attrib["data-product_id"]
    if form.css('input[name="product_id"]::attr(value)').getall() != [pid]:
        return []
    try:
        variants = json.loads(form.attrib["data-product_variations"])
    except (ValueError, TypeError):
        return []
    if not isinstance(variants, list):
        return []
    choices = {
        n.attrib["name"]: {
            o.attrib.get("value"): str(o.get_all_text(strip=True)).strip()
            for o in n.css("option[value]")
            if o.attrib.get("value")
        }
        for n in form.css('select[name^="attribute_"]')
    }
    result = []
    for variant in variants:
        attrs = variant.get("attributes") or {}
        labels = {key: choices.get(key, {}).get(value) for key, value in attrs.items()}
        size = labels.get("attribute_pa_size")
        if not size or not attrs or any(not value for value in labels.values()):
            continue
        vid = variant.get("variation_id")
        price = money(variant.get("display_price"), parent.price.currency)
        if type(vid) is not int or vid <= 0 or price != parent.price:
            continue
        stock, requirements = _stock(variant)
        quantity = None
        text = str(
            Selector(variant.get("availability_html") or "<span></span>").get_all_text(strip=True)
        ).strip()
        count = re.fullmatch(r"(\d+)\s+p[åa]\s+lager", text, re.I)
        if count and int(count[1]) == variant.get("max_qty") and stock == "in_stock":
            quantity = int(count[1])
        regular = money(variant.get("display_regular_price"), price.currency)
        if regular and regular.amount <= price.amount:
            regular = None
        result.append(
            parent.model_copy(
                update={
                    "offer_id": offer_id(source["code"], page_url, str(vid)),
                    "identity": ProductIdentity(
                        brand="Uno-X 官方周边",
                        model=parent.name,
                        size=size.upper(),
                        color=labels.get("attribute_pa_color"),
                        gender="unisex",
                    ),
                    "price": price,
                    "original_price": regular,
                    "stock": stock,
                    "stock_quantity": quantity,
                    "family_hint": page_url,
                    "purchase_requirements": requirements,
                    "sales_region": "挪威商城 / " + price.currency + " 报价",
                    "identity_evidence": "Uno-X 官方合作商城公共俱乐部入口；当前商品隐藏ID、逐尺码变体JSON、页面币种价格与可售状态核对，未读取用户账户",
                }
            )
        )
    return result


def _json_parse_assignment(html: str, variable: str) -> dict | None:
    """解码已知 JSON.parse 字符串；不执行官网的任意脚本。"""
    marker = variable + " = JSON.parse('"
    if marker not in html:
        return None
    raw = html.split(marker, 1)[1].split("');", 1)[0]
    try:
        decoded = []
        index = 0
        escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
        while index < len(raw):
            char = raw[index]
            if char == "\\":
                index += 1
                char = raw[index]
                if char == "u":
                    decoded.append(chr(int(raw[index + 1 : index + 5], 16)))
                    index += 4
                elif char in "\\/'\"":
                    decoded.append(char)
                elif char in escapes:
                    decoded.append(escapes[char])
                else:
                    return None
            else:
                decoded.append(char)
            index += 1
        value = json.loads("".join(decoded))
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError, IndexError):
        return None


def parse_pissei(html: str, source: dict, page_url: str, fetched_at: datetime) -> list[Offer]:
    """尺码选项、官方变体 ID/库存数和该尺码的显示价格必须同时对应。"""
    page = Selector(html)
    attributes = _json_parse_assignment(html, "window.productAttributes")
    options = {node.attrib.get("value"): node for node in page.css("#group-5001 option[value]")}
    if not attributes or not options:
        return []
    parents = parse_jsonld(html, source, page_url, fetched_at)
    if len(parents) != 1:
        return []
    parent = parents[0]
    region = "官网当前地区"
    for script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(script)
            for product in payload if isinstance(payload, list) else [payload]:
                if product.get("@type") == "Product":
                    value = (product.get("offers") or {}).get("eligibleRegion")
                    if isinstance(value, str) and len(value) <= 12:
                        region = value
        except (ValueError, TypeError, AttributeError):
            continue
    dom = page.css(".gescat_product-page-main[data-gtm-database-id]")
    parent_ids = {
        (
            n.attrib.get("data-gtm-database-parent-id")
            if n.attrib.get("data-gtm-database-parent-id") not in (None, "", "0")
            else n.attrib["data-gtm-database-id"]
        )
        for n in dom
    }
    if len(parent_ids) != 1:
        return []
    parent_id = parent_ids.pop()
    result = []
    for variant in attributes.get("5001", []):
        vid = str(variant.get("id", ""))
        if str(variant.get("id_parent")) != parent_id or vid not in options:
            continue
        size = variant.get("descr")
        quantity = variant.get("disponibilita")
        if not isinstance(size, str) or type(quantity) is not int or quantity < 0:
            continue
        option = options[vid]
        disabled = "disabled" in option.attrib
        if disabled != (quantity == 0):
            continue
        label = str(option.get_all_text(strip=True))
        if size not in label:
            continue
        price_page = Selector(str(variant.get("priceHtml", "")))
        labels = price_page.css(".details_article_dett_prezzo_new_price")
        if len(labels) != 1:
            continue
        price = formatted_money(str(labels[0].get_all_text(strip=True)), parent.price.currency)
        # The merchant can expose a VAT-inclusive parent price and a net display
        # price. Never turn the VAT difference into a purported discount.
        if price is None or price.amount <= 0:
            continue
        try:
            identity = ProductIdentity(
                brand=parent.identity.brand,
                model=parent.name,
                mpn=parent.identity.mpn,
                size=size,
                gtin=str(variant.get("barcode") or "") or None,
                gender="male" if "/man/" in page_url else None,
            )
        except ValueError:
            continue
        result.append(
            parent.model_copy(
                update={
                    "offer_id": offer_id(source["code"], page_url, vid),
                    "identity": identity,
                    "price": price,
                    "original_price": None,
                    "stock": "out_of_stock" if disabled else "in_stock",
                    "stock_quantity": quantity,
                    "family_hint": page_url,
                    "sales_region": region + " / " + price.currency + " 报价",
                    "identity_evidence": "PISSEI 官网渲染尺码选项与 productAttributes 的 SKU、条码、库存数量和逐规格显示价相符；父级含税价不作为折扣原价",
                }
            )
        )
    return result


def collect_variants(
    page: CapturedPage, source: dict, parser: Callable[[str, dict, str, datetime], list[Offer]]
) -> list[Offer]:
    """在同一页面与其已选规格快照上解析，附上实际抓取方式和证据指纹。"""
    result: dict[str, Offer] = {}
    for body in [page.body, *page.variant_pages]:
        rows = parser(body.decode("utf-8", errors="replace"), source, page.url, page.observed_at)
        fingerprint = hashlib.sha256(body).hexdigest()
        for row in rows:
            result[row.offer_id] = row.model_copy(
                update={"fetch_mode": page.fetch_mode, "evidence_sha256": fingerprint}
            )
    return list(result.values())


def parse_kask_rendered(
    html: str, source: dict, page_url: str, fetched_at: datetime
) -> list[Offer]:
    """读取实际选择尺码后返回的官方变体响应；不依赖页面遗留的初始 SKU。"""
    if not html.lstrip().startswith("{"):
        return parse_kask(html, source, page_url, fetched_at)
    try:
        payload = json.loads(html)
        product = payload["product"]
        sku = product["id"]
        master = product["masterProductId"]
        if not isinstance(sku, str) or not isinstance(master, str) or not sku.startswith(master):
            return []
        if master not in urlsplit(page_url).path.rsplit("/", 1)[-1]:
            return []
        attrs = {attr["id"]: attr for attr in product["variationAttributes"]}
        sizes = [v for v in attrs["size"]["values"] if v.get("selected") is True]
        colors = [v for v in attrs["color"]["values"] if v.get("selected") is True]
        if len(sizes) != 1 or len(colors) != 1 or not sku.endswith("." + sizes[0]["value"]):
            return []
        if "-" + colors[0]["value"] + "." not in sku:
            return []
        quoted = product["price"]["sales"]
        price = money(quoted["value"], quoted["currency"])
        if (
            price is None
            or price != formatted_money(quoted["formatted"], quoted["currency"])
            or money(quoted["decimalPrice"], quoted["currency"]) != price
            or source.get("currency", quoted["currency"]) != price.currency
        ):
            return []
        url = urljoin(page_url, payload["selectedProductAbsUrl"])
        if urlsplit(url).hostname != urlsplit(page_url).hostname or sku not in urlsplit(url).path:
            return []
        available = product.get("available")
        future = (product.get("availability") or {}).get("inStockDate")
        stock = (
            "out_of_stock"
            if available is False
            else (
                "in_stock"
                if available is True
                and product.get("readyToOrder") is True
                and product.get("online") is True
                and not future
                else "unknown"
            )
        )
        original = product["price"].get("list") or {}
        original_price = money(original.get("value"), original.get("currency"))
        if original_price and (
            original_price.currency != price.currency or original_price.amount <= price.amount
        ):
            original_price = None
        images = product.get("images") or {}
        photos = next((v for v in images.values() if isinstance(v, list) and v), [])
        image = photos[0].get("absURL") or photos[0].get("url") if photos else None
        name = product["productName"]
        return [
            Offer(
                offer_id=offer_id(source["code"], url, sku),
                source_code=source["code"],
                source_name=source["name"],
                name=name,
                url=url,
                identity=ProductIdentity(
                    brand="KASK",
                    model=name,
                    mpn=sku.rsplit(".", 1)[0],
                    size=sizes[0]["displayValue"],
                    color=colors[0]["displayValue"],
                    gender="unisex",
                ),
                image=urljoin(page_url, image) if image else None,
                price=price,
                original_price=original_price,
                stock=stock,
                fetched_at=fetched_at,
                family_hint=sku.rsplit(".", 1)[0],
                sales_region=source.get("sales_region", ""),
                shipping_to_china=evidence(source, "china_shipping"),
                china_issued_card=evidence(source, "china_credit_card"),
                identity_evidence="KASK 官网实际选择尺码返回的 Product-Variation：选中颜色和尺码、完整 SKU、三种同币种价格及可售状态一致",
            )
        ]
    except (ValueError, KeyError, TypeError, AttributeError):
        return []


def kask_page_action(captures: list[bytes], max_variants: int = 12) -> Callable:
    """只切换官方尺码按钮，保存每次选中 SKU；不点击购物或账户按钮。"""

    def action(page) -> None:
        selector = '.product-detail [data-attr="size"] button[data-attr-value][data-url]'
        page.wait_for_selector(selector, state="attached", timeout=15000)
        captures.append(page.content().encode("utf-8"))
        sizes = page.locator(selector).evaluate_all("nodes => nodes.map(n => n.dataset.attrValue)")
        for size in list(dict.fromkeys(sizes))[:max_variants]:
            button = page.locator(selector + f'[data-attr-value="{size}"]').first
            if not button.count():
                continue
            if "selected" in (button.get_attribute("class") or "").split():
                captures.append(page.content().encode("utf-8"))
                continue
            try:
                with page.expect_response(
                    lambda r: "Product-Variation?" in r.url, timeout=12000
                ) as pending:
                    button.dispatch_event("click")
                response = pending.value
                payload = response.json()
                if response.status != 200 or not str(
                    payload.get("product", {}).get("id", "")
                ).endswith("." + size):
                    raise CollectionError("Returned variant does not match the chosen size")
                captures.append(response.body())
            except Exception as exc:
                raise CollectionError(
                    f"KASK selected size did not resolve to its SKU: {size}"
                ) from exc

    return action
