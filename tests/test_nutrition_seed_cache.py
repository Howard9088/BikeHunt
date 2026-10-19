"""A stale CI cache cannot erase reviewed products or manufacture fresh stock."""
import copy,json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from app.catalog.storage import OfferRepository
ROOT=Path(__file__).resolve().parents[1]
class NutritionSeedCacheTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  (self.root/'offers').mkdir();(self.root/'reviewed_nutrition').mkdir();(self.root/'collection_status').mkdir()
  self.seed=json.loads((ROOT/'data/reviewed_nutrition/maurten_nutrition.json').read_text())
  (self.root/'sources.json').write_text('[]')
  self.write('reviewed_nutrition/maurten_nutrition.json',self.seed)
 def tearDown(self):self.temp.cleanup()
 def write(self,path,data):(self.root/path).write_text(json.dumps(data))
 def rows(self):return {x.offer_id:x for x in OfferRepository(self.root).load()}
 def test_old_cache_cannot_erase_new_products_or_reset_time(self):
  old=copy.deepcopy(self.seed['offers'][0]);old['fetched_at']='2026-10-19T01:34:00Z'
  self.write('offers/maurten_nutrition.json',{'offers':[old]})
  self.write('collection_status/maurten_nutrition.json',{'status':'failed','attempted_at':'2026-10-19T08:50:49+00:00','errors':[{'url':old['url'],'error':'collection_failed'}]})
  rows=self.rows();self.assertEqual(len(rows),5)
  for raw in self.seed['offers']:
   row=rows[raw['offer_id']];self.assertEqual(row.fetched_at,datetime.fromisoformat(raw['fetched_at'].replace('Z','+00:00')))
   self.assertEqual(row.collection_state,'retained');self.assertEqual(row.evidence_sha256,raw['evidence_sha256'])
  self.assertEqual(json.loads((self.root/'collection_status/maurten_nutrition.json').read_text())['status'],'failed')
 def test_newer_and_equal_cache_wins_even_when_sold_out(self):
  for stamp in ['2026-10-19T09:00:00Z',self.seed['offers'][0]['fetched_at']]:
   newer=copy.deepcopy(self.seed['offers'][0]);newer.update(fetched_at=stamp,stock='out_of_stock',collection_state='current')
   self.write('offers/maurten_nutrition.json',{'offers':[newer]})
   row=self.rows()[newer['offer_id']];self.assertEqual(row.stock,'out_of_stock');self.assertEqual(row.fetched_at,datetime.fromisoformat(stamp.replace('Z','+00:00')))
 def test_failed_save_keeps_exact_seed_without_new_freshness(self):
  repo=OfferRepository(self.root);now=datetime(2026,10,19,9,tzinfo=timezone.utc)
  repo.save('maurten_nutrition',[],now,[{'url':x['url'],'error':'market mismatch'} for x in self.seed['offers']])
  self.assertEqual(len(self.rows()),5)
  for row in self.rows().values():self.assertLess(row.fetched_at,now);self.assertEqual(row.collection_state,'retained')
 def test_unreviewed_or_wrong_market_seed_is_not_admitted(self):
  seed=copy.deepcopy(self.seed)
  for row in seed['offers']:row['url']=row['url'].replace('/fr/','/us/')
  self.write('reviewed_nutrition/maurten_nutrition.json',seed);self.assertEqual(self.rows(),{})
