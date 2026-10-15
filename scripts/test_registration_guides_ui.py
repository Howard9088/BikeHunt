"""Hermetic desktop/mobile real-screenshot UI checks; no merchant browsing."""
from __future__ import annotations

import copy
import json
import os
import shutil
import threading
import struct
import zlib
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright
from test_catalog_messages_ui import OUT, ROOT, QuietHandler
from test_merchant_guides_ui import guide_fixture, assert_no_overflow


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / 'tests/fixtures/registration-guides.json').read_text())
    # Test-only image bytes: never added to the real screenshot configuration.
    def chunk(kind, value):
        return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value) & 0xffffffff)
    image_fixture = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1170, 751, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\x00' + b'\xe8\xee\xf5' * 1170) * 751)) + chunk(b'IEND', b'')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/web/'
    errors, checks = [], []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'), headless=True)
            for mode, viewport in [('desktop', {'width': 1440, 'height': 900}), ('mobile', {'width': 390, 'height': 844}), ('small_mobile', {'width': 320, 'height': 740})]:
                state = guide_fixture()
                for quote in state['detail']['offers']:
                    quote['offer']['sales_region'] = 'US 市场报价（USD）'
                state['screenshots'] = copy.deepcopy(config)
                state['config_failure'] = False
                external_requests = []
                context = browser.new_context(viewport=viewport, is_mobile=mode != 'desktop', has_touch=mode != 'desktop')
                context.set_default_timeout(7000)
                context.add_init_script('window.BIKEHUNT_PAGES=true;')

                def intercept(route):
                    url = urlparse(route.request.url)
                    if url.netloc == 'merchant.example' and url.path.endswith('.svg'):
                        return route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"></svg>')
                    if url.netloc != urlparse(base).netloc:
                        external_requests.append(route.request.url)
                        return route.abort()
                    if url.path.endswith('/registration-guides.json'):
                        if state['config_failure']:
                            return route.fulfill(status=503, body='Unavailable')
                        return route.fulfill(content_type='application/json', body=json.dumps(state['screenshots']))
                    if '/assets/registration/' in url.path:
                        return route.fulfill(content_type='image/png', body=image_fixture)
                    if not url.path.startswith('/api/'):
                        return route.continue_()
                    if url.path == '/api/catalog':
                        result = state['catalog']
                    elif url.path.startswith('/api/catalog/'):
                        result = state['detail']
                        state['last_variant'] = parse_qs(url.query).get('variant_id', [None])[0]
                    elif url.path == '/api/directories':
                        result = {'brands': [], 'teams': []}
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
                page.locator('.card .compare-button').first.click()
                pending = page.locator('.reference-channel [data-registration-source=visma][data-registration-scope=market]')
                expect(pending).to_have_count(1)
                expect(pending).not_to_have_attribute('open', '')
                pending.locator('summary').press('Enter')
                expect(pending).to_contain_text('注册页面图解待核实')
                expect(pending.locator('img')).to_have_count(0)
                reference = page.locator('.reference-channel').filter(has=page.locator('[data-registration-source=visma][data-registration-scope=market]'))
                public = reference.locator('[data-registration-scope=public_account]')
                expect(public).to_have_count(1)
                public.locator('summary').focus()
                page.keyboard.press('Enter')
                expect(public).to_have_attribute('open', '')
                expect(public.locator('img')).to_have_count(3)
                for image in public.locator('img').all():
                    image.scroll_into_view_if_needed()
                    expect(image).to_be_visible()
                    expect(image).to_have_js_property('naturalWidth', 1170)
                expect(public).to_contain_text('公开账户页，销售市场未核实')
                expect(public).to_contain_text('2026-10-15')
                expect(public).to_contain_text('Register＝注册入口')
                expect(public).to_contain_text('Country＝国家')
                expect(public).to_contain_text('Create account＝创建账户')
                expect(public.locator('form,input,select,textarea,iframe,a')).to_have_count(0)
                assert reference.evaluate('(node) => node.querySelector(".registration-help").compareDocumentPosition(node.querySelector("a[data-reference-link]")) & Node.DOCUMENT_POSITION_FOLLOWING')
                assert_no_overflow(page)
                public.locator('summary').scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / f'registration_visma_{mode}.png'))
                public.locator('summary').press('Space')
                expect(public).not_to_have_attribute('open', '')
                page.locator('[data-merchant-guide=visma]').click()
                expect(page.locator('#merchantGuideTitle')).to_be_focused()
                expect(page.locator('#merchantLanguageGuide [data-registration-scope=public_account] img')).to_have_count(3)
                expect(page.locator('#merchantLanguageGuide [data-registration-scope=market] img')).to_have_count(0)
                # Mark a page changed: hide real images without inventing a date-based expiry.
                state['screenshots']['entries'][0].update(status='needs_review', reviewReason='测试：原站账户页面布局已变化。')
                page.evaluate('loadRegistrationGuides()')
                expect(page.locator('#merchantLanguageGuide [data-registration-scope=public_account] img')).to_have_count(0)
                expect(page.locator('#merchantLanguageGuide')).to_contain_text('旧图已停用')
                state['screenshots'] = copy.deepcopy(config)
                page.evaluate('loadRegistrationGuides()')
                expect(page.locator('#merchantLanguageGuide [data-registration-scope=public_account] img')).to_have_count(3)
                state['config_failure'] = True
                page.evaluate('loadRegistrationGuides()')
                expect(page.locator('#merchantLanguageGuide [data-registration-scope=public_account]')).to_have_count(0)
                expect(page.locator('#merchantLanguageGuide [data-registration-scope=market]')).to_contain_text('暂时无法读取')
                state['config_failure'] = False
                page.evaluate('loadRegistrationGuides()')
                page.locator('#merchantGuideBack').click()
                expect(page.locator('[data-merchant-guide=visma]')).to_be_focused()
                page.locator('#close').click()
                page.locator('#amazonChannels').click()
                markets = page.locator('.amazon-market')
                expect(markets).to_have_count(4)
                for i, (code, label) in enumerate([('amazon_us', '美国站'), ('amazon_uk', '英国站'), ('amazon_de', '德国站'), ('amazon_jp', '日本站')]):
                    market = markets.nth(i)
                    guide = market.locator(f'[data-registration-source={code}]')
                    expect(guide).to_have_attribute('data-registration-market', label)
                    guide.locator('summary').click()
                    expect(guide).to_contain_text('本次云端未能打开页面')
                    expect(guide.locator('img')).to_have_count(0)
                    expect(market.locator('a[data-amazon-search-link]')).to_have_count(2)
                    assert market.evaluate('(node) => node.querySelector(".registration-help").compareDocumentPosition(node.querySelector(".amazon-search-links")) & Node.DOCUMENT_POSITION_FOLLOWING')
                    assert_no_overflow(page)
                    guide.locator('summary').click()
                assert external_requests == [], 'Reading screenshots never contacts merchant sites'
                page.keyboard.press('Escape')
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                expect(page.locator('#amazonChannels')).to_be_focused()
                checks.append(mode + ': three real Visma images/notes; exact-market pending; optional keyboard details; source/version; no forms or merchant requests; disabled and failed-refresh withdrawal; four separate Amazon cards; no overflow; safe Back/Close')
                context.close()
            browser.close()
        assert errors == [], errors
        print(json.dumps({'passed': checks, 'page_errors': errors}, ensure_ascii=False, indent=2))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
