"""Oakley fixtures are minimal excerpts of the public selected-variant contract."""
from __future__ import annotations

import copy
import gzip
import html
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.catalog.models import ProductIdentity
from app.collectors.fetch_policy import CapturedPage
from app.collectors.oakley import (
    PUBLIC_DIAGNOSTICS, collect_oakley_product, oakley_variant_urls, parse_oakley, preserve_oakley_identity,
)
from app.collectors.transport import CollectionError, PublicPageFetcher, SourceDeferred

NOW = datetime(2026, 10, 17, 2, 0, 0, tzinfo=timezone.utc)
URL = "https://www.oakley.com/en-us/product/FOS902243"
SOURCE = {"code": "oakley", "name": "Oakley 美国官方商城", "currency": "USD"}
UPCS = {"S": "8056153857062", "M": "8056153857055", "L": "8056153857048"}


def document(size="L", *, status="Available", price="340.00", full="340.00",
             color="Black/Red Pro", model="VELO MACH MIPS", updates=None):
    upc = UPCS[size]
    sold = status in {"SoldOut", "Out-of-stock"}
    state = "outofstock" if sold else "instock" if status == "Available" else "lowstock"
    product = {"Category": "AFA", "Units": "999", "Price": price, "PriceFull": full,
               "Status": status, "Sku": "FOS902243-BRP", "ModelName": model,
               "Url": URL, "BackOrder": "0", "Preorder": "0"}
    data = {"product_size": [size], "site_currency": "USD", "Order_Currency": "USD",
            "product_name": [model], "product_sku": [product["Sku"]],
            "product_id": [product["Sku"]], "product_state": state,
            "Products": {upc: product}, "Page_Country": "US", "Page_Type": "Pdp"}
    if updates:
        updates(data)
    # The merchant's JS object literal uses an unquoted numeric UPC key.
    script = json.dumps(data, ensure_ascii=False).replace('"' + upc + '": {', upc + ': {')
    controls = []
    for label, variant in UPCS.items():
        selected = label == size
        flags = ' checked' if selected else ''
        disabled = 'true' if sold and selected else 'false'
        controls.append(f'<label data-size="{label}" data-checked="{str(selected).lower()}" '
                        f'aria-checked="{str(selected).lower()}" aria-disabled="{disabled}">'
                        f'<input name="size" value="{label}" data-variant="{variant}"{flags}></label>')
    stock_fields = '' if sold else f'<input name="hiddenAvailability" value="Available"><button data-test="Add_To_Cart_Button" data-isdisabled="false"></button>'
    return f'''<html><head><title>{html.escape(f"Oakley {model} in {color} | Oakley® US")}</title>
    <link rel="canonical" href="{URL}"><meta property="og:image" content="https://assets2.oakley.com/product.png">
    <script>var utag_data={script};</script><script>var ACC={{config:{{}}}};var Oakley={{languageCountry:"en_US"}};</script></head><body>
    <h1 data-test="product-name">{html.escape(model)}</h1>
    <form class="pdhero-form"><input name="selectedColor" value="{html.escape(color, quote=True)}">
    <input name="selectedSize" value="{size}"><input name="productCodePost" value="{'' if sold else upc}">
    {stock_fields}</form>
    <div class="product-attributes"><input name="sku" value="FOS902243-BRP"><input name="articleNumber" value="FOS902243"></div>
    <input id="variantOption" value="{upc}">
    <div class="pdhero-price"><span data-test="sale-price">${price}</span><span content="USD"></span>
    <span data-test="original-price"></span></div>
    <div data-test="colors-box"><div class="selected"><a title="{html.escape(color.lower(), quote=True)}" href="{URL}?variant={upc}"></a></div></div>
    <div data-test="sizes-selection">{''.join(controls)}</div></body></html>'''


