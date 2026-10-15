"""Hermetic desktop/mobile regression tests for the brand, inventory and purchase exit.

Run: python scripts/test_purchase_ui.py
Uses system Chromium (or CHROME_EXECUTABLE), intercepts all API/merchant requests,
and never visits a merchant or submits a purchase. Screenshots use labelled fixtures.
"""
from __future__ import annotations
import json
import os
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright
from test_catalog_messages_ui import fixture, select_purchase_route, expect_purchase_restored, cancel_purchase_to_detail, assert_disclaimer

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'artifacts' / 'acceptance'
DISCLAIMER = '本站仅提供商品与优惠信息，不参与交易。价格、库存、尺码及折扣可能变化，信息不保证完全准确，请以实际商家页面及结算信息为准，并在购买前自行核实。购买、付款、配送、退换货，以及买错商品或尺码不合适等问题，请直接联系实际商家。法律规定本站应承担的责任除外。'



class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/web/'
    checks, errors = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'), headless=True)
            for mode, viewport in [('desktop', {'width': 1440, 'height': 900}), ('mobile', {'width': 390, 'height': 844}), ('small_mobile', {'width': 375, 'height': 667})]:
                state = fixture()
                external_reads = []
                context = browser.new_context(viewport=viewport, is_mobile=mode != 'desktop', has_touch=mode != 'desktop')
                context.add_init_script('window.BIKEHUNT_PAGES=true;')
                def intercept(route):
                    url = urlparse(route.request.url)
                    if url.netloc == 'merchant.example':
                        if url.path.endswith('.svg'):
                            return route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 600 600"><rect width="600" height="600" fill="#eef1f4"/><path d="M200 90h70v155h60V90h70l-20 250 28 150H302l-2-120-2 120H192l28-150Z" fill="#fff" stroke="#c7d0d9" stroke-width="4"/><text x="300" y="554" text-anchor="middle" font-family="sans-serif" font-size="18" fill="#667788">UI regression fixture</text></svg>')
                        assert route.request.method == 'GET'
                        assert route.request.url in {'https://merchant.example/bib?variant=S', 'https://merchant.example/policy'}
                        external_reads.append(route.request.url)
                        return route.fulfill(body='Merchant navigation test only')
                    if url.netloc != urlparse(base).netloc:
                        return route.abort()
                    path = url.path
                    if not path.startswith('/api/'):
                        return route.continue_()
                    if path == '/api/catalog': result = state['catalog']
                    elif path.startswith('/api/catalog/'): result = state['detail']
                    elif path == '/api/directories': result = {'brands': [], 'teams': []}
                    elif path.startswith('/api/rules/'): result = {'version': 1, 'documents': []}
                    elif path.startswith('/api/fit/'): result = {'state': 'no_chart', 'note_zh': '测试数据', 'candidate_sizes': [], 'chart_rows': []}
                    else: result = {}
                    route.fulfill(content_type='application/json', body=json.dumps(result))
                context.route('**/*', intercept)
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base, wait_until='networkidle')
                expect(page.locator('.card')).to_have_count(1)
                expect(page.locator('[data-id="sold-out"]')).to_have_count(0)
                page.evaluate("openProduct('sold-out')")
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                expect(page.locator('.bikehunt-mark')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                cta = page.locator('.card .compare-button').first.bounding_box()
                assert cta and cta['y'] + cta['height'] <= viewport['height'], cta
                page.screenshot(path=str(OUTPUT / f'purchase_{mode}_feed.png'))
                checks.append(f'{mode}: sold-out hidden; stale open blocked; responsive logo and CTA')
                page.once('dialog', lambda dialog: (assert_disclaimer(dialog), dialog.dismiss()))
                page.locator('#purchaseDisclaimerInfo').click()
                expect(page).to_have_url(base)
                page.locator('.card .compare-button').first.click()
                expect(page.locator('[data-variant="S"]')).to_be_enabled()
                expect(page.locator('[data-variant="M"],[data-variant="XL"]')).to_have_count(0)
                expect(page.locator('#variant option[value="M"],#variant option[value="XL"]')).to_have_count(0)
                expect(page.locator('.registration-help,.purchase-readiness,[data-merchant-guide]')).to_have_count(0)
                page.locator('[data-variant="S"]').click()
                expect(page.locator('.offer .payment-feasibility')).to_have_count(1)
                page.locator('.guide-start').click()
                expect(page.locator('#routeComparison')).to_be_visible()
                expect(page.locator('#routeContinue')).to_be_disabled()
                expect(page.locator('.registration-help')).to_have_count(0)
                page.locator('#sheet').evaluate('el=>Promise.all(el.getAnimations().map(a=>a.finished.catch(()=>{})))')
                page.screenshot(path=str(OUTPUT / f'purchase_{mode}_routes.png'))
                # Policy/source links remain ordinary links, outside the guarded purchase exit.
                page.evaluate("document.querySelector('#routeComparison').insertAdjacentHTML('beforeend','<a id=ordinaryLink target=_blank href=https://merchant.example/policy>规则原文</a>')")
                with context.expect_page() as popup:
                    page.locator('#ordinaryLink').click()
                popup.value.wait_for_load_state()
                assert popup.value.url == 'https://merchant.example/policy'
                popup.value.close()
                assert external_reads == ['https://merchant.example/policy']
                select_purchase_route(page)
                expect(page.locator('#registrationInterstitial')).to_contain_text('MAAP')
                page.screenshot(path=str(OUTPUT / f'purchase_{mode}_registration.png'))
                page.reload(wait_until='networkidle')
                expect_purchase_restored(page, 'registration')
                for attempt in range(3):
                    page.once('dialog', lambda dialog: (assert_disclaimer(dialog), dialog.dismiss()))
                    page.locator('#registrationContinue').click(modifiers=['Control'] if attempt == 1 else [])
                    expect(page.locator('#routeComparison')).to_be_visible()
                    expect(page).to_have_url(base)
                    assert len(context.pages) == 1
                    assert external_reads == ['https://merchant.example/policy']
                    page.locator('#routeContinue').click()
                page.locator('#registrationCancel').click()
                expect(page.locator('#routeComparison')).to_be_visible()
                expect(page.locator('#routeContinue')).to_be_enabled()
                page.locator('#routeContinue').click()
                expect(page.locator('#registrationInterstitial')).to_be_visible()
                page.once('dialog', lambda dialog: (assert_disclaimer(dialog), dialog.accept()))
                with page.expect_navigation(wait_until='domcontentloaded'):
                    page.locator('#registrationContinue').click()
                expect(page).to_have_url('https://merchant.example/bib?variant=S')
                assert len(context.pages) == 1
                assert external_reads == ['https://merchant.example/policy', 'https://merchant.example/bib?variant=S']
                page.go_back(wait_until='networkidle')
                expect_purchase_restored(page)
                page.reload(wait_until='networkidle')
                expect_purchase_restored(page)
                cancel_purchase_to_detail(page)
                expect(page.locator('[data-variant=S]')).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('.guide-start[data-offer=offer-s]')).to_be_enabled()
                checks.append(f'{mode}: exact disclosure; ordinary source links; route selection before registration; repeated dismissal and interstitial Cancel; modifier click; exact same-tab URL; interstitial reload and merchant Back restore their stage and selected size')
                # A published retained/sold-out result invalidates the pending registration exit.
                page.locator('.guide-start').click()
                select_purchase_route(page, selected=True)
                state['detail']['offers'][0]['offer']['collection_state'] = 'retained'
                state['detail']['variants'][0]['in_stock'] = False
                state['catalog']['items'][0]['available_sizes'] = []
                page.evaluate("window.dispatchEvent(new CustomEvent('bikehunt-published',{detail:{events:[],freshnessChanged:true}}))")
                expect(page.locator('#registrationContinue:not([disabled]),#routeContinue:not([disabled])')).to_have_count(0)
                expect(page.locator('[data-purchase-link][data-offer]')).to_have_count(0)
                expect(page).to_have_url(base)
                assert external_reads == ['https://merchant.example/policy', 'https://merchant.example/bib?variant=S']
                checks.append(f'{mode}: retained snapshot invalidates pending route/registration exit without merchant traffic')
                context.close()
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        (OUTPUT / 'purchase_results.json').write_text(json.dumps({'checks': checks, 'errors': errors}, ensure_ascii=False, indent=2))
    assert not errors, errors
    print(json.dumps({'ok': True, 'checks': checks}, ensure_ascii=False))


if __name__ == '__main__':
    main()
