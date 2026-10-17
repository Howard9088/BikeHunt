"""Real browser regression: loading/errors must never masquerade as empty stock."""
import os
import json
import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from test_pages_ui import public_server


def main():
    with public_server() as (base, _), sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'), headless=True)
        for width, height in [(1440, 900), (390, 844)]:
            for failure in [False, True]:
                context = browser.new_context(viewport={'width': width, 'height': height})
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                held = []
                mode = {'blocked': True}

                def publication(route):
                    if not mode['blocked']:
                        route.continue_()
                    elif failure:
                        route.abort()
                    else:
                        held.append(route)

                page.route('**/data/publication.json*', publication)
                page.goto(base, wait_until='domcontentloaded')
                state = '商品暂时无法加载' if failure else '正在整理骑行好价'
                expect(page.locator('#grid')).to_contain_text(state)
                page.get_by_role('button', name='精选好价', exact=True).click()
                page.get_by_role('searchbox').fill('gobik')
                page.get_by_role('button', name='清空搜索', exact=True).click()
                expect(page.locator('#grid')).to_contain_text(state)
                expect(page.locator('#grid')).not_to_contain_text('暂无已核实')
                expect(page.locator('#grid')).not_to_contain_text('没有找到')
                if failure:
                    expect(page.get_by_role('button', name='重新加载', exact=True)).to_be_visible()
                mode['blocked'] = False
                for route in held:
                    route.continue_()
                if failure:
                    page.get_by_role('button', name='重新加载', exact=True).click()
                expect(page.locator('#grid .card').first).to_be_visible(timeout=15000)
                expect(page.locator('[data-category-group]').first).to_be_visible()
                cards = page.locator('#grid .card').count()
                page.get_by_role('link', name='为什么海淘？', exact=True).click()
                expect(page.get_by_role('heading', level=1)).to_have_text('为什么我愿意花时间海淘？')
                page.go_back(wait_until='networkidle')
                expect(page.locator('#grid .card')).to_have_count(cards)
                page.go_forward(wait_until='networkidle')
                page.get_by_role('link', name='← 返回首页', exact=True).click()
                expect(page.locator('#grid .card')).to_have_count(cards)
                if not failure:
                    # A bad/cached publication must retain the last verified cards.
                    bad = json.loads((Path(__file__).resolve().parents[1] / '_site/data/publication.json').read_text())
                    bad['snapshot']['sha256'] = '0' * 64
                    page.route('**/data/publication.json*', lambda route: route.fulfill(status=200, content_type='application/json', body=json.dumps(bad)))
                    page.locator('#refreshPrices').click()
                    expect(page.locator('#sheetName')).to_have_text('价格核对失败')
                    expect(page.locator('#grid .card')).to_have_count(cards)
                    page.locator('#close').click()
                    page.get_by_role('button', name='精选好价', exact=True).click()
                    expect(page.locator('#grid .card')).to_have_count(cards)
                assert not errors, errors
                context.close()
                print(f'{width}px initial {"failure + retry" if failure else "delayed response"}: no false empty, categories/cards recovered, back/forward PASS', flush=True)
        browser.close()


if __name__ == '__main__':
    main()
