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
from test_catalog_messages_ui import OUT, ROOT, QuietHandler, select_purchase_route, cancel_purchase_to_detail
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
                page.locator('#q').fill('Guide Bib')
                expect(page.locator('.card')).to_have_count(1)
                page.locator('.card .compare-button').click()
                expect(page.locator('#variant')).to_be_visible()
                expect(page.locator('#sheetBody .registration-help,#sheetBody .purchase-readiness,[data-merchant-guide]')).to_have_count(0)
                page.locator('[data-variant=S]').click()
                page.locator('.guide-start[data-offer=offer-visma]').click()
                select_purchase_route(page)
                interstitial = page.locator('#registrationInterstitial')
                expect(interstitial.locator('[data-registration-source]:not([data-registration-source=visma])')).to_have_count(0)
                pending = interstitial.locator('[data-registration-source=visma][data-registration-scope=market]')
                expect(pending).to_have_count(1)
                expect(pending).to_have_attribute('open', '')
                expect(pending).to_be_hidden()
                expect(pending.locator('.registration-content')).to_have_text('')
                expect(pending.locator('img')).to_have_count(0)
                public = interstitial.locator('[data-registration-scope=public_account]')
                expect(public).to_have_count(1)
                public.locator('>summary').focus()
                page.keyboard.press('Enter')
                expect(public).to_have_attribute('open', '')
                expect(public.locator('img')).to_have_count(6)
                for image in public.locator('.registration-preview img').all():
                    image.scroll_into_view_if_needed()
                    expect(image).to_be_visible()
                    expect(image).to_have_js_property('naturalWidth', 1170)
                zoom = public.locator('.registration-zoom').first
                zoom.locator('>summary').focus()
                page.keyboard.press('Enter')
                expect(zoom).to_have_attribute('open', '')
                viewport_node = zoom.locator('.registration-zoom-viewport')
                expect(zoom.locator('img')).to_have_js_property('naturalWidth', 1170)
                assert zoom.locator('img').evaluate('(el) => el.getBoundingClientRect().width === el.naturalWidth')
                assert viewport_node.evaluate('(el) => el.scrollWidth > el.clientWidth')
                expect(zoom.locator('.registration-annotation')).not_to_have_count(0)
                viewport_node.focus()
                page.keyboard.press('ArrowRight')
                page.wait_for_timeout(100)
                assert viewport_node.evaluate('(el) => el.scrollLeft > 0')
                assert_no_overflow(page)
                page.screenshot(path=str(OUT / f'registration_zoom_{mode}.png'))
                page.keyboard.press('Escape')
                expect(zoom).not_to_have_attribute('open', '')
                expect(zoom.locator('>summary')).to_be_focused()
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'false')
                expect(public).to_contain_text('账户注册图解')
                expect(public).not_to_contain_text('图解版本')
                expect(public).not_to_contain_text('截图视口')
                expect(public).to_contain_text('2026-10-15')
                expect(public).to_contain_text('Register＝注册入口')
                expect(public).to_contain_text('Country＝国家')
                expect(public).to_contain_text('Create account＝创建账户')
                expect(public.locator('form,input,select,textarea,iframe,a')).to_have_count(0)
                expect(interstitial.locator('[data-reference-link],[data-purchase-link]')).to_have_count(0)
                expect(page.locator('#registrationContinue')).to_be_enabled()
                assert_no_overflow(page)
                public.locator('>summary').scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / f'registration_visma_{mode}.png'))
                public.locator('>summary').press('Space')
                expect(public).not_to_have_attribute('open', '')
                # Mark a page changed: hide real images without inventing a date-based expiry.
                state['screenshots']['entries'][0].update(status='needs_review', reviewReason='测试：原站账户页面布局已变化。')
                page.evaluate('loadRegistrationGuides()')
                expect(page.locator('#registrationInterstitial [data-registration-scope=public_account] img')).to_have_count(0)
                expect(page.locator('#registrationInterstitial [data-registration-scope=public_account]')).to_have_count(0)
                expect(page.locator('#registrationInterstitial')).not_to_contain_text('测试：原站账户页面布局已变化。')
                state['screenshots'] = copy.deepcopy(config)
                page.evaluate('loadRegistrationGuides()')
                expect(page.locator('#registrationInterstitial [data-registration-scope=public_account] img')).to_have_count(6)
                state['config_failure'] = True
                page.evaluate('loadRegistrationGuides()')
                expect(page.locator('#registrationInterstitial [data-registration-scope=public_account]')).to_have_count(0)
                expect(page.locator('#registrationInterstitial [data-registration-scope=market]')).to_be_hidden()
                state['config_failure'] = False
                page.evaluate('loadRegistrationGuides()')
                cancel_purchase_to_detail(page)
                expect(page.locator('[data-variant=S]')).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('#sheetBody .registration-help')).to_have_count(0)
                assert state['last_variant'] == 'S'
                page.locator('#close').click()
                page.locator('#amazonChannels').click()
                expect(page.locator('.amazon-market')).to_have_count(4)
                expect(page.locator('.amazon-market .registration-help,.amazon-market .purchase-readiness')).to_have_count(0)
                for code, label in [('amazon_us', '美国站'), ('amazon_uk', '英国站'), ('amazon_de', '德国站'), ('amazon_jp', '日本站')]:
                    page.locator(f'[data-amazon-search-link="{code}_jerseys"]').click()
                    interstitial = page.locator('#registrationInterstitial')
                    expect(interstitial).to_be_visible()
                    guide = interstitial.locator(f'[data-registration-source={code}]')
                    expect(guide).to_have_attribute('data-registration-market', label)
                    expect(interstitial.locator('[data-registration-source]')).to_have_count(1)
                    expect(guide).to_have_attribute('open', '')
                    expect(guide).to_be_hidden()
                    expect(guide.locator('.registration-content')).to_have_text('')
                    expect(guide.locator('img')).to_have_count(0)
                    expect(interstitial.locator('form,input,select,textarea,iframe')).to_have_count(0)
                    assert_no_overflow(page)
                    page.locator('#registrationCancel').click()
                    expect(page.locator('.amazon-market')).to_have_count(4)
                    expect(page.locator('[data-amazon-search-link]')).to_have_count(8)
                    expect(page.locator('#registrationInterstitial')).to_have_count(0)
                assert external_requests == [], 'Reading screenshots never contacts merchant sites'
                page.keyboard.press('Escape')
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                expect(page.locator('#amazonChannels')).to_be_focused()
                checks.append(mode + ': three real Visma images/notes with local original-resolution zoom, overlays, keyboard scroll and Escape focus return; unverified exact-market guide hidden; optional keyboard details; source/date without diagnostics; no forms or merchant requests; disabled and failed-refresh withdrawal; four source-scoped Amazon interstitials after explicit exit; no early registration; no overflow; safe route Back/Close')
                context.close()
            browser.close()
        assert errors == [], errors
        print(json.dumps({'passed': checks, 'page_errors': errors}, ensure_ascii=False, indent=2))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
