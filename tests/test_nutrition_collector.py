"""Regression tests using compact official SiS source evidence."""
import json
import re
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.collectors.nutrition import parse_nutrition

FIXTURE = (Path(__file__).parent / 'fixtures' / 'sis_nutrition.html').read_text()
SOURCE = {'code': 'sis_nutrition', 'name': 'SiS official'}
URL = 'https://www.scienceinsport.com/beta-fuel-80?sku=131263'
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


def mutate(fn):
    blocks = re.findall(r'<script[^>]*>(.*?)</script>', FIXTURE, re.S)
    product, config = map(json.loads, blocks)
    fn(product, config['jsonConfig'])
    return ('<script type="application/ld+json">' + json.dumps(product) + '</script>'
            '<script>' + json.dumps(config) + '</script>')


class NutritionCollectorTests(unittest.TestCase):
    def test_exact_orange_pack(self):
        offer, = parse_nutrition(FIXTURE, SOURCE, URL, NOW)
        self.assertEqual(offer.price.amount, Decimal('42'))
        self.assertEqual(offer.price.currency, 'GBP')
        self.assertEqual(offer.identity.size, 'Orange / 15 Pack')
        self.assertIsNone(offer.identity.gtin)
        self.assertIsNone(offer.identity.color)
        self.assertEqual(offer.stock_quantity, 138)
        self.assertEqual(offer.stock, 'in_stock')
        self.assertEqual(offer.sales_region, 'UK')
        self.assertIn('131263_gs.png', offer.image)
        self.assertEqual(offer.shipping_to_china.status, 'unknown')
        self.assertEqual(offer.china_issued_card.status, 'unknown')
        self.assertEqual(offer.fetched_at, NOW)
        self.assertEqual(len(offer.evidence_sha256), 64)

    def test_second_flavour_same_family(self):
        orange, = parse_nutrition(FIXTURE, SOURCE, URL, NOW)
        berry, = parse_nutrition(FIXTURE, SOURCE, URL.replace('131263', '131265'), NOW)
        self.assertEqual(berry.identity.size, 'Strawberry and Lime / 15 Pack')
        self.assertEqual(berry.stock_quantity, 163)
        self.assertEqual(berry.family_hint, orange.family_hint)
        self.assertNotEqual(berry.offer_id, orange.offer_id)

    def test_live_selected_variant_titles(self):
        for sku, flavour, quantity in [('131263', 'Orange', 154),
                                      ('131265', 'Strawberry and Lime', 170)]:
            fixture = (Path(__file__).parent / 'fixtures' / f'sis_selected_{sku}.html').read_text()
            row, = parse_nutrition(fixture, SOURCE, URL.replace('131263', sku), NOW)
            self.assertEqual(row.identity.size, f'{flavour} / 15 Pack')
            self.assertEqual(row.stock_quantity, quantity)
            self.assertEqual(row.price.amount, Decimal('42'))
            wrong_flavour = 'Strawberry and Lime' if flavour == 'Orange' else 'Orange'
            for wrong_name in [f'Beta Fuel 80 - {wrong_flavour} - 15 Pack',
                               f'Beta Fuel 80 - {flavour} - Single', 'Beta Fuel 90']:
                broken = fixture.replace(f'Beta Fuel 80 - {flavour} - 15 Pack', wrong_name)
                self.assertEqual(parse_nutrition(broken, SOURCE, URL.replace('131263', sku), NOW), [])

    def test_price_and_stock_are_refreshed(self):
        def change(p, c):
            p['offers'][0]['price'] = '39.50'
            c['optionPrices']['6256']['finalPrice']['amount'] = 39.5
            c['index']['6256']['stock_status_qty'] = 4
        row, = parse_nutrition(mutate(change), SOURCE, URL, NOW)
        self.assertEqual(row.price.amount, Decimal('39.50'))
        self.assertEqual(row.stock_quantity, 4)

    def test_fail_closed_on_conflicts(self):
        changes = [
            lambda p,c: p['offers'][0].update(price='2.50'),
            lambda p,c: p['offers'][0].update(priceCurrency='EUR'),
            lambda p,c: p['offers'][0].update(sku='wrong'),
            lambda p,c: p['offers'][0].update(url=URL.replace('131263','131265')),
            lambda p,c: c['sku'].update({'6256': 'wrong'}),
            lambda p,c: c['index']['6256']['preselect_settings'].update(sku='wrong'),
            lambda p,c: c['attributes']['173']['options'][0].update(label='Single'),
            lambda p,c: c['index']['6256'].update(stock_status_qty=0),
            lambda p,c: c['index']['6256'].update(stock_status_qty=True),
            lambda p,c: c['disabledProducts'].append('6256'),
            lambda p,c: c['images']['6256'].clear(),
        ]
        for change in changes:
            with self.subTest(change=change):
                self.assertEqual(parse_nutrition(mutate(change), SOURCE, URL, NOW), [])

    def test_confirmed_out_of_stock(self):
        def change(p,c):
            p['offers'][0]['availability'] = 'https://schema.org/OutOfStock'
            c['index']['6256']['stock_status_qty'] = 0
            c['salable']['175']['67'] = []
            c['salable']['173']['18098'].remove('6256')
            c['oosProducts'].append('6256')
        offer, = parse_nutrition(mutate(change), SOURCE, URL, NOW)
        self.assertEqual(offer.stock, 'out_of_stock')
        self.assertEqual(offer.stock_quantity, 0)

    def test_wrong_source_url_or_missing_evidence(self):
        for url in (URL.replace('www.scienceinsport.com','example.com'), URL.replace('sku=131263','sku=131197'), URL + '&___store=us'):
            self.assertEqual(parse_nutrition(FIXTURE, SOURCE, url, NOW), [])
        self.assertEqual(parse_nutrition(FIXTURE, {'code':'other'}, URL, NOW), [])
        self.assertEqual(parse_nutrition('<html>unavailable</html>', SOURCE, URL, NOW), [])
        self.assertEqual(parse_nutrition(FIXTURE + FIXTURE, SOURCE, URL, NOW), [])


if __name__ == '__main__':
    unittest.main()
