import importlib.util
import unittest
import tempfile
from copy import deepcopy
from pathlib import Path

spec=importlib.util.spec_from_file_location('health',Path(__file__).resolve().parents[1]/'scripts/check_catalog_health.py')
health=importlib.util.module_from_spec(spec);spec.loader.exec_module(health)

class HealthTests(unittest.TestCase):
    def test_missing_image_reuses_only_its_own_exact_record(self):
        from app.catalog.storage import OfferRepository, atomic_json
        from test_catalog import make_offer, NOW
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);atomic_json(root/'sources.json',[])
            repository=OfferRepository(root)
            prior=make_offer(image='https://exact.example/own.jpg')
            repository.save(prior.source_code,[prior],NOW,[])
            repository.save(prior.source_code,[prior.model_copy(update={'image':None})],NOW,[])
            self.assertEqual(repository.load()[0].image,prior.image)
            changed=prior.model_copy(update={'image':None,'url':'https://other.example/other-product'})
            repository.save(prior.source_code,[changed],NOW,[])
            self.assertIsNone(next(row for row in repository.load() if row.offer_id==prior.offer_id).image)

    def fixture(self):
        return {'cards':[{'product_id':'helmet','category_group':'helmets','stock_state':'in_stock','image':'https://exact.example/helmet.jpg'}],
                'offers':{'offer':{'stock':'in_stock','fetched_at':'2026-10-16T00:00:00Z','collection_state':'current'}}}

    def test_failed_collection_keeps_last_observation(self):
        before=self.fixture();after=deepcopy(before);after['offers']['offer']['collection_state']='retained'
        self.assertFalse(health.inspect(before,after)['errors'])
        after['offers']['offer']['fetched_at']='2026-10-17T00:00:00Z'
        self.assertTrue(health.inspect(before,after)['errors'])

    def test_genuine_sold_out_is_allowed_and_reported(self):
        before=self.fixture();after=deepcopy(before)
        after['cards'][0]['stock_state']='out_of_stock';after['offers']['offer']['stock']='out_of_stock'
        result=health.inspect(before,after)
        self.assertFalse(result['errors']);self.assertTrue(result['warnings'])

    def test_loss_unknown_mapping_and_image_regressions_block_release(self):
        before=self.fixture()
        for mutation in ['drop','unknown','category','image','offer']:
            after=deepcopy(before)
            if mutation=='drop':after['cards']=[]
            elif mutation=='offer':after['offers']={}
            else:after['cards'][0][{'unknown':'stock_state','category':'category_group','image':'image'}[mutation]]={'unknown':'unknown','category':'other','image':None}[mutation]
            self.assertTrue(health.inspect(before,after)['errors'],mutation)
