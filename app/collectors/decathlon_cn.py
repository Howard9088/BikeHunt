"""Decathlon China: explicitly selected public variants, never default/stale stock.

Selectors and the page-initiated stock request are grounded in the official
2026-10-17 PDP. No independent API request, user account, cart or coupon action
is made. The caller must use PublicPageFetcher (including its robots checks).
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import evidence, money, offer_id
from app.collectors.transport import CollectionError, SourceDeferred, retry_after

SCHEMA = "bikehunt-decathlon-cn-selected-v1"
PANEL = "#product-right-content"
SIZES = PANEL + " .sku-size .size-list > div"
SELECTED = "border-[#3643BA]"
STOCK_PATH = "/facade_order/api/v4/stock/online_stocks"
STOCK_HOSTS = {"api-cn.decathlon.com.cn"}


class DecathlonAccessDenied(CollectionError):
    """Terminal public-page denial; do not retry with another route/session."""


def _text(node) -> str:
    return " ".join(str(node.get_all_text(separator=" ", strip=True)).split())


def _canonical(url: str) -> str | None:
    parsed = urlsplit(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    if (parsed.scheme != "https" or parsed.hostname != "www.decathlon.com.cn"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.path != "/product-detail" or parsed.fragment
            or set(params) - {"dsm_code", "model_code"}
            or "dsm_code" not in params
            or any(len(v) != 1 or not re.fullmatch(r"\d{5,9}", v[0]) for v in params.values())):
        return None
    return "https://www.decathlon.com.cn/product-detail?" + urlencode(
        [(key, params[key][0]) for key in ("dsm_code", "model_code") if key in params])


def _stock_request(url: str) -> str | None:
    """Identify the read-only request the site's own size control generated."""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in STOCK_HOSTS
            or parsed.path != STOCK_PATH or parsed.username or parsed.password):
        return None
    params = parse_qs(parsed.query, keep_blank_values=True)
    values = params.get("item_codes", [])
    if len(values) != 1 or not re.fullmatch(r"\d{5,12}", values[0]):
        return None
    # This fresh browser must not import or submit a user's location.
    if any(params.get(field, [""]) != [""] for field in ("province", "city")):
        return None
    return values[0]


def _stock_quantity(payload: object, item_code: str) -> int | None:
    # The public PDP accesses response[0].quantity. Fail closed on unknown or
    # application-error envelopes even if the HTTP request itself succeeded.
    if isinstance(payload, dict):
        if type(payload.get("code")) is not int or payload["code"] != 0:
            return None
        payload = payload.get("data")
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        return None
    row = payload[0]
    if "item_code" in row and str(row["item_code"]) != item_code:
        return None
    quantity = row.get("quantity")
    return quantity if type(quantity) is int and 0 <= quantity <= 10_000_000 else None


def _dom_stock(panel: Selector) -> int | None:
    labels = [node for node in panel.css("span") if re.fullmatch(r"线上库存\s*\d+", _text(node))]
    empty = [node for node in panel.css("span") if _text(node) == "缺货"]
    if len(labels) == 1 and not empty:
        return int(re.search(r"\d+$", _text(labels[0]))[0])
    if len(empty) == 1 and not labels:
        return 0
    return None


def _selected_size(panel: Selector) -> str | None:
    selected = [node for node in panel.css(".sku-size .size-list > div")
                if SELECTED in node.attrib.get("class", "").split()
                and "font_maincolor" in node.attrib.get("class", "").split()]
    return _text(selected[0]) if len(selected) == 1 else None


