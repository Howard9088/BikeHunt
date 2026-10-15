"""Hermetic featured-deals Chromium checks; all nonlocal requests are blocked."""
from __future__ import annotations
import json
import os
import shutil
import sys
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import expect, sync_playwright
from app.catalog.models import FxSnapshot, Money, Offer, ProductIdentity
from app.catalog.service import ComparisonCatalog
from app.localization import CATEGORIES

OUT = ROOT / 'artifacts' / 'featured-deals'


def fixture():
    now = datetime.now(timezone.utc)
    fx = FxSnapshot(snapshot_id='featured-fixture', rate_date=now.date().isoformat(), fetched_at=now,
                    rates={'USD': Decimal(7), 'CNY': Decimal(1)})
    def offer(identifier, name='Sale Jersey', price='90', original='120', source='brand', **changes):
        values = dict(offer_id=identifier, source_code=source, source_name='Test Merchant',
                      identity=ProductIdentity(brand='Test', model=name, mpn=name, size='L', color='Black'),
                      name=name, url='https://merchant.invalid/'+identifier,
                      image=None, price=Money(amount=price, currency='USD'),
                      original_price=Money(amount=original, currency='USD') if original else None,
                      stock='in_stock', fetched_at=now)
        values.update(changes)
        return Offer(**values)
    sale = offer('sale')
    offers = [sale, offer('cheaper', price='50', original=None, identity=sale.identity.model_copy(update={'size':'M'})),
              offer('hoodie', name='Stamp Hoodie', price='89', original=None),
              offer('stale', name='Stale Jersey', source='team', fetched_at=now-timedelta(hours=2)),
              offer('retained', name='Retained Jersey', source='team', collection_state='retained'),
              offer('sold', name='Sold Jersey', source='team', stock='out_of_stock')]
    catalog = ComparisonCatalog(offers, fx, now)
    cards = catalog.search()
    return {'catalog': {'items':[card.model_dump(mode='json') for card in cards], 'fx':fx.model_dump(mode='json'),
                        'categories':CATEGORIES, 'source_count':2},
            'directories': {'brands':[{'code':'brand','name':'Test Brand','name_zh':'测试品牌','offer_count':3,'product_count':2,'rule_count':0}],
                            'teams':[{'code':'team','name':'Test Team','name_zh':'测试车队','offer_count':3,'product_count':3,'rule_count':0}]}}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1',0), partial(QuietHandler,directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    base = f'http://127.0.0.1:{server.server_port}/web/'
    errors, checks, external = [], [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'),headless=True)
            for mode, viewport in [('desktop',{'width':1440,'height':900}),('mobile',{'width':390,'height':844}),('small_mobile',{'width':375,'height':667})]:
                state = fixture()
                for card in state['catalog']['items']:card['image']=base+'icons/icon-512.png'
                context = browser.new_context(viewport=viewport,is_mobile=mode!='desktop',has_touch=mode!='desktop')
                context.set_default_timeout(7000)
                context.add_init_script('window.BIKEHUNT_PAGES=true;')
                def intercept(route):
                    url = urlparse(route.request.url)
                    if url.netloc != urlparse(base).netloc:
                        external.append(route.request.url)
                        return route.abort()
                    if not url.path.startswith('/api/'):return route.continue_()
                    if url.path=='/api/catalog':result=state['catalog']
                    elif url.path=='/api/directories':result=state['directories']
                    elif url.path.startswith('/api/rules/'):result={'version':1,'documents':[]}
                    elif url.path=='/api/updates':result={'items':[],'cursor':0,'fx':state['catalog']['fx']}
                    elif url.path=='/api/community':result={'schema_version':1,'configured':False,'available':False,'title':'骑游海淘交流群'}
                    else:result={}
                    route.fulfill(content_type='application/json',body=json.dumps(result))
                context.route('**/*',intercept)
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base,wait_until='networkidle')
                expect(page.locator('.card')).to_have_count(1)
                expect(page.locator('#browseLabel')).to_have_text('精选好价')
                deal=page.locator('.card')
                for text in ['商家原价','120.00','90.00','630.00','−25%','L / Black','未取得折扣结束时间']:
                    expect(deal).to_contain_text(text)
                expect(deal).not_to_contain_text('350.00');expect(deal).not_to_contain_text('限时')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                cta=deal.locator('.compare-button').bounding_box()
                assert cta and cta['y']+cta['height']<=viewport['height'],cta
                page.screenshot(path=str(OUT/f'featured_{mode}.png'))
                page.locator('#q').fill('Stamp Hoodie')
                expect(page.locator('.card')).to_have_count(1);expect(page.locator('#browseLabel')).to_have_text('搜索结果')
                expect(page.locator('.discount')).to_have_count(0)
                page.locator('#wechatCommunity').click();expect(page).to_have_url(base+'group/')
                page.go_back(wait_until='networkidle')
                expect(page.locator('#q')).to_have_value('Stamp Hoodie');expect(page.locator('#browseLabel')).to_have_text('搜索结果');expect(page.locator('.card')).to_have_count(1)
                page.reload(wait_until='networkidle')
                expect(page.locator('#q')).to_have_value('Stamp Hoodie');expect(page.locator('#browseLabel')).to_have_text('搜索结果')
                page.locator('#clear').click();expect(page.locator('#browseLabel')).to_have_text('精选好价');expect(page.locator('.discount')).to_have_count(1)
                page.locator('#q').fill('Stamp Hoodie');page.locator('[data-tab=products]').click()
                expect(page.locator('#q')).to_have_value('');expect(page.locator('#browseLabel')).to_have_text('精选好价');expect(page.locator('.discount')).to_have_count(1)
                page.locator('[data-tab=brands]').click();page.locator('[data-source=brand]').click();page.locator('#sourceProducts').click()
                expect(page.locator('#browseLabel')).to_have_text('测试品牌');expect(page.locator('.card')).to_have_count(2)
                page.locator('#q').fill('Stamp Hoodie');expect(page.locator('.card')).to_have_count(1);expect(page.locator('#browseLabel')).to_have_text('测试品牌')
                page.locator('#clear').click();page.locator('[data-tab=teams]').click();page.locator('[data-source=team]').click();page.locator('#sourceProducts').click()
                expect(page.locator('#browseLabel')).to_have_text('测试车队');expect(page.locator('.card')).to_have_count(2);expect(page.locator('.discount')).to_have_count(0)
                page.locator('[data-tab=products]').click();expect(page.locator('.card')).to_have_count(1)
                page.evaluate("for(const card of items)card.fetched_at='2000-01-01T00:00:00Z';expireLocalInventory()")
                expect(page.locator('.card')).to_have_count(0);expect(page.locator('.empty')).to_contain_text('暂无符合条件的已核实折扣')
                page.screenshot(path=str(OUT/f'featured_empty_{mode}.png'))
                checks.append(mode+': exact fresh discount price/spec; no fake deadline; ordinary global search with Back/reload; clear and featured reset; brand/team reference scope; soldout exclusion; live expiry and honest empty state')
                context.close()
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        (OUT/'results.json').write_text(json.dumps({'checks':checks,'errors':errors,'external_requests':external},ensure_ascii=False,indent=2))
    assert not errors,errors
    assert not external,external
    print(json.dumps({'ok':True,'checks':checks},ensure_ascii=False))


if __name__=='__main__':main()
