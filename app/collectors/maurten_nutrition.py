"""Exact, allowlisted Maurten France packs with product-level quote evidence."""
import hashlib
import json
from urllib.parse import urlsplit

from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import evidence, money, offer_id, stock_status
from app.collectors.transport import CollectionError

URL = 'https://www.maurten.com/fr/products/gel-100-box'
BASE_URL = 'https://www.maurten.com/fr/products/'
# Names, SKUs and portions are independently captured from the official pages.
# Prices/stock remain live observations; a newly introduced SKU is not inferred.
PRODUCTS = {
    URL: {
        'sku': '12002', 'name': 'Gel 100', 'portions': 'Boîte de 12 sachets',
        'size': '标准版 · 12袋/盒', 'family_hint': 'maurten-gel100-box-fr',
    },
    BASE_URL + 'gel-160-box': {
        'sku': '12103', 'name': 'Gel 160', 'portions': 'Boîte de 12 portions',
        'size': '标准版 · 12袋/盒', 'family_hint': 'maurten-gel160-box-fr',
    },
    BASE_URL + 'gel-100-caf-100-box': {
        'sku': '13002', 'name': 'Gel 100 Caf 100', 'portions': 'Boîte de 12 sachets',
        'size': 'Caf 100咖啡因版 · 12袋/盒', 'family_hint': 'maurten-gel100-caf100-box-fr',
    },
    BASE_URL + 'drink-mix-160': {
        'sku': '10102', 'name': 'Drink Mix 160', 'portions': 'Box of 18 servings',
        'size': '标准版 · 18袋/盒', 'family_hint': 'maurten-drinkmix160-box-fr',
    },
    BASE_URL + 'drink-mix-320': {
        'sku': '10202', 'name': 'Drink Mix 320', 'portions': 'Box of 14 servings',
        'size': '标准版 · 14袋/盒', 'family_hint': 'maurten-drinkmix320-box-fr',
    },
}


def _text(node):
    return ' '.join(' '.join(node.css('::text').getall()).split())


def parse_maurten_nutrition(html, source, page_url, fetched_at):
    if source.get('code') != 'maurten_nutrition':
        raise CollectionError('Maurten nutrition source mismatch')
    spec = PRODUCTS.get(page_url)
    if spec is None:
        raise CollectionError('Maurten nutrition market URL mismatch')
    page = Selector(html)
    # /fr is a language path, and EUR is also used in other countries. Both
    # selected-market controls must explicitly confirm France, not a country
    # link elsewhere in the footer or the mere presence of EUR in JSON-LD.
    markets = [_text(x) for x in page.css('footer .__market')]
    currencies = [_text(x) for x in page.css('footer .__currency-market .__currency')]
    if not markets or set(markets) != {'France | fr'} or not currencies or set(currencies) != {'France (EUR)'}:
        raise CollectionError('Maurten selected France EUR market not confirmed')
    canonical = page.css('link[rel="canonical"]::attr(href)').getall()
    if canonical != [page_url]:
        raise CollectionError('Maurten canonical market URL mismatch')

    products = []
    for block in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(block)
        except (ValueError, TypeError):
            continue
        nodes = payload.get('@graph', [payload]) if isinstance(payload, dict) else []
        if isinstance(nodes, list):
            products.extend(x for x in nodes if isinstance(x, dict) and x.get('@type') == 'Product')
    matches = [x for x in products if x.get('sku') == spec['sku'] and x.get('url') == page_url
               and x.get('name') == spec['name']]
    if len(matches) != 1:
        raise CollectionError('Maurten exact product identity absent or ambiguous')
    product = matches[0]
    if product.get('mainEntityOfPage') != page_url:
        raise CollectionError('Maurten product page identity changed')

    # Read the pack only within a cart-product block bearing this exact title.
    # Duplicate mobile/desktop presentations are fine only when they agree.
    portions = []
    for info in page.css('.el-add-to-cart__product-info'):
        titles = [_text(x) for x in info.css('.el-add-to-cart__product-title')]
        if titles == [spec['name']]:
            portions.extend(_text(x) for x in info.css('.el-add-to-cart__product-servings'))
    if not portions or set(portions) != {spec['portions']}:
        raise CollectionError('Maurten exact product pack not confirmed')

    quotes = product.get('offers', [])
    if not isinstance(quotes, list) or len(quotes) != 1 or not isinstance(quotes[0], dict):
        raise CollectionError('Maurten exact offer ambiguous')
    quote = quotes[0]
    if (quote.get('@type') != 'Offer' or quote.get('sku') != spec['sku']
            or quote.get('url') != page_url or quote.get('priceCurrency') != 'EUR'):
        raise CollectionError('Maurten market or variant changed')
    price = money(quote.get('price'), quote['priceCurrency'])
    images = product.get('image', [])
    image = images[0] if isinstance(images, list) and images else None
    try:
        image_url = urlsplit(image) if isinstance(image, str) else None
    except ValueError:
        image_url = None
    if (not price or price.amount <= 0 or image_url is None
            or image_url.scheme != 'https' or image_url.netloc != 'maurten.imgix.net'):
        raise CollectionError('Maurten price or official image unavailable')
    availability = quote.get('availability')
    allowed_availability = {
        prefix + status for prefix in ('https://schema.org/', 'http://schema.org/')
        for status in ('InStock', 'OutOfStock', 'SoldOut', 'Discontinued')
    }
    if not isinstance(availability, str) or availability not in allowed_availability:
        raise CollectionError('Maurten exact structured stock unavailable')

    return [Offer(
        offer_id=offer_id(source['code'], page_url, spec['sku']),
        source_code=source['code'], source_name=source['name'],
        identity=ProductIdentity(brand='Maurten', model=spec['name'], size=spec['size']),
        name=spec['name'], url=page_url, image=image, price=price, stock=stock_status(availability),
        fetched_at=fetched_at, family_hint=spec['family_hint'],
        evidence_sha256=hashlib.sha256(html.encode()).hexdigest(), collection_url=page_url, fetch_mode='static',
        sales_region='法国市场 · EUR 报价；中国配送与支付待核实',
        shipping_to_china=evidence(source, 'china_shipping'), china_issued_card=evidence(source, 'china_credit_card'),
        identity_evidence=(f"官方法国选定市场、商品页SKU{spec['sku']}、EUR逐商品报价、"
                           f"{spec['portions']}包装及结构化库存；未混用其他市场"),
        purchase_requirements=[f"{spec['size']}；购买前核对配方、咖啡因和过敏原标签",
                               '运费税费另计；中国配送及食品进口条件待核实'],
    )]