def page(body, url=URL, at=NOW):
    return CapturedPage(body.encode(), 200, url, {}, "static", at)


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class OakleyParserTests(unittest.TestCase):
    def parse(self, body=None, url=URL, source=None, at=NOW):
        return parse_oakley(body or document(), source or SOURCE, url, at)

    def test_diagnostic_codes_are_finite_and_never_include_page_contents(self):
        cases = [
            (document().replace('"Page_Country": "US"', '"Page_Country": "PRIVATE_MARKET_SENTINEL"'), "oakley_market_country"),
            (document().replace('"site_currency": "USD"', '"site_currency": "PRIVATE_CURRENCY_SENTINEL"'), "oakley_site_currency"),
            (document().replace('Oakley VELO MACH MIPS in', 'PRIVATE_TITLE_SENTINEL in'), "oakley_page_title"),
            (document().replace('data-isdisabled="false"', 'data-isdisabled="true"'), "oakley_stock_cart"),
            ('<html><p>PRIVATE_BODY_SENTINEL</p></html>', "oakley_canonical_missing"),
        ]
        for body, expected in cases:
            diagnostics = []
            self.assertEqual(parse_oakley(body, SOURCE, URL, NOW, diagnostics=diagnostics), [])
            self.assertEqual(diagnostics[0], expected)
            self.assertLessEqual(len(diagnostics), 3)
            self.assertTrue(set(diagnostics) <= PUBLIC_DIAGNOSTICS)
            self.assertNotIn("PRIVATE", json.dumps(diagnostics))
        diagnostics = []
        self.assertEqual(len(parse_oakley(document(), SOURCE, URL, NOW, diagnostics=diagnostics)), 1)
        self.assertEqual(diagnostics, [])
        self.assertTrue(all(code.startswith("oakley_") and code.replace("_", "").isalnum()
                            and len(code) < 64 for code in PUBLIC_DIAGNOSTICS))

    def test_rejected_canonical_shapes_are_distinguished_without_being_accepted(self):
        cases = [
            ("", "canonical_blank"),
            (URL + "?variant=" + UPCS["L"], "canonical_same_product_selected_upc"),
            (URL + "?variant=" + UPCS["S"], "canonical_same_product_other_upc"),
            (URL + "?private=PRIVATE_QUERY_SENTINEL", "canonical_same_product_other_query"),
            (URL + "/", "canonical_same_product_trailing_slash"),
            (URL + "#PRIVATE_FRAGMENT_SENTINEL", "canonical_same_product_fragment"),
            (URL.replace("https:", "http:"), "canonical_same_product_non_https"),
            (URL.replace("www.oakley.com", "oakley.com"), "canonical_same_product_origin_variant"),
            (URL.replace("www.oakley.com", "www.oakley.com:443"), "canonical_same_product_origin_variant"),
            (URL.replace("https://www.oakley.com", ""), "canonical_relative_same_product"),
            (URL.replace("https:", ""), "canonical_protocol_relative_same_product"),
            (URL.replace("/en-us/", "/en-ca/"), "canonical_other_market"),
            (URL.replace("FOS902243", "FOS902123"), "canonical_other_product"),
            (URL.replace("www.oakley.com", "PRIVATE_HOST_SENTINEL.test"), "canonical_external_origin"),
            ("https://www.oakley.com/en-us", "canonical_other_path"),
            ("https://user:PRIVATE_PASSWORD_SENTINEL@www.oakley.com/en-us/product/FOS902243", "canonical_invalid"),
        ]
        for canonical, expected in cases:
            with self.subTest(shape=expected):
                body = document().replace(f'<link rel="canonical" href="{URL}">',
                                          f'<link rel="canonical" href="{html.escape(canonical, quote=True)}">')
                diagnostics = []
                self.assertEqual(parse_oakley(body, SOURCE, URL, NOW, diagnostics=diagnostics), [])
                self.assertEqual(diagnostics, ["oakley_" + expected, "oakley_canonical_analytics_us", "oakley_canonical_locale_en_us"])
                self.assertTrue(set(diagnostics) <= PUBLIC_DIAGNOSTICS)
                self.assertNotIn("PRIVATE", json.dumps(diagnostics))

    def test_missing_conflicting_and_rel_token_canonical_diagnostics(self):
        original = f'<link rel="canonical" href="{URL}">'
        cases = [
            ("", "canonical_missing_product_layout"),
            (original + '<link rel="canonical" href="https://www.oakley.com/en-ca/product/FOS902243">', "canonical_conflicting"),
            (original.replace('rel="canonical"', 'rel="Canonical"'), "canonical_rel_token_variant"),
            (original.replace('rel="canonical"', 'rel="canonical alternate"'), "canonical_rel_token_variant"),
        ]
        for replacement, code in cases:
            diagnostics = []
            self.assertEqual(parse_oakley(document().replace(original, replacement), SOURCE, URL, NOW,
                                          diagnostics=diagnostics), [])
            self.assertEqual(diagnostics, ["oakley_" + code, "oakley_canonical_analytics_us", "oakley_canonical_locale_en_us"])

    def test_canonical_context_only_reports_finite_market_flags(self):
        body = document().replace(f'<link rel="canonical" href="{URL}">', "")
        body = body.replace('"Page_Country": "US"', '"Page_Country": "PRIVATE_COUNTRY_SENTINEL"')
        body = body.replace('languageCountry:"en_US"', 'languageCountry:"en_CA"')
        diagnostics = []
        self.assertFalse(parse_oakley(body, SOURCE, URL, NOW, diagnostics=diagnostics))
        self.assertEqual(diagnostics, ["oakley_canonical_missing_product_layout",
                                     "oakley_canonical_analytics_other_country", "oakley_canonical_locale_other"])
        self.assertNotIn("PRIVATE", json.dumps(diagnostics))
        result = collect_oakley_product(FakeFetcher({URL: page(body)}), URL, SOURCE)
        self.assertEqual(result.errors[0]["diagnostics"], diagnostics)

    def test_missing_page_shape_is_finite_and_does_not_authorize_hydration(self):
        cases = [
            ("", "response_empty"),
            (gzip.compress(document().encode()).decode("utf-8", errors="replace"), "response_gzip"),
            ('<html><body>PRIVATE_UTF16_SENTINEL</body></html>'.encode("utf-16").decode("utf-8", errors="replace"), "response_utf16"),
            ('{"message":"PRIVATE_JSON_SENTINEL"}', "response_json"),
            (html.escape('<html>PRIVATE_ESCAPED_SENTINEL</html>'), "response_escaped_html"),
            ('PRIVATE_TEXT_SENTINEL', "response_non_html"),
            ('<html><body><p>PRIVATE_BODY_SENTINEL</p></body></html>', "response_html_text"),
            ('<html><script src="/PRIVATE_SCRIPT_SENTINEL"></script></html>', "response_script_shell"),
            ('<html><body></body></html>', "response_html_empty"),
            ('<html><script id="__NEXT_DATA__">{"secret":"PRIVATE_JSON_SENTINEL"}</script></html>', "response_hydration_marker"),
            ('<html><noscript>Please enable JavaScript. PRIVATE_NOSCRIPT_SENTINEL</noscript></html>', "response_javascript_required"),
        ]
        for body, code in cases:
            with self.subTest(shape=code):
                diagnostics = []
                self.assertEqual(parse_oakley(body, SOURCE, URL, NOW, diagnostics=diagnostics), [])
                self.assertEqual(diagnostics[:2], ["oakley_canonical_missing", "oakley_" + code])
                self.assertEqual(len(diagnostics), 3)
                self.assertTrue(set(diagnostics) <= PUBLIC_DIAGNOSTICS)
                self.assertNotIn("PRIVATE", json.dumps(diagnostics))

    def test_explicit_access_restriction_markers_are_closed_and_never_page_text(self):
        cases = [
            ('<title>Access Denied</title><p>PRIVATE_DENIAL_SENTINEL</p>', "access_denied"),
            ('<h1>Sorry, you have been blocked</h1>', "access_denied"),
            ('<title>Just a moment...</title>', "human_verification"),
            ('<h2>Verify you are human</h2>', "human_verification"),
            ('<form id="challenge-form" action="/PRIVATE_ACTION_SENTINEL"></form>', "human_verification"),
            ('<script src="/_sec/cp_challenge/PRIVATE_PATH_SENTINEL"></script>', "human_verification"),
            ('<form action="/captcha/PRIVATE_PATH_SENTINEL"></form>', "captcha_challenge"),
        ]
        for body, code in cases:
            diagnostics = []
            self.assertEqual(parse_oakley('<html>' + body + '</html>', SOURCE, URL, NOW,
                                          diagnostics=diagnostics), [])
            self.assertEqual(diagnostics, ["oakley_" + code, "oakley_response_under_1k_chars"])
            self.assertTrue(set(diagnostics) <= PUBLIC_DIAGNOSTICS)
            self.assertNotIn("PRIVATE", json.dumps(diagnostics))

    def test_normal_product_security_assets_or_newsletter_captcha_are_not_denial(self):
        added = ('<script>var data={message:"Access Denied", cookie:"_abck"};</script>'
                 '<script src="/security/sensor.js"></script><div class="g-recaptcha"></div>'
                 '<h2>Human verification</h2>')
        diagnostics = []
        self.assertEqual(len(parse_oakley(document().replace('</body>', added + '</body>'),
                                         SOURCE, URL, NOW, diagnostics=diagnostics)), 1)
        self.assertEqual(diagnostics, [])

    def test_exact_selected_variant_price_stock_and_observation_time(self):
        row, = self.parse()
        self.assertEqual(row.identity.size, "L")
        self.assertEqual(row.identity.color, "Black/Red Pro")
        self.assertEqual(row.identity.gtin, UPCS["L"])
        self.assertEqual(row.price.amount, Decimal("340.00"))
        self.assertEqual(row.price.currency, "USD")
        self.assertEqual(row.stock, "in_stock")
        self.assertIsNone(row.stock_quantity)  # Analytics Units=999 is not stock.
        self.assertEqual(row.fetched_at, NOW)
        self.assertEqual(row.url, URL)

    def test_low_stock_does_not_invent_quantity(self):
        row, = self.parse(document(status="Available-oneLeft"))
        self.assertEqual(row.stock, "in_stock")
        self.assertIsNone(row.stock_quantity)

    def test_sold_out_needs_selected_disabled_option_and_status(self):
        body = document(status="SoldOut")
        row, = self.parse(body)
        self.assertEqual(row.stock, "out_of_stock")
        self.assertIsNone(row.stock_quantity)
        self.assertEqual(self.parse(body.replace('aria-disabled="true"', 'aria-disabled="false"')), [])
        self.assertEqual(self.parse(document().replace('aria-disabled="false"', 'aria-disabled="true"')), [])

    def test_current_official_out_of_stock_label(self):
        row, = self.parse(document(status="Out-of-stock"))
        self.assertEqual(row.stock, "out_of_stock")
        self.assertIsNone(row.stock_quantity)

    def test_pricefull_is_scoped_to_selected_upc(self):
        row, = self.parse(document(price="152.00", full="190.00"))
        self.assertEqual(row.original_price.amount, Decimal("190.00"))
        mismatched = document(price="152.00", full="190.00").replace(
            '<span data-test="original-price"></span>', '<span data-test="original-price">$200.00</span>')
        self.assertEqual(self.parse(mismatched), [])

    def test_future_or_unknown_status_is_not_in_stock(self):
        row, = self.parse(document(updates=lambda d: d["Products"][UPCS["L"]].update(Preorder="1")))
        self.assertEqual(row.stock, "unknown")
        self.assertTrue(any("预订" in note for note in row.purchase_requirements))
        row, = self.parse(document(status="ComingSoon"))
        self.assertEqual(row.stock, "unknown")

    def test_conflicting_market_currency_price_or_identifiers_are_rejected(self):
        updates = [
            lambda d: d.update(Page_Country="CA"),
            lambda d: d.update(site_currency="CAD"),
            lambda d: d.update(Order_Currency="CAD"),
            lambda d: d.update(product_size=["M"]),
            lambda d: d.update(product_state="outofstock"),
            lambda d: d.update(product_name=["Another helmet"]),
            lambda d: d["Products"][UPCS["L"]].update(Price="339.00"),
            lambda d: d["Products"][UPCS["L"]].update(Url=URL.replace("en-us", "en-ca")),
            lambda d: d["Products"].update({UPCS["S"]: copy.deepcopy(d["Products"][UPCS["L"]])}),
        ]
        for change in updates:
            with self.subTest(change=change):
                self.assertEqual(self.parse(document(updates=change)), [])

    def test_selected_size_color_and_live_button_must_agree(self):
        mutations = [
            ('name="selectedSize" value="L"', 'name="selectedSize" value="M"'),
            ('name="selectedColor" value="Black/Red Pro"', 'name="selectedColor" value="White"'),
            ('aria-checked="true"', 'aria-checked="false"'),
            (' data-variant="8056153857048" checked', ' data-variant="8056153857048"'),
            ('data-isdisabled="false"', 'data-isdisabled="true"'),
            ('id="variantOption" value="8056153857048"', 'id="variantOption" value="8056153857055"'),
            ('name="productCodePost" value="8056153857048"', 'name="productCodePost" value="8056153857055"'),
            ('name="articleNumber" value="FOS902243"', 'name="articleNumber" value="FOS902123"'),
        ]
        for old, new in mutations:
            with self.subTest(old=old):
                self.assertEqual(self.parse(document().replace(old, new)), [])

    def test_does_not_publish_any_unselected_option(self):
        self.assertEqual(len(self.parse()), 1)
        no_selection = document().replace('data-checked="true"', 'data-checked="false"').replace(
            'aria-checked="true"', 'aria-checked="false"').replace(' checked>', '>')
        self.assertEqual(self.parse(no_selection), [])

    def test_exact_us_url_and_requested_upc_are_required(self):
        for url in [URL.replace("en-us", "en-ca"), URL.replace("www.oakley.com", "www.oakley.com.evil.test"),
                    URL.replace("https:", "http:"), URL + "#other", URL + "?foo=1",
                    URL + "?variant=" + UPCS["M"], URL + "?variant=" + UPCS["L"] + "&variant=" + UPCS["M"]]:
            with self.subTest(url=url):
                self.assertEqual(self.parse(url=url), [])
        self.assertEqual(len(self.parse(url=URL + "?variant=" + UPCS["L"])), 1)
        self.assertEqual(self.parse(at=NOW.replace(tzinfo=None)), [])
        self.assertEqual(self.parse(source={**SOURCE, "currency": "CAD"}), [])

    def test_javascript_is_decoded_without_execution(self):
        body = document().replace('"Page_Type": "Pdp"', '"Page_Type": "product", "Page_Type": "Pdp"')
        self.assertEqual(len(self.parse(body)), 1)
        self.assertEqual(self.parse(body.replace('"USD", "Order_Currency"', '"USD", "site_currency": "CAD", "Order_Currency"')), [])
        self.assertEqual(self.parse(body.replace('"Price": "340.00"', '"Price": dangerous()')), [])
        self.assertEqual(self.parse(body.replace(';</script>', ';dangerous();</script>')), [])
        body = document().replace('"Page_Country": "US"', '"breadcrumb_path":"Apparel \\x26 Eyewear", "Page_Country": "US"')
        self.assertEqual(len(self.parse(body)), 1)
        escaped_name = document(model="Giro D'Italia").replace('"ModelName": "Giro D\'Italia"', '"ModelName": "Giro D\\\\\'Italia"')
        self.assertEqual(len(self.parse(escaped_name)), 1)

    def test_scientific_notation_numeric_upc_is_exact_and_never_rounded(self):
        literal = UPCS["L"] + ': {'
        valid = document().replace(literal, '8.056153857048E12: {')
        row, = self.parse(valid)
        self.assertEqual(row.identity.gtin, UPCS["L"])
        for numeric in ['8.0561538570481E12', '8056153857048E999', '8056153857048.5', '1E999999999999999999999999']:
            self.assertEqual(self.parse(document().replace(literal, numeric + ': {')), [])

    def test_missing_color_swatch_on_sold_out_page_uses_exact_title(self):
        body = document(status="SoldOut")
        start = body.index('<div data-test="colors-box">')
        end = body.index('<div data-test="sizes-selection">')
        self.assertEqual(len(self.parse(body[:start] + body[end:])), 1)
        self.assertEqual(self.parse((body[:start] + body[end:]).replace('in Black/Red Pro |', 'in White |')), [])

    def test_only_current_color_size_urls_are_discovered(self):
        body = document() + '<a href="https://evil.test/product?variant=12345678">bad</a>'
        urls = oakley_variant_urls(body, URL)
        self.assertEqual(urls, [URL + "?variant=" + value for value in UPCS.values()])
        self.assertEqual(oakley_variant_urls(body, "https://evil.test/product"), [])


