"""Discount selection stays on one merchant offer and one exact variant."""
from __future__ import annotations

import copy
import unittest
from datetime import timedelta
from decimal import Decimal

from app.catalog.models import Money
from app.catalog.service import ComparisonCatalog
from app.publication import digest, semantic_projection
from test_catalog import NOW, make_fx, make_offer


class FeaturedDealsTests(unittest.TestCase):
    def discounted(self, code='sale', **changes):
        return make_offer(code, '90', original_price=Money(amount='120', currency='USD'), **changes)

    def test_fresh_discount_wins_over_cheaper_nondiscount_and_recommended_variant(self):
        cheap = make_offer('cheapest', '50')
        sale = self.discounted(identity=cheap.identity.model_copy(update={'size': 'L'}))
        catalog = ComparisonCatalog([cheap, sale], make_fx(), NOW)
        card = catalog.search()[0]
        self.assertEqual(card.reference_offer_id, 'sale')
        self.assertEqual(card.reference_price, sale.price)
        self.assertEqual(card.reference_original_price, sale.original_price)
        self.assertEqual(card.reference_cny, Decimal('630.00'))
        self.assertEqual(card.reference_size, 'L')
        self.assertEqual(card.reference_color, 'BLACK')
        detail = catalog.compare(card.product_id, card.reference_variant_id)
        self.assertEqual(detail.identity.size, 'L')
        self.assertEqual(detail.offers[0].offer.offer_id, card.reference_offer_id)
        self.assertEqual(card.discount_pct, 25)

    def test_no_discount_is_inferred_from_other_quotes_or_historical_decreases(self):
        before, after = make_offer('a', '120'), make_offer('b', '90')
        catalog = ComparisonCatalog([before, after], make_fx(), NOW)
        self.assertFalse(any(catalog.discounted(offer) for offer in [before, after]))
        self.assertIsNone(catalog.search()[0].reference_original_price)

    def test_only_current_fresh_in_stock_live_same_currency_positive_discounts(self):
        good = self.discounted()
        for changes in [
            {'original_price': None}, {'original_price': Money(amount='90', currency='USD')},
            {'original_price': Money(amount='80', currency='USD')},
            {'original_price': Money(amount='120', currency='EUR')},
            {'price': Money(amount='0', currency='USD')}, {'stock': 'unknown'}, {'stock': 'out_of_stock'},
            {'collection_state': 'retained'}, {'data_kind': 'legacy_cache'}, {'fetched_at': None},
            {'fetched_at': NOW-timedelta(hours=24, microseconds=1)}, {'fetched_at': NOW+timedelta(seconds=1)},
            {'price_valid_until': (NOW-timedelta(days=1)).date().isoformat()},
            {'price_valid_until': '2026-02-30'}, {'price_valid_until': 'invalid'},
        ]:
            with self.subTest(changes=changes):
                offer = good.model_copy(update=changes)
                catalog = ComparisonCatalog([offer], make_fx(), NOW)
                self.assertFalse(catalog.discounted(offer))
                self.assertEqual(len(catalog.search()), 1, 'Brand/team catalog keeps reference-only cards')
        catalog = ComparisonCatalog([good], make_fx(), NOW)
        self.assertTrue(catalog.discounted(good))
        self.assertTrue(catalog.discounted(good.model_copy(update={'fetched_at': NOW-timedelta(hours=1)})))
        self.assertTrue(catalog.discounted(good.model_copy(update={'fetched_at': NOW-timedelta(hours=24)})))
        self.assertTrue(catalog.discounted(good.model_copy(update={'price_valid_until': NOW.date().isoformat()})))

    def test_sold_discount_in_family_does_not_turn_full_price_stock_into_a_deal(self):
        full = make_offer('current', '100')
        sold = self.discounted(stock='out_of_stock')
        catalog = ComparisonCatalog([full, sold], make_fx(), NOW)
        card = catalog.search()[0]
        self.assertEqual(card.reference_offer_id, 'current')
        self.assertIsNone(card.reference_original_price)
        self.assertEqual(card.stock_state, 'in_stock')

    def test_tiny_discount_and_price_validity_are_preserved_without_invented_promo(self):
        tiny = make_offer('tiny', '99.99', original_price=Money(amount='100', currency='USD'),
                          price_valid_until=NOW.date().isoformat())
        catalog = ComparisonCatalog([tiny], make_fx(), NOW)
        card = catalog.search()[0]
        self.assertTrue(catalog.discounted(tiny))
        self.assertEqual(card.discount_pct, 0)
        self.assertEqual(card.reference_price_valid_until, NOW.date().isoformat())
        self.assertFalse(any('promotion' in field or 'countdown' in field for field in type(card).model_fields))

    def test_discount_facts_remain_semantic_but_observation_time_does_not(self):
        card = ComparisonCatalog([self.discounted()], make_fx(), NOW).search()[0].model_dump(mode='json')
        payload = {'catalog': {'items': [card], 'fx': {}}, 'updates': {'fx': {}}, 'details': {}}
        baseline = digest(semantic_projection(payload))
        for key, value in [('reference_original_price', {'amount': '150', 'currency': 'USD'}),
                           ('reference_variant_id', 'another-variant'), ('reference_size', 'XL'),
                           ('reference_color', 'BLUE'), ('reference_price_valid_until', '2000-01-01'),
                           ('reference_data_kind', 'legacy_cache'), ('reference_collection_state', 'retained')]:
            changed = copy.deepcopy(payload)
            changed['catalog']['items'][0][key] = value
            self.assertNotEqual(digest(semantic_projection(changed)), baseline, key)
        changed = copy.deepcopy(payload)
        changed['catalog']['items'][0]['fetched_at'] = (NOW+timedelta(minutes=5)).isoformat()
        self.assertEqual(digest(semantic_projection(changed)), baseline)


if __name__ == '__main__':
    unittest.main()
