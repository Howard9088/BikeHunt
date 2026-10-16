"""Reduced factual fixtures and fail-closed mutation tests; no network calls.

Full captured pages are deliberately kept outside the repository and package.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from tempfile import TemporaryDirectory

from scrapling.parser import Selector

from app.collectors.parsers import parse_jsonld
from app.collectors.saved_team_catalogs import (
    PREORDER, REDBULL_KEY, REDBULL_PAGE, SIZE_UNKNOWN,
    _decode_cache, _redbull_search, parse_lotto, parse_redbull_catalog,
)

FIXTURES = Path(__file__).parent / 'fixtures' / 'saved_teams'
LOTTO_HTML = (FIXTURES / 'lotto-beanie.html').read_text()
RED_HTML = (FIXTURES / 'redbull-jp-category.html').read_text()
MOV_HTML = (FIXTURES / 'movistar-landing.html').read_text()
LOTTO_URL = 'https://www.lotto-intermarche.be/nl/shop/product/250/beanie'
LOTTO_TIME = datetime(2026, 10, 14, 17, 31, 22, 737440, tzinfo=timezone.utc)
RED_TIME = datetime(2026, 10, 14, 17, 30, 24, 136679, tzinfo=timezone.utc)
LOTTO = {'code': 'lotto', 'name': 'Lotto-Intermarché 官方商城', 'brand': 'Lotto-Intermarché',
         'currency': 'EUR', 'sales_region': '比利时站 EUR 报价'}
RED = {'code': 'redbull', 'name': 'Red Bull 官方商城', 'brand': 'Red Bull',
       'currency': 'JPY', 'sales_region': '日本市场 JPY 报价'}


def pack(data):
    """Test-only encoder of the already decoded observed reference format."""
    atoms = []

    def ref(number):
        alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
        if number < 0:
            return '-' + ref(-number)
        result = ''
        while number:
            number, remainder = divmod(number, 62)
            result = alphabet[remainder] + result
        return result or '0'

    def add(value):
        if value is None:
            return ''
        if isinstance(value, dict):
            literal = 'o|' + add(list(value)) + ''.join('|' + add(v) for v in value.values())
        elif isinstance(value, list):
            literal = 'a|' + '|'.join(add(v) for v in value)
        elif isinstance(value, bool):
            literal = 'b|T' if value else 'b|F'
        elif isinstance(value, int):
            literal = 'n|' + ref(value)
        else:
            assert isinstance(value, str)
            literal = value
        atoms.append(literal)
        return ref(len(atoms) - 1)

    root = add(data)
    return [atoms, root]


def red_page(*, state_edit=None, ld_edit=None):
    page = Selector(RED_HTML)
    search = copy.deepcopy(_redbull_search(page))
    ld = json.loads(page.css('script[type="application/ld+json"]::text').get())
    if state_edit:
        state_edit(search)
    if ld_edit:
        ld_edit(ld['itemListElement'][0])
    payload = {'data': pack([[REDBULL_KEY, {'key': REDBULL_KEY, 'data': {'response': search}}]])}
    return ('<link rel="canonical" href="' + REDBULL_PAGE + '">'
            '<script id="state-body">window.__INITIAL_DATA_CACHE__ = ' + json.dumps(payload) + ';</script>'
            '<script type="application/ld+json">' + json.dumps(ld) + '</script>')


class SavedTeamCatalogTests(unittest.TestCase):
    def setUp(self):
        self.network_guard = patch('socket.create_connection', side_effect=AssertionError('Network forbidden in offline tests'))
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)

    def lotto(self, html=LOTTO_HTML, url=LOTTO_URL, source=LOTTO):
        return parse_lotto(html, source, url, LOTTO_TIME)

    def red(self, html=RED_HTML, url=REDBULL_PAGE, source=RED):
        return parse_redbull_catalog(html, source, url, RED_TIME)

    def test_collector_routes_each_proposed_parser_without_network(self):
        from scripts.collect_offers import collect_source
        for code, parser, source, html, url, count in [
                ('lotto', 'lotto', LOTTO, LOTTO_HTML, LOTTO_URL, 1),
                ('redbull', 'redbull_catalog', RED, RED_HTML, REDBULL_PAGE, 23)]:
            with self.subTest(code=code), TemporaryDirectory() as directory, \
                    patch('scripts.collect_offers.ROOT', Path(directory)), \
                    patch('scripts.collect_offers.PublicPageFetcher') as fetcher:
                (Path(directory) / 'data').mkdir()
                from app.collectors.fetch_policy import CapturedPage
                fetcher.return_value.fetch.return_value = CapturedPage(
                    html.encode(), 200, url, {}, 'static', LOTTO_TIME if code == 'lotto' else RED_TIME)
                repository = MagicMock()
                collect_source({'code': code, 'parser': parser, 'domains': [], 'urls': [url]},
                               repository, {code: source})
                args = repository.save.call_args.args
                self.assertEqual(len(args[1]), count)
                self.assertEqual(args[3], [])
                self.assertFalse(args[4]['complete'])
                self.assertTrue(args[4]['partial'])
                if code == 'redbull':
                    self.assertEqual({row.stock for row in args[1]}, {'unknown'})

    def test_reduced_fixture_fingerprints_and_size_limits(self):
        expected = {'lotto-beanie.html': '8ac109a7a286694819b3fa795b8f1a410a6f6a8766a30de5a5fe82da0d65263c',
                    'redbull-jp-category.html': '83c150a7ca1f0fd1113742474563d1003a0ada39afcfe4cbc7996a1901a3c4f5',
                    'movistar-landing.html': 'ca5e22b9eaee78ffde44f2386ec60c13e7c69f84144fba0106f7594d2f55d74e'}
        self.assertLess(sum((FIXTURES / name).stat().st_size for name in expected), 30_000)
        for name, digest in expected.items():
            self.assertNotIn('src=', (FIXTURES / name).read_text())
            self.assertNotIn('<style', (FIXTURES / name).read_text())
            self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), digest)

    def test_lotto_single_saved_variant_price_stock_and_original_timestamp(self):
        rows = self.lotto()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row.name, str(row.price.amount), row.price.currency, row.stock),
                         ('Beanie', '25.00', 'EUR', 'in_stock'))
        self.assertEqual(row.url, LOTTO_URL)
        self.assertEqual(row.fetched_at, LOTTO_TIME)
        self.assertIsNone(row.identity.size)
        self.assertIsNone(row.identity.mpn)
        self.assertEqual(row.shipping_to_china.status, 'unknown')
        self.assertEqual(row.china_issued_card.status, 'unknown')
        self.assertIsNone(row.shipping)
        self.assertIsNone(row.tax)

    def test_lotto_currency_needs_explicit_matching_symbol(self):
        for value in ['25.00', '$ 25.00', '¥ 25.00', '€ NaN', '€ -25.00', '€ 25.00 USD']:
            with self.subTest(value=value):
                self.assertEqual(self.lotto(LOTTO_HTML.replace('&euro; 25.00', value)), [])
        self.assertEqual(self.lotto(source={**LOTTO, 'currency': 'USD'}), [])
        self.assertEqual(self.lotto(source={k: v for k, v in LOTTO.items() if k != 'currency'}), [])

    def test_lotto_page_form_and_wrapper_bind_same_product(self):
        for url in [LOTTO_URL.replace('/250/', '/237/'), LOTTO_URL.replace('https:', 'http:'),
                    LOTTO_URL.replace('www.lotto-intermarche.be', 'example.com'), LOTTO_URL + '?variant=other']:
            self.assertEqual(self.lotto(url=url), [])
        for old, new in [('value="250---1"', 'value="other"'),
                         ('class="variant-wrap" data-hash="250---1"', 'class="variant-wrap" data-hash="other"')]:
            self.assertEqual(self.lotto(LOTTO_HTML.replace(old, new)), [])

    def test_lotto_preorder_title_cannot_become_ready_stock(self):
        html = re.sub(r'(<h1[^>]*>)(.*?)(</h1>)', r'\1PRE-ORDER Beanie\3', LOTTO_HTML, flags=re.S)
        row = self.lotto(html)[0]
        self.assertEqual(row.stock, 'unknown')
        self.assertTrue(row.purchase_requirements)

    def test_lotto_multiple_variants_do_not_inherit_single_price_or_stock(self):
        html = LOTTO_HTML.replace('</body>', '<span class="variant-trigger" data-hash="250-S-1" data-stock="4"></span></body>')
        self.assertEqual(self.lotto(html), [])

    def test_lotto_missing_bad_or_conflicting_stock_is_unknown(self):
        for replacement in ['', 'data-stock="invalid"', 'data-stock="-1"', 'data-stock="0"']:
            with self.subTest(replacement=replacement):
                self.assertEqual(self.lotto(LOTTO_HTML.replace('data-stock="8"', replacement))[0].stock, 'unknown')
        for label in ['Niet op voorraad', 'Uitverkocht', 'Onbekend']:
            self.assertEqual(self.lotto(LOTTO_HTML.replace('Op voorraad', label))[0].stock, 'unknown')
        self.assertEqual(self.lotto(LOTTO_HTML.replace('id="submit"', 'id="submit" disabled'))[0].stock, 'unknown')

    def test_lotto_matching_zero_and_soldout_is_explicit_out_of_stock(self):
        html = LOTTO_HTML.replace('data-stock="8"', 'data-stock="0"').replace('Op voorraad', 'Uitverkocht')
        self.assertEqual(self.lotto(html)[0].stock, 'out_of_stock')

    def test_redbull_saved_23_jpy_product_quotes_are_not_size_inventory(self):
        rows = self.red()
        self.assertEqual(len(rows), 23)
        self.assertEqual(len({r.url for r in rows}), 23)
        self.assertEqual({r.price.currency for r in rows}, {'JPY'})
        self.assertEqual({r.stock for r in rows}, {'unknown'})
        self.assertEqual({r.fetched_at for r in rows}, {RED_TIME})
        for row in rows:
            self.assertIsNone(row.identity.size)
            self.assertIsNone(row.identity.mpn)
            self.assertIsNone(row.shipping)
            self.assertIsNone(row.tax)
            self.assertEqual(row.shipping_to_china.status, 'unknown')
            self.assertEqual(row.china_issued_card.status, 'unknown')
            self.assertIn(SIZE_UNKNOWN, row.purchase_requirements)
            self.assertTrue(row.image.startswith('https://assets.redbullshop.com/'))
        jersey = next(row for row in rows if row.name == 'SPECIALIZED France Race Jersey')
        self.assertEqual(int(jersey.price.amount), 24250)
        self.assertIn('/p/Men/', jersey.url)

    def test_redbull_preorder_marker_overrides_misleading_instock_and_false_flag(self):
        rows = self.red()
        preorders = [row for row in rows if PREORDER in row.purchase_requirements]
        self.assertEqual({r.name for r in preorders}, {'Winter Jacket', 'Hybrid 3-in-1 Jacket', 'Insulated Shirt Jacket'})
        self.assertTrue(all(r.stock == 'unknown' for r in preorders))

    def test_redbull_bound_sample_does_not_expand_reported_94_results(self):
        data = _redbull_search(Selector(RED_HTML))
        self.assertEqual(data['pagination']['totalResults'], 94)
        self.assertEqual(data['pagination']['totalPages'], 4)
        self.assertEqual(data['pagination']['currentPage'], 0)
        self.assertEqual(len(self.red()), len(data['products']))

    def test_redbull_default_eur_cache_is_not_quote_currency_or_dispatch_origin(self):
        self.assertEqual(self.red(source={**RED, 'currency': 'EUR'}), [])
        self.assertEqual(self.red(url=REDBULL_PAGE.replace('en-jp', 'en-int')), [])
        self.assertTrue(all(r.dispatch_origin is None for r in self.red()))

    def test_redbull_two_payloads_must_agree_price_currency_code_and_name(self):
        mutations = [lambda rows: rows[0]['item']['offers'].update(price='6501'),
                     lambda rows: rows[0]['item']['offers'].update(priceCurrency='EUR'),
                     lambda rows: rows[0]['item'].update(sku='OTHER'),
                     lambda rows: rows[0]['item'].update(name='Other')]
        for mutation in mutations:
            self.assertEqual(len(self.red(red_page(ld_edit=mutation))), 22)

    def test_redbull_urls_are_exact_same_host_market_and_variant(self):
        for mutate in [lambda url: url.replace('www.redbullshop.com', 'example.com'),
                       lambda url: url.replace('/en-jp/', '/en-int/'),
                       lambda url: url.replace('https:', 'http:'),
                       lambda url: url.replace('preselectedVariant=M-RBB264026001', 'preselectedVariant=OTHER'),
                       lambda url: url.replace('/M-RBB264026/', '/OTHER/')]:
            def edit(rows):
                offer = rows[0]['item']['offers']
                offer['url'] = mutate(offer['url'])
            self.assertEqual(len(self.red(red_page(ld_edit=edit))), 22)

    def test_redbull_missing_state_or_missing_price_does_not_fallback(self):
        self.assertEqual(self.red(RED_HTML.replace('id="state-body"', 'id="other"')), [])
        self.assertEqual(len(self.red(red_page(state_edit=lambda s: s['products'][0].pop('price')))), 22)
        self.assertEqual(len(self.red(red_page(state_edit=lambda s: s['products'].append(copy.deepcopy(s['products'][0]))))), 22)

    def test_redbull_absent_availability_never_becomes_soldout(self):
        def edit(search):
            for row in search['products']:
                row.pop('soldOut')
        self.assertEqual({r.stock for r in self.red(red_page(state_edit=edit))}, {'unknown'})
        rows = self.red(red_page(state_edit=lambda s: s['products'][0].update(soldOut=True)))
        self.assertEqual(rows[0].stock, 'out_of_stock')

    def test_reference_decoder_roundtrip_null_empty_and_negative(self):
        value = {'entries': [], 'blank': '', 'nested': {'a': None, 'b': True, 'c': False, 'n': -1}}
        self.assertEqual(_decode_cache(pack(value)), value)

    def test_reference_decoder_rejects_cycles_bad_references_and_unsupported_types(self):
        for payload in [[['a|0'], '0'], [['n|?'], '0'], [['a|z'], '0'], [['d|2026'], '0'], [['b|yes'], '0']]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                _decode_cache(payload)

    def test_movistar_saved_ids_are_discovery_hints_not_verified_offers(self):
        rows = parse_jsonld(MOV_HTML, {'code': 'movistar', 'name': 'Movistar', 'brand': 'Movistar'},
                            'https://www.tradeinn.com/bikeinn/es/movistar_team', RED_TIME)
        self.assertEqual(rows, [])
        self.assertIn("pintar_productos_id_modelos('142758678,", MOV_HTML)
        self.assertNotIn('priceCurrency', MOV_HTML)
        self.assertNotIn('"@type":"Product"', MOV_HTML)
        self.assertNotIn('"price"', MOV_HTML)


if __name__ == '__main__':
    unittest.main()
