"""Hermetic accessory detail/exit and four public groups with stale-payload rejection; run Chromium only in CI."""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from playwright.sync_api import expect, sync_playwright
from app.browse_taxonomy import CATEGORY_GROUPS
from app.road_equipment import BROWSE_CATEGORIES, read_road_references
from test_featured_deals_ui import fixture as base_fixture, QuietHandler

OUT = ROOT / 'artifacts/browse-groups'
MIDLOADER = 'canyon-9102039'


def fixture():
    state = base_fixture()
    references = read_road_references(ROOT)
    state['catalog']['category_groups'] = CATEGORY_GROUPS
    state['catalog']['categories'] = BROWSE_CATEGORIES
    state['catalog']['road_equipment_references'] = references
    # Deliberately serve pre-release payloads. New client code must project them safely.
    sample = state['catalog']['items'][0]
    for row in references['products']:
        if row['category_group'] == 'road_equipment':
            state['catalog']['items'].append({**sample, 'product_id': 'stale-' + row['id'],
                'name': row['name'], 'name_zh': row['name'], 'brand': row['brand'],
                'category': row['category'], 'category_group': row['category_group'],
                'source_codes': [row['source_code']]})
    state['directories']['brands'] += [
        dict(code=b['code'], name=b['name'], name_zh=b['name'],
             offer_count=0, product_count=0, rule_count=0, road_reference=True,
             reference_note=b['note'], official_url=b['url'], shop_url=b['url'])
        for b in references['brands']
    ]
    return state


def inline_cards(page, count):
    """Sheet references deliberately duplicate records; only count gallery cards."""
    inline = page.locator('#grid #roadReferenceInline')
    expect(inline).to_be_visible()
    expect(inline.locator('.road-reference-card[data-road-reference-card]')).to_have_count(count)
    expect(inline.locator('.card')).to_have_count(0)
    expect(page.locator('#grid .card')).to_have_count(0)
    expect(page.locator('#count')).to_have_text('0 件商品')
    return inline


def product_opener(page, identifier=MIDLOADER, owner='#roadReferenceInline'):
    return page.locator(f'{owner} button[data-road-open="{identifier}"]')


def product_link(page, identifier=MIDLOADER):
    return page.locator(f'#roadReferenceDetail a[data-road-reference="product:{identifier}"]')


def open_reference(page, identifier=MIDLOADER, owner='#roadReferenceInline'):
    opener = product_opener(page, identifier, owner)
    expect(opener).to_have_count(1)
    opener.click()
    detail = page.locator('#sheetBody #roadReferenceDetail')
    expect(detail).to_be_visible()
    expect(page.locator('#externalExitDialog')).not_to_be_visible()
    expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'false')
    return detail


def back_to_references(page, identifier=MIDLOADER, owner='#roadReferenceInline', focus=True):
    page.locator('#roadReferenceBack').click()
    # Closed sheets are translated offscreen, not display:none.
    expect(page.locator('#sheet.open #roadReferenceDetail')).to_have_count(0)
    if owner == '#roadReferenceInline':
        expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
    else:
        expect(page.locator(owner)).to_be_visible()
    if focus:
        expect(product_opener(page, identifier, owner)).to_be_focused()


