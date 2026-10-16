"""动态抓取独立 Mock 回归：python tests/test_dynamic.py。"""

from __future__ import annotations

import json
import html as html_module
import sys
import unittest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.collectors.discovery import SourceSpec, discover
from app.collectors.fetch_policy import CapturedPage, FetchPolicy
from app.collectors.rendered import collect_variants, parse_pissei, parse_kask_rendered, parse_unox
from app.collectors.transport import CollectionError, PublicPageFetcher, SourceDeferred
from app.collectors.parsers import parse_jsonld
from app.catalog.storage import OfferRepository, atomic_json

URL = "https://shop.example/products/mock"
NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def response(url: str, body: str = "", status: int = 200):
    return SimpleNamespace(url=url, body=body.encode(), status=status, headers={})


class DynamicTests(unittest.TestCase):
    def fetcher(self, html: str = "<html>Loading</html>", status: int = 200):
        calls = []

        def static(url, **kwargs):
            calls.append(("static", url))
            return response(
                url,
                "User-agent: *\nAllow: /" if url.endswith("robots.txt") else html,
                200 if url.endswith("robots.txt") else status,
            )

        def browser(url, **kwargs):
            calls.append(("dynamic", url))
            return response(url, '<select id="sizes"><option>M</option></select>')

        return (
            PublicPageFetcher(
                {"shop.example"},
                request=static,
                browser_request=browser,
                sleep=lambda _: None,
                utcnow=lambda: NOW,
            ),
            calls,
        )

    def test_auto_renders_missing_selector_and_checks_robots_once(self):
        fetcher, calls = self.fetcher()
        page = fetcher.fetch(URL, policy=FetchPolicy(mode="auto", wait_selector="#sizes"))
        self.assertEqual(page.fetch_mode, "dynamic")
        self.assertEqual(
            calls,
            [("static", "https://shop.example/robots.txt"), ("static", URL), ("dynamic", URL)],
        )
        self.assertEqual(len(page.evidence_sha256), 64)

    def test_auto_keeps_valid_static_page(self):
        fetcher, calls = self.fetcher('<div id="sizes">M</div>')
        self.assertEqual(
            fetcher.fetch(URL, policy=FetchPolicy(mode="auto", wait_selector="#sizes")).fetch_mode,
            "static",
        )
        self.assertFalse(any(kind == "dynamic" for kind, _ in calls))

    def test_429_or_403_does_not_escalate_to_browser(self):
        for status in (403, 429):
            fetcher, calls = self.fetcher(status=status)
            with self.subTest(status=status), self.assertRaises(CollectionError):
                fetcher.fetch(URL, policy=FetchPolicy(mode="auto", wait_selector="#sizes"))
            self.assertFalse(any(kind == "dynamic" for kind, _ in calls))

    def test_browser_cannot_redirect_outside_allowed_domains(self):
        fetcher, _ = self.fetcher()
        fetcher.browser_request = lambda *a, **k: response("https://outside.example/", "M")
        with self.assertRaises(CollectionError):
            fetcher.fetch(URL, policy=FetchPolicy(mode="dynamic"))

    def test_swallowed_browser_action_error_does_not_publish_initial_state(self):
        fetcher, _ = self.fetcher()
        fetcher.page_action = lambda _: (_ for _ in ()).throw(ValueError("SKU never changed"))

        def browser(url, **kwargs):
            try:
                kwargs["page_action"](object())
            except ValueError:
                pass
            return response(url, "initial SKU")

        fetcher.browser_request = browser
        with self.assertRaises(CollectionError):
            fetcher.fetch(URL, policy=FetchPolicy(mode="dynamic"))

    def test_browser_retry_discards_partial_variant_capture(self):
        fetcher, _ = self.fetcher()
        attempts = []

        def browser(url, **kwargs):
            attempts.append(url)
            fetcher.variant_pages.append(b"old" if len(attempts) == 1 else b"new")
            if len(attempts) == 1:
                raise ValueError("interrupted selection")
            return response(url, "success")

        fetcher.browser_request = browser
        result = fetcher.fetch(URL, policy=FetchPolicy(mode="dynamic"))
        self.assertEqual(result.variant_pages, [b"new"])

    def test_discovery_is_bounded_scoped_and_never_follows_account_or_foreign_links(self):
        fetcher, calls = self.fetcher(
            '<a href="/products/one?variant=3">one</a>'
            '<a href="https://outside.example/products/bad">bad</a>'
            '<a href="/products/two">two</a><a href="/account/products/no">account</a>'
        )
        spec = SourceSpec(
            "mock",
            frozenset({"shop.example"}),
            ("https://shop.example/collection",),
            r"^/products/",
            FetchPolicy(max_products=1),
        )
        self.assertEqual(discover(spec, fetcher), ["https://shop.example/products/one"])
        self.assertEqual(len(calls), 2)

    def pissei_html(self, quantity=2, disabled=False, parent_id=100, price="€ 80,00"):
        data = {
            "5001": [
                {
                    "id": 101,
                    "id_parent": parent_id,
                    "descr": "M",
                    "disponibilita": quantity,
                    "barcode": "8104600001480",
                    "priceHtml": '<span class="details_article_dett_prezzo_new_price">'
                    + price
                    + "</span>",
                }
            ]
        }
        encoded = json.dumps(json.dumps(data))[1:-1].replace("'", "\\'")
        product = {
            "@type": "Product",
            "name": "Mock Jersey",
            "brand": "PISSEI",
            "sku": "100",
            "offers": {
                "price": "97.60",
                "priceCurrency": "EUR",
                "availability": "https://schema.org/InStock",
            },
        }
        return (
            '<div class="gescat_product-page-main" data-gtm-database-id="100"></div>'
            '<select id="group-5001"><option value="101" '
            + ("disabled" if disabled else "")
            + ">M</option></select>"
            "<script>window.productAttributes = JSON.parse('" + encoded + "');</script>"
            '<script type="application/ld+json">' + json.dumps(product) + "</script>"
        )

    def test_rendered_size_stock_and_price_are_bound_and_vat_is_not_discount(self):
        source = {"code": "uae", "name": "Mock PISSEI"}
        rows = parse_pissei(self.pissei_html(), source, URL, NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].identity.size, "M")
        self.assertEqual(rows[0].stock_quantity, 2)
        self.assertEqual(str(rows[0].price.amount), "80.00")
        self.assertIsNone(rows[0].original_price)
        self.assertEqual(rows[0].stock, "in_stock")

    def test_conflicting_stock_or_wrong_product_is_rejected(self):
        source = {"code": "uae", "name": "Mock"}
        for kwargs in (
            {"quantity": 0},
            {"disabled": True},
            {"parent_id": 999},
            {"quantity": True},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(parse_pissei(self.pissei_html(**kwargs), source, URL, NOW), [])
        rows = parse_pissei(self.pissei_html(quantity=0, disabled=True), source, URL, NOW)
        self.assertEqual(rows[0].stock, "out_of_stock")

    def test_offer_retains_actual_dynamic_mode_and_html_hash(self):
        page = CapturedPage(self.pissei_html().encode(), 200, URL, {}, "dynamic", NOW)
        row = collect_variants(page, {"code": "uae", "name": "Mock"}, parse_pissei)[0]
        self.assertEqual(row.fetch_mode, "dynamic")
        self.assertEqual(row.evidence_sha256, page.evidence_sha256)
        self.assertEqual(row.fetched_at, NOW)

    def test_default_selected_child_does_not_change_the_parent_product(self):
        html = self.pissei_html().replace(
            'data-gtm-database-id="100"',
            'data-gtm-database-id="101" data-gtm-database-parent-id="100"',
        )
        self.assertEqual(len(parse_pissei(html, {"code": "uae", "name": "Mock"}, URL, NOW)), 1)

    def test_kask_response_matches_exact_color_size_currency_and_stock(self):
        url = "https://www.kask.com/en-it/Model/CHE00097-.html"
        data = {
            "selectedProductAbsUrl": "https://www.kask.com/en-it/Model/CHE00097-CE-WG-494.56.html",
            "product": {
                "id": "CHE00097-CE-WG-494.56",
                "masterProductId": "CHE00097-",
                "productName": "Mock helmet",
                "online": True,
                "readyToOrder": True,
                "available": True,
                "price": {
                    "sales": {
                        "value": 100,
                        "decimalPrice": "100.00",
                        "formatted": "€ 100,00",
                        "currency": "EUR",
                    }
                },
                "variationAttributes": [
                    {
                        "id": "size",
                        "values": [{"value": "56", "displayValue": "S", "selected": True}],
                    },
                    {
                        "id": "color",
                        "values": [{"value": "494", "displayValue": "Yellow", "selected": True}],
                    },
                ],
            },
        }
        source = {"code": "kask", "name": "Mock", "currency": "EUR"}
        rows = parse_kask_rendered(json.dumps(data), source, url, NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].identity.size, rows[0].stock), ("S", "in_stock"))
        self.assertIsNone(rows[0].stock_quantity)  # maxOrderQuantity is never a stock count.
        data["product"]["variationAttributes"][0]["values"][0]["value"] = "62"
        self.assertEqual(parse_kask_rendered(json.dumps(data), source, url, NOW), [])

    def unox_html(self, size="l", max_qty=67):
        variants = [
            {
                "variation_id": 11,
                "attributes": {"attribute_pa_size": size, "attribute_pa_color": "red"},
                "display_price": 199,
                "display_regular_price": 199,
                "is_in_stock": True,
                "is_purchasable": True,
                "variation_is_active": True,
                "variation_is_visible": True,
                "backorders_allowed": False,
                "availability_html": "<p>67 på lager</p>",
                "max_qty": max_qty,
            }
        ]
        product = {
            "@type": "Product",
            "name": "Mock Uno-X T-shirt",
            "brand": "Uno-X",
            "offers": {
                "price": "199",
                "priceCurrency": "NOK",
                "availability": "https://schema.org/InStock",
            },
        }
        return (
            '<link rel="canonical" href="'
            + URL
            + '"><form class="variations_form" data-product_id="10" '
            'data-product_variations="'
            + html_module.escape(json.dumps(variants), quote=True)
            + '">'
            '<input name="product_id" value="10"><select name="attribute_pa_size"><option value="l">L</option></select>'
            '<select name="attribute_pa_color"><option value="red">Red</option></select></form>'
            '<script type="application/ld+json">' + json.dumps(product) + "</script>"
        )

    def test_unox_stock_requires_actual_public_variant_and_numeric_stock_label(self):
        source = {"code": "unox", "name": "Mock", "brand": "Uno-X", "currency": "NOK"}
        rows = parse_unox(self.unox_html(), source, URL, NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].identity.size, rows[0].stock_quantity), ("L", 67))
        self.assertEqual(parse_unox(self.unox_html(size="xl"), source, URL, NOW), [])
        self.assertIsNone(
            parse_unox(self.unox_html(max_qty=999), source, URL, NOW)[0].stock_quantity
        )
        self.assertEqual(parse_unox(self.unox_html(), source | {"currency": "EUR"}, URL, NOW), [])

    def test_official_team_maap_sku_preserves_size_and_actual_market_url(self):
        data = {
            "@type": "Product",
            "name": "Mock Jayco jersey",
            "brand": "MAAP",
            "url": "https://maap.cc/products/mock",
            "offers": [
                {
                    "sku": "MPMJE262726_TDPG_M",
                    "price": "6200.0",
                    "priceCurrency": "TWD",
                    "availability": "https://schema.org/InStock",
                }
            ],
        }
        html = '<script type="application/ld+json">' + json.dumps(data) + "</script>"
        source = {"code": "jayco", "name": "MAAP team", "manufacturer_sku_scheme": "maap"}
        url = "https://maap.cc/tw/products/mock"
        row = parse_jsonld(html, source, url, NOW)[0]
        self.assertEqual((row.source_code, row.identity.size, row.url), ("jayco", "M", url))
        # The same SKU on an unrelated merchant is not manufacturer proof.
        foreign = parse_jsonld(
            html.replace("https://maap.cc/products/mock", URL), source, URL, NOW
        )[0]
        self.assertIsNone(foreign.identity.mpn)

    def test_parent_refresh_replaces_removed_variants_and_marks_failed_parent_retained(self):
        source = {"code": "uae", "name": "Mock"}
        row = parse_pissei(self.pissei_html(), source, URL, NOW)[0]
        first = row.model_copy(
            update={"offer_id": "first", "url": URL + "/sku-M", "collection_url": URL}
        )
        second = row.model_copy(
            update={"offer_id": "second", "url": URL + "/sku-L", "collection_url": URL}
        )
        other = row.model_copy(update={"offer_id": "other", "url": URL + "-other"})
        with tempfile.TemporaryDirectory() as folder:
            repository = OfferRepository(Path(folder))
            atomic_json(Path(folder) / "sources.json", [source])
            repository.save("uae", [first, second, other], NOW, [])
            repository.save("uae", [first], NOW + timedelta(seconds=1), [])
            self.assertEqual({r.offer_id for r in repository.load()}, {"first", "other"})
            repository.save(
                "uae", [other], NOW + timedelta(seconds=2), [{"url": URL, "error": "timeout"}]
            )
            rows = {r.offer_id: r for r in repository.load()}
            self.assertEqual(rows["first"].collection_state, "retained")
            self.assertEqual(rows["other"].collection_state, "current")


if __name__ == "__main__":
    unittest.main(verbosity=2)
