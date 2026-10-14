"""独立 Mock 验收：python tests/test_catalog.py。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError

from app.catalog.models import Evidence, FxSnapshot, Money, Offer, ProductIdentity
from app.catalog.service import ComparisonCatalog, compare_offer, same_variant
from app.catalog.storage import OfferRepository, atomic_json
from app.fx import FxProvider, snapshot

NOW = datetime.now(timezone.utc)


def make_offer(code: str = "a", price: str = "100", currency: str = "USD", **updates) -> Offer:
    """Mock 数据仅用于临时测试，永不写入生产目录。"""
    verified = Evidence(status="yes", url="https://example.org/policy", checked_at=NOW)
    values = dict(offer_id=code, source_code=code, source_name=code,
                  identity=ProductIdentity(brand="Mock", model="Jersey", mpn="J-001_BLACK", size="M", color="BLACK"),
                  name="Mock Jersey", url=f"https://example.org/{code}",
                  price=Money(amount=price, currency=currency),
                  shipping=Money(amount="10", currency=currency),
                  tax=Money(amount="0", currency="CNY"), stock="in_stock",
                  shipping_to_china=verified, china_issued_card=verified, fetched_at=NOW)
    values.update(updates)
    return Offer(**values)


def make_fx(**updates) -> FxSnapshot:
    values = dict(snapshot_id="test-fx", rate_date=NOW.date().isoformat(), fetched_at=NOW,
                  rates={"CNY": Decimal(1), "USD": Decimal(7), "EUR": Decimal(8)}, stale=False)
    values.update(updates)
    return FxSnapshot(**values)


class CatalogTests(unittest.TestCase):
    def test_cross_currency_total_ranking_uses_one_snapshot(self):
        a = make_offer("usd", "100", "USD")
        b = make_offer("eur", "70", "EUR", shipping=Money(amount="5", currency="EUR"))
        store = ComparisonCatalog([a, b], make_fx(), NOW)
        card = store.search()[0]
        detail = store.compare(card.product_id)
        self.assertEqual([x.total_cny for x in detail.offers], [Decimal("600.00"), Decimal("770.00")])
        self.assertEqual(detail.recommended_offer_id, "eur")
        self.assertEqual({x.fx_snapshot_id for x in detail.offers}, {"test-fx"})

    def test_missing_cost_is_not_zero_and_never_recommended(self):
        row = compare_offer(make_offer(shipping=None), make_fx(), NOW)
        self.assertIsNone(row.total_cny)
        self.assertFalse(row.eligible)
        self.assertIn("中国运费待确认", row.reasons)

    def test_explicit_zero_cost_is_valid(self):
        zero = Money(amount="0", currency="CNY")
        row = compare_offer(make_offer(shipping=zero, tax=zero), make_fx(), NOW)
        self.assertEqual(row.total_cny, Decimal("700.00"))
        self.assertTrue(row.eligible)

    def test_larger_shipping_can_reverse_product_price_order(self):
        a = make_offer("cheap", "10", shipping=Money(amount="100", currency="USD"))
        b = make_offer("expensive", "30", shipping=Money(amount="0", currency="USD"))
        store = ComparisonCatalog([a, b], make_fx(), NOW)
        self.assertEqual(store.compare(store.search()[0].product_id).recommended_offer_id, "expensive")

    def test_unknown_delivery_card_stock_and_stale_price_block(self):
        for update in [dict(shipping_to_china=Evidence()), dict(china_issued_card=Evidence()),
                       dict(stock="unknown"), dict(stock="out_of_stock"),
                       dict(fetched_at=NOW-timedelta(days=2)), dict(fetched_at=None),
                       dict(fetched_at=NOW+timedelta(minutes=1)),
                       dict(price_valid_until=(NOW-timedelta(days=1)).date().isoformat())]:
            with self.subTest(update=update):
                self.assertFalse(compare_offer(make_offer(**update), make_fx(), NOW).eligible)

    def test_old_verification_blocks_recommendation(self):
        old = Evidence(status="yes", url="https://example.org", checked_at=NOW-timedelta(days=31))
        row = compare_offer(make_offer(china_issued_card=old), make_fx(), NOW)
        self.assertIn("中国发行信用卡核实记录已过期", row.reasons)

    def test_missing_currency_and_stale_fx_degrade(self):
        for fx in [make_fx(stale=True), make_fx(rates={"CNY": Decimal(1)})]:
            self.assertFalse(compare_offer(make_offer(), fx, NOW).eligible)
        with self.assertRaises(ValidationError):
            make_fx(rates={"USD": Decimal("NaN")})

    def test_title_similarity_does_not_merge_unidentified_products(self):
        identity = ProductIdentity(brand="Mock", model="Same title")
        self.assertFalse(same_variant(make_offer("a", identity=identity), make_offer("b", identity=identity)))

    def test_variants_are_isolated(self):
        a = make_offer()
        for updates in [dict(size="L"), dict(color="RED"), dict(year="2025")]:
            other = a.identity.model_copy(update=updates)
            original = a.identity.model_copy(update={"year":"2024"}) if "year" in updates else a.identity
            self.assertFalse(same_variant(a.model_copy(update={"identity":original}),
                                          make_offer("b", identity=other)))

    def test_same_color_separate_sizes_share_card_but_not_quotes(self):
        a = make_offer()
        b = make_offer("b", identity=a.identity.model_copy(update={"size":"L"}))
        store = ComparisonCatalog([a, b], make_fx(), NOW)
        self.assertEqual(len(store.search()), 1)
        detail = store.compare(store.search()[0].product_id)
        self.assertEqual(len(detail.variants), 2)
        self.assertEqual(len(detail.offers), 1)
        other = store.compare(detail.product_id, detail.variants[1].variant_id)
        self.assertNotEqual(detail.identity.size, other.identity.size)

    def test_different_gtins_never_merge_even_if_mpn_matches(self):
        a = make_offer(identity=ProductIdentity(brand="Mock", model="X", mpn="same", gtin="4006381333931"))
        b = make_offer("b", identity=ProductIdentity(brand="Mock", model="X", mpn="same", gtin="9780306406157"))
        self.assertFalse(same_variant(a, b))

    def test_invalid_numeric_data_is_rejected(self):
        for value in ["NaN", "Infinity", "-1", "not-price"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Money(amount=value, currency="USD")
        with self.assertRaises(ValidationError):
            ProductIdentity(brand="Mock", model="X", gtin="1234567890123")
        with self.assertRaises(ValidationError):
            Evidence(status="yes")

    def test_unknown_spec_not_merged_with_known_size(self):
        a = make_offer()
        b = make_offer("b", identity=a.identity.model_copy(update={"size":None}))
        self.assertFalse(same_variant(a, b))

    def test_bad_source_isolated_and_failed_refresh_preserves_good_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            atomic_json(data/"sources.json", [])
            repository = OfferRepository(data)
            repository.save("a", [make_offer()], NOW, [])
            before = (data/"offers/a.json").read_bytes()
            repository.save("a", [], NOW, [{"error":"network"}])
            (data/"offers/broken.json").write_text("{bad", encoding="utf-8")
            self.assertEqual((data/"offers/a.json").read_bytes(), before)
            self.assertEqual([row.offer_id for row in repository.load()], ["a"])

    def test_price_query_not_found(self):
        store = ComparisonCatalog([make_offer()], make_fx(), NOW)
        self.assertEqual(store.search("missing"), [])
        with self.assertRaises(KeyError):
            store.compare("missing")

    def test_fx_failure_uses_explicit_stale_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"fx.json"
            atomic_json(path, {"rates":{"USD":"7"},"fetched_at":NOW.isoformat(),"rate_date":NOW.date().isoformat()})
            provider = FxProvider(path)
            with patch.object(provider, "_fetch", side_effect=OSError("offline")) as request, patch("app.fx.time.sleep"):
                result = provider.get(force=True)
            self.assertTrue(result.stale)
            self.assertEqual(result.rates["USD"], Decimal(7))
            self.assertEqual(request.call_count, 3)

    def test_daily_fx_validity_is_separate_from_hourly_refresh(self):
        payload = {"rates": {"USD": "7"}, "fetched_at": (NOW-timedelta(hours=2)).isoformat(),
                   "rate_date": NOW.date().isoformat()}
        self.assertFalse(snapshot(payload).stale)
        self.assertTrue(snapshot({**payload, "fetched_at": (NOW-timedelta(hours=25)).isoformat()}).stale)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"fx.json"
            atomic_json(path, payload)
            provider = FxProvider(path)
            refreshed = {**payload, "fetched_at": NOW.isoformat()}
            with patch.object(provider, "_fetch", return_value=refreshed) as request:
                result = provider.get()
            request.assert_called_once()
            self.assertFalse(result.stale)
            self.assertEqual(result.rate_date, payload["rate_date"])
            atomic_json(path, payload)
            with patch.object(provider, "_fetch", side_effect=OSError("offline")), patch("app.fx.time.sleep"):
                fallback = provider.get()
            self.assertTrue(fallback.stale)
            self.assertEqual(fallback.fetched_at.isoformat(), payload["fetched_at"])

    def test_corrupted_or_future_fx_never_marked_fresh(self):
        self.assertTrue(snapshot({"rates":{"USD":"NaN"}}).stale)
        self.assertTrue(snapshot({"rate_date":(NOW+timedelta(days=3)).date().isoformat(),
                                  "fetched_at":NOW.isoformat(), "rates":{"USD":"7"}}).stale)


if __name__ == "__main__":
    unittest.main(verbosity=2)

