"""Evidence-bound Pelotan 200 ml spray quote; no licensed imagery is reused."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import evidence, money, offer_id

_HANDLE = 'pelotan-200ml-spray'
_VARIANT = '47674080395595'
_BASE = 'https://pelotan.cc/products/' + _HANDLE


def parse_pelotan(html: str, source: dict, url: str,
                  fetched_at: datetime) -> list[Offer]:
    """Require exact product/variant, GBP market, price and availability joins."""
    if source.get('code') != 'pelotan':
        return []
    try:
        return _parse(html, source, url, fetched_at)
    except (KeyError, ValueError, TypeError, AttributeError, IndexError):
        return []


def _parse(html: str, source: dict, url: str, fetched_at: datetime) -> list[Offer]:
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'pelotan.cc'
            or parsed.path != '/products/' + _HANDLE
            or parse_qs(parsed.query) not in ({}, {'variant': [_VARIANT]})):
        return []
    page = Selector(html)
    blocks = page.css('script[data-product-json]::text').getall()
    if len(blocks) != 1:
        return []
    product = json.loads(blocks[0])
    if (product['handle'] != _HANDLE or str(product['id']) != '8848550527307'
            or product['title'] != 'Pelotan 200ml Spray'
            or product['vendor'] != 'Pelotan Limited'):
        return []
    currencies = []
    for script in page.css('script::text').getall():
        for match in re.finditer(r'Shopify\.currency\s*=\s*', script):
            currencies.append(json.JSONDecoder().raw_decode(script[match.end():])[0]['active'])
    if not currencies or any(c != 'GBP' for c in currencies):
        return []
    variants = [v for v in product['variants'] if str(v['id']) == _VARIANT]
    if len(variants) != 1:
        return []
    variant = variants[0]
    if (type(variant['price']) is not int or variant['price'] <= 0
            or type(variant['available']) is not bool
            or variant.get('requires_selling_plan') is not False):
        return []
    structured = []
    for block in page.css('script[type="application/ld+json"]::text').getall():
        data = json.loads(block)
        if isinstance(data, dict) and data.get('@type') == 'Product':
            structured.append(data)
    if len(structured) != 1:
        return []
    data = structured[0]
    if data['name'] != product['title'] or data['url'] != _BASE:
        return []
    variant_url = _BASE + '?variant=' + _VARIANT
    quotes = [q for q in data['offers'] if q.get('url') == variant_url]
    if len(quotes) != 1:
        return []
    quote = quotes[0]
    price = money(quote['price'], quote['priceCurrency'])
    if (not price or price.currency != 'GBP'
            or price.amount != Decimal(variant['price']) / 100
            or quote['sku'] != variant['sku']):
        return []
    stock = 'InStock' if variant['available'] else 'OutOfStock'
    if quote['availability'].rsplit('/', 1)[-1] != stock:
        return []
    gtin = str(quote.get('gtin13', ''))
    if not gtin or gtin != str(variant.get('barcode', '')):
        return []
    return [Offer(
        offer_id=offer_id(source['code'], variant_url, _VARIANT),
        source_code=source['code'], source_name=source['name'],
        identity=ProductIdentity(brand='Pelotan', model='200ml Spray', gtin=gtin,
                                 size='200 ml · 喷雾 · 单瓶'),
        name='Pelotan 200ml Spray', url=variant_url, image=None, price=price,
        stock='in_stock' if variant['available'] else 'out_of_stock',
        shipping_to_china=evidence(source, 'china_shipping'),
        china_issued_card=evidence(source, 'china_credit_card'),
        fetched_at=fetched_at, price_valid_until=quote.get('priceValidUntil'),
        fetch_mode='static', collection_url=url,
        evidence_sha256=hashlib.sha256(html.encode()).hexdigest(),
        family_hint='pelotan:200ml-spray', sales_region='UK',
        identity_evidence='Official Shopify product variant and JSON-LD match variant ID, SKU, GTIN, GBP price and stock. Single 200 ml spray.',
    )]
