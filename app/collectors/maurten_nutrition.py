"""Exact French-market Gel 100 box; never treat a regional redirect as US stock."""
import hashlib
import json
import re
from urllib.parse import urlsplit
from scrapling.parser import Selector
from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import evidence, money, offer_id, stock_status
from app.collectors.transport import CollectionError

URL = 'https://www.maurten.com/fr/products/gel-100-box'

def parse_maurten_nutrition(html, source, page_url, fetched_at):
    if page_url != URL:
        raise CollectionError('Maurten nutrition market URL mismatch')
    page = Selector(html)
    products = []
    for block in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(block)
        except ValueError:
            continue
        nodes = payload.get('@graph', [payload]) if isinstance(payload, dict) else []
        products.extend(x for x in nodes if isinstance(x, dict) and x.get('@type') == 'Product')
    matches = [x for x in products if x.get('sku') == '12002' and x.get('url') == URL and x.get('name') == 'Gel 100']
    if len(matches) != 1:
        raise CollectionError('Maurten exact product identity absent or ambiguous')
    product = matches[0]
    portions = ' '.join(page.css('.el-add-to-cart__product-servings::text').getall())
    if not re.search(r'Boîte de 12\s+sachets', portions):
        raise CollectionError('Maurten 12-sachet box not confirmed')
    quotes = product.get('offers', [])
    if len(quotes) != 1:
        raise CollectionError('Maurten exact offer ambiguous')
    quote = quotes[0]
    if quote.get('sku') != '12002' or quote.get('url') != URL or quote.get('priceCurrency') != 'EUR':
        raise CollectionError('Maurten market or variant changed')
    price = money(quote.get('price'), quote['priceCurrency'])
    images = product.get('image', [])
    image = images[0] if isinstance(images, list) and images else None
    if not price or not image or urlsplit(image).hostname != 'maurten.imgix.net':
        raise CollectionError('Maurten price or official image unavailable')
    return [Offer(offer_id=offer_id(source['code'], URL, '12002'), source_code=source['code'],
        source_name=source['name'], identity=ProductIdentity(brand='Maurten',model='Gel 100',size='标准版 · 12袋/盒'),
        name='Gel 100', url=URL, image=image, price=price, stock=stock_status(quote.get('availability')),
        fetched_at=fetched_at, family_hint='maurten-gel100-box-fr',
        evidence_sha256=hashlib.sha256(html.encode()).hexdigest(), collection_url=URL, fetch_mode='static',
        sales_region='法国市场 · EUR 报价；中国配送与支付待核实',
        shipping_to_china=evidence(source,'china_shipping'),china_issued_card=evidence(source,'china_credit_card'),
        identity_evidence='官方法国商品页SKU12002、EUR逐商品报价、12袋包装及结构化库存；未混用其他市场',
        purchase_requirements=['12袋/盒标准版本；购买前核对配方、咖啡因和过敏原标签','运费税费另计；中国配送及食品进口条件待核实'])]
