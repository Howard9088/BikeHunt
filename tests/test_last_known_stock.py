"""Only an affirmative new sold-out observation withdraws known stock."""
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from app.catalog.models import Money
from app.catalog.service import ComparisonCatalog, compare_offer
from app.catalog.storage import OfferRepository
from test_catalog import NOW, make_fx, make_offer


class LastKnownStockTests(unittest.TestCase):
    def test_old_and_failed_stock_keep_exact_channel_without_claiming_discount(self):
        for state in ["current", "retained"]:
            row = make_offer(fetched_at=NOW-timedelta(days=90), collection_state=state,
                             original_price=Money(amount="120", currency="USD"))
            catalog = ComparisonCatalog([row], make_fx(), NOW)
            card = catalog.search()[0].channel_quotes[row.source_code]
            self.assertEqual(card.reference_offer_id, row.offer_id)
            self.assertEqual(card.reference_url, row.url)
            self.assertEqual(card.fetched_at, row.fetched_at)
            self.assertEqual(card.reference_collection_state, state)
            self.assertEqual(card.stock_state, "in_stock")
            self.assertEqual(card.available_sizes, ["M"])
            self.assertIn("上次核实", card.status)
            self.assertIsNone(card.discount_pct)
            self.assertFalse(compare_offer(row, make_fx(), NOW).eligible)

    def test_expired_coupon_does_not_remove_stock_or_claim_current_saving(self):
        row = make_offer(price_valid_until=(NOW-timedelta(days=1)).date().isoformat(),
                         original_price=Money(amount="120", currency="USD"))
        catalog = ComparisonCatalog([row], make_fx(), NOW)
        card = catalog.search()[0].channel_quotes[row.source_code]
        self.assertTrue(catalog.available(row))
        self.assertIsNone(card.discount_pct)
        self.assertEqual(card.reference_price_valid_until, row.price_valid_until)
        self.assertFalse(compare_offer(row, make_fx(), NOW).eligible)

    def test_unknown_never_promotes_stock_and_sold_out_overrides_history(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = OfferRepository(Path(folder)/"data")
            known = make_offer()
            repo.save("a", [known], NOW, [])
            later = NOW+timedelta(days=2)
            unknown = known.model_copy(update={"stock": "unknown", "fetched_at": later})
            repo.save("a", [unknown], later, [])
            retained = repo.load()[0]
            self.assertEqual(retained.fetched_at, known.fetched_at)
            self.assertEqual(retained.stock, "in_stock")
            self.assertEqual(retained.collection_state, "retained")
            self.assertTrue(ComparisonCatalog([retained], make_fx(), later).available(retained))
            sold = known.model_copy(update={"stock": "out_of_stock", "fetched_at": later})
            repo.save("a", [sold], later, [])
            card = ComparisonCatalog(repo.load(), make_fx(), later).search()[0]
            self.assertEqual(card.stock_state, "out_of_stock")
            self.assertFalse(card.channel_quotes)
            never = make_offer("never", stock="unknown")
            repo.save("never", [never], NOW, [])
            catalog = ComparisonCatalog(repo.load(), make_fx(), later)
            self.assertFalse(catalog.available(never))

    def test_missing_future_or_legacy_observations_are_not_reliable_stock(self):
        for changes in [{"fetched_at": None}, {"fetched_at": NOW+timedelta(seconds=1)},
                        {"data_kind": "legacy_cache"}, {"stock": "unknown"}]:
            row = make_offer(**changes)
            self.assertFalse(ComparisonCatalog([row], make_fx(), NOW).available(row))
