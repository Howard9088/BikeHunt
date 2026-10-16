"""Same-store policy aliases must not refresh inventory or invent checkout facts."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from app.catalog.models import Evidence
from app.catalog.service import compare_offer
from app.source_rules import apply_source_rules
from test_catalog import NOW, make_offer, make_fx


class SourceRuleAliasTests(unittest.TestCase):
    def setUp(self):
        self.sources = {s['code']: s for s in json.loads((ROOT/'data/sources.json').read_text())}

    def quote(self, code, currency='USD'):
        return make_offer(code, currency=currency, source_code=code,
                          url=self.sources[code]['base_url']+'/products/test',
                          sales_region='Observed merchant market', shipping=None, tax=None,
                          shipping_to_china=Evidence(), china_issued_card=Evidence())

    def unchanged_quote(self, original, result):
        for field in ['source_code', 'offer_id', 'url', 'identity', 'price', 'sales_region', 'fetched_at', 'stock']:
            self.assertEqual(getattr(result, field), getattr(original, field), field)
        self.assertEqual(result.china_issued_card.status, 'unknown')
        self.assertIsNone(result.shipping)
        compared = compare_offer(result, make_fx(), NOW)
        self.assertFalse(compared.eligible)
        self.assertIsNone(compared.total_cny)

    def test_domestic_delivery_scope_is_not_free_shipping_or_card_approval(self):
        source = self.sources['decathlon_cn']
        original = self.quote('decathlon_cn', 'CNY')
        result = apply_source_rules(original, source, ROOT/'data')
        self.assertEqual(result.shipping_to_china.status, 'yes')
        self.assertEqual(result.shipping_to_china.url, 'https://www.decathlon.com.cn/help/delivery-method')
        self.assertIn('港澳台及海外地区不配送', result.shipping_to_china.note)
        self.assertIn('结账页', result.shipping_to_china.note)
        self.unchanged_quote(original, result)

    def test_jayco_uses_same_maap_store_policy_without_changing_market(self):
        source = self.sources['jayco']
        self.assertEqual(source['base_url'], self.sources['maap']['base_url'])
        self.assertEqual(source['rules_code'], 'maap')
        original = self.quote('jayco')
        result = apply_source_rules(original, source, ROOT/'data')
        self.assertEqual(result.shipping_to_china.status, 'no')
        self.assertEqual(result.accepted_card_networks, ['Visa', 'Mastercard', 'American Express'])
        self.assertEqual(result.card_networks_evidence.status, 'yes')
        self.assertEqual(result.dispatch_origin, '澳大利亚墨尔本仓库')
        self.unchanged_quote(original, result)
        # Alias must look up MAAP's translated hashes, not bypass document drift.
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp); (data/'rules').mkdir()
            book = json.loads((ROOT/'data/rules/maap.json').read_text())
            for doc in book['documents']:
                doc['content_hash'] = 'changed-test-document'
            (data/'rules/maap.json').write_text(json.dumps(book))
            changed = apply_source_rules(original, source, data)
            self.assertEqual(changed.accepted_card_networks, [])
            self.assertEqual(changed.card_networks_evidence.status, 'unknown')
            self.assertIsNone(changed.dispatch_origin)
            self.unchanged_quote(original, changed)

    def test_lidl_santini_warehouse_does_not_claim_china_delivery(self):
        source = self.sources['lidl_trek']
        self.assertEqual(source['base_url'], self.sources['santini']['base_url'])
        self.assertEqual(source['rules_code'], 'santini')
        original = self.quote('lidl_trek', 'EUR')
        result = apply_source_rules(original, source, ROOT/'data')
        self.assertEqual(result.shipping_to_china.status, 'unknown')
        self.assertEqual(result.dispatch_origin, '意大利仓库')
        self.unchanged_quote(original, result)


if __name__ == '__main__':
    unittest.main()
