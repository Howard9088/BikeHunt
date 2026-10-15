"""Hermetic EF cost-estimate regression: local pages, no merchant visits or purchase."""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
# Direct script execution puts scripts/, rather than the repository, on sys.path.
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright

from app.catalog.models import Evidence, FxSnapshot, Money, Offer, ProductIdentity
from app.catalog.service import ComparisonCatalog
from app.localization import CATEGORIES
from app.landed import load_rules
OUTPUT = ROOT / 'artifacts' / 'cost-preview'


def fixture():
    now = datetime.now(timezone.utc)
    fx = FxSnapshot(snapshot_id='cost-preview-fixture', rates={'USD': Decimal('6.6927'), 'CNY': Decimal(1)},
                    rate_date=now.date().isoformat(), fetched_at=now)
    offer = Offer(offer_id='ef-stamp-m', source_code='ef_team_shop', source_name='EF 车队官方商城美国站',
                  identity=ProductIdentity(brand='EF Pro Cycling', model='Stamp Hoodie', size='M', color='Black'),
                  name='Stamp Hoodie', url='https://merchant.example/stamp-hoodie/',
                  image='https://merchant.example/hoodie.svg', price=Money(amount='89', currency='USD'),
                  fetched_at=now, stock='in_stock', shipping_to_china=Evidence(), china_issued_card=Evidence())
    # This UI fixture intentionally assumes freshly reviewed rules. Change only
    # a deep copy: never extend production policy validity or mutate its cache.
    fixture_rules = deepcopy(load_rules())
    fixture_rules['checked_on'] = now.date().isoformat()
    with patch('app.landed.load_rules', return_value=fixture_rules):
        store = ComparisonCatalog([offer], fx, now)
        cards = store.search()
        detail = store.compare(cards[0].product_id)
    return {'catalog': {'items': [x.model_dump(mode='json') for x in cards], 'fx': fx.model_dump(mode='json'),
                        'source_count': 1, 'categories': CATEGORIES},
            'detail': detail.model_dump(mode='json')}


