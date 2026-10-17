"""Hermetic desktop/mobile merchant-guide QA; no live account or checkout requests."""
from __future__ import annotations

import copy
import json
import os
import shutil
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

from test_catalog_messages_ui import OUT, ROOT, QuietHandler, assert_single_category_layer, fixture
from exit_dialog_test_support import assert_exit_closed, assert_exit_dialog, cancel_exit_dialog, confirm_exit_dialog

MERCHANTS = {
    'maap': ('MAAP', '已有账户的找回说明'),
    'visma': ('Visma', '发票日期起 30 天'),
    'decathlon': ('Decathlon CMA CGM', '官方页面对退货天数和费用有不同表述'),
    'other': ('其他商家', '该商家流程未逐步核实'),
}
OFFICIAL_HOSTS = {
    'support.maap.cc', 'www.teamvismaleaseabike.com',
    'shop.decathloncmacgmteam.com', 'support.apple.com', 'support.google.com',
}
STEPS = ['country', 'account', 'size', 'cart', 'address', 'returns']
DIRECTORY_BRANDS = [
    {'code': 'maap', 'name': 'MAAP', 'name_zh': 'MAAP 品牌', 'offer_count': 4,
     'product_count': 2, 'rule_count': 0, 'logo_images': ['/web/assets/brands/maap.svg']},
    {'code': 'pns', 'name': 'Pas Normal Studios', 'name_zh': 'Pas Normal Studios',
     'offer_count': 1, 'product_count': 1, 'rule_count': 0,
     'logo_images': ['/web/assets/brands/pns.svg']},
    {'code': 'pns-no-image', 'name': 'Pas Normal Studios', 'name_zh': '无图片回归测试',
     'offer_count': 0, 'product_count': 0, 'rule_count': 0, 'logo_images': []},
]



def guide_fixture():
    state = fixture()
    card = state['catalog']['items'][0]
    card.update(name='Guide Bib', name_zh='Guide Bib 图解测试')
    state['catalog']['items'] = [card, {**card, 'product_id': 'other-bib', 'name': 'Other Bib', 'name_zh': '另一件商品'},
                                 {**card, 'product_id': 'pns-bib', 'name': 'PNS Bib', 'name_zh': 'PNS 目录测试', 'source_codes': ['pns']}]
    original = state['detail']['offers'][0]
    state['detail']['offers'] = []
    for code, (name, _) in MERCHANTS.items():
        quote = copy.deepcopy(original)
        quote['offer'].update(source_code=code, source_name=name, offer_id='offer-'+code)
        state['detail']['offers'].append(quote)
    return state


def assert_scope(page, base, read_state):
    expect(page).to_have_url(base)
    expect(page.locator('#q')).to_have_value('Guide Bib')
    expect(page.locator('#browseLabel')).to_have_text('搜索结果 · 骑行服饰')
    expect(page.locator('[data-category-group=clothing]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.card')).to_have_count(1)
    assert page.evaluate("localStorage.getItem('bikehuntMessagesReadCursor')") == read_state


def assert_no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('#sheetBody').evaluate('(element) => element.scrollWidth <= element.clientWidth + 1')



