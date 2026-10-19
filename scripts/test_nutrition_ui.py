"""Sports fueling editorial navigation on desktop and narrow mobile viewports."""
import os
import shutil
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from test_pages_ui import public_server

OUT = Path(__file__).resolve().parents[1] / 'artifacts/nutrition'

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with public_server() as (base, _), sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'), headless=True)
        for width, height in [(1440, 900), (390, 844), (320, 740)]:
            context = browser.new_context(viewport={'width': width, 'height': height})
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda err: errors.append(str(err)))
            page.goto(base, wait_until='networkidle')
            button = page.get_by_role('button', name='运动补能', exact=True)
            expect(button).to_be_visible()
            button.click()
            expect(page.locator('.nutrition-brand-reference')).to_have_count(5)
            expect(page.locator('#count')).to_have_text('5 个品牌资料')
            expect(page.locator('.profile-bar')).to_be_hidden()
            expect(page.locator('[data-category-group="road_equipment"]')).to_have_count(0)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            expect(page.locator('#grid .card')).to_have_count(0)
            expect(page.locator('#grid')).not_to_contain_text('¥')
            page.screenshot(path=str(OUT / f'nutrition-{width}.png'), full_page=True)
            page.get_by_role('searchbox').fill('Maurten')
            expect(page.locator('.nutrition-brand-reference')).to_have_count(1)
            page.locator('[data-nutrition-reference="maurten"]').click()
            expect(page.locator('#externalExitDialog')).to_be_visible()
            expect(page.locator('#externalExitDomain')).to_have_text('www.maurten.com')
            page.locator('#externalExitCancel').click()
            expect(page.locator('#externalExitDialog')).not_to_be_visible()
            expect(page.locator('.nutrition-brand-reference')).to_have_count(1)
            page.get_by_role('button', name='清空搜索', exact=True).click()
            expect(page.locator('.nutrition-brand-reference')).to_have_count(5)
            page.reload(wait_until='networkidle')
            expect(page.locator('.nutrition-brand-reference')).to_have_count(5)
            button.click()
            expect(page.locator('.nutrition-reference-page')).to_have_count(0)
            expect(page.locator('.profile-bar')).to_be_visible()
            assert not errors, errors
            context.close()
        browser.close()
    print('PASS sports fueling: desktop/390px/320px, search, exact exit/cancel, reload, reset, no overflow or false offers.')

if __name__ == '__main__':
    main()
