"""现货规格与群入口独立 Mock 测试：python tests/test_inventory.py。"""
from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.catalog.models import ProductIdentity
from app.catalog.service import ComparisonCatalog
from app.collectors.variants import parse_rapha, parse_visma
from app.community import Community
from test_catalog import NOW, make_fx, make_offer


class InventoryTests(unittest.TestCase):
    def test_expired_price_cannot_make_a_size_selectable(self):
        offer = make_offer(price_valid_until=(NOW-timedelta(days=1)).date().isoformat())
        catalog = ComparisonCatalog([offer], make_fx(), NOW)
        self.assertFalse(catalog.available(offer))
        self.assertEqual(catalog.search()[0].available_sizes, [])

    def test_only_fresh_in_stock_sizes_are_selectable(self):
        offers=[make_offer("s",identity=ProductIdentity(brand="Mock",model="Jersey",mpn="M-1",size="S")),
                make_offer("m",stock="out_of_stock",identity=ProductIdentity(brand="Mock",model="Jersey",mpn="M-1",size="M")),
                make_offer("l",fetched_at=NOW-timedelta(days=2),identity=ProductIdentity(brand="Mock",model="Jersey",mpn="M-1",size="L"))]
        store=ComparisonCatalog(offers,make_fx(),NOW)
        card=store.search()[0]
        self.assertEqual(card.available_sizes,["S"])
        detail=store.compare(card.product_id)
        self.assertEqual(detail.identity.size,"S")
        self.assertEqual([v.size for v in detail.variants if v.in_stock],["S"])

    def test_visma_each_size_keeps_its_own_price_and_stock(self):
        html='''<h1>Mock Cycling Jersey Men</h1><script type="application/ld+json">{"@type":"Product","name":"Mock jersey","brand":"Mock","image":"https://example.org/_1200x630_crop_/preview.jpg","offers":{"price":"85.00","priceCurrency":"EUR","url":"https://example.org/item"}}</script>
        <div class="product__images"><div class="product__image"><img src="https://example.org/_1439xAUTO_resize_/full.jpg"></div></div>
        <input id="v1" name="purchasableId" value="1" data-saleprice="€85.00" data-stock="In stock" data-purchasable="1"><label for="v1"><span class="product__variant__variant">M</span>€85.00</label>
        <input id="v2" name="purchasableId" value="2" data-saleprice="€72.00" data-stock="Out of stock" data-purchasable="0"><label for="v2"><span class="product__variant__variant">L</span>€72.00</label>'''
        rows=parse_visma(html,{"code":"mock","name":"Mock"},"https://example.org/item",NOW)
        self.assertEqual([(r.identity.size,str(r.price.amount),r.stock) for r in rows],[("M","85.00","in_stock"),("L","72.00","out_of_stock")])
        self.assertTrue(all(r.image == "https://example.org/_1439xAUTO_resize_/full.jpg" for r in rows))

    def rapha_html(self, conflict=False):
        product={"region":"jp","title":"RCC Mock Bib Shorts","rccProduct":True,"sku":"RBS00DNY","gender":"Mens","isRestricted":False,
                 "variants":[{"sku":"RBS00DNY","color":"Dark Navy","currency":"JPY","price":20000,"wasPrice":30000,
                              "sizes":[{"size":"Small","sku":"RBS00DNYSML"},{"size":"Medium","sku":"RBS00DNYMED"}]}],
                 "initialStockLevels":{"RBS00DNYSML":{"status":"inStock","level":4}}}
        rsc="1:"+json.dumps(["$","component",None,product])+"\n"
        scripts=''.join('<script>self.__next_f.push('+json.dumps([1,chunk])+')</script>' for chunk in [rsc[:75],rsc[75:]])
        return '<script type="application/ld+json">'+json.dumps({"@type":"Product","name":"RCC Mock Bib Shorts","brand":"Rapha","offers":{"price":20000,"priceCurrency":"JPY","url":"https://example.org/RBS00DNY"}})+'</script>'+scripts+'<input name="size" value="SML" aria-label="Small'+(' (Out of stock)' if conflict else '')+'"><input name="size" value="MED" aria-label="Medium (Out of stock)">'

    def test_rapha_streamed_json_chunks_validate_size_stock_and_membership(self):
        rows=parse_rapha(self.rapha_html(),{"code":"rapha","name":"Mock"},"https://example.org/RBS00DNY",NOW)
        self.assertEqual([(r.identity.size,r.stock) for r in rows],[("S","in_stock"),("M","out_of_stock")])
        self.assertEqual(rows[0].purchase_requirements,["RCC 会员专享，需登录本人会员账号"])
        self.assertEqual(str(rows[0].original_price.amount),"30000")

    def test_rapha_conflicting_public_inventory_degrades_to_unknown(self):
        rows=parse_rapha(self.rapha_html(True),{"code":"rapha","name":"Mock"},"https://example.org/RBS00DNY",NOW)
        self.assertEqual(rows[0].stock,"unknown")

    def test_group_requires_real_image_and_hides_expired_qr(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Community(Path(temp))
            self.assertFalse(service.get()["available"])
            with self.assertRaises(ValueError):
                service.configure("Mock","data:image/svg+xml;base64,"+base64.b64encode(b'<svg></svg>').decode())
            image='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aC9sAAAAASUVORK5CYII='
            settings=service.configure("Mock 测试群",image,NOW+timedelta(days=1))
            self.assertTrue(settings["available"])
            path=Path(temp)/"config/community.json"
            value=json.loads(path.read_text(encoding="utf-8"));value["expires_at"]=(NOW-timedelta(days=1)).isoformat()
            path.write_text(json.dumps(value),encoding="utf-8")
            self.assertTrue(service.get()["expired"])
            self.assertFalse(service.get()["available"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
