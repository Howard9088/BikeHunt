"""Offline contracts for localized, bounded Shopify collection ingestion."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.collectors.shopify import collect_shopify_catalog, parse_shopify_product, shopify_market_currency, shopify_market_country
from app.collectors.transport import CollectionError, PublicPageFetcher
from app.source_rules import apply_source_rules

NOW = datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc)
SOURCE = {"code": "team", "name": "Official team store", "type": "team_official"}
CATALOG = "https://shop.example/en/collections/team-kit"
URL = "https://shop.example/en/products/jersey"
SETTINGS = {"catalog_url": CATALOG, "max_products": 25}
MARKET = '<script>Shopify.currency = {"active":"EUR","rate":"1.0"};</script>'


def product():
    return {"id": 10, "title": "Team jersey", "handle": "jersey", "vendor": "Real kit maker",
        "options": [{"name": "Size", "position": 1, "values": ["S", "M"]}],
        "images": [{"src": "https://cdn.example/jersey.png"}],
        "variants": [{"id": 100 + i, "product_id": 10, "option1": size,
            "price": "99.95", "compare_at_price": "125.00", "available": i == 0,
            "sku": "merchant-only-" + size} for i, size in enumerate(["S", "M"])]}


def page(p=None, currency="EUR", price="99.95", gtin=None):
    p = p or product()
    data = {"@type": "ProductGroup", "name": p["title"], "brand": p["vendor"], "hasVariant": []}
    for v in p["variants"]:
        item = {"@type": "Product", "name": p["title"] + " - " + str(v.get("option1")),
            "sku": v.get("sku"), "offers": {"@type": "Offer", "price": price,
            "priceCurrency": currency, "url": URL + "?variant=" + str(v["id"]),
            "availability": "https://schema.org/" + ("InStock" if v.get("available") is True else "OutOfStock")}}
        if gtin:
            item["gtin"] = gtin
        data["hasVariant"].append(item)
    return MARKET.replace('"EUR"', '"' + currency + '"') + '<script type="application/ld+json">' + json.dumps(data) + '</script>'


def fetcher_for(p=None, product_status=200, robots=b"User-agent: *\nAllow: /", headers=None):
    p = p or product(); calls = []
    def request(url, **kwargs):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return SimpleNamespace(status=200, body=robots, headers={})
        if url == CATALOG:
            return SimpleNamespace(status=200, body=MARKET.encode(), headers={})
        if "/collections/team-kit/products.json?limit=25&page=1" in url:
            return SimpleNamespace(status=200, body=json.dumps({"products": [p]}).encode(), headers={})
        if url == URL:
            return SimpleNamespace(status=product_status, body=page(p).encode(), headers=headers or {})
        raise AssertionError("Unexpected request: " + url)
    return PublicPageFetcher({"shop.example"}, request=request, sleep=lambda _: None, utcnow=lambda: NOW), calls


class ShopifyTests(unittest.TestCase):
    def test_paused_product_url_is_never_requested(self):
        fetcher,calls=fetcher_for()
        result=collect_shopify_catalog(fetcher,{**SETTINGS,"excluded_urls":[URL]},SOURCE,NOW)
        self.assertEqual(result.offers,[])
        self.assertNotIn(URL,calls)
        self.assertIn("paused",result.errors[0]["error"])


    def test_market_label_uses_observed_country_and_currency(self):
        html = page(currency="USD") + '<script>Shopify.country = "US";</script>'
        rows = parse_shopify_product(product(), html, {**SOURCE, "sales_region":"欧洲站 EUR 报价"}, URL, NOW)
        self.assertEqual(rows[0].price.currency, "USD")
        self.assertIn("US 市场 · USD", rows[0].sales_region)
        self.assertNotIn("EUR", rows[0].sales_region)
        effective = apply_source_rules(rows[0], {**SOURCE, "sales_region":"欧洲站 EUR 报价"}, Path("/tmp/unused-market-test"))
        self.assertEqual(effective.sales_region, rows[0].sales_region)
        self.assertIn("US 市场 · USD", effective.sales_region)

    def test_missing_market_country_is_not_inferred(self):
        rows = parse_shopify_product(product(), page(), {**SOURCE, "sales_region":"欧洲站"}, URL, NOW)
        self.assertIn("地区未核实", rows[0].sales_region)
        self.assertIsNone(shopify_market_country(""))
        with self.assertRaises(CollectionError):
            shopify_market_country('<script>Shopify.country="US";Shopify.country="FR";</script>')


    def test_exact_sizes_prices_stock_and_unverified_policies(self):
        rows = parse_shopify_product(product(), page(), SOURCE, URL, NOW, "EUR")
        self.assertEqual([r.identity.size for r in rows], ["S", "M"])
        self.assertEqual([r.stock for r in rows], ["in_stock", "out_of_stock"])
        self.assertEqual(str(rows[0].price.amount), "99.95")
        self.assertEqual(rows[0].price.currency, "EUR")
        self.assertEqual(rows[0].identity.brand, "Real kit maker")
        self.assertIsNone(rows[0].identity.mpn)
        self.assertIsNone(rows[0].identity.gtin)
        self.assertIsNone(rows[0].shipping)
        self.assertEqual(rows[0].shipping_to_china.status, "unknown")
        self.assertEqual(rows[0].china_issued_card.status, "unknown")
        self.assertTrue(rows[0].url.endswith("?variant=100"))

    def test_does_not_guess_currency_from_symbol_or_source_default(self):
        with self.assertRaises(CollectionError):
            shopify_market_currency('<p>$99.95</p>')
        with self.assertRaises(CollectionError):
            shopify_market_currency(MARKET + MARKET.replace("EUR", "USD"))

    def test_localized_feed_price_must_match_variant_page(self):
        with self.assertRaises(CollectionError):
            parse_shopify_product(product(), page(currency="USD"), SOURCE, URL, NOW, "EUR")
        with self.assertRaises(CollectionError):
            parse_shopify_product(product(), page(price="119.95"), SOURCE, URL, NOW, "EUR")
        with self.assertRaises(CollectionError):
            parse_shopify_product(product(), page().replace("?variant=100", "?variant=999"), SOURCE, URL, NOW)

    def test_valid_gtin_is_retained_invalid_gtin_is_not_invented(self):
        rows = parse_shopify_product(product(), page(gtin="8053845469305"), SOURCE, URL, NOW)
        self.assertEqual(rows[0].identity.gtin, "8053845469305")
        rows = parse_shopify_product(product(), page(gtin="1234567890123"), SOURCE, URL, NOW)
        self.assertIsNone(rows[0].identity.gtin)

    def test_feed_stock_conflict_is_unknown_and_strings_are_not_booleans(self):
        p = product(); html = page(p); p["variants"][0]["available"] = False
        self.assertEqual(parse_shopify_product(p, html, SOURCE, URL, NOW)[0].stock, "unknown")
        p["variants"][0]["available"] = "true"
        self.assertEqual(parse_shopify_product(p, html, SOURCE, URL, NOW)[0].stock, "unknown")

    def test_default_variant_and_localized_size_names(self):
        for label in ("taglia", "Taille", "Maat", "Accessoiregrootte", "3XL"):
            p = product(); p["options"][0]["name"] = label
            rows = parse_shopify_product(p, page(p), SOURCE, URL, NOW)
            self.assertEqual([r.identity.size for r in rows], ["S", "M"])
        p = product(); p["options"] = [{"name": "Title", "values": ["Default Title"]}]
        p["variants"] = [p["variants"][0]]; p["variants"][0]["option1"] = "Default Title"
        self.assertIsNone(parse_shopify_product(p, page(p), SOURCE, URL, NOW)[0].identity.size)

    def test_bundle_option_combinations_are_preserved(self):
        p = product(); p["options"] = [{"name": "Jersey (Size)", "position": 1, "values": ["S", "M"]},
            {"name": "Bib shorts (Size)", "position": 2, "values": ["L", "XL"]}]
        p["variants"][0]["option2"] = "L"; p["variants"][1]["option2"] = "XL"
        rows = parse_shopify_product(p, page(p), SOURCE, URL, NOW)
        self.assertEqual(rows[0].identity.size, "Jersey (Size): S / Bib shorts (Size): L")

    def test_missing_duplicate_or_foreign_variant_rejected(self):
        p = product(); p["variants"][0]["product_id"] = 99
        with self.assertRaises(CollectionError):
            parse_shopify_product(p, page(p), SOURCE, URL, NOW)
        p = product(); p["variants"].append(copy.deepcopy(p["variants"][0]))
        with self.assertRaises(CollectionError):
            parse_shopify_product(p, page(p), SOURCE, URL, NOW)

    def test_compare_at_must_be_higher_and_same_validated_currency(self):
        p = product(); p["variants"][0]["compare_at_price"] = "0.00"
        p["variants"][1]["compare_at_price"] = "99.95"
        self.assertTrue(all(r.original_price is None for r in parse_shopify_product(p, page(p), SOURCE, URL, NOW)))

    def test_catalog_is_scoped_bounded_and_saved_raw(self):
        fetcher, calls = fetcher_for()
        with tempfile.TemporaryDirectory() as d:
            r = collect_shopify_catalog(fetcher, SETTINGS, SOURCE, NOW, Path(d))
            self.assertEqual(len(list(Path(d).iterdir())), 3)
        self.assertEqual(len(r.offers), 2); self.assertEqual(r.errors, [])
        self.assertEqual(r.coverage["scope"], "collection")
        self.assertTrue(r.coverage["complete"])
        self.assertEqual(r.coverage["collected_product_count"], 1)
        self.assertFalse(any(url.startswith("https://shop.example/products.json") for url in calls))

    def test_robots_denial_and_cooldown_are_not_bypassed(self):
        fetcher, calls = fetcher_for(robots=b"User-agent: *\nDisallow: /en/collections/")
        r = collect_shopify_catalog(fetcher, SETTINGS, SOURCE, NOW)
        self.assertEqual(r.offers, []); self.assertEqual(len(calls), 1)
        fetcher, calls = fetcher_for(product_status=429, headers={"Retry-After": "600"})
        r = collect_shopify_catalog(fetcher, SETTINGS, SOURCE, NOW)
        self.assertEqual(r.offers, []); self.assertEqual(calls.count(URL), 1)
        self.assertIn("retry_at", r.errors[0])
        self.assertIn("shop.example", fetcher.deferred)

    def test_full_first_page_is_explicitly_partial_and_has_no_page_two(self):
        products = []
        for i in range(25):
            p = product(); p["id"] += i; p["handle"] += "-" + str(i)
            for v in p["variants"]:
                v["id"] += i * 2; v["product_id"] = p["id"]
            products.append(p)
        calls = []
        class Bounded:
            def fetch(self, url):
                calls.append(url)
                if url == CATALOG:
                    body = MARKET
                elif "products.json" in url:
                    body = json.dumps({"products": products})
                else:
                    p = next(p for p in products if url.endswith("/" + p["handle"]))
                    body = page(p).replace(URL + "?", url + "?")
                return SimpleNamespace(status=200, body=body.encode())
        result = collect_shopify_catalog(Bounded(), SETTINGS, SOURCE, NOW)
        self.assertEqual(len(result.offers), 50)
        self.assertEqual(result.coverage["collected_product_count"], 25)
        self.assertTrue(result.coverage["partial"])
        self.assertFalse(result.coverage["complete"])
        self.assertEqual(len(calls), 27)
        self.assertFalse(any("page=2" in url for url in calls))

    def test_server_ignoring_limit_does_not_expand_scope(self):
        calls = []
        class Unbounded:
            def fetch(self, url):
                calls.append(url)
                body = MARKET if url == CATALOG else json.dumps({"products": [product()] * 26})
                return SimpleNamespace(status=200, body=body.encode())
        result = collect_shopify_catalog(Unbounded(), SETTINGS, SOURCE, NOW)
        self.assertEqual(result.offers, [])
        self.assertIn("ignored", result.errors[0]["error"])
        self.assertEqual(len(calls), 2)

    def test_redirected_source_is_not_published(self):
        class Redirected:
            def fetch(self, url):
                return SimpleNamespace(status=200, body=MARKET.encode(), url="https://other.example/")
        r = collect_shopify_catalog(Redirected(), SETTINGS, SOURCE, NOW)
        self.assertEqual(r.offers, [])
        self.assertIn("redirected", r.errors[0]["error"])

    def test_limit_and_unsafe_urls_fail_without_requests(self):
        fetcher, calls = fetcher_for()
        for settings in ({"catalog_url": CATALOG, "max_products": 26},
                         {"catalog_url": "https://shop.example/collections/team-kit/other"},
                         {"catalog_url": CATALOG + "?filter=team"}):
            self.assertEqual(collect_shopify_catalog(fetcher, settings, SOURCE, NOW).offers, [])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
