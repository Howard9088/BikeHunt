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
        values = dict(offer_id=identifier, source_code=source, source_name='Test Brand Merchant' if source == 'brand' else 'Test Team Merchant',
                      identity=ProductIdentity(brand='Test', model=name, mpn=name, size='L', color='Black'),
                      name=name, url='https://merchant.invalid/'+identifier,
                      image=None, price=Money(amount=price, currency='USD'),
                      original_price=Money(amount=original, currency='USD') if original else None,
                      stock='in_stock', fetched_at=now)
        values.update(changes)
        return Offer(**values)
    sale = offer('sale')
    offers = [sale, offer('cheaper', price='50', original=None, identity=sale.identity.model_copy(update={'size':'M'})),
              offer('hoodie', name='Stamp Hoodie', price='99', original=None),
              offer('stale', name='Stale Jersey', source='team', fetched_at=now-timedelta(hours=2)),
              offer('retained', name='Retained Jersey', source='team', collection_state='retained'),
              offer('sold', name='Sold Jersey', source='team', stock='out_of_stock')]
    catalog = ComparisonCatalog(offers, fx, now)
    cards = catalog.search()
    return {'catalog': {'items':[card.model_dump(mode='json') for card in cards], 'fx':fx.model_dump(mode='json'),
                        'categories':CATEGORIES, 'source_count':2},
            'details': {card.product_id:catalog.compare(card.product_id,card.reference_variant_id).model_dump(mode='json') for card in cards},
            'directories': {'brands':[{'code':'brand','name':'Test Brand','name_zh':'测试品牌','offer_count':3,'product_count':2,'rule_count':0}],
                            'teams':[{'code':'team','name':'Test Team','name_zh':'测试车队','offer_count':3,'product_count':3,'rule_count':0}]}}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass


def oakley_fixture():
    """Real selected variants evaluated at their historical observation time."""
    from app.browse_taxonomy import CATEGORY_GROUPS
    payload=json.loads((ROOT/'data/offers/oakley.json').read_text(encoding='utf-8'))
    observed=datetime(2026,10,16,12,2,10,tzinfo=timezone.utc)
    now=datetime(2026,10,16,12,5,55,tzinfo=timezone.utc)
    offers=[Offer.model_validate(row) for row in payload['offers']]
    assert len(offers)==24 and sum(row.stock=='in_stock' for row in offers)==23
    assert all(row.source_code=='oakley' and row.fetched_at==observed for row in offers)
    assert all(row.stock_quantity is None for row in offers),'Units=0 is not a stock quantity'
    assert all(row.price.currency=='USD' and row.sales_region=='美国站 USD 报价' for row in offers)
    assert all(row.shipping_to_china.status=='no' and row.china_issued_card.status=='unknown' for row in offers)
    assert all(urlparse(row.url).scheme=='https' and urlparse(row.url).netloc=='www.oakley.com' and urlparse(row.url).path.startswith('/en-us/product/') and not urlparse(row.url).query and not urlparse(row.url).fragment for row in offers)
    target='https://www.oakley.com/en-us/product/FOS902243'
    sale_target='https://www.oakley.com/en-us/product/FOA406782'
    sold_target='https://www.oakley.com/en-us/product/FOS902123'
    selected=next(row for row in offers if row.url==target);sale=next(row for row in offers if row.url==sale_target);sold=next(row for row in offers if row.url==sold_target)
    assert selected.name==selected.identity.model=='VELO MACH MIPS'
    assert (selected.identity.size,selected.identity.color,selected.price.amount,selected.stock)==('L','Black/Red Pro',Decimal('340'),'in_stock')
    assert (sale.name,sale.identity.size,sale.identity.color,sale.price.amount,sale.original_price.amount,sale.original_price.currency)==('Endurance Mix Jersey','XL','White',Decimal('152'),Decimal('190'),'USD')
    assert sold.stock=='out_of_stock' and sold.identity.size=='L'
    assert [row.offer_id for row in offers if row.original_price and row.original_price.amount>row.price.amount]==[sale.offer_id]
    fx=FxSnapshot(snapshot_id='oakley-observation-fixture',rate_date=now.date().isoformat(),fetched_at=now,rates={'USD':Decimal(7),'CNY':Decimal(1)})
    catalog=ComparisonCatalog(offers,fx,now,public_only=True);cards=catalog.search()
    assert len(cards)==24
    assert sum(card.category_group=='helmets' for card in cards)==20
    assert sum(card.category_group=='clothing' for card in cards)==4
    assert all(card.source_codes==['oakley'] and card.variant_count==1 for card in cards)
    details={card.product_id:catalog.compare(card.product_id,card.reference_variant_id).model_dump(mode='json') for card in cards}
    chosen={label:next(card for card in cards if card.reference_url==url).model_dump(mode='json') for label,url in [('selected',target),('sale',sale_target),('sold',sold_target)]}
    assert chosen['selected']['category']=='helmets' and chosen['selected']['category_group']=='helmets'
    assert chosen['sale']['category_group']=='clothing' and chosen['sale']['discount_pct']==20
    assert chosen['selected']['reference_original_price'] is None
    assert all(card.recommended_total_cny is None for card in cards)
    directory=json.loads((ROOT/'data/directories.json').read_text(encoding='utf-8'));oakley=next(row for row in directory['brands'] if row['code']=='oakley')
    assert oakley.get('source_codes',['oakley'])==['oakley']
    return {'catalog':{'items':[card.model_dump(mode='json') for card in cards],'fx':fx.model_dump(mode='json'),'categories':CATEGORIES,'category_groups':CATEGORY_GROUPS,'source_count':1},'details':details,'directories':{'brands':[oakley],'teams':[]},'chosen':chosen,'clock_ms':int(now.timestamp()*1000),'images':{row.image for row in offers if row.image},'detail_requests':[]}


