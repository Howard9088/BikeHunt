"""Reduced public-RSC mock data; no network, browser login or vendor script execution."""

import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.collectors.specialized import parse_specialized

URL = "https://www.specialized.com/us/en/mock-jersey/p/1000097850?color=1000196880-1000097850"
NOW = datetime.now(timezone.utc)
SOURCE = {"code": "specialized", "name": "Specialized official"}


def fixture(edit=None):
    sku = {
        "availability": "INSTOCK",
        "code": "1000235432",
        "skuCode": "1000235432",
        "sku": "65725-1001",
        "isBike": False,
        "name": "XS",
        "size": "XS",
        "upc": "196625206085",
        "prices": {
            "special": {"raw": 146.99, "currency": "USD", "minorUnits": 14699},
            "regular": {"raw": 209.99, "currency": "USD", "minorUnits": 20999},
        },
    }
    color = {
        "code": "1000196880-1000097850",
        "colorName": "Spice",
        "preOrderable": False,
        "sizes": [{"name": "XS", "skus": {"name": "XS", "values": [sku]}}],
    }
    stock = {
        "availability": "INSTOCK",
        "code": "1000235432",
        "sku": "65725-1001",
        "inboundInventory": False,
        "stock": {"stockLevel": 14, "isValueRounded": False, "stockLevelStatus": "inStock"},
    }
    value = {
        "getPDP": {
            "code": "1000097850",
            "name": "Women's Mock Jersey",
            "brand": "SPECIALIZED",
            "url": "/mock-jersey/p/1000097850",
            "archived": False,
            "endOfLife": False,
            "isBike": False,
            "showAddToCartButton": True,
            "colors": [color],
        },
        "dynamicData": {
            "code": "1000097850",
            "showAddToCartButton": True,
            "colors": [{"code": color["code"], "sizes": [stock]}],
        },
    }
    if edit:
        edit(value)
    return (
        "<script>self.__next_f.push("
        + json.dumps([1, "a:" + json.dumps({"productData": value}) + "\n"])
        + ")</script>"
    )


class SpecializedTests(unittest.TestCase):
    def test_exact_sku_join_and_minor_unit_prices(self):
        row = parse_specialized(fixture(), SOURCE, URL, NOW)[0]
        self.assertEqual(
            (row.identity.size, row.identity.color, row.stock_quantity), ("XS", "Spice", 14)
        )
        self.assertEqual(str(row.price.amount), "146.99")
        self.assertEqual(str(row.original_price.amount), "209.99")
        self.assertEqual(row.stock, "in_stock")

    def test_wrong_product_market_and_missing_independent_stock_rejected(self):
        for edit in [
            lambda v: v["dynamicData"].update(code="other"),
            lambda v: v["getPDP"].update(isBike=True),
            lambda v: v["getPDP"]["colors"][0]["sizes"][0]["skus"]["values"][0]["prices"][
                "special"
            ].update(minorUnits=1),
            lambda v: v["dynamicData"]["colors"][0]["sizes"][0].update(sku="other"),
        ]:
            self.assertEqual(parse_specialized(fixture(edit), SOURCE, URL, NOW), [])
        self.assertEqual(
            parse_specialized(fixture(), SOURCE, URL.replace("/us/en/", "/jp/ja/"), NOW), []
        )

    def test_rounded_or_conflicting_stock_stays_unknown(self):
        edit = lambda v: v["dynamicData"]["colors"][0]["sizes"][0]["stock"].update(
            isValueRounded=True
        )
        row = parse_specialized(fixture(edit), SOURCE, URL, NOW)[0]
        self.assertEqual(row.stock, "unknown")
        self.assertIsNone(row.stock_quantity)

    def test_preorder_and_mismatched_color_do_not_become_current_inventory(self):
        self.assertEqual(
            parse_specialized(
                fixture(lambda v: v["getPDP"]["colors"][0].update(preOrderable=True)),
                SOURCE,
                URL,
                NOW,
            ),
            [],
        )
        self.assertEqual(
            parse_specialized(fixture(), SOURCE, URL.replace("1000196880-", "1000000000-"), NOW),
            [],
        )


if __name__ == "__main__":
    unittest.main()
