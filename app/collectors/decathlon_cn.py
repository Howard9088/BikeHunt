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
PUBLIC_DIAGNOSTICS = frozenset({
    "decathlon_root_object", "decathlon_root_array", "decathlon_root_other_type",
    "decathlon_code_missing", "decathlon_code_zero", "decathlon_code_200",
    "decathlon_code_other_integer", "decathlon_code_string_zero",
    "decathlon_code_string_200", "decathlon_code_other_string", "decathlon_code_other_type",
    "decathlon_data_missing", "decathlon_data_array", "decathlon_data_object", "decathlon_data_other_type",
    "decathlon_rows_empty", "decathlon_rows_one", "decathlon_rows_many",
    "decathlon_quantity_missing", "decathlon_quantity_integer", "decathlon_quantity_float",
    "decathlon_quantity_string", "decathlon_quantity_boolean", "decathlon_quantity_other_type",
    "decathlon_item_missing", "decathlon_item_matches", "decathlon_item_mismatch",
    "decathlon_parse_source", "decathlon_parse_capture_url", "decathlon_parse_time",
    "decathlon_parse_response_status", "decathlon_parse_item", "decathlon_parse_quantity",
    "decathlon_parse_panel", "decathlon_parse_size", "decathlon_parse_stock",
    "decathlon_parse_base", "decathlon_parse_title", "decathlon_parse_brand",
    "decathlon_parse_model", "decathlon_parse_price", "decathlon_parse_color",
    "decathlon_parse_swatch", "decathlon_parse_model_url", "decathlon_parse_fields",
})


class DecathlonAccessDenied(CollectionError):
    """Terminal public-page denial; do not retry with another route/session."""


class DecathlonStockShapeUnverified(CollectionError):
    """Finite diagnostic flags only; never retain a response or credentials."""

    def __init__(self, payload: object, item_code: str) -> None:
        super().__init__("Decathlon selected stock response is unverified")
        self.diagnostics = _stock_shape_flags(payload, item_code)


class DecathlonCaptureRejected(CollectionError):
    """A recognized selection capture failed a fixed, public parser gate."""

    def __init__(self, diagnostic: str) -> None:
        super().__init__("Decathlon selected capture failed validation")
        self.diagnostics = [diagnostic if diagnostic in PUBLIC_DIAGNOSTICS else "decathlon_parse_fields"]


def _require_capture(condition: bool, diagnostic: str) -> None:
    if not condition:
        raise DecathlonCaptureRejected(diagnostic)


def _stock_shape_flags(payload: object, item_code: str) -> list[str]:
    """Inspect known fields without emitting arbitrary field names or values.

    This is diagnostic only. An unfamiliar shape is still rejected and the
    collector never logs the body, request headers, anonymous tokens or URLs.
    """
    flags = []
    if isinstance(payload, dict):
        flags.append("decathlon_root_object")
        code = payload.get("code")
        if "code" not in payload:
            flags.append("decathlon_code_missing")
        elif type(code) is int:
            flags.append("decathlon_code_zero" if code == 0 else "decathlon_code_200" if code == 200 else "decathlon_code_other_integer")
        elif isinstance(code, str):
            flags.append("decathlon_code_string_zero" if code == "0" else "decathlon_code_string_200" if code == "200" else "decathlon_code_other_string")
        else:
            flags.append("decathlon_code_other_type")
        if "data" not in payload:
            flags.append("decathlon_data_missing")
        else:
            flags.append("decathlon_data_array" if isinstance(payload["data"], list) else "decathlon_data_object" if isinstance(payload["data"], dict) else "decathlon_data_other_type")
        payload = payload.get("data")
    elif isinstance(payload, list):
        flags.append("decathlon_root_array")
    else:
        return ["decathlon_root_other_type"]
    if isinstance(payload, list):
        flags.append("decathlon_rows_empty" if not payload else "decathlon_rows_one" if len(payload) == 1 else "decathlon_rows_many")
        if len(payload) == 1 and isinstance(payload[0], dict):
            row = payload[0]
            quantity = row.get("quantity")
            if "quantity" not in row:
                flags.append("decathlon_quantity_missing")
            else:
                names = {int: "decathlon_quantity_integer", float: "decathlon_quantity_float", str: "decathlon_quantity_string", bool: "decathlon_quantity_boolean"}
                flags.append(names.get(type(quantity), "decathlon_quantity_other_type"))
            flags.append("decathlon_item_missing" if "item_code" not in row else "decathlon_item_matches" if str(row["item_code"]) == item_code else "decathlon_item_mismatch")
    return flags


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