def assert_reference_detail(page, row, state, owner='#roadReferenceInline'):
    """The retained accessory keeps its honest, read-only in-site workflow."""
    card = page.locator(f'{owner} [data-road-reference-card="{row["id"]}"]')
    expect(card.locator('a[data-road-reference^="product:"]')).to_have_count(0)
    expect(card.locator('[data-road-open]')).to_have_count(1)
    if row.get('image'):
        expect(card.locator('img[data-reference-image]')).to_have_attribute('src', row['image'])
    else:
        expect(card.locator('img[data-reference-image]')).to_have_count(0)
        expect(card.locator('.reference-image-fallback')).to_be_visible()
    detail = open_reference(page, row['id'], owner)
    for text in [row['name'], '库存待核实', '未取得折扣结束时间']:
        expect(detail).to_contain_text(text)
    expect(detail.locator('.road-item-only')).to_contain_text('商品价')
    expect(detail.locator('.road-item-only')).to_contain_text('不是到手总价')
    for amount in [row['price'], row['reference_price']]:
        # Use the actual locale formatter, checking source and CNY amounts separately.
        for currency, value in [(row['currency'], amount), ('CNY', amount * 7)]:
            formatted = page.evaluate('({value, currency}) => money(value, currency)',
                                      {'value': value, 'currency': currency})
            expect(detail.locator('.road-price')).to_contain_text(formatted)
    expect(detail.locator('.road-reference-fx')).to_contain_text(state['catalog']['fx']['rate_date'])
    expect(detail.locator('.road-reference-fx')).to_contain_text('每日参考')
    options = detail.locator('#roadReferenceOptions')
    for option in row['listed_options']:
        expect(options).to_contain_text(option)
    expect(options.locator('button,input,select,a,[role=radio],[role=option],[role=button]')).to_have_count(0)
    expect(detail.locator('select,[data-purchase-link],[data-route-select],#variant,#bundleChoices,.costs')).to_have_count(0)
    assert page.evaluate('currentProduct === null'), 'Reference detail must not manufacture an Offer/product'
    steps = detail.locator('#roadPurchaseSteps')
    expect(steps).to_be_visible()
    assert steps.locator('li').count() >= 4
    for text in ['市场', '尺码', '运费', '税费', '支付', '账户']:
        expect(steps).to_contain_text(text)
    brand = next(b for b in state['catalog']['road_equipment_references']['brands'] if b['code'] == row['source_code'])
    expect(detail).to_contain_text('配件研究参考')
    expect(detail).to_contain_text(row['notes'])
    expect(steps).to_contain_text('不套用服装税率')
    expect(detail.locator('#roadReferenceRegistration')).to_be_visible()
    expect(detail.locator('#roadReferenceRegistration')).to_contain_text('是否提供待核实')
    expect(detail.locator('[data-payment-directory]')).to_have_count(1)
    expect(product_link(page, row['id'])).to_have_attribute('href', row['url'])
    expect(product_link(page, row['id'])).to_have_attribute('target', '_self')
    if row.get('image'):
        image = detail.locator('img[data-reference-image]')
        expect(image).to_have_attribute('src', row['image'])
        image.evaluate("img => img.dispatchEvent(new Event('error'))")
        expect(image).to_be_hidden()
        expect(detail.locator('.reference-image-fallback')).to_be_visible()
    else:
        expect(detail.locator('img[data-reference-image]')).to_have_count(0)
        expect(detail.locator('.reference-image-fallback')).to_contain_text('图片待核实')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    back_to_references(page, row['id'], owner)


def check_fx_states(page, state):
    original = page.evaluate('JSON.parse(JSON.stringify(fx))')
    page.evaluate("fx = {...fx, rate_date: '2000-01-01', stale: true}; render()")
    expect(page.locator('#roadReferenceInline .road-reference-fx')).to_contain_text('过期缓存')
    original_opener = product_opener(page).element_handle()
    detail = open_reference(page)
    expect(detail.locator('.road-reference-fx')).to_contain_text('2000-01-01')
    expect(detail.locator('.road-reference-fx')).to_contain_text('过期缓存')
    expect(detail.locator('.road-price')).to_contain_text(page.evaluate('money(55.95 * 7)'))
    # Published FX updates refresh an already-open detail without replacing its exit.
    exit_handle = product_link(page).element_handle()
    page.evaluate('(original) => { fx = original; refreshRoadReferenceDetail(); }', original)
    expect(detail.locator('.road-reference-fx')).to_contain_text(original['rate_date'])
    expect(detail.locator('.road-reference-fx')).to_contain_text('每日参考')
    for missing in [{}, {'rate_date': state['catalog']['fx']['rate_date'], 'rates': {'CNY': 1}}]:
        page.evaluate('(missing) => { fx = missing; refreshRoadReferenceDetail(); }', missing)
        expect(detail.locator('.road-reference-fx')).to_contain_text('汇率待获取')
        expect(detail.locator('.road-price')).to_contain_text('待换算')
        expect(detail.locator('.road-price')).not_to_contain_text(page.evaluate('money(55.95 * 7)'))
        expect(detail.locator('.road-price')).not_to_contain_text('NaN')
        expect(detail.locator('.road-price')).not_to_contain_text('Infinity')
    assert page.evaluate('(link) => link.isConnected', exit_handle)
    # A catalog render replaces the list underneath an open detail. Back still
    # resolves the current card instead of trying to focus the detached opener.
    page.evaluate('render(); refreshRoadReferenceDetail()')
    assert page.evaluate('(opener) => !opener.isConnected', original_opener)
    expect(detail).to_be_visible()
    back_to_references(page)
    page.evaluate('(original) => { fx = original; render(); }', original)


