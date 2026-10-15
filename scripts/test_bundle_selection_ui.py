"""Hermetic bundle-selector and purchase-flow UI regression at three widths.

Uses actual cached Soudal variant/offer identities. The browser clock is fixed at
that snapshot's publication time; external requests are intercepted, including
the one intentional same-tab navigation to a mock merchant destination.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import threading
from datetime import datetime
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from playwright.sync_api import expect, sync_playwright
from test_catalog_messages_ui import DISCLAIMER, OUT, ROOT, QuietHandler, fixture

FIXTURE = ROOT / 'tests/fixtures/soudal-outfit-variants.json'
PARTS = ('jersey', 'bib', 'socks')
LABELS = {'jersey': 'Jersey', 'bib': 'Bib Short', 'socks': 'Socks'}
VIEWPORTS = [('desktop', {'width': 1440, 'height': 900}),
             ('mobile', {'width': 390, 'height': 844}),
             ('small_mobile', {'width': 320, 'height': 740})]


def parts(row):
    """Independent fixture oracle, deliberately not the production JS parser."""
    values = {}
    for component in row['size'].split(' / '):
        label, value = component.rsplit(': ', 1)
        key = next(key for key, name in LABELS.items() if label.startswith(name + ' '))
        assert key not in values
        values[key] = value
    assert set(values) == set(PARTS)
    return values


def synthetic_product(product_id, name, sizes, timestamp):
    """Unrecognized-combination and ordinary single-size compatibility fixtures."""
    seed = fixture()
    card = copy.deepcopy(seed['catalog']['items'][0])
    card.update(product_id=product_id, name=name, name_zh=name, available_sizes=sizes,
                variant_count=len(sizes), fetched_at=timestamp)
    rows = []
    for index, size in enumerate(sizes):
        variant_id = product_id + '-' + str(index)
        offer = copy.deepcopy(seed['detail']['offers'][0]['offer'])
        offer.update(offer_id='offer-' + variant_id, fetched_at=timestamp,
                     url='https://merchant.example/products/' + product_id + '?variant=' + variant_id,
                     identity={'brand': 'MAAP', 'size': size, 'color': '白色'})
        rows.append({'variant_id': variant_id, 'size': size, 'in_stock': True,
                     'stock_state': 'in_stock', 'source_count': 1,
                     'product_cny_from': '1080', 'offer': offer})
    card.update(reference_offer_id=rows[0]['offer']['offer_id'],
                reference_variant_id=rows[0]['variant_id'], reference_size=sizes[0])
    return {'product_id': product_id, 'name': name, 'image': card['image'], 'card': card, 'variants': rows}


def make_state():
    bundle = json.loads(FIXTURE.read_text())
    at = bundle['provenance']['snapshot_generated_at']
    when = datetime.fromisoformat(at.replace('Z', '+00:00'))
    assert len(bundle['variants']) == 60
    assert sum(row['in_stock'] for row in bundle['variants']) == 50
    for row in bundle['variants']:
        parts(row)
        assert row['size'] == row['offer']['identity']['size']
        age = (when - datetime.fromisoformat(row['offer']['fetched_at'].replace('Z', '+00:00'))).total_seconds()
        assert 0 <= age <= 3600, 'Fixture clock must preserve the captured stock verification'
    fallback = synthetic_product('unknown-bundle-format', 'Fallback unrecognized equipment bundle', [
        'Helmet collaboration edition (Size): M / Gloves winter team issue (Accessory size): 8 / Shoe covers racing edition (Size): L',
        'Helmet collaboration edition (Size): L / Gloves winter team issue (Accessory size): 9 / Shoe covers racing edition (Size): XL',
    ], at)
    single = synthetic_product('ordinary-single-size', 'Single ordinary cycling jersey', ['S', 'M'], at)
    fx = {'rate_date': at[:10], 'stale': False, 'rates': {'EUR': '7.4925', 'AUD': '4.8'}}
    products = {product['product_id']: product for product in [bundle, fallback, single]}
    return {'bundle': bundle, 'products': products, 'clock': when, 'fx': fx,
            'detail_requests': [], 'outbound': [], 'unexpected': [],
            'catalog': {'items': [product['card'] for product in products.values()],
                        'fx': fx, 'source_count': 2,
                        'categories': [{'code': 'all', 'name': '全部'},
                                       {'code': 'accessories', 'name': '配件'},
                                       {'code': 'bibs', 'name': '骑行裤'}]}}


def detail_for(state, product_id, variant_id=None):
    product = state['products'][product_id]
    rows = product['variants']
    # An unknown exact ID must fail. Returning the first offer would hide the bug.
    selected = next(row for row in rows if row['variant_id'] == variant_id) if variant_id else rows[0]
    offer = copy.deepcopy(selected['offer'])
    identity = copy.deepcopy(offer['identity'])
    identity['size'] = selected['size']
    return {'product_id': product_id, 'variant_id': selected['variant_id'],
            'name': product['name'], 'name_zh': product['name'],
            'category': product['card']['category'], 'image': product['image'],
            'identity': identity, 'variants': [{key: copy.deepcopy(value) for key, value in row.items()
                                             if key != 'offer'} for row in rows],
            'colors': [], 'fx': state['fx'], 'recommended_offer_id': None,
            'offers': [{'offer': offer, 'eligible': False, 'reasons': [],
                        'product_cny': selected['product_cny_from'],
                        'shipping_cny': None, 'tax_cny': None, 'total_cny': None}]}


def intercept_request(route, state, base):
    parsed = urlparse(route.request.url)
    if parsed.netloc != urlparse(base).netloc:
        if route.request.resource_type == 'image':
            return route.fulfill(content_type='image/svg+xml',
                                 body='<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"/>')
        assert route.request.method == 'GET', 'Regression must never submit a merchant form'
        state['outbound'].append(route.request.url)
        return route.fulfill(content_type='text/html',
                             body='<title>Mock official destination</title><p>Navigation fixture only.</p>')
    if not parsed.path.startswith('/api/'):
        return route.continue_()
    if parsed.path == '/api/catalog':
        value = state['catalog']
    elif parsed.path.startswith('/api/catalog/'):
        product_id = unquote(parsed.path.removeprefix('/api/catalog/'))
        variant_id = parse_qs(parsed.query).get('variant_id', [None])[0]
        state['detail_requests'].append((product_id, variant_id))
        try:
            value = detail_for(state, product_id, variant_id)
        except (KeyError, StopIteration):
            state['unexpected'].append((product_id, variant_id))
            return route.fulfill(status=404, content_type='application/json', body='{}')
    elif parsed.path == '/api/directories':
        value = {'brands': [], 'teams': [{'code': 'soudal', 'name': 'Soudal Quick-Step',
                  'name_zh': 'Soudal Quick-Step 车队', 'offer_count': 60, 'product_count': 1, 'rule_count': 0}]}
    elif parsed.path == '/api/updates':
        value = {'items': [], 'cursor': 0, 'fx': state['fx']}
    elif parsed.path.startswith('/api/rules/'):
        value = {'version': 1, 'documents': []}
    elif parsed.path.startswith('/api/fit/'):
        value = {'state': 'no_chart', 'note_zh': '测试数据', 'candidate_sizes': [],
                 'required_measurements': [], 'source_url': None, 'checked_at': None, 'chart_rows': []}
    elif parsed.path == '/api/community':
        value = {'schema_version': 1, 'available': False, 'configured': False}
    else:
        value = {}
    return route.fulfill(content_type='application/json', body=json.dumps(value))


def enabled_options(page, part):
    return page.locator('#bundle-' + part + ' option').evaluate_all(
        'options => options.filter(o => o.value && !o.disabled).map(o => o.value)')


def assert_no_purchase(page):
    expect(page.locator('.guide-start:enabled')).to_have_count(0)
    expect(page.locator('[data-purchase-link], [data-reference-link]')).to_have_count(0)
    expect(page.locator('#routeComparison, #registrationInterstitial, .registration-help')).to_have_count(0)


def assert_layout(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Document overflows the viewport'
    assert page.locator('#sheetBody').evaluate('el => el.scrollWidth <= el.clientWidth + 1'), 'Detail overflows'
    for control in page.locator('#bundleChoices select').all():
        assert control.evaluate('el => { const r=el.getBoundingClientRect(); return r.left>=0 && r.right<=innerWidth+1; }')


def assert_bundle_shell(page):
    expect(page.locator('#bundleChoices')).to_be_visible()
    # Wait for the sliding sheet to settle before checking viewport geometry.
    page.locator('#bundleChoices').scroll_into_view_if_needed()
    expect(page.locator('#bundleChoices select')).to_have_count(3)
    expect(page.locator('#variant, [data-variant]')).to_have_count(0)
    for key in PARTS:
        expect(page.locator('label[for="bundle-' + key + '"]')).to_contain_text(re.compile('[\u4e00-\u9fff]'))
        for label in page.locator('#bundle-' + key + ' option').all_text_contents():
            assert len(label) <= 32 and 'Quick-Step' not in label, label
    assert_layout(page)


def assert_selected(page, state, row):
    assert_bundle_shell(page)
    for key, value in parts(row).items():
        expect(page.locator('#bundle-' + key)).to_have_value(value)
        expect(page.locator('.bundle-selection-summary')).to_contain_text(value)
    expect(page.locator('.guide-start')).to_have_count(1)
    expect(page.locator('.guide-start')).to_have_attribute('data-offer', row['offer']['offer_id'])
    expect(page.locator('.guide-start')).to_be_enabled()
    assert state['detail_requests'][-1] == (state['bundle']['product_id'], row['variant_id'])
    assert page.evaluate('currentProduct.variant_id') == row['variant_id']
    assert page.evaluate('currentProduct.offers[0].offer.url') == row['offer']['url']
    assert page.evaluate('currentProduct.offers[0].offer.price') == row['offer']['price']
    formatted = page.evaluate("price => new Intl.NumberFormat('zh-CN', {style:'currency',currency:price.currency,maximumFractionDigits:2}).format(Number(price.amount))", row['offer']['price'])
    expect(page.locator('.offer .price')).to_contain_text(formatted)
    expect(page.locator('.offer .price')).to_contain_text('≈')


def select_combo(page, state, row):
    for key in PARTS:
        expect(page.locator('#bundle-' + key)).to_be_enabled()
        page.locator('#bundle-' + key).select_option(parts(row)[key])
    expect(page.locator('.guide-start')).to_have_attribute('data-offer', row['offer']['offer_id'])
    assert_selected(page, state, row)


def open_bundle(page, state, scoped=False):
    if scoped:
        page.locator('[data-tab="teams"]').click()
        page.locator('.directory-card[data-source="soudal"]').click()
        page.locator('#sourceProducts').click()
    page.locator('#q').fill('Cycling outfit')
    page.locator('.card[data-id="' + state['bundle']['product_id'] + '"] .compare-button').click()
    assert_bundle_shell(page)


def publish_change(page, row, **changes):
    event = {'offer_id': row['offer']['offer_id'], 'stock': row['offer']['stock'],
             'currency': row['offer']['price']['currency'], 'new_price': row['offer']['price']['amount'], **changes}
    page.evaluate("event => window.dispatchEvent(new CustomEvent('bikehunt-published', {detail:{events:[event],freshnessChanged:true}}))", event)


def assert_exact_history(page, state, row, stage):
    saved = page.evaluate('history.state')
    purchase = saved['bikehuntPurchase']
    assert purchase['productId'] == state['bundle']['product_id']
    assert purchase['variantId'] == row['variant_id']
    assert purchase['offerId'] == row['offer']['offer_id']
    assert purchase['sourceCode'] == row['offer']['source_code']
    assert purchase['url'] == row['offer']['url']
    assert purchase['route'] == 'direct' and purchase['stage'] == stage
    assert saved['bikehuntBrowse']['query'] == 'Cycling outfit'
    assert saved['bikehuntBrowse']['source'] == 'soudal'
    assert urlparse(page.url).query == '' and urlparse(page.url).fragment == ''


def exercise_real_bundle(page, context, state, mode):
    open_bundle(page, state, scoped=True)
    available = [row for row in state['bundle']['variants'] if row['in_stock']]
    row = next(row for row in available if parts(row) == {'jersey': 'S', 'bib': 'M', 'socks': 'S-M'})
    expect(page.locator('#bundle-jersey')).to_have_value('')
    expect(page.locator('#bundle-bib')).to_be_disabled()
    expect(page.locator('#bundle-socks')).to_be_disabled()
    assert set(enabled_options(page, 'jersey')) == {parts(item)['jersey'] for item in available}
    assert_no_purchase(page)
    requests_before = list(state['detail_requests'])
    page.locator('#bundle-jersey').select_option('S')
    expect(page.locator('#bundle-bib')).to_be_focused()
    expect(page.locator('#bundle-bib')).to_be_enabled()
    expect(page.locator('#bundle-socks')).to_be_disabled()
    assert set(enabled_options(page, 'bib')) == {parts(item)['bib'] for item in available if parts(item)['jersey'] == 'S'}
    assert '3XL' not in enabled_options(page, 'bib'), 'Sold-out bib size must not be offered'
    assert_no_purchase(page)
    page.locator('#bundle-bib').select_option('M')
    expect(page.locator('#bundle-socks')).to_be_focused()
    expect(page.locator('#bundle-socks')).to_be_enabled()
    assert set(enabled_options(page, 'socks')) == {parts(item)['socks'] for item in available if parts(item)['jersey'] == 'S' and parts(item)['bib'] == 'M'}
    assert_no_purchase(page)
    assert state['detail_requests'] == requests_before, 'Partial choices must not resolve an offer'
    page.screenshot(path=str(OUT / f'bundle_partial_{mode}.png'))
    page.locator('#bundle-socks').select_option('S-M')
    assert_selected(page, state, row)
    raw = page.locator('details.bundle-original').filter(has_text=row['size']).first
    expect(raw).to_have_count(1)
    assert raw.get_attribute('open') is None, 'Long merchant text should be collapsed initially'
    raw.locator('summary').click()
    expect(raw).to_contain_text(row['size'])
    assert_layout(page)
    raw.locator('summary').click()
    page.screenshot(path=str(OUT / f'bundle_selected_{mode}.png'))
    expect(page.locator('.registration-help')).to_have_count(0)
    page.locator('.guide-start').click()
    expect(page.locator('#routeComparison')).to_be_visible()
    expect(page.locator('[data-route-select]')).to_have_count(3)
    expect(page.locator('#routeContinue')).to_be_disabled()
    page.locator('[data-route-select="direct"]').click()
    expect(page.locator('#routeContinue')).to_be_enabled()
    expect(page.locator('#routeComparison')).to_contain_text('EUR 228.00')
    page.locator('#routeContinue').click()
    expect(page.locator('#registrationInterstitial')).to_be_visible()
    expect(page.locator('#registrationInterstitial .registration-help')).to_have_count(1)
    expect(page.locator('#registrationInterstitial')).to_contain_text(row['offer']['source_name'])
    expect(page.locator('#registrationInterstitial input, #registrationInterstitial form')).to_have_count(0)
    assert_exact_history(page, state, row, 'registration')
    assert state['outbound'] == [], 'Selection and registration must not contact a merchant'
    page.reload(wait_until='networkidle')
    expect(page.locator('#registrationInterstitial')).to_be_visible()
    assert_exact_history(page, state, row, 'registration')
    dialogs = []
    def accept(dialog):
        dialogs.append(dialog.message)
        assert DISCLAIMER in dialog.message
        dialog.accept()
    page.once('dialog', accept)
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#registrationContinue').click()
    expect(page).to_have_url(row['offer']['url'])
    assert len(dialogs) == 1 and state['outbound'] == [row['offer']['url']]
    assert len(context.pages) == 1, 'Merchant exit must remain in the same tab'
    page.go_back(wait_until='networkidle')
    expect(page.locator('#routeComparison')).to_be_visible()
    expect(page.locator('[data-route-select="direct"]')).to_have_attribute('aria-pressed', 'true')
    assert_exact_history(page, state, row, 'route')
    expect(page.locator('#q')).to_have_value('Cycling outfit')
    expect(page.locator('#browseLabel')).to_have_text('Soudal Quick-Step 车队')
    page.locator('#routeBack').click()
    assert_selected(page, state, row)
    page.screenshot(path=str(OUT / f'bundle_restored_{mode}.png'))
    return row


def exercise_sparse_and_refresh(page, state, row):
    page.locator('#close').click()
    all_rows = state['bundle']['variants']
    other = next(item for item in all_rows if item['in_stock'] and parts(item) == {'jersey': 'XL', 'bib': 'XL', 'socks': 'L-XL'})
    # Restrict the API to two genuine rows. The absent cross-product combinations
    # must never be presented as available or silently mapped to another offer.
    state['bundle']['variants'] = [row, other]
    open_bundle(page, state)
    page.locator('#bundle-jersey').select_option('S')
    assert enabled_options(page, 'bib') == ['M']
    page.locator('#bundle-bib').select_option('M')
    assert enabled_options(page, 'socks') == ['S-M']
    page.locator('#bundle-socks').select_option('S-M')
    assert_selected(page, state, row)
    page.locator('#bundle-jersey').select_option('XL')
    expect(page.locator('#bundle-bib')).to_have_value('')
    expect(page.locator('#bundle-socks')).to_have_value('')
    expect(page.locator('#bundle-socks')).to_be_disabled()
    assert enabled_options(page, 'bib') == ['XL']
    assert_no_purchase(page)
    page.locator('#bundle-bib').select_option('XL')
    assert enabled_options(page, 'socks') == ['L-XL']
    page.locator('#bundle-socks').select_option('L-XL')
    assert_selected(page, state, other)
    # A stock event while the exact bundle is open must use the bundle refresh
    # path, rather than relying on the ordinary #variant element existing.
    other['in_stock'] = False
    other['stock_state'] = other['offer']['stock'] = 'out_of_stock'
    with page.expect_response(lambda response: '/api/catalog/' in response.url and
                              parse_qs(urlparse(response.url).query).get('variant_id') == [other['variant_id']]):
        publish_change(page, other)
    expect(page.locator('.guide-start:enabled')).to_have_count(0)
    expect(page.locator('#registrationContinue')).to_have_count(0)
    expect(page.locator('#sheetBody')).to_contain_text('售罄')
    assert state['outbound'] == [row['offer']['url']]
    page.locator('#close').click()
    other['in_stock'] = True
    other['stock_state'] = other['offer']['stock'] = 'in_stock'
    state['bundle']['variants'] = all_rows
    open_bundle(page, state)
    select_combo(page, state, row)
    page.locator('.guide-start').click()
    expect(page.locator('#routeComparison')).to_be_visible()
    page.locator('[data-route-select="direct"]').click()
    page.locator('#routeContinue').click()
    expect(page.locator('#registrationInterstitial')).to_be_visible()
    publish_change(page, row, new_price='229.00')
    expect(page.locator('#registrationInterstitial')).to_have_count(0)
    expect(page.locator('#routeComparison')).to_be_visible()
    expect(page.locator('#routeContinue')).to_be_disabled()
    expect(page.locator('[data-route-select]:enabled')).to_have_count(0)
    for costs in page.locator('.route-cost-detail').all():
        expect(costs).not_to_contain_text('228.00')
    assert state['outbound'] == [row['offer']['url']]
    # The prior observation must survive reload even if the API still lags.
    page.reload(wait_until='networkidle')
    expect(page.locator('#routeContinue')).to_be_disabled()
    page.locator('#close').click()
    open_bundle(page, state)
    assert_no_purchase(page)
    # The fresh detail now agrees with the observed price change.
    row['offer']['price']['amount'] = '229.00'
    page.locator('#close').click()
    open_bundle(page, state)
    select_combo(page, state, row)
    page.locator('.guide-start').click()
    expect(page.locator('#routeComparison')).to_be_visible()
    page.locator('[data-route-select="direct"]').click()
    publish_change(page, row, stock='out_of_stock')
    expect(page.locator('#routeContinue')).to_be_disabled()
    expect(page.locator('[data-route-select]:enabled')).to_have_count(0)
    assert state['outbound'] == [row['offer']['url']]
    page.locator('#close').click()


def exercise_compatibility(page, state, mode):
    page.locator('[data-tab="products"]').click()
    page.locator('#q').fill('Fallback')
    page.locator('.card .compare-button').click()
    expect(page.locator('#bundleChoices')).to_have_count(0)
    expect(page.locator('#variant')).to_be_visible()
    fallback = state['products']['unknown-bundle-format']
    options = page.locator('#variant option').evaluate_all('rows => rows.filter(row => row.value).map(row => ({value:row.value,label:row.textContent}))')
    assert len(options) == 2
    assert len({option['label'] for option in options}) == 2, 'Fallback labels must remain distinguishable'
    for option in options:
        assert len(option['label']) <= 90, option
        assert 'Helmet collaboration edition' not in option['label'], 'Do not render merchant paragraphs as option labels'
    target = fallback['variants'][1]
    page.locator('#variant').select_option(target['variant_id'])
    expect(page.locator('.guide-start')).to_have_attribute('data-offer', target['offer']['offer_id'])
    raw = page.locator('details.variant-original').filter(has_text=target['size']).first
    expect(raw).to_have_count(1)
    if raw.get_attribute('open') is None:
        raw.locator('summary').click()
    expect(raw).to_contain_text(target['size'])
    assert_layout(page)
    page.screenshot(path=str(OUT / f'bundle_fallback_{mode}.png'))
    page.locator('#close').click()
    page.locator('#q').fill('Single ordinary')
    page.locator('.card .compare-button').click()
    expect(page.locator('#bundleChoices')).to_have_count(0)
    expect(page.locator('#variant')).to_be_visible()
    single = state['products']['ordinary-single-size']
    expect(page.locator('[data-variant]')).to_have_count(2)
    expect(page.locator('[data-variant]').first).to_have_text('S')
    target = single['variants'][1]
    page.locator('[data-variant="' + target['variant_id'] + '"]').click()
    expect(page.locator('#variant')).to_have_value(target['variant_id'])
    expect(page.locator('.guide-start')).to_have_attribute('data-offer', target['offer']['offer_id'])
    expect(page.locator('.guide-start')).to_be_enabled()
    assert_layout(page)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/web/'
    errors, checks = [], []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'), headless=True)
            for mode, viewport in VIEWPORTS:
                state = make_state()
                context = browser.new_context(viewport=viewport, is_mobile=mode != 'desktop', has_touch=mode != 'desktop')
                context.set_default_timeout(7000)
                context.add_init_script('window.BIKEHUNT_PAGES=true;')
                context.route('**/*', lambda route: intercept_request(route, state, base))
                page = context.new_page()
                page.clock.set_fixed_time(state['clock'])
                page.on('pageerror', lambda error: errors.append(str(error)))
                try:
                    page.goto(base, wait_until='networkidle')
                    row = exercise_real_bundle(page, context, state, mode)
                    exercise_sparse_and_refresh(page, state, row)
                    exercise_compatibility(page, state, mode)
                    assert state['unexpected'] == [], state['unexpected']
                    assert state['outbound'] == [row['offer']['url']], 'Only the deliberate mock merchant exit is allowed'
                    checks.append(mode + ': Chinese three-part selectors; exact genuine variant and EUR offer; partial/no purchase; sparse-combination reset; route/registration/same-tab exit; browser Back and reload restore source/query/parts/route; sold-out and price refresh invalidate; raw-text fallback; ordinary size compatibility; no horizontal overflow')
                finally:
                    context.close()
            browser.close()
        assert errors == [], errors
        print(json.dumps({'passed': checks, 'page_errors': errors}, ensure_ascii=False, indent=2))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
