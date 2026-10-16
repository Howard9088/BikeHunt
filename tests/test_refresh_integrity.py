"""Failed refreshes must not turn retained quotes into actionable inventory."""
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.catalog.service import ComparisonCatalog, compare_offer
from app.catalog.storage import OfferRepository, atomic_json
from test_catalog import NOW, make_fx, make_offer

class RefreshIntegrityTests(unittest.TestCase):
    def test_failed_refresh_keeps_last_known_selectable_stock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            quote = make_offer()
            atomic_json(root/'offers'/f'{quote.source_code}.json', {'offers':[quote.model_dump(mode='json')]})
            repo = OfferRepository(root)
            repo.save(quote.source_code, [], NOW+timedelta(minutes=1), [{'url':quote.url,'error':'HTTP 429'}])
            rows = repo.load()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].price, quote.price)
            self.assertEqual(rows[0].fetched_at, quote.fetched_at)
            self.assertEqual(rows[0].collection_state, 'retained')
            catalog = ComparisonCatalog(rows, make_fx(), NOW+timedelta(minutes=2))
            self.assertEqual(catalog.search()[0].stock_state, 'in_stock')
            self.assertEqual(catalog.search()[0].available_sizes, ["M"])
            self.assertFalse(compare_offer(rows[0], make_fx(), NOW).eligible)
            fresh = quote.model_copy(update={'fetched_at':NOW+timedelta(minutes=3)})
            repo.save(quote.source_code, [fresh], NOW+timedelta(minutes=3), [])
            self.assertEqual(repo.load()[0].collection_state, 'current')

    def test_partial_failure_only_invalidates_affected_page(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a = make_offer('a', url='https://example.com/a')
            b = make_offer('b', url='https://example.com/b')
            atomic_json(root/'offers'/f'{a.source_code}.json', {'offers':[q.model_dump(mode='json') for q in [a,b]]})
            atomic_json(root/'collection_status'/f'{a.source_code}.json', {'status':'partial','attempted_at':(NOW+timedelta(minutes=1)).isoformat(),'errors':[{'url':a.url,'error':'empty'}]})
            states = {q.offer_id:q.collection_state for q in OfferRepository(root).load()}
            self.assertEqual(states, {'a':'retained','b':'current'})

    def test_sold_out_variant_is_explicit_and_unselectable(self):
        catalog = ComparisonCatalog([make_offer(stock='out_of_stock')], make_fx(), NOW)
        card = catalog.search()[0]
        self.assertEqual(card.stock_state, 'out_of_stock')
        detail = catalog.compare(card.product_id)
        self.assertFalse(detail.variants[0].in_stock)
        self.assertEqual(detail.variants[0].stock_state, 'out_of_stock')

if __name__ == '__main__':
    unittest.main()
