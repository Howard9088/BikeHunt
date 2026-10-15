"""Hermetic five-group/reference UI on desktop and phones; no merchant access."""
from __future__ import annotations
import copy
import json
import os
import shutil
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT), str(ROOT/'scripts')]
from playwright.sync_api import expect, sync_playwright
from app.browse_taxonomy import CATEGORY_GROUPS
from app.road_equipment import BROWSE_CATEGORIES, read_road_references
from test_featured_deals_ui import fixture as base_fixture, QuietHandler

OUT=ROOT/'artifacts/browse-groups'


def fixture():
    state=base_fixture()
    state['catalog']['category_groups']=CATEGORY_GROUPS
    state['catalog']['categories']=BROWSE_CATEGORIES
    state['catalog']['road_equipment_references']=read_road_references(ROOT)
    state['directories']['brands'] += [dict(code=b['code'], name=b['name'],name_zh=b['name']+' 公路车装备',offer_count=0,product_count=0,rule_count=0,road_reference=True,reference_note=b['note'],official_url=b['url'],shop_url=b['url']) for b in read_road_references(ROOT)['brands']]
    return state


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}/web/'
    errors,checks,unexpected=[],[],[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'),headless=True)
            for mode,viewport in [('desktop',{'width':1440,'height':900}),('mobile',{'width':390,'height':844}),('small_mobile',{'width':320,'height':667})]:
                state=fixture();expected_urls={r['url'] for r in state['catalog']['road_equipment_references']['products']}
                for card in state['catalog']['items']:card['image']=base+'icons/icon-512.png'
                context=browser.new_context(viewport=viewport,is_mobile=mode!='desktop',has_touch=mode!='desktop')
                context.set_default_timeout(7000);context.add_init_script('window.BIKEHUNT_PAGES=true;')
                def intercept(route):
                    url=urlparse(route.request.url)
                    if route.request.url in expected_urls:return route.fulfill(content_type='text/html',body='<h1>Mock official reference page</h1>')
                    if url.netloc!=urlparse(base).netloc:unexpected.append(route.request.url);return route.abort()
                    if not url.path.startswith('/api/'):return route.continue_()
                    if url.path=='/api/catalog':result=state['catalog']
                    elif url.path=='/api/directories':result=state['directories']
                    elif url.path.startswith('/api/rules/'):result={'version':1,'documents':[]}
                    elif url.path=='/api/updates':result={'items':[],'cursor':0,'fx':state['catalog']['fx']}
                    else:result={}
                    route.fulfill(content_type='application/json',body=json.dumps(result))
                context.route('**/*',intercept);page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base,wait_until='networkidle')
                expect(page.locator('[data-category-group]')).to_have_count(5)
                assert page.locator('[data-category-group]').all_text_contents()==['公路车装备','骑行服','头盔','锁鞋','其他']
                expect(page.locator('.card')).to_have_count(1)
                page.locator('[data-category-group=road_equipment]').click();expect(page.locator('.card')).to_have_count(0)
                expect(page.locator('#roadReferenceStrip')).to_be_visible();page.locator('#roadReferencesButton').click()
                expect(page.locator('[data-road-reference-card]')).to_have_count(4)
                expect(page.locator('#roadReferencePanel')).to_contain_text('库存待核实')
                expect(page.locator('#roadReferencePanel')).to_contain_text('不接受转运地址')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(OUT/f'references_{mode}.png'))
                page.locator('#close').click();page.locator('[data-category=frames]').click();page.locator('#roadReferencesButton').click();expect(page.locator('[data-road-reference-card]')).to_have_count(1)
                page.locator('#close').click();page.locator('[data-category=all]').click()
                page.locator('[data-tab=brands]').click();page.locator('[data-source=canyon]').click();page.locator('#sourceProducts').click()
                expect(page.locator('[data-road-reference-card]')).to_have_count(3)
                page.locator('#close').click();page.locator('#q').fill('Midloader');page.reload(wait_until='networkidle');expect(page.locator('#q')).to_have_value('Midloader');page.locator('#roadReferencesButton').click();expect(page.locator('[data-road-reference-card]')).to_have_count(1)
                link=page.locator('[data-road-reference="product:canyon-9102039"]');expected=link.get_attribute('href');link.click()
                expect(page.locator('#externalExitDomain')).to_have_text('www.canyon.com')
                expect(page.locator('#registrationInterstitial')).to_have_count(0)
                page.locator('#externalExitCancel').click();expect(page.locator('#roadReferencePanel')).to_be_visible();link.click();page.locator('#externalExitConfirm').click();expect(page).to_have_url(expected)
                assert len(context.pages)==1
                page.go_back(wait_until='networkidle');expect(page.locator('#q')).to_have_value('Midloader');expect(page.locator('[data-category-group=road_equipment]')).to_have_attribute('aria-pressed','true');expect(page.locator('#browseLabel')).to_contain_text('Canyon')
                page.reload(wait_until='networkidle');expect(page.locator('#q')).to_have_value('Midloader');expect(page.locator('[data-category=all]')).to_have_attribute('aria-pressed','true')
                page.locator('[data-tab=products]').click();expect(page.locator('#q')).to_have_value('');expect(page.locator('[data-category-group][aria-pressed=true]')).to_have_count(0);expect(page.locator('.card')).to_have_count(1)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(OUT/f'groups_{mode}.png'));checks.append(mode+': ordered five groups, leaf/source/query scope, honest references, exact guarded same-tab URL, Back/reload and global reset');context.close()
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        (OUT/'results.json').write_text(json.dumps({'checks':checks,'errors':errors,'unexpected_external_requests':unexpected},ensure_ascii=False,indent=2))
    assert not errors,errors
    assert not unexpected,unexpected
    print(json.dumps({'ok':True,'checks':checks},ensure_ascii=False))


if __name__=='__main__':main()