def check_language_help(page):
    detail = open_reference(page)
    expected_url = product_link(page).get_attribute('href')
    detail.locator('#roadReferenceLanguage').click()
    expect(page.locator('#merchantLanguageGuide')).to_be_visible()
    expect(page.locator('#merchantGuideTitle')).to_be_focused()
    expect(page.locator('#merchantLanguageGuide')).to_contain_text('未实测注册或结账成功')
    expect(page.locator('#merchantLanguageGuide input, #merchantLanguageGuide form')).to_have_count(0)
    page.locator('#merchantGuideBack').click()
    expect(page.locator('#roadReferenceDetail')).to_be_visible()
    expect(page.locator('#roadReferenceLanguage')).to_be_focused()
    expect(product_link(page)).to_have_attribute('href', expected_url)
    back_to_references(page)


def check_gender_scope(page):
    expect(page.locator('#genderFilter')).to_be_hidden()
    page.locator('[data-category-group=clothing]').click()
    expect(page.locator('#genderFilter')).to_be_visible()
    page.locator('#genderFilter [data-gender=female]').click()
    assert page.evaluate("shopperProfile.gender === 'female'")
    # Existing body measurements survive clearing only the out-of-scope gender filter.
    page.evaluate('shopperProfile.height_cm = 175; shopperProfile.weight_kg = 65; saveProfile()')
    for group in ['cleat_shoes', 'helmets', 'other']:
        page.locator(f'[data-category-group={group}]').click()
        expect(page.locator('#genderFilter')).to_be_hidden()
        assert page.evaluate("shopperProfile.gender === 'all'")
        assert page.evaluate("JSON.parse(localStorage.getItem(PROFILE_KEY)).gender === 'all'")
        assert page.evaluate('shopperProfile.height_cm === 175 && shopperProfile.weight_kg === 65')
        # A stale listener or programmatic hidden click must not revive an invisible filter.
        page.locator('#genderFilter [data-gender=female]').evaluate('button => button.click()')
        assert page.evaluate("shopperProfile.gender === 'all'")
        assert page.evaluate("(group) => profileMatches({category_group: group, gender: 'male'})", group)
    page.locator('[data-category-group=clothing]').click()
    expect(page.locator('#genderFilter [data-gender=all]')).to_have_attribute('aria-pressed', 'true')
    page.locator('#genderFilter [data-gender=female]').click()
    page.locator('[data-tab=brands]').click()
    expect(page.locator('#genderFilter')).to_be_hidden()
    assert page.evaluate("shopperProfile.gender === 'all'")
    page.locator('[data-tab=products]').click()
    expect(page.locator('#genderFilter')).to_be_hidden()
    # Restore an old persisted female preference on a non-clothing reload.
    page.evaluate("localStorage.setItem(PROFILE_KEY, JSON.stringify({...shopperProfile, gender: 'female'}))")
    page.reload(wait_until='networkidle')
    expect(page.locator('#genderFilter')).to_be_hidden()
    assert page.evaluate("shopperProfile.gender === 'all'")
    expect(page.locator('#grid .card')).to_have_count(2)


def check_hidden_bicycle_paths(page, references):
    hidden = [row for row in references if row['category_group'] == 'road_equipment']
    assert page.evaluate("categoryGroups.map(row => row.code)") == ['clothing', 'cleat_shoes', 'helmets', 'other']
    assert page.evaluate("roadReferenceData.products.map(row => row.id)") == [MIDLOADER]
    assert page.evaluate("items.every(row => row.category_group !== 'road_equipment' && !['road_bikes','frames'].includes(row.category))")
    for row in hidden:
        page.evaluate('(id) => openRoadReferenceDetail(id)', row['id'])
        page.evaluate('(id) => openProduct(id)', 'stale-' + row['id'])
        expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
        expect(page.locator('#externalExitDialog')).not_to_be_visible()
    for source in ['trek', 'specialized', 'colnago']:
        page.evaluate("""source => {
            history.replaceState({...history.state, bikehuntBrowse: {
                tab: 'products', source, categoryGroup: 'road_equipment', category: 'frames', query: 'Allez'
            }}, '');
        }""", source)
        page.reload(wait_until='networkidle')
        assert page.evaluate("activeCategoryGroup === null && activeCategory === 'all' && activeSource === null")
        expect(page.locator('#q')).to_have_value('Allez')
        expect(page.locator('#grid .card,#grid [data-road-reference-card]')).to_have_count(0)
        expect(page.locator('[data-category-group=road_equipment]')).to_have_count(0)
    page.locator('[data-tab=products]').click()
    expect(page.locator('#grid .card')).to_have_count(2)


