"""Actual built catalog: desktop/mobile global scope, slot transitions and images."""
import json
import os
import shutil
import sys
import threading
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/featured-rotation'

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(ROOT/'_site')))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=os.environ.get('BIKEHUNT_TEST_URL') or f'http://127.0.0.1:{server.server_port}/'
    # After the 24h real-new-publication priority window, the actual catalog
    # must visibly rotate if sufficient candidates exist.
    day=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=2)
    before=day+timedelta(hours=3,minutes=29,seconds=59)
    checks=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'),headless=True)
            for mode,viewport in [('desktop',{'width':1440,'height':900}),('mobile',{'width':390,'height':844})]:
                context=browser.new_context(viewport=viewport)
                page=context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                # Product assets are not substituted. Network failures are
                # recorded separately from missing/wrong product image paths.
                page.clock.install(time=before);page.clock.pause_at(before)
                page.goto(base,wait_until='domcontentloaded')
                page.wait_for_function("typeof catalogLoadState!=='undefined'&&catalogLoadState==='ready'",timeout=60000)
                page.wait_for_selector('[data-category-group=helmets]')
                initial=page.evaluate('visibleItems().map(p=>({id:p.product_id,image:p.image,time:p.first_listed_at}))')
                page.clock.run_for(1500)
                midday=page.evaluate('visibleItems().map(p=>({id:p.product_id,image:p.image,time:p.first_listed_at}))')
                pools=page.evaluate("items.filter(channelOfferEligible).length")
                if len(initial)>2 and pools>len(initial):assert initial!=midday,'11:30 should select an observable new batch'
                page.evaluate("openPanel('教程核验','<p id=rotationGuide>保持教程位置</p>')")
                body=page.locator('#sheetBody').inner_html()
                page.clock.fast_forward(23400000)
                assert page.locator('#sheetBody').inner_html()==body
                assert page.evaluate('visibleItems().length')>0
                page.locator('#close').click()
                evening=page.evaluate('visibleItems().map(p=>({id:p.product_id,image:p.image,time:p.first_listed_at}))')
                if len(midday)>2 and pools>len(midday):assert midday!=evening,'18:00 should select another batch after closing guide'
                # Match every selected image/time to the actual catalog record.
                assert page.evaluate("visibleItems().every(p=>items.some(x=>x.product_id===p.product_id&&x.image===p.image&&x.first_listed_at===p.first_listed_at))")
                categories={}
                for group in ['helmets','cleat_shoes']:
                    page.evaluate("openSource('maap')")
                    page.locator('[data-category-group='+group+']').click()
                    assert page.evaluate('activeSource') is None
                    rows=page.evaluate('visibleItems().map(p=>({id:p.product_id,image:p.image,stock:p.reference_stock}))')
                    if not rows:
                        assert page.evaluate('(group)=>items.filter(p=>p.category_group===group).every(p=>p.stock_state==="out_of_stock")',group),'Empty category lacks affirmative sold-out evidence'
                        categories[group]=0
                        print(f'::warning title=Catalog category::{group}: no in-stock products; real sold-out state preserved')
                        continue
                    assert all(row['stock']=='in_stock' and row['image'] for row in rows)
                    page.eval_on_selector_all('#grid img',"imgs=>imgs.forEach(img=>img.loading='eager')")
                    for attempt in range(30):
                        if page.eval_on_selector_all('#grid img',"imgs=>imgs.every(img=>img.complete)"):break
                        page.wait_for_timeout(500)
                    images=page.eval_on_selector_all('#grid img',"imgs=>imgs.map(img=>({src:img.src,loaded:img.complete&&img.naturalWidth>0}))")
                    for image in images:
                        if '/web/assets/product-images/' in image['src']:assert image['loaded'],'Stored exact image failed to load'
                    unavailable=sum(not image['loaded'] for image in images)
                    if unavailable:print(f'::warning title=Product image check::{group}: {unavailable} external images did not load; original product URLs preserved')
                    first_order=[row['id'] for row in rows]
                    page.clock.fast_forward(86400000)
                    assert page.evaluate('visibleItems().map(p=>p.product_id)')==first_order,'Category latest ordering changed with featured clock'
                    categories[group]=len(rows)
                    page.screenshot(path=str(OUT/f'{mode}-{group}.png'))
                page.locator('[data-tab=experiences]').click()
                expect(page.locator('[data-traveler-id]')).to_have_count(10)
                page.locator('#travelerBrand').select_option('POC')
                expect(page.locator('[data-traveler-id]')).to_have_count(1)
                expect(page.locator('[data-traveler-id]')).to_contain_text('2023-08-03')
                expect(page.locator('[data-traveler-id]')).to_contain_text('北美')
                page.locator('[data-traveler-id] summary').first.click()
                expect(page.locator('[data-traveler-id]')).to_contain_text('非本站亲测或投稿')
                assert page.locator('[data-traveler-id] a').first.get_attribute('href').startswith('https://www.reddit.com/')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Horizontal page overflow'
                page.screenshot(path=str(OUT/f'{mode}-experiences.png'))
                assert not errors,errors
                checks.append({'mode':mode,'initial':initial,'midday':midday,'evening':evening,'categories':categories,'javascript_errors':errors})
                context.close()
            browser.close()
    finally:server.shutdown()
    (OUT/'result.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'mode':x['mode'],'categories':x['categories'],'changed_at_1130':x['initial']!=x['midday'],'changed_at_1800':x['midday']!=x['evening']} for x in checks]))

if __name__=='__main__':main()
