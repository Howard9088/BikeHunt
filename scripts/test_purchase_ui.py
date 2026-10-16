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
from exit_dialog_test_support import assert_exit_closed, assert_exit_dialog, open_final_exit, cancel_exit_dialog, confirm_exit_dialog

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'artifacts' / 'acceptance'



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
                assert_exit_closed(page)
                page.locator('[data-variant="S"]').click()
                assert_exit_closed(page)
                expect(page.locator('.offer .payment-feasibility')).to_have_count(1)
                page.locator('.guide-start').click()
                expect(page.locator('#routeComparison')).to_be_visible()
                expect(page.locator('#routeContinue')).to_be_disabled()
                expect(page.locator('.registration-help')).to_have_count(0)
                page.locator('#sheet').evaluate('el=>Promise.all(el.getAnimations().map(a=>a.finished.catch(()=>{})))')
                page.screenshot(path=str(OUTPUT / f'purchase_{mode}_routes.png'))
                # Plain policy/source anchors use the same final gate and
                # same tab, even if their original markup requested a popup.
                page.evaluate("document.querySelector('#routeComparison').insertAdjacentHTML('beforeend','<a id=ordinaryLink target=_blank href=https://merchant.example/policy>规则原文</a>')")
                ordinary_link = page.locator('#ordinaryLink')
                ordinary_link.click()
                assert_exit_dialog(page, 'https://merchant.example/policy', official=False)
                assert external_reads == [] and len(context.pages) == 1
                cancel_exit_dialog(page)
                expect(ordinary_link).to_be_focused()
                expect(page.locator('#routeComparison')).to_be_visible()
                ordinary_link.click(modifiers=['Control'])
                confirm_exit_dialog(page, 'https://merchant.example/policy', official=False)
                assert len(context.pages) == 1
                assert external_reads == ['https://merchant.example/policy']
                page.go_back(wait_until='networkidle')
                expect_purchase_restored(page)
                select_purchase_route(page)
                expect(page.locator('#registrationInterstitial')).to_contain_text('MAAP')
                page.screenshot(path=str(OUTPUT / f'purchase_{mode}_registration.png'))
                page.reload(wait_until='networkidle')
                expect_purchase_restored(page, 'registration')
                for attempt in range(3):
                    open_final_exit(page, 'https://merchant.example/bib?variant=S', modifiers=['Control'] if attempt == 1 else [])
                    cancel_exit_dialog(page)
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
                open_final_exit(page, 'https://merchant.example/bib?variant=S')
                confirm_exit_dialog(page, 'https://merchant.example/bib?variant=S')
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
                checks.append(f'{mode}: exact disclosure; generic source links use the same modal and same tab; route selection before registration; repeated dismissal and interstitial Cancel; modifier click; exact same-tab URL; interstitial reload and merchant Back restore their stage and selected size')
                # A refresh failure retains the exact last-known offer; a later explicit sellout invalidates it.
                page.locator('.guide-start').click()
                select_purchase_route(page, selected=True)
                state['detail']['offers'][0]['offer']['collection_state'] = 'retained'
                page.evaluate("window.dispatchEvent(new CustomEvent('bikehunt-published',{detail:{events:[],freshnessChanged:true}}))")
                expect(page.locator('#routeContinue')).to_be_enabled()
                state['detail']['offers'][0]['offer']['stock'] = 'out_of_stock'
                state['detail']['variants'][0]['in_stock'] = False
                state['catalog']['items'][0]['available_sizes'] = []
                page.evaluate("window.dispatchEvent(new CustomEvent('bikehunt-published',{detail:{events:[],freshnessChanged:true}}))")
                expect(page.locator('#registrationContinue:not([disabled]),#routeContinue:not([disabled])')).to_have_count(0)
                expect(page.locator('[data-purchase-link][data-offer]')).to_have_count(0)
                expect(page).to_have_url(base)
                assert external_reads == ['https://merchant.example/policy', 'https://merchant.example/bib?variant=S']
                checks.append(f'{mode}: retained snapshot preserves guarded route; explicit sold-out snapshot invalidates exit without merchant traffic')
                # A plain footer reference has no specialized data-* guard and
                # must receive the same modal even outside the product sheet.
                page.locator('#close').click()
                page.evaluate("document.querySelector('footer.footer').insertAdjacentHTML('beforeend','<a id=footerPolicyLink target=_blank href=https://merchant.example/policy>规则原文</a>')")
                footer_link = page.locator('#footerPolicyLink')
                footer_link.click()
                assert_exit_dialog(page, 'https://merchant.example/policy', official=False)
                assert external_reads == ['https://merchant.example/policy', 'https://merchant.example/bib?variant=S']
                cancel_exit_dialog(page, escape=True)
                expect(footer_link).to_be_focused()
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                footer_link.click(button='middle')
                confirm_exit_dialog(page, 'https://merchant.example/policy', official=False)
                assert len(context.pages) == 1
                assert external_reads == ['https://merchant.example/policy', 'https://merchant.example/bib?variant=S', 'https://merchant.example/policy']
                page.go_back(wait_until='networkidle')
                expect(page).to_have_url(base)
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                assert_exit_closed(page)
                checks.append(f'{mode}: generic footer rules link uses exact domain and target-site label; Escape restores link focus; middle-click confirmation navigates only in the same tab; Back stays outside the product sheet')
                context.close()
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        (OUTPUT / 'purchase_results.json').write_text(json.dumps({'checks': checks, 'errors': errors}, ensure_ascii=False, indent=2))
    assert not errors, errors
    print(json.dumps({'ok': True, 'checks': checks}, ensure_ascii=False))


if __name__ == '__main__':
    main()
