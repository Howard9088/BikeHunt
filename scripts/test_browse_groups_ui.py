"""Hermetic inline road-reference UI on desktop and phones; no merchant access."""
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


def product_link(page, identifier=MIDLOADER):
    return page.locator(f'#roadReferenceInline a[data-road-reference="product:{identifier}"]')


def assert_inline_layout(page, viewport):
    inline = inline_cards(page, 3)
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
    assert gallery.evaluate('(element) => element.scrollHeight > element.clientHeight')
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
    # Stock changes during reading invalidate the originally opened entry.
    product_link(page).click()
    page.evaluate("""(id) => {
        roadReferenceData.products.find(row => row.id === id).stock = 'out_of_stock';
    }""", MIDLOADER)
    assert_disabled_exit(page, base)
    page.evaluate('render()')
    sold = inline_cards(page, 1).locator(f'[data-road-reference-card="{MIDLOADER}"]')
    expect(sold).to_contain_text('已确认售罄')
    expect(sold.locator('a')).to_have_count(0)
    page.evaluate("""(id) => {
        roadReferenceData.products.find(row => row.id === id).stock = 'unknown';
        render();
    }""", MIDLOADER)
    expect(product_link(page)).to_have_attribute('href', expected_url)

    # Changing only the DOM destination must not reuse the original confirmation.
    product_link(page).click()
    product_link(page).evaluate("(link) => link.setAttribute('href', link.href + '?changed=1')")
    assert_disabled_exit(page, base)
    page.evaluate('render()')
    expect(product_link(page)).to_have_attribute('href', expected_url)

    # A new same-host record URL is still a different exact destination.
    product_link(page).click()
    page.evaluate("""(id) => {
        roadReferenceData.products.find(row => row.id === id).url += '?changed=1';
    }""", MIDLOADER)
    assert_disabled_exit(page, base)
    page.evaluate("""({id, url}) => {
        roadReferenceData.products.find(row => row.id === id).url = url;
        render();
    }""", {'id': MIDLOADER, 'url': expected_url})

    # Re-rendering an identical card detaches the trigger and requires a fresh visit.
    product_link(page).click()
    page.evaluate('render()')
    assert_disabled_exit(page, base)
    expect(product_link(page)).to_have_attribute('href', expected_url)
    product_link(page).click()
    expect(page.locator('#externalExitConfirm')).to_be_enabled()
    page.locator('#externalExitCancel').click()
    expect(product_link(page)).to_be_focused()


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
    errors, checks, unexpected = [], [], []
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
                expect(page.locator('[data-category-group]')).to_have_count(5)
                assert page.locator('[data-category-group]').all_text_contents() == ['自行车', '骑行服饰', '锁鞋', '头盔', '配件与周边']
                expect(page.locator('#categoryNav')).to_have_count(0)
                expect(page.locator('[data-category]')).to_have_count(0)
                expect(page.locator('#grid .card')).to_have_count(1)
                expect(page.locator('#roadReferenceInline')).to_have_count(0)
                page.locator('[data-category-group=road_equipment]').click()
                inline = inline_cards(page, 3)
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                expect(inline).to_contain_text('库存待核实')
                for row in [r for r in references if r['category_group'] == 'road_equipment']:
                    record = inline.locator(f'[data-road-reference-card="{row["id"]}"]')
                    expect(record).to_contain_text(row['name'])
                    expect(record).to_contain_text('库存待核实')
                    link = record.locator(f'a[data-road-reference="product:{row["id"]}"]')
                    expect(link).to_have_attribute('href', row['url'])
                    expect(link).to_have_attribute('target', '_self')
                assert_inline_layout(page, viewport)
                page.screenshot(path=str(OUT / f'references_{mode}.png'))

                # An explicitly opened reference sheet can coexist without count leakage.
                expect(page.locator('#roadReferenceStrip')).to_be_visible()
                page.locator('#roadReferencesButton').click()
                panel = page.locator('#roadReferencePanel')
                expect(panel).to_be_visible()
                expect(panel.locator('[data-road-reference-card]')).to_have_count(3)
                expect(inline.locator('[data-road-reference-card]')).to_have_count(3)
                expect(panel).to_contain_text('不接受转运地址')
                expect(page.locator('#count')).to_have_text('0 件商品')
                page.locator('#close').click()

                # One visible category row; search and group reset never create a second layer.
                page.locator('#q').fill('Frameset')
                expect(inline_cards(page, 1)).to_contain_text('Ultimate CF SL Frameset')
                page.locator('#roadReferencesButton').click()
                expect(panel.locator('[data-road-reference-card]')).to_have_count(1)
                page.locator('#close').click()
                page.locator('#q').fill('no matching reference')
                inline_cards(page, 0)
                page.locator('#clear').click()
                inline_cards(page, 3)
                page.locator('[data-category-group=other]').click()
                expect(inline_cards(page, 1)).to_contain_text('Canyon Midloader')
                expect(page.locator('[data-category]')).to_have_count(0)

                # A brand source returns directly to its bike records; accessories remain discoverable.
                page.locator('[data-tab=brands]').click()
                page.locator('[data-source=canyon]').click()
                page.locator('#sourceProducts').click()
                expect(page.locator('#sheet')).to_have_attribute('aria-hidden', 'true')
                inline_cards(page, 2)
                page.locator('#q').fill('Midloader')
                inline_cards(page, 0)
                page.locator('[data-category-group=other]').click()
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

                link = product_link(page)
                expected = next(row['url'] for row in references if row['id'] == MIDLOADER)
                expect(link).to_have_attribute('href', expected)
                original_trigger = link.element_handle()
                link.click()
                expect(page.locator('#externalExitDomain')).to_have_text('www.canyon.com')
                expect(page.locator('#registrationInterstitial')).to_have_count(0)
                page.locator('#externalExitCancel').click()
                expect(link).to_be_focused()
                assert page.evaluate('(trigger) => document.activeElement === trigger', original_trigger)
                check_exit_mutations(page, base, expected)

                # A newly opened valid link leaves in this tab and restores all browse scope.
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
                page.locator('[data-category-group=road_equipment]').click()
                inline_cards(page, 2)
                page.locator('[data-category-group=other]').click()
                inline_cards(page, 1)

                # Unrelated brand/team scopes must never expose the global references.
                for tab, source in [('brands', 'brand'), ('teams', 'team')]:
                    page.locator(f'[data-tab={tab}]').click()
                    page.locator(f'[data-source={source}]').click()
                    page.locator('#sourceProducts').click()
                    inline_cards(page, 0)
                    assert page.evaluate('(source) => activeSource === source', source)

                page.locator('[data-tab=products]').click()
                expect(page.locator('#q')).to_have_value('')
                expect(page.locator('[data-category-group][aria-pressed=true]')).to_have_count(0)
                expect(page.locator('[data-category]')).to_have_count(0)
                assert page.evaluate("activeCategory === 'all'")
                expect(page.locator('#roadReferenceInline')).to_have_count(0)
                expect(page.locator('#grid .card')).to_have_count(1)
                assert page.evaluate('activeSource === null')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(OUT / f'groups_{mode}.png'))
                checks.append(mode + ': inline references before brand directory; honest zero verified count; first-screen price and native scroll; exact links; single-layer group/source/query filters and old-leaf migration; sold-out and stale-link guards; exact cancel focus; same-tab Back/reload scope; global reset')
                context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        (OUT / 'results.json').write_text(json.dumps({'checks': checks, 'errors': errors, 'unexpected_external_requests': unexpected}, ensure_ascii=False, indent=2))
    assert not errors, errors
    assert not unexpected, unexpected
    print(json.dumps({'ok': True, 'checks': checks}, ensure_ascii=False))


if __name__ == '__main__':
    main()