def parse_decathlon_cn(html: str, source: dict, page_url: str, fetched_at: datetime) -> list[Offer]:
    """Only accepted selected-response captures can become fresh CNY offers."""
    canonical = _canonical(page_url)
    if not canonical or source.get("code") != "decathlon_cn" or source.get("currency") != "CNY" or source.get("market") != "CN":
        return []
    try:
        capture = json.loads(html)
        observed = datetime.fromisoformat(capture["observed_at"].replace("Z", "+00:00"))
        if (capture.get("schema") != SCHEMA or _canonical(capture["url"]) != canonical
                or observed.tzinfo is None or fetched_at.tzinfo is None
                or not timedelta(0) <= fetched_at - observed <= timedelta(minutes=15)
                or capture.get("stock_response_status") != 200
                or not re.fullmatch(r"\d{5,12}", capture["item_code"])
                or type(capture.get("quantity")) is not int
                or not 0 <= capture["quantity"] <= 10_000_000):
            return []
        panels = Selector(capture["html"]).css(PANEL)
        if len(panels) != 1:
            return []
        panel = panels[0]
        selected = _selected_size(panel)
        if not selected or selected != capture["selected_size"] or _dom_stock(panel) != capture["quantity"]:
            return []
        # The fixed/sticky header duplicates these values; use the actual PDP
        # details and direct .p-price child, not recommendations or coupon price.
        base = panel.css(".pdp-base-info-box")
        if len(base) != 1:
            return []
        names = base[0].css('div[class~="text-1A2A34"][class~="text-24"]')
        brands = base[0].css('div[class~="text-16"][class~="mb-4"]')
        codes = base[0].css('span[class~="text-16"][class~="text-[#B3BAC3]"]')
        prices = base[0].css(".p-price > .price-format-display")
        colors = panel.css(".sku-color > div:first-child > span")
        images = [n.attrib.get("src") for n in panel.css(".sku-color .color-list > img")
                  if SELECTED in n.attrib.get("class", "").split()]
        if any(len(values) != 1 for values in (names, brands, codes, prices, colors, images)):
            return []
        title, brand, model, color = _text(names[0]), _text(brands[0]), _text(codes[0]), _text(colors[0])
        if not all((title, brand, color)) or not re.fullmatch(r"\d{7,9}", model):
            return []
        params = parse_qs(urlsplit(page_url).query)
        if params.get("model_code", [model]) != [model]:
            return []
        quoted = re.fullmatch(r"￥\s*(\d[\d,]*)\s*(\.\d{2})?", _text(prices[0]))
        price = money(quoted[1].replace(",", "") + (quoted[2] or ".00"), "CNY") if quoted else None
        if not price or price.amount <= 0:
            return []
        image = images[0]
        if not image or urlsplit(image).scheme != "https" or urlsplit(image).hostname != "pixl.decathlon.com.cn":
            return []
        name = brand + " " + title
        gender = "unisex" if "男女" in title else "male" if "男士" in title else "female" if "女士" in title else None
        model_url = "https://www.decathlon.com.cn/product-detail?" + urlencode({"dsm_code": params["dsm_code"][0], "model_code": model})
        requirements = [f"购买时请在官网重新选择 {selected} / {color}；库存为该规格公开线上库存，不保证实际履约。"]
        if "预估到手" in _text(base[0]):
            requirements.append("官网另有预估到手价或领券活动；资格、有效期及实际抵扣未验证，报价使用未领券商品价。")
        return [Offer(
            offer_id=offer_id(source["code"], model_url, capture["item_code"]),
            source_code=source["code"], source_name=source["name"], name=name,
            identity=ProductIdentity(brand=brand, model=name, mpn=model, size=selected, color=color, gender=gender),
            url=model_url, collection_url=model_url, image=image, price=price,
            stock="in_stock" if capture["quantity"] > 0 else "out_of_stock",
            stock_quantity=capture["quantity"], fetched_at=observed,
            family_hint=model, sales_region="中国大陆 CNY 报价",
            shipping_to_china=evidence(source, "china_shipping"),
            china_issued_card=evidence(source, "china_credit_card"),
            purchase_requirements=requirements,
            identity_evidence="迪卡侬中国官网公开页面逐个选择尺码；等待该次线上库存请求成功完成，核对选中颜色/尺码、型号、人民币商品价与库存数量；不使用默认规格、优惠券预估价或门店库存。",
        )]
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return []


