"""Release-data checks for the read-only pre-registration summary."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PurchaseReadinessTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'web/purchase-readiness.json').read_text())
        self.rows = {row['sourceCode']: row for row in self.data['entries']}

    def test_no_current_china_issued_card_approval_is_invented(self):
        self.assertEqual(self.data['checkedAt'], '2026-10-15')
        for row in self.rows.values():
            self.assertIn(row['payment']['chinaIssuedCard'], ('unknown', 'conditional_checkout'))
            self.assertTrue(row['sources'])
        for code in ('amazon_de', 'amazon_jp'):
            self.assertEqual(self.rows[code]['payment']['status'], 'historical_official_only')

    def test_market_and_merchant_boundaries(self):
        for code, market in [('amazon_us', '美国站'), ('amazon_uk', '英国站'), ('amazon_de', '德国站'), ('amazon_jp', '日本站')]:
            self.assertEqual(self.rows[code]['scope'], 'market')
            self.assertEqual(self.rows[code]['salesRegion'], market)
        self.assertEqual(self.rows['poc']['salesRegion'], 'Global EN')
        teamcycles = self.rows['teamcycles']
        self.assertEqual(teamcycles['scope'], 'merchant')
        self.assertIsNone(teamcycles['salesRegion'])
        self.assertEqual(teamcycles['merchantHosts'], ['www.teamcycles.com'])
        self.assertEqual(teamcycles['payment']['chinaIssuedCard'], 'unknown')
        self.assertEqual(teamcycles['directChina']['status'], 'unknown')
        self.assertIn('自行车配送部分', teamcycles['directChina']['note'])
        self.assertIn('不能因此推断所有骑行服', teamcycles['directChina']['note'])
        self.assertNotIn('sigmasports', self.rows)
        self.assertNotIn('decathlon', self.rows)

    def test_shipping_restrictions_and_currency_stay_explicit(self):
        visma = self.rows['visma']['directChina']
        self.assertEqual((visma['shippingAmount'], visma['shippingCurrency']), (47.95, 'EUR'))
        self.assertEqual(self.rows['maap']['directChina']['status'], 'prohibited')
        self.assertEqual(self.rows['maap']['forwarding']['status'], 'unknown')
        self.assertEqual(self.rows['poc']['forwarding']['status'], 'prohibited')

    def test_forwarding_is_reference_not_a_fabricated_total_or_legal_limit(self):
        text = json.dumps(self.data, ensure_ascii=False)
        self.assertNotIn('CNY1000', text)
        self.assertNotIn('CNY 1000', text)
        self.assertNotIn('exampleRate', text)
        self.assertNotIn('landedTotal', text)
        self.assertIn('US$9.99/月', text)
        for row in self.data['forwarders']:
            self.assertTrue(row['calculator'].startswith('https://'))
            self.assertTrue(row['warning'])

    def test_assets_are_published_and_ui_ci_is_wired(self):
        source = (ROOT / 'app/pages.py').read_text()
        index = (ROOT / 'web/index.html').read_text()
        workflow = (ROOT / '.github/workflows/pages.yml').read_text()
        for name in ('purchase-readiness.js', 'purchase-readiness.json'):
            self.assertIn(name, source)
        self.assertLess(index.index('purchase-readiness.js'), index.index('gallery.js'))
        self.assertIn('node scripts/test_purchase_readiness.js', workflow)
        self.assertIn('python scripts/test_purchase_readiness_ui.py', workflow)


if __name__ == '__main__':
    unittest.main()
