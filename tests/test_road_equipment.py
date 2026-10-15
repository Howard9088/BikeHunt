"""Official bike research is isolated from inventory, tax and payment claims."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from app.road_equipment import read_road_references, BROWSE_CATEGORIES
from app.catalog.storage import OfferRepository
from app.catalog.service import ComparisonCatalog
from app.catalog.models import FxSnapshot
from app.landed import _clothing, load_rules

ROOT = Path(__file__).resolve().parents[1]


class RoadEquipmentTests(unittest.TestCase):
    def test_four_honest_references_and_four_official_brands(self):
        data = read_road_references(ROOT)
        self.assertEqual([b['code'] for b in data['brands']], ['trek','specialized','canyon','colnago'])
        self.assertEqual(len(data['products']), 4)
        self.assertEqual([row['category_group'] for row in data['products']],
                         ['road_equipment', 'road_equipment', 'road_equipment', 'other'])
        self.assertEqual(data['products'][-1]['id'], 'canyon-9102039')
        for row in data['products']:
            self.assertEqual(row['stock'], 'unknown')
            self.assertEqual(row['available_sizes'], [])
            self.assertIsNone(row['observed_at'])
            self.assertIsNone(row['recommended_total_cny'])
            self.assertIsNone(row['discount_deadline'])
            self.assertFalse(row['eligible'])
            self.assertGreater(row['reference_price'], row['price'])
            self.assertNotIn('fetched_at', row)
        self.assertEqual(sum(bool(p.get('image')) for p in data['products']), 3)
        for row in data['products'][1:]:
            self.assertTrue(row['image'].startswith('https://dma.canyon.com/'))
            self.assertEqual(row['image_source_page'], row['url'])
            self.assertTrue(row['image_checked_at'].startswith('2026-10-15T'))
        self.assertNotIn('trek', {p['source_code'] for p in data['products']})
        self.assertNotIn('colnago', {p['source_code'] for p in data['products']})
        self.assertIn('不接受转运地址', data['brands'][0]['note'])
        self.assertIn('不支持直接寄中国', data['brands'][1]['note'])
        self.assertIn('退货条件有冲突', data['brands'][2]['note'])

    def test_research_does_not_register_new_crawlers_or_offers(self):
        codes = {'trek','specialized','canyon','colnago'}
        offers = OfferRepository(ROOT/'data').load()
        self.assertTrue(codes.isdisjoint(o.source_code for o in offers))
        sources=json.loads((ROOT/'data/crawl_sources.json').read_text())
        # These identities have directory references only, no added collection request.
        self.assertTrue(codes.isdisjoint(row.get('code', row.get('source_code')) for row in sources))
        # Fixed FX fixture: the repository may contain the older provider-cache format.
        fixed = json.loads((ROOT/'tests/fixtures/browse-catalog-2026-10-15.json').read_text())
        catalog = ComparisonCatalog(offers, FxSnapshot.model_validate(fixed['fx']))
        reference_ids={p['id'] for p in read_road_references(ROOT)['products']}
        self.assertTrue(reference_ids.isdisjoint(c.product_id for c in catalog.search()))

    def test_references_never_receive_clothing_tax(self):
        rule = load_rules()['personal_postal_clothing']
        for row in read_road_references(ROOT)['products']:
            self.assertFalse(_clothing(row['name'], rule), row['name'])
        self.assertEqual({c['code'] for c in BROWSE_CATEGORIES}, {'all','jerseys','bibs','jackets','shoes','helmets','accessories','road_bikes','frames','bike_parts'})

    def test_fail_closed_on_false_freshness_stock_or_wrong_domain(self):
        original = read_road_references(ROOT)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'data').mkdir()
            for field, value in [('category_group','other'),('stock','in_stock'),('observed_at',original['research_checked_at']),('available_sizes',['M']),('discount_deadline','2027-01-01'),('eligible',True),('url','https://www.canyon.com.evil/en-us/')]:
                data=copy.deepcopy(original);data['products'][0][field]=value
                (root/'data/road_equipment_references.json').write_text(json.dumps(data))
                with self.assertRaises(ValueError, msg=field):read_road_references(root)

    def test_official_entry_fallback_uses_text_not_fake_logos(self):
        directory=json.loads((ROOT/'data/directories.json').read_text())
        brands=[b for b in directory['brands'] if b.get('road_reference')]
        self.assertEqual(len(brands),4)
        self.assertTrue(all(not b.get('logo_images') for b in brands))


if __name__ == '__main__':unittest.main()
