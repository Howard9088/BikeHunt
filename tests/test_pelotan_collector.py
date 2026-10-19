import json
import re
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.collectors.pelotan import parse_pelotan

FIXTURE = (Path(__file__).parent / 'fixtures' / 'pelotan_200ml.html').read_text()
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)
URL = 'https://pelotan.cc/products/pelotan-200ml-spray'
SOURCE = {'code':'pelotan', 'name':'Pelotan official',
          'china_shipping': {'status':'no', 'evidence_url':'https://pelotan.cc/pages/faqs',
                             'checked_at':NOW, 'note':'UK and EU only'}}


def mutate(fn):
    blocks = re.findall(r'<script[^>]*>(.*?)</script>', FIXTURE, re.S)
    product, ld = map(json.loads, blocks[1:])
    fn(product['variants'][0], ld['offers'][0])
    return ('<script>' + blocks[0] + '</script><script data-product-json>'
            + json.dumps(product) + '</script><script type="application/ld+json">'
            + json.dumps(ld) + '</script>')


class PelotanCollectorTests(unittest.TestCase):
    def test_exact_product_no_reused_image(self):
        row, = parse_pelotan(FIXTURE, SOURCE, URL, NOW)
        self.assertEqual(row.price.amount, Decimal('24.95'))
        self.assertEqual(row.price.currency, 'GBP')
        self.assertEqual(row.identity.size, '200 ml · 喷雾 · 单瓶')
        self.assertEqual(row.identity.gtin, '5017371154763')
        self.assertEqual(row.stock, 'in_stock')
        self.assertIsNone(row.stock_quantity)
        self.assertIsNone(row.image)
        self.assertEqual(row.shipping_to_china.status, 'no')
        self.assertEqual(row.china_issued_card.status, 'unknown')
        self.assertEqual(row.fetched_at, NOW)
        self.assertEqual(row.price_valid_until, '2026-10-20')

    def test_refresh_price_and_stock(self):
        def change(v,q):
            v.update(price=2295, available=False)
            q.update(price=22.95, availability='https://schema.org/OutOfStock')
        row, = parse_pelotan(mutate(change), SOURCE, URL, NOW)
        self.assertEqual(row.price.amount, Decimal('22.95'))
        self.assertEqual(row.stock, 'out_of_stock')

    def test_fail_closed(self):
        for change in [lambda v,q:q.update(price=10),
                       lambda v,q:q.update(priceCurrency='EUR'),
                       lambda v,q:q.update(sku='wrong'),
                       lambda v,q:q.update(url=URL+'?variant=1'),
                       lambda v,q:v.update(id=1),
                       lambda v,q:v.update(available=False),
                       lambda v,q:v.update(available='true'),
                       lambda v,q:v.update(requires_selling_plan=True),
                       lambda v,q:v.update(barcode='wrong')]:
            with self.subTest(change=change):
                self.assertEqual(parse_pelotan(mutate(change), SOURCE, URL, NOW), [])
        for text in [FIXTURE.replace('"active":"GBP"','"active":"USD"'),
                     FIXTURE.replace('data-product-json','other-data'),
                     FIXTURE + FIXTURE]:
            self.assertEqual(parse_pelotan(text, SOURCE, URL, NOW), [])
        for url in [URL.replace('pelotan.cc','example.com'), URL+'?currency=USD', URL.replace('200ml','100ml')]:
            self.assertEqual(parse_pelotan(FIXTURE, SOURCE, url, NOW), [])

    def test_variant_url_and_unknown_shipping_by_default(self):
        row, = parse_pelotan(FIXTURE, {'code':'pelotan','name':'Pelotan'}, URL+'?variant=47674080395595', NOW)
        self.assertEqual(row.shipping_to_china.status, 'unknown')
        self.assertEqual(row.family_hint, 'pelotan:200ml-spray')


if __name__ == '__main__':
    unittest.main()
