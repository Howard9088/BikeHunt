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
from test_catalog_messages_ui import OUT, ROOT, QuietHandler, fixture
from exit_dialog_test_support import (assert_exit_closed, assert_exit_layout, assert_exit_focus_trap, open_final_exit, cancel_exit_dialog, confirm_exit_dialog)


def assert_no_early_registration(page):
    assert_exit_closed(page)
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


def assert_action_colors(locator, selected=True):
    """Check rendered hierarchy, not CSS text; keep native disabled semantics."""
    colors = locator.evaluate("""el => {
        const style = getComputedStyle(el);
        const probe = document.createElement('span');
        probe.style.color = 'var(--blue)';
        document.body.append(probe);
        const blue = getComputedStyle(probe).color;
        probe.remove();
        return {background: style.backgroundColor, color: style.color,
                border: style.borderTopColor, blue};
    }""")
    if selected:
        assert colors['background'] == colors['blue'], colors
        assert colors['color'] == 'rgb(255, 255, 255)', colors
    else:
        assert colors['background'] == 'rgb(255, 255, 255)', colors
        assert colors['color'] != colors['background'], colors


def select_route(page, name):
    page.locator(f'[data-route-select="{name}"]').click()
    expect(page.locator('#routeContinue')).to_be_enabled()
    assert_action_colors(page.locator(f'[data-route-select="{name}"]'))
    assert_action_colors(page.locator('#routeContinue'))


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
                state['detail']['image'] = 'https://merchant.example/selected-bib.svg'
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
                        value = {'brands': [{'code': 'decathlon_cn', 'name': 'Decathlon China', 'name_zh': '迪卡侬中国官网', 'official_url': 'https://www.decathlon.com.cn/', 'shop_url': 'https://www.decathlon.com.cn/', 'status': 'official_link_found', 'shop_evidence_url': 'https://www.decathlon.com.cn/', 'offer_count': 1, 'product_count': 1, 'rule_count': 0}], 'teams': [{'code': 'visma', 'name': 'Visma', 'name_zh': 'Visma', 'official_url': 'https://www.teamvismaleaseabike.com/', 'shop_url': 'https://www.teamvismaleaseabike.com/shop/', 'status': 'verified_shop', 'shop_evidence_url': 'https://www.teamvismaleaseabike.com/', 'offer_count': 1, 'product_count': 1, 'rule_count': 0}]}
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
                expect(page.locator('#variant')).to_be_visible()
                assert_no_early_registration(page)
                page.locator('[data-variant="S"]').click()
                assert_action_colors(page.locator('[data-variant="S"]'))
                assert_action_colors(page.locator('[data-offer="offer-maap"]'))
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
                assert_action_colors(page.locator('[data-route-select="hongkong"]'), selected=False)
                assert page.locator('[data-route-select="direct"]').evaluate('el => getComputedStyle(el).cursor') == 'not-allowed'
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
                assert_exit_closed(page)
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
                target = baseline['offers'][0]['offer']['url']
                selected_image = baseline['image']
                dialog = open_final_exit(page, target, official=True, image=selected_image)
                expect(dialog).to_contain_text(baseline['name_zh'])
                expect(dialog).to_contain_text('官方来源及商城入口依据')
                expect(page.locator('#externalExitImage')).to_be_visible()
                page.wait_for_function('document.getElementById("externalExitImage").naturalWidth > 0')
                expect(page.locator('#externalExitImageFallback')).to_be_hidden()
                assert outbound == [], 'Opening the confirmation must never leave BikeHunt'
                assert_exit_focus_trap(page)
                dialog.locator('details summary').click()
                expect(dialog.locator('details[open]')).to_have_count(1)
                assert_exit_layout(page)
                dialog.locator('details summary').click()
                page.screenshot(path=str(OUT / f'purchase_exit_{mode}.png'))
                # A failed selected-product image has a clear, usable text fallback.
                failed_image = selected_image + '?simulate-image-failure'
                page.route(failed_image, lambda route: route.abort())
                page.locator('#externalExitImage').evaluate('(img, src) => { img.src = src; }', failed_image)
                expect(page.locator('#externalExitImage')).to_be_hidden()
                expect(page.locator('#externalExitImageFallback')).to_be_visible()
                assert page.locator('#externalExitImageFallback').inner_text().strip()
                assert_exit_layout(page)
                page.screenshot(path=str(OUT / f'purchase_exit_image_fallback_{mode}.png'))
                cancel_exit_dialog(page)
                assert outbound == []
                assert_routes(page)
                expect(page.locator('#routeContinue')).to_be_focused()
                page.locator('#routeContinue').click()
                open_final_exit(page, target, official=True, image=selected_image)
                expect(page.locator('#externalExitImage')).to_be_visible()
                expect(page.locator('#externalExitImageFallback')).to_be_hidden()
                cancel_exit_dialog(page, escape=True)
                assert_routes(page)
                expect(page.locator('#routeContinue')).to_be_focused()
                expect(page.locator('[data-route-select="direct"]')).to_have_attribute('aria-pressed', 'true')
                # The exact quote is revalidated when Confirm is clicked, not
                # merely when the dialog opens. Restore fixture state afterward.
                for field, changed in [('stock', 'out_of_stock'), ('url', 'https://evil.example/changed-product')]:
                    page.locator('#routeContinue').click()
                    open_final_exit(page, target, official=True, image=selected_image)
                    original = page.evaluate('(field) => guideContext.quote.offer[field]', field)
                    page.evaluate('([field, value]) => { guideContext.quote.offer[field] = value; }', [field, changed])
                    page.locator('#externalExitConfirm').click()
                    expect(page).to_have_url(base)
                    expect(page.locator('#externalExitError')).to_be_visible()
                    assert outbound == [] and len(context.pages) == 1
                    page.evaluate('([field, value]) => { guideContext.quote.offer[field] = value; }', [field, original])
                    cancel_exit_dialog(page)
                    assert_routes(page)
                page.locator('#routeContinue').click()
                expect(page.locator('#registrationInterstitial')).to_be_visible()
                page.reload(wait_until='networkidle')
                expect(page.locator('#registrationInterstitial')).to_be_visible()
                expect(page.locator('#registrationInterstitial .registration-help')).to_have_count(1)
                open_final_exit(page, target, official=True, image=selected_image)
                confirm_exit_dialog(page, target, official=True)
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
                expect(page.locator('#amazonChannels,.amazon-market,[data-amazon-search-link]')).to_have_count(0)
                assert_no_early_registration(page)
                # Stale stock can only plan a route, then recheck at the exact official page.
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
                checks.append(mode + ': compact payment after size; exact three routes; prohibited disabled/unknown planning; registration only after route; four numbered modal explanations and exact domain/labels; selected image and failure fallback; full disclosure; Escape/focus trap; stock and URL revalidation; same-tab exact URL; cancel/back/reload preserve source, offer, size and route; no standalone Amazon search module; stale stock reference stage; no early merchant request')

                # Domestic official offers keep the same guarded exit and restore flow,
                # without showing cross-border route choices or imported-cost estimates.
                page.locator('#close').click()
                domestic_detail = copy.deepcopy(baseline)
                domestic_detail.update(variant_id='M')
                domestic_detail['identity']['size'] = 'M'
                domestic_detail['variants'] = [{'variant_id': 'M', 'size': 'M', 'in_stock': True,
                                               'stock_state': 'in_stock', 'source_count': 1,
                                               'product_cny_from': '399.90'}]
                domestic_quote = copy.deepcopy(baseline['offers'][0])
                domestic_target = 'https://www.decathlon.com.cn/p/test-domestic-jersey?size=M'
                domestic_quote['offer']['identity'] = copy.deepcopy(domestic_detail['identity'])
                domestic_quote['offer'].update(offer_id='offer-domestic-m', source_code='decathlon_cn',
                    source_name='迪卡侬中国官网', sales_region='中国大陆 CNY 报价',
                    url=domestic_target, price={'amount': '399.90', 'currency': 'CNY'},
                    original_price=None, stock='in_stock')
                domestic_quote.update(product_cny='399.90', shipping_cny=None, tax_cny=None, total_cny=None)
                domestic_quote.pop('landed_cost', None)
                domestic_detail['offers'] = [domestic_quote]
                state['detail'] = domestic_detail
                page.locator('.card .compare-button').first.click()
                page.locator('[data-variant="M"]').click()
                page.locator('[data-offer="offer-domestic-m"]').click()
                panel = page.locator('#routeComparison')
                expect(panel).to_be_visible()
                expect(panel.locator('[data-route]')).to_have_count(1)
                expect(panel.locator('[data-route="domestic"]')).to_have_attribute('data-route-status', 'conditional')
                expect(panel).to_contain_text('399.90')
                expect(panel).to_contain_text('尺码 M')
                expect(panel.locator('.route-hk-notes,.route-budget,.route-policy')).to_have_count(0)
                for absent in ['中国进口税', '清关', '海外转运', '香港']:
                    expect(panel).not_to_contain_text(absent)
                expect(page.locator('#routeContinue')).to_be_disabled()
                select_route(page, 'domestic')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('#routeContinue').click()
                expect(page.locator('#registrationInterstitial')).to_contain_text('登录或注册')
                expect(page.locator('#registrationInterstitial')).not_to_contain_text('Account / Sign in')
                page.locator('#registrationCancel').click()
                expect(page.locator('[data-route-select="domestic"]')).to_have_attribute('aria-pressed', 'true')
                page.locator('#routeContinue').click()
                open_final_exit(page, domestic_target, official=True, image=selected_image)
                page.evaluate("guideContext.quote.offer.sales_region = '其他市场'")
                page.locator('#externalExitConfirm').click()
                expect(page).to_have_url(base)
                expect(page.locator('#externalExitError')).to_be_visible()
                assert outbound == [target]
                page.evaluate("guideContext.quote.offer.sales_region = '中国大陆 CNY 报价'")
                cancel_exit_dialog(page)
                page.locator('#routeContinue').click()
                page.reload(wait_until='networkidle')
                expect(page.locator('#registrationInterstitial')).to_be_visible()
                assert page.evaluate('history.state.bikehuntPurchase.route') == 'domestic'
                open_final_exit(page, domestic_target, official=True, image=selected_image)
                confirm_exit_dialog(page, domestic_target, official=True)
                expect(page).to_have_url(domestic_target)
                assert outbound == [target, domestic_target] and len(context.pages) == 1
                page.go_back(wait_until='networkidle')
                expect(page.locator('[data-route-select="domestic"]')).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('#routeComparison')).to_contain_text('尺码 M')
                page.locator('#routeBack').click()
                expect(page.locator('[data-variant="M"]')).to_have_attribute('aria-pressed', 'true')
                checks.append(mode + ': exact domestic China CNY route; no import estimates; unknown shipping; M size and original URL; market mutation blocks exit; same-tab exit and restore')

                context.close()
            browser.close()
        assert errors == [], errors
        print(json.dumps({'passed': checks, 'page_errors': errors}, ensure_ascii=False, indent=2))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