def exercise_directory_logos(page, context, base, external_reads, mode, checks):
    """Real local images and load/error events keep the complete brand identity."""
    assert_exit_closed(page)
    page.locator('[data-tab=brands]').click()
    expect(page.locator('.directory-card')).to_have_count(3)
    pns = page.locator('.directory-card[data-source=pns]')
    maap = page.locator('.directory-card[data-source=maap]')
    text_only = page.locator('.directory-card[data-source=pns-no-image]')
    expect(text_only.locator('.directory-mark')).to_be_visible()
    expect(text_only.locator('.directory-mark')).to_have_text('Pas Normal Studios')
    expect(text_only.locator('img[data-directory-logo]')).to_have_count(0)
    for card, name, asset in [(pns, 'Pas Normal Studios', '/web/assets/brands/pns.svg'),
                              (maap, 'MAAP', '/web/assets/brands/maap.svg')]:
        image = card.locator('img[data-directory-logo]')
        expect(image).to_have_attribute('src', asset)
        expect(image).to_have_attribute('alt', name + ' 标志')
        expect(image).to_be_visible()
        assert image.evaluate('img => img.complete && img.naturalWidth > 0 && new URL(img.currentSrc).origin === location.origin')
        expect(card.locator('.directory-mark')).to_be_hidden()
    initial_area = pns.locator('.directory-logo').bounding_box()
    text_area = text_only.locator('.directory-logo').bounding_box()
    assert initial_area and text_area and abs(initial_area['height'] - text_area['height']) <= 1
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('#directoryPage').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
    for card in [pns, maap, text_only]:
        assert card.evaluate('el => el.scrollWidth <= el.clientWidth + 1')
    page.screenshot(path=str(OUT / f'directory_logos_{mode}.png'))
    failed_asset = urlparse(base)._replace(path='/web/assets/brands/controlled-missing-logo.svg', query='', fragment='').geturl()
    page.route(failed_asset, lambda route: route.fulfill(status=404, content_type='text/plain', body='Controlled missing directory image'))
    pns.locator('img[data-directory-logo]').evaluate('(img, src) => { img.src = src; }', failed_asset)
    expect(pns.locator('img[data-directory-logo]')).to_be_hidden()
    expect(pns.locator('.directory-mark')).to_be_visible()
    expect(pns.locator('.directory-mark')).to_have_text('Pas Normal Studios')
    failed_area = pns.locator('.directory-logo').bounding_box()
    assert failed_area and all(abs(initial_area[key] - failed_area[key]) <= 1 for key in ['width', 'height'])
    assert pns.locator('.directory-logo').evaluate('el => el.scrollWidth <= el.clientWidth + 1 && el.scrollHeight <= el.clientHeight + 1')
    assert_exit_closed(page)
    page.screenshot(path=str(OUT / f'directory_logo_fallback_{mode}.png'))
    # Opening the card renders a fresh image, and its own fallback is also wired.
    pns.click()
    expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
    expect(page.locator('#channelInfo')).to_be_visible()
    assert not page.locator('#channelInfo').evaluate('el => el.open')
    expect(page.locator('#sourceProducts')).to_have_count(0)
    page.locator('#channelInfo > summary').click()
    assert_exit_closed(page)
    expect(page).to_have_url(base)
    overview = page.locator('#channelInfo .source-overview')
    expect(overview.locator('img[data-directory-logo]')).to_be_visible()
    expect(overview.locator('.directory-mark')).to_be_hidden()
    source_area = overview.locator('.directory-logo').bounding_box()
    overview.locator('img[data-directory-logo]').evaluate('(img, src) => { img.src = src; }', failed_asset)
    expect(overview.locator('img[data-directory-logo]')).to_be_hidden()
    expect(overview.locator('.directory-mark')).to_be_visible()
    expect(overview.locator('.directory-mark')).to_have_text('Pas Normal Studios')
    source_failed_area = overview.locator('.directory-logo').bounding_box()
    assert source_area and source_failed_area and all(abs(source_area[key] - source_failed_area[key]) <= 1 for key in ['width', 'height'])
    assert page.locator('#channelInfo').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
    assert_exit_closed(page)
    expect(page).to_have_url(base)
    expect(page.locator('#browseLabel')).to_have_text('Pas Normal Studios')
    expect(page.locator('.card')).to_have_count(1)
    assert len(context.pages) == 1 and external_reads == []
    # A normal re-render restores the original working asset after the failed URL.
    page.locator('[data-tab=brands]').click()
    expect(page.locator('.directory-card[data-source=pns] img[data-directory-logo]')).to_be_visible()
    expect(page.locator('.directory-card[data-source=pns] .directory-mark')).to_be_hidden()
    assert_exit_closed(page)
    checks.append(mode + ': full Pas Normal Studios fallback with absent and failed images; real local PNS/MAAP assets; load/error and fresh render recovery; constant logo area; no overflow; directory and sourceProducts stay internal without an exit prompt')