def assert_inline_layout(page, viewport):
    inline = inline_cards(page, 1)
    gallery = page.locator('#grid')
    gallery.evaluate('(element) => { element.scrollTop = 0; }')
    first = inline.locator('[data-road-reference-card]').first
    first_box = first.bounding_box()
    price_box = first.locator('.road-price').bounding_box()
    gallery_box = gallery.bounding_box()
    assert first_box and price_box and gallery_box
    visible_bottom = min(viewport['height'], gallery_box['y'] + gallery_box['height'])
    assert gallery_box['y'] <= first_box['y'] < visible_bottom, (viewport, first_box, gallery_box)
    assert gallery_box['y'] <= price_box['y'] and price_box['y'] + price_box['height'] <= visible_bottom, (viewport, price_box, gallery_box)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert gallery.evaluate('(element) => element.scrollWidth <= element.clientWidth')
    assert gallery.evaluate("(element) => getComputedStyle(element).touchAction.split(' ').includes('pan-y')")
    assert gallery.evaluate("(element) => ['auto', 'scroll'].includes(getComputedStyle(element).overflowY)")
    # Product feed wheel/swipe interception must not own the reference gallery.
    assert gallery.evaluate("""(element) => {
        const event = new WheelEvent('wheel', {deltaY: 180, bubbles: true, cancelable: true});
        element.dispatchEvent(event);
        return !event.defaultPrevented;
    }""")
    # One accessory may fit on desktop; exercise native scrolling where it overflows.
    if gallery.evaluate('(element) => element.scrollHeight > element.clientHeight'):
        page.mouse.move(gallery_box['x'] + gallery_box['width'] / 2,
                        gallery_box['y'] + min(gallery_box['height'] / 2, 100))
        page.mouse.wheel(0, 240)
        page.wait_for_function("document.getElementById('grid').scrollTop > 0")
    assert page.evaluate('window.scrollY === 0')
    gallery.evaluate('(element) => { element.scrollTop = 0; }')

    # The brand directory is a separate, collapsed section after product records.
    directory = inline.locator('details').filter(has=page.locator('.road-brand-grid'))
    expect(directory).to_have_count(1)
    assert directory.get_attribute('open') is None
    assert inline.evaluate("""(element) => {
        const directory = element.querySelector('.road-brand-grid')?.closest('details');
        return !!directory && [...element.querySelectorAll('[data-road-reference-card]')]
            .every(card => !!(card.compareDocumentPosition(directory) & Node.DOCUMENT_POSITION_FOLLOWING));
    }""")


def assert_disabled_exit(page, base):
    page.locator('#externalExitConfirm').click()
    expect(page.locator('#externalExitConfirm')).to_be_disabled()
    expect(page.locator('#externalExitError')).to_be_visible()
    expect(page).to_have_url(base)
    assert len(page.context.pages) == 1
    page.locator('#externalExitCancel').click()
    expect(page.locator('#externalExitDialog')).not_to_be_visible()


