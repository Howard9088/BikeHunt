"""Hermetic synthetic Offer fixture: normal nutrition cards, precise variants and no fit UI."""
import json
import os
import shutil
import threading
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import expect, sync_playwright
from test_featured_deals_ui import ROOT, QuietHandler
from app.catalog.models import FxSnapshot, Money, Offer, ProductIdentity
from app.catalog.service import ComparisonCatalog

OUT = ROOT / 'artifacts/nutrition'
URL = 'https://www.scienceinsport.com/beta-fuel-gel-pack'

def fixture(base):
    now = datetime.now(timezone.utc)
    fx = FxSnapshot(snapshot_id='synthetic-nutrition-ui', rate_date=now.date().isoformat(), fetched_at=now,
                    rates={'GBP': Decimal(9), 'CNY': Decimal(1)})
    # Prices and imagery are explicitly synthetic and never written to production data.
    offers = [Offer(offer_id='synthetic-gel-'+flavor, source_code='sis', source_name='Synthetic SiS merchant',
                    identity=ProductIdentity(brand='SiS', model='BETA Fuel Gel', mpn='synthetic-gel', size=flavor+' · 60 ml × 6', color=None),
                    name='BETA Fuel Gel', url=URL, image=base+'icons/icon-512.png',
                    price=Money(amount=str(price), currency='GBP'), stock='in_stock', fetched_at=now)
              for flavor, price in [('Orange', 12), ('Apple', 14)]]
    offers.append(Offer(offer_id='synthetic-sunscreen',source_code='pelotan',source_name='Synthetic Pelotan merchant',
                        identity=ProductIdentity(brand='Pelotan',model='Synthetic sunscreen',mpn='synthetic-sunscreen',size='200 ml',color=None),
                        name='Synthetic sunscreen',url='https://pelotan.invalid/synthetic-sunscreen',image=None,
                        price=Money(amount='20',currency='GBP'),stock='in_stock',fetched_at=now))
    catalog = ComparisonCatalog(offers, fx, now)
    cards = [card.model_dump(mode='json') for card in catalog.search()]
    assert len(cards) == 2, 'Two flavors must remain one nutrition card, plus one sunscreen card'
    details = {}
    for card in cards:
        group = {'category':'sunscreen','category_group':'other'} if card['brand']=='Pelotan' else {'category':'energy_gels','category_group':'nutrition'}
        card.update(group)
        variants = catalog.compare(card['product_id'], card['reference_variant_id']).variants
        for variant in variants:
            detail = catalog.compare(card['product_id'], variant.variant_id).model_dump(mode='json')
            detail.update(group)
            details[variant.variant_id] = detail
    return {'catalog': {'items':cards, 'fx':fx.model_dump(mode='json'), 'source_count':1, 'categories':[]},
            'details': details, 'directories': {'brands':[{'code':'sis','name':'SiS','offer_count':2,'product_count':1,'rule_count':0}], 'teams':[]}}

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1',0), partial(QuietHandler,directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    base = f'http://127.0.0.1:{server.server_port}/web/'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'), headless=True)
            for width, height in [(1440,900),(390,844),(320,740)]:
                state = fixture(base)
                context = browser.new_context(viewport={'width':width,'height':height})
                context.add_init_script('window.BIKEHUNT_PAGES=true;')
                fit_requests, errors = [], []
                def intercept(route):
                    url = urlparse(route.request.url)
                    if url.netloc != urlparse(base).netloc:return route.abort()
                    if not url.path.startswith('/api/'):return route.continue_()
                    if url.path == '/api/catalog':result = state['catalog']
                    elif url.path.startswith('/api/catalog/'):
                        card = next(card for card in state['catalog']['items'] if card['product_id']==url.path.rsplit('/',1)[-1])
                        variant = parse_qs(url.query).get('variant_id',[card['reference_variant_id']])[0]
                        result = state['details'][variant]
                    elif url.path == '/api/directories':result = state['directories']
                    elif url.path.startswith('/api/fit/'):
                        fit_requests.append(url.path);result = {}
                    elif url.path.startswith('/api/rules/'):result = {'version':1,'documents':[]}
                    elif url.path == '/api/updates':result = {'items':[],'cursor':0,'fx':state['catalog']['fx']}
                    else:result = {}
                    return route.fulfill(content_type='application/json',body=json.dumps(result))
                context.route('**/*',intercept)
                page = context.new_page();page.on('pageerror',lambda err:errors.append(str(err)))
                page.goto(base,wait_until='networkidle')
                expect(page.locator('#grid .card')).to_have_count(1)
                expect(page.locator('#grid')).not_to_contain_text('Synthetic sunscreen')
                page.get_by_role('button',name='运动补能',exact=True).click()
                card = page.locator('#grid .card');expect(card).to_have_count(1)
                expect(page.locator('#count')).to_have_text('1 件商品')
                expect(card.locator('img')).to_be_visible()
                assert card.locator('img').evaluate('(img)=>img.complete && img.naturalWidth>0')
                expect(card).to_contain_text('60 ml × 6');expect(card.locator('.best-price')).to_contain_text('108')
                expect(page.locator('.profile-bar')).to_be_hidden()
                expect(page.locator('.nutrition-reference-page')).to_have_count(0)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(OUT/f'nutrition-{width}.png'),full_page=True)
                card.locator('.compare-button').click()
                expect(page.locator('label[for=variant]')).to_have_text('先选现货口味与包装规格')
                expect(page.locator('#variant option')).to_have_count(3)
                expect(page.locator('#sheetBody')).not_to_contain_text('尺码')
                expect(page.locator('#fitReference')).to_have_count(0)
                folded = page.locator('.nutrition-product-reference')
                expect(folded).to_have_count(1);assert not folded.evaluate('(node)=>node.open')
                expect(folded.locator('a')).to_have_count(0)
                apple = next(key for key, detail in state['details'].items() if detail['identity']['size'].startswith('Apple'))
                page.locator('#variant').select_option(apple)
                expect(page.locator('.offers')).to_contain_text('Apple · 60 ml × 6')
                assert page.evaluate('currentProduct.variant_id') == apple
                assert page.evaluate('Number(currentProduct.offers[0].offer.price.amount)') == 14
                expect(page.locator('.offers')).to_contain_text('14.00')
                expect(page.locator('#sheetBody')).not_to_contain_text('身高')
                assert not fit_requests and not errors, (fit_requests,errors)
                page.screenshot(path=str(OUT/f'nutrition-detail-{width}.png'),full_page=True)
                page.locator('#close').click()
                page.get_by_role('searchbox').fill('nonexistent')
                expect(page.locator('#grid .card')).to_have_count(0)
                expect(page.locator('.nutrition-brand-reference')).to_have_count(0)
                expect(page.locator('#count')).to_have_text('0 件商品')
                page.get_by_role('searchbox').fill('')
                page.locator('[data-category-group=other]').click()
                expect(page.locator('#grid .card')).to_have_count(1)
                expect(page.locator('#grid .card img')).to_have_count(0)
                expect(page.locator('.image-permission-pending')).to_have_text('商品图片待授权')
                page.locator('#grid .compare-button').click()
                expect(page.locator('label[for=variant]')).to_have_text('先选现货容量规格')
                expect(page.locator('#fitReference')).to_have_count(0)
                expect(page.locator('#sheetBody')).not_to_contain_text('尺码')
                assert not fit_requests and not errors, (fit_requests,errors)
                context.close()
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
    print('PASS nutrition normal cards: desktop/390/320, image, synthetic price, two exact flavor-pack variants, collapsed evidence, no fit requests, no editorial fallback.')

if __name__ == '__main__':main()
