"""Independent synthetic variant regressions: python -X utf8 tests/test_remaining.py."""

from __future__ import annotations

import copy
import json
import sys
import unittest
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.collectors.remaining import (
    parse_redbull_product,
    parse_topfanz,
    parse_canyon_product,
    parse_colnago_product,
)
from test_saved_team_catalogs import pack
from app.catalog.storage import OfferRepository, atomic_json
from app.promotion import safe_https

NOW = datetime.now(timezone.utc)
RED_URL = "https://www.redbullshop.com/en-jp/p/Mock-Jersey/M-RBB26001/"
TOP_URL = "https://shops.topfanz.com/en/mock-socks.html"
SOURCE = {"code": "redbull", "name": "Mock official", "currency": "JPY"}


def red_html(edit=None, base_key=True):
    price = {"currencyIso": "JPY", "value": 12000}
    variant = {
        "code": "M-RBB26001001",
        "priceData": price,
        "stock": {"stockLevel": 8, "isValueRounded": False, "statusInfo": "inStock"},
        "variantOptionQualifiers": [{"qualifier": "size", "name": "Mock Jersey", "value": "M"}],
    }
    selected = copy.deepcopy(variant)
    selected["variantOptionQualifiers"].append(
        {"qualifier": "color", "value": "T801", "colorNameEN": "Black"}
    )
    other = copy.deepcopy(variant)
    other.update(
        code="M-RBB26001002",
        stock={"stockLevel": 0, "isValueRounded": False, "statusInfo": "outOfStock"},
    )
    other["variantOptionQualifiers"][0]["value"] = "L"
    product = {
        "code": variant["code"],
        "baseProduct": "M-RBB26001",
        "name": "Mock Jersey",
        "absoluteProductUrl": RED_URL + "?preselectedVariant=" + variant["code"],
        "price": price,
        "trackingData": {"id": variant["code"]},
        "ean": "4006381333931",
        "preorder": False,
        "purchasable": True,
        "hasRestrictedVariants": False,
        "baseOptions": [{"selected": selected, "sizeOptions": [variant, other]}],
    }
    ld = {
        "@type": "Product",
        "name": product["name"],
        "sku": product["code"],
        "offers": {"url": product["absoluteProductUrl"], "price": "12000", "priceCurrency": "JPY"},
    }
    if edit:
        edit(product, ld)
    key = "product:" + (product["baseProduct"] if base_key else product["code"]) + ":anonymous"
    cache = pack([[key, {"key": key, "data": {"response": product}}]])
    return (
        '<script id="state-body">window.__INITIAL_DATA_CACHE__ = '
        + json.dumps({"data": cache})
        + '</script><script type="application/ld+json">'
        + json.dumps(ld)
        + "</script>"
    )


def top_html(edit=None):
    ld = {
        "@type": "Product",
        "name": "Mock Socks",
        "brand": "Mock",
        "gtin13": "4006381333931",
        "color": "White",
        "offers": {
            "price": "26.41",
            "priceCurrency": "EUR",
            "url": TOP_URL,
            "availability": "https://schema.org/InStock",
            "inventoryLevel": "3",
        },
    }
    if edit:
        edit(ld)
    return (
        f'<link rel="canonical" href="{TOP_URL}"><div id="productpage"><div class="product-info">'
        '<span class="price-new">€31,95</span></div></div>'
        '<form id="product_configure_form" action="https://shops.topfanz.com/en/cart/add/123456/">'
        '<select name="option[123]"><option value="9" selected>S</option></select>'
        '<button class="add-cart">Add</button></form>'
        '<script type="application/ld+json">' + json.dumps(ld) + "</script>"
    )


