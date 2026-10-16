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
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import expect, sync_playwright
from app.catalog.models import FxSnapshot, Money, Offer, ProductIdentity
from app.catalog.service import ComparisonCatalog
from app.localization import CATEGORIES
from app.public_visibility import public_category_groups
from exit_dialog_test_support import (assert_exit_closed, assert_exit_focus_trap, open_final_exit, cancel_exit_dialog)

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
        # Brand -> homepage -> global category must not retain the homepage cap.
        page.locator('[data-tab=products]').click()
        assert page.evaluate('activeSource === null && activeCategoryGroup === null && featuredBrowse()')
        expect(page.locator('#q')).to_have_value('')
        expect(page.locator('#grid .card')).to_have_count(2)
        page.locator('[data-category-group=helmets]').click()
        assert page.evaluate('activeSource === null && !featuredBrowse()')
        assert_cards([card for card in available if card['category_group'] == 'helmets'])
        expect(page.locator('#count')).to_have_text('19 件商品')
        expect(page.locator('#grid .low-price-label')).to_have_count(0)
        expect(page.locator('#genderFilter')).to_be_hidden()
        page.locator('#q').fill('VELO MACH MIPS')
        expected_search = [card for card in available if card['category_group'] == 'helmets'
                           and all(term in ' '.join(str(card.get(key) or '') for key in ('brand', 'name', 'name_zh', 'color')).lower()
                                   for term in ('velo', 'mach', 'mips'))]
        assert_cards(expected_search)
        expect(page.locator(f'#grid .card[data-id="{chosen["product_id"]}"]')).to_have_count(1)
        page.locator('#clear').click()
        assert_cards([card for card in available if card['category_group'] == 'helmets'])
        page.locator('[data-category-group=helmets]').click()
        expect(page.locator('#grid .card')).to_have_count(2)
        assert page.evaluate('activeSource === null && activeCategoryGroup === null && featuredBrowse()')
        checks.append(mode + ': Oakley brand reset keeps two homepage selections; global helmets exposes all 19 reliable products; category search intersects without a cap; toggling off restores homepage selection')
        checks.append(mode+': real Oakley 23 available / 19 helmets / 4 clothing; exact selected identity, only genuine Mix Jersey discount, sold-out excluded, no China direct route, unknown manual plan, cancel/Escape, price mutation guard and mocked same-tab Back/reload')
    finally:
        context.close()


# Frozen replay of the committed manual capture, not a fresh stock verification.
GOBIK_FACTORY_URL = 'https://gobik.com/en/products/short-sleeve-jersey-cx-pro-4-0-unisex-gobik-factory-team-26'
GOBIK_FACTORY_IMAGE = 'https://gobik.com/cdn/shop/files/short-sleeve-jersey-cx-pro-4-0-men-gobik-factory-team-26-01.jpg?v=1767891796&width=1500'


def gobik_fixture():
    """Use real selected-size observations unchanged; only FX/image bytes are synthetic."""
    path = ROOT / 'data/offers/gobik.json'
    captured_bytes = path.read_bytes()
    payload = json.loads(captured_bytes)
    offers = [Offer.model_validate(row) for row in payload['offers']]
    assert len(offers) == 19
    assert len({row.offer_id for row in offers}) == 19
    assert len({row.url for row in offers}) == 19
    assert all(row.source_code == 'gobik' and row.identity.brand == 'Gobik'
               and row.sales_region == '西班牙站 EUR 报价' and row.price.currency == 'EUR'
               and row.fetched_at is not None and row.fetched_at.tzinfo is not None
               for row in offers)
    factory = next(row for row in offers if row.url == GOBIK_FACTORY_URL)
    assert factory.identity.size == 'XS'
    assert factory.price.amount == Decimal('85')
    assert factory.original_price is None
    assert factory.image == GOBIK_FACTORY_IMAGE
    assert not urlparse(factory.url).query, 'Do not invent an official variant URL'
    replay_time = max(row.fetched_at for row in offers)
    # Synthetic conversion only, explicitly labelled and never written to production.
    fx = FxSnapshot(snapshot_id='synthetic-gobik-ui-replay', rate_date=replay_time.date().isoformat(),
                    fetched_at=replay_time, rates={'EUR': Decimal('8'), 'CNY': Decimal('1')},
                    source='Synthetic UI test fixture', note='Synthetic EUR rate for UI replay only')
    catalog = ComparisonCatalog(offers, fx, replay_time, public_only=True)
    cards = catalog.search()
    assert len(cards) == 19 and len({card.product_id for card in cards}) == 19
    assert {card.reference_offer_id for card in cards} == {row.offer_id for row in offers}
    assert all(card.variant_count == 1 for card in cards), 'One actually observed size per product'
    details = {card.product_id: catalog.compare(card.product_id, card.reference_variant_id).model_dump(mode='json')
               for card in cards}
    directory = json.loads((ROOT / 'data/directories.json').read_text(encoding='utf-8'))
    entries = [row for row in directory['brands'] if row['code'] == 'gobik']
    assert len(entries) == 1 and entries[0]['source_codes'] == ['gobik']
    entry = dict(entries[0], product_count=19, offer_count=19, rule_count=0)
    factory_card = next(card for card in cards if card.reference_offer_id == factory.offer_id)
    return {'catalog': {'items': [card.model_dump(mode='json') for card in cards],
                        'fx': fx.model_dump(mode='json'), 'categories': CATEGORIES,
                        'category_groups': public_category_groups(), 'source_count': 1},
            'details': details, 'directories': {'brands': [entry], 'teams': []},
            'factory': factory_card.model_dump(mode='json'), 'replay_time': replay_time,
            'images': {row.image for row in offers if row.image}, 'requests': [],
            'captured_bytes': captured_bytes}


