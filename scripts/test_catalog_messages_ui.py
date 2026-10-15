"""Hermetic Chromium desktop/mobile QA. All merchant requests are mocked."""
from __future__ import annotations
import copy
import json
import os
import shutil
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import expect, sync_playwright
from datetime import datetime, timedelta, timezone
from exit_dialog_test_support import (DISCLAIMER, assert_exit_closed, assert_exit_dialog, cancel_exit_dialog, confirm_exit_dialog, open_final_exit)

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.browse_taxonomy import CATEGORY_GROUPS

OUT=ROOT/'artifacts/acceptance'
AMAZON_SEARCHES = [
    ('amazon_us', 'www.amazon.com', ['road cycling jersey', 'road cycling bib shorts']),
    ('amazon_uk', 'www.amazon.co.uk', ['road cycling jersey', 'road cycling bib shorts']),
    ('amazon_de', 'www.amazon.de', ['Rennrad Trikot', 'Rennrad Trägerhose']),
    ('amazon_jp', 'www.amazon.co.jp', ['ロードバイク サイクルジャージ', 'ロードバイク ビブショーツ']),
]

AMAZON_HELP = {
    'seller': 'https://digprjsurvey.amazon.co.uk/csad/help/node/GEF528GN65XSJ7V8',
    'charges': 'https://digprjsurvey.amazon.co.uk/csad/help/node/G8VRJ7Y8Z3T5WPV3',
    'deposit': 'https://digprjsurvey.amazon.co.uk/csad/help/node/G9UHGT37MYD2EJPL',
    'tracking': 'https://digprjsurvey.amazon.co.uk/csad/help/node/GBPEXEXYULHB5WCH',
}





def fixture():
    now = datetime.now(timezone.utc).isoformat()
    fx = {'rate_date': now[:10], 'stale': False, 'rates': {'AUD': '4.8'}}
    base = {'product_id': 'partial', 'brand': 'MAAP', 'name': 'UI regression fixture · Partial stock',
            'name_zh': '界面回归测试 · 部分现货', 'category': 'bibs', 'category_group': 'clothing', 'gender': 'male',
            'color': '白色', 'image': 'https://merchant.example/product.svg', 'source_count': 1,
            'source_codes': ['maap'], 'variant_count': 3, 'available_sizes': ['S'],
            'reference_price': {'amount': '225', 'currency': 'AUD'}, 'reference_cny': '1080',
            'reference_source': 'MAAP', 'recommended_total_cny': None, 'discount_pct': 40,
            'reference_original_price': {'amount': '375', 'currency': 'AUD'},
            'reference_offer_id': 'offer-s', 'reference_variant_id': 'S', 'reference_size': 'S',
            'reference_color': '白色', 'reference_stock': 'in_stock', 'reference_collection_state': 'current',
            'reference_data_kind': 'live_snapshot', 'reference_price_valid_until': None,
            'fetched_at': now, 'stock_state': 'in_stock'}
    sold = {**base, 'product_id': 'sold-out', 'name': 'Team Bib Evo Cargo White Sold Out',
            'name_zh': '白色背带裤 · 全部售罄测试', 'stock_state': 'out_of_stock', 'available_sizes': []}
    unknown = {**base, 'product_id': 'unknown', 'name': 'Unknown inventory fixture',
               'name_zh': '库存待确认测试', 'stock_state': 'unknown', 'available_sizes': []}
    variants = [{'variant_id': size, 'size': size, 'in_stock': size == 'S',
                 'stock_state': 'in_stock' if size == 'S' else 'out_of_stock' if size == 'M' else 'unknown',
                 'source_count': 1, 'product_cny_from': '1080' if size == 'S' else None}
                for size in ['S', 'M', 'XL']]
    check = {'status': 'unknown', 'note': '测试规则', 'url': 'https://merchant.example/policy'}
    offer = {'offer_id': 'offer-s', 'source_code': 'maap', 'source_name': 'MAAP',
             'url': 'https://merchant.example/bib?variant=S', 'stock': 'in_stock',
             'collection_state': 'current', 'price': base['reference_price'], 'original_price': base['reference_original_price'], 'fetched_at': now,
             'shipping_to_china': check, 'china_issued_card': check, 'accepted_card_networks': ['Visa'],
             'purchase_requirements': [], 'identity_evidence': '回归测试数据'}
    detail = {'product_id': 'partial', 'variant_id': 'S', 'name': base['name'], 'name_zh': base['name_zh'],
              'category': 'bibs', 'category_group': 'clothing', 'image': base['image'], 'identity': {'brand': 'MAAP', 'size': 'S', 'color': '白色'},
              'variants': variants, 'colors': [], 'fx': fx, 'recommended_offer_id': None,
              'offers': [{'offer': offer, 'eligible': False, 'reasons': [], 'product_cny': '1080',
                          'shipping_cny': None, 'tax_cny': None, 'total_cny': None}]}
    return {'catalog': {'items': [base, sold, unknown], 'fx': fx, 'source_count': 1,
                        'category_groups': copy.deepcopy(CATEGORY_GROUPS),
                        'categories': [{'code': 'all', 'name': '全部'}, {'code': 'bibs', 'name': '骑行裤'}]},
            'detail': detail}


