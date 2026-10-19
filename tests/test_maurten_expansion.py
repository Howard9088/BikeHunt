"""Reduced real-page fixtures; full HTTP captures remain in review evidence."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import unittest

from app.collectors.maurten_nutrition import PRODUCTS, URL, parse_maurten_nutrition
from app.collectors.transport import CollectionError

FIXTURES = Path(__file__).parent / 'fixtures' / 'maurten_expansion'
SOURCE = {'code': 'maurten_nutrition', 'name': 'Maurten 法国官网'}
NOW = datetime(2026, 10, 19, 7, 36, tzinfo=timezone.utc)
EXPECTED = {
    'gel-100-box': ('12002', 'Gel 100', '40.96', '标准版 · 12袋/盒'),
    'gel-160-box': ('12103', 'Gel 160', '54.95', '标准版 · 12袋/盒'),
    'gel-100-caf-100-box': ('13002', 'Gel 100 Caf 100', '47.50', 'Caf 100咖啡因版 · 12袋/盒'),
    'drink-mix-160': ('10102', 'Drink Mix 160', '39.95', '标准版 · 18袋/盒'),
    'drink-mix-320': ('10202', 'Drink Mix 320', '46.95', '标准版 · 14袋/盒'),
}


def fixture(slug='gel-160-box'):
    return (FIXTURES / (slug + '.html')).read_text()


def url(slug='gel-160-box'):
    return 'https://www.maurten.com/fr/products/' + slug


def alter_product(body, change):
    pattern = r'(<script type="application/ld\+json">)(.*?)(</script>)'
    def replace(match):
        payload = json.loads(match.group(2))
        change(payload['@graph'][0])
        return match.group(1) + json.dumps(payload, ensure_ascii=False) + match.group(3)
    return re.sub(pattern, replace, body, flags=re.S)


class MaurtenExpansionTests(unittest.TestCase):
    def parse(self, body=None, page_url=None):
        return parse_maurten_nutrition(body or fixture(), SOURCE, page_url or url(), NOW)[0]

    def test_exact_live_products_have_independent_quotes_and_images(self):
        rows = []
        for slug, (sku, name, amount, size) in EXPECTED.items():
            with self.subTest(slug=slug):
                body = fixture(slug)
                row = self.parse(body, url(slug))
                self.assertEqual(PRODUCTS[url(slug)]['sku'], sku)
                self.assertEqual(row.name, name)
                self.assertEqual(row.identity.model, name)
                self.assertEqual(row.identity.size, size)
                self.assertEqual(str(row.price.amount), amount)
                self.assertEqual(row.price.currency, 'EUR')
                self.assertEqual(row.stock, 'in_stock')
                self.assertEqual(row.url, url(slug))
                self.assertEqual(row.collection_url, url(slug))
                self.assertEqual(row.evidence_sha256, hashlib.sha256(body.encode()).hexdigest())
                self.assertIn(sku, row.identity_evidence)
                self.assertEqual(row.shipping_to_china.status, 'unknown')
                self.assertEqual(row.china_issued_card.status, 'unknown')
                self.assertIsNone(row.shipping)
                rows.append(row)
        for field in ('offer_id', 'family_hint', 'image'):
            self.assertEqual(len({getattr(row, field) for row in rows}), 5)
        self.assertEqual(URL, url('gel-100-box'))

    def test_reject_foreign_or_missing_source_code(self):
        for source in ({'code': 'other', 'name': SOURCE['name']}, {'name': SOURCE['name']}):
            with self.subTest(source=source), self.assertRaises(CollectionError):
                parse_maurten_nutrition(fixture(), source, url(), NOW)

    def test_reject_other_markets_even_with_french_url_and_euros(self):
        body = fixture()
        for wrong in (
            body.replace('France', 'Netherlands'),
            body.replace('France |', 'Belgium |'),
            body.replace('France <span>(EUR)', 'Germany <span>(EUR)'),
            body.replace('(EUR)', '(USD)'),
            re.sub(r'<footer>.*?</footer>', '', body, flags=re.S),
            body.replace('class="__market"', 'class="unknown-market"'),
        ):
            with self.subTest(wrong=wrong[:90]), self.assertRaises(CollectionError):
                self.parse(wrong)
        for wrong_url in (url().replace('/fr/', '/us/'), url() + '?country=FR', url('unknown-product')):
            with self.subTest(url=wrong_url), self.assertRaises(CollectionError):
                self.parse(body, wrong_url)

    def test_reject_product_identity_or_canonical_mismatch(self):
        mutations = [
            lambda p: p.update(sku='12104'),
            lambda p: p.update(name='Gel 100'),
            lambda p: p.update(url=url('gel-100-box')),
            lambda p: p.update(mainEntityOfPage=url().replace('/fr/', '/us/')),
        ]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(CollectionError):
                self.parse(alter_product(fixture(), change))
        with self.assertRaises(CollectionError):
            self.parse(fixture().replace('<link href="' + url(), '<link href="' + url('gel-100-box')))
        with self.assertRaises(CollectionError):
            self.parse(fixture('gel-100-box'))

    def test_pack_must_match_exact_product_and_all_presentations(self):
        body = fixture()
        for wrong in (
            body.replace('Boîte de 12', 'Boîte de 6'),
            body.replace('Boîte de 12', 'Boîte de 6', 1),
            body.replace('Boîte de 12\u00a0portions', 'Boîte de 12\u00a0portions + bonus'),
            body.replace('class="el-add-to-cart__product-info"', 'class="unrelated-product"'),
            re.sub(r'<h3 class="el-add-to-cart__product-title">.*?</h3>', '<h3 class="el-add-to-cart__product-title">Gel 100</h3>', body),
        ):
            with self.subTest(wrong=wrong[:90]), self.assertRaises(CollectionError):
                self.parse(wrong)
        for slug, before in [('drink-mix-160', 'Box of 18'), ('drink-mix-320', 'Box of 14')]:
            with self.subTest(slug=slug), self.assertRaises(CollectionError):
                self.parse(fixture(slug).replace(before, 'Box of 12'), url(slug))

    def test_reject_ambiguous_or_mismatched_quotes(self):
        mutations = [
            lambda p: p.update(offers=[]),
            lambda p: p['offers'].append(p['offers'][0].copy()),
            lambda p: p.update(offers=p['offers'][0]),
            lambda p: p['offers'][0].update(sku='12002'),
            lambda p: p['offers'][0].update(url=url('gel-100-box')),
            lambda p: p['offers'][0].update(priceCurrency='USD'),
            lambda p: p['offers'][0].update(**{'@type': 'AggregateOffer'}),
        ]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(CollectionError):
                self.parse(alter_product(fixture(), change))
        ld = re.search(r'<script type="application/ld\+json">.*?</script>', fixture(), re.S).group(0)
        with self.assertRaises(CollectionError):
            self.parse(fixture() + ld)

    def test_price_image_and_stock_require_explicit_valid_evidence(self):
        mutations = [
            lambda p: p['offers'][0].pop('price'),
            lambda p: p['offers'][0].update(price='0'),
            lambda p: p['offers'][0].update(price='NaN'),
            lambda p: p['offers'][0].update(price='-1'),
            lambda p: p.update(image=[]),
            lambda p: p.update(image=['https://unrelated.example/gel.png']),
            lambda p: p.update(image=['http://maurten.imgix.net/gel.png']),
            lambda p: p.update(image=['https://[broken/gel.png']),
            lambda p: p.update(image=['https://user:pass@maurten.imgix.net/gel.png']),
            lambda p: p['offers'][0].pop('availability'),
            lambda p: p['offers'][0].update(availability='http://schema.org/PreOrder'),
            lambda p: p['offers'][0].update(availability='https://unrelated.example/InStock'),
        ]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(CollectionError):
                self.parse(alter_product(fixture(), change))

    def test_explicit_out_of_stock_is_preserved(self):
        for status in ('OutOfStock', 'SoldOut', 'Discontinued'):
            row = self.parse(alter_product(fixture(), lambda p: p['offers'][0].update(availability='https://schema.org/' + status)))
            self.assertEqual(row.stock, 'out_of_stock')


if __name__ == '__main__':
    unittest.main()
