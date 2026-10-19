"""Reviewed Enervit single-product pages; require matching visible SKU, price and stock."""
import hashlib
from urllib.parse import urlsplit
from scrapling.parser import Selector
from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import money, offer_id
from app.collectors.transport import CollectionError

MARKET = '欧洲站 EUR 报价；中国配送与支付待核实'
PRODUCTS = {
 'https://www.enervit.com/en/products/carbo-gel-c-2-1-pro-caffeine.html': {
  'sku':'96631', 'name':'Carbo Gel Cola Caffeine', 'size':'Cola · 100 mg咖啡因 · 60 ml × 1袋',
  'selected_pack':'1 pc', 'pack_evidence':'60 ml pack',
 },
 'https://www.enervit.com/en/products/the-carbo-bar-c-2-1-pro-brownie.html': {
  'sku':'99190', 'name':'Carbo Bar Brownie', 'size':'Brownie · 45 g × 1条',
  'selected_pack':'1 pz', 'pack_evidence':'45 g bar',
 },
 'https://www.enervit.com/en/products/isocarb-c-2-1-pro.html': {
  'sku':'90938', 'name':'Isocarb Lemon', 'size':'Lemon · 650 g × 1罐',
  'selected_pack':'1 pc', 'pack_evidence':'650 g jar',
 },
 'https://www.enervit.com/en/products/carbo-gel-c-2-1-pro-mango.html': {
  'sku':'96651', 'name':'Carbo Gel Mango', 'size':'Mango · 60 ml × 1袋',
  'selected_pack':'1 pz', 'pack_evidence':'60 ml pack',
 },
}

def parse_enervit_nutrition(html, source, page_url, fetched_at):
    if source.get('code') != 'enervit_nutrition' or page_url not in PRODUCTS:
        raise CollectionError('Enervit unreviewed source, product or market')
    p=PRODUCTS[page_url];page=Selector(html)
    def meta(key):return page.css(f'meta[property="{key}"]::attr(content)').get()
    if meta('og:url') != page_url or meta('og:title') != p['name'] or meta('product:price:currency') != 'EUR':
        raise CollectionError('Enervit product or market identity changed')
    forms=page.css('form#product_addtocart_form')
    if len(forms)!=1 or forms[0].attrib.get('data-product-sku')!=p['sku']:
        raise CollectionError('Enervit exact form SKU absent')
    form=forms[0];buttons=form.css('button#product-addtocart-button')
    if len(buttons)!=1:raise CollectionError('Enervit exact purchase control absent')
    button=buttons[0];a=button.attrib
    if a.get('data-simple-id')!=p['sku'] or a.get('data-name')!=p['name'] or a.get('data-store')!='English Store View':
        raise CollectionError('Enervit purchase control identity mismatch')
    price=money(meta('product:price:amount'),'EUR')
    amount=form.css('[data-price-type="finalPrice"]::attr(data-price-amount)').getall()
    if not price or price.amount<=0 or len(amount)!=1 or price!=money(amount[0],'EUR') or price!=money(a.get('data-price'),'EUR'):
        raise CollectionError('Enervit conflicting or absent exact price')
    containers=page.css('.product-info-main')
    if len(containers)!=1:
        raise CollectionError('Enervit exact product container absent or ambiguous')
    container=containers[0]
    if container.css('form#product_addtocart_form::attr(data-product-sku)').getall()!=[p['sku']]:
        raise CollectionError('Enervit package container not bound to exact SKU')
    selected=' '.join(container.css('.variant-swatch a.selected::text').getall()).strip()
    package_labels=[' '.join(' '.join(x.css('::text').getall()).split())
                    for x in container.css('.product-details-accordion [data-role="content"] li')]
    if selected != p['selected_pack'] or p['pack_evidence'] not in package_labels:
        raise CollectionError('Enervit selected package changed or absent')
    stock=a.get('data-dimension10')
    if stock not in ('In stock','Out of stock'):
        raise CollectionError('Enervit stock evidence absent')
    if stock=='In stock' and ('disabled' in a or a.get('aria-disabled')=='true'):
        raise CollectionError('Enervit stock and purchase control conflict')
    image=meta('og:image')
    if not image or urlsplit(image).scheme!='https' or urlsplit(image).hostname!='www.enervit.com' or not urlsplit(image).path.startswith('/media/catalog/product/'):
        raise CollectionError('Enervit official product image absent')
    return [Offer(offer_id=offer_id(source['code'],page_url,p['sku']),source_code=source['code'],source_name=source['name'],
      identity=ProductIdentity(brand='Enervit',model=p['name'],size=p['size']),name=p['name'],url=page_url,image=image,price=price,
      stock='in_stock' if stock=='In stock' else 'out_of_stock',fetched_at=fetched_at,fetch_mode='dynamic',
      family_hint='enervit:'+p['sku'],sales_region=MARKET,evidence_sha256=hashlib.sha256(html.encode()).hexdigest(),collection_url=page_url,
      identity_evidence='Official exact product URL, selected package, form SKU and purchase-control stock/price agree with product metadata.',
      purchase_requirements=['按所选包装核对配方、咖啡因和过敏原标签','运费税费另计；中国配送及食品进口条件待核实'])]
