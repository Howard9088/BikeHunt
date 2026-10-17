"""Reduced real-DOM-shaped fixtures; no network or historical freshness promotion."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.catalog.models import Offer
from app.collectors.decathlon_cn import (
    SCHEMA, PUBLIC_DIAGNOSTICS, DecathlonAccessDenied, DecathlonStockShapeUnverified, _stock_quantity, _stock_request,
    decathlon_cn_page_action, parse_decathlon_cn, preserve_decathlon_cn_identity,
)
from app.collectors.fetch_policy import CapturedPage
from app.collectors.rendered import collect_variants
from app.collectors.transport import CollectionError, PublicPageFetcher, SourceDeferred

NOW = datetime(2026, 10, 17, 2, 5, tzinfo=timezone.utc)
URL = "https://www.decathlon.com.cn/product-detail?dsm_code=367685&model_code=8969603"
SOURCE = {"code": "decathlon_cn", "name": "迪卡侬中国官网", "market": "CN", "currency": "CNY"}
STOCK_URL = "https://api-cn.decathlon.com.cn/facade_order/api/v4/stock/online_stocks?item_codes=1234567&province=&city="


def dom(size="M - 180/80A", quantity=443):
    options = "".join(f'<div class="{("border-[#3643BA] font_maincolor" if s == size else "border-[#949494]")}">{s}</div>'
                      for s in ["S - 175/76A", "M - 180/80A"])
    stock = f'<span>线上库存 <span>{quantity}</span></span>' if quantity else '<span>缺货</span>'
    return f'''<div id="product-right-content"><div class="pdp-base-info-box">
      <div class="fixed-base-info"><div class="price-format-display">￥1.00</div></div>
      <div class="text-16 mb-4">VAN RYSEL</div>
      <div class="text-1A2A34 text-24">男士骑行背带短裤RCR-R 5 - 黑色</div>
      <span class="text-16 text-[#B3BAC3]">8969603</span>
      <div class="p-price"><div class="price-format-display"><div>￥399</div><div>.90</div></div>
       <div>预估到手 <div class="price-format-display">￥369.90</div></div></div></div>
      <div class="sku-color"><div><p>颜色</p><span>烟熏黑</span></div><div class="color-list">
       <img class="border-[#3643BA]" src="https://pixl.decathlon.com.cn/p3043223/content.jpg"></div></div>
      <div class="sku-size"><div class="size-list">{options}</div></div>{stock}
      <span>查看门店库存</span><button>加入购物车</button></div>'''


def fixture(**update):
    capture = {"schema": SCHEMA, "url": URL, "observed_at": NOW.isoformat(),
               "selected_size": "M - 180/80A", "item_code": "1234567", "quantity": 443,
               "stock_response_status": 200, "html": dom()}
    capture.update(update)
    return json.dumps(capture)


class ParserTests(unittest.TestCase):
    def parse(self, value=None, url=URL, source=SOURCE, at=NOW):
        return parse_decathlon_cn(value or fixture(), source, url, at)

    def test_exact_selected_price_color_size_quantity_and_time(self):
        row = self.parse()[0]
        self.assertEqual((row.identity.mpn, row.identity.color, row.identity.size), ("8969603", "烟熏黑", "M - 180/80A"))
        self.assertEqual((str(row.price.amount), row.price.currency, row.stock_quantity), ("399.90", "CNY", 443))
        self.assertIsNone(row.original_price)
        self.assertEqual(row.fetched_at, NOW)
        self.assertEqual(row.stock, "in_stock")
        self.assertIn("model_code=8969603", row.collection_url)

    def test_raw_html_manual_snapshot_and_old_envelope_cannot_refresh(self):
        for value in [dom(), json.dumps({"offers": [{"price": 399.9}]}), fixture(observed_at=(NOW-timedelta(days=1)).isoformat())]:
            self.assertEqual(self.parse(value), [])
        self.assertEqual(self.parse(fixture(observed_at=(NOW+timedelta(seconds=1)).isoformat())), [])
        self.assertEqual(self.parse(fixture(observed_at=NOW.replace(tzinfo=None).isoformat())), [])

    def test_wrong_market_currency_host_and_model_rejected(self):
        for url in [URL.replace("https", "http"), URL.replace(".com.cn", ".fr"), URL.replace("8969603", "8987878"), URL + "&dsm_code=999999"]:
            self.assertEqual(self.parse(url=url), [])
        for source in [dict(SOURCE, market="US"), dict(SOURCE, currency="USD"), dict(SOURCE, code="decathlon")]:
            self.assertEqual(self.parse(source=source), [])

    def test_stale_previous_size_stock_is_rejected(self):
        self.assertEqual(self.parse(fixture(html=dom(quantity=123))), [])
        self.assertEqual(self.parse(fixture(selected_size="S - 175/76A")), [])
        self.assertEqual(self.parse(fixture(html=dom().replace("font_maincolor", ""))), [])

    def test_explicit_zero_is_oos_but_missing_conflicting_or_store_stock_is_not(self):
        row = self.parse(fixture(quantity=0, html=dom(quantity=0)))[0]
        self.assertEqual((row.stock, row.stock_quantity), ("out_of_stock", 0))
        for value in [dom().replace("线上库存", "门店库存"), dom().replace("线上库存", "库存待查"), dom().replace("</button>", "</button><span>缺货</span>")]:
            self.assertEqual(self.parse(fixture(html=value)), [])

    def test_coupon_or_recommendation_price_cannot_replace_product_price(self):
        self.assertEqual(self.parse(fixture(html=dom().replace('class="p-price"', 'class="other"'))), [])
        self.assertEqual(self.parse(fixture(html=dom().replace('￥399', '$399'))), [])

    def test_each_capture_keeps_own_observation_time_and_fingerprint(self):
        body = fixture().encode()
        page = CapturedPage(dom().encode(), 200, URL, {}, "dynamic", NOW+timedelta(seconds=25), [body])
        rows = collect_variants(page, SOURCE, parse_decathlon_cn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].fetched_at, NOW)
        self.assertEqual(rows[0].fetch_mode, "dynamic")
        self.assertEqual(len(rows[0].evidence_sha256), 64)

    def test_preserve_legacy_identity_without_old_stock_price_or_requirements(self):
        old = Offer.model_validate(json.loads((Path(__file__).parents[1]/"data/offers/decathlon_cn.json").read_text())["offers"][0])
        fresh = self.parse()[0]
        row = preserve_decathlon_cn_identity([fresh], [old])[0]
        self.assertEqual(row.offer_id, "decathlon_cn-8969603-M")
        self.assertEqual(row.identity, old.identity)
        self.assertEqual(row.family_hint, old.family_hint)
        self.assertEqual(row.stock_quantity, 443)
        self.assertEqual(row.fetched_at, NOW)
        self.assertEqual(row.purchase_requirements, fresh.purchase_requirements)
        new = self.parse(fixture(html=dom(size="S - 175/76A"), selected_size="S - 175/76A", item_code="7654321"))[0]
        reconciled = preserve_decathlon_cn_identity([new], [old])[0]
        self.assertEqual(reconciled.identity.model, old.identity.model)
        self.assertEqual(reconciled.identity.size, "S - 175/76A")
        self.assertEqual(reconciled.offer_id, new.offer_id)
        changed = fresh.model_copy(update={"identity": fresh.identity.model_copy(update={"color": "浅暖灰"})})
        self.assertEqual(preserve_decathlon_cn_identity([changed], [old])[0], changed)

    def test_stock_response_must_identify_one_item_and_successful_numeric_quantity(self):
        self.assertEqual(_stock_request(STOCK_URL), "1234567")
        for url in [STOCK_URL.replace("api-cn.decathlon.com.cn", "evil.example"), STOCK_URL.replace("1234567", "1234567,7654321"), STOCK_URL.replace("city=", "city=Shanghai")]:
            self.assertIsNone(_stock_request(url))
        self.assertEqual(_stock_quantity({"code": 0, "data": [{"item_code": "1234567", "quantity": 443}]}, "1234567"), 443)
        for payload in [{"code": 1, "data": [{"quantity": 443}]}, [{"quantity": True}], [{"quantity": -1}], [{"quantity": "443"}], [{"quantity": 0}, {"quantity": 443}], [{"item_code": "other", "quantity": 443}]]:
            self.assertIsNone(_stock_quantity(payload, "1234567"))

    def test_opaque_code_is_not_success_evidence_without_exact_stock_contract(self):
        row = {"item_code": "1234567", "quantity": 443}
        # Deliberately fictional opaque marker: no guessed vendor success code.
        payload = {"code": "opaque-envelope-marker", "data": [row]}
        self.assertEqual(_stock_quantity(payload, "1234567"), 443)
        self.assertEqual(_stock_quantity(dict(payload, data=[dict(row, quantity=0)]), "1234567"), 0)
        for bad_row in [dict(row, item_code="7654321"), {"quantity": 443}, {"item_code": "1234567"},
                        dict(row, quantity=-1), dict(row, quantity=1.5), dict(row, quantity=443.0),
                        dict(row, quantity="443"), dict(row, quantity=True), dict(row, errors=["failure"])]:
            self.assertIsNone(_stock_quantity(dict(payload, data=[bad_row]), "1234567"))
        for update in [{"data": [row, row]}, {"data": []}, {"data": row}, {"error": "failure"},
                       {"errors": [{"message": "failure"}]}, {"success": False}, {"ok": False},
                       {"success": "false"}, {"success": 0}, {"ok": " false "}, {"ok": 0},
                       {"status": False}, {"status": "false"}, {"code": "invalid"},
                       {"status": "failed"}, {"status_code": 403}, {"statusCode": "500"},
                       {"msg": "request failed"}, {"message": "库存请求错误"},
                       {"code": "ERROR"}, {"code": "E08-2201"}, {"code": ""}, {"code": False}]:
            self.assertIsNone(_stock_quantity(dict(payload, **update), "1234567"))

    def test_shape_diagnostics_never_leak_body_keys_values_or_credentials(self):
        payload = {"code": "private-token-value", "credential-secret-key": "private-token-value",
                   "data": [{"item_code": "7654321", "quantity": "443", "extra-private-key": "private-token-value"}]}
        error = DecathlonStockShapeUnverified(payload, "1234567")
        self.assertEqual(error.diagnostics, ["decathlon_root_object", "decathlon_code_other_string", "decathlon_data_array", "decathlon_rows_one", "decathlon_quantity_string", "decathlon_item_mismatch"])
        self.assertTrue(set(error.diagnostics) <= PUBLIC_DIAGNOSTICS)
        self.assertFalse(any(secret in str(error.__dict__) + str(error) for secret in ["private-token-value", "credential-secret-key", "7654321", "443"]))
        self.assertFalse(hasattr(error, "payload"))
        self.assertIsNone(_stock_quantity(payload, "1234567"))
        candidate = {"code": 200, "data": [{"quantity": 443}]}
        self.assertIn("decathlon_code_200", DecathlonStockShapeUnverified(candidate, "1234567").diagnostics)
        self.assertIsNone(_stock_quantity(candidate, "1234567"))


class FakeLocator:
    def __init__(self, page, kind="panel", pattern=None):
        self.page, self.kind, self.pattern = page, kind, pattern
    def evaluate_all(self, script): return ["S - 175/76A", "M - 180/80A"]
    def inner_html(self): return dom(self.page.size, self.page.quantity)
    def evaluate(self, script):
        if self.page.late_competing:
            self.page.emit("request", FakeRequest(self.page, FakeResponse()))
        return dom(self.page.size, self.page.quantity)
    def filter(self, has_text): return FakeLocator(self.page, "size", has_text)
    def count(self): return 1
    def click(self):
        self.page.size = next(s for s in ["S - 175/76A", "M - 180/80A"] if self.pattern.fullmatch(s))
        self.page.clicked.append(self.page.size)
        # Selection changes before stock. Keep preceding quantity until wait.
        request = FakeRequest(self.page, self.page.response)
        self.page.current_request = request
        self.page.emit("request", request)
        if self.page.competing:
            self.page.emit("request", FakeRequest(self.page, FakeResponse()))


class FakeResponse:
    url, status, headers = STOCK_URL, 200, {}
    def finished(self):
        self.request.page.emit("requestfinished", self.request)
        return None
    def json(self): return {"code": "opaque-envelope-marker", "data": [{"item_code": _stock_request(self.url), "quantity": 443}]}


class FakeRequest:
    method = "GET"
    def __init__(self, page, response):
        self.page, self._response = page, response
        code = "1234567" if page.size == "M - 180/80A" or page.repeat_item else "7654321"
        self.url = STOCK_URL.replace("1234567", code)
        response.url, response.request = self.url, self
    def response(self): return self._response


class FakePending:
    def __init__(self, page, predicate): self.page, self.predicate = page, predicate
    @property
    def value(self): return self.page.current_request
    def __enter__(self): return self
    def __exit__(self, *args): assert self.predicate(self.value)


class FakePage:
    url = URL
    def __init__(self, response=None, fail_settle=False, competing=False, late_competing=False,
                 previous_inflight=False, changed_size=False, repeat_item=False):
        self.response = response or FakeResponse()
        self.size, self.quantity = "S - 175/76A", 123
        self.clicked, self.waits = [], []
        self.fail_settle = fail_settle
        self.competing, self.late_competing = competing, late_competing
        self.previous_inflight, self.changed_size, self.repeat_item = previous_inflight, changed_size, repeat_item
        self.listeners = {}
    def on(self, event, callback): self.listeners.setdefault(event, []).append(callback)
    def remove_listener(self, event, callback): self.listeners[event].remove(callback)
    def emit(self, event, value):
        for callback in self.listeners.get(event, []): callback(value)
    def wait_for_selector(self, *args, **kwargs): pass
    def wait_for_load_state(self, *args, **kwargs):
        if self.previous_inflight: self.emit("request", FakeRequest(self, FakeResponse()))
    def locator(self, selector): return FakeLocator(self)
    def expect_request(self, predicate, **kwargs): return FakePending(self, predicate)
    def wait_for_function(self, script, arg, **kwargs):
        self.waits.append((self.quantity, arg["quantity"]))
        if self.fail_settle: raise TimeoutError("previous stock stayed visible")
        self.quantity = arg["quantity"]
        if self.changed_size: self.size = "S - 175/76A"


class ActionTests(unittest.TestCase):
    def test_selects_other_size_first_and_waits_matching_response_quantity(self):
        page, captures, pauses = FakePage(), [], []
        decathlon_cn_page_action(captures, utcnow=lambda: NOW, sleep=pauses.append)(page)
        self.assertEqual(page.clicked, ["M - 180/80A", "S - 175/76A"])
        self.assertEqual(page.waits[0], (123, 443))
        self.assertEqual(pauses, [1, 1])
        self.assertEqual(len(captures), 2)
        self.assertTrue(all(parse_decathlon_cn(c.decode(), SOURCE, URL, NOW) for c in captures))
        self.assertTrue(all(not callbacks for callbacks in page.listeners.values()))

    def test_equal_quantities_cannot_hide_competing_requests_or_changed_size(self):
        for changes in [{"competing": True}, {"late_competing": True}, {"previous_inflight": True},
                        {"changed_size": True}, {"repeat_item": True}]:
            with self.subTest(changes=changes):
                page, captures = FakePage(**changes), []
                page.quantity = 443  # Both sizes deliberately have equal stock.
                with self.assertRaises(CollectionError):
                    decathlon_cn_page_action(captures, utcnow=lambda: NOW, sleep=lambda _: None)(page)
                self.assertEqual(captures, [])
                self.assertTrue(all(not callbacks for callbacks in page.listeners.values()))

    def test_failed_settle_or_failed_response_never_yields_partial_snapshot(self):
        captures = []
        with self.assertRaises(CollectionError):
            decathlon_cn_page_action(captures, utcnow=lambda: NOW, sleep=lambda _: None)(FakePage(fail_settle=True))
        self.assertEqual(captures, [])
        for status, expected in [(403, DecathlonAccessDenied), (429, SourceDeferred), (503, SourceDeferred)]:
            response = FakeResponse()
            response.status, response.headers = status, {"Retry-After": "120"}
            with self.assertRaises(expected):
                decathlon_cn_page_action(captures, utcnow=lambda: NOW, sleep=lambda _: None)(FakePage(response))
            self.assertEqual(captures, [])

    def test_robots_denial_never_opens_browser(self):
        calls = []
        fetcher = PublicPageFetcher({"www.decathlon.com.cn"}, sleep=lambda _: None,
            request=lambda url, **kwargs: SimpleNamespace(url=url, status=200, body=b"User-agent: *\nDisallow: /product-detail", headers={}),
            browser_request=lambda *args, **kwargs: calls.append(args))
        with self.assertRaises(CollectionError):
            fetcher.fetch(URL, dynamic=True)
        self.assertEqual(calls, [])

    def test_stock_deferral_survives_transport_without_new_browser_retry(self):
        calls, response = [], FakeResponse()
        response.status, response.headers = 429, {"Retry-After": "120"}
        fetcher = PublicPageFetcher({"www.decathlon.com.cn"}, sleep=lambda _: None, utcnow=lambda: NOW,
            request=lambda url, **kwargs: SimpleNamespace(url=url, status=200, body=b"User-agent: *\nAllow: /", headers={}))
        fetcher.page_action = decathlon_cn_page_action(fetcher.variant_pages, utcnow=lambda: NOW, sleep=lambda _: None)
        def browser(url, **kwargs):
            calls.append(url)
            kwargs["page_action"](FakePage(response))
        fetcher.browser_request = browser
        for _ in range(2):
            with self.assertRaises(SourceDeferred) as raised:
                fetcher.fetch(URL, dynamic=True)
            self.assertEqual(raised.exception.retry_at, NOW+timedelta(seconds=120))
        self.assertEqual(calls, [URL])
        self.assertEqual(fetcher.variant_pages, [])


if __name__ == "__main__":
    unittest.main()
