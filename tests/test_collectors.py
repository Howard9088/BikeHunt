"""独立 Mock HTML 与网络行为验收，不访问互联网。"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.collectors.parsers import parse_jsonld, parse_teamcycles
from app.collectors.transport import CollectionError, PublicPageFetcher

NOW = datetime.now(timezone.utc)
SOURCE = {"code":"maap", "name":"MAAP 官网"}
URL = "https://example.org/products/mock"


def html(data) -> str:
    return '<script type="application/ld+json">'+json.dumps(data)+'</script>'


class CollectorTests(unittest.TestCase):
    def test_maap_multi_size_and_wrong_original_currency(self):
        data = {"@type":"Product", "name":"Mock jersey", "brand":{"name":"MAAP"},
                "offers":[{"sku":"MAP-MAJ339_BLK_"+size, "price":"100", "priceCurrency":"AUD",
                            "availability":"https://schema.org/InStock",
                            "priceSpecification":{"price":"245","priceCurrency":"GBP"}}
                           for size in ["XS","S","M","L","XL","XXL"]]}
        rows = parse_jsonld(html(data), SOURCE, URL, NOW)
        self.assertEqual([r.identity.size for r in rows], ["XS","S","M","L","XL","XXL"])
        self.assertEqual({r.identity.mpn for r in rows}, {"MAP-MAJ339_BLK"})
        self.assertTrue(all(r.original_price is None for r in rows))

    def test_product_group_and_uk_shipping_not_china_shipping(self):
        product = {"@type":"ProductGroup", "brand":{"name":"POC"}, "name":"Mock helmet", "productGroupID":"group",
                   "hasVariant":[{"@type":"Product", "name":"Mock helmet", "size":"M", "color":"white", "sku":"merchant-001",
                                   "offers":{"price":"99", "priceCurrency":"GBP", "shippingDetails":{
                                       "shippingDestination":{"addressCountry":"GB"},
                                       "shippingRate":{"value":0,"currency":"GBP"}}}}]}
        rows = parse_jsonld(html([product]), {"code":"sigmasports","name":"Sigma"}, URL, NOW)
        self.assertEqual(len(rows),1)
        self.assertIsNone(rows[0].shipping)
        self.assertIsNone(rows[0].identity.mpn)
        self.assertEqual(rows[0].shipping_to_china.status,"unknown")

    def test_invalid_json_price_and_aggregate_price_not_published(self):
        page = '<script type="application/ld+json">bad</script>'+html({
            "@type":"Product", "name":"Mock", "brand":"Mock",
            "offers":[{"price":"NaN","priceCurrency":"USD"},{"@type":"AggregateOffer","lowPrice":"12","priceCurrency":"USD"}]})
        self.assertEqual(parse_jsonld(page,SOURCE,URL,NOW),[])

    def test_teamcycles_manufacturer_code_is_verified(self):
        product = {"id":"MAP-MAJ339_BLK", "title":"Mock Jersey", "price":115.5,
                   "oldPrice":165,"currency":"GBP","status":"notAvailable","productVendor":"MAAP"}
        page = ('<p id="summaryCode">Code:MAP-MAJ339_BLK</p><script>'
                'gts.push(["google_base_offer_id","MAP-MAJ339_BLK_XS"]);'
                'omnisend.push(["track","viewed product",{"properties":'+json.dumps({"product":product})+'}]);</script>')
        rows = parse_teamcycles(page,{"code":"teamcycles","name":"Team"},URL,NOW)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].identity.size,"XS")
        self.assertEqual(rows[0].stock,"out_of_stock")
        self.assertEqual(parse_teamcycles(page.replace("Code:MAP-MAJ339_BLK","Code:OTHER"),{"code":"teamcycles","name":"Team"},URL,NOW),[])

    def test_robots_blocks_without_requesting_product(self):
        calls=[]
        def request(url,**kwargs):
            calls.append(url)
            return SimpleNamespace(status=200,body=b"User-agent: *\nDisallow: /products/")
        fetcher=PublicPageFetcher({"example.org"},request=request,sleep=lambda seconds:None)
        with self.assertRaises(CollectionError):
            fetcher.fetch(URL)
        self.assertEqual(calls,["https://example.org/robots.txt"])

    def test_retries_are_bounded_with_exponential_backoff(self):
        calls=[];sleeps=[]
        def request(url,**kwargs):
            calls.append(url)
            if url.endswith("robots.txt"):
                return SimpleNamespace(status=200,body=b"User-agent: *\nAllow: /")
            raise OSError("offline")
        fetcher=PublicPageFetcher({"example.org"},request=request,sleep=sleeps.append)
        with self.assertRaises(CollectionError):
            fetcher.fetch(URL)
        self.assertEqual(calls.count(URL),3)
        self.assertIn(1,sleeps)
        self.assertIn(2,sleeps)

    def test_client_errors_not_retried(self):
        calls=[]
        def request(url,**kwargs):
            calls.append(url)
            return SimpleNamespace(status=200 if url.endswith("robots.txt") else 403,
                                   body=b"User-agent: *\nAllow: /")
        with self.assertRaises(CollectionError):
            PublicPageFetcher({"example.org"},request=request,sleep=lambda _:None).fetch(URL)
        self.assertEqual(calls.count(URL),1)

    def test_outside_domain_rejected(self):
        with self.assertRaises(CollectionError):
            PublicPageFetcher({"example.org"}).fetch("https://wrong.example/product")


if __name__ == "__main__":
    unittest.main(verbosity=2)
