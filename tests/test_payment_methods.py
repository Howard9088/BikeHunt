"""Schema, coverage and build-contract regression tests for payment summaries."""
import copy
import json
import unittest
from pathlib import Path

from app.payment_methods import REQUIRED_METHODS, read_payment_methods, validate_payment_methods

ROOT = Path(__file__).resolve().parents[1]


class PaymentMethodsTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / 'web/payment-channels.json').read_text())
        self.fixture = json.loads((ROOT / 'tests/fixtures/payment-methods.json').read_text())

    def test_fixture_and_full_source_registry(self):
        self.assertEqual(len(self.catalog['channels']), 37)
        validate_payment_methods(self.fixture, self.catalog, require_complete=True)
        for row in self.fixture['entries']:
            self.assertTrue(REQUIRED_METHODS <= {x['method_key'] for x in row['methods']})

    def test_actual_release_covers_all_channels_and_every_required_category(self):
        data = read_payment_methods(ROOT)
        self.assertEqual(len(data['entries']), 38)
        for row in data['entries']:
            self.assertTrue(REQUIRED_METHODS <= {m['method_key'] for m in row['methods']})
            for method in row['methods']:
                self.assertTrue(method['note'].strip())
                self.assertTrue(method['account_region_constraints'].strip())

    def test_china_official_store_is_exact_and_help_is_not_checkout_proof(self):
        channel = next(c for c in self.catalog['channels'] if c['source_code'] == 'decathlon_cn')
        self.assertEqual(channel['sales_regions'], ['中国大陆 CNY 报价'])
        self.assertEqual(channel['merchant_hosts'], ['www.decathlon.com.cn', 'decathlon.com.cn'])
        self.assertEqual(channel['base_url'], 'https://www.decathlon.com.cn/')
        for data in (self.fixture, read_payment_methods(ROOT)):
            row = next(r for r in data['entries'] if r['source_code'] == 'decathlon_cn')
            self.assertEqual(row['scope'], 'market')
            self.assertEqual(row['sales_region'], '中国大陆 CNY 报价')
            self.assertEqual(row['merchant_hosts'], channel['merchant_hosts'])
            self.assertEqual(len(row['methods']), 11)
            self.assertEqual({m['method_key'] for m in row['methods']}, REQUIRED_METHODS)
            for method in row['methods']:
                listed = method['method_key'] in {'cards', 'china_issued_cards', 'alipay', 'wechat_pay', 'unionpay'}
                self.assertEqual(method['status'], 'conditional' if listed else 'unknown')
                self.assertEqual(method['china_applicability']['status'], 'unknown')
                self.assertEqual(method['merchant_evidence_status'], 'official_text' if listed else 'unavailable')
                self.assertEqual(method['evidence_urls'], ['https://www.decathlon.com.cn/help/introduction'] if listed else [])
                self.assertEqual(method['checked_at'], '2026-10-16' if listed else None)
                if listed:
                    self.assertEqual(method['evidence_class'], 'official_confirmed')
                    self.assertIn('官方帮助', method['note'])
                    self.assertIn('未实测', method['note'])
                if method['method_key'] == 'cards':
                    self.assertEqual(method['card_networks'], ['Visa'])
                self.assertTrue(method['note'].strip())
                self.assertTrue(method['account_region_constraints'].strip())
            self.assertTrue(any(r['source_code'] == 'decathlon' for r in data['entries']))
        for changes in ({'merchant_hosts': ['shop.decathloncmacgmteam.com']},
                        {'sales_region': '法国站 EUR 报价'}):
            invalid = copy.deepcopy(self.fixture)
            next(r for r in invalid['entries'] if r['source_code'] == 'decathlon_cn').update(changes)
            with self.assertRaises(ValueError):
                validate_payment_methods(invalid, self.catalog, require_complete=True)


    def test_corrected_team_merchants_and_colnago_are_exact(self):
        expected = {
            'movistar': ('gobik.com', 'US 市场 · EUR 报价；未验证其他市场库存', 'www.tradeinn.com'),
            'jayco': ('maap.cc', 'MAAP国际站；以逐规格实际币种报价为准，配送另核', 'shop.greenedgecycling.com'),
            'colnago': ('www.colnago.com', 'US 市场 · USD 商品报价；配送另核', 'evil.example'),
        }
        for code, (host, market, wrong_host) in expected.items():
            channel = next(c for c in self.catalog['channels'] if c['source_code'] == code)
            self.assertEqual(channel['sales_regions'], [market])
            self.assertIn(host, channel['merchant_hosts'])
            self.assertNotIn(wrong_host, channel['merchant_hosts'])
            for data in (self.fixture, read_payment_methods(ROOT)):
                row = next(r for r in data['entries'] if r['source_code'] == code)
                self.assertEqual(row['sales_region'], market)
                self.assertEqual(row['scope'], 'market')
                self.assertIn(host, row['merchant_hosts'])
                self.assertTrue(REQUIRED_METHODS <= {m['method_key'] for m in row['methods']})
                china = next(m for m in row['methods'] if m['method_key'] == 'china_issued_cards')
                self.assertEqual(china['status'], 'unknown')
                if code == 'colnago':
                    self.assertTrue(all(m['status'] == 'unknown' for m in row['methods']))
            invalid = copy.deepcopy(self.fixture)
            next(r for r in invalid['entries'] if r['source_code'] == code)['merchant_hosts'] = [wrong_host]
            with self.assertRaises(ValueError):
                validate_payment_methods(invalid, self.catalog, require_complete=True)

    def test_missing_unknown_blank_and_undated_claims_are_rejected(self):
        for mutation in (
            lambda d: d['entries'].pop(),
            lambda d: d['entries'][0]['methods'].pop(),
            lambda d: d['entries'][0]['methods'][0].update(note=''),
            lambda d: d['entries'][0]['methods'][2].update(evidence_urls=[]),
            lambda d: d['entries'][0]['methods'][2].update(checked_at=None),
            lambda d: d['entries'][0]['methods'][2].update(checked_at='2026-02-30'),
            lambda d: d['entries'][0]['methods'][2].update(evidence_urls=['https://evil.example/']),
            lambda d: d['entries'][0].update(merchant_hosts=['evil.example']),
            lambda d: d['entries'][0].update(sales_region='unrelated market'),
            lambda d: d['entries'][0].update(scope='merchant', sales_region=None),
            lambda d: d['entries'][0].update(merchant_evidence_status='official_icons_only'),
            lambda d: d['entries'][0].update(merchant_evidence_status='unavailable'),
            lambda d: d['entries'][0].update(merchant_evidence_status='historical_official'),
        ):
            data = copy.deepcopy(self.fixture)
            mutation(data)
            with self.assertRaises(ValueError):
                validate_payment_methods(data, self.catalog, require_complete=True)

    def test_unknown_may_have_no_source_or_observation_but_still_explains_why(self):
        data = copy.deepcopy(self.fixture)
        data['entries'][0]['methods'][0].update(checked_at=None, evidence_urls=[])
        validate_payment_methods(data, self.catalog, require_complete=True)

    def test_object_china_evidence_keeps_note_and_class(self):
        data = copy.deepcopy(self.fixture)
        data['entries'][0]['methods'][0]['china_applicability'] = {
            'status': 'unknown', 'evidence_class': 'insufficient_evidence',
            'note': '测试：中国发行地没有得到保证。'}
        validate_payment_methods(data, self.catalog, require_complete=True)
        data['entries'][0]['methods'][0]['china_applicability']['note'] = ''
        with self.assertRaises(ValueError):
            validate_payment_methods(data, self.catalog)

    def test_separate_merchants_cannot_borrow_sibling_evidence(self):
        data = copy.deepcopy(self.fixture)
        row = next(r for r in data['entries'] if r['source_code'] == 'alpecin')
        row['channels'][0]['methods'][0]['evidence_urls'] = ['https://www.kalas.cc/fixture-policy']
        with self.assertRaises(ValueError):
            validate_payment_methods(data, self.catalog)

    def test_cdn_asset_requires_exact_identity_and_owning_official_page(self):
        data = copy.deepcopy(self.fixture)
        row = next(r for r in data['entries'] if r['source_code'] == 'ef_team_shop')
        asset = next(c for c in self.catalog['channels'] if c['source_code'] == 'ef_team_shop')['reference_assets'][0]
        method = row['methods'][0]
        method.update(status='conditional', merchant_evidence_status='official_icons_only',
                      evidence_urls=[asset['owner_page'], asset['url']])
        validate_payment_methods(data, self.catalog)
        method['evidence_urls'] = [asset['url']]
        with self.assertRaises(ValueError):
            validate_payment_methods(data, self.catalog)
        method['evidence_urls'] = [asset['owner_page'], asset['url'] + '&replacement=1']
        with self.assertRaises(ValueError):
            validate_payment_methods(data, self.catalog)

    def test_oakley_us_keeps_jp_and_unknown_china_card(self):
        market = '美国站 USD 报价'
        channel = next(r for r in self.catalog['channels'] if r['source_code'] == 'oakley')
        self.assertEqual(channel['sales_regions'], [market, '未核实'])
        production = read_payment_methods(ROOT)
        for data in [self.fixture, production]:
            rows = [r for r in data['entries'] if r['source_code'] == 'oakley']
            self.assertEqual(len(rows), 2)
            us = next(r for r in rows if r['sales_region'] == market)
            jp = next(r for r in rows if r['sales_region'] == '未核实')
            self.assertEqual(us['merchant_hosts'], ['www.oakley.com'])
            self.assertEqual(us['observed_market'], 'US/USD')
            self.assertEqual({m['method_key'] for m in us['methods']}, REQUIRED_METHODS)
            for m in us['methods']:
                listed = m['method_key'] in {'cards', 'paypal', 'apple_pay', 'unionpay', 'gift_cards', 'instalments'}
                self.assertEqual(m['status'], 'conditional' if listed else 'unknown')
                self.assertEqual(m['china_applicability']['status'], 'unknown')
                self.assertEqual(m['checked_at'], '2026-10-16')
                self.assertEqual(m['evidence_urls'], ['https://www.oakley.com/en-us/support/shopping-support'])
            self.assertEqual(next(m for m in jp['methods'] if m['method_key'] == 'paypal')['status'], 'unknown')
            invalid = copy.deepcopy(data)
            next(r for r in invalid['entries'] if r['source_code'] == 'oakley' and r['sales_region'] == market)['sales_region'] = '日本站报价'
            with self.assertRaises(ValueError): validate_payment_methods(invalid, self.catalog, require_complete=True)
        jp = next(r for r in production['entries'] if r['source_code'] == 'oakley' and r['sales_region'] == '未核实')
        self.assertEqual(jp['observed_market'], 'JP/JPY')
        self.assertEqual(jp['checked_at'], '2026-10-15')
        codes = {r['source_code'] for r in production['entries']}
        sources = {r['code'] for r in json.loads((ROOT/'data/sources.json').read_text())}
        coverage = production['coverage']
        self.assertEqual(coverage['registered_sources'], len(codes & sources))
        self.assertEqual(coverage['additional_directory_entries'], len(codes - sources))
        self.assertEqual(coverage['additional_market_entries'], len(production['entries'])-len(codes))
        self.assertEqual(coverage['unmapped_registered_sources'], sorted(sources-codes))
        self.assertEqual(coverage['actual_payment_tests'], 0)

    def test_runtime_and_ci_assets_are_wired(self):
        index = (ROOT / 'web/index.html').read_text()
        pages = (ROOT / 'app/pages.py').read_text()
        workflow = (ROOT / '.github/workflows/pages.yml').read_text()
        for asset in ('payment-methods.js', 'payment-methods.json', 'payment-channels.json'):
            self.assertIn(asset, pages)
        self.assertLess(index.index('payment-methods.js'), index.index('purchase-readiness.js'))
        self.assertIn('read_payment_methods(root)', pages)
        self.assertIn('node scripts/test_payment_methods.js', workflow)
        self.assertIn('python scripts/test_payment_methods_ui.py', workflow)
        self.assertIn('python scripts/verify_payment_methods.py --local-dir _site', workflow)
        self.assertIn('paymentDirectoryMarkup(entry)', (ROOT / 'web/flows.js').read_text())


if __name__ == '__main__':
    unittest.main()