def open_guide(page, code, selected=False):
    if page.locator('#sheet').get_attribute('aria-hidden') == 'false':
        page.locator('#close').click()
    card = page.locator('.card')
    product_id = card.get_attribute('data-id')
    card.locator('.compare-button').click()
    # A zero-count assertion also passes on the loading placeholder. Wait for
    # positive detail UI plus its bound object before calling the retained helper.
    expect(page.locator('#variant')).to_be_visible()
    page.wait_for_function('(id) => currentProduct !== null && currentProduct.product_id === id && Array.isArray(currentProduct.offers)', arg=product_id)
    expect(page.locator('[data-merchant-guide],.registration-help,.purchase-readiness')).to_have_count(0)
    if selected:
        page.locator('[data-variant=S]').click()
        expect(page.locator('[data-variant=S]')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('.guide-start')).to_have_count(4)
        page.wait_for_function("currentProduct !== null && currentProduct.variant_id === 'S'")
    page.evaluate('(options) => openMerchantGuide(currentProduct, options.code, options.variant)', {'code': code, 'variant': 'S' if selected else None})
    expect(page.locator('#merchantGuideTitle')).to_be_focused()
    expect(page.locator('#merchantLanguageGuide')).to_be_visible()
    assert_exit_closed(page)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/web/'
    errors, checks = [], []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'), headless=True)
            for mode, viewport in [('desktop', {'width': 1440, 'height': 900}), ('mobile', {'width': 390, 'height': 844}), ('small_mobile', {'width': 320, 'height': 740})]:
                state, external_reads = guide_fixture(), []
                context = browser.new_context(viewport=viewport, is_mobile=mode != 'desktop', has_touch=mode != 'desktop')
                context.set_default_timeout(7000)
                context.set_default_navigation_timeout(10000)
                context.add_init_script('''
                    window.BIKEHUNT_PAGES=true;
                    // Deterministic loading interval: absence-only waits must
                    // not let a retained read-only helper consume a null detail.
                    const realFetch=window.fetch.bind(window);
                    window.fetch=async (...args)=>{
                        const response=await realFetch(...args);
                        const input=args[0];
                        const path=new URL(input instanceof Request?input.url:String(input),location.href).pathname;
                        if(path.startsWith('/api/catalog/'))await new Promise(resolve=>setTimeout(resolve,150));
                        return response;
                    };
                ''')

                def intercept(route):
                    url = urlparse(route.request.url)
                    if url.netloc in OFFICIAL_HOSTS:
                        assert route.request.method == 'GET', 'The guide must never submit an account or checkout form'
                        external_reads.append(route.request.url)
                        return route.fulfill(content_type='text/html', body='<title>Mock official help</title><p>Read-only navigation regression fixture.</p>')
                    if url.netloc == 'merchant.example' and url.path.endswith('.svg'):
                        return route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="#edf1f5"/><text x="20" y="100">TEST FIXTURE</text></svg>')
                    if url.netloc != urlparse(base).netloc:
                        return route.abort()
                    if not url.path.startswith('/api/'):
                        return route.continue_()
                    if url.path == '/api/catalog':
                        result = state['catalog']
                    elif url.path.startswith('/api/catalog/'):
                        result = state['detail']
                        state['last_variant'] = parse_qs(url.query).get('variant_id', [None])[0]
                    elif url.path == '/api/directories':
                        result = {'brands': DIRECTORY_BRANDS, 'teams': []}
                    elif url.path == '/api/updates':
                        result = {'items': [], 'cursor': 0, 'fx': state['catalog']['fx']}
                    elif url.path.startswith('/api/rules/'):
                        result = {'version': 1, 'documents': []}
                    elif url.path.startswith('/api/fit/'):
                        result = {'state': 'no_chart', 'note_zh': '测试数据', 'candidate_sizes': [], 'required_measurements': [], 'source_url': None, 'checked_at': None, 'chart_rows': []}
                    elif url.path == '/api/community':
                        result = {'schema_version': 1, 'available': False, 'configured': False}
                    else:
                        result = {}
                    route.fulfill(content_type='application/json', body=json.dumps(result))

                context.route('**/*', intercept)
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base, wait_until='networkidle')
                assert_single_category_layer(page)
                exercise_directory_logos(page, context, base, external_reads, mode, checks)
                page.locator('[data-tab=brands]').click()
                page.locator('[data-source=maap]').click()
                assert_exit_closed(page)
                page.locator('[data-category-group=clothing]').click()
                page.locator('#q').fill('Guide Bib')
                expect(page.locator('.card')).to_have_count(1)
                read_state = page.evaluate("localStorage.getItem('bikehuntMessagesReadCursor')")

                for code, (name, special_text) in MERCHANTS.items():
                    open_guide(page, code, selected=True)
                    guide = page.locator('#merchantLanguageGuide')
                    expect(guide).to_contain_text(name)
                    expect(guide).to_contain_text('2026-10-15')
                    expect(guide).to_contain_text('未实测注册或结账成功')
                    expect(guide).to_contain_text(special_text)
                    expect(guide.locator('form,input,select,textarea,iframe,[data-purchase-link],[data-reference-link]')).to_have_count(0)
                    expect(guide.locator('img,.registration-help,.registration-guide,.purchase-readiness')).to_have_count(0)
                    expect(guide.locator('.merchant-guide-step')).to_have_count(6)
                    assert external_reads == [], 'Opening a local guide must not contact help or account websites'
                    translation = guide.locator('.merchant-translation')
                    translation.locator('summary').focus()
                    page.keyboard.press('Enter')
                    expect(translation).to_have_attribute('open', '')
                    for text in ['iPhone Safari', 'Android Chrome', 'iPhone / iPad Chrome', '不要把密码', '菜单可能随版本']:
                        expect(translation).to_contain_text(text)
                    expect(translation.locator('[data-merchant-help-link]')).to_have_count(3)
                    translation.locator('summary').press('Space')
                    expect(translation).not_to_have_attribute('open', '')
                    for step_id in STEPS:
                        step = guide.locator(f'[data-merchant-step={step_id}]')
                        if step.get_attribute('open') is None:
                            step.locator('summary').focus()
                            page.keyboard.press('Enter')
                        expect(step).to_have_attribute('open', '')
                        expect(step.locator('figure')).to_be_visible()
                        expect(step.locator('figcaption')).to_have_text('示意 · 非商家截图')
                        expect(guide.locator('.merchant-guide-step[open]')).to_have_count(1)
                        assert_no_overflow(page)
                    # Native accordions participate in the existing dialog keyboard trap.
                    last_summary = guide.locator('[data-merchant-step=returns]>summary')
                    last_summary.focus()
                    page.keyboard.press('Tab')
                    expect(page.locator('#close')).to_be_focused()
                    page.keyboard.press('Shift+Tab')
                    expect(last_summary).to_be_focused()
                    if code != 'other':
                        guide.locator('.merchant-specific-notes>summary').click()
                        expect(guide.locator('.merchant-specific-notes')).to_contain_text(special_text)
                    page.locator('#sheetBody').evaluate('(element) => element.scrollTop = 0')
                    page.screenshot(path=str(OUT / f'merchant_guide_{code}_{mode}.png'))
                    page.locator('#merchantGuideBack').click()
                    expect(page.locator('[data-merchant-guide],.registration-help,.purchase-readiness')).to_have_count(0)
                    expect(page.locator('[data-variant=S]')).to_have_attribute('aria-pressed', 'true')
                    assert state['last_variant'] == 'S'
                    expect(page.locator('.guide-start')).to_have_count(4)
                    page.locator('#close').click()
                    assert_scope(page, base, read_state)
                open_guide(page, 'other')
                page.keyboard.press('Escape')
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                expect(page.locator('.card .compare-button')).to_be_focused()
                checks.append(mode + ': callable read-only merchant helper, no early account entry, exact return variant, six keyboard accordions, labelled schematic graphics, source limits, mobile translations, no forms or automatic requests')

                # Each scoped official destination remains optional, same-tab and guarded.
                for code in MERCHANTS:
                    open_guide(page, code)
                    if code == 'other':
                        page.locator('.merchant-translation>summary').click()
                        link = page.locator('[data-merchant-help-link=chrome-android]')
                    else:
                        page.locator('.merchant-sources>summary').click()
                        link = page.locator('.merchant-sources [data-merchant-help-link]').first
                    target = link.get_attribute('href')
                    expect(link).to_have_attribute('target', '_self')
                    before = len(external_reads)
                    assert_exit_closed(page)
                    link.click()
                    dialog = assert_exit_dialog(page, target, official=False)
                    expect(dialog).to_contain_text('不会代你注册、登录或下单')
                    cancel_exit_dialog(page)
                    expect(page).to_have_url(base)
                    expect(link).to_be_focused()
                    assert len(external_reads) == before
                    link.click()
                    confirm_exit_dialog(page, target, official=False)
                    expect(page).to_have_url(target)
                    assert len(context.pages) == 1
                    assert external_reads[-1] == target
                    page.go_back(wait_until='networkidle')
                    expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'false')
                    expect(page.locator('#variant')).to_be_visible()
                    expect(page.locator('#merchantLanguageGuide')).to_have_count(0)
                    assert_scope(page, base, read_state)
                    page.reload(wait_until='networkidle')
                    expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'false')
                    expect(page.locator('#variant')).to_be_visible()
                    expect(page.locator('#merchantLanguageGuide')).to_have_count(0)
                    assert_scope(page, base, read_state)
                checks.append(mode + ': scoped official-help Cancel/Continue, forced same-tab navigation, Back/reload restores detail and source/category/search/read state without reopening a guide')

                # Changing stock while help is open cannot enable any buying path.
                open_guide(page, 'maap', selected=True)
                for quote in state['detail']['offers']:
                    quote['offer']['stock'] = 'out_of_stock'
                for variant in state['detail']['variants']:
                    variant['in_stock'] = False
                    variant['stock_state'] = 'out_of_stock'
                page.evaluate("window.dispatchEvent(new CustomEvent('bikehunt-published',{detail:{events:[],freshnessChanged:true}}))")
                expect(page.locator('#merchantLanguageGuide')).to_be_visible()
                expect(page.locator('[data-purchase-link],[data-reference-link]')).to_have_count(0)
                page.locator('#merchantGuideBack').click()
                expect(page.locator('#sheetBody')).to_contain_text('已售罄')
                expect(page.locator('.guide-start,[data-purchase-link],[data-reference-link]')).to_have_count(0)
                expect(page.locator('[data-merchant-guide]')).to_have_count(0)
                page.evaluate("openMerchantGuide(currentProduct, 'visma', 'S')")
                expect(page.locator('#merchantGuideTitle')).to_be_focused()
                expect(page.locator('.merchant-guide-step')).to_have_count(6)
                expect(page.locator('[data-purchase-link],[data-reference-link]')).to_have_count(0)
                assert_no_overflow(page)
                page.keyboard.press('Escape')
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                checks.append(mode + ': sold-out offers retain read-only help; stock changes never restore purchase links; Escape closes the guide')
                context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        (OUT / 'merchant_guides_results.json').write_text(json.dumps({'checks': checks, 'errors': errors}, ensure_ascii=False, indent=2))
    assert not errors, errors
    print(json.dumps({'ok': True, 'checks': checks}, ensure_ascii=False))


if __name__ == '__main__':
    main()
