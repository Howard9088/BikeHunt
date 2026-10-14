"""Offline regression fixtures for the EF shop's observed WooCommerce format."""
from __future__ import annotations

import copy
import html
import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from app.collectors.woocommerce import parse_woocommerce


NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)
URL = "https://efprocycling.shop/us/product/stamp-hoodie/"
SOURCE = {"code": "ef_team_shop", "name": "EF 车队官方商城美国站",
          "base_url": "https://efprocycling.shop/us", "brand": "EF Pro Cycling",
          "currency": "USD", "sales_region": "美国"}


def variation(variation_id=50113, size="s", **updates):
    result = {"attributes": {"attribute_pa_size": size, "attribute_pa_color": "black"},
              "display_price": 89, "display_regular_price": 89,
              "image": {"url": "https://efprocycling.shop/us/wp-content/uploads/hoodie.avif"},
              "is_in_stock": True, "is_purchasable": True,
              "variation_is_active": True, "variation_is_visible": True,
              "backorders_allowed": False, "sku": "ASC-5161-Stamp Hoodie-Black-" + size.upper(),
              "variation_id": variation_id}
    result.update(updates)
    return result


def page(variants=None, currency="USD", store_currency="USD", product_id="50111",
         name="Stamp Hoodie", canonical=URL, action=URL, analytics_id=50111,
         analytics_name="Stamp Hoodie", store_url="https://efprocycling.shop/us"):
    if variants is None:
        variants = [variation(), variation(50114, "m", is_in_stock=False)]
    props = {"store_currency": store_currency, "url": store_url}
    events = [{"eventName": "product_view", "props": {
        "pi": analytics_id, "pn": analytics_name, "pp": 89, "pt": "variable"}}]
    return ('<link rel="canonical" href="' + html.escape(canonical, quote=True) + '">'
            '<h1 class="product_title entry-title">' + html.escape(name) + '</h1>'
            '<span class="yay-currency-selected-option">' + currency + '</span>'
            '<script>wcAnalytics.commonProps = ' + json.dumps(props) + ';'
            'wcAnalytics.eventQueue = ' + json.dumps(events) + ';</script>'
            '<form class="variations_form cart" action="' + html.escape(action, quote=True)
            + '" data-product_id="' + product_id + '" data-product_variations="'
            + html.escape(json.dumps(variants), quote=True) + '">'
            '<select name="attribute_pa_size"><option value="">Choose an option</option>'
            '<option value="s">S</option><option value="m">M</option></select>'
            '<select name="attribute_pa_color"><option value="">Choose an option</option>'
            '<option value="black">Black</option></select>'
            '<input name="product_id" value="' + product_id + '">'
            '<input name="add-to-cart" value="' + product_id + '"></form>'
            '<script type="application/ld+json">{"@type":"BreadcrumbList"}</script>')