def assert_single_category_layer(page):
    """The only category controls are the five exact public groups, in order."""
    groups = page.locator('#categoryGroupNav [data-category-group]')
    expect(groups).to_have_text(['自行车', '骑行服饰', '锁鞋', '头盔', '配件与周边'])
    assert groups.evaluate_all('buttons => buttons.map(button => button.dataset.categoryGroup)') == [
        'road_equipment', 'clothing', 'cleat_shoes', 'helmets', 'other']
    expect(page.locator('#categoryNav,[data-category]')).to_have_count(0)
    assert page.evaluate("activeCategory === 'all'")


def assert_card_ids(page, identifiers):
    """Check the whole scope, including exclusions, rather than only its size."""
    expect(page.locator('.card')).to_have_count(len(identifiers))
    assert set(page.locator('.card').evaluate_all('cards => cards.map(card => card.dataset.id)')) == set(identifiers)


def detail_for_request(state, product_id, variant_id=''):
    """Bind mock details to declared cards/events; never return another family.

    Ordinary cards deliberately share the single S offer fixture. Their family
    IDs and names must still match the requested card, just like the real API.
    Unsupported IDs/variants fail rather than silently returning the S quote.
    """
    matching = next((event for event in state.get('events', [])
                     if event['product'].get('product_id') == product_id
                     and event['product'].get('variant_id') == variant_id), None)
    result = copy.deepcopy(state['detail'])
    if matching:
        product = matching['product']
        result.update(product_id=product_id, variant_id=variant_id,
                      name=product['name'], name_zh=matching['name_zh'], image=product['image'],
                      category=matching['category'], category_group='clothing')
        result['identity'].update(size=product['size'], color=product['color'], mpn=product['model'])
        result['variants'] = [{'variant_id': variant_id, 'size': product['size'], 'in_stock': False,
                               'stock_state': product['current_stock'], 'source_count': 1,
                               'product_cny_from': None}]
        result['offers'][0]['offer'].update(offer_id=matching['offer_id'], url=matching['url'],
                                           stock=product['current_stock'], fetched_at='2000-01-01T00:00:00Z')
        return result
    card = next((card for card in state['catalog']['items'] if card['product_id'] == product_id), None)
    if card is None or variant_id and variant_id != result['variant_id']:
        raise KeyError((product_id, variant_id))
    result.update(product_id=card['product_id'], name=card['name'], name_zh=card['name_zh'], image=card['image'],
                  category=card['category'], category_group=card['category_group'])
    return result


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def event(n, family='173', size='M', sold=False, image=True):
    url=f'https://merchant.example/products/26-{family}-bah?variant={n}'
    return {'id':n,'event_key':f'{n:064x}','source_code':'maap','source_name':'Bahrain test fixture',
        'offer_id':f'o{n}','name_zh':'同名 Bahrain 车队短袖测试','category':'jerseys','kind':'price_changed',
        'old_price':'148' if family=='173' else '107','new_price':'149' if family=='173' else '108',
        'currency':'AUD','stock':'out_of_stock' if sold else 'in_stock','observed_at':'2026-10-14T23:00:00Z','url':url,
        'product':{'offer_id':f'o{n}','url':url,'name':'Bahrain jersey fixture','brand':'Ale','model':f'R26{family}',
            'color':'红色' if family=='173' else '白色','size':size,'image':f'https://merchant.example/{family}.svg' if image else None,
            'product_id':family,'variant_id':size,'current_stock':'out_of_stock' if sold else 'in_stock'}}



def select_purchase_route(page, route='direct', selected=False):
    """Registration is available only after an explicit, enabled route choice."""
    assert_exit_closed(page)
    comparison = page.locator('#routeComparison')
    expect(comparison).to_be_visible()
    expect(comparison.locator('.registration-help')).to_have_count(0)
    expect(comparison.locator('[data-route]')).to_have_count(3)
    for name in ['direct', 'forwarding', 'hongkong']:
        card = comparison.locator(f'[data-route="{name}"]')
        expect(card).to_have_count(1)
        assert card.get_attribute('data-route-status') in {'confirmed', 'conditional', 'unknown', 'prohibited'}
    if selected:
        expect(page.locator('#routeContinue')).to_be_enabled()
    else:
        expect(page.locator('#routeContinue')).to_be_disabled()
    choice = comparison.locator(f'[data-route-select="{route}"]')
    expect(choice).to_be_enabled()
    choice.click()
    expect(page.locator('#routeContinue')).to_be_enabled()
    if comparison.locator(f'[data-route="{route}"]').get_attribute('data-route-status') == 'unknown':
        expect(page.locator('#routeContinue')).to_have_text('去官网核实 →')
    page.locator('#routeContinue').click()
    expect(page.locator('#registrationInterstitial')).to_be_visible()
    expect(page.locator('#registrationInterstitial .registration-help')).to_have_count(1)
    expect(page.locator('#routeComparison')).to_have_count(0)
    assert_exit_closed(page)


def expect_purchase_restored(page, stage='route'):
    expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'false')
    expect(page.locator('#registrationInterstitial' if stage == 'registration' else '#routeComparison')).to_be_visible()
    assert page.evaluate('history.state && history.state.bikehuntPurchase && history.state.bikehuntPurchase.stage') == stage