def check_exit_mutations(page, base, expected_url):
    # Stock changes while reading invalidate the exact final gate.
    open_reference(page)
    product_link(page).click()
    page.evaluate("""(id) => {
        roadReferenceData.products.find(row => row.id === id).stock = 'out_of_stock';
    }""", MIDLOADER)
    assert_disabled_exit(page, base)
    back_to_references(page, focus=False)
    page.evaluate('render()')
    sold = inline_cards(page, 1).locator(f'[data-road-reference-card="{MIDLOADER}"]')
    expect(sold).to_contain_text('已确认售罄')
    expect(sold.locator('a')).to_have_count(0)
    page.evaluate("""(id) => {
        roadReferenceData.products.find(row => row.id === id).stock = 'unknown';
        render();
    }""", MIDLOADER)

    # Changing only the DOM destination cannot reuse the original confirmation.
    open_reference(page)
    product_link(page).click()
    product_link(page).evaluate("link => link.setAttribute('href', link.href + '?changed=1')")
    assert_disabled_exit(page, base)
    back_to_references(page)

    # A new same-host record URL is still a different exact destination.
    open_reference(page)
    product_link(page).click()
    page.evaluate("""(id) => {
        roadReferenceData.products.find(row => row.id === id).url += '?changed=1';
    }""", MIDLOADER)
    assert_disabled_exit(page, base)
    page.evaluate("""({id, url}) => {
        roadReferenceData.products.find(row => row.id === id).url = url;
    }""", {'id': MIDLOADER, 'url': expected_url})
    back_to_references(page)

    # Replacing an identical final anchor detaches its exact trigger.
    open_reference(page)
    product_link(page).click()
    product_link(page).evaluate('link => link.replaceWith(link.cloneNode(true))')
    assert_disabled_exit(page, base)
    back_to_references(page)

    # Filters changing during the final gate must revalidate current browse scope.
    for mutate, restore in [
        ("document.getElementById('q').value = 'different product'", "document.getElementById('q').value = 'Midloader'"),
        ("activeCategoryGroup = 'road_equipment'", "activeCategoryGroup = 'other'"),
        ("activeSource = 'specialized'", "activeSource = 'canyon'"),
        ("activeTab = 'brands'", "activeTab = 'products'"),
    ]:
        open_reference(page)
        product_link(page).click()
        page.evaluate(mutate)
        assert_disabled_exit(page, base)
        page.evaluate(restore)
        back_to_references(page)

    open_reference(page)
    expect(product_link(page)).to_have_attribute('href', expected_url)
    product_link(page).click()
    expect(page.locator('#externalExitConfirm')).to_be_enabled()
    page.locator('#externalExitCancel').click()
    expect(product_link(page)).to_be_focused()
    back_to_references(page)


