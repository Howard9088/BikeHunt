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
        self.assertEqual(len(self.catalog['channels']), 35)
        validate_payment_methods(self.fixture, self.catalog, require_complete=True)
        for row in self.fixture['entries']:
            self.assertTrue(REQUIRED_METHODS <= {x['method_key'] for x in row['methods']})

    def test_actual_release_covers_all_channels_and_every_required_category(self):
        data = read_payment_methods(ROOT)
        self.assertEqual(len(data['entries']), 35)
        for row in data['entries']:
            self.assertTrue(REQUIRED_METHODS <= {m['method_key'] for m in row['methods']})
            for method in row['methods']:
                self.assertTrue(method['note'].strip())
                self.assertTrue(method['account_region_constraints'].strip())

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
