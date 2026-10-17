"""Real manually selected Gobik sizes; no invented merchant IDs or auto refresh."""
import json
import re
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from app.catalog.models import Offer, FxSnapshot
from app.catalog.service import ComparisonCatalog

ROOT = Path(__file__).resolve().parents[1]
class GobikManualSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((ROOT/'data/offers/gobik.json').read_text())
        self.rows = [Offer.model_validate(x) for x in self.payload['offers']]
        self.now = max(x.fetched_at for x in self.rows)
        self.fx = FxSnapshot(snapshot_id='synthetic-test-only', rates={'EUR':Decimal('8')})

    def test_only_nineteen_observed_sizes_and_canonical_products(self):
        self.assertEqual(len(self.rows),19)
        self.assertEqual(len({x.url for x in self.rows}),19)
        self.assertEqual(len({x.offer_id for x in self.rows}),19)
        start=datetime.fromisoformat(self.payload['observation_window']['start'].replace('Z','+00:00'))
        end=datetime.fromisoformat(self.payload['observation_window']['end'].replace('Z','+00:00'))
        for row in self.rows:
            self.assertTrue(row.identity.size)
            self.assertGreater(row.stock_quantity,0)
            self.assertGreater(row.price.amount,0)
            self.assertTrue(row.image.startswith('https://gobik.com/'))
            self.assertGreaterEqual(row.fetched_at,start)
            self.assertLessEqual(row.fetched_at,end)
            self.assertEqual(row.stock,'in_stock')
            self.assertEqual(row.source_code,'gobik')
            self.assertEqual(row.sales_region,'西班牙站 EUR 报价')
            self.assertEqual(row.price.currency,'EUR')
            self.assertEqual(urlsplit(row.url).hostname,'gobik.com')
            self.assertEqual(urlsplit(row.url).query,'')
            self.assertIsNone(row.original_price)
            self.assertIsNone(row.identity.mpn)
            self.assertNotRegex(row.name,r'(^1\b|\bNEW\b|\n)')
            self.assertEqual(row.identity.brand,'Gobik')
            if '/bib-short-' in row.url:
                self.assertEqual(row.fetched_at.isoformat(),'2026-10-16T10:28:29+00:00')
        photo=next(x for x in self.rows if 'cx-pro-4-0-unisex-gobik-factory' in x.url)
        self.assertEqual((photo.identity.size,photo.price.amount,photo.stock_quantity),('XS',Decimal('85'),2))

    def test_catalog_keeps_nineteen_families_and_no_fake_discounts(self):
        for now in [self.now,self.now+timedelta(days=2)]:
            catalog=ComparisonCatalog(self.rows,self.fx,now)
            cards=catalog.search()
            self.assertEqual(len(cards),19)
            self.assertEqual(sum(c.category=='bibs' for c in cards),2)
            self.assertEqual(sum(c.category=='jerseys' for c in cards),17)
            for card in cards:
                self.assertEqual(card.stock_state,'in_stock')
                self.assertEqual(len(card.available_sizes),1)
                self.assertIsNone(card.discount_pct)
                self.assertEqual(card.source_codes,['gobik'])
                self.assertEqual(card.source_count,1)
        # Explicitly synthetic state changes exercise safety without private observations.
        for status in ['unknown','out_of_stock']:
            row=self.rows[0].model_copy(update={'stock':status})
            self.assertFalse(ComparisonCatalog([row],self.fx,self.now).available(row))

    def test_manual_only_registry_and_no_unrelated_policy_changes(self):
        self.assertEqual(self.payload['verification_method'],'manual_public_selected_variant')
        crawlers=json.loads((ROOT/'data/crawl_sources.json').read_text())
        self.assertIn('gobik',{x['code'] for x in crawlers})
        sources={x['code']:x for x in json.loads((ROOT/'data/sources.json').read_text())}
        self.assertEqual(sources['gobik']['collection_strategy'],'automatic_verified_public_variant')
        self.assertEqual(sources['gobik']['china_credit_card']['status'],'unknown')
        self.assertEqual(sources['movistar']['base_url'],'https://gobik.com')
        directories=json.loads((ROOT/'data/directories.json').read_text())
        brand=next(x for x in directories['brands'] if x['code']=='gobik')
        self.assertEqual(brand['source_codes'],['gobik'])
        team=next(x for x in crawlers if x['code']=='movistar')
        self.assertEqual(team['catalog_url'],'https://gobik.com/en/collections/movistar-team')
        self.assertTrue(all('movistar' not in x.url for x in self.rows))

if __name__=='__main__':unittest.main()
