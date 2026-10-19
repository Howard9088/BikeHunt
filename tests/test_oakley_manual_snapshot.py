"""Exact manually observed Oakley US variants, never a full-size stock claim."""
import json
import unittest
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from app.catalog.models import Offer, FxSnapshot
from app.catalog.service import ComparisonCatalog
from app.browse_taxonomy import browse_classification
ROOT=Path(__file__).resolve().parents[1]
class OakleyManualSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.payload=json.loads((ROOT/'data/offers/oakley.json').read_text())
        self.rows=[Offer.model_validate(x) for x in self.payload['offers']]
        self.now=datetime.fromisoformat('2026-10-16T12:05:55+00:00')
        self.fx=FxSnapshot(snapshot_id='synthetic-test-only',rates={'USD':Decimal(7)})
    def test_exact_observations_no_invented_quantity_time_or_variant(self):
        self.assertEqual(len(self.rows),24)
        self.assertEqual(len({x.url for x in self.rows}),24)
        self.assertEqual(len({x.offer_id for x in self.rows}),24)
        self.assertEqual(self.payload['observation_window'],{'start':'2026-10-16T12:02:10Z','end':'2026-10-16T12:05:55Z'})
        for o in self.rows:
            self.assertEqual(o.name,o.identity.model)
            self.assertTrue(o.identity.size and o.identity.color)
            self.assertGreater(o.price.amount,0)
            self.assertTrue(o.image.startswith('https://assets2.oakley.com/'))
            self.assertEqual(o.price.currency,'USD')
            self.assertEqual(o.sales_region,'美国站 USD 报价')
            self.assertEqual(o.fetched_at.isoformat(),'2026-10-16T12:02:10+00:00')
            for v in [o.stock_quantity,o.identity.year,o.identity.mpn,o.identity.gtin]:self.assertIsNone(v)
            self.assertEqual(urlsplit(o.url).hostname,'www.oakley.com')
            self.assertEqual(urlsplit(o.url).query,'')
            self.assertEqual(o.shipping_to_china.status,'no')
            self.assertEqual(o.china_issued_card.status,'unknown')
            self.assertTrue(any(note.startswith('用途：') for note in o.purchase_requirements) or '/FOA' in o.url or o.url.endswith(('/FOS901803','/FOS902106')))
        self.assertEqual(Counter(o.stock for o in self.rows),{'in_stock':23,'out_of_stock':1})
        sold=next(o for o in self.rows if o.url.endswith('/FOS902123'))
        self.assertEqual((sold.identity.size,sold.identity.color,sold.stock),('L','Matte Black','out_of_stock'))
        sale=[o for o in self.rows if o.original_price]
        self.assertEqual(len(sale),1)
        self.assertTrue(sale[0].url.endswith('/FOA406782'))
        self.assertEqual((sale[0].price.amount,sale[0].original_price.amount),(Decimal(152),Decimal(190)))
    def test_categories_last_known_and_discount_expiry(self):
        for age in [timedelta(0),timedelta(days=2)]:
            c=ComparisonCatalog(self.rows,self.fx,self.now+age);cards=c.search()
            self.assertEqual(len(cards),24)
            self.assertEqual(Counter(x.category_group for x in cards),{'helmets':20,'clothing':4})
            self.assertEqual(sum(c.available(x) for x in self.rows),23)
            for card in cards:
                self.assertEqual(card.variant_count,1)
                self.assertEqual(card.source_codes,['oakley'])
                self.assertLessEqual(len(card.available_sizes),1)
                for offer in c.compare(card.product_id).offers:
                    self.assertFalse(offer.eligible)
                    self.assertIsNone(offer.total_cny)
            self.assertEqual([x.discount_pct for x in cards if x.discount_pct],[20] if not age else [])
        # Synthetic unknown observation must never imply stock.
        o=self.rows[0].model_copy(update={'stock':'unknown'})
        self.assertFalse(ComparisonCatalog([o],self.fx,self.now).available(o))
    def test_manual_source_and_strict_taxonomy_identity(self):
        reviews=json.loads((ROOT/'data/browse-taxonomy.json').read_text())['products']
        self.assertEqual(len(reviews),263)
        self.assertEqual(len({x['product_id'] for x in reviews}),263)
        self.assertEqual(sum(x['source_codes']==['oakley'] for x in reviews),24)
        source=next(x for x in json.loads((ROOT/'data/sources.json').read_text()) if x['code']=='oakley')
        self.assertEqual(source['collection_strategy'],'automatic_verified_public_variant')
        self.assertEqual(source['china_shipping']['status'],'no')
        self.assertIn('oakley',{x['code'] for x in json.loads((ROOT/'data/crawl_sources.json').read_text())})
        brand=next(x for x in json.loads((ROOT/'data/directories.json').read_text())['brands'] if x['code']=='oakley')
        self.assertEqual(brand['source_codes'],['oakley'])
        c=ComparisonCatalog(self.rows,self.fx,self.now)
        for pid,family in c.families.items():
            o=family[0][0]
            if o.url.endswith('/FOS902243'):
                self.assertEqual(browse_classification(pid,[o]).category_group,'helmets')
                self.assertEqual(browse_classification(pid,[o.model_copy(update={'source_code':'other'})]).category_group,'other')
                self.assertEqual(browse_classification(pid,[o.model_copy(update={'url':'https://www.oakley.com/en-us/product/OTHER'})]).category_group,'other')
if __name__=='__main__':unittest.main()