class OakleyIdentityTests(unittest.TestCase):
    def test_manual_identity_is_stable_but_observation_is_new(self):
        fresh, = parse_oakley(document(), SOURCE, URL, NOW)
        old = fresh.model_copy(update={
            "offer_id": "oakley-manual-stable", "family_hint": "old-family",
            "identity": ProductIdentity(brand="Oakley", model="VELO MACH MIPS", size="L", color="Black/Red Pro"),
            "fetched_at": NOW - timedelta(days=1), "stock_quantity": 999,
            "purchase_requirements": ["人工核验快照，尚未启用自动刷新。"],
        })
        row, = preserve_oakley_identity([fresh], [old])
        self.assertEqual(row.offer_id, old.offer_id)
        self.assertEqual(row.identity, old.identity)
        self.assertEqual(row.family_hint, old.family_hint)
        self.assertEqual(row.fetched_at, NOW)
        self.assertIsNone(row.stock_quantity)
        self.assertNotEqual(row.purchase_requirements, old.purchase_requirements)
        self.assertEqual(fresh.identity.gtin, UPCS["L"])  # Input not mutated.

    def test_new_size_keeps_card_family_but_never_siblings_upc(self):
        old, = parse_oakley(document(), SOURCE, URL, NOW)
        old.identity = old.identity.model_copy(update={"mpn": None, "gtin": None})
        new, = parse_oakley(document("S"), SOURCE, URL, NOW)
        row, = preserve_oakley_identity([new], [old])
        self.assertEqual(row.identity.size, "S")
        self.assertEqual(row.identity.gtin, UPCS["S"])
        self.assertIsNone(row.identity.mpn)
        self.assertEqual(row.family_hint, old.family_hint)
        self.assertNotEqual(row.offer_id, old.offer_id)

    def test_expanded_sizes_keep_old_product_route(self):
        from app.catalog.models import FxSnapshot
        from app.catalog.service import ComparisonCatalog
        old, = parse_oakley(document(), SOURCE, URL, NOW)
        old = old.model_copy(update={"offer_id": "oakley-manual-stable", "identity":
            ProductIdentity(brand="Oakley", model="VELO MACH MIPS", size="L", color="Black/Red Pro")})
        current = [parse_oakley(document(size), SOURCE, URL, NOW)[0] for size in UPCS]
        rows = preserve_oakley_identity(current, [old])
        fx = FxSnapshot(snapshot_id="test", rates={"USD": Decimal("7"), "CNY": Decimal("1")})
        before = ComparisonCatalog([old], fx, NOW)
        after = ComparisonCatalog(rows, fx, NOW)
        self.assertEqual(list(before.families), list(after.families))
        self.assertEqual(len(next(iter(after.families.values()))), 3)

    def test_other_color_and_ambiguous_previous_id_do_not_merge(self):
        row, = parse_oakley(document(), SOURCE, URL, NOW)
        old = row.model_copy(update={"offer_id": "manual"})
        other = old.model_copy(update={"identity": old.identity.model_copy(update={"color": "White"})})
        self.assertEqual(preserve_oakley_identity([row], [other])[0].offer_id, row.offer_id)
        self.assertEqual(preserve_oakley_identity([row], [old, old])[0].offer_id, row.offer_id)