def exercise_shipping_budget(page, estimate, screenshot):
    """Exercise the same delegated DOM handler in detail and Step 3."""
    field = estimate.locator('[data-shipping-budget]')
    preview = estimate.locator('[data-budget-result]')
    error = estimate.locator('[data-budget-error]')
    quote_before = page.evaluate('JSON.stringify(currentProduct.offers[0])')
    storage_before = page.evaluate('JSON.stringify(Object.entries(localStorage).sort())')
    expect(field).to_have_value('')
    expect(preview).to_be_hidden()
    expect(error).to_be_hidden()
    field.fill('120.50')
    expect(preview).to_be_visible()
    expect(estimate.locator('[data-budget-shipping]')).to_contain_text('120.50')
    expect(estimate.locator('[data-budget-subtotal]')).to_contain_text('835.28')
    expect(preview).to_contain_text('不是商家报价，也不是完整到手价')
    expect(preview).to_contain_text('未知清关／代垫手续费仍需另计')
    expect(estimate).to_contain_text('中国大陆配送仍待核实')
    expect(estimate.locator('dl.costs').first.locator('div').filter(has_text='寄中国运费').locator('dd')).to_have_text('待确认')
    expect(estimate.locator('dl.costs').first.locator('.total dd')).to_contain_text('714.78')
    assert page.locator('#sheetBody').evaluate('el=>el.scrollWidth <= el.clientWidth')
    estimate.locator('[data-shipping-budget-box]').screenshot(path=str(screenshot))
    for value in ['-1', 'NaN', 'Infinity', '100000.01', '1000000', '1e309', '0.001']:
        field.fill(value)
        expect(field).to_have_attribute('aria-invalid', 'true')
        expect(error).to_be_visible()
        expect(preview).to_be_hidden()
        expect(estimate.locator('[data-budget-subtotal]')).to_have_text('')
    field.fill('0')
    expect(field).to_have_attribute('aria-invalid', 'false')
    expect(estimate.locator('[data-budget-subtotal]')).to_contain_text('714.78')
    expect(estimate.locator('[data-budget-zero]')).to_be_visible()
    expect(preview).to_contain_text('不代表商家免邮')
    field.fill('120.50')
    expect(estimate.locator('[data-budget-subtotal]')).to_contain_text('835.28')
    field.fill('')
    expect(field).to_have_value('')
    expect(field).to_have_attribute('aria-invalid', 'false')
    expect(error).to_be_hidden()
    expect(preview).to_be_hidden()
    expect(estimate.locator('[data-budget-subtotal]')).to_have_text('')
    assert page.evaluate('JSON.stringify(currentProduct.offers[0])') == quote_before
    assert page.evaluate('JSON.stringify(Object.entries(localStorage).sort())') == storage_before
    assert page.evaluate('currentProduct.offers[0].eligible') is False
    assert page.evaluate('currentProduct.offers[0].landed_cost.complete') is False
    assert page.evaluate('currentProduct.offers[0].total_cny') is None


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    checks, errors = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'), headless=True)
            for mode, viewport in [('desktop', {'width': 1440, 'height': 1000}), ('mobile', {'width': 390, 'height': 844}), ('small_mobile', {'width': 375, 'height': 667})]:
                state = fixture()
                context = browser.new_context(viewport=viewport, is_mobile=mode != 'desktop', has_touch=mode != 'desktop')
                context.add_init_script('window.BIKEHUNT_PAGES=true;')
                def intercept(route):
                    url = urlparse(route.request.url)
                    if url.netloc == 'merchant.example':
                        if url.path.endswith('.svg'):
                            return route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="500" height="500"><rect width="500" height="500" fill="#f1f2f4"/><text x="40" y="250" font-size="28">EF Hoodie UI fixture</text></svg>')
                        raise AssertionError('Test must not visit a merchant')
                    if not url.path.startswith('/api/'):
                        return route.continue_()
                    if url.path == '/api/catalog': result = state['catalog']
                    elif url.path.startswith('/api/catalog/'): result = state['detail']
                    elif url.path == '/api/directories': result = {'brands': [], 'teams': []}
                    elif url.path.startswith('/api/rules/'): result = {'version': 1, 'documents': []}
                    elif url.path.startswith('/api/fit/'): result = {'state': 'no_chart', 'note_zh': '测试数据', 'candidate_sizes': [], 'required_measurements': [], 'source_url': None, 'checked_at': None, 'chart_rows': []}
                    else: result = {}
                    route.fulfill(content_type='application/json', body=json.dumps(result))
                context.route('**/*', intercept)
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/web/', wait_until='networkidle')
                page.locator('.card .compare-button').click()
                page.locator('[data-variant]').first.click()
                estimate = page.locator('.cost-estimate')
                for text in ['595.65', '119.13', '714.78', '中国大陆配送仍待核实', '不能视为完整到手价', '待确认']:
                    expect(estimate).to_contain_text(text)
                expect(page.locator('.tag').filter(has_text='推荐渠道')).to_have_count(0)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                estimate.scroll_into_view_if_needed()
                estimate.screenshot(path=str(OUTPUT / f'cost_{mode}_detail.png'))
                exercise_shipping_budget(page, estimate, OUTPUT / f'cost_{mode}_detail_budget.png')
                page.locator('.guide-start').click()
                page.locator('#guideNext').click()
                expect(page.locator('.guide-conclusion')).to_contain_text('尚需核实')
                page.locator('#guideNext').click()
                expect(page.locator('.guide-progress')).to_contain_text('第 3 步')
                for text in ['595.65', '119.13', '714.78', '商品 + 预估税小计', '中国大陆配送仍待核实', '不能视为完整到手价']:
                    expect(page.locator('.guide-content')).to_contain_text(text)
                expect(page.locator('.guide-content')).not_to_contain_text('预计总成本')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert page.locator('#sheetBody').evaluate('el=>el.scrollWidth <= el.clientWidth')
                page.locator('#sheetBody').evaluate('el=>el.scrollTop=0')
                page.locator('#sheet').evaluate('el=>Promise.all(el.getAnimations().map(a=>a.finished.catch(()=>{})))')
                page.screenshot(path=str(OUTPUT / f'cost_{mode}_guide.png'))
                page.locator('.cost-estimate').screenshot(path=str(OUTPUT / f'cost_{mode}_estimate.png'))
                exercise_shipping_budget(page, page.locator('.cost-estimate'), OUTPUT / f'cost_{mode}_guide_budget.png')
                checks.append(f'{mode}: detail and Step 3 show conditional ¥119.13 tax and ¥714.78 incomplete subtotal; blank → ¥120.50 user budget → clear, explicit zero and invalid inputs verified; quote/evidence/storage unchanged, no recommendation or horizontal overflow')
                context.close()
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        (OUTPUT / 'results.json').write_text(json.dumps({'checks': checks, 'errors': errors}, ensure_ascii=False, indent=2))
    assert not errors, errors
    print(json.dumps({'ok': True, 'checks': checks}, ensure_ascii=False))


if __name__ == '__main__':
    main()