def cancel_purchase_to_detail(page):
    if page.locator('#registrationCancel').count():
        page.locator('#registrationCancel').click()
    expect(page.locator('#routeComparison')).to_be_visible()
    page.locator('#routeBack').click()
    # Both stages disappear before the asynchronous detail request completes.
    expect(page.locator('#variant')).to_be_visible()
    page.wait_for_function('currentProduct !== null && Array.isArray(currentProduct.offers)')
    expect(page.locator('#routeComparison,#registrationInterstitial')).to_have_count(0)


def exercise_amazon_searches(page, context, base, mode, return_label, checks):
    """No Amazon traffic: intercept every official search and validate each exit."""
    saved_read = page.evaluate("localStorage.getItem('bikehuntMessagesReadCursor')")
    initial_badge = page.locator('#messageBadge').inner_text()
    page.locator('#amazonChannels').click()
    expect(page.locator('#sheetName')).to_have_text('Amazon购买途径')
    expect(page.locator('[data-amazon-search-link]')).to_have_count(8)
    expect(page.locator('[data-purchase-link],[data-reference-link]')).to_have_count(0)
    expect(page.locator('.amazon-market .registration-help,.amazon-market .purchase-readiness')).to_have_count(0)
    for text in ['搜索入口，非商品实时报价', '未核实搜索结果中的卖家、价格或库存', '第三方卖家', '不等于 Amazon 自营', '中国大陆', '进口税费', '结账页']:
        expect(page.locator('#sheetBody')).to_contain_text(text)
    logos = page.locator('.amazon-channel-logo')
    expect(logos).to_have_count(4)
    for index, country in enumerate(['美国站', '英国站', '德国站', '日本站']):
        logo = logos.nth(index)
        expect(logo).to_be_visible()
        expect(logo).to_have_attribute('alt', 'Amazon')
        assert logo.evaluate('(img) => img.complete && img.naturalWidth === 6110 && img.naturalHeight === 2047')
        assert logo.evaluate('(img) => new URL(img.currentSrc).origin === location.origin')
        assert logo.evaluate('(img) => Math.abs(img.getBoundingClientRect().width / img.getBoundingClientRect().height - 6110 / 2047) < 0.02')
        expect(page.locator('.amazon-country').nth(index)).to_have_text(country)
        expect(page.locator('.amazon-market').nth(index).get_by_role('heading', name='Amazon '+country)).to_be_visible()
    expect(page.locator('.amazon-channel-fallback:visible')).to_have_count(0)
    expect(page.locator('.amazon-brand-note')).to_contain_text('BikeHunt 与 Amazon 无合作或隶属关系')
    assert page.locator('#sheetBody').evaluate('(el) => el.scrollWidth <= el.clientWidth')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(OUT/f'amazon_searches_{mode}.png'))
    # A failed image leaves ordinary Amazon text plus country, host and working links.
    failed_logo_url = logos.first.get_attribute('src') + '?simulate-image-failure'
    page.route(failed_logo_url, lambda route: route.abort())
    logos.evaluate_all('(images, src) => images.forEach(img => { img.src = src; })', failed_logo_url)
    expect(page.locator('.amazon-channel-logo:visible')).to_have_count(0)
    expect(page.locator('.amazon-channel-fallback:visible')).to_have_count(4)
    expect(page.locator('[data-amazon-search-link]')).to_have_count(8)
    assert page.locator('#sheetBody').evaluate('(el) => el.scrollWidth <= el.clientWidth')
    page.screenshot(path=str(OUT/f'amazon_logo_fallback_{mode}.png'))
    page.locator('#close').click(); page.locator('#amazonChannels').click()
    expect(page.locator('.amazon-channel-logo:visible')).to_have_count(4)
    expect(page.locator('.amazon-channel-fallback:visible')).to_have_count(0)
    checks.append(mode+': four unchanged official Amazon marks load locally, proportional size, country labels and accessible headings, clean fallback on failed image, restored after reopen; no affiliation claim')
    # Native accordion remains usable with keyboard and touch; it never collects data.
    expect(page.locator('.amazon-guide-step')).to_have_count(8)
    expect(page.locator('.amazon-guide-step[open]')).to_have_count(1)
    expect(page.locator('.amazon-import-guide form, .amazon-import-guide input, .amazon-import-guide select, .amazon-import-guide iframe')).to_have_count(0)
    for step, text in [('market', '最终扣款币种'), ('address', 'China（中国）'), ('size', 'Size chart'), ('seller', '不等于 Amazon 自营'), ('delivery', '都不保证这件商品能直邮中国'), ('fees', '没有列出进口费用，不代表免税或全部税费已预付'), ('payment', '跨境退货运费由谁承担'), ('aftercare', 'Your Orders')]:
        detail = page.locator(f'[data-amazon-step="{step}"]')
        if detail.get_attribute('open') is None:
            summary = detail.locator('summary')
            summary.focus(); page.keyboard.press('Enter')
        expect(detail).to_have_attribute('open', '')
        expect(detail.locator('.amazon-step-body')).to_be_visible()
        expect(detail.locator('.amazon-step-body')).to_contain_text(text)
        expect(page.locator('.amazon-guide-step[open]')).to_have_count(1)
        assert page.locator('#sheetBody').evaluate('(el) => el.scrollWidth <= el.clientWidth')
        if step == 'fees':
            detail.scroll_into_view_if_needed()
            page.screenshot(path=str(OUT/f'amazon_import_fees_{mode}.png'))
    page.locator('.amazon-help-sources summary').click()
    expect(page.locator('.amazon-help-sources')).to_contain_text('美国、德国、日本站具体帮助本次未能完成核验')
    expect(page.locator('[data-amazon-help-link]')).to_have_count(4)
    for key, href in AMAZON_HELP.items():
        help_link = page.locator(f'[data-amazon-help-link="{key}"]')
        expect(help_link).to_have_attribute('href', href)
        expect(help_link).to_have_attribute('target', '_self')
    help_link = page.locator('[data-amazon-help-link="seller"]')
    help_link.click()
    assert_exit_dialog(page, AMAZON_HELP['seller'], official=False)
    cancel_exit_dialog(page)
    expect(help_link).to_be_focused()
    expect(page).to_have_url(base)
    help_link.click(button='middle')
    confirm_exit_dialog(page, AMAZON_HELP['seller'], official=False)
    expect(page).to_have_url(AMAZON_HELP['seller']); assert len(context.pages) == 1
    page.go_back(wait_until='networkidle')
    expect(page.locator('#q')).to_have_value('Stamp Hoodie')
    assert page.evaluate("localStorage.getItem('bikehuntMessagesReadCursor')") == saved_read
    page.locator('#amazonChannels').click()
    checks.append(mode+': eight-step Amazon import accordion supports keyboard and touch, narrow layouts, specific item/address checks, FBA distinction, unprepaid tax warning, payment and returns checklist; verified UK source scope and same-tab help Cancel/Continue; no personal-data form')
    page.keyboard.press('Escape')
    expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
    expect(page.locator('#amazonChannels')).to_be_focused()
    page.locator('#amazonChannels').click()
    # Wrong domains, credentials, affiliate parameters and altered search queries never prompt or navigate.
    link = page.locator('[data-amazon-search-link]').first
    original_url = link.get_attribute('href')
    dialogs = []
    def reject_unexpected(dialog):
        dialogs.append(dialog.message)
        dialog.dismiss()
    page.on('dialog', reject_unexpected)
    for bad in ['https://www.amazon.com.evil.example/s?k=road', 'https://www.amazon.com@evil.example/s?k=road', original_url+'&tag=affiliate-20', original_url+'&k=other', 'javascript:alert(1)']:
        link.evaluate('(el, href) => el.setAttribute("href", href)', bad)
        link.click()
        expect(page).to_have_url(base)
        expect(page.locator('#registrationInterstitial')).to_have_count(0)
        assert_exit_closed(page)
    link.evaluate('(el, href) => el.setAttribute("href", href)', original_url)
    page.remove_listener('dialog', reject_unexpected)
    assert not dialogs, dialogs
    for market_index, (code, host, queries) in enumerate(AMAZON_SEARCHES):
        for category_index, (category, query) in enumerate(zip(['jerseys', 'bibs'], queries)):
            link = page.locator(f'[data-amazon-search-link="{code}_{category}"]')
            href = link.get_attribute('href')
            parsed = urlparse(href)
            assert parsed.scheme == 'https' and parsed.netloc == host and parsed.path == '/s'
            assert parse_qs(parsed.query) == {'k': [query]} and not parsed.fragment
            expect(link).to_have_attribute('target', '_self')
            if market_index == 0 and category_index == 0:
                link.click(modifiers=['Control'])
            elif market_index == 0 and category_index == 1:
                link.click(button='middle')
            elif market_index == 1 and category_index == 0:
                link.focus(); page.keyboard.press('Enter')
            else:
                link.click()
            expect(page).to_have_url(base)
            expect(page.locator('#registrationInterstitial')).to_be_visible()
            expect(page.locator('#registrationInterstitial [data-registration-source]')).to_have_attribute('data-registration-source', code)
            assert len(context.pages) == 1
            page.locator('#registrationCancel').click()
            expect(page.locator('.amazon-market')).to_have_count(4)
            expect(page.locator('#registrationInterstitial')).to_have_count(0)
            page.locator(f'[data-amazon-search-link="{code}_{category}"]').click()
            open_final_exit(page, href, official=True)
            cancel_exit_dialog(page)
            expect(page).to_have_url(base)
            expect(page.locator('.amazon-market')).to_have_count(4)
            page.locator(f'[data-amazon-search-link="{code}_{category}"]').click()
            open_final_exit(page, href, official=True)
            confirm_exit_dialog(page, href, official=True)
            expect(page).to_have_url(href)
            assert len(context.pages) == 1
            page.go_back(wait_until='networkidle')
            expect(page).to_have_url(base)
            expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
            if market_index == 0 and category_index == 0:
                page.reload(wait_until='networkidle')
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
            expect(page.locator('#q')).to_have_value('Stamp Hoodie')
            expect(page.locator('#browseLabel')).to_have_text(return_label)
            expect(page.locator('[data-category-group=clothing]')).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('.card')).to_have_count(1)
            expect(page.locator('#messageBadge')).to_have_text(initial_badge)
            assert page.evaluate("localStorage.getItem('bikehuntMessagesReadCursor')") == saved_read
            page.locator('#amazonChannels').click()
            expect(page.locator('.amazon-market')).to_have_count(4)
    page.locator('#close').click()
    expect(page.locator('#amazonChannels')).to_be_focused()
    page.reload(wait_until='networkidle')
    expect(page.locator('#q')).to_have_value('Stamp Hoodie')
    expect(page.locator('#browseLabel')).to_have_text(return_label)
    expect(page.locator('[data-category-group=clothing]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.card')).to_have_count(1)
    expect(page.locator('#messageBadge')).to_have_text(initial_badge)
    assert page.evaluate("localStorage.getItem('bikehuntMessagesReadCursor')") == saved_read
    checks.append(mode+': Amazon four official sites/eight category searches; accurate disclosure; exact allowlist rejects tampering; full disclaimer Cancel/Continue; click/modifier/middle/keyboard same-tab; Back/reload retains source/category/query/read state; Close/Escape restores focus')


