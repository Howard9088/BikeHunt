import unittest
from datetime import datetime,timezone,timedelta
from app.collectors.variants import parse_visma, formatted_money
from app.collectors.transport import PublicPageFetcher, SourceDeferred
class OfficialRepairs(unittest.TestCase):
    def test_visma_explicit_currency_overrides_eur_jsonld(self):
        html='''<script type="application/ld+json">{"@type":"Product","name":"Jersey","brand":"Visma","offers":{"price":"85","priceCurrency":"EUR"}}</script><script>app.shop.productCurrency = 'USD';</script><input id="v1" name="purchasableId" value="1" data-saleprice="$100.30" data-stock="In stock" data-purchasable="1"><label for="v1"><span class="product__variant__variant">M</span></label>'''
        rows=parse_visma(html,{'code':'visma','name':'Visma'},'https://example.org/product',datetime.now(timezone.utc))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].price.currency,'USD')
        self.assertEqual(str(rows[0].price.amount),'100.30')
        self.assertEqual(parse_visma(html.replace("app.shop.productCurrency = 'USD';",''),{'code':'visma','name':'Visma'},'https://example.org/product',datetime.now(timezone.utc)),[])
    def test_formatted_prices(self):
        self.assertEqual(str(formatted_money('€1.234,56','EUR').amount),'1234.56')
        self.assertEqual(str(formatted_money('$1,234.56','USD').amount),'1234.56')
        self.assertIsNone(formatted_money('$100.30','EUR'))
    def test_rate_limit_stops_same_run_and_preserves_server_delay(self):
        calls=[]
        class Response:
            status=429
            headers={'Retry-After':'7200'}
        def request(url,**kwargs):
            calls.append(url);return Response()
        now=datetime.now(timezone.utc)
        fetcher=PublicPageFetcher({'example.org'},request=request,sleep=lambda _:None,utcnow=lambda:now)
        for url in ['https://example.org/a','https://example.org/b']:
            with self.assertRaises(SourceDeferred) as raised:fetcher.fetch(url)
            self.assertEqual(raised.exception.retry_at,now+timedelta(hours=2))
        self.assertEqual(len(calls),1)
