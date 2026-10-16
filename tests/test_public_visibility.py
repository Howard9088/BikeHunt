"""Reversible public hiding never edits source research or internal taxonomy."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from app.browse_taxonomy import CATEGORY_GROUPS, BrowseClassification
from app.catalog.models import ProductIdentity
from app.catalog.service import ComparisonCatalog
from app.public_visibility import (BICYCLES_PUBLIC, public_category_groups, public_categories,
    public_road_references, public_directories, public_product)
from app.road_equipment import BROWSE_CATEGORIES, read_road_references
from app.update_views import enrich_events
from test_catalog import NOW, make_fx, make_offer

PUBLIC_GROUPS = ['clothing', 'cleat_shoes', 'helmets', 'other']
MIDLOADER = 'canyon-9102039'


def offers():
    return [make_offer(code, name=name, identity=ProductIdentity(brand='Mock', model=name,
                mpn=code, color='Black', size='M')) for code, name in
            [('bike', 'Mock Road Bike'), ('frame', 'Mock Frameset'), ('bag', 'Mock Midloader Bag')]]


def classify(_product_id, rows, **_kwargs):
    code = next(iter(rows)).offer_id
    return {'bike': BrowseClassification('road_bikes', 'road_equipment'),
            'frame': BrowseClassification('frames', 'road_equipment'),
            'bag': BrowseClassification('accessories', 'other')}[code]


class PublicVisibilityTests(unittest.TestCase):
    def test_public_groups_are_four_but_internal_categories_are_preserved(self):
        original = copy.deepcopy((CATEGORY_GROUPS, BROWSE_CATEGORIES))
        self.assertFalse(BICYCLES_PUBLIC)
        self.assertEqual([row['code'] for row in public_category_groups()], PUBLIC_GROUPS)
        self.assertEqual([row['name'] for row in public_category_groups()],
                         ['骑行服饰', '锁鞋', '头盔', '配件与周边'])
        self.assertTrue({'road_bikes', 'frames'}.isdisjoint(row['code'] for row in public_categories()))
        self.assertIn('bike_parts', {row['code'] for row in public_categories()})
        self.assertEqual([row['code'] for row in CATEGORY_GROUPS], ['road_equipment'] + PUBLIC_GROUPS)
        # Mutating projected controls must not edit the retained internal taxonomy.
        public_category_groups()[0]['name'] = 'changed'
        public_categories()[0]['name'] = 'changed'
        self.assertEqual((CATEGORY_GROUPS, BROWSE_CATEGORIES), original)

    def test_either_hidden_group_or_hidden_leaf_fails_closed(self):
        for row in [{'category_group': 'road_equipment', 'category': 'accessories'},
                    {'category_group': 'other', 'category': 'road_bikes'},
                    {'category_group': 'other', 'category': 'frames'}]:
            with self.subTest(row=row):
                self.assertFalse(public_product(row))
        for category in ['accessories', 'bike_parts', 'jerseys', 'shoes', 'helmets']:
            self.assertTrue(public_product({'category': category, 'category_group': 'other'}))

    def test_only_accessory_research_and_safe_accessory_entrance_are_public(self):
        path = ROOT / 'data/road_equipment_references.json'
        raw = path.read_bytes()
        original = read_road_references(ROOT)
        visible = public_road_references(ROOT)
        self.assertEqual([row['id'] for row in visible['products']], [MIDLOADER])
        self.assertEqual([row['code'] for row in visible['brands']], ['canyon'])
        accessory = next(row for row in original['products'] if row['id'] == MIDLOADER)
        self.assertEqual(visible['products'][0], accessory)
        self.assertEqual(visible['brands'][0]['url'], accessory['url'])
        self.assertNotIn('outlet-bikes', visible['brands'][0]['url'])
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(len(read_road_references(ROOT)['products']), 4)

    def test_directory_hides_bicycle_research_but_keeps_collected_clothing_and_accessories(self):
        original = (ROOT / 'data/directories.json').read_bytes()
        result = public_directories(ROOT)
        codes = {row['code'] for row in result['brands']}
        self.assertNotIn('trek', codes)
        self.assertTrue({'specialized', 'colnago', 'canyon'}.issubset(codes))
        for code in ('specialized', 'colnago'):
            entry = next(row for row in result['brands'] if row['code'] == code)
            self.assertFalse(entry.get('road_reference'))
            self.assertIn('骑行服饰', entry['name_zh'])
            self.assertNotIn('/collections/bikes', entry['shop_url'])
            self.assertEqual(entry['source_codes'], [code])
        canyon = next(row for row in result['brands'] if row['code'] == 'canyon')
        target = public_road_references(ROOT)['products'][0]['url']
        self.assertEqual(canyon['name_zh'], 'Canyon 配件')
        self.assertEqual(canyon['reference_category_group'], 'other')
        for field in ['official_url', 'shop_url', 'shop_evidence_url']:
            self.assertEqual(canyon[field], target)
        self.assertEqual((ROOT / 'data/directories.json').read_bytes(), original)
        self.assertEqual(len(result['teams']), len(json.loads(original)['teams']))

    @patch('app.catalog.service.browse_classification', side_effect=classify)
    def test_default_catalog_keeps_internal_ids_public_catalog_rejects_them(self, _classification):
        rows = offers()
        internal = ComparisonCatalog(rows, make_fx(), NOW)
        public = ComparisonCatalog(rows, make_fx(), NOW, public_only=True)
        cards = internal.search()
        self.assertEqual(len(cards), 3)
        self.assertEqual([row.category for row in public.search()], ['accessories'])
        self.assertEqual(public.search(category_group='road_equipment'), [])
        self.assertEqual(public.search(category='frames'), [])
        self.assertEqual(public.search('Mock Road Bike'), [])
        self.assertEqual(public.hidden_offer_ids, {'bike', 'frame'})
        for card in cards:
            detail = internal.compare(card.product_id)
            if card.category in {'road_bikes', 'frames'}:
                for variant in [None, detail.variant_id]:
                    with self.assertRaises(KeyError):
                        public.compare(card.product_id, variant)
            else:
                self.assertEqual(public.compare(card.product_id).product_id, card.product_id)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(internal.search()), 3)

    @patch('app.catalog.service.browse_classification', side_effect=classify)
    def test_hidden_updates_are_removed_even_with_missing_legacy_category(self, _classification):
        rows = offers()
        public = ComparisonCatalog(rows, make_fx(), NOW, public_only=True)
        events = [{'id': i, 'offer_id': row.offer_id, 'url': row.url}
                  for i, row in enumerate(rows, 1)]
        events += [{'id': 4, 'offer_id': 'old-frame', 'url': 'https://example.org/old-frame', 'category': 'frames'},
                   {'id': 5, 'offer_id': 'old-bike', 'url': 'https://example.org/old-bike',
                    'product': {'category_group': 'road_equipment'}}]
        original = copy.deepcopy(events)
        self.assertEqual([row['offer_id'] for row in enrich_events(events, public)], ['bag'])
        self.assertEqual(len(enrich_events(events, ComparisonCatalog(rows, make_fx(), NOW))), 5)
        self.assertEqual(events, original)

    @patch('app.catalog.service.browse_classification', side_effect=classify)
    def test_api_excludes_bikes_and_returns_404_for_old_product_and_fit_ids(self, _classification):
        from fastapi import HTTPException
        from app import main
        from app.fit import ShopperProfile
        rows = offers()
        internal = ComparisonCatalog(rows, make_fx(), NOW)
        hidden = [card for card in internal.search() if card.category_group == 'road_equipment']
        with patch.object(main.repository, 'load', return_value=rows), \
             patch.object(main.fx_provider, 'get', return_value=make_fx()):
            payload = main.search_catalog(q='', category='all', category_group=None)
            self.assertEqual([row['code'] for row in payload['category_groups']], PUBLIC_GROUPS)
            self.assertEqual([row['category'] for row in payload['items']], ['accessories'])
            self.assertEqual(payload['offer_count'], 1)
            self.assertEqual(payload['source_count'], 1)
            self.assertEqual([row['id'] for row in payload['road_equipment_references']['products']], [MIDLOADER])
            for card in hidden:
                for action in [lambda: main.compare_product(card.product_id),
                               lambda: main.compare_product(card.product_id, internal.compare(card.product_id).variant_id),
                               lambda: main.assess_fit(card.product_id, ShopperProfile())]:
                    with self.assertRaises(HTTPException) as error:
                        action()
                    self.assertEqual(error.exception.status_code, 404)


if __name__ == '__main__':
    unittest.main()
