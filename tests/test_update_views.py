"""Exact event-product binding, backward-compatible storage, and seed restoration."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.catalog.service import ComparisonCatalog
from app.update_views import enrich_events, event_product
from app.updates import UpdateStore
from scripts.seed_updates import restore_public_cursor, validate_events
from test_catalog import make_offer, make_fx


class UpdateViewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def offer(self, oid="exact", **values):
        return make_offer(oid, image="https://shop.example/model-a-red.jpg",
                          url="https://shop.example/products/model-a?variant=m", **values)

    def test_legacy_event_uses_exact_offer_id_and_url_never_generic_name(self):
        offer = self.offer()
        event = UpdateStore(self.root).capture([], [offer])[0]
        event.pop("product")
        wrong = self.offer("another", name=offer.name)
        result = enrich_events([event], ComparisonCatalog([wrong], make_fx()))[0]
        self.assertIsNone(result["product"])
        result = enrich_events([event], ComparisonCatalog([offer], make_fx()))[0]
        self.assertEqual(result["product"]["image"], offer.image)
        self.assertEqual(result["product"]["offer_id"], offer.offer_id)
        self.assertTrue(result["product"]["product_id"])
        changed_url = offer.model_copy(update={"url":"https://shop.example/other-model"})
        self.assertIsNone(enrich_events([event], ComparisonCatalog([changed_url], make_fx()))[0]["product"])

    def test_capture_persists_event_time_photo_color_size_after_offer_disappears(self):
        offer = self.offer()
        store = UpdateStore(self.root)
        event = store.capture([], [offer])[0]
        self.assertEqual(store.latest()[0]["product"], event_product(offer))
        result = enrich_events([event], ComparisonCatalog([], make_fx()))[0]
        self.assertEqual(result["product"]["image"], offer.image)
        self.assertEqual(result["product"]["size"], offer.identity.size)
        self.assertEqual(result["product"]["current_stock"], "unknown")
        self.assertIsNone(result["product"]["product_id"])
        self.assertEqual((result["id"],result["event_key"]), (event["id"],event["event_key"]))

    def test_current_soldout_is_separate_from_historical_event_stock(self):
        offer = self.offer()
        event = UpdateStore(self.root).capture([], [offer])[0]
        sold = offer.model_copy(update={"stock":"out_of_stock"})
        result = enrich_events([event], ComparisonCatalog([sold], make_fx()))[0]
        self.assertEqual(result["stock"], "in_stock")
        self.assertEqual(result["product"]["current_stock"], "out_of_stock")
        self.assertEqual(result["old_price"], event["old_price"])

    def test_persisted_event_photo_is_not_replaced_by_later_photo(self):
        offer = self.offer()
        event = UpdateStore(self.root).capture([], [offer])[0]
        later = offer.model_copy(update={"image":"https://shop.example/new-color.jpg"})
        result = enrich_events([event], ComparisonCatalog([later], make_fx()))[0]
        self.assertEqual(result["product"]["image"], offer.image)

    def test_enriched_seed_roundtrips_and_rejects_mismatched_identity(self):
        offer = self.offer()
        event = UpdateStore(self.root).capture([], [offer])[0]
        enriched = enrich_events([event], ComparisonCatalog([offer], make_fx()))
        with tempfile.TemporaryDirectory() as other:
            root=Path(other);(root/"data").mkdir()
            (root/"data/public_updates.json").write_text(json.dumps(enriched))
            restore_public_cursor(root)
            self.assertEqual(UpdateStore(root).latest()[0]["product"], enriched[0]["product"])
        bad = dict(enriched[0], product=dict(enriched[0]["product"], offer_id="wrong"))
        with self.assertRaises(ValueError):
            validate_events([bad],bad["id"])

    def test_old_database_migrates_without_changing_event_cursor(self):
        store=UpdateStore(self.root)
        event=store.capture([], [self.offer()])[0]
        with store.connect() as db:
            db.execute('ALTER TABLE events DROP COLUMN product_json')
        migrated=UpdateStore(self.root)
        self.assertEqual(migrated.cursor(),event["id"])
        self.assertNotIn("product",migrated.latest()[0])
        self.assertEqual(migrated.capture([], [self.offer("second")])[0]["id"],event["id"]+1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