class WooCommerceTests(unittest.TestCase):
    def parse(self, body=None, source=None, url=URL):
        return parse_woocommerce(page() if body is None else body,
                                 SOURCE if source is None else source, url, NOW)

    def test_explicit_variants_and_provenance_without_product_jsonld(self):
        offers = self.parse()
        self.assertEqual(len(offers), 2)
        self.assertEqual([offer.identity.size for offer in offers], ["S", "M"])
        self.assertEqual([offer.stock for offer in offers], ["in_stock", "out_of_stock"])
        self.assertEqual(offers[0].price.amount, Decimal("89"))
        self.assertEqual(offers[0].price.currency, "USD")
        self.assertEqual(offers[0].identity.color, "Black")
        self.assertEqual(offers[0].identity.brand, "EF Pro Cycling")
        self.assertIsNone(offers[0].identity.mpn)  # A merchant SKU is not a manufacturer MPN.
        self.assertIsNone(offers[0].identity.gtin)
        self.assertIsNone(offers[0].original_price)
        self.assertEqual(offers[0].url, URL)
        self.assertEqual(offers[0].fetched_at, NOW)
        self.assertEqual(offers[0].family_hint, "50111")
        self.assertIn("50113", offers[0].identity_evidence)
        self.assertEqual(offers[0].shipping_to_china.status, "unknown")
        self.assertEqual(offers[0].china_issued_card.status, "unknown")
        self.assertIsNone(offers[0].shipping)
        self.assertIsNone(offers[0].tax)
        self.assertNotEqual(offers[0].offer_id, offers[1].offer_id)
        self.assertEqual(offers[0].offer_id, self.parse()[0].offer_id)

    def test_independent_prices_and_only_a_real_discount(self):
        offers = self.parse(page([variation(display_price=75, display_regular_price=89),
                                  variation(50114, "m", display_price=90, display_regular_price=80)]))
        self.assertEqual([o.price.amount for o in offers], [Decimal("75"), Decimal("90")])
        self.assertEqual(offers[0].original_price.amount, Decimal("89"))
        self.assertIsNone(offers[1].original_price)

    def test_visible_options_are_not_invented_variants(self):
        offers = self.parse(page([variation()]))
        self.assertEqual([o.identity.size for o in offers], ["S"])

    def test_missing_and_non_boolean_stock_flags_stay_unknown(self):
        for key in ("is_in_stock", "is_purchasable", "variation_is_active",
                    "variation_is_visible", "backorders_allowed"):
            for missing in (True, False):
                with self.subTest(key=key, missing=missing):
                    item = variation()
                    if missing:
                        item.pop(key)
                    else:
                        item[key] = "true" if key != "backorders_allowed" else "false"
                    self.assertEqual(self.parse(page([item]))[0].stock, "unknown")

    def test_not_purchasable_is_not_invented_out_of_stock(self):
        offer = self.parse(page([variation(is_purchasable=False)]))[0]
        self.assertEqual(offer.stock, "unknown")
        self.assertTrue(offer.purchase_requirements)

    def test_backorders_are_not_claimed_as_on_hand_stock(self):
        offer = self.parse(page([variation(backorders_allowed=True)]))[0]
        self.assertEqual(offer.stock, "unknown")
        self.assertTrue(offer.purchase_requirements)

    def test_hidden_or_inactive_variants_are_not_current_offers(self):
        for key in ("variation_is_active", "variation_is_visible"):
            with self.subTest(key=key):
                self.assertEqual(self.parse(page([variation(**{key: False})])), [])

    def test_no_default_currency_or_dollar_symbol_inference(self):
        for body in (page(currency=""), page(currency="$"),
                     page().replace('class="yay-currency-selected-option"', 'class="unused"')):
            self.assertEqual(self.parse(body), [])

    def test_currency_conflicts_are_rejected(self):
        for body in (page(currency="EUR"), page(store_currency="CAD"),
                     page() + '<span class="yay-currency-selected-option">CAD</span>'):
            self.assertEqual(self.parse(body), [])
        self.assertEqual(self.parse(source={**SOURCE, "currency": "GBP"}), [])

    def test_currency_is_read_from_page_not_hardcoded_usd(self):
        source = {**SOURCE, "currency": "EUR"}
        self.assertEqual(self.parse(page(currency="EUR", store_currency="EUR"), source)[0].price.currency, "EUR")
        source.pop("currency")
        self.assertEqual(self.parse(page(currency="EUR", store_currency="EUR"), source)[0].price.currency, "EUR")

    def test_store_currency_or_product_analytics_must_be_present(self):
        for variable in ("commonProps", "eventQueue"):
            with self.subTest(variable=variable):
                self.assertEqual(self.parse(page().replace("wcAnalytics." + variable, "unrelated." + variable)), [])

    def test_actual_product_and_store_urls_must_match(self):
        for kwargs in ({"canonical": URL.replace("stamp-hoodie", "wrong")},
                       {"action": URL.replace("stamp-hoodie", "wrong")},
                       {"canonical": URL.replace("efprocycling.shop", "evil.example")},
                       {"store_url": "https://efprocycling.shop/uk"},
                       {"action": URL + "?add-to-cart=50111"}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.parse(page(**kwargs)), [])
        self.assertEqual(self.parse(url=URL.replace("efprocycling.shop", "evil.example")), [])
        self.assertEqual(self.parse(url=URL.replace("https:", "http:")), [])
        self.assertEqual(self.parse(source={**SOURCE, "base_url": "https://elsewhere.example"}), [])

    def test_product_identity_is_bound_to_form_and_analytics(self):
        for kwargs in ({"analytics_id": 20}, {"analytics_id": "50111"},
                       {"analytics_name": "Another product"}, {"product_id": "0"}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.parse(page(**kwargs)), [])
        self.assertEqual(self.parse(page().replace('name="product_id" value="50111"',
                                                   'name="product_id" value="50112"')), [])
        self.assertEqual(self.parse(page().replace('name="add-to-cart"', 'name="missing"')), [])

    def test_missing_or_ambiguous_page_identity_rejected(self):
        self.assertEqual(self.parse(page().replace('rel="canonical"', 'rel="other"')), [])
        self.assertEqual(self.parse(page() + '<h1 class="product_title">Other</h1>'), [])
        self.assertEqual(self.parse(page() + '<link rel="canonical" href="' + URL + '">'), [])
        self.assertEqual(self.parse(source={**SOURCE, "brand": ""}), [])

    def test_attributes_must_be_complete_and_real_visible_options(self):
        invalid = [None, [], {}, {"attribute_pa_size": "s"},
                   {"attribute_pa_size": "", "attribute_pa_color": "black"},
                   {"attribute_pa_size": "xl", "attribute_pa_color": "black"},
                   {"attribute_pa_size": "s", "attribute_pa_color": "pink"},
                   {"attribute_pa_size": ["s"], "attribute_pa_color": "black"},
                   {"attribute_pa_size": "s", "attribute_pa_color": "black", "attribute_material": "cotton"}]
        for attributes in invalid:
            with self.subTest(attributes=attributes):
                self.assertEqual(self.parse(page([variation(attributes=attributes)])), [])

    def test_id_and_duplicate_options_are_validated(self):
        for ident in (None, True, "50113", 0, -1):
            with self.subTest(ident=ident):
                self.assertEqual(self.parse(page([variation(ident)])), [])
        self.assertEqual(self.parse(page([variation(), variation(50113, "m")])), [])
        self.assertEqual(self.parse(page([variation(), variation(50114, "s")])), [])

    def test_invalid_or_free_price_rejected_without_parent_price_fallback(self):
        for price in (None, True, "NaN", "Infinity", -1, 0, "$89", ""):
            with self.subTest(price=price):
                self.assertEqual(self.parse(page([variation(display_price=price)])), [])

    def test_invalid_variation_payload_is_rejected(self):
        for variants in ([], None, False, {}, [None], [True]):
            body = page([variation()])
            encoded = html.escape(json.dumps([variation()]), quote=True)
            body = body.replace(encoded, html.escape(json.dumps(variants), quote=True))
            self.assertEqual(self.parse(body), [])

    def test_corrupt_json_is_not_executed(self):
        body = page().replace('data-product_variations="', 'data-product_variations="not_json;')
        self.assertEqual(self.parse(body), [])

    def test_unsafe_image_is_dropped(self):
        for image in ({"url": "javascript:alert(1)"}, {"url": "http://example.com/a.jpg"}, None):
            with self.subTest(image=image):
                self.assertIsNone(self.parse(page([variation(image=image)]))[0].image)

    def test_input_data_is_not_mutated(self):
        source = copy.deepcopy(SOURCE)
        self.parse(source=source)
        self.assertEqual(source, SOURCE)


if __name__ == "__main__":
    unittest.main()