def exercise_oakley_flow(browser,base,mode,viewport,checks,errors):
    """Isolated Oakley real-data flow; external navigation is fulfilled locally."""
    from urllib.parse import parse_qs
    from exit_dialog_test_support import (assert_exit_closed,assert_exit_focus_trap,open_final_exit,cancel_exit_dialog,confirm_exit_dialog)
    state=oakley_fixture();chosen=state['chosen']['selected'];sale=state['chosen']['sale'];sold=state['chosen']['sold'];target=chosen['reference_url']
    available=[card for card in state['catalog']['items'] if card['reference_stock']=='in_stock']
    outbound,unexpected=[],[]
    context=browser.new_context(viewport=viewport,is_mobile=mode!='desktop',has_touch=mode!='desktop')
    context.set_default_timeout(7000);context.set_default_navigation_timeout(10000)
    context.add_init_script("window.BIKEHUNT_PAGES=true; (() => { const NativeDate=Date, fixed="+str(state['clock_ms'])+"; window.Date=class extends NativeDate { constructor(...args){super(...(args.length?args:[fixed]));} static now(){return fixed;} }; })();")
    def intercept(route):
        url=urlparse(route.request.url)
        if url.netloc!=urlparse(base).netloc:
            if route.request.method=='GET' and route.request.resource_type=='image' and route.request.url in state['images']:
                return route.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><text x="10" y="100">UI test image</text></svg>')
            if route.request.method=='GET' and route.request.is_navigation_request() and route.request.url==target:
                outbound.append(route.request.url)
                return route.fulfill(content_type='text/html',body='<title>Mock Oakley destination</title><p>Navigation fixture only.</p>')
            unexpected.append(route.request.method+' '+route.request.url);return route.abort()
        if not url.path.startswith('/api/'):return route.continue_()
        if url.path=='/api/catalog':result=state['catalog']
        elif url.path.startswith('/api/catalog/'):
            product_id=url.path.rsplit('/',1)[-1];variant_id=parse_qs(url.query).get('variant_id',[None])[0]
            state['detail_requests'].append((product_id,variant_id));result=state['details'].get(product_id)
            if result is None or variant_id is not None and variant_id!=result['variant_id']:return route.fulfill(status=404,content_type='application/json',body='{}')
        elif url.path=='/api/directories':result=state['directories']
        elif url.path.startswith('/api/rules/'):result={'version':1,'documents':[]}
        elif url.path.startswith('/api/fit/'):result={'state':'no_chart','note_zh':'未取得此款服饰尺码表','candidate_sizes':[],'required_measurements':[],'source_url':None,'checked_at':None,'chart_rows':[]}
        elif url.path=='/api/updates':result={'items':[],'cursor':0,'fx':state['catalog']['fx']}
        elif url.path=='/api/community':result={'schema_version':1,'configured':False,'available':False}
        else:result={}
        return route.fulfill(content_type='application/json',body=json.dumps(result))
    def assert_cards(expected):
        expect(page.locator('#grid .card')).to_have_count(len(expected))
        assert set(page.locator('#grid .card').evaluate_all('nodes => nodes.map(node => node.dataset.id)'))=={card['product_id'] for card in expected}
        expect(page.locator(f'#grid .card[data-id="{sold["product_id"]}"]')).to_have_count(0)
    def assert_exact_selected():
        current=page.evaluate("""() => { const detail=currentProduct, offer=detail.offers[0].offer; return {product:detail.product_id,variant:detail.variant_id,name:detail.name,model:offer.identity.model,size:offer.identity.size,color:offer.identity.color,amount:Number(offer.price.amount),currency:offer.price.currency,market:offer.sales_region,url:offer.url,offer:offer.offer_id,source:offer.source_code,stock:offer.stock,quantity:offer.stock_quantity,observed:offer.fetched_at}; }""")
        original=state['details'][chosen['product_id']]['offers'][0]['offer']
        assert current=={'product':chosen['product_id'],'variant':chosen['reference_variant_id'],'name':'VELO MACH MIPS','model':'VELO MACH MIPS','size':'L','color':'Black/Red Pro','amount':340,'currency':'USD','market':'美国站 USD 报价','url':target,'offer':chosen['reference_offer_id'],'source':'oakley','stock':'in_stock','quantity':None,'observed':original['fetched_at']}
    context.route('**/*',intercept);page=context.new_page()
    page.on('pageerror',lambda error:errors.append('Oakley '+mode+': '+str(error)))
    try:
        page.goto(base,wait_until='networkidle')
        expect(page.locator('[data-category-group]')).to_have_text(['骑行服饰','锁鞋','头盔','配件与周边'])
        expect(page.locator('[data-category-group=road_equipment],[data-category]')).to_have_count(0)
        page.locator('[data-tab=brands]').click()
        directory=page.locator('.directory-card[data-source=oakley]')
        expect(directory.locator('.directory-count')).to_contain_text('23 款现货')
        directory.click();assert_cards(available)
        expect(page.locator('#count')).to_have_text('23 件商品')
        expect(page.locator('#channelInfo')).to_be_visible()
        assert page.locator('#channelInfo').get_attribute('open') is None
        expect(page.locator('#grid .card.has-deal')).to_have_count(1)
        deal=page.locator(f'#grid .card[data-id="{sale["product_id"]}"]')
        expect(deal.locator('.discount')).to_have_text('−20%')
        for phrase in ['商家原价','190.00','152.00','XL / White','未取得折扣结束时间']:expect(deal).to_contain_text(phrase)
        expect(deal).not_to_contain_text('限时')
        page.locator('[data-category-group=helmets]').click()
        assert_cards([card for card in available if card['category_group']=='helmets'])
        expect(page.locator('#count')).to_have_text('19 件商品');expect(page.locator('#genderFilter')).to_be_hidden()
        expect(page.locator('#grid .discount')).to_have_count(0)
        page.locator('[data-category-group=clothing]').click()
        assert_cards([card for card in available if card['category_group']=='clothing'])
        expect(page.locator('#count')).to_have_text('4 件商品');expect(page.locator('#genderFilter')).to_be_visible()
        page.locator('[data-category-group=other]').click();assert_cards([])
        page.locator('[data-category-group=cleat_shoes]').click();assert_cards([])
        page.locator('[data-category-group=helmets]').click()
        assert_cards([card for card in available if card['category_group']=='helmets'])
        page.evaluate('([id, variant]) => openProduct(id, variant, true)',[sold['product_id'],sold['reference_variant_id']])
        expect(page.locator('#sheetBody')).to_contain_text('已售罄')
        expect(page.locator('[data-variant],[data-offer],[data-reference-link][href]')).to_have_count(0)
        assert_exit_closed(page);page.locator('#close').click()
        page.locator(f'#grid .card[data-id="{chosen["product_id"]}"] .compare-button').click()
        expect(page.locator('[data-variant]')).to_have_count(1)
        size=page.locator(f'[data-variant="{chosen["reference_variant_id"]}"]')
        expect(size).to_have_text('L');size.click();expect(size).to_have_attribute('aria-pressed','true')
        assert state['detail_requests'][-1]==(chosen['product_id'],chosen['reference_variant_id'])
        assert_exact_selected()
        expect(page.locator('#sheetName')).to_contain_text('VELO MACH MIPS')
        expect(page.locator('.offer .price')).to_contain_text('340.00')
        expect(page.locator('.offer .source-logistics')).to_contain_text('美国站 USD 报价')
        expect(page.locator('#sheetBody')).to_contain_text('Black/Red Pro')
        page.locator(f'[data-offer="{chosen["reference_offer_id"]}"]').click()
        panel=page.locator('#routeComparison');expect(panel).to_be_visible()
        expect(panel.locator('[data-route]')).to_have_count(3)
        expect(panel.locator('[data-route=direct]')).to_have_attribute('data-route-status','prohibited')
        expect(panel.locator('[data-route-select=direct]')).to_be_disabled()
        for phrase in ['尺码 L','Black/Red Pro','美国站 USD 报价']:expect(panel).to_contain_text(phrase)
        assert page.evaluate('routeOptions(guideContext.quote).every(row => row.total === null)')
        assert page.evaluate('guideContext.quote.total_cny === null && !guideContext.quote.eligible')
        expect(page.locator('#routeContinue')).to_be_disabled();assert outbound==[]
        plan=page.locator('[data-route=forwarding]');expect(plan).to_have_attribute('data-route-status','unknown')
        expect(plan.locator('[data-route-select]')).to_have_text('选作待核实计划')
        plan.locator('[data-route-select]').click();expect(page.locator('#routeContinue')).to_be_enabled()
        expect(page.locator('#routeContinue')).to_contain_text('去官网核实');page.locator('#routeContinue').click()
        expect(page.locator('#registrationInterstitial')).to_contain_text('美国站 USD 报价')
        expect(page.locator('#registrationInterstitial form,#registrationInterstitial input')).to_have_count(0)
        page.locator('#registrationCancel').click()
        expect(page.locator('[data-route-select=forwarding]')).to_have_attribute('aria-pressed','true')
        page.locator('#routeContinue').click();open_final_exit(page,target,official=True,image=chosen['image'])
        assert_exit_focus_trap(page)
        assert page.evaluate('externalExitState.options.url')==target and outbound==[]
        page.screenshot(path=str(OUT/f'oakley_exit_{mode}.png'))
        cancel_exit_dialog(page);expect(panel).to_be_visible();expect(page.locator('#routeContinue')).to_be_focused();assert outbound==[]
        page.locator('#routeContinue').click();open_final_exit(page,target,official=True,image=chosen['image'])
        cancel_exit_dialog(page,escape=True);expect(panel).to_be_visible();expect(page.locator('#routeContinue')).to_be_focused();assert outbound==[]
        page.locator('#routeContinue').click();open_final_exit(page,target,official=True,image=chosen['image'])
        original_amount=page.evaluate('guideContext.quote.offer.price.amount')
        page.evaluate("guideContext.quote.offer.price.amount = '341'")
        page.locator('#externalExitConfirm').click()
        expect(page.locator('#externalExitError')).to_be_visible();expect(page.locator('#externalExitConfirm')).to_be_disabled()
        expect(page).to_have_url(base);assert outbound==[]
        page.evaluate('(amount) => { guideContext.quote.offer.price.amount = amount; }',original_amount)
        cancel_exit_dialog(page);page.locator('#routeContinue').click();open_final_exit(page,target,official=True,image=chosen['image'])
        confirm_exit_dialog(page,target,official=True)
        assert outbound==[target] and len(context.pages)==1
        page.go_back(wait_until='networkidle');expect(page).to_have_url(base)
        expect(page.locator('[data-route-select=forwarding]')).to_have_attribute('aria-pressed','true')
        assert page.evaluate("activeSource === 'oakley' && activeCategoryGroup === 'helmets'")
        assert_exact_selected();page.reload(wait_until='networkidle')
        expect(page.locator('[data-route-select=forwarding]')).to_have_attribute('aria-pressed','true')
        assert_exact_selected();page.locator('#routeBack').click();expect(size).to_have_attribute('aria-pressed','true')
        page.locator('#close').click();assert_cards([card for card in available if card['category_group']=='helmets'])
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not unexpected,unexpected
        checks.append(mode+': real Oakley 23 available / 19 helmets / 4 clothing; exact selected identity, only genuine Mix Jersey discount, sold-out excluded, no China direct route, unknown manual plan, cancel/Escape, price mutation guard and mocked same-tab Back/reload')
    finally:
        context.close()


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
                    elif url.path.startswith('/api/catalog/'):result=state['details'].get(url.path.rsplit('/',1)[-1],{})
                    elif url.path.startswith('/api/rules/'):result={'version':1,'documents':[]}
                    elif url.path=='/api/updates':result={'items':[],'cursor':0,'fx':state['catalog']['fx']}
                    elif url.path=='/api/community':result={'schema_version':1,'configured':False,'available':False,'title':'骑游海淘交流群'}
                    else:result={}
                    route.fulfill(content_type='application/json',body=json.dumps(result))
                context.route('**/*',intercept)
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base,wait_until='networkidle')
                expect(page.locator('.card')).to_have_count(4)
                expect(page.locator('#browseLabel')).to_have_text('精选好价')
                deal=page.locator('.card.has-deal').filter(has_text='Sale Jersey')
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
                page.locator('#clear').click();expect(page.locator('#browseLabel')).to_have_text('精选好价');expect(page.locator('.discount')).to_have_count(2)
                page.locator('#q').fill('Stamp Hoodie');page.locator('[data-tab=products]').click()
                expect(page.locator('#q')).to_have_value('');expect(page.locator('#browseLabel')).to_have_text('精选好价');expect(page.locator('.discount')).to_have_count(2)
                page.locator('[data-tab=brands]').click();page.locator('[data-source=brand]').click()
                expect(page.locator('#browseLabel')).to_have_text('测试品牌');expect(page.locator('.card')).to_have_count(2)
                page.locator('#q').fill('Stamp Hoodie');expect(page.locator('.card')).to_have_count(1);expect(page.locator('#browseLabel')).to_have_text('测试品牌')
                page.locator('#clear').click();page.locator('[data-tab=teams]').click();page.locator('[data-source=team]').click()
                expect(page.locator('#browseLabel')).to_have_text('测试车队');expect(page.locator('.card')).to_have_count(2);expect(page.locator('.discount')).to_have_count(1)
                expect(page.locator('#grid')).to_contain_text('Stale Jersey');expect(page.locator('#grid')).to_contain_text('Retained Jersey')
                expect(page.locator('#grid')).not_to_contain_text('Sold Jersey')
                expect(page.locator('#historicalDiscountReferences,#roadReferenceInline')).to_have_count(0)
                page.locator('[data-tab=products]').click();expect(page.locator('.card')).to_have_count(4)
                page.evaluate("for(const card of items){card.fetched_at='2000-01-01T00:00:00Z';for(const quote of Object.values(card.channel_quotes||{}))quote.fetched_at=card.fetched_at;}expireLocalInventory()")
                expect(page.locator('.card')).to_have_count(4)
                expect(page.locator('#count')).to_have_text('4 件渠道精选 · 0 件有折扣')
                expect(page.locator('#historicalDiscountReferences')).to_have_count(0)
                expect(page.locator('.historical-reference-card')).to_have_count(0)
                expect(page.locator('#grid')).not_to_contain_text('暂无已核实有货的渠道精选')
                expect(page.locator('#grid')).not_to_contain_text('Sold Jersey')
                expect(page.locator('.discount')).to_have_count(0)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(OUT/f'featured_empty_{mode}.png'))
                checks.append(mode+': exact fresh discount price/spec; no fake deadline; ordinary global search with Back/reload; clear and featured reset; brand/team reference scope; soldout exclusion; elapsed time preserves last-known stock while expired discounts disappear; exact stale detail and focus restoration; no sold-out or unknown stock promoted into availability')
                # The same production render handles non-discount recommendations,
                # narrow model samples, stale labels and exact-spec detail routing.
                page.evaluate("""() => {
                  const base=items.find(p=>p.name==='Sale Jersey');
                  items=[100,200,300].map((price,i)=>({...base,product_id:'helmet-'+i,name:'Helmet '+i,name_zh:'头盔 '+i,brand:'Helmet Brand '+i,category:'helmets',category_group:'helmets',gender:'unisex',reference_cny:String(price),reference_price:{amount:String(price/7),currency:'USD'},reference_original_price:null,reference_url:'https://merchant.invalid/helmet-'+i,reference_stock:'in_stock',stock_state:'in_stock',reference_collection_state:'current',fetched_at:new Date().toISOString(),reference_price_valid_until:null,reference_variant_id:'helmet-variant-'+i}));
                  for(const card of items){delete card.channel_quotes;card.discount_pct=null;}
                  render();window.__openedRecommendation=null;openProduct=(id,variant)=>{window.__openedRecommendation={id,variant}};
                }""")
                expect(page.locator('.card')).to_have_count(2)
                expect(page.locator('.low-price-label')).to_have_count(2)
                expect(page.locator('.discount')).to_have_count(0)
                expect(page.locator('#count')).to_have_text('2 件渠道精选 · 0 件有折扣')
                first=page.locator('.card').first
                expect(first).to_contain_text('参考规格')
                expect(first).not_to_contain_text('商家原价')
                expect(first).to_contain_text('不是同类比价或全网最低价')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                cta=first.locator('.compare-button').bounding_box()
                assert cta and cta['y']+cta['height']<=viewport['height'],cta
                first.locator('.compare-button').click()
                assert page.evaluate('window.__openedRecommendation')=={'id':'helmet-0','variant':'helmet-variant-0'}
                page.screenshot(path=str(OUT/f'channel_selection_{mode}.png'))
                page.evaluate("items[0].reference_stock='out_of_stock';render()")
                expect(page.locator('.card')).to_have_count(2)
                expect(page.locator('[data-id=helmet-0]')).to_have_count(0)
                checks.append(mode+': 2 lower-priced in-stock items per channel; no invented discount; exact variant; sold-out replacement')
                context.close()
            for mode, viewport in [('desktop', {'width': 1440, 'height': 900}), ('mobile', {'width': 390, 'height': 844}), ('small_mobile', {'width': 320, 'height': 740})]:
                exercise_oakley_flow(browser, base, mode, viewport, checks, errors)
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        (OUT/'results.json').write_text(json.dumps({'checks':checks,'errors':errors,'external_requests':external},ensure_ascii=False,indent=2))
    assert not errors,errors
    assert not external,external
    print(json.dumps({'ok':True,'checks':checks},ensure_ascii=False))


if __name__=='__main__':main()
