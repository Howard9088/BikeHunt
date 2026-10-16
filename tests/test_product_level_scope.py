import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from tempfile import TemporaryDirectory
from scripts.collect_offers import collect_source
from test_catalog import make_offer
from app.collectors.fetch_policy import CapturedPage
from datetime import datetime, timezone

class ProductLevelScope(unittest.TestCase):
    def test_selected_sku_urls_count_as_one_collected_parent(self):
        response = CapturedPage(b'raw', 200, 'https://example.com/a', {}, 'static', datetime.now(timezone.utc))
        offers = [make_offer('m', url='https://example.com/a/sku-m'),
                  make_offer('l', url='https://example.com/a/sku-l')]
        with TemporaryDirectory() as directory, patch('scripts.collect_offers.ROOT', Path(directory)), patch('scripts.collect_offers.PublicPageFetcher') as fetcher, patch('scripts.collect_offers.parse_jsonld', return_value=offers):
            (Path(directory) / 'data').mkdir()
            fetcher.return_value.fetch.return_value = response
            repository = MagicMock()
            collect_source({'code':'mock','domains':['example.com'],'parser':'jsonld','urls':['https://example.com/a']}, repository, {'mock':{'code':'mock'}})
            self.assertEqual(len(repository.save.call_args.args[1]), 2)
            self.assertEqual(repository.save.call_args.args[4]['collected_product_count'], 1)

    def test_generic_stock_is_not_a_size_level_claim(self):
        offer=make_offer()
        response=CapturedPage(b'raw', 200, 'https://example.com/a', {}, 'static', datetime.now(timezone.utc))
        with TemporaryDirectory() as directory, patch('scripts.collect_offers.ROOT',Path(directory)), patch('scripts.collect_offers.PublicPageFetcher') as fetcher, patch('scripts.collect_offers.parse_jsonld',return_value=[offer]):
            (Path(directory)/'data').mkdir()
            fetcher.return_value.fetch.return_value=response
            repository=MagicMock()
            collect_source({'code':'mock','domains':['example.com'],'parser':'jsonld','urls':['https://example.com/a'],'product_level_only':True},repository,{'mock':{'code':'mock','sales_region':'USD market'}})
            saved=repository.save.call_args.args[1][0]
            self.assertEqual(saved.stock,'unknown')
            self.assertEqual(saved.sales_region,'USD market')
            self.assertIn('仅商品级报价；逐尺码库存尚未核实',saved.purchase_requirements)
            self.assertEqual(saved.price,offer.price)
