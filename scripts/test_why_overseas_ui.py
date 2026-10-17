"""Article entrance and full text navigation on desktop and narrow mobile."""
import json
import os
from pathlib import Path
import shutil
import sys
from playwright.sync_api import sync_playwright, expect
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_pages_ui import public_server
ROOT=Path(__file__).resolve().parents[1]

def main():
    # Run after the ordinary public build, keeping its catalog untouched.
    out=ROOT/'artifacts/acceptance';out.mkdir(parents=True,exist_ok=True)
    with public_server() as (base,responses), sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'),headless=True)
        for mode,width,height in [('desktop',1440,900),('mobile',390,844),('narrow',320,700)]:
            context=browser.new_context(viewport={'width':width,'height':height})
            context.route('**/*',lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base,wait_until='networkidle')
            entrance=page.get_by_role('link',name='为什么海淘？',exact=True)
            expect(entrance).to_be_visible()
            box=entrance.bounding_box();assert box['x']>=0 and box['x']+box['width']<=width
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            try:
                expect(page.locator('#grid .card').first).to_be_visible(timeout=15000)
            except AssertionError:
                print('CATALOG_DIAGNOSTIC', page.evaluate("async () => { const r = await fetch('/api/catalog'); const d = await r.json(); return {status: r.status, detail: d.detail, items: d.items?.length, secure: isSecureContext, root: document.querySelector('script[src*=\"pages-adapter\"]').src}; }"), flush=True)
                print('HTTP_DIAGNOSTIC', responses, flush=True)
                raise
            cards=page.locator('#grid .card').count()
            assert cards>0
            page.screenshot(path=str(out/f'why_overseas_home_{mode}.png'))
            for attempt in range(2):
                entrance.click()
                expect(page).to_have_url(base+'why-overseas/')
                expect(page.get_by_role('heading',level=1)).to_have_text('为什么我愿意花时间海淘？')
                assert page.locator('article p').count()==11
                expect(page.locator('article')).to_contain_text('我多年前海淘买到的正版队服，到现在还很珍惜。')
                expect(page.locator('article')).to_contain_text('各有所爱，不必说服谁。')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                if attempt==0:
                    page.screenshot(path=str(out/f'why_overseas_article_{mode}.png'),full_page=True)
                    page.go_back(wait_until='networkidle')
                    expect(entrance).to_be_visible()
                    page.go_forward(wait_until='networkidle')
                    expect(page.get_by_role('heading',level=1)).to_be_visible()
                page.get_by_role('link',name='← 返回首页',exact=True).click()
                expect(page).to_have_url(base)
                expect(entrance).to_be_visible()
                expect(page.locator('#grid .card')).to_have_count(cards)
            page.goto(base+'why-overseas/')
            page.get_by_role('link',name='← 返回首页，继续看好价',exact=True).click()
            expect(entrance).to_be_visible()
            # Direct article URL is readable without scripts or a login.
            plain=browser.new_context(java_script_enabled=False,viewport={'width':width,'height':height})
            tab=plain.new_page();tab.goto(base+'why-overseas/')
            expect(tab.locator('article')).to_contain_text('便宜不能直接等于假货。')
            plain.close()
            assert not errors,errors
            context.close()
            print(mode+': entrance, full article, repeat/back/forward/home, narrow layout, unchanged cards, no JavaScript errors PASS')
        browser.close()
    assert not [x for x in responses if x['status']>=400],responses

if __name__=='__main__':main()
