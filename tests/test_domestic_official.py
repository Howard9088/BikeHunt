"""Domestic official quotes must not invent import fees or bypass freshness."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from app.catalog.models import Evidence, FxSnapshot, Money, Offer, ProductIdentity
from app.catalog.service import ComparisonCatalog, compare_offer
from app.landed import estimate_landed_cost, is_domestic_official_offer

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)


def offer(**updates):
    values = dict(
        offer_id="domestic", source_code="decathlon_cn", source_name="Decathlon China",
        identity=ProductIdentity(brand="Test", model="Jersey", mpn="TEST-JERSEY", size="M"),
        name="Test cycling jersey", url="https://www.decathlon.com.cn/p/test",
        sales_region="中国大陆 CNY 报价", price=Money(amount="500", currency="CNY"),
        stock="in_stock", fetched_at=NOW)
    values.update(updates)
    return Offer(**values)


def fx():
    return FxSnapshot(snapshot_id="test-domestic", rates={"CNY": Decimal(1), "USD": Decimal(7)})


def overseas(**updates):
    values = dict(offer_id="overseas", source_code="foreign",
                  url="https://example.org/jersey", sales_region="Overseas",
                  price=Money(amount="10", currency="USD"))
    values.update(updates)
    return offer(**values)


def detail(rows):
    catalog = ComparisonCatalog(rows, fx(), NOW)
    return catalog, catalog.compare(next(iter(catalog.families)))


class DomesticOfficialTests(unittest.TestCase):
    def test_predicate_requires_all_explicit_mainland_fields(self):
        self.assertTrue(is_domestic_official_offer(offer()))
        for change in [
            {"source_code": "foreign"}, {"sales_region": ""},
            {"sales_region": "Overseas"}, {"price": Money(amount="500", currency="USD")},
            {"url": "https://www.decathlon.com.cn.evil.example/p/test"},
            {"url": "https://www.decathlon.com.cn@evil.example/p/test"},
            {"url": "https://evil.example@www.decathlon.com.cn/p/test"},
            {"url": "http://www.decathlon.com.cn/p/test"},
            {"url": "https://www.decathlon.com.cn:8443/p/test"},
            {"url": "https://[invalid/p/test"},
        ]:
            with self.subTest(change=change):
                self.assertFalse(is_domestic_official_offer(offer(**change)))

    def test_domestic_unknown_fees_are_not_fabricated_zeros(self):
        result = estimate_landed_cost(offer(), fx(), NOW)
        self.assertEqual([x.key for x in result.components], ["product", "shipping"])
        self.assertEqual(result.components[0].cny, Decimal("500.00"))
        self.assertIsNone(result.components[1].cny)
        self.assertIsNone(result.components[1].original)
        self.assertEqual(result.components[1].status, "unknown")
        self.assertEqual(result.known_subtotal_cny, Decimal("500.00"))
        self.assertEqual(result.scenarios, [])
        self.assertIsNone(result.quoted_total_cny)
        self.assertFalse(result.complete)
        self.assertFalse(any("进口" in x or "清关" in x for x in result.missing))

    def test_domestic_explicit_shipping_preserved_without_claiming_checkout_total(self):
        result = estimate_landed_cost(offer(shipping=Money(amount="12", currency="CNY")), fx(), NOW)
        self.assertEqual(result.components[1].cny, Decimal("12.00"))
        self.assertEqual(result.known_subtotal_cny, Decimal("512.00"))
        self.assertIsNone(result.quoted_total_cny)
        self.assertFalse(result.complete)

    def test_unknown_payment_and_delivery_remain_blockers(self):
        row = compare_offer(offer(), fx(), NOW)
        self.assertFalse(row.eligible)
        self.assertIsNone(row.tax_cny)
        self.assertIsNone(row.total_cny)
        self.assertIn("银行卡支付条件待核实", row.reasons)
        self.assertIn("境内配送待核实", row.reasons)
        self.assertFalse(any("税费" in x or "进口" in x or "清关" in x for x in row.reasons))

    def test_foreign_cny_keeps_import_components(self):
        row = overseas(price=Money(amount="500", currency="CNY"))
        self.assertFalse(is_domestic_official_offer(row))
        result = estimate_landed_cost(row, fx(), NOW)
        self.assertEqual([x.key for x in result.components], ["product", "shipping", "tax", "clearance"])

    def test_fresh_domestic_quote_precedes_cheaper_overseas_same_variant(self):
        catalog, comparison = detail([overseas(), offer()])
        self.assertEqual([x.offer.offer_id for x in comparison.offers], ["domestic", "overseas"])
        self.assertIsNone(comparison.recommended_offer_id)
        card = catalog.search()[0]
        self.assertEqual(card.reference_offer_id, "domestic")
        self.assertEqual(card.reference_cny, Decimal("500.00"))
        self.assertIsNone(card.recommended_total_cny)

    def test_unavailable_domestic_never_overrides_fresh_overseas(self):
        for change in [
            {"fetched_at": NOW - timedelta(hours=2)},
            {"fetched_at": NOW - timedelta(days=2)},
            {"fetched_at": NOW + timedelta(minutes=1)},
            {"fetched_at": None}, {"collection_state": "retained"},
            {"stock": "out_of_stock"}, {"stock": "unknown"},
            {"price_valid_until": "2026-10-15"}, {"price_valid_until": "invalid"},
        ]:
            with self.subTest(change=change):
                catalog, comparison = detail([offer(**change), overseas()])
                self.assertEqual(comparison.offers[0].offer.offer_id, "overseas")
                self.assertEqual(catalog.search()[0].reference_offer_id, "overseas")
                self.assertFalse(next(x for x in comparison.offers if x.offer.offer_id == "domestic").eligible)

    def test_domestic_evidence_freshness_still_checked(self):
        old = Evidence(status="yes", url="https://www.decathlon.com.cn/policy",
                       checked_at=NOW - timedelta(days=31))
        row = compare_offer(offer(shipping_to_china=old, china_issued_card=old), fx(), NOW)
        self.assertIn("境内配送核实记录已过期", row.reasons)
        self.assertIn("中国发行信用卡核实记录已过期", row.reasons)
        self.assertFalse(row.eligible)

    def test_domestic_priority_never_merges_different_sizes(self):
        large = overseas(identity=offer().identity.model_copy(update={"size": "L"}))
        catalog, comparison = detail([offer(), large])
        self.assertEqual(len(comparison.variants), 2)
        self.assertEqual(len(comparison.offers), 1)


if __name__ == "__main__":
    unittest.main()