class RemainingTests(unittest.TestCase):
    def test_canyon_capacity_variants_bind_query_sku_and_market(self):
        url = "https://www.canyon.com/en-us/gear/accessories/bags/mock/9102039.html"
        target = url + "?dwvar_9102039_pv_volumen=1.90%20l"
        group = {
            "@type": "ProductGroup",
            "url": url,
            "name": "Canyon Mock Bag",
            "brand": {"name": "Canyon"},
            "productGroupID": "9102039",
            "hasVariant": [
                {
                    "@type": "Product",
                    "name": "Canyon Mock Bag",
                    "sku": "10011121",
                    "url": target,
                    "additionalProperty": [{"name": "Volume", "value": "1,90 l"}],
                    "offers": {
                        "url": target,
                        "price": "48.95",
                        "priceCurrency": "USD",
                        "availability": "https://schema.org/InStock",
                    },
                }
            ],
        }

        def html():
            return '<script type="application/ld+json">' + json.dumps(group) + "</script>"

        source = {"code": "canyon", "name": "Canyon", "brand": "Canyon"}
        row = parse_canyon_product(html(), source, url, NOW)[0]
        self.assertEqual(row.identity.size, "容量 1,90 l")
        self.assertEqual(row.stock, "in_stock")
        self.assertIsNone(row.stock_quantity)
        group["hasVariant"][0]["additionalProperty"][0]["value"] = "2,30 l"
        self.assertEqual(parse_canyon_product(html(), source, url, NOW), [])

    def test_colnago_case_sensitive_official_size_urls_and_missing_sku(self):
        url = "https://www.colnago.com/en-us/products/mock-jersey"
        product = {
            "@type": "Product",
            "url": url,
            "name": "Mock Jersey",
            "brand": {"name": "Colnago"},
            "offers": [
                {
                    "sku": "000059670",
                    "url": url + "?Size=XS",
                    "price": 207,
                    "priceCurrency": "USD",
                    "availability": "https://schema.org/InStock",
                },
                {
                    "sku": "000059671",
                    "url": url + "?Size=S",
                    "price": 207,
                    "priceCurrency": "USD",
                    "availability": "https://schema.org/OutOfStock",
                },
            ],
        }

        def html():
            return '<script type="application/ld+json">' + json.dumps(product) + "</script>"

        source = {"code": "colnago", "name": "Colnago"}
        rows = parse_colnago_product(html(), source, url, NOW)
        self.assertEqual(
            [(r.identity.size, r.stock) for r in rows], [("XS", "in_stock"), ("S", "out_of_stock")]
        )
        product["offers"][0]["url"] = url + "?size=XS"
        self.assertEqual(len(parse_colnago_product(html(), source, url, NOW)), 2)
        product["offers"][1].pop("sku")
        self.assertEqual(parse_colnago_product(html(), source, url, NOW), [])

    def test_legacy_category_quote_is_replaced_only_by_its_exact_product_refresh(self):
        row = parse_redbull_product(red_html(), SOURCE, RED_URL, NOW)[0]
        category = "https://www.redbullshop.com/en-jp/c/redbullborahansgrohe/"
        old = row.model_copy(
            update={"offer_id": "old-reference", "stock": "unknown", "collection_url": category}
        )
        other = row.model_copy(
            update={
                "offer_id": "unrelated",
                "url": RED_URL.replace("26001", "26002"),
                "collection_url": category,
            }
        )
        with tempfile.TemporaryDirectory() as folder:
            repo = OfferRepository(Path(folder) / "data")
            atomic_json(repo.data_dir / "sources.json", [SOURCE])
            repo.save("redbull", [old, other], NOW, [])
            repo.save("redbull", [row.model_copy(update={"collection_url": RED_URL})], NOW, [])
            self.assertEqual({r.offer_id for r in repo.load()}, {row.offer_id, "unrelated"})

    def test_promotion_variant_links_are_strictly_host_scoped(self):
        self.assertTrue(safe_https(TOP_URL + "?id=123456", product=True))
        self.assertFalse(safe_https("https://shop.example/product?id=123456", product=True))
        self.assertFalse(safe_https(TOP_URL + "?id=https://example.com", product=True))
        self.assertTrue(safe_https(RED_URL + "?preselectedVariant=M-RBB26001001", product=True))
        self.assertFalse(
            safe_https(
                "https://shop.example/product?preselectedVariant=M-RBB26001001", product=True
            )
        )

    def test_redbull_base_and_variant_cache_keys_bind_exact_sizes(self):
        for key in (True, False):
            rows = parse_redbull_product(red_html(base_key=key), SOURCE, RED_URL, NOW)
            self.assertEqual(
                [(r.identity.size, r.stock_quantity, r.stock) for r in rows],
                [("M", 8, "in_stock"), ("L", 0, "out_of_stock")],
            )
            self.assertEqual(rows[0].identity.gtin, "4006381333931")
            self.assertIsNone(rows[1].identity.gtin)
            self.assertTrue(rows[1].url.endswith("preselectedVariant=M-RBB26001002"))

    def test_redbull_mismatched_market_sku_and_structured_price_rejected(self):
        edits = [
            lambda p, ld: ld.update(sku="OTHER"),
            lambda p, ld: ld["offers"].update(price="1"),
            lambda p, ld: p.update(absoluteProductUrl=RED_URL.replace("en-jp", "en-us")),
            lambda p, ld: p["trackingData"].update(id="OTHER"),
        ]
        for edit in edits:
            with self.subTest(edit=edit):
                self.assertEqual(parse_redbull_product(red_html(edit), SOURCE, RED_URL, NOW), [])
        self.assertEqual(
            parse_redbull_product(red_html(), SOURCE, RED_URL + "?preselectedVariant=OTHER", NOW),
            [],
        )

    def test_redbull_preorder_and_rounded_counts_never_become_current_stock(self):
        for edit in [
            lambda p, ld: p.update(preorder=True),
            lambda p, ld: p["baseOptions"][0]["sizeOptions"][0]["stock"].update(
                isValueRounded=True
            ),
        ]:
            row = parse_redbull_product(red_html(edit), SOURCE, RED_URL, NOW)[0]
            self.assertEqual(row.stock, "unknown")
            self.assertIsNone(row.stock_quantity)

    def test_topfanz_gross_price_not_a_fake_discount(self):
        row = parse_topfanz(top_html(), {"code": "alpecin", "name": "Mock"}, TOP_URL, NOW)[0]
        self.assertEqual(str(row.price.amount), "31.95")
        self.assertIsNone(row.original_price)
        self.assertEqual(row.identity.size, "S")
        self.assertEqual(row.stock_quantity, 3)
        self.assertEqual(row.url, TOP_URL + "?id=123456")
        # The shop's size-specific merchandise code is not a shared model number.
        other = parse_topfanz(
            top_html(lambda ld: ld.update(mpn="SHOP-S")),
            {"code": "alpecin", "name": "Mock"},
            TOP_URL,
            NOW,
        )[0]
        self.assertIsNone(other.identity.mpn)

    def test_topfanz_conflicts_and_foreign_forms_rejected(self):
        for html in [
            top_html(lambda ld: ld["offers"].update(inventoryLevel="-1")),
            top_html(lambda ld: ld["offers"].update(inventoryLevel="0")),
            top_html(lambda ld: ld.pop("gtin13")),
            top_html().replace("/en/cart/add/123456/", "/en/checkout/"),
            top_html().replace('class="add-cart"', 'class="add-cart" disabled'),
        ]:
            self.assertEqual(
                parse_topfanz(html, {"code": "alpecin", "name": "Mock"}, TOP_URL, NOW), []
            )


if __name__ == "__main__":
    unittest.main()
