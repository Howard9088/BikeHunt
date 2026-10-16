"""Domestic official observations retain their real verification times."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.catalog.models import Offer, FxSnapshot
from app.catalog.service import ComparisonCatalog
from app.localization import category_of

ROOT = Path(__file__).resolve().parents[1]

class ChinaOfficialSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((ROOT / "data/offers/decathlon_cn.json").read_text())
        self.offers = [Offer.model_validate(row) for row in self.payload["offers"]]
        self.fx = FxSnapshot(snapshot_id="domestic-test", rates={"CNY": Decimal("1")})

    def test_exact_observed_variants_and_conditional_coupon(self):
        self.assertEqual(len(self.offers), 2)
        self.assertEqual({o.identity.mpn for o in self.offers}, {"8969603", "8987878"})
        for offer in self.offers:
            self.assertEqual(offer.source_code, "decathlon_cn")
            self.assertEqual(offer.sales_region, "中国大陆 CNY 报价")
            self.assertTrue(offer.identity.size.startswith("M"))
            self.assertEqual(offer.price.amount, Decimal("399.90"))
            self.assertEqual(offer.price.currency, "CNY")
            self.assertIsNone(offer.original_price)
            self.assertIsNone(offer.shipping)
            self.assertEqual(offer.stock, "in_stock")
            self.assertIn("满300减30", " ".join(offer.purchase_requirements))
            self.assertIn("未验证实际抵扣", " ".join(offer.purchase_requirements))

    def test_manual_snapshot_is_not_refreshed_by_crawler(self):
        settings = json.loads((ROOT / "data/crawl_sources.json").read_text())
        self.assertNotIn("decathlon_cn", {row["code"] for row in settings})
        self.assertEqual(self.payload["verification_method"], "manual_public_selected_variant")
        for offer in self.offers:
            self.assertIsNotNone(offer.fetched_at)
            recent = ComparisonCatalog([offer], self.fx, offer.fetched_at + timedelta(minutes=5))
            expired = ComparisonCatalog([offer], self.fx, offer.fetched_at + timedelta(hours=1, seconds=1))
            self.assertEqual(recent.search()[0].stock_state, "in_stock")
            self.assertEqual(expired.search()[0].stock_state, "in_stock")
            self.assertTrue(expired.search()[0].channel_quotes)

    def test_chinese_garments_use_existing_clothing_groups(self):
        self.assertEqual(category_of(self.offers[0].name), "bibs")
        self.assertEqual(category_of(self.offers[1].name), "jerseys")
        now = max(o.fetched_at for o in self.offers) + timedelta(minutes=5)
        cards = ComparisonCatalog(self.offers, self.fx, now).search()
        self.assertEqual({c.category_group for c in cards}, {"clothing"})
        self.assertEqual(len(cards), 2)

if __name__ == "__main__":
    unittest.main()
