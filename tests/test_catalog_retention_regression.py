"""Regression for previously observed sold-out variants omitted by a refresh."""
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.catalog.storage import OfferRepository, atomic_json
from test_catalog import NOW, make_offer


class SoldOutRetentionTests(unittest.TestCase):
    def test_missing_sold_out_variant_keeps_original_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atomic_json(root / 'sources.json', [])
            repository = OfferRepository(root)
            old_time = NOW - timedelta(days=1)
            old = make_offer('old', source_code='maap', url='https://example.org/item',
                             stock='out_of_stock', fetched_at=old_time)
            new = make_offer('new', source_code='maap', url='https://example.org/item',
                             stock='in_stock', fetched_at=NOW)
            repository.save('maap', [old], old_time, [])
            repository.save('maap', [new], NOW, [])
            offers = {row.offer_id: row for row in repository.load()}
            self.assertIn('old', offers)
            self.assertEqual(offers['old'].stock, 'out_of_stock')
            self.assertEqual(offers['old'].fetched_at, old_time)
            self.assertEqual(offers['old'].collection_state, 'retained')
            self.assertEqual(offers['new'].stock, 'in_stock')


if __name__ == '__main__':
    unittest.main()