def check_browse_state(page):
    expect(page.locator('#q')).to_have_value('Midloader')
    expect(page.locator('[data-category-group=other]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('[data-category]')).to_have_count(0)
    assert page.evaluate("activeCategory === 'all'")
    expect(page.locator('#browseLabel')).to_contain_text('Canyon')
    inline_cards(page, 1)
    assert page.evaluate("activeSource === 'canyon' && activeTab === 'products'")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/web/'
    errors, checks, unexpected, product_api_requests = [], [], [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'), headless=True)
            for mode, viewport in [
                ('desktop', {'width': 1440, 'height': 900}),
                ('mobile', {'width': 390, 'height': 844}),
                ('small_mobile', {'width': 320, 'height': 667}),
            ]:
                state = fixture()
                references = state['catalog']['road_equipment_references']['products']
                expected_urls = {row['url'] for row in references}
                image_urls = {row['image'] for row in references if row.get('image')}
                for card in state['catalog']['items']:
                    card['image'] = base + 'icons/icon-512.png'
                context = browser.new_context(viewport=viewport, is_mobile=mode != 'desktop', has_touch=mode != 'desktop')
                context.set_default_timeout(7000)
                context.add_init_script('window.BIKEHUNT_PAGES=true;')

                def intercept(route):
                    url = urlparse(route.request.url)
                    if route.request.url in image_urls:
                        return route.fulfill(content_type='image/png', body=(ROOT / 'web/icons/icon-512.png').read_bytes())
                    if route.request.url in expected_urls:
                        return route.fulfill(content_type='text/html', body='<h1>Mock official reference page</h1>')
                    if url.netloc != urlparse(base).netloc:
                        unexpected.append(route.request.url)
                        return route.abort()
                    if not url.path.startswith('/api/'):
                        return route.continue_()
                    if url.path.startswith(('/api/catalog/', '/api/fit/')):
                        product_api_requests.append(route.request.url)
                        return route.abort()
                    if url.path == '/api/catalog':
                        result = state['catalog']
                    elif url.path == '/api/directories':
                        result = state['directories']
                    elif url.path.startswith('/api/rules/'):
                        result = {'version': 1, 'documents': []}
                    elif url.path == '/api/updates':
                        result = {'items': [], 'cursor': 0, 'fx': state['catalog']['fx']}
                    else:
                        result = {}
                    route.fulfill(content_type='application/json', body=json.dumps(result))

                context.route('**/*', intercept)
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base, wait_until='networkidle')
                expect(page.locator('[data-category-group]')).to_have_count(4)
                assert page.locator('[data-category-group]').all_text_contents() == ['骑行服饰', '锁鞋', '头盔', '配件与周边']
                expect(page.locator('#categoryNav')).to_have_count(0)
                expect(page.locator('[data-category]')).to_have_count(0)
                expect(page.locator('#grid .card')).to_have_count(2)
                expect(page.locator('#roadReferenceInline')).to_have_count(0)
                check_hidden_bicycle_paths(page, references)
                check_gender_scope(page)
                page.locator('[data-category-group=other]').click()
                expect(page.locator('#grid .card')).to_have_count(0)
                expect(page.locator('#grid')).not_to_contain_text('Stamp Hoodie')
                # Hoodies belong to clothing; browse research in its merchant scope.
                page.locator('[data-tab=brands]').click()
                page.locator('[data-source=canyon]').click()
                page.locator('#sourceProducts').click()
                expect(page.locator('[data-category-group=other]')).to_have_attribute('aria-pressed', 'true')
                inline = inline_cards(page, 1)
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                expect(inline).to_contain_text('Canyon Midloader')
                expect(inline).to_contain_text('库存待核实')
                accessory = next(row for row in references if row['id'] == MIDLOADER)
                assert_reference_detail(page, accessory, state)
                assert_inline_layout(page, viewport)
                page.screenshot(path=str(OUT / f'references_{mode}.png'))

                # The accessory panel and inline list cannot leak hidden bicycle entrances.
                expect(page.locator('#roadReferenceStrip')).to_be_visible()
                page.locator('#roadReferencesButton').click()
                panel = page.locator('#roadReferencePanel')
                expect(panel).to_be_visible()
                expect(panel.locator('[data-road-reference-card]')).to_have_count(1)
                expect(inline.locator('[data-road-reference-card]')).to_have_count(1)
                expect(panel.locator('[data-road-reference^="brand:"]')).to_have_count(1)
                expect(page.locator('#count')).to_have_text('0 件商品')
                assert_reference_detail(page, accessory, state, '#roadReferencePanel')
                brand = panel.locator('a[data-road-reference="brand:canyon"]')
                expect(brand).to_have_attribute('href', accessory['url'])
                brand.click()
                expect(page.locator('#externalExitDomain')).to_have_text('www.canyon.com')
                expect(page.locator('#roadReferenceDetail')).not_to_be_visible()
                page.locator('#externalExitCancel').click()
                expect(brand).to_be_focused()
                page.locator('#close').click()

                # Old bicycle queries never expose saved bicycle/frame references.
                page.locator('#q').fill('Frameset')
                inline_cards(page, 0)
                page.locator('#roadReferencesButton').click()
                expect(panel.locator('[data-road-reference-card]')).to_have_count(0)
                page.locator('#close').click()
                page.locator('#q').fill('no matching reference')
                inline_cards(page, 0)
                page.locator('#clear').click()
                inline_cards(page, 1)
                expect(page.locator('[data-category]')).to_have_count(0)
                check_fx_states(page, state)
                check_language_help(page)

                # Canyon opens its accessory reference directly; bike-only brands stay hidden.
                page.locator('[data-tab=brands]').click()
                for hidden in ['trek', 'specialized', 'colnago']:
                    expect(page.locator(f'[data-source={hidden}]')).to_have_count(0)
                expect(page.locator('[data-source=canyon]')).to_contain_text('配件')
                page.locator('[data-source=canyon]').click()
                page.locator('#sourceProducts').click()
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                inline_cards(page, 1)
                expect(page.locator('[data-category-group=other]')).to_have_attribute('aria-pressed', 'true')
                page.locator('#q').fill('Midloader')
                inline_cards(page, 1)
                image = page.locator('#roadReferenceInline img[data-reference-image]')
                expect(image).to_have_count(1)
                expect(image).to_have_attribute('src', next(r['image'] for r in references if r['id'] == MIDLOADER))
                image.evaluate("img => img.dispatchEvent(new Event('error'))")
                expect(image).to_be_hidden()
                expect(page.locator('#roadReferenceInline .reference-image-fallback')).to_be_visible()
                # A pre-upgrade leaf entry must not silently filter the new single-layer view.
                page.evaluate("history.replaceState({...history.state, bikehuntBrowse:{...history.state.bikehuntBrowse, category:'frames'}}, '')")
                page.reload(wait_until='networkidle')
                check_browse_state(page)

                open_reference(page)
                page.locator('#roadReferenceBack').scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / f'reference_detail_{mode}.png'))
                link = product_link(page)
                expected = next(row['url'] for row in references if row['id'] == MIDLOADER)
                expect(link).to_have_attribute('href', expected)
                original_trigger = link.element_handle()
                link.click()
                expect(page.locator('#externalExitDomain')).to_have_text('www.canyon.com')
                expect(page.locator('#externalExitImage')).to_have_attribute('src', next(row['image'] for row in references if row['id'] == MIDLOADER))
                expect(page.locator('#registrationInterstitial')).to_have_count(0)
                page.locator('#externalExitCancel').click()
                expect(link).to_be_focused()
                assert page.evaluate('(trigger) => document.activeElement === trigger', original_trigger)
                back_to_references(page)
                check_exit_mutations(page, base, expected)

                # A newly opened valid link leaves in this tab and restores all browse scope.
                open_reference(page)
                product_link(page).click()
                expect(page.locator('#externalExitConfirm')).to_be_enabled()
                page.locator('#externalExitConfirm').click()
                expect(page).to_have_url(expected)
                assert len(context.pages) == 1
                page.go_back(wait_until='networkidle')
                check_browse_state(page)
                page.reload(wait_until='networkidle')
                check_browse_state(page)
                page.locator('#clear').click()
                inline_cards(page, 1)
                page.evaluate("chooseCategoryGroup('road_equipment')")
                assert page.evaluate('activeCategoryGroup === null')
                expect(page.locator('#grid [data-road-reference-card]')).to_have_count(0)
                page.locator('[data-category-group=other]').click()
                inline_cards(page, 1)

                # Unrelated brand/team scopes must never expose the global references.
                for tab, source in [('brands', 'brand'), ('teams', 'team')]:
                    page.locator(f'[data-tab={tab}]').click()
                    page.locator(f'[data-source={source}]').click()
                    page.locator('#sourceProducts').click()
                    # This source may have ordinary accessory products; it must not inherit global references.
                    expect(page.locator('#grid [data-road-reference-card]')).to_have_count(0)
                    expect(page.locator('#grid a[data-road-reference]')).to_have_count(0)
                    assert page.evaluate('(source) => activeSource === source', source)

                page.locator('[data-tab=products]').click()
                expect(page.locator('#q')).to_have_value('')
                expect(page.locator('[data-category-group][aria-pressed=true]')).to_have_count(0)
                expect(page.locator('[data-category]')).to_have_count(0)
                assert page.evaluate("activeCategory === 'all'")
                expect(page.locator('#roadReferenceInline')).to_have_count(0)
                expect(page.locator('#grid .card')).to_have_count(2)
                assert page.evaluate('activeSource === null')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(OUT / f'groups_{mode}.png'))
                checks.append(mode + ': four one-level public groups; old five-group payload, bike/frame cards, hidden sources, IDs and history rejected; clothing-only gender with persisted residue clearing; reference list to internal detail to exact guarded same-tab exit; original/current currency and CNY item-only with current/stale/missing FX; read-only displayed options and practical purchase steps; exact/missing/failed images; brand direct guard; honest zero verified count; mobile price/layout and native scroll; group/source/query migration; stock/DOM/URL/filter mutation gates; cancel and list-return focus; merchant Back/reload scope; global reset')
                context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        (OUT / 'results.json').write_text(json.dumps({'checks': checks, 'errors': errors, 'unexpected_external_requests': unexpected, 'unexpected_product_api_requests': product_api_requests}, ensure_ascii=False, indent=2))
    assert not errors, errors
    assert not unexpected, unexpected
    assert not product_api_requests, product_api_requests
    print(json.dumps({'ok': True, 'checks': checks}, ensure_ascii=False))


if __name__ == '__main__':
    main()