def exercise_group_entry(page, context, base, mode, return_label, checks):
    read_state=page.evaluate("localStorage.getItem('bikehuntMessagesReadCursor')")
    expect(page.locator('#wechatReminder')).to_have_count(0)
    expect(page.locator('#wechatCommunity')).to_be_visible()
    expect(page.locator('#wechatCommunity')).to_have_text('加入骑游海淘交流群')
    page.locator('#wechatCommunity').click()
    expect(page).to_have_url(base+'group/')
    expect(page.locator('#groupTitle')).to_have_text('骑游海淘交流群')
    expect(page.locator('#groupQr')).to_be_visible()
    expect(page.locator('#groupStatus')).to_have_text('微信标注10月22日前有效')
    assert page.locator('#communityReminder, #wechatReminder').count()==0
    assert len(context.pages)==1
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(OUT/f'group_entry_{mode}.png'))
    page.locator('#groupBack').click()
    expect(page).to_have_url(base)
    expect(page.locator('#q')).to_have_value('Stamp Hoodie')
    expect(page.locator('#browseLabel')).to_have_text(return_label)
    expect(page.locator('[data-category-group=clothing]')).to_have_attribute('aria-pressed','true')
    expect(page.locator('.card')).to_have_count(1)
    expect(page.locator('#sheet')).to_have_attribute('aria-hidden','true')
    assert page.evaluate("localStorage.getItem('bikehuntMessagesReadCursor')")==read_state
    page.go_forward(wait_until='networkidle')
    expect(page.locator('#groupQr')).to_be_visible()
    page.go_back(wait_until='networkidle')
    expect(page.locator('#q')).to_have_value('Stamp Hoodie')
    expect(page.locator('.card')).to_have_count(1)
    checks.append(mode+': exact group name, real QR only, same-tab stable group entrance, Back/Forward preserves source/category/search/read state')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}/web/'
    errors=[];checks=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'),headless=True)
            for mode,viewport in [('desktop',{'width':1440,'height':900}),('mobile',{'width':390,'height':844})]:
                state=fixture();state['events']=[event(5,'missing',image=False),event(4,'sold',sold=True),event(3,'175'),event(2,size='L'),event(1)]
                state['events'][0]['product'].update(product_id=None,variant_id=None)
                basecard=state['catalog']['items'][0]
                state['catalog']['items'] += [
                    {**basecard, 'product_id': 'maap-jersey', 'category': 'jerseys'},
                    {**basecard, 'product_id': 'other-jersey', 'category': 'jerseys', 'source_codes': ['other']},
                    {**basecard, 'product_id': 'maap-helmet', 'category': 'helmets', 'category_group': 'helmets', 'name': 'Scope Helmet'},
                    {**basecard, 'product_id': 'other-helmet', 'category': 'helmets', 'category_group': 'helmets', 'name': 'Scope Helmet', 'source_codes': ['other']},
                ]
                state['catalog']['categories'].append({'code':'jerseys','name':'骑行上衣'})
                context=browser.new_context(viewport=viewport,is_mobile=mode=='mobile',has_touch=mode=='mobile')
                context.set_default_timeout(7000);context.set_default_navigation_timeout(10000)
                context.add_init_script('window.BIKEHUNT_PAGES=true;')
                def intercept(route):
                    u=urlparse(route.request.url)
                    if route.request.url in AMAZON_HELP.values():
                        return route.fulfill(content_type='text/html', body='<title>Mock official help</title><p>Help navigation test only</p>')
                    if u.netloc in {market[1] for market in AMAZON_SEARCHES}:
                        assert u.path == '/s' and set(parse_qs(u.query)) == {'k'}
                        return route.fulfill(content_type='text/html', body='<title>Mock Amazon search</title><p>Search navigation test only</p>')
                    if u.netloc=='merchant.example':
                        if u.path.endswith('.svg'):
                            color='#d65b5b' if '173' in u.path else '#f6f7f8'
                            return route.fulfill(content_type='image/svg+xml',body=f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="#edf1f5"/><path d="M60 30L30 60l20 30 15-10v90h70V80l15 10 20-30-30-30Z" fill="{color}" stroke="#9ca7b3"/><text x="100" y="195" text-anchor="middle" font-size="10">TEST FIXTURE</text></svg>')
                        return route.fulfill(body='Mock merchant product detail')
                    if u.netloc!=urlparse(base).netloc:return route.abort()
                    if not u.path.startswith('/api/'):return route.continue_()
                    if u.path=='/api/catalog':result=state['catalog']
                    elif u.path.startswith('/api/catalog/'):
                        product_id=u.path.rsplit('/',1)[-1];variant_id=parse_qs(u.query).get('variant_id',[''])[0]
                        state['last_detail_request']=(product_id,variant_id)
                        try:result=detail_for_request(state,product_id,variant_id)
                        except KeyError:return route.fulfill(status=404,content_type='application/json',body='{}')
                    elif u.path=='/api/community':result={'schema_version':1,'configured':True,'available':True,'title':'骑游海淘交流群','image_url':'/web/assets/community/group-20261015.png','revision':'test','expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),'expiry_label':'微信标注10月22日前有效'}
                    elif u.path=='/api/updates':result={'items':state['events'],'cursor':max(e['id'] for e in state['events']),'fx':state['catalog']['fx']}
                    elif u.path=='/api/directories':result={'brands':[{'code':'maap','name':'MAAP','name_zh':'MAAP 品牌','offer_count':2,'product_count':2,'rule_count':0}], 'teams':[{'code':'other','name':'Other','name_zh':'测试车队','offer_count':1,'product_count':1,'rule_count':0}]}
                    elif u.path.startswith('/api/rules/'):result={'version':1,'documents':[]}
                    elif u.path.startswith('/api/fit/'):result={'state':'no_chart','note_zh':'测试数据','candidate_sizes':[],'required_measurements':[],'source_url':None,'checked_at':None,'chart_rows':[]}
                    else:result={}
                    route.fulfill(content_type='application/json',body=json.dumps(result))
                context.route('**/*',intercept)
                page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base,wait_until='networkidle')
                expect(page.locator('#wechatReminder')).to_have_count(0)
                expect(page.locator('#wechatCommunity')).to_be_visible()
                expect(page.locator('#wechatCommunity')).to_have_text('加入骑游海淘交流群')
                expect(page.locator('#messageBadge')).to_have_text('4')
                page.locator('[data-tab=brands]').click();page.locator('[data-source=maap]').click();page.locator('#sourceProducts').click()
                assert_single_category_layer(page)
                assert_card_ids(page, ['partial', 'unknown', 'maap-jersey', 'maap-helmet'])
                page.locator('[data-category-group=clothing]').click()
                assert_card_ids(page, ['partial', 'unknown', 'maap-jersey'])
                expect(page.locator('#browseLabel')).to_have_text('MAAP 品牌 · 骑行服饰')
                # Clicking the selected group clears only that group, keeping the source.
                page.locator('[data-category-group=clothing]').click()
                expect(page.locator('[data-category-group][aria-pressed=true]')).to_have_count(0)
                assert_card_ids(page, ['partial', 'unknown', 'maap-jersey', 'maap-helmet'])
                expect(page.locator('#browseLabel')).to_have_text('MAAP 品牌')
                page.locator('[data-tab=products]').click()
                page.locator('[data-category-group=clothing]').click()
                assert_card_ids(page, ['partial', 'maap-jersey', 'other-jersey'])
                expect(page.locator('#browseLabel')).to_have_text('精选好价 · 骑行服饰')
                checks.append(mode+': exact single five-category layer; brand group/toggle retains source; explicit精选好价 clears source; clothing includes both bibs and jerseys and excludes helmets')
                return_tab,return_source,return_label=('brands','maap','MAAP 品牌 · 骑行服饰') if mode=='desktop' else ('teams','other','测试车队 · 骑行服饰')
                page.locator(f'[data-tab={return_tab}]').click();page.locator(f'[data-source={return_source}]').click();page.locator('#sourceProducts').click()
                # A source opened from the directory retains the selected clothing group.
                expect(page.locator('[data-category-group=clothing]')).to_have_attribute('aria-pressed', 'true')
                scoped_ids = ['partial', 'unknown', 'maap-jersey'] if mode == 'desktop' else ['other-jersey']
                assert_card_ids(page, scoped_ids);expect(page.locator('#browseLabel')).to_have_text(return_label)
                page.locator('#priceMessages').click();expect(page.locator('.message-card')).to_have_count(4);expect(page.locator('#messageBadge')).to_be_hidden()
                red=page.locator('.message-card').filter(has=page.locator('img[src$="173.svg"]'))
                expect(red).to_contain_text('M');expect(red).to_contain_text('L');expect(red.locator('.message-variant')).to_have_count(2)
                sold=page.locator('.message-card').filter(has_text='R26sold');expect(sold.locator('a')).to_have_count(0)
                expect(page.locator('.message-no-image:visible')).to_have_count(1)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(OUT/f'catalog_messages_{mode}.png'))
                # Image, title, card and variant actions stay inside BikeHunt and bind exact IDs.
                red.locator('.message-thumbnail').click();expect(page).to_have_url(base);assert len(context.pages)==1
                expect(page.locator('#sheetBody')).to_contain_text('制造商型号 R26173');assert state['last_detail_request']==('173','L')
                page.locator('#close').click();page.locator('#priceMessages').click()
                page.locator('.message-card').filter(has_text='R26173').locator('.message-title').click();expect(page.locator('#sheetBody')).to_contain_text('制造商型号 R26173');expect(page).to_have_url(base)
                page.locator('#close').click();page.locator('#priceMessages').click()
                page.locator('.message-card').filter(has_text='R26sold').locator('.message-thumbnail').click();expect(page.locator('#sheetBody')).to_contain_text('已售罄');expect(page.locator('[data-reference-link][href]')).to_have_count(0);expect(page).to_have_url(base)
                page.locator('#close').click();page.locator('#priceMessages').click()
                missing=page.locator('.message-card').filter(has_text='R26missing');expect(missing.locator('[data-message-product]')).to_have_count(0);expect(missing).to_contain_text('该商品详情暂不可用')
                page.locator('.message-card').filter(has_text='R26173').locator('.message-spec').click();expect(page.locator('#sheetBody')).to_contain_text('制造商型号 R26173');assert state['last_detail_request']==('173','L');expect(page).to_have_url(base)
                # The separately labelled merchant action is offered only inside product details.
                reference=page.locator('.reference-exit');expect(reference).to_be_visible()
                reference.click()
                select_purchase_route(page)
                page.locator('#registrationCancel').click()
                expect(page.locator('#routeComparison')).to_be_visible()
                page.locator('#routeContinue').click()
                open_final_exit(page, 'https://merchant.example/products/26-173-bah?variant=2')
                cancel_exit_dialog(page);assert len(context.pages)==1;expect(page).to_have_url(base)
                expect(page.locator('#routeComparison')).to_be_visible()
                page.locator('#routeContinue').click()
                open_final_exit(page, 'https://merchant.example/products/26-173-bah?variant=2')
                confirm_exit_dialog(page, 'https://merchant.example/products/26-173-bah?variant=2')
                expect(page).to_have_url('https://merchant.example/products/26-173-bah?variant=2');assert len(context.pages)==1
                page.go_back(wait_until='networkidle')
                expect(page).to_have_url(base);expect_purchase_restored(page)
                expect(page.locator('#browseLabel')).to_have_text(return_label);expect(page.locator('[data-category-group=clothing]')).to_have_attribute('aria-pressed','true');assert_card_ids(page, scoped_ids)
                expect(page.locator('#messageBadge')).to_be_hidden()
                page.reload(wait_until='networkidle');expect_purchase_restored(page)
                expect(page.locator('#browseLabel')).to_have_text(return_label);expect(page.locator('[data-category-group=clothing]')).to_have_attribute('aria-pressed','true');assert_card_ids(page, scoped_ids);expect(page.locator('#messageBadge')).to_be_hidden()
                cancel_purchase_to_detail(page)
                expect(page.locator('#sheetBody')).to_contain_text('制造商型号 R26173')
                page.locator('#close').click()
                state['events'].insert(0,event(6,'new'))
                page.evaluate("window.dispatchEvent(new CustomEvent('bikehunt-published',{detail:{events:[{id:6,category:'jerseys'}],freshnessChanged:false}}))")
                expect(page.locator('#messageBadge')).to_have_text('1');expect(page.locator('#messageBadge')).to_be_visible()
                checks.append(mode+': exact thumbnails and internal product/variant actions; generic-name products separate; soldout opens status without purchase link; same-tab Cancel/Continue; brand/team category restored after Back and reload; selected route and exact reference restored; read persisted; new increment')
                # Search is part of the history entry; Back must restore actual results, not just scope.
                scoped=next(card for card in state['catalog']['items'] if card['category']=='jerseys' and return_source in card['source_codes'])
                scoped['name']='Stamp Hoodie';scoped['name_zh']='Stamp Hoodie 测试商品'
                state['catalog']['items'] += [
                    {**scoped, 'product_id': 'search-other', 'name': 'Other jersey', 'name_zh': '其他测试商品'},
                    # Matching text must not leak a different source or category into the scope.
                    {**scoped, 'product_id': 'query-wrong-source', 'source_codes': ['other' if return_source == 'maap' else 'maap']},
                    {**scoped, 'product_id': 'query-wrong-group', 'category': 'helmets', 'category_group': 'helmets'},
                ]
                page.evaluate('refreshCatalogSilently(false)');assert_card_ids(page, scoped_ids + ['search-other'])
                page.locator('#q').fill('Stamp Hoodie');expect(page.locator('.card')).to_have_count(1);expect(page.locator('#count')).to_have_text('1 件商品');expect(page.locator('#clear')).to_be_enabled()
                page.locator('.card .compare-button').click();expect(page.locator('[data-variant="S"]')).to_be_visible();expect(page.locator('.guide-start')).to_have_count(0)
                expect(page.locator('#fitReference')).to_contain_text('测试数据');page.locator('[data-variant="S"]').click();expect(page.locator('.guide-start')).to_be_enabled();page.locator('.guide-start').click()
                select_purchase_route(page)
                expect(page.locator('#registrationInterstitial')).to_contain_text('MAAP')
                open_final_exit(page, 'https://merchant.example/bib?variant=S');cancel_exit_dialog(page);expect(page).to_have_url(base);expect(page.locator('#routeComparison')).to_be_visible();assert len(context.pages)==1
                page.locator('#routeContinue').click()
                open_final_exit(page, 'https://merchant.example/bib?variant=S')
                confirm_exit_dialog(page, 'https://merchant.example/bib?variant=S')
                expect(page).to_have_url('https://merchant.example/bib?variant=S');assert len(context.pages)==1
                page.go_back(wait_until='networkidle');expect(page).to_have_url(base);expect_purchase_restored(page);expect(page.locator('#q')).to_have_value('Stamp Hoodie');expect(page.locator('.card')).to_have_count(1);expect(page.locator('#count')).to_have_text('1 件商品')
                expect(page.locator('#browseLabel')).to_have_text(return_label);expect(page.locator('[data-category-group=clothing]')).to_have_attribute('aria-pressed','true');expect(page.locator('#messageBadge')).to_have_text('1')
                page.reload(wait_until='networkidle');expect_purchase_restored(page);expect(page.locator('#browseLabel')).to_have_text(return_label);expect(page.locator('[data-category-group=clothing]')).to_have_attribute('aria-pressed','true');expect(page.locator('#messageBadge')).to_have_text('1')
                expect(page.locator('#q')).to_have_value('Stamp Hoodie');expect(page.locator('.card')).to_have_count(1);expect(page.locator('#count')).to_have_text('1 件商品');expect(page.locator('#clear')).to_be_visible();expect(page.locator('#clear')).to_be_enabled()
                cancel_purchase_to_detail(page)
                expect(page.locator('[data-variant=S]')).to_have_attribute('aria-pressed','true')
                page.locator('#close').click()
                exercise_amazon_searches(page, context, base, mode, return_label, checks)
                exercise_group_entry(page, context, base, mode, return_label, checks)
                page.locator('#clear').click();expect(page.locator('#q')).to_have_value('');assert_card_ids(page, scoped_ids + ['search-other'])
                checks.append(mode+': search Stamp Hoodie narrows the clothing/source scope to one exact product; explicit route and registration Cancel/Continue use exact same-tab URL; Back/reload restores selected route, query/results, source/size/read state and working clear control')
                page.locator('[data-tab=products]').click();expect(page.locator('[data-category-group][aria-pressed=true]')).to_have_count(0)
                old='2000-01-01T00:00:00Z';state['detail']['offers'][0]['offer']['fetched_at']=old
                for v in state['detail']['variants']:v['in_stock']=False
                page.evaluate("openProduct('partial')");expect(page.locator('#sheetBody')).to_contain_text('库存待核实');expect(page.locator('[data-variant]')).to_have_count(0)
                reference=page.locator('.reference-exit');expect(reference).to_be_visible()
                reference.click();select_purchase_route(page)
                open_final_exit(page, 'https://merchant.example/bib?variant=S');cancel_exit_dialog(page);expect(page.locator('#routeComparison')).to_be_visible();assert len(context.pages)==1
                page.locator('#routeContinue').click()
                open_final_exit(page, 'https://merchant.example/bib?variant=S')
                confirm_exit_dialog(page, 'https://merchant.example/bib?variant=S')
                expect(page).to_have_url('https://merchant.example/bib?variant=S');assert len(context.pages)==1
                page.go_back(wait_until='networkidle');expect(page).to_have_url(base);expect_purchase_restored(page)
                page.reload(wait_until='networkidle');expect_purchase_restored(page);expect(page.locator('#messageBadge')).to_have_text('1')
                cancel_purchase_to_detail(page);expect(page.locator('.reference-exit')).to_be_visible()
                page.screenshot(path=str(OUT/f'catalog_stale_reference_{mode}.png'))
                state['detail']['offers'][0]['offer']['stock']='out_of_stock'
                page.evaluate("window.dispatchEvent(new CustomEvent('bikehunt-published',{detail:{events:[],freshnessChanged:true}}))")
                expect(page.locator('#variant')).to_be_visible()
                expect(page.locator('#sheetBody')).to_contain_text('已售罄')
                expect(page.locator('[data-reference-link][href]')).to_have_count(0)
                checks.append(mode+': stale inventory reference-only path remains usable; no stale size claims; newly sold-out snapshot removes link')
                page.locator('#close').click()
                restored={**event(1500,'recovered'),'recovered_history':True};state['events'].insert(0,restored)
                page.evaluate("document.getElementById('updateToast').hidden=true;window.dispatchEvent(new CustomEvent('bikehunt-published',{detail:{events:[{id:1500,category:'jerseys',recovered_history:true}],freshnessChanged:false}}))")
                expect(page.locator('#messageBadge')).to_have_text('1');expect(page.locator('#updateToast')).to_be_hidden()
                page.locator('#priceMessages').click();expect(page.locator('#sheetBody')).to_contain_text('恢复的历史记录');expect(page.locator('#messageBadge')).to_be_hidden()
                checks.append(mode+': recovered history stays visible without unread or toast inflation; genuine unread remains independent')
                context.close()
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        (OUT/'catalog_messages_results.json').write_text(json.dumps({'checks':checks,'errors':errors},ensure_ascii=False,indent=2))
    assert not errors,errors
    print(json.dumps({'ok':True,'checks':checks},ensure_ascii=False))


def assert_disclaimer(dialog):
    assert DISCLAIMER in dialog.message


if __name__=='__main__':main()
