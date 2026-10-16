"""Navigation-only classification of the reviewed 232-product snapshot."""
from __future__ import annotations

import json
import unittest
from collections import Counter
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app.browse_taxonomy import (
    CATEGORY_GROUPS, BrowseClassification, browse_classification, canonical_product_url,
)
from app.catalog.models import FxSnapshot, Money, Offer, ProductIdentity
from app.catalog.service import ComparisonCatalog
from app.fit import FitGuideService, ShopperProfile
from app.localization import CATEGORIES, category_of

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_GROUPS = [
    {"code": "road_equipment", "name": "自行车"},
    {"code": "clothing", "name": "骑行服饰"},
    {"code": "cleat_shoes", "name": "锁鞋"},
    {"code": "helmets", "name": "头盔"},
    {"code": "other", "name": "配件与周边"},
]
EXPECTED_COUNTS = {"road_equipment": 0, "clothing": 150, "helmets": 24,
                   "cleat_shoes": 1, "other": 57}
REVIEWED_FIZIK_IDS = {'5ad5212be3060e67e469', '4d9d83be3fc1b1c269b2', '278398453a8bc7f987bd', '1b69bc0c93d723bbfaa4', '6dcd80d8f81aff55fe4d', '513016c2f137ed7c78bb', '721a76cb87222c272cc3'}
ADDITIONAL_FIZIK_IDS = {'78acc3eaca8dfe404153', '4a4c176b889bac22ff99', '26c6e68e81cf6784e4f2', 'b23964d45d093564b80f'}
CLASSIFIED_COUNTS = {**EXPECTED_COUNTS, "cleat_shoes": 8, "other": 50}
FLAT_IDS = {"4d2ca7ada71ec8f59f8e", "9a07bf563ca56d45df39", "e15de842c81699d8f2ba",
            "605372f654b93c9fd105", "d184f4dc651ca9dcd9c1", "a2c3d6e5806b099fe272",
            "d16dab0e7fd9c64d5a34"}
UNRESOLVED_FOOTWEAR_IDS = {
    "4ebfe1967c462b483c23", "513016c2f137ed7c78bb", "5ad5212be3060e67e469",
    "f6a4ed47a7f00945317a", "72a6789fb4c602b77c92", "6dcd80d8f81aff55fe4d",
    "1b69bc0c93d723bbfaa4", "4d9d83be3fc1b1c269b2", "278398453a8bc7f987bd",
    "721a76cb87222c272cc3",
}
UNRESOLVED_FOOTWEAR_IDS -= REVIEWED_FIZIK_IDS


def unknown_offer(name: str, **changes) -> Offer:
    values = {"offer_id": "unreviewed", "source_code": "fizik", "source_name": "Fixture",
              "identity": ProductIdentity(brand="Fizik", model=name), "name": name,
              "url": "https://www.fizik.com/en-us/products/shoes-unreviewed",
              "price": Money(amount="100", currency="USD")}
    values.update(changes)
    return Offer(**values)


class BrowseTaxonomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = json.loads((ROOT / "data/browse-taxonomy.json").read_text(encoding="utf-8"))
        cls.all_review_rows = {row["product_id"]: row for row in cls.review["products"]}
        # Scheduled collectors may change data/offers. Exact historical counts
        # belong to this frozen audit fixture, never today's merchant inventory.
        cls.fixture = json.loads((ROOT / "tests/fixtures/browse-catalog-2026-10-15.json")
                                 .read_text(encoding="utf-8"))
        cls.rows = {key: cls.all_review_rows[key] for key in cls.fixture["expected_product_groups"]}
        cls.now = datetime.fromisoformat(cls.fixture["snapshot_generated_at"])
        cls.offers = [Offer.model_validate(row) for row in cls.fixture["offers"]]
        cls.original_offers = [offer.model_dump(mode="json") for offer in cls.offers]
        cls.fx = FxSnapshot.model_validate(cls.fixture["fx"])
        cls.catalog = ComparisonCatalog(cls.offers, cls.fx, cls.now)
        cls.cards = cls.catalog.search()
        cls.by_id = {card.product_id: card for card in cls.cards}

    def test_exact_five_groups_are_separate_from_legacy_categories(self):
        self.assertEqual(CATEGORY_GROUPS, EXPECTED_GROUPS)
        self.assertEqual([row["code"] for row in CATEGORIES],
                         ["all", "jerseys", "bibs", "jackets", "shoes", "helmets", "accessories"])
        self.assertNotIn("all", {row["code"] for row in CATEGORY_GROUPS})
        # Unrelated historical matching remains byte-for-byte behaviorally compatible.
        self.assertEqual(category_of("TROPPO SHOECOVER"), "shoes")
        self.assertEqual(category_of("RBH Helmet Keyring"), "helmets")
        self.assertEqual(category_of("Future QUOC accessory"), "shoes")

    def test_complete_232_product_partition_and_stable_ids(self):
        self.assertEqual(self.fixture["snapshot_generated_at"], "2026-10-15T06:10:51.416607+00:00")
        self.assertEqual(self.fixture["audit_snapshot_sha256"], self.review["snapshot_sha256"])
        self.assertEqual(self.fixture["expected_product_count"], 232)
        self.assertEqual(self.fixture["expected_group_counts"], EXPECTED_COUNTS)
        self.assertEqual(len(self.rows), 232)
        self.assertEqual(len(self.review["products"]), len(self.all_review_rows), "No duplicate reviews")
        self.assertTrue(all(row["category_group"] == "other" for row in self.rows.values()
                            if "Bicycle accessory or part" in row["reason"]))
        self.assertEqual(sum("Bicycle accessory or part" in row["reason"]
                             for row in self.rows.values()), 14)
        self.assertEqual(len(self.rows), 232, "No duplicate reviewed IDs")
        self.assertEqual(len(self.cards), 232)
        self.assertEqual(set(self.by_id), set(self.rows), "No product added, lost, or rekeyed")
        self.assertEqual(set(self.fixture["expected_product_groups"]), set(self.rows))
        self.assertEqual(Counter(card.category_group for card in self.cards), Counter(CLASSIFIED_COUNTS))
        self.assertEqual(Counter(row["category_group"] for row in self.rows.values()), Counter(CLASSIFIED_COUNTS))
        self.assertEqual(self.review["expected_group_counts"], EXPECTED_COUNTS)
        for product_id, row in self.rows.items():
            with self.subTest(product_id=product_id):
                card = self.by_id[product_id]
                self.assertEqual((card.category, card.category_group),
                                 (row["category"], row["category_group"]))
                expected = self.fixture["expected_product_groups"][product_id]
                self.assertEqual(card.source_codes, expected["source_codes"])
                self.assertTrue(set(card.source_codes).issubset(row["source_codes"]))
                self.assertEqual(card.variant_count, 1)
                self.assertEqual(len(self.catalog.families[product_id]), 1)
                for variant in self.catalog.families[product_id]:
                    self.assertEqual(self.catalog._variant_id(variant), expected["variant_id"])
                    self.assertEqual(sorted(offer.offer_id for offer in variant), expected["offer_ids"])
                    detail = self.catalog.compare(product_id, self.catalog._variant_id(variant))
                    self.assertEqual((detail.category, detail.category_group),
                                     (card.category, card.category_group))

    def test_only_ten_reviewed_leaf_corrections(self):
        changed = {card.product_id for card in self.cards if card.category != category_of(card.name)}
        expected = {row["product_id"] for row in self.rows.values()
                    if row["category_group"] == "helmets" and row["source_codes"] in (["kask"], ["fizik"])}
        expected.update({"18f085d4eca709d679e4", "f49583aa2defe25f1b72"})
        expected.update(REVIEWED_FIZIK_IDS)
        self.assertEqual(changed, expected)
        self.assertEqual(len(changed), 17)
        self.assertEqual(self.by_id["f49583aa2defe25f1b72"].category_group, "clothing")
        self.assertEqual(self.by_id["18f085d4eca709d679e4"].category_group, "other")
        self.assertEqual(self.by_id["a51786b59bf7bced4008"].category, "helmets")

    def test_flat_ambiguous_shoes_and_other_boundaries_remain_conservative(self):
        for product_id in FLAT_IDS | UNRESOLVED_FOOTWEAR_IDS:
            with self.subTest(product_id=product_id):
                self.assertEqual(self.by_id[product_id].category_group, "other")
                self.assertEqual(self.by_id[product_id].category, "accessories")
        cleats = [card.product_id for card in self.cards if card.category_group == "cleat_shoes"]
        self.assertEqual(set(cleats), {"d64fc007e38c0435a592"} | REVIEWED_FIZIK_IDS)
        for card in self.cards:
            if card.name == "HYDRO SWIMMING CAP" or card.name.startswith("DRIIVE Pro"):
                self.assertEqual(card.category_group, "other")
        self.assertEqual(self.by_id["c291a77f8b5ab6857285"].category_group, "other")

    def test_exact_fizik_reviews_cover_live_powerstrap_and_preserve_identity_guards(self):
        self.assertEqual(len(REVIEWED_FIZIK_IDS | ADDITIONAL_FIZIK_IDS), 11)
        for product_id in REVIEWED_FIZIK_IDS | ADDITIONAL_FIZIK_IDS:
            row = self.all_review_rows[product_id]
            offer = unknown_offer(row["name"], url=row["source_url"])
            before = offer.model_dump(mode="json")
            with self.subTest(product_id=product_id):
                self.assertFalse(row["needs_type_review"])
                self.assertIn("Clipless", row["reason"])
                self.assertEqual(browse_classification(product_id, [offer]),
                                 BrowseClassification("shoes", "cleat_shoes"))
                alternate_size = offer.model_copy(update={"url": row["type_evidence_url"] + "?variant=another-size"})
                self.assertEqual(browse_classification(product_id, [alternate_size]).category_group, "cleat_shoes")
                for changed_id, changed in [
                    ("unreviewed-id", offer),
                    (product_id, offer.model_copy(update={"source_code": "other-source"})),
                    (product_id, offer.model_copy(update={"url": "https://www.fizik.com/en-us/products/unreviewed-flat"})),
                ]:
                    self.assertNotEqual(browse_classification(changed_id, [changed]).category_group, "cleat_shoes")
                self.assertEqual(offer.model_dump(mode="json"), before)
        powerstrap = self.all_review_rows["78acc3eaca8dfe404153"]
        self.assertIn("tpr5psre17410", powerstrap["source_url"])
        self.assertIn("50672334995798", powerstrap["source_url"])

    def test_french_garments_and_reviewed_clothing_sets_are_preserved(self):
        groupama = [card for card in self.cards if "groupama" in card.source_codes]
        self.assertEqual(len(groupama), 5)
        self.assertTrue(all(card.category_group == "clothing" for card in groupama))
        self.assertTrue(all(card.category == "accessories" for card in groupama))
        for product_id in ["d641981e4dd1fb08f1e3", "72012857fe1d6b21d423"]:
            self.assertEqual(self.by_id[product_id].category_group, "clothing")
            self.assertEqual(self.by_id[product_id].category, "accessories")
        # Broad apparel navigation does not grant garment sizing to accessories.
        guide = FitGuideService(ROOT)
        for product_id in ["f49583aa2defe25f1b72", "d641981e4dd1fb08f1e3"]:
            self.assertEqual(guide.assess(self.catalog.compare(product_id), ShopperProfile(), self.now).state,
                             "not_applicable")

    def test_search_intersects_group_leaf_and_query_using_reviewed_leaf(self):
        for group, count in CLASSIFIED_COUNTS.items():
            with self.subTest(group=group):
                self.assertEqual(len(self.catalog.search(category_group=group)), count)
        self.assertEqual([card.product_id for card in self.catalog.search("Nirvana", "helmets", "helmets")],
                         ["1529bbd706b0364a37a4"])
        self.assertEqual(self.catalog.search("Helmet Keyring", "helmets", "helmets"), [])
        self.assertEqual(self.catalog.search("Nirvana", "accessories", "helmets"), [])
        self.assertEqual(self.catalog.search(category="helmets", category_group="clothing"), [])
        self.assertEqual(self.catalog.search(category_group="unknown"), [])
        self.assertEqual(len(self.catalog.search(category_group="")), 232)
        self.assertEqual(len(self.catalog.search(category_group=None)), 232)

    def test_review_requires_product_id_source_and_canonical_product_url(self):
        product_id = "1529bbd706b0364a37a4"
        original = self.catalog.families[product_id][0][0]
        self.assertEqual(browse_classification(product_id, [original]).category_group, "helmets")
        for changed_id, changed in [
            ("unreviewed-id", original),
            (product_id, original.model_copy(update={"source_code": "unreviewed-source"})),
            (product_id, original.model_copy(update={"url": "https://www.kask.com/en-it/unreviewed"})),
            (product_id, original.model_copy(update={"url": "https://example.org/en-it/Nirvana/CHE00109-CE-WG-465.58.html"})),
        ]:
            with self.subTest(product_id=changed_id, url=changed.url):
                self.assertEqual(browse_classification(changed_id, [changed]),
                                 BrowseClassification("accessories", "other"))
        self.assertEqual(canonical_product_url("https://example.org/p?variant=1#size"),
                         canonical_product_url("https://example.org/p/?variant=2"))
        self.assertNotEqual(canonical_product_url("https://example.org/product?id=1"),
                            canonical_product_url("https://example.org/product?id=2"))

    def test_unknown_fallback_never_infers_gear_or_cleats_from_brand_or_url(self):
        for name in ["Future Fizik", "ERGOLACE 2", "Fizik Cycling Shoes", "New FLAT shoes",
                     "Future QUOC accessory", "KASK Nirvana", "Trek team merchandise",
                     "Specialized Team Bundle", "Canyon bike", "Colnago gift", "Bicycle Wheelset",
                     "Chainring", "Frame Bag", "Cycling Bottle", "Saddle"]:
            with self.subTest(name=name):
                result = browse_classification("unreviewed", [unknown_offer(name)])
                self.assertEqual(result, BrowseClassification("accessories", "other"))
        self.assertEqual(browse_classification("unknown", []), BrowseClassification("accessories", "other"))
        for name, category, group in [
            ("Team Jersey", "jerseys", "clothing"),
            ("Team Bib Shorts", "bibs", "clothing"),
            ("Team Jacket", "jackets", "clothing"),
            ("Stamp Hoodie", "accessories", "clothing"),
            ("Team Sweatshirt", "accessories", "clothing"),
            ("Hoodie Keychain", "accessories", "other"),
            ("Cycling Helmet", "helmets", "helmets"),
            ("Helmet Keyring", "accessories", "other"),
            ("Helmet Bag", "accessories", "other"),
            ("Rain Shoecover", "accessories", "clothing"),
        ]:
            with self.subTest(name=name):
                self.assertEqual(browse_classification("unknown", [unknown_offer(name)]),
                                 BrowseClassification(category, group))

    def test_classification_does_not_change_offer_identity_prices_stock_or_tax(self):
        def legacy(product_id, offers, *, name=None):
            return BrowseClassification(category_of(name or next(iter(offers)).name), "other")

        with patch("app.catalog.service.browse_classification", side_effect=legacy):
            original = ComparisonCatalog(self.offers, self.fx, self.now)
            cards = original.search()
            details = {card.product_id: original.compare(card.product_id).model_dump(mode="json")
                       for card in cards}
        self.assertEqual(set(original.families), set(self.catalog.families))
        for before, after in zip(cards, self.cards):
            with self.subTest(product_id=after.product_id):
                baseline = before.model_dump(mode="json")
                actual = after.model_dump(mode="json")
                for key in ["category", "category_group"]:
                    baseline.pop(key)
                    actual.pop(key)
                    # Last-known channel cards now remain present after one hour.
                    for quote in baseline.get("channel_quotes", {}).values():
                        quote.pop(key, None)
                    for quote in actual.get("channel_quotes", {}).values():
                        quote.pop(key, None)
                self.assertEqual(actual, baseline)
                baseline = details[after.product_id]
                actual = self.catalog.compare(after.product_id).model_dump(mode="json")
                for key in ["category", "category_group"]:
                    baseline.pop(key)
                    actual.pop(key)
                self.assertEqual(actual, baseline)
        self.assertEqual([offer.model_dump(mode="json") for offer in self.offers], self.original_offers)


if __name__ == "__main__":
    unittest.main()
