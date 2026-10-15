"""Hermetic desktop/mobile ordered purchase-flow regression; all external GETs mocked."""
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


def assert_no_early_registration(page):
    expect(page.locator('.registration-help')).to_have_count(0)
    expect(page.locator('#registrationInterstitial')).to_have_count(0)


def assert_routes(page):
    panel = page.locator('#routeComparison')
    expect(panel).to_be_visible()
    expect(panel.locator('[data-route]')).to_have_count(3)
    for route in ['direct', 'forwarding', 'hongkong']:
        card = panel.locator(f'[data-route="{route}"]')
        expect(card).to_be_visible()
        assert card.get_attribute('data-route-status') in {'confirmed', 'conditional', 'unknown', 'prohibited'}
        expect(card.locator(f'[data-route-select="{route}"]')).to_have_count(1)
    assert_no_early_registration(page)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert panel.evaluate('el => el.scrollWidth <= el.clientWidth + 1')


def select_route(page, name):
    page.locator(f'[data-route-select="{name}"]').click()
    expect(page.locator('#routeContinue')).to_be_enabled()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/web/'
    errors, checks = [], []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'), headless=True)
            for mode, viewport in [('desktop', {'width': 1440, 'height': 900}), ('mobile', {'width': 390, 'height': 844}), ('small_mobile', {'width': 320, 'height': 740})]:
                state, outbound = fixture(), []
                state['detail']['offers'] = []
                for code, market, host in [('visma', 'US 市场报价（USD）', 'www.teamvismaleaseabike.com'), ('maap', '', 'maap.cc'), ('poc', 'Global EN', 'poc.com'), ('teamcycles', '英国站', 'www.teamcycles.com')]:
                    q = copy.deepcopy(fixture()['detail']['offers'][0])
                    q['offer'].update(offer_id='offer-'+code, source_code=code, source_name=code, sales_region=market, url=f'https://{host}/products/test?variant=S')
                    state['detail']['offers'].append(q)
                baseline = copy.deepcopy(state['detail'])
                context = browser.new_context(viewport=viewport, is_mobile=mode != 'desktop', has_touch=mode != 'desktop')
                context.set_default_timeout(7000)
                context.add_init_script('window.BIKEHUNT_PAGES=true;')

                def intercept(route):
                    parsed = urlparse(route.request.url)
                    if parsed.netloc != urlparse(base).netloc:
                        if parsed.netloc == 'merchant.example' and parsed.path.endswith('.svg'):
                            return route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"/>')
                        assert route.request.method == 'GET', 'Regression must never submit a merchant form'
                        outbound.append(route.request.url)
                        return route.fulfill(content_type='text/html', body='<title>Mock official destination</title><p>Navigation fixture only.</p>')
                    if not parsed.path.startswith('/api/'):
                        return route.continue_()
                    if parsed.path == '/api/catalog':
                        value = state['catalog']
                    elif parsed.path.startswith('/api/catalog/'):
                        value = state['detail']
                        state['last_variant'] = parse_qs(parsed.query).get('variant_id', [None])[0]
                    elif parsed.path == '/api/directories':
                        value = {'brands': [], 'teams': []}
                    elif parsed.path == '/api/updates':
                        value = {'items': [], 'cursor': 0, 'fx': state['catalog']['fx']}
                    elif parsed.path.startswith('/api/rules/'):
                        value = {'version': 1, 'documents': []}
                    elif parsed.path.startswith('/api/fit/'):
                        value = {'state': 'no_chart', 'note_zh': '测试数据', 'candidate_sizes': [], 'required_measurements': [], 'source_url': None, 'checked_at': None, 'chart_rows': []}
                    elif parsed.path == '/api/community':
                        value = {'schema_version': 1, 'available': False, 'configured': False}
                    else:
                        value = {}
                    return route.fulfill(content_type='application/json', body=json.dumps(value))

                context.route('**/*', intercept)
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base, wait_until='networkidle')
                page.locator('.card .compare-button').first.click()
                assert_no_early_registration(page)
                page.locator('[data-variant="S"]').click()
                expect(page.locator('.offer .payment-feasibility')).to_have_count(4)
                expect(page.locator('.offer .purchase-readiness')).to_have_count(0)
                assert_no_early_registration(page)
                for compact in page.locator('.offer .payment-feasibility').all():
                    expect(compact).to_contain_text('中国')
                page.locator('[data-offer="offer-maap"]').click()
                assert_routes(page)
                expect(page.locator('#routeContinue')).to_be_disabled()
                expect(page.locator('[data-route="direct"]')).to_have_attribute('data-route-status', 'prohibited')
                expect(page.locator('[data-route-select="direct"]')).to_be_disabled()
                expect(page.locator('[data-route="hongkong"]')).to_have_attribute('data-route-status', 'unknown')
                select_route(page, 'hongkong')
                expect(page.locator('#routeContinue')).to_contain_text('去官网核实')
                page.screenshot(path=str(OUT / f'purchase_routes_unknown_{mode}.png'))
                page.locator('#routeBack').click()
                expect(page.locator('[data-variant="S"]')).to_have_attribute('aria-pressed', 'true')
                assert_no_early_registration(page)
                page.locator('[data-offer="offer-poc"]').click()
                assert_routes(page)
                expect(page.locator('[data-route="forwarding"]')).to_have_attribute('data-route-status', 'prohibited')
                expect(page.locator('[data-route-select="forwarding"]')).to_be_disabled()
                page.locator('#routeBack').click()
                page.locator('[data-offer="offer-teamcycles"]').click()
                assert_routes(page)
                for route in ['direct', 'forwarding', 'hongkong']:
                    expect(page.locator(f'[data-route="{route}"]')).to_have_attribute('data-route-status', 'unknown')
                page.locator('#routeBack').click()
                page.locator('[data-offer="offer-visma"]').click()
                assert_routes(page)
                expect(page.locator('[data-route="direct"]')).to_have_attribute('data-route-status', 'conditional')
                expect(page.locator('[data-route="direct"]')).to_contain_text('EUR 47.95')
                select_route(page, 'direct')
                page.locator('#routeContinue').click()
                expect(page.locator('#registrationInterstitial')).to_be_visible()
                expect(page.locator('#registrationInterstitial .registration-help')).to_have_count(1)
                expect(page.locator('#registrationInterstitial')).to_contain_text('visma')
                expect(page.locator('#registrationInterstitial form, #registrationInterstitial input, #registrationInterstitial textarea, #registrationInterstitial select')).to_have_count(0)
                assert outbound == [], 'Stages and screenshots must not contact a merchant'
                saved = page.evaluate('history.state.bikehuntPurchase')
                assert saved['productId'] == 'partial' and saved['variantId'] == 'S'
                assert saved['offerId'] == 'offer-visma' and saved['sourceCode'] == 'visma'
                assert saved['route'] == 'direct' and saved['stage'] == 'registration'
                assert urlparse(page.url).query == '' and urlparse(page.url).fragment == ''
                page.locator('#registrationCancel').click()
                assert_routes(page)
                expect(page.locator('[data-route-select="direct"]')).to_have_attribute('aria-pressed', 'true')
                page.locator('#routeContinue').click()
                dialogs = []
                def dismiss(dialog):
                    dialogs.append(dialog.message)
                    assert DISCLAIMER in dialog.message
                    dialog.dismiss()
                page.once('dialog', dismiss)
                page.locator('#registrationContinue').click()
                assert len(dialogs) == 1 and outbound == []
                assert_routes(page)
                page.locator('#routeContinue').click()
                expect(page.locator('#registrationInterstitial')).to_be_visible()
                page.reload(wait_until='networkidle')
                expect(page.locator('#registrationInterstitial')).to_be_visible()
                expect(page.locator('#registrationInterstitial .registration-help')).to_have_count(1)
                target = baseline['offers'][0]['offer']['url']
                page.once('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.accept()))
                with page.expect_navigation(wait_until='domcontentloaded'):
                    page.locator('#registrationContinue').click()
                assert DISCLAIMER in dialogs[-1]
                expect(page).to_have_url(target)
                assert len(context.pages) == 1 and outbound == [target]
                page.go_back(wait_until='networkidle')
                assert_routes(page)
                expect(page.locator('[data-route-select="direct"]')).to_have_attribute('aria-pressed', 'true')
                page.locator('#routeBack').click()
                expect(page.locator('[data-variant="S"]')).to_have_attribute('aria-pressed', 'true')
                # Fresh stock metadata remains untouched by choosing a route.
                assert state['detail'] == baseline
                page.locator('#close').click()
                page.locator('#amazonChannels').click()
                assert_no_early_registration(page)
                page.locator('[data-amazon-search-link="amazon_jp_jerseys"]').click()
                expect(page.locator('#registrationInterstitial')).to_be_visible()
                expect(page.locator('[data-registration-source="amazon_jp"][data-registration-market="日本站"]')).to_have_count(1)
                expect(page.locator('[data-registration-source="amazon_us"]')).to_have_count(0)
                page.locator('#registrationCancel').click()
                expect(page.locator('.amazon-market')).to_have_count(4)
                assert_no_early_registration(page)
                # Stale stock can only plan a route, then recheck at the exact official page.
                page.locator('#close').click()
                state['detail']['offers'][0]['offer']['fetched_at'] = '2000-01-01T00:00:00Z'
                page.locator('.card .compare-button').first.click()
                page.locator('[data-variant="S"]').click()
                expect(page.locator('[data-offer="offer-visma"]')).to_be_disabled()
                page.locator('.offer[data-source="visma"] [data-reference-link]').click()
                assert_routes(page)
                expect(page.locator('#routeComparison')).to_contain_text('库存')
                select_route(page, 'direct')
                page.locator('#routeContinue').click()
                expect(page.locator('#registrationInterstitial')).to_be_visible()
                assert len(outbound) == 1
                page.screenshot(path=str(OUT / f'purchase_registration_{mode}.png'))
                checks.append(mode + ': compact payment after size; exact three routes; prohibited disabled/unknown planning; registration only after route; full disclosure; same-tab exact URL; cancel/back/reload preserve source, offer, size and route; Amazon scope; stale stock reference stage; no early merchant request')
                context.close()
            browser.close()
        assert errors == [], errors
        print(json.dumps({'passed': checks, 'page_errors': errors}, ensure_ascii=False, indent=2))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