def decathlon_cn_page_action(captures: list[bytes], max_variants: int = 20,
                             utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                             sleep: Callable[[float], None] = time.sleep) -> Callable:
    """Capture each size only after its own successful stock request and DOM join.

    Initial DOM may display a previous size's stock for hundreds of milliseconds.
    Merely waiting for a selected class, a fixed sleep, or network-idle is not
    evidence. We require the size-control request and its matching quantity.
    """
    def action(page) -> None:
        if not _canonical(page.url):
            raise CollectionError("Unexpected Decathlon China product URL")
        page.wait_for_selector(SIZES, state="visible", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        sizes = page.locator(SIZES).evaluate_all("nodes => nodes.map(n => n.textContent.trim().replace(/\\s+/g, ' '))")
        if not 2 <= len(sizes) <= max_variants or len(set(sizes)) != len(sizes) or any(not s for s in sizes):
            raise CollectionError("Ambiguous or unsupported Decathlon size list")
        initial = _selected_size(Selector(page.locator(PANEL).inner_html()))
        # Start with another size so every saved variant has a fresh request;
        # never accept the unobserved initial/default stock, including zero.
        ordered = [size for size in sizes if size != initial] + ([initial] if initial in sizes else [])
        staged: list[bytes] = []
        for size in ordered:
            # Same domain, sequential selections, at least one second apart.
            # PublicPageFetcher separately handles robots and document limits.
            sleep(1)
            button = page.locator(SIZES).filter(has_text=re.compile(r"^\s*" + re.escape(size) + r"\s*$"))
            if button.count() != 1:
                raise CollectionError("Decathlon exact size selector is ambiguous")
            try:
                with page.expect_response(lambda response: response.request.method == "GET" and _stock_request(response.url), timeout=20000) as pending:
                    button.click()
                response = pending.value
                if response.status == 429 or (response.status == 503 and any(
                        key.casefold() == "retry-after" for key in response.headers)):
                    raise SourceDeferred("Decathlon online stock temporarily deferred", retry_after(response, utcnow()))
                if response.status in (401, 403):
                    raise DecathlonAccessDenied("Decathlon online stock access denied")
                if response.status != 200 or response.finished():
                    raise CollectionError("Decathlon selected stock request failed")
                item_code = _stock_request(response.url)
                quantity = _stock_quantity(response.json(), item_code)
                if quantity is None:
                    raise CollectionError("Decathlon selected stock response is unverified")
                # Response body completion precedes Vue's DOM update. Wait for
                # both selected size and displayed stock to equal THIS response.
                page.wait_for_function("""({size, quantity}) => {
                  const root = document.querySelector('#product-right-content');
                  if (!root) return false;
                  const selected = [...root.querySelectorAll('.sku-size .size-list > div')]
                    .filter(n => n.classList.contains('font_maincolor') && n.classList.contains('border-[#3643BA]'));
                  if (selected.length !== 1 || selected[0].textContent.trim().replace(/\\s+/g, ' ') !== size) return false;
                  const labels = [...root.querySelectorAll('span')].map(n => n.textContent.trim().replace(/\\s+/g, ' '));
                  return quantity > 0 ? labels.filter(s => /^线上库存\\s*\\d+$/.test(s)).length === 1 && labels.includes('线上库存 ' + quantity)
                    : labels.filter(s => s === '缺货').length === 1 || labels.includes('线上库存 0');
                }""", arg={"size": size, "quantity": quantity}, timeout=15000)
                panel = page.locator(PANEL).evaluate("node => node.outerHTML.replace(/src=\"data:[^\"]+\"/g, 'src=\"\"')")
                if _selected_size(Selector(panel)) != size or _dom_stock(Selector(panel)) != quantity:
                    raise CollectionError("Decathlon selected stock DOM did not settle")
                staged.append(json.dumps({"schema": SCHEMA, "url": page.url,
                    "observed_at": utcnow().isoformat(), "selected_size": size,
                    "item_code": item_code, "quantity": quantity,
                    "stock_response_status": 200, "html": panel}, ensure_ascii=False).encode())
            except CollectionError:
                raise
            except Exception as exc:
                raise CollectionError("Decathlon selected size could not be verified") from exc
        # All-or-nothing within a model: a failed later selection cannot leak a
        # partially updated model, nor an unverified raw final page.
        captures.extend(staged)
    return action


def preserve_decathlon_cn_identity(fresh: list[Offer], existing: list[Offer]) -> list[Offer]:
    """Retain IDs/card names only after exact model, color, title and size match.

    No price, quantity, timestamp, requirements or eligibility is taken from an
    old row. New sizes can share a verified same-model/color sibling's card.
    """
    def compact(text: str | None) -> str:
        return re.sub(r"\s+", "", text or "").casefold()

    def key(row: Offer):
        identity = row.identity
        return (row.source_code, identity.mpn, compact(identity.brand),
                compact(identity.color), compact(identity.model))

    result = []
    for row in fresh:
        matches = [old for old in existing if old.source_code == "decathlon_cn"
                   and key(old) == key(row) and old.price.currency == row.price.currency]
        exact = [old for old in matches if compact(old.identity.size) == compact(row.identity.size)]
        if len(exact) == 1:
            old = exact[0]
            row = row.model_copy(update={"offer_id": old.offer_id, "name": old.name,
                "identity": old.identity.model_copy(deep=True), "family_hint": old.family_hint})
        elif not exact and matches and len({(old.family_hint, old.identity.model, old.identity.gender, old.identity.year) for old in matches}) == 1:
            old = matches[0]
            identity = row.identity.model_copy(update={"brand": old.identity.brand,
                "model": old.identity.model, "color": old.identity.color,
                "gender": old.identity.gender, "year": old.identity.year})
            row = row.model_copy(update={"identity": identity, "name": old.name, "family_hint": old.family_hint})
        result.append(row)
    return result
