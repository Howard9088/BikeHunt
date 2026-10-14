"""Offline fixtures model the observed official payloads, including uncertainty."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from app.collectors.embedded_catalogs import parse_assos, parse_kask, parse_pns


NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def pns_page(product=None, detail=None):
    product = product or {
        "id": "gid://shopify/Product/123", "handle": "jersey-olive", "title": "Jersey - Olive",
        "featuredImage": {"url": "https://cdn.shopify.com/jersey.jpg"}, "tags": [],
        "variants": [
            {"id": "gid://shopify/ProductVariant/" + str(i), "sku": "PNS-" + size,
             "selectedOptions": [{"name": "Size", "value": size}],
             "price": {"amount": str(price), "currencyCode": "EUR"},
             "compareAtPrice": {"amount": "250", "currencyCode": "EUR"},
             "availableForSale": available}
            for i, (size, price, available) in enumerate([("S", 190, True), ("M", 200, False)])]}
    detail = detail or {"gid": product["id"], "handle": product["handle"], "title": "Jersey",
                        "color": "Olive", "selfProductGrid": {"gender": "men", "tags": {}}}
    rsc = 'b:["$",null,{"value":' + json.dumps({"sanityProduct": detail, "shopifyProduct": product}) + "}]\n"
    # Real Next responses split a literal object across script chunks.
    split = rsc.find('"variants"') + 5
    return "".join('<script>self.__next_f.push(' + json.dumps([1, chunk]) + ')</script>'
                   for chunk in [rsc[:split], rsc[split:]]), product, detail


def assos_data():
    def attributes(**kwargs):
        return {key: {"value": value} for key, value in kwargs.items()}
    children = [{"attributes": attributes(sku="11.20.001.18." + size, size=size,
                                         barcode="7627776069838"),
                 "pricing": {"final_price": price, "base_price": 230}, "inventory": inventory}
                for size, price, inventory in [
                    ("S", 200, {"in_stock": True, "saleable": True, "backorders": False, "quantity": 2}),
                    ("M", 210, {"in_stock": False, "saleable": True, "quantity": 0}),
                    ("L", 220, {"saleable": True, "backorders": False})]]
    return {"store": {"config": {"general": {"default_currency": "USD"}}},
            "product": {"sku": "11.20.001.18", "name": "Jersey undefined", "enabled": "1",
                        "attributes": attributes(url_key="jersey", color_details="Black", gender="Men"),
                        "pricing": {"final_price": 200}, "childsProducts": children}}


def assos_page(data):
    product = data["product"]
    quoted = {"@type": "Product", "sku": product["sku"],
              "offers": {"price": product["pricing"]["final_price"], "priceCurrency": "USD"}}
    return ('<meta property="og:image" content="https://www.assos.com/jersey.jpg">'
            '<script>window.INITIAL_STATE = ' + json.dumps(data)[:-1] + ',"unused":undefined};</script>'
            '<script type="application/ld+json">' + json.dumps(quoted) + '</script>')


def kask_page(*, disabled=False, wrong_price=False, wrong_sku=False):
    sku = "CHE00097-CE-WG-494.58"
    telemetry = [{"item_id": "CHE00097-", "item_variant": sku, "item_name": "Protone Icon", "price": 275}]
    return ('<select id="countrySelector-language-select"><option selected value=\''
            + json.dumps({"currencyCode": "EUR", "locale": "en_IT"}) + "'>English</option></select>"
            '<div class="product-detail" data-pid="' + sku + '" data-absurl="https://www.kask.com/en-it/Protone-Icon/' + sku + '.html">'
            '<h1>Protone Icon</h1><div class="price"><span class="sales">'
            '<span class="value" content="275.00">€ ' + ("250,00" if wrong_price else "275,00") + '</span></span></div>'
            '<div data-attr="size"><button data-attr-value="56">S</button>'
            '<button class="selected" data-attr-value="58">M</button><button data-attr-value="62">L</button></div>'
            '<span data-selected-swatch="Yellow"></span><img itemprop="image" src="/helmet.jpg">'
            '<button class="add-to-cart" data-pid="' + ("wrong" if wrong_sku else sku) + '"'
            ' data-in-stock-label="Add to Cart" data-out-stock-label="Out of Stock"' + (' disabled' if disabled else '') + '>'
            + ('Out of Stock' if disabled else 'Add to Cart') + '</button></div>'
            '<script>window.pdpProduct = ' + json.dumps(telemetry) + ';</script>')


class EmbeddedCatalogTests(unittest.TestCase):
    def test_pns_chunked_rsc_has_individual_size_price_and_stock(self):
        page, _, _ = pns_page()
        rows = parse_pns(page, {"code": "pns", "name": "PNS"}, "https://pasnormalstudios.com/eu/products/jersey-olive", NOW)
        self.assertEqual([(r.identity.size, int(r.price.amount), r.stock) for r in rows],
                         [("S", 190, "in_stock"), ("M", 200, "out_of_stock")])
        self.assertTrue(all(r.identity.mpn is None and r.shipping is None and r.tax is None
                            and r.shipping_to_china.status == "unknown" for r in rows))
        self.assertTrue(all(r.original_price.currency == "EUR" for r in rows))

    def test_pns_does_not_import_other_product_or_currency(self):
        page, _, _ = pns_page()
        url = "https://pasnormalstudios.com/eu/products/jersey-olive"
        self.assertEqual(parse_pns(page, {"code": "pns", "name": "PNS"}, url + "-other", NOW), [])
        self.assertEqual(parse_pns(page, {"code": "pns", "name": "PNS", "currency": "USD"}, url, NOW), [])

    def test_pns_unknown_stock_and_cross_currency_original_stay_unknown(self):
        _, product, detail = pns_page()
        product["variants"][0].pop("availableForSale")
        product["variants"][0]["compareAtPrice"]["currencyCode"] = "USD"
        product["variants"][1]["price"]["amount"] = "NaN"
        page, _, _ = pns_page(product, detail)
        rows = parse_pns(page, {"code": "pns", "name": "PNS"}, "https://pasnormalstudios.com/eu/products/jersey-olive", NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].stock, "unknown")
        self.assertIsNone(rows[0].original_price)

    def test_pns_coming_soon_does_not_claim_in_stock(self):
        _, product, detail = pns_page()
        detail["selfProductGrid"]["tags"]["isComingSoon"] = True
        page, _, _ = pns_page(product, detail)
        rows = parse_pns(page, {"code": "pns", "name": "PNS"}, "https://pasnormalstudios.com/eu/products/jersey-olive", NOW)
        self.assertTrue(all(r.stock == "out_of_stock" and r.purchase_requirements for r in rows))

    def test_assos_child_prices_gtin_and_missing_stock(self):
        rows = parse_assos(assos_page(assos_data()), {"code": "assos", "name": "ASSOS"}, "https://www.assos.com/int/jersey.html", NOW)
        self.assertEqual([r.stock for r in rows], ["in_stock", "out_of_stock", "unknown"])
        self.assertEqual([int(r.price.amount) for r in rows], [200, 210, 220])
        self.assertEqual(rows[0].name, "Jersey undefined")
        self.assertEqual(rows[0].identity.gtin, "7627776069838")
        self.assertEqual({r.identity.mpn for r in rows}, {"11.20.001.18"})
        self.assertTrue(all(r.shipping is None and r.tax is None for r in rows))

    def test_assos_rejects_currency_and_sku_mismatches(self):
        data = assos_data()
        data["store"]["config"]["general"]["default_currency"] = "EUR"
        self.assertEqual(parse_assos(assos_page(data), {"code": "assos", "name": "ASSOS"}, "https://www.assos.com/int/jersey.html", NOW), [])
        data = assos_data()
        data["product"]["childsProducts"][0]["attributes"]["sku"]["value"] = "OTHER.S"
        rows = parse_assos(assos_page(data), {"code": "assos", "name": "ASSOS"}, "https://www.assos.com/int/jersey.html", NOW)
        self.assertEqual(len(rows), 2)

    def test_assos_invalid_gtin_is_not_propagated_and_backorder_not_in_stock(self):
        data = assos_data()
        child = data["product"]["childsProducts"][0]
        child["attributes"]["barcode"]["value"] = "123"
        child["inventory"]["backorders"] = True
        rows = parse_assos(assos_page(data), {"code": "assos", "name": "ASSOS"}, "https://www.assos.com/int/jersey.html", NOW)
        self.assertIsNone(rows[0].identity.gtin)
        self.assertEqual(rows[0].stock, "unknown")

    def test_kask_only_selected_size_with_verified_price(self):
        rows = parse_kask(kask_page(), {"code": "kask", "name": "KASK"}, "https://www.kask.com/en-it/Protone-Icon/CHE00097-.html", NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].identity.size, "M")
        self.assertEqual(rows[0].stock, "in_stock")
        self.assertEqual(rows[0].price.currency, "EUR")
        self.assertIn("494.58.html", rows[0].url)
        self.assertIsNone(rows[0].shipping)

    def test_kask_stock_button_must_match_selected_sku(self):
        source, url = {"code": "kask", "name": "KASK"}, "https://www.kask.com/product.html"
        self.assertEqual(parse_kask(kask_page(disabled=True), source, url, NOW)[0].stock, "out_of_stock")
        self.assertEqual(parse_kask(kask_page(wrong_sku=True), source, url, NOW)[0].stock, "unknown")
        self.assertEqual(parse_kask(kask_page(wrong_price=True), source, url, NOW), [])

    def test_kask_rejects_cross_host_selected_url(self):
        html = kask_page().replace('data-absurl="https://www.kask.com/', 'data-absurl="https://example.com/')
        self.assertEqual(parse_kask(html, {"code": "kask", "name": "KASK"}, "https://www.kask.com/product.html", NOW), [])


if __name__ == "__main__":
    unittest.main()