def exercise_gobik_catalog(browser, base, checks, errors, external):
    """Exercise the new brand independently of every original featured-deals fixture."""
    for mode, viewport in [('desktop', {'width': 1440, 'height': 900}),
                           ('mobile', {'width': 390, 'height': 844}),
                           ('small_mobile', {'width': 320, 'height': 740})]:
        state = gobik_fixture()
        selected = state['factory']
        product_id, variant_id, offer_id = (selected[key] for key in
                                           ['product_id', 'reference_variant_id', 'reference_offer_id'])
        context = browser.new_context(viewport=viewport, is_mobile=mode != 'desktop',
                                      has_touch=mode != 'desktop', service_workers='block')
        context.set_default_timeout(7000)
        context.add_init_script('window.BIKEHUNT_PAGES=true;')
        mocked_images = []

        def intercept(route):
            parsed = urlparse(route.request.url)
            if parsed.netloc != urlparse(base).netloc:
                # Preserve the exact observed photo URL. Synthetic image bytes make
                # this a hermetic identity/layout test, not a merchant image fetch.
                if route.request.method == 'GET' and route.request.resource_type == 'image' and route.request.url in state['images']:
                    mocked_images.append(route.request.url)
                    return route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><text x="10" y="30">Synthetic UI image fixture</text></svg>')
                external.append(route.request.url)
                return route.abort()
            if not parsed.path.startswith('/api/'):
                return route.continue_()
            if parsed.path == '/api/catalog':
                value = state['catalog']
            elif parsed.path.startswith('/api/catalog/'):
                requested_id = parsed.path.rsplit('/', 1)[-1]
                requested_variant = parse_qs(parsed.query).get('variant_id', [None])[0]
                value = state['details'].get(requested_id)
                if value is None or requested_variant and requested_variant != value['variant_id']:
                    return route.fulfill(status=404, content_type='application/json', body='{}')
                state['requests'].append((requested_id, requested_variant))
            elif parsed.path == '/api/directories':
                value = state['directories']
            elif parsed.path.startswith('/api/rules/'):
                value = {'version': 1, 'documents': []}
            elif parsed.path.startswith('/api/fit/'):
                value = {'state': 'no_chart', 'note_zh': '界面回放测试，无合成尺码建议',
                         'candidate_sizes': [], 'required_measurements': [], 'chart_rows': [],
                         'source_url': None, 'checked_at': None}
            elif parsed.path == '/api/updates':
                value = {'items': [], 'cursor': 0, 'fx': state['catalog']['fx']}
            elif parsed.path == '/api/community':
                value = {'schema_version': 1, 'configured': False, 'available': False}
            else:
                value = {}
            return route.fulfill(content_type='application/json', body=json.dumps(value))

        context.route('**/*', intercept)
        page = context.new_page()
        page.clock.set_fixed_time(state['replay_time'])
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(base, wait_until='networkidle')
            page.locator('[data-tab="brands"]').click()
            brand = page.locator('.directory-card[data-source="gobik"]')
            expect(brand).to_have_count(1)
            expect(brand).to_contain_text('19 款现货')
            brand.click()
            expect(page.locator('#browseLabel')).to_have_text(state['directories']['brands'][0]['name_zh'])
            expect(page.locator('.card')).to_have_count(19)
            rendered = page.locator('.card').evaluate_all('cards => cards.map(card => card.dataset.id)')
            assert len(set(rendered)) == 19
            assert set(rendered) == {card['product_id'] for card in state['catalog']['items']}
            # Every card retains its own captured image, amount and single observed size.
            for item in state['catalog']['items']:
                card = page.locator(f'.card[data-id="{item["product_id"]}"]')
                expect(card.locator('.product-visual img')).to_have_attribute('src', item['image'])
                if item['reference_original_price'] is None:
                    expect(card.locator('.discount,.original-price')).to_have_count(0)
            factory_card = page.locator(f'.card[data-id="{product_id}"]')
            expect(factory_card.locator('.foreign-price')).to_contain_text('85.00')
            expect(factory_card.locator('.foreign-price')).to_contain_text('€')
            expect(factory_card).to_contain_text('XS')
            expect(factory_card).not_to_contain_text('商家原价')
            expect(factory_card.locator('.discount')).to_have_count(0)
            factory_card.locator('.compare-button').click()
            expect(page.locator('#sheetImg')).to_have_attribute('src', GOBIK_FACTORY_IMAGE)
            choice = page.locator(f'[data-variant="{variant_id}"]')
            expect(choice).to_have_text('XS')
            expect(page.locator('[data-variant]')).to_have_count(1)
            choice.click()
            expect(choice).to_have_attribute('aria-pressed', 'true')
            assert state['requests'][-1] == (product_id, variant_id)
            detail = state['details'][product_id]
            actual = page.evaluate('currentProduct')
            assert actual['product_id'] == product_id and actual['variant_id'] == variant_id
            assert actual['identity'] == detail['identity']
            assert len(actual['offers']) == 1
            assert actual['offers'][0]['offer'] == detail['offers'][0]['offer']
            expect(page.locator('.offers')).to_contain_text('西班牙站 EUR 报价')
            expect(page.locator('.offers .price')).to_contain_text('85.00')
            assert_exit_closed(page)
            page.locator(f'[data-offer="{offer_id}"]').click()
            routes = page.locator('#routeComparison')
            expect(routes).to_be_visible()
            expect(routes).to_contain_text('尺码 XS')
            expect(routes).to_contain_text('西班牙站 EUR 报价')
            expect(routes.locator('[data-route]')).to_have_count(3)
            assert page.evaluate('guideContext.quote.offer.url') == GOBIK_FACTORY_URL
            assert page.evaluate('guideContext.quote.offer.fetched_at') == detail['offers'][0]['offer']['fetched_at']
            expect(page.locator('#routeContinue')).to_be_disabled()
            page.locator('[data-route-select="direct"]').click()
            assert page.evaluate('routeOptions(guideContext.quote).every(route => route.total === null)')
            # Repeat with button cancel and Escape; neither may navigate or lose identity.
            for escape in [False, True]:
                page.locator('#routeContinue').click()
                expect(page.locator('#registrationInterstitial')).to_contain_text('西班牙站 EUR 报价')
                expect(page.locator('#registrationInterstitial')).to_contain_text('XS')
                assert_exit_closed(page)
                saved = page.evaluate('history.state.bikehuntPurchase')
                assert (saved['productId'], saved['variantId'], saved['offerId'],
                        saved['sourceCode'], saved['url']) == (product_id, variant_id, offer_id, 'gobik', GOBIK_FACTORY_URL)
                open_final_exit(page, GOBIK_FACTORY_URL, official=True, image=GOBIK_FACTORY_IMAGE)
                assert page.evaluate('externalExitState.url.href') == GOBIK_FACTORY_URL
                assert page.evaluate('externalExitState.options.url') == GOBIK_FACTORY_URL
                assert_exit_focus_trap(page)
                cancel_exit_dialog(page, escape=escape)
                expect(routes).to_be_visible()
                expect(page.locator('#routeContinue')).to_be_focused()
                expect(page.locator('[data-route-select="direct"]')).to_have_attribute('aria-pressed', 'true')
                expect(page).to_have_url(base)
                assert len(context.pages) == 1
                assert not external, 'Gobik replay must never contact or navigate to a merchant'
            page.locator('#routeBack').click()
            expect(page.locator(f'[data-variant="{variant_id}"]')).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('#sheetImg')).to_have_attribute('src', GOBIK_FACTORY_IMAGE)
            assert page.evaluate('currentProduct.offers[0].offer.url') == GOBIK_FACTORY_URL
            assert page.evaluate('currentProduct.offers[0].offer.fetched_at') == detail['offers'][0]['offer']['fetched_at']
            assert GOBIK_FACTORY_IMAGE in mocked_images
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(OUT / f'gobik_identity_synthetic_image_{mode}.png'))
            assert (ROOT / 'data/offers/gobik.json').read_bytes() == state['captured_bytes']
            checks.append(mode + ': Gobik frozen capture replay, 19 distinct single-size cards; Factory Team 26 XS EUR 85 Spain, observed photo URL, no invented discount; exact offer/variant/canonical URL; final cancel/Escape restores focus and selection; no external network; synthetic FX/image bytes, original timestamps unchanged')
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
            exercise_gobik_catalog(browser, base, checks, errors, external)
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        (OUT/'results.json').write_text(json.dumps({'checks':checks,'errors':errors,'external_requests':external},ensure_ascii=False,indent=2))
    assert not errors,errors
    assert not external,external
    print(json.dumps({'ok':True,'checks':checks},ensure_ascii=False))


if __name__=='__main__':main()