def _stock_endpoint(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in STOCK_HOSTS and parsed.path == STOCK_PATH


def _stock_quantity(payload: object, item_code: str) -> int | None:
    # The served official HTTP interceptor unwraps data on HTTP 200/201 when
    # code exists (0 OR a truthy value). The stock view consumes [0].quantity
    # without interpreting code. Treat that code as opaque, never as proof of
    # success: HTTP200, exact item identity and settled selected DOM must also
    # be joined by the caller. CI observed a nonempty string code, singleton
    # data array, explicit matching item_code and integer quantity.
    if isinstance(payload, dict):
        code = payload.get("code")
        if (_explicit_stock_error(payload)
                or not (type(code) is int and code == 0 or isinstance(code, str) and code.strip())):
            return None
        payload = payload.get("data")
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        return None
    row = payload[0]
    if _explicit_stock_error(row) or "item_code" not in row or str(row["item_code"]) != item_code:
        return None
    quantity = row.get("quantity")
    return quantity if type(quantity) is int and 0 <= quantity <= 10_000_000 else None


def _explicit_stock_error(value: dict) -> bool:
    """Reject explicit failures, even if they carry a stale-looking data row."""
    if any(value.get(key) not in (None, "", False, [], {}) for key in ("error", "errors")):
        return True
    if any(value.get(key) is False or type(value.get(key)) is int and value[key] == 0
           or isinstance(value.get(key), str) and value[key].strip().casefold() == "false"
           for key in ("success", "ok")):
        return True
    if any(isinstance(value.get(key), str) and re.search(
            r"\b(?:error|failed|failure|forbidden|unauthorized|denied|invalid)\b|失败|错误|无权限|未授权|拒绝|异常",
            value[key], flags=re.I) for key in ("message", "msg")):
        return True
    for key in ("code", "status", "status_code", "statusCode"):
        status = value.get(key)
        if key != "code" and (status is False or isinstance(status, str) and status.strip().casefold() == "false"):
            return True
        if type(status) is int and 400 <= status <= 599:
            return True
        if isinstance(status, str) and re.fullmatch(
                r"(?:error|fail|failed|failure|invalid|invalid_request|forbidden|unauthorized|denied|[45]\d{2}|E\d{2}-[A-Z0-9-]+|SB_\d+)",
                status.strip(), flags=re.I):
            return True
    return False


# Image-only recovery metadata from the previously published, manually verified
# exact CN product/color observations. Never used for price, stock or freshness.
VERIFIED_IMAGE_SEEDS = ({'identity': {'brand': 'VAN RYSEL', 'model': 'VAN RYSEL 男士骑行背带短裤 RCR-R 5 - 黑色', 'mpn': '8969603', 'size': 'M - 180/80A', 'color': '烟熏黑', 'gender': 'male'}, 'image': 'https://pixl.decathlon.com.cn/p3043223/k$4140c9f5c953c033f539ba057e40434c/content.jpg', 'url': 'https://www.decathlon.com.cn/product-detail?dsm_code=367685&model_code=8969603', 'fetched_at': '2026-10-16T05:29:14Z'}, {'identity': {'brand': 'VAN RYSEL', 'model': 'VAN RYSEL 男女同款迪卡侬 CMA CGM队版复刻版公路骑行服 RCR竞赛系列', 'mpn': '8987878', 'size': 'M', 'color': '孔雀蓝', 'gender': 'unisex'}, 'image': 'https://pixl.decathlon.com.cn/p3154827/k$0847c4ceacd8c8f51fc26bdc6b51d0b8/content.jpg', 'url': 'https://www.decathlon.com.cn/product-detail?dsm_code=355348', 'fetched_at': '2026-10-16T05:29:14Z'})


def _official_image(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        asset = urlsplit(value)
        if (asset.scheme == "https" and asset.hostname == "pixl.decathlon.com.cn"
                and asset.port in (None, 443) and not asset.username and not asset.password
                and not asset.fragment):
            return value
    except ValueError:
        pass
    return None


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
    """Only accepted selected-response captures can become fresh CNY offers.

    Ignore the unverified initial HTML and unrelated formats. A rejected capture
    with our schema is terminal for this model, so a missing size cannot silently
    become a partially refreshed model. Diagnostics contain fixed gate names only.
    """
    try:
        capture = json.loads(html)
    except (ValueError, TypeError):
        return []
    if not isinstance(capture, dict) or capture.get("schema") != SCHEMA:
        return []
    try:
        _require_capture(source.get("code") == "decathlon_cn" and source.get("currency") == "CNY"
                         and source.get("market") == "CN", "decathlon_parse_source")
        try:
            canonical = _canonical(page_url)
            matching_url = canonical and _canonical(capture["url"]) == canonical
        except (ValueError, KeyError, TypeError, AttributeError):
            matching_url = False
        _require_capture(bool(matching_url), "decathlon_parse_capture_url")
        try:
            observed = datetime.fromisoformat(capture["observed_at"].replace("Z", "+00:00"))
            current = (observed.tzinfo is not None and fetched_at.tzinfo is not None
                       and timedelta(0) <= fetched_at - observed <= timedelta(minutes=15))
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            current = False
        _require_capture(current, "decathlon_parse_time")
        _require_capture(type(capture.get("stock_response_status")) is int
                         and capture["stock_response_status"] == 200, "decathlon_parse_response_status")
        _require_capture(isinstance(capture.get("item_code"), str)
                         and bool(re.fullmatch(r"\d{5,12}", capture["item_code"])), "decathlon_parse_item")
        _require_capture(type(capture.get("quantity")) is int
                         and 0 <= capture["quantity"] <= 10_000_000, "decathlon_parse_quantity")
        _require_capture(isinstance(capture.get("html"), str) and bool(capture["html"]), "decathlon_parse_panel")
        panels = Selector(capture["html"]).css(PANEL)
        _require_capture(len(panels) == 1, "decathlon_parse_panel")
        panel = panels[0]
        selected = _selected_size(panel)
        _require_capture(bool(selected) and selected == capture.get("selected_size"), "decathlon_parse_size")
        _require_capture(_dom_stock(panel) == capture["quantity"], "decathlon_parse_stock")
        # The fixed/sticky header duplicates these values; use the actual PDP
        # details and direct .p-price child, not recommendations or coupon price.
        base = panel.css(".pdp-base-info-box")
        _require_capture(len(base) == 1, "decathlon_parse_base")
        names = base[0].css('div[class~="text-1A2A34"][class~="text-24"]')
        brands = base[0].css('div[class~="text-16"][class~="mb-4"]')
        codes = base[0].css('span[class~="text-16"][class~="text-[#B3BAC3]"]')
        prices = base[0].css(".p-price > .price-format-display")
        colors = panel.css(".sku-color > div:first-child > span")
        images = [n for n in panel.css(".sku-color .color-list > img")
                  if SELECTED in n.attrib.get("class", "").split()]
        for values, gate in ((names, "title"), (brands, "brand"), (codes, "model"),
                             (prices, "price"), (colors, "color"), (images, "swatch")):
            _require_capture(len(values) == 1, "decathlon_parse_" + gate)
        title, brand, model, color = _text(names[0]), _text(brands[0]), _text(codes[0]), _text(colors[0])
        _require_capture(bool(title), "decathlon_parse_title")
        _require_capture(bool(brand), "decathlon_parse_brand")
        _require_capture(bool(color), "decathlon_parse_color")
        _require_capture(bool(re.fullmatch(r"\d{7,9}", model)), "decathlon_parse_model")
        params = parse_qs(urlsplit(page_url).query)
        _require_capture(params.get("model_code", [model]) == [model], "decathlon_parse_model_url")
        quoted = re.fullmatch(r"￥\s*(\d[\d,]*)\s*(\.\d{2})?", _text(prices[0]))
        price = money(quoted[1].replace(",", "") + (quoted[2] or ".00"), "CNY") if quoted else None
        _require_capture(price is not None and price.amount > 0, "decathlon_parse_price")
        # PublicPageFetcher intentionally disables image downloads. The official
        # lazyImg directive first installs default-img.png and only swaps in the
        # real asset after onload. Thumbnail loading is not identity evidence:
        # keep the exact selected swatch and textual color checks above, but omit
        # absent/placeholder/unsupported images instead of discarding valid stock.
        image = (_official_image(images[0].attrib.get("src"))
                 or _official_image(images[0].attrib.get("data-bh-bound-image-src")))
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
        raise DecathlonCaptureRejected("decathlon_parse_fields") from None


def decathlon_cn_page_action(captures: list[bytes], max_variants: int = 20,
                             utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                             sleep: Callable[[float], None] = time.sleep) -> Callable:
    """Capture each size only after its own successful stock request and DOM join.

    Initial DOM may display a previous size's stock for hundreds of milliseconds.
    Merely waiting for a selected class, a fixed sleep, or network-idle is not
    evidence. We require the size-control request and its matching quantity.
    """
    def action(page) -> None:
        inflight, transaction, active = set(), [], [False]

        def started(request):
            if _stock_endpoint(request.url):
                inflight.add(request)
                if active[0]:
                    transaction.append(request)

        def finished(request):
            inflight.discard(request)

        listeners = (("request", started), ("requestfinished", finished), ("requestfailed", finished))
        for event, listener in listeners:
            page.on(event, listener)
        try:
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
            seen_items: set[str] = set()
            for size in ordered:
                # Same domain, sequential selections, at least one second apart.
                # PublicPageFetcher separately handles robots and document limits.
                sleep(1)
                button = page.locator(SIZES).filter(has_text=re.compile(r"^\s*" + re.escape(size) + r"\s*$"))
                if button.count() != 1:
                    raise CollectionError("Decathlon exact size selector is ambiguous")
                try:
                    before = _selected_size(Selector(page.locator(PANEL).inner_html()))
                    if before == size or inflight:
                        raise CollectionError("Decathlon stock selection is not isolated")
                    transaction.clear()
                    active[0] = True
                    with page.expect_request(lambda request: _stock_endpoint(request.url), timeout=20000) as pending:
                        button.click()
                    request = pending.value
                    if (len(transaction) != 1 or transaction[0] != request
                            or request.method != "GET" or not _stock_request(request.url)):
                        raise CollectionError("Decathlon stock request is not uniquely tied to selection")
                    response = request.response()
                    if response is None or response.request != request:
                        raise CollectionError("Decathlon selected stock response is missing")
                    if response.status == 429 or (response.status == 503 and any(
                            key.casefold() == "retry-after" for key in response.headers)):
                        raise SourceDeferred("Decathlon online stock temporarily deferred", retry_after(response, utcnow()))
                    if response.status in (401, 403):
                        raise DecathlonAccessDenied("Decathlon online stock access denied")
                    if response.status != 200 or response.finished():
                        raise CollectionError("Decathlon selected stock request failed")
                    item_code = _stock_request(response.url)
                    if item_code in seen_items:
                        raise CollectionError("Decathlon item code repeated across different sizes")
                    payload = response.json()
                    quantity = _stock_quantity(payload, item_code)
                    if quantity is None:
                        raise DecathlonStockShapeUnverified(payload, item_code)
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
                    panel = page.locator(PANEL).evaluate("""node => {
                      const copy = node.cloneNode(true);
                      const original = [...node.querySelectorAll('.sku-color .color-list > img')];
                      const cloned = [...copy.querySelectorAll('.sku-color .color-list > img')];
                      original.forEach((img, index) => {
                        if (img.classList.contains('border-[#3643BA]') && typeof img.$data_src === 'string') {
                          try {
                            const url = new URL(img.$data_src);
                            if (url.protocol === 'https:' && url.hostname === 'pixl.decathlon.com.cn'
                                && !url.username && !url.password && !url.port && !url.hash)
                              cloned[index].setAttribute('data-bh-bound-image-src', img.$data_src);
                          } catch (_) {}
                        }
                      });
                      return copy.outerHTML.replace(/src="data:[^"]+"/g, 'src=""');
                    }""")
                    if _selected_size(Selector(panel)) != size or _dom_stock(Selector(panel)) != quantity:
                        raise CollectionError("Decathlon selected stock DOM did not settle")
                    # Recheck AFTER reading the panel: same-quantity variants must
                    # not hide a second or previously in-flight stock response.
                    if len(transaction) != 1 or transaction[0] != request or inflight:
                        raise CollectionError("Decathlon stock request competed with another selection")
                    active[0] = False
                    seen_items.add(item_code)
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
        finally:
            active[0] = False
            for event, listener in listeners:
                page.remove_listener(event, listener)

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
        if not row.image and row.source_code == "decathlon_cn" and row.price.currency == "CNY":
            # A thumbnail is shared across sizes only for this exact model,
            # brand, textual product name and color. Ambiguous history is not used.
            candidates = {_official_image(old.image) for old in matches if _official_image(old.image)}
            provenance = "图片沿用此前同型号同颜色已验证图片；本次库存观察不代表图片重新验证。"
            if not candidates:
                seeds = [seed for seed in VERIFIED_IMAGE_SEEDS
                         if (seed["identity"].get("mpn"), compact(seed["identity"].get("brand")),
                             compact(seed["identity"].get("color")), compact(seed["identity"].get("model"))) == key(row)[1:]]
                candidates = {_official_image(seed["image"]) for seed in seeds if _official_image(seed["image"])}
                if len(seeds) == 1:
                    provenance = "图片沿用 " + seeds[0]["fetched_at"] + " 核实的同型号同颜色官网图片；本次库存观察不代表图片重新验证。"
            if len(candidates) == 1:
                row = row.model_copy(update={"image": next(iter(candidates)),
                    "identity_evidence": row.identity_evidence + "；" + provenance})
        result.append(row)
    return result
