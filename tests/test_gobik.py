"""Offline exact-variant, history and permitted-transport Gobik contracts."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.collectors.gobik import (collect_gobik_catalog, parse_gobik,
                                  preserve_gobik_identity, GobikCollectionError,
                                  PUBLIC_DIAGNOSTICS, fetch_gobik_product,
                                  _spain_localization_form)
from app.collectors.transport import CollectionError, PublicPageFetcher, SourceDeferred
from app.catalog.models import FxSnapshot
from app.catalog.service import ComparisonCatalog
from app.catalog.listings import bootstrap_legacy, family_records, prepare_listing_history
from app.catalog.storage import OfferRepository, atomic_json

NOW = datetime(2026, 10, 17, 2, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=1)
URL = "https://gobik.com/en/products/long-sleeve-jersey-hyder-men-hammock"
SOURCE = {"code": "gobik", "name": "Gobik 官方商城", "brand": "Gobik"}


def variants():
    return [{"id": 100 + i, "title": size, "option1": size,
             "option2": None, "option3": None, "public_title": size,
             "options": [size], "sku": "10-01-080-075-" + size,
             "price": 12000 + i * 100, "compare_at_price": 15000,
             "available": i == 0, "barcode": None}
            for i, size in enumerate(["S", "M"])]


def product(rows=None):
    rows = rows or variants()
    return {"@type": "Product", "url": URL,
            "name": "LONG SLEEVE JERSEY HYDER MEN HAMMOCK", "brand": {"name": "GOBIK"},
            "image": ["https://gobik.com/cdn/shop/files/hammock.jpg"],
            "offers": [{"@type": "Offer", "url": URL + "?variant=" + str(v["id"]),
                        "sku": v["sku"], "price": v["price"] / 100,
                        "priceCurrency": "EUR", "availability": "https://schema.org/" +
                        ("InStock" if v["available"] else "OutOfStock")} for v in rows]}


def page(rows=None, structured=None, color="Hammock", label="Choose the size"):
    rows = rows or variants()
    structured = structured or product(rows)
    path = URL.removeprefix("https://gobik.com")
    radios = "".join(f'<input type="radio" name="{label}" value="{v["option1"]}" '
                     + ('checked ' if i == 0 else '')
                     + ('class="disabled" ' if v["available"] is False else '') + '>'
                     for i, v in enumerate(rows))
    color_picker = (f'<variant-radios class="product-variant-picker__container" data-url="{path}">'
                    '<label class="form__label">Color</label><div>'
                    f'<fieldset class="current-pick"><legend>{color}</legend>'
                    f'<a href="{path}"><div id="10"></div></a></fieldset></div>') if color else ''
    return ('<script>Shopify.currency = {"active":"EUR"}; Shopify.country = "ES";</script>'
            f'<link rel="canonical" href="{URL}">'
            f'<div class="product__info-container" data-url="{path}">'
            '<input name="product-id" value="10">' + color_picker +
            f'<variant-radios class="size-variant-picker" data-url="{path}">'
            f'<fieldset><legend>{label}</legend>{radios}</fieldset>'
            '<script type="application/json">' + json.dumps(rows) + '</script></variant-radios>'
            + ('</variant-radios>' if color else '') +
            '<input id="quantity-stock_inventory" value="100" data-value="100" product-id="10">'
            '<div id="quantity_stock"><span>2 In stock</span></div></div>'
            '<script type="application/ld+json">' + json.dumps(structured) + '</script>')


def old_row():
    row = parse_gobik(page(), SOURCE, URL, OLD)[0]
    identity = row.identity.model_copy(update={"model": "JERSEY Hyder MEN Hammock", "color": None})
    return row.model_copy(update={"offer_id": "gobik-manual-stable", "identity": identity,
        "name": identity.model, "url": URL, "family_hint": URL,
        "stock_quantity": 9, "purchase_requirements": ["manual only; no auto refresh"]})


def localization_form():
    return ('<form action="/en/localization" method="post" enctype="multipart/form-data">'
        '<input type="hidden" name="form_type" value="localization">'
        '<input type="hidden" name="utf8" value="✓">'
        '<input type="hidden" name="_method" value="put">'
        f'<input type="hidden" name="return_to" value="{URL.removeprefix("https://gobik.com")}">'
        '<input type="hidden" name="country_code" value="US">'
        '<a data-value="ES">EUR € | Spain</a></form>')


class GobikLocalizationTests(unittest.TestCase):
    def fetcher(self, *, initial='US', final='ES', form=None, currency='EUR', post_status=302, fail_post=False):
        calls = []; clock = iter([NOW, NOW + timedelta(seconds=2), NOW + timedelta(seconds=4), NOW + timedelta(seconds=6)])
        def get(url, **kwargs):
            calls.append(('GET', url))
            if url.endswith('/robots.txt'):
                return SimpleNamespace(status=200, body=b'User-agent: *\nAllow: /', headers={}, url=url)
            country = final if kwargs.get('cookies', {}).get('localization') == 'server-session' else initial
            html = page().replace('"ES"', json.dumps(country)).replace('"active":"EUR"', '"active":' + json.dumps(currency))
            html += localization_form() if form is None else form
            return SimpleNamespace(status=200, body=html.encode(), headers={}, url=url)
        def post(url, **kwargs):
            calls.append(('POST', url))
            if fail_post:
                raise OSError('uncertain submission')
            return SimpleNamespace(status=post_status, body=b'', headers={'Location':URL, 'Retry-After':'3600'},
                                   cookies={'localization':'server-session'}, url=url)
        fetcher = PublicPageFetcher({'gobik.com'}, request=get, post_request=post,
                                    sleep=lambda _: None, utcnow=lambda:next(clock))
        return fetcher, calls

    def test_official_spain_form_once_and_only_after_explicit_country_mismatch(self):
        fetcher, calls = self.fetcher()
        capture = fetch_gobik_product(fetcher, URL)
        self.assertEqual(capture.observed_at, NOW + timedelta(seconds=2))
        self.assertEqual(len(parse_gobik(capture.body.decode(), SOURCE, URL, capture.observed_at)), 2)
        fetch_gobik_product(fetcher, URL)
        self.assertEqual(calls.count(('POST','https://gobik.com/en/localization')), 1)
        self.assertEqual(calls.count(('GET',URL)), 3)

    def test_already_spain_requires_no_form_post(self):
        fetcher, calls = self.fetcher(initial='ES', form='')
        fetch_gobik_product(fetcher, URL)
        self.assertFalse(any(method == 'POST' for method, _ in calls))

    def test_missing_or_wrong_official_form_fails_without_post_and_is_remembered(self):
        for form in ['', localization_form().replace('Spain', 'France'),
                     localization_form().replace('/en/localization', 'https://other.example/localization'),
                     localization_form().replace('name="return_to"', 'name="unexpected"'),
                     localization_form().replace('value="put"', 'value="delete"')]:
            fetcher, calls = self.fetcher(form=form)
            with self.assertRaises(GobikCollectionError) as raised:
                fetch_gobik_product(fetcher, URL)
            self.assertEqual(raised.exception.diagnostics, ['gobik_localization_form_unverified'])
            count = len(calls)
            with self.assertRaises(GobikCollectionError):
                fetch_gobik_product(fetcher, URL)
            self.assertEqual(len(calls), count)
            self.assertFalse(any(method == 'POST' for method, _ in calls))

    def test_changed_currency_is_not_relabelled_or_localized(self):
        fetcher, calls = self.fetcher(currency='USD')
        with self.assertRaises(GobikCollectionError) as raised:
            fetch_gobik_product(fetcher, URL)
        self.assertEqual(raised.exception.diagnostics, ['gobik_market_currency_mismatch'])
        self.assertFalse(any(method == 'POST' for method, _ in calls))

    def test_selection_must_really_return_spain_and_never_retries_failed_post(self):
        for kwargs in [{'final':'US'}, {'fail_post':True}, {'post_status':403}]:
            fetcher, calls = self.fetcher(**kwargs)
            with self.assertRaises(CollectionError):
                fetch_gobik_product(fetcher, URL)
            count = len(calls)
            with self.assertRaises(CollectionError):
                fetch_gobik_product(fetcher, URL)
            self.assertEqual(len(calls), count)
            self.assertEqual(calls.count(('POST','https://gobik.com/en/localization')), 1)

    def test_rate_limit_remains_source_deferred_and_does_not_repeat_form(self):
        fetcher, calls = self.fetcher(post_status=429)
        with self.assertRaises(SourceDeferred):
            fetch_gobik_product(fetcher, URL)
        count = len(calls)
        with self.assertRaises(SourceDeferred):
            fetch_gobik_product(fetcher, URL)
        self.assertEqual(len(calls), count)

    def test_duplicate_identical_visible_forms_are_safe_but_extra_fields_are_not(self):
        action, fields = _spain_localization_form(localization_form() * 2, URL)
        self.assertEqual(action, 'https://gobik.com/en/localization')
        self.assertEqual(fields['country_code'], 'ES')
        with self.assertRaises(GobikCollectionError):
            _spain_localization_form(localization_form().replace('</form>',
                '<input type="hidden" name="token" value="never-submit"></form>'), URL)

    def test_cookie_loss_after_success_is_not_a_second_localization_attempt(self):
        fetcher, calls = self.fetcher()
        fetch_gobik_product(fetcher, URL)
        fetcher.public_cookies.clear()
        with self.assertRaises(GobikCollectionError) as raised:
            fetch_gobik_product(fetcher, URL)
        self.assertEqual(raised.exception.diagnostics, ['gobik_localization_not_persistent'])
        self.assertEqual(calls.count(('POST','https://gobik.com/en/localization')), 1)


class GobikParserTests(unittest.TestCase):
    def test_public_diagnostics_are_finite_and_do_not_repeat_external_text(self):
        self.assertIsInstance(PUBLIC_DIAGNOSTICS, frozenset)
        arbitrary = 'untrusted page token=do-not-log https://private.example/value'
        error = GobikCollectionError(arbitrary)
        self.assertEqual(error.diagnostics, ['gobik_validation_failed'])
        self.assertTrue(set(error.diagnostics) <= PUBLIC_DIAGNOSTICS)
        self.assertNotIn(arbitrary, json.dumps(error.diagnostics))

    def test_market_diagnostics_distinguish_wrong_currency_country_and_missing_evidence(self):
        cases = [
            (page().replace('"ES"', '"US"'), 'gobik_market_country_mismatch'),
            (page().replace('"active":"EUR"', '"active":"USD"'), 'gobik_market_currency_mismatch'),
            (page().replace('Shopify.country = "ES";', ''), 'gobik_market_country_unverified'),
            (page().replace('Shopify.currency = {"active":"EUR"};', ''), 'gobik_market_currency_unverified'),
            (page() + '<script>Shopify.country="US";</script>', 'gobik_market_country_unverified'),
        ]
        for html, expected in cases:
            with self.subTest(expected=expected), self.assertRaises(GobikCollectionError) as raised:
                parse_gobik(html, SOURCE, URL, NOW)
            self.assertEqual(raised.exception.diagnostics, [expected])
            self.assertIn(expected, PUBLIC_DIAGNOSTICS)

    def test_schema_and_reconciliation_diagnostics_are_classified(self):
        with self.assertRaises(GobikCollectionError) as raised:
            parse_gobik(page().replace('class="size-variant-picker"', 'class="other"'), SOURCE, URL, NOW)
        self.assertEqual(raised.exception.diagnostics, ['gobik_size_picker_unverified'])
        prior = old_row(); prior.identity = prior.identity.model_copy(update={'model':'Other'})
        with self.assertRaises(GobikCollectionError) as raised:
            preserve_gobik_identity(parse_gobik(page(), SOURCE, URL, NOW), [prior])
        self.assertEqual(raised.exception.diagnostics, ['gobik_reconciliation_unverified'])

    def test_price_and_stock_are_exact_per_size_and_color(self):
        rows = parse_gobik(page(), SOURCE, URL, NOW)
        self.assertEqual([str(x.price.amount) for x in rows], ["120.0", "121.0"])
        self.assertEqual([x.stock for x in rows], ["in_stock", "out_of_stock"])
        self.assertEqual([x.identity.size for x in rows], ["S", "M"])
        self.assertTrue(all(x.identity.color == "Hammock" for x in rows))
        self.assertTrue(all(x.identity.gender == "male" and x.identity.mpn is None for x in rows))
        self.assertEqual([x.stock_quantity for x in rows], [2, None])
        self.assertTrue(all(x.fetched_at == NOW and x.sales_region == "西班牙站 EUR 报价" for x in rows))
        self.assertTrue(rows[0].url.endswith("?variant=100"))

    def test_alternative_explicit_size_label_is_supported(self):
        self.assertEqual(len(parse_gobik(page(label="Choose your size"), SOURCE, URL, NOW)), 2)

    def test_missing_color_is_not_guessed_from_title_or_image(self):
        self.assertIsNone(parse_gobik(page(color=None), SOURCE, URL, NOW)[0].identity.color)

    def test_size_picker_json_not_unrelated_product_or_script(self):
        unrelated = page().replace('class="size-variant-picker"', 'class="unrelated"')
        with self.assertRaises(CollectionError):
            parse_gobik(unrelated, SOURCE, URL, NOW)

    def test_active_country_and_currency_must_both_match(self):
        for html in (page().replace('"ES"', '"US"'), page().replace('"active":"EUR"', '"active":"USD"'),
                     page().replace('Shopify.country = "ES";', ''),
                     page() + '<script>Shopify.country="US";</script>'):
            with self.subTest(html=html[:80]), self.assertRaises(CollectionError):
                parse_gobik(html, SOURCE, URL, NOW)

    def test_invalid_source_url_canonical_or_observation_time(self):
        for url in (URL.replace('gobik.com', 'other.example'), URL + '?variant=100&variant=101',
                    URL + '?variant=100&market=US', URL.replace('https:', 'http:')):
            with self.subTest(url=url), self.assertRaises(CollectionError):
                parse_gobik(page(), SOURCE, url, NOW)
        with self.assertRaises(CollectionError):
            parse_gobik(page().replace(f'href="{URL}"', 'href="https://gobik.com/en/products/other"'), SOURCE, URL, NOW)
        with self.assertRaises(CollectionError):
            parse_gobik(page(), SOURCE, URL, NOW.replace(tzinfo=None))

    def test_variant_id_sku_price_currency_and_duplicates_fail_closed(self):
        mutations = [lambda p: p['offers'][0].update(price=119),
                     lambda p: p['offers'][0].update(priceCurrency='USD'),
                     lambda p: p['offers'][0].update(sku='different'),
                     lambda p: p['offers'][0].update(url=URL + '?variant=999'),
                     lambda p: p['offers'][1].update(url=URL + '?variant=100'),
                     lambda p: p['offers'][0].update(url=URL.replace('hammock', 'cortex') + '?variant=100')]
        for change in mutations:
            p = product(); change(p)
            with self.subTest(p=p), self.assertRaises(CollectionError):
                parse_gobik(page(structured=p), SOURCE, URL, NOW)

    def test_multiple_option_dimensions_and_repeated_sizes_fail_closed(self):
        for change in [lambda vs: vs[0].update(option2='Other color'),
                       lambda vs: vs[0].update(price=True),
                       lambda vs: vs[0].update(title='M'),
                       lambda vs: vs[0].update(options=['M'])]:
            vs = variants(); change(vs)
            with self.assertRaises(CollectionError):
                parse_gobik(page(rows=vs), SOURCE, URL, NOW)

    def test_stock_conflict_is_unknown_not_published_in_stock(self):
        p = product(); p['offers'][0]['availability'] = 'https://schema.org/OutOfStock'
        row = parse_gobik(page(structured=p), SOURCE, URL, NOW)[0]
        self.assertEqual(row.stock, 'unknown'); self.assertIsNone(row.stock_quantity)
        row = parse_gobik(page().replace('checked >', 'checked class="disabled">'), SOURCE, URL, NOW)[0]
        self.assertEqual(row.stock, 'unknown')

    def test_color_selection_must_match_current_exact_product(self):
        for before, after in [('id="10"></div>', 'id="11"></div>'),
                              (f'<a href="{URL.removeprefix("https://gobik.com")}">', '<a href="/en/products/other">')]:
            with self.assertRaises(CollectionError):
                parse_gobik(page().replace(before, after), SOURCE, URL, NOW)

    def test_quantity_only_when_selected_id_size_and_product_agree(self):
        for before, after in [('data-value="100"', 'data-value="101"'),
                              ('product-id="10"', 'product-id="11"'),
                              ('value="100" data-value="100"', 'value="101" data-value="101"'),
                              ('2 In stock', 'Low stock')]:
            rows = parse_gobik(page().replace(before, after), SOURCE, URL, NOW)
            self.assertTrue(all(x.stock_quantity is None for x in rows))

    def test_exact_gtin_checked_and_sku_never_becomes_manufacturer_id(self):
        vs = variants(); vs[0]['barcode'] = '8434738206502'
        p = product(vs); p['offers'][0]['gtin13'] = 8434738206502
        row = parse_gobik(page(vs, p), SOURCE, URL, NOW)[0]
        self.assertEqual(row.identity.gtin, '8434738206502'); self.assertIsNone(row.identity.mpn)
        p['offers'][0]['gtin13'] = 8434738206496
        with self.assertRaises(CollectionError):
            parse_gobik(page(vs, p), SOURCE, URL, NOW)


class GobikHistoryTests(unittest.TestCase):
    def test_full_size_expansion_keeps_exact_card_and_first_listing_identity(self):
        prior = old_row()
        rows = preserve_gobik_identity(parse_gobik(page(), SOURCE, URL, NOW), [prior])
        fx = FxSnapshot(snapshot_id='test-fx', rates={'EUR':Decimal('1'), 'CNY':Decimal('7.8')})
        previous = ComparisonCatalog([prior], fx, NOW)
        expanded = ComparisonCatalog(rows, fx, NOW)
        self.assertEqual(set(previous.families), set(expanded.families))
        self.assertEqual(previous._variant_id([prior]), expanded._variant_id([rows[0]]))
        before, after = family_records(previous), family_records(expanded)
        self.assertEqual(before, after)
        ledger = bootstrap_legacy(before)
        family_id = before[0]['product_id']
        first_listed = OLD.isoformat()
        ledger['entries'][family_id].update(state='confirmed', first_listed_at=first_listed,
            receipt={'snapshot_sha256':'1'*64, 'commit':'2'*40, 'verified_at':first_listed})
        prepared = prepare_listing_history(ledger, after)
        self.assertEqual(prepared['entries'][family_id]['first_listed_at'], first_listed)
        self.assertEqual(prepared['entries'][family_id]['state'], 'confirmed')
        self.assertEqual(len(expanded.families[family_id]), 2)

    def test_preserves_old_variant_and_new_sibling_family_without_old_observations(self):
        prior = old_row()
        rows = preserve_gobik_identity(parse_gobik(page(), SOURCE, URL, NOW), [prior])
        self.assertEqual(rows[0].offer_id, prior.offer_id)
        self.assertEqual(rows[0].identity, prior.identity)
        self.assertNotEqual(rows[1].offer_id, prior.offer_id)
        for row in rows:
            for field in ('brand', 'model', 'color', 'year', 'gender'):
                self.assertEqual(getattr(row.identity, field), getattr(prior.identity, field))
            self.assertEqual(row.family_hint, prior.family_hint)
            self.assertEqual(row.fetched_at, NOW)
            self.assertNotIn('manual only; no auto refresh', row.purchase_requirements)
        self.assertEqual(rows[0].stock_quantity, 2)
        self.assertEqual(rows[1].identity.size, 'M')
        self.assertIn('Hammock', rows[0].identity_evidence)

    def test_explicit_new_sold_out_overrides_manual_in_stock(self):
        prior = old_row(); vs = variants(); vs[0]['available'] = False
        fresh = parse_gobik(page(vs), SOURCE, URL, NOW)
        current = preserve_gobik_identity(fresh, [prior])[0]
        self.assertEqual(current.stock, 'out_of_stock')
        self.assertIsNone(current.stock_quantity)
        self.assertEqual(current.fetched_at, NOW)

    def test_ambiguous_legacy_sizes_or_families_fail_closed(self):
        prior = old_row(); fresh = parse_gobik(page(), SOURCE, URL, NOW)
        for old in [[prior, prior.model_copy(update={'offer_id': 'another'})],
                    [prior, prior.model_copy(update={'identity': prior.identity.model_copy(update={'size':'L', 'model':'Other'})})]]:
            with self.assertRaises(CollectionError):
                preserve_gobik_identity(fresh, old)

    def test_changed_model_market_gender_or_known_color_is_not_merged(self):
        for field, value in [('model', 'JERSEY Other MEN Hammock'), ('gender', 'female'), ('color', 'Cortex')]:
            prior = old_row(); prior.identity = prior.identity.model_copy(update={field: value})
            with self.assertRaises(CollectionError):
                preserve_gobik_identity(parse_gobik(page(), SOURCE, URL, NOW), [prior])

    def test_other_product_size_cannot_supply_old_identity(self):
        prior = old_row().model_copy(update={'url': URL.replace('hammock', 'cortex')})
        rows = preserve_gobik_identity(parse_gobik(page(), SOURCE, URL, NOW), [prior])
        self.assertNotEqual(rows[0].offer_id, prior.offer_id)
        self.assertEqual(rows[0].identity.color, 'Hammock')

    def test_legacy_null_gtin_is_preserved_for_existing_variant_only(self):
        vs = variants(); vs[0]['barcode'] = '8434738206502'
        p = product(vs); p['offers'][0]['gtin13'] = 8434738206502
        rows = preserve_gobik_identity(parse_gobik(page(vs, p), SOURCE, URL, NOW), [old_row()])
        self.assertIsNone(rows[0].identity.gtin)


class GobikCollectionTests(unittest.TestCase):
    def fetcher(self, *, robots=b'User-agent: *\nAllow: /', status=200, headers=None, final_url=None, html=None):
        calls = []
        def request(url, **kwargs):
            calls.append(url)
            if url.endswith('/robots.txt'):
                return SimpleNamespace(status=200, body=robots, headers={}, url=url)
            return SimpleNamespace(status=status, body=(page() if html is None else html).encode(), headers=headers or {}, url=final_url or url)
        return PublicPageFetcher({'gobik.com'}, request=request, sleep=lambda _: None, utcnow=lambda: NOW), calls

    def test_live_transport_timestamp_hash_and_scope(self):
        fetcher, calls = self.fetcher()
        result = collect_gobik_catalog(fetcher, {'urls':[URL]}, SOURCE, OLD, existing_offers=[old_row()])
        self.assertFalse(result.errors); self.assertEqual(len(result.offers), 2)
        self.assertEqual(calls, ['https://gobik.com/robots.txt', URL])
        self.assertTrue(result.coverage['configured_scope_complete'])
        self.assertFalse(result.coverage['catalog_complete'])
        for row in result.offers:
            self.assertEqual(row.fetched_at, NOW)
            self.assertEqual(row.fetch_mode, 'static')
            self.assertEqual(row.evidence_sha256, hashlib.sha256(page().encode()).hexdigest())

    def test_robots_denial_stops_before_product(self):
        fetcher, calls = self.fetcher(robots=b'User-agent: *\nDisallow: /en/products/')
        result = collect_gobik_catalog(fetcher, {'urls':[URL]}, SOURCE, NOW)
        self.assertFalse(result.offers); self.assertEqual(len(result.errors), 1)
        self.assertEqual(calls, ['https://gobik.com/robots.txt'])

    def test_failed_market_parse_retains_prior_snapshot_and_original_timestamp(self):
        prior = old_row()
        fetcher, calls = self.fetcher(html=page().replace('"ES"', '"US"'))
        result = collect_gobik_catalog(fetcher, {'urls':[URL]}, SOURCE, NOW, existing_offers=[prior])
        self.assertFalse(result.offers); self.assertTrue(result.errors)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = root / 'offers' / 'gobik.json'
            atomic_json(root / 'sources.json', [SOURCE])
            atomic_json(snapshot, {'source_code':'gobik', 'collected_at':OLD.isoformat(),
                                   'offers':[prior.model_dump(mode='json')]})
            before = snapshot.read_bytes()
            repository = OfferRepository(root)
            repository.save('gobik', result.offers, NOW, result.errors, result.coverage)
            self.assertEqual(snapshot.read_bytes(), before)
            retained = repository.load()[0]
            self.assertEqual(retained.collection_state, 'retained')
            self.assertEqual(retained.fetched_at, OLD)
            self.assertEqual(retained.offer_id, prior.offer_id)
            self.assertEqual(retained.stock_quantity, prior.stock_quantity)

    def test_429_defers_remaining_urls_without_further_request(self):
        fetcher, calls = self.fetcher(status=429, headers={'Retry-After':'3600'})
        result = collect_gobik_catalog(fetcher, {'urls':[URL, URL.replace('hammock','cortex')]}, SOURCE, NOW)
        self.assertFalse(result.offers); self.assertEqual(len(result.errors), 2)
        self.assertTrue(all('retry_at' in row for row in result.errors))
        self.assertEqual(calls, ['https://gobik.com/robots.txt', URL])

    def test_redirect_different_product_or_market_is_rejected(self):
        fetcher, calls = self.fetcher(final_url=URL.replace('/en/', '/en-us/'))
        result = collect_gobik_catalog(fetcher, {'urls':[URL]}, SOURCE, NOW)
        self.assertFalse(result.offers); self.assertEqual(len(result.errors), 1)

    def test_invalid_or_oversized_scope_is_rejected_before_network(self):
        for settings in [{'urls':[]}, {'urls':[URL, URL]}, {'urls':[URL], 'max_products':True},
                         {'urls':[URL + '?variant=100']}, {'urls':[URL.replace('gobik.com','other.example')]}]:
            fetcher, calls = self.fetcher()
            result = collect_gobik_catalog(fetcher, settings, SOURCE, NOW)
            self.assertFalse(result.offers); self.assertTrue(result.errors); self.assertFalse(calls)


if __name__ == '__main__':
    unittest.main()
