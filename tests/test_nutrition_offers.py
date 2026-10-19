import unittest
from pathlib import Path
from datetime import datetime,timezone
from app.collectors.maurten_nutrition import parse_maurten_nutrition,URL
from app.collectors.transport import CollectionError
from app.catalog.storage import OfferRepository
from app.catalog.models import FxSnapshot
from app.catalog.service import ComparisonCatalog
ROOT=Path(__file__).resolve().parents[1]
class NutritionOfferTests(unittest.TestCase):
 def test_french_market_exact_box(self):
  html=(ROOT/'tests/fixtures/maurten_nutrition.html').read_text()
  source={'code':'maurten_nutrition','name':'Maurten 法国官网'}
  now=datetime.now(timezone.utc)
  row=parse_maurten_nutrition(html,source,URL,now)[0]
  self.assertEqual(str(row.price.amount),'40.96');self.assertEqual(row.price.currency,'EUR')
  self.assertEqual(row.identity.size,'标准版 · 12袋/盒');self.assertEqual(row.stock,'in_stock')
  for altered in [html.replace('Boîte de 12','Boîte de 6'),html.replace('"EUR"','"USD"'),html.replace('"12002"','"other"')]:
   with self.assertRaises(CollectionError):parse_maurten_nutrition(altered,source,URL,now)
  with self.assertRaises(CollectionError):parse_maurten_nutrition(html,source,URL.replace('/fr/','/us/'),now)
 def test_real_snapshots_export_as_two_cards_and_two_sis_choices(self):
  offers=[o for o in OfferRepository(ROOT/'data').load() if o.source_code in {'sis_nutrition','maurten_nutrition'}]
  now=max(o.fetched_at for o in offers)
  catalog=ComparisonCatalog(offers,FxSnapshot(snapshot_id='test',rates={'GBP':'9','EUR':'8'}),now)
  cards=catalog.search()
  self.assertEqual(len(cards),2)
  self.assertTrue(all(c.category_group=='nutrition' for c in cards))
  sis=next(c for c in cards if c.brand=='SiS')
  self.assertEqual(sis.variant_count,2)
  detail=catalog.compare(sis.product_id)
  self.assertEqual(len(detail.variants),2)
  for quote in detail.offers:
   self.assertNotEqual(quote.offer.shipping_to_china.status,'yes')
   self.assertFalse(quote.landed_cost.scenarios)
