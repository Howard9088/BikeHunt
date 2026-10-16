"""Mocked desktop/mobile payment QA. External requests are intercepted GETs only.

The fixture is intentionally synthetic and never substitutes production research.
Run in the authorized browser CI environment; no checkout or account is accessed.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from test_catalog_messages_ui import ROOT, OUT, QuietHandler, fixture
from exit_dialog_test_support import assert_exit_closed, assert_exit_dialog, cancel_exit_dialog, confirm_exit_dialog


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/web/'
    matrix = json.loads((ROOT / 'tests/fixtures/payment-methods.json').read_text())
    catalog = json.loads((ROOT / 'web/payment-channels.json').read_text())
    errors, checks = [], []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'), headless=True)
            for mode, viewport in [('desktop', {'width': 1440, 'height': 900}), ('mobile', {'width': 390, 'height': 844}), ('small_mobile', {'width': 320, 'height': 740})]:
                state, external, failure = fixture(), [], {'payment': False}
                state['detail']['offers'][0]['offer'].update(url='https://maap.cc/products/fixture?variant=S', sales_region='',
                                                          china_issued_card={'status': 'yes', 'note': '旧字段声称中国卡已验证'})
                unchanged = json.dumps(state['detail']['offers'], sort_keys=True)
                directory = {'brands': [{'code': 'oakley', 'name': 'Oakley', 'name_zh': 'Oakley', 'offer_count': 0,
                                        'rule_count': 0, 'official_url': 'https://www.oakley.com', 'shop_url': 'https://www.oakley.com'}],
                             'teams': [{'code': 'alpecin', 'name': 'Alpecin', 'name_zh': 'Alpecin', 'offer_count': 0, 'rule_count': 0,
                                        'official_url': 'https://www.alpecin-premiertech.com/', 'shop_url': 'https://www.alpecin-premiertech.com/webshops/'}]}
                context = browser.new_context(viewport=viewport, is_mobile=mode != 'desktop', has_touch=mode != 'desktop')
                context.set_default_timeout(8000)
                context.add_init_script('window.BIKEHUNT_PAGES=true;')

                def intercept(route):
                    url = urlparse(route.request.url)
                    if url.netloc != urlparse(base).netloc:
                        if url.netloc == 'maap.cc' and url.path == '/fixture-payment-evidence':
                            assert route.request.method == 'GET'
                            external.append(route.request.url)
                            return route.fulfill(content_type='text/html', body='<title>Mock official evidence</title><p>Read-only regression destination.</p>')
                        return route.abort()
                    if url.path.endswith('/payment-methods.json'):
                        return route.fulfill(status=503 if failure['payment'] else 200,
                                             content_type='application/json', body=json.dumps(matrix))
                    if url.path.endswith('/payment-channels.json'):
                        return route.fulfill(content_type='application/json', body=json.dumps(catalog))
                    if not url.path.startswith('/api/'):
                        return route.continue_()
                    if url.path == '/api/catalog':
                        value = state['catalog']
                    elif url.path.startswith('/api/catalog/'):
                        value = state['detail']
                    elif url.path == '/api/directories':
                        value = directory
                    elif url.path == '/api/updates':
                        value = {'items': [], 'cursor': 0, 'fx': state['catalog']['fx']}
                    elif url.path.startswith('/api/rules/'):
                        value = {'version': 1, 'documents': []}
                    elif url.path.startswith('/api/fit/'):
                        value = {'state': 'no_chart', 'note_zh': '测试数据', 'candidate_sizes': [], 'required_measurements': [],
                                 'source_url': None, 'checked_at': None, 'chart_rows': []}
                    elif url.path == '/api/community':
                        value = {'schema_version': 1, 'available': False, 'configured': False}
                    else:
                        value = {}
                    return route.fulfill(content_type='application/json', body=json.dumps(value))

                context.route('**/*', intercept)
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base, wait_until='networkidle')
                page.locator('#amazonChannels').click()
                expect(page.locator('.amazon-market .payment-matrix')).to_have_count(4)
                expect(page.locator('.amazon-market .registration-help')).to_have_count(0)
                for card in page.locator('.amazon-market').all():
                    expect(card.locator('[data-china-card-status=unknown]')).to_have_count(1)
                    details = card.locator('.payment-method-details')
                    expect(details).not_to_have_attribute('open', '')
                    details.locator('>summary').focus()
                    page.keyboard.press('Enter')
                    expect(details).to_have_attribute('open', '')
                    expect(details.locator('[data-payment-method-key]')).to_have_count(11)
                    for key in ('paypal', 'alipay', 'wechat_pay', 'unionpay', 'bank_transfer_local', 'gift_cards', 'instalments'):
                        expect(details.locator(f'[data-payment-method-key={key}]')).to_be_visible()
                    details.locator('>summary').click()
                assert external == []
                assert_exit_closed(page)
                page.locator('#close').click()
                page.locator('.card .compare-button').first.click()
                page.locator('[data-variant=S]').click()
                panel = page.locator('.offer .payment-matrix')
                expect(panel.locator('[data-china-card-status]')).to_have_attribute('data-china-card-status', 'unknown')
                details = panel.locator('.payment-method-details')
                details.locator('>summary').click()
                expect(details.locator('[data-payment-method-key=paypal] [data-payment-status]')).to_have_attribute('data-payment-status', 'not_supported')
                expect(details.locator('[data-payment-method-key=apple_pay] [data-payment-status]')).to_have_attribute('data-payment-status', 'supported')
                expect(details).not_to_contain_text('旧字段声称中国卡已验证')
                expect(details.locator('form,input,textarea,select,iframe,img')).to_have_count(0)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert page.locator('#sheetBody').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
                page.screenshot(path=str(OUT / f'payment_methods_{mode}.png'))
                link = details.locator('a[data-payment-link]').first
                target = link.get_attribute('href')
                expect(link).to_have_attribute('target', '_self')
                link.click()
                assert_exit_dialog(page, target, official=False)
                assert external == []
                cancel_exit_dialog(page, escape=True)
                expect(link).to_be_focused()
                expect(details).to_have_attribute('open', '')
                link.click()
                link.evaluate('(el) => el.href="https://evil.example/replaced"')
                page.locator('#externalExitConfirm').click()
                expect(page).to_have_url(base)
                expect(page.locator('#externalExitError')).to_be_visible()
                assert external == []
                link.evaluate('(el, href) => el.href=href', target)
                cancel_exit_dialog(page)
                link.click()
                confirm_exit_dialog(page, target, official=False)
                expect(page).to_have_url(target)
                assert len(context.pages) == 1 and external == [target]
                page.go_back(wait_until='networkidle')
                # Back intentionally restores the exact product sheet; close it before switching directories.
                expect(page.locator('#sheet')).to_be_visible()
                expect(page.locator('.offer .payment-matrix')).to_be_visible()
                page.locator('#close').click()
                expect(page.locator('#overlay')).not_to_have_class('overlay open')
                page.locator('[data-tab=brands]').click()
                page.locator('.directory-card[data-source=oakley]').click()
                expect(page.locator('#channelInfo')).to_be_visible()
                assert not page.locator('#channelInfo').evaluate('el => el.open')
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                expect(page.locator('#grid .card')).to_have_count(0)
                expect(page.locator('#grid')).to_contain_text('该渠道暂无已核实有货的商品')
                page.locator('#channelInfo > summary').click()
                expect(page.locator('#channelInfo .source-payment-overview')).to_be_visible()
                expect(page.locator('.source-payment-overview [data-payment-method-key]')).to_have_count(11)
                expect(page.locator('#sourceProducts')).to_have_count(0)
                expect(page.locator('#sheetBody .registration-help')).to_have_count(0)
                page.locator('[data-tab=teams]').click()
                page.locator('.directory-card[data-source=alpecin]').click()
                assert not page.locator('#channelInfo').evaluate('el => el.open')
                page.locator('#channelInfo > summary').click()
                expect(page.locator('#channelInfo .payment-separate-merchant')).to_have_count(2)
                expect(page.locator('.payment-separate-merchant').first.locator('[data-payment-method-key=gift_cards] [data-payment-status]')).to_have_attribute('data-payment-status', 'unknown')
                expect(page.locator('.payment-separate-merchant').last.locator('[data-payment-method-key=gift_cards] [data-payment-status]')).to_have_attribute('data-payment-status', 'supported')
                page.locator('[data-tab=products]').click()
                failure['payment'] = True
                page.reload(wait_until='networkidle')
                page.locator('.card .compare-button').first.click()
                page.locator('[data-variant=S]').click()
                panel = page.locator('.offer .payment-matrix')
                expect(panel).to_contain_text('支付说明暂时无法加载')
                expect(panel).not_to_contain_text('读取或校验')
                expect(panel).not_to_contain_text('旧卡种字段')
                expect(panel.locator('[data-payment-status=unknown]')).to_have_count(11)
                expect(panel.locator('a[data-payment-link]')).to_have_count(0)
                page.locator('.guide-start').first.click()
                expect(page.locator('#routeComparison [data-route=direct]')).to_have_attribute('data-route-status', 'prohibited')
                expect(page.locator('#routeComparison .registration-help')).to_have_count(0)
                assert json.dumps(state['detail']['offers'], sort_keys=True) == unchanged
                checks.append(mode + ': all method categories, China issuer independence, scoped directory without offers, keyboard accordion, 320px layout, no early registration, guarded evidence Cancel/Continue/Back and tamper rejection, honest failed-load fallback preserving shipping restrictions')
                context.close()
            browser.close()
        assert not errors, errors
        print(json.dumps({'status': 'passed', 'checks': checks, 'page_errors': errors}, ensure_ascii=False))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
