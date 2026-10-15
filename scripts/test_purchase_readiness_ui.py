"""Hermetic desktop/mobile readiness QA; external destinations are mocked GETs only."""
from __future__ import annotations

import copy
import json
import os
import shutil
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from test_catalog_messages_ui import ROOT, OUT, QuietHandler, fixture, assert_disclaimer


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/web/'
    errors, checks = [], []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'), headless=True)
            for mode, viewport in [('desktop', {'width': 1440, 'height': 900}), ('mobile', {'width': 390, 'height': 844})]:
                state, external = fixture(), []
                original = state['detail']['offers'][0]
                state['detail']['offers'] = []
                for code, market, url in [('maap', '', 'https://maap.cc/products/example'), ('visma', 'US 市场报价（USD）', 'https://www.teamvismaleaseabike.com/shop/example/'), ('poc', 'Global EN', 'https://poc.com/en/example'), ('teamcycles', '英国站', 'https://www.teamcycles.com/example')]:
                    quote = copy.deepcopy(original)
                    quote['offer'].update(source_code=code, source_name=code, offer_id='offer-'+code, sales_region=market, url=url)
                    state['detail']['offers'].append(quote)
                unchanged = json.dumps(state['detail']['offers'], sort_keys=True)
                context = browser.new_context(viewport=viewport, is_mobile=mode == 'mobile', has_touch=mode == 'mobile')
                context.set_default_timeout(7000)
                context.add_init_script('window.BIKEHUNT_PAGES=true;')

                def intercept(route):
                    url = urlparse(route.request.url)
                    if url.netloc != urlparse(base).netloc:
                        if url.netloc == 'www.myus.com':
                            assert route.request.method == 'GET'
                            external.append(route.request.url)
                            return route.fulfill(content_type='text/html', body='<title>Official calculator fixture</title><p>Read-only test destination.</p>')
                        return route.abort()
                    if not url.path.startswith('/api/'):
                        return route.continue_()
                    if url.path == '/api/catalog':
                        value = state['catalog']
                    elif url.path.startswith('/api/catalog/'):
                        value = state['detail']
                    elif url.path == '/api/directories':
                        value = {'brands': [], 'teams': []}
                    elif url.path == '/api/updates':
                        value = {'items': [], 'cursor': 0, 'fx': state['catalog']['fx']}
                    elif url.path.startswith('/api/rules/'):
                        value = {'version': 1, 'documents': []}
                    elif url.path.startswith('/api/fit/'):
                        value = {'state': 'no_chart', 'note_zh': '测试数据', 'candidate_sizes': [], 'required_measurements': [], 'source_url': None, 'checked_at': None, 'chart_rows': []}
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
                expect(page.locator('.amazon-market .payment-feasibility')).to_have_count(4)
                expect(page.locator('.amazon-market .purchase-readiness,.amazon-market .registration-help')).to_have_count(0)
                expect(page.locator('.amazon-market [data-china-card-status=conditional]')).to_have_count(4)
                for card in page.locator('.amazon-market').all():
                    expect(card.locator('.payment-feasibility')).to_contain_text('中国发行卡')
                    expect(card.locator('.payment-feasibility')).to_contain_text('不保证')
                for country in ['德国站', '日本站']:
                    expect(page.locator('.amazon-market').filter(has=page.locator('.amazon-country', has_text=country)).locator('.payment-feasibility')).to_contain_text('历史官方资料')
                assert external == []
                explain = page.locator('.forwarding-explainer')
                explain.locator('>summary').focus()
                page.keyboard.press('Enter')
                expect(explain).to_have_attribute('open', '')
                expect(explain).to_contain_text('US$9.99/月')
                expect(explain).to_contain_text('不低报')
                expect(explain.locator('form,input,textarea,select,iframe')).to_have_count(0)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert page.locator('#sheetBody').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
                link = page.locator('a[data-readiness-link=myus]').first
                target = link.get_attribute('href')
                expect(link).to_have_attribute('target', '_self')
                page.once('dialog', lambda dialog: (assert_disclaimer(dialog), dialog.dismiss()))
                link.click()
                expect(page).to_have_url(base)
                assert external == []
                page.once('dialog', lambda dialog: (assert_disclaimer(dialog), dialog.accept()))
                with page.expect_navigation(wait_until='domcontentloaded'):
                    link.click()
                expect(page).to_have_url(target)
                assert len(context.pages) == 1 and external == [target]
                page.go_back(wait_until='networkidle')
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                page.locator('.card .compare-button').first.click()
                page.locator('[data-variant=S]').click()
                expect(page.locator('.offer .payment-feasibility')).to_have_count(4)
                expect(page.locator('#sheetBody .purchase-readiness,#sheetBody .registration-help,[data-merchant-guide]')).to_have_count(0)
                for card in page.locator('.offer').all():
                    expect(card.locator('.payment-feasibility')).to_contain_text('中国发行卡')
                    expect(card.locator('.payment-feasibility')).to_contain_text('不保证')
                expect(page.locator('.offer[data-source=teamcycles] [data-china-card-status]')).to_have_attribute('data-china-card-status', 'unknown')
                page.locator('.guide-start[data-offer=offer-visma]').click()
                routes = page.locator('#routeComparison')
                expect(routes).to_be_visible()
                expect(routes.locator('.registration-help')).to_have_count(0)
                expect(routes).to_contain_text('EUR 47.95')
                page.locator('#routeBack').click()
                expect(page.locator('[data-variant=S]')).to_have_attribute('aria-pressed', 'true')
                page.locator('.guide-start[data-offer=offer-maap]').click()
                expect(page.locator('#routeComparison [data-route=direct]')).to_have_attribute('data-route-status', 'prohibited')
                expect(page.locator('#routeComparison [data-route-select=direct]')).to_be_disabled()
                expect(page.locator('#routeContinue')).to_be_disabled()
                page.locator('#routeBack').click()
                page.locator('.guide-start[data-offer=offer-poc]').click()
                expect(page.locator('#routeComparison [data-route=forwarding]')).to_have_attribute('data-route-status', 'prohibited')
                expect(page.locator('#routeComparison [data-route-select=forwarding]')).to_be_disabled()
                page.locator('#routeBack').click()
                # The retained language helper is read-only and carries no purchase setup.
                page.evaluate("openMerchantGuide(currentProduct, 'maap', 'S')")
                guide = page.locator('#merchantLanguageGuide')
                expect(guide.locator('.purchase-readiness,.registration-help,.registration-guide')).to_have_count(0)
                expect(guide.locator('[data-purchase-link],[data-reference-link],form,input')).to_have_count(0)
                expect(guide.locator('.merchant-translation')).to_be_visible()
                page.locator('#sheetBody').evaluate('el => el.scrollTop=0')
                page.screenshot(path=str(OUT / f'purchase_readiness_{mode}.png'))
                page.locator('#merchantGuideBack').click()
                expect(page.locator('[data-variant=S]')).to_have_attribute('aria-pressed', 'true')
                assert json.dumps(state['detail']['offers'], sort_keys=True) == unchanged
                page.keyboard.press('Escape')
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                checks.append(mode + ': four compact Amazon payment strips, historical evidence, no early registration, China-card caveats, route-scoped EUR shipping and prohibited direct/forwarding choices, retailer isolation, forwarding costs, keyboard, no overflow, guarded same-tab Cancel/Continue/Back and unchanged offers')
                context.close()
            browser.close()
        assert not errors, errors
        print(json.dumps({'status': 'passed', 'checks': checks, 'page_errors': errors}, ensure_ascii=False))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
