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

from test_catalog_messages_ui import DISCLAIMER, OUT, ROOT, QuietHandler, fixture

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


def guide_fixture():
    state = fixture()
    card = state['catalog']['items'][0]
    card.update(name='Guide Bib', name_zh='Guide Bib 图解测试')
    state['catalog']['items'] = [card, {**card, 'product_id': 'other-bib', 'name': 'Other Bib', 'name_zh': '另一件商品'}]
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
    expect(page.locator('#browseLabel')).to_have_text('MAAP 品牌')
    expect(page.locator('[data-category=bibs]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.card')).to_have_count(1)
    assert page.evaluate("localStorage.getItem('bikehuntMessagesReadCursor')") == read_state


def assert_no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('#sheetBody').evaluate('(element) => element.scrollWidth <= element.clientWidth + 1')


def open_guide(page, code, selected=False):
    page.locator('.card .compare-button').click()
    expect(page.locator('[data-merchant-guide]')).to_have_count(4)
    if selected:
        page.locator('[data-variant=S]').click()
        expect(page.locator('.guide-start')).to_have_count(4)
    page.locator(f'[data-merchant-guide={code}]').click()
    expect(page.locator('#merchantGuideTitle')).to_be_focused()
    expect(page.locator('#merchantLanguageGuide')).to_be_visible()


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
            for mode, viewport in [('desktop', {'width': 1440, 'height': 900}), ('mobile', {'width': 390, 'height': 844})]:
                state, external_reads = guide_fixture(), []
                context = browser.new_context(viewport=viewport, is_mobile=mode == 'mobile', has_touch=mode == 'mobile')
                context.set_default_timeout(7000)
                context.set_default_navigation_timeout(10000)
                context.add_init_script('window.BIKEHUNT_PAGES=true;')

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
                        result = {'brands': [{'code': 'maap', 'name': 'MAAP', 'name_zh': 'MAAP 品牌', 'offer_count': 4, 'product_count': 2, 'rule_count': 0}], 'teams': []}
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
                page.locator('[data-tab=brands]').click()
                page.locator('[data-source=maap]').click()
                page.locator('#sourceProducts').click()
                page.locator('[data-category=bibs]').click()
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
                    expect(guide.locator('form,input,select,textarea,iframe,img,[data-purchase-link],[data-reference-link]')).to_have_count(0)
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
                    expect(page.locator(f'[data-merchant-guide={code}]')).to_be_focused()
                    expect(page.locator('[data-variant=S]')).to_have_attribute('aria-pressed', 'true')
                    assert state['last_variant'] == 'S'
                    expect(page.locator('.guide-start')).to_have_count(4)
                    page.locator('#close').click()
                    assert_scope(page, base, read_state)
                open_guide(page, 'other')
                page.keyboard.press('Escape')
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                expect(page.locator('.card .compare-button')).to_be_focused()
                checks.append(mode + ': all merchant entrances, exact return variant/focus, six keyboard accordions, labelled schematic graphics, source limits, mobile translations, no forms or automatic requests')

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
                    def dismiss(dialog):
                        assert DISCLAIMER in dialog.message
                        assert '不会代你注册、登录或下单' in dialog.message
                        dialog.dismiss()
                    page.once('dialog', dismiss)
                    link.click()
                    expect(page).to_have_url(base)
                    expect(link).to_be_focused()
                    assert len(external_reads) == before
                    page.once('dialog', lambda dialog: dialog.accept())
                    with page.expect_navigation(wait_until='domcontentloaded'):
                        link.click()
                    expect(page).to_have_url(target)
                    assert len(context.pages) == 1
                    assert external_reads[-1] == target
                    page.go_back(wait_until='networkidle')
                    expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                    assert_scope(page, base, read_state)
                    page.reload(wait_until='networkidle')
                    expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                    assert_scope(page, base, read_state)
                checks.append(mode + ': scoped official-help Cancel/Continue, forced same-tab navigation, Back/reload restores source/category/search/read state without reopening a guide')

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
                expect(page.locator('[data-merchant-guide]')).to_have_count(4)
                page.locator('[data-merchant-guide=visma]').click()
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
