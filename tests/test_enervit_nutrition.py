"""Exact official Enervit offers fail closed on price, pack, identity and stock conflicts."""
from datetime import datetime,timezone
from pathlib import Path
import unittest
from app.collectors.enervit_nutrition import PRODUCTS,parse_enervit_nutrition
from app.collectors.transport import CollectionError
ROOT=Path(__file__).resolve().parents[1]
SOURCE={'code':'enervit_nutrition','name':'Enervit 欧洲官网'}
class EnervitTests(unittest.TestCase):
 def test_reviewed_exact_products(self):
  for url,p in PRODUCTS.items():
   html=(ROOT/'tests/fixtures'/('enervit-'+p['sku']+'.html')).read_text()
   row=parse_enervit_nutrition(html,SOURCE,url,datetime.now(timezone.utc))[0]
   self.assertEqual(row.stock,'in_stock');self.assertEqual(row.price.currency,'EUR')
   self.assertEqual(row.identity.size,p['size']);self.assertEqual(row.shipping_to_china.status,'unknown')
   self.assertIsNone(row.original_price);self.assertIsNone(row.stock_quantity)
 def test_conflicts_and_unreviewed_products_fail_closed(self):
  url='https://www.enervit.com/en/products/carbo-gel-c-2-1-pro-mango.html';p=PRODUCTS[url]
  html=(ROOT/'tests/fixtures'/('enervit-'+p['sku']+'.html')).read_text()
  for altered in [html.replace('content="EUR"','content="USD"'),html.replace('data-price="2.95"','data-price="3.95"'),html.replace('data-simple-id="96651"','data-simple-id="99999"'),html.replace('In stock','Unknown'),html.replace('1 pz','12 pz'),html.replace('English Store View','Italian Store View'),html.replace('id="product-addtocart-button"','id="product-addtocart-button" disabled'),html.replace('60 ml pack','90 ml pack')]:
   with self.subTest(altered=altered[:50]):
    with self.assertRaises(CollectionError):parse_enervit_nutrition(altered,SOURCE,url,datetime.now(timezone.utc))
  for wrong in [url.replace('/en/','/it/'),url+'?variant=12',url.replace('www.enervit.com','www.enervit.com.evil.example')]:
   with self.assertRaises(CollectionError):parse_enervit_nutrition(html,SOURCE,wrong,datetime.now(timezone.utc))
 def test_stock_not_rewritten_to_available(self):
  url='https://www.enervit.com/en/products/carbo-gel-c-2-1-pro-mango.html';p=PRODUCTS[url]
  html=(ROOT/'tests/fixtures'/('enervit-'+p['sku']+'.html')).read_text().replace('In stock','Out of stock')
  row=parse_enervit_nutrition(html,SOURCE,url,datetime.now(timezone.utc))[0]
  self.assertEqual(row.stock,'out_of_stock')

 def test_related_product_pack_cannot_replace_missing_exact_pack(self):
  for url,p in PRODUCTS.items():
   html=(ROOT/'tests/fixtures'/('enervit-'+p['sku']+'.html')).read_text()
   html=html.replace(p['pack_evidence'],'other package')+'<aside class="related-products"><li>'+p['pack_evidence']+'</li></aside>'
   with self.assertRaises(CollectionError):parse_enervit_nutrition(html,SOURCE,url,datetime.now(timezone.utc))
