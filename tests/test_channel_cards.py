"""Source-bound catalog cards; synthetic offers only."""
import unittest
from datetime import timedelta
from app.catalog.models import Money, ProductCard
from app.catalog.service import ComparisonCatalog
from test_catalog import NOW, make_fx, make_offer

class ChannelCardTests(unittest.TestCase):
    def test_only_current_source_has_stock_and_its_own_price(self):
        rows = [make_offer("a", "80"), make_offer("b", "100"),
                make_offer("sold", "1", stock="out_of_stock"),
                make_offer("unknown", "2", stock="unknown"),
                make_offer("old", "3", fetched_at=NOW-timedelta(hours=2)),
                make_offer("retained", "4", collection_state="retained")]
        card = ComparisonCatalog(rows, make_fx(), NOW).search()[0]
        self.assertEqual(set(card.channel_quotes), {"a", "b", "old", "retained"})
        self.assertEqual(card.channel_quotes["a"].reference_price.amount, 80)
        self.assertEqual(card.channel_quotes["b"].reference_price.amount, 100)
        for code, quote in card.channel_quotes.items():
            self.assertEqual(quote.reference_offer_id, code)
            self.assertEqual(quote.reference_url, "https://example.org/"+code)
            self.assertEqual(quote.product_id, card.product_id)
            self.assertEqual(quote.channel_quotes, {})
            self.assertEqual(quote.available_sizes, ["M"])
        # Recursive serialization stays finite and preserves exact source fields.
        restored = ProductCard.model_validate_json(card.model_dump_json())
        self.assertEqual(restored.channel_quotes["b"].reference_price.amount, 100)

    def test_source_sizes_discount_and_variant_do_not_leak(self):
        a = make_offer("a", "80", original_price=Money(amount="120", currency="USD"))
        b = make_offer("b", "100", identity=a.identity.model_copy(update={"size":"L"}))
        card = ComparisonCatalog([a, b], make_fx(), NOW).search()[0]
        self.assertEqual(card.channel_quotes["a"].available_sizes, ["M"])
        self.assertEqual(card.channel_quotes["b"].available_sizes, ["L"])
        self.assertEqual(card.channel_quotes["a"].discount_pct, 33)
        self.assertIsNone(card.channel_quotes["b"].discount_pct)
        self.assertIsNone(card.channel_quotes["b"].reference_original_price)
        self.assertNotEqual(card.channel_quotes["a"].reference_variant_id,
                            card.channel_quotes["b"].reference_variant_id)
