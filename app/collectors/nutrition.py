"""Strict, source-bound nutrition variant extraction (no aggregate-price fallback)."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import money, offer_id

_HOST = 'www.scienceinsport.com'
_PATH = '/beta-fuel-80'
_VARIANTS = {'131263': ('6256', '67', 'Orange'),
             '131265': ('6262', '737', 'Strawberry and Lime')}


def _is_variant_url(url: str, sku: str) -> bool:
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.hostname == _HOST
            and parsed.path == _PATH and parse_qs(parsed.query) == {'sku': [sku]})


def parse_nutrition(html: str, source: dict, url: str,
                    fetched_at: datetime) -> list[Offer]:
    """Join SiS JSON-LD to Magento's exact Orange / 15 Pack child.

    The reviewed scope is deliberately two verified SKUs. Missing, ambiguous or conflicting
    evidence produces no quote; stock and prices are read anew on every fetch.
    """
    sku = parse_qs(urlsplit(url).query).get('sku', [''])[0]
    if source.get('code') != 'sis_nutrition' or sku not in _VARIANTS or not _is_variant_url(url, sku):
        return []
    try:
        return _parse_sis(html, source, url, fetched_at, sku)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return []


def _parse_sis(html: str, source: dict, url: str,
               fetched_at: datetime, sku: str) -> list[Offer]:
    child_id, flavour_id, flavour = _VARIANTS[sku]
    page = Selector(html)
    products = []
    for block in page.css('script[type="application/ld+json"]::text').getall():
        # The live source emits literal newlines inside its description string.
        data = json.loads(block, strict=False)
        if isinstance(data, dict) and data.get('@type') == 'Product':
            products.append(data)
    if len(products) != 1:
        return []
    product = products[0]
    if product['name'].strip().casefold() != 'beta fuel 80':
        return []
    quotes = [q for q in product['offers'] if str(q.get('sku')) == sku]
    if len(quotes) != 1 or not _is_variant_url(quotes[0]['url'], sku):
        return []
    quote = quotes[0]
    configs = []
    for script in page.css('script::text').getall():
        for match in re.finditer(r'"jsonConfig"\s*:\s*', script):
            configs.append(json.JSONDecoder().raw_decode(script[match.end():])[0])
    if len(configs) != 1:
        return []
    config = configs[0]
    child = config['index'][child_id]
    if (str(config['sku'][child_id]) != sku
            or str(child['preselect_settings']['sku']) != sku):
        return []
    for attr, code, value, label in (('175', 'flavour', flavour_id, flavour),
                                     ('173', 'pack_size', '18098', '15 Pack')):
        attribute = config['attributes'][attr]
        options = [o for o in attribute['options'] if str(o['id']) == value]
        if (str(child[attr]) != value or attribute['code'] != code or len(options) != 1
                or options[0]['label'] != label or child_id not in options[0]['products']):
            return []
    price = money(quote['price'], quote['priceCurrency'])
    variant_price = money(config['optionPrices'][child_id]['finalPrice']['amount'], 'GBP')
    if not price or price.currency != 'GBP' or price.amount <= 0 or price != variant_price:
        return []
    quantity = child['stock_status_qty']
    if type(quantity) is not int or quantity < 0:
        return []
    available = quote['availability'].rsplit('/', 1)[-1]
    expected = 'InStock' if quantity > 0 else 'OutOfStock'
    if available != expected:
        return []
    disabled = any(child_id in config[key] for key in ('disabledItems', 'disabledProducts', 'oosProducts'))
    salable = all(child_id in config['salable'].get(attr, {}).get(value, [])
                  for attr, value in (('175', flavour_id), ('173', '18098')))
    if (quantity > 0 and (disabled or not salable)) or (quantity == 0 and salable):
        return []
    images = [i for i in config['images'][child_id] if i.get('isMain') is True]
    if len(images) != 1:
        return []
    image = images[0]['img']
    if (urlsplit(image).hostname != _HOST or urlsplit(image).scheme != 'https'
            or urlsplit(image).path != urlsplit(quote['image']).path):
        return []
    return [Offer(
        offer_id=offer_id(source['code'], url, sku),
        source_code=source['code'], source_name=source['name'],
        identity=ProductIdentity(brand='SiS', model='Beta Fuel 80',
                                 size=f'{flavour} / 15 Pack'),
        name='SiS Beta Fuel 80', url=url, image=image,
        price=price, stock='in_stock' if quantity > 0 else 'out_of_stock',
        stock_quantity=quantity, fetched_at=fetched_at, fetch_mode='static',
        evidence_sha256=hashlib.sha256(html.encode()).hexdigest(), collection_url=url,
        family_hint='sis:beta-fuel-80', sales_region='UK',
        identity_evidence=f'SiS official JSON-LD SKU {sku} joined to Magento child {child_id}; flavour {flavour} and 15 Pack, matching price and stock.',
    )]