class OakleyCollectorTests(unittest.TestCase):
    def responses(self):
        result = {URL: page(document())}
        for index, size in enumerate(["S", "M"]):
            url = URL + "?variant=" + UPCS[size]
            result[url] = page(document(size), url, NOW + timedelta(seconds=index + 1))
        return result

    def test_fetches_each_size_independently_with_its_own_timestamp_and_hash(self):
        fetcher = FakeFetcher(self.responses())
        result = collect_oakley_product(fetcher, URL, SOURCE)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.coverage, {"scope": "selected_color_sizes", "discovered_variants": 3,
                                          "attempted_variants": 3, "validated_variants": 3, "complete": True})
        self.assertEqual([row.identity.size for row in result.offers], ["L", "S", "M"])
        self.assertEqual([row.fetched_at for row in result.offers], [NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)])
        self.assertEqual(len(result.pages), 3)
        for row in result.offers:
            self.assertEqual(row.evidence_sha256, result.pages[row.collection_url].evidence_sha256)
            self.assertEqual(row.fetch_mode, "static")

    def test_explicit_restriction_stops_other_products_on_same_fetcher(self):
        other_url = URL.replace("FOS902243", "FOS902248")
        fetcher = FakeFetcher({URL: page('<html><title>Access Denied</title>PRIVATE_SENTINEL</html>')})
        first = collect_oakley_product(fetcher, URL, SOURCE)
        second = collect_oakley_product(fetcher, other_url, SOURCE)
        self.assertEqual(fetcher.calls, [URL])
        self.assertEqual(first.errors[0]["diagnostics"], ["oakley_access_denied", "oakley_response_under_1k_chars"])
        self.assertEqual(second.errors[0]["diagnostics"], ["oakley_access_denied", "oakley_source_access_stopped"])
        for result in [first, second]:
            self.assertFalse(result.offers)
            self.assertFalse(result.coverage["complete"])
            self.assertTrue(result.coverage["source_stopped"])
            self.assertNotIn("PRIVATE", json.dumps(result.errors))
        self.assertEqual(second.coverage["attempted_variants"], 0)
        # Terminal state belongs only to this fetcher/run, not future sessions.
        fresh = collect_oakley_product(FakeFetcher(self.responses()), URL, SOURCE)
        self.assertTrue(fresh.coverage["complete"])

    def test_challenged_size_stops_remaining_sizes_and_retains_only_verified_page(self):
        responses = self.responses()
        size_url = URL + "?variant=" + UPCS["S"]
        responses[size_url] = page('<html><title>Just a moment...</title></html>', size_url)
        fetcher = FakeFetcher(responses)
        result = collect_oakley_product(fetcher, URL, SOURCE)
        self.assertEqual(fetcher.calls, [URL, size_url])
        self.assertEqual([row.identity.size for row in result.offers], ["L"])
        self.assertFalse(result.coverage["complete"])
        self.assertTrue(result.coverage["source_stopped"])
        self.assertEqual(result.errors[0]["diagnostics"][0], "oakley_human_verification")

    def test_unknown_script_shell_is_not_denial_or_permission_to_retry_in_browser(self):
        body = '<html><script src="/PRIVATE_SCRIPT_SENTINEL"></script></html>'
        other_url = URL.replace("FOS902243", "FOS902248")
        fetcher = FakeFetcher({URL: page(body), other_url: page(body, other_url)})
        for target in [URL, other_url]:
            result = collect_oakley_product(fetcher, target, SOURCE)
            self.assertFalse(result.offers)
            self.assertFalse(result.coverage["complete"])
            self.assertNotIn("source_stopped", result.coverage)
            self.assertEqual(result.errors[0]["diagnostics"], ["oakley_canonical_missing",
                             "oakley_response_script_shell", "oakley_response_under_1k_chars"])
        self.assertEqual(fetcher.calls, [URL, other_url])

    def test_real_transport_explicit_denial_makes_no_other_product_request(self):
        calls = []
        def request(url, **kwargs):
            calls.append(url)
            body = (b"User-agent: *\nAllow: /\n" if url.endswith("/robots.txt") else
                    b'<html><h1>Access Denied</h1><p>PRIVATE_SENTINEL</p></html>')
            return SimpleNamespace(status=200, url=url, headers={}, cookies={}, body=body)
        fetcher = PublicPageFetcher({"www.oakley.com"}, request=request, sleep=lambda _: None)
        first = collect_oakley_product(fetcher, URL, SOURCE)
        second = collect_oakley_product(fetcher, URL.replace("FOS902243", "FOS902248"), SOURCE)
        self.assertEqual(calls, ["https://www.oakley.com/robots.txt", URL])
        self.assertTrue(first.coverage["source_stopped"])
        self.assertTrue(second.coverage["source_stopped"])

    def test_redirect_to_default_variant_cannot_refresh_requested_size(self):
        responses = self.responses()
        responses[URL + "?variant=" + UPCS["S"]] = page(document(), URL, NOW + timedelta(seconds=1))
        result = collect_oakley_product(FakeFetcher(responses), URL, SOURCE)
        self.assertEqual([row.identity.size for row in result.offers], ["L", "M"])
        self.assertFalse(result.coverage["complete"])
        self.assertEqual(len(result.errors), 1)

    def test_market_or_color_redirect_cannot_publish(self):
        responses = self.responses()
        responses[URL + "?variant=" + UPCS["S"]] = page(document("S"), URL.replace("en-us", "en-ca"))
        responses[URL + "?variant=" + UPCS["M"]] = page(document("M", color="White"), URL)
        result = collect_oakley_product(FakeFetcher(responses), URL, SOURCE)
        self.assertEqual(len(result.offers), 1)
        self.assertEqual(len(result.errors), 2)

    def test_changed_default_follows_only_exposed_historical_color(self):
        old, = parse_oakley(document(color="White"), SOURCE, URL, NOW - timedelta(days=1))
        old = old.model_copy(update={"offer_id": "old-white", "identity":
            ProductIdentity(brand="Oakley", model="VELO MACH MIPS", size="L", color="White")})
        known_link = f'<a title="white" href="{URL}?variant={UPCS["L"]}"></a>'
        changed_default = document().replace('<div data-test="colors-box">', '<div data-test="colors-box">' + known_link)
        responses = {URL: page(changed_default)}
        for index, size in enumerate(UPCS):
            target = URL + "?variant=" + UPCS[size]
            responses[target] = page(document(size, color="White"), target, NOW + timedelta(seconds=index + 1))
        fetcher = FakeFetcher(responses)
        result = collect_oakley_product(fetcher, URL, SOURCE, [old])
        self.assertEqual(result.errors, [])
        self.assertTrue(result.coverage["complete"])
        self.assertEqual(result.coverage["color_selection_pages"], 1)
        self.assertEqual(result.coverage["discovered_variants"], 3)
        self.assertEqual(result.coverage["attempted_variants"], 3)
        self.assertEqual(len(fetcher.calls), 4)
        self.assertEqual(fetcher.calls[1], URL + "?variant=" + UPCS["L"])
        self.assertEqual({row.identity.color for row in result.offers}, {"White"})
        self.assertIn("old-white", {row.offer_id for row in result.offers})

    def test_changed_default_without_exact_official_link_remains_unrefreshed(self):
        old, = parse_oakley(document(color="White"), SOURCE, URL, NOW - timedelta(days=1))
        fetcher = FakeFetcher({URL: page(document())})
        result = collect_oakley_product(fetcher, URL, SOURCE, [old])
        self.assertFalse(result.offers)
        self.assertFalse(result.coverage["complete"])
        self.assertIn("no exact exposed", result.errors[0]["error"])
        self.assertEqual(fetcher.calls, [URL])

    def test_variant_limit_is_explicit_and_keeps_partial_evidence(self):
        fetcher = FakeFetcher(self.responses())
        result = collect_oakley_product(fetcher, URL, SOURCE, max_variants=2)
        self.assertEqual(len(fetcher.calls), 2)
        self.assertEqual(len(result.offers), 2)
        self.assertFalse(result.coverage["complete"])
        self.assertIn("limit", result.errors[0]["error"])
        for limit in [0, 21, True]:
            with self.assertRaises(ValueError):
                collect_oakley_product(fetcher, URL, SOURCE, max_variants=limit)

    def test_denial_and_deferred_retry_stop_further_requests(self):
        for error in [CollectionError("robots.txt forbids this product URL"), SourceDeferred("limited", NOW + timedelta(minutes=10))]:
            responses = self.responses()
            responses[URL + "?variant=" + UPCS["S"]] = error
            fetcher = FakeFetcher(responses)
            result = collect_oakley_product(fetcher, URL, SOURCE)
            self.assertEqual(len(fetcher.calls), 2)
            self.assertEqual(len(result.offers), 1)
            self.assertFalse(result.coverage["complete"])
            if isinstance(error, SourceDeferred):
                self.assertEqual(result.errors[0]["retry_at"], error.retry_at.isoformat())

    def test_real_transport_enforces_robots_without_product_request(self):
        calls = []
        def request(url, **kwargs):
            calls.append(url)
            return SimpleNamespace(status=200, url=url, headers={}, cookies={},
                                   body=b"User-agent: *\nDisallow: /en-us/product/\n")
        fetcher = PublicPageFetcher({"www.oakley.com"}, request=request, sleep=lambda _: None)
        result = collect_oakley_product(fetcher, URL, SOURCE)
        self.assertEqual(calls, ["https://www.oakley.com/robots.txt"])
        self.assertFalse(result.offers)
        self.assertIn("robots", result.errors[0]["error"])

    def test_malformed_exposed_size_is_not_silent_complete_coverage(self):
        body = document().replace('data-variant="8056153857062"', 'data-variant="not-a-upc"')
        self.assertEqual(oakley_variant_urls(body, URL), [])
        result = collect_oakley_product(FakeFetcher({URL: page(body)}), URL, SOURCE)
        self.assertFalse(result.coverage["complete"])
        self.assertTrue(result.errors)

    def test_collector_exports_only_allowlisted_parse_diagnostic(self):
        body = document().replace('"site_currency": "USD"', '"site_currency": "PRIVATE_CURRENCY_SENTINEL"')
        result = collect_oakley_product(FakeFetcher({URL: page(body)}), URL, SOURCE)
        self.assertEqual(result.errors[0]["diagnostics"], ["oakley_site_currency"])
        self.assertTrue(set(result.errors[0]["diagnostics"]) <= PUBLIC_DIAGNOSTICS)
        self.assertNotIn("PRIVATE", json.dumps(result.errors))
        self.assertFalse(result.offers)

    def test_base_failure_does_not_load_previous_snapshot_as_new(self):
        old, = parse_oakley(document(), SOURCE, URL, NOW - timedelta(days=1))
        result = collect_oakley_product(FakeFetcher({URL: page('<html>blocked</html>')}), URL, SOURCE, [old])
        self.assertFalse(result.offers)
        self.assertFalse(result.coverage["complete"])
        self.assertEqual(old.fetched_at, NOW - timedelta(days=1))


if __name__ == "__main__":
    unittest.main()
