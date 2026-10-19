"""Catalog and directory integration for reviewed nutrition expansion."""
from datetime import datetime,timezone
import json
from pathlib import Path
import unittest
from app.catalog.models import FxSnapshot
from app.catalog.service import ComparisonCatalog
from app.catalog.storage import OfferRepository
from app.public_visibility import public_directories
ROOT=Path(__file__).resolve().parents[1]
CODES={'sis_nutrition','maurten_nutrition','enervit_nutrition'}
class NutritionExpansionTests(unittest.TestCase):
 def test_brand_zone_and_exact_offers(self):
  offers=[x for x in OfferRepository(ROOT/'data').load() if x.source_code in CODES]
  catalog=ComparisonCatalog(offers,FxSnapshot(snapshot_id='test',rates={'EUR':'8','GBP':'9'}),datetime.now(timezone.utc))
  cards=catalog.search()
  self.assertEqual(len(cards),10)
  self.assertTrue(all(x.category_group=='nutrition' for x in cards))
  brands={x['code']:x for x in public_directories(ROOT)['brands']}
  for code in CODES:
   self.assertEqual(brands[code]['source_codes'],[code])
   self.assertGreater(brands[code]['product_count'],0)
  enervit=[x for x in cards if x.brand=='Enervit'];self.assertEqual(len(enervit),4)
  for card in enervit:
   detail=catalog.compare(card.product_id);self.assertEqual(len(detail.variants),1)
   offer=detail.offers[0].offer
   self.assertEqual(offer.shipping_to_china.status,'unknown');self.assertEqual(offer.china_issued_card.status,'unknown')
   self.assertIsNone(offer.original_price);self.assertFalse(detail.offers[0].landed_cost.scenarios)
  self.assertIn('不代表每款商品',brands['enervit_nutrition']['reference_note'])
 def test_crawl_and_payment_scope_are_connected(self):
  crawls={x['code']:x for x in json.loads((ROOT/'data/crawl_sources.json').read_text())}
  self.assertEqual(len(crawls['maurten_nutrition']['urls']),5)
  self.assertEqual(len(crawls['enervit_nutrition']['urls']),4)
  self.assertEqual(crawls['enervit_nutrition']['fetch_policy']['mode'],'dynamic')
  payments=json.loads((ROOT/'web/payment-methods.json').read_text())
  self.assertIn('enervit_nutrition',payments['coverage']['unmapped_registered_sources'])
  self.assertEqual(payments['coverage']['registered_source_registry_total'],len(json.loads((ROOT/'data/sources.json').read_text())))
