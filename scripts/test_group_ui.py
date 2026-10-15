"""Hermetic desktop/mobile tests of the built /BikeHunt/group/ page."""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.pages import build_public_site
from app.fx import snapshot

OUT=ROOT/'artifacts/acceptance'
NOW=datetime(2030,1,1,tzinfo=timezone.utc)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    build_public_site(ROOT,snapshot(json.loads((ROOT/'data/fx_latest.json').read_text())))
    checks=[];errors=[]
    with tempfile.TemporaryDirectory(prefix='bikehunt-group-test-') as temp:
        site=Path(temp)/'BikeHunt'
        shutil.copytree(ROOT/'_site',site)
        # Test-only image fixture also exists after the real group code has expired.
        assets=site/'web/assets/community';assets.mkdir(parents=True,exist_ok=True)
        for name in ('group-20261015.png','group-replacement.png'):
            shutil.copy2(ROOT/'web/assets/community/group-20261015.png',assets/name)
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=temp))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}/BikeHunt/'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'),headless=True)
                for mode,viewport in [('desktop',{'width':1440,'height':900}),('mobile',{'width':390,'height':844})]:
                    context=browser.new_context(viewport=viewport,is_mobile=mode=='mobile',has_touch=mode=='mobile')
                    context.set_default_timeout(7000)
                    config={'schema_version':1,'configured':True,'available':True,'title':'骑游海淘交流群','revision':'first','image_url':'/web/assets/community/group-20261015.png','expires_at':'2030-01-02T00:00:00Z','expiry_label':'微信标注10月22日前有效'}
                    state={'data':copy.deepcopy(config),'fail':False,'image_error':False};requests=[]
                    def route_request(route):
                        url=urlparse(route.request.url)
                        if url.netloc!=urlparse(base).netloc:return route.abort()
                        if url.path=='/BikeHunt/data/community.json':
                            requests.append(route.request.url)
                            if state['fail']:return route.abort()
                            return route.fulfill(content_type='application/json',body=json.dumps(state['data']),headers={'Date':'Tue, 01 Jan 2030 00:00:00 GMT','Cache-Control':'no-store'})
                        if '/web/assets/community/' in url.path and state['image_error']:
                            return route.fulfill(status=404,body='missing test image')
                        return route.continue_()
                    context.route('**/*',route_request)
                    page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                    page.clock.install(time=NOW)
                    def open_group():page.goto(base+'group/',wait_until='networkidle')
                    open_group()
                    expect(page).to_have_title('BikeHunt')
                    expect(page.locator('#groupQr')).to_be_visible()
                    expect(page.locator('#groupQr')).to_have_attribute('src',base+'web/assets/community/group-20261015.png?v=first')
                    expect(page.locator('#groupStatus')).to_have_text('微信标注10月22日前有效')
                    assert page.locator('img').count()==1
                    assert page.locator('button').count()==0
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert len(context.pages)==1
                    page.screenshot(path=str(OUT/f'group_public_{mode}.png'))
                    checks.append(mode+': project prefix, exact title and group name, real image only, responsive layout')
                    # The stable URL acquires a replacement without changing its entrance.
                    state['data'].update(image_url='/web/assets/community/group-replacement.png',revision='second')
                    page.reload(wait_until='networkidle')
                    expect(page.locator('#groupQr')).to_have_attribute('src',base+'web/assets/community/group-replacement.png?v=second')
                    expect(page.locator('#groupQr')).to_be_visible()
                    assert len(set(requests))==len(requests),requests
                    state['image_error']=True;open_group()
                    expect(page.locator('#groupQr')).to_be_hidden()
                    expect(page.locator('#groupQr')).not_to_have_attribute('src')
                    expect(page.locator('#groupStatus')).to_contain_text('无法显示')
                    state['image_error']=False;state['fail']=True;open_group()
                    expect(page.locator('#groupQr')).to_be_hidden()
                    expect(page.locator('#groupStatus')).to_contain_text('无法读取')
                    state['fail']=False
                    for expires in [None,'invalid','2030-02-30T00:00:00Z','2030-01-02T00:00:00']:
                        state['data']['expires_at']=expires;open_group()
                        expect(page.locator('#groupQr')).to_be_hidden()
                        expect(page.locator('#groupStatus')).to_contain_text('待更新')
                    state['data']=copy.deepcopy(config);open_group()
                    expect(page.locator('#groupQr')).to_be_visible()
                    context.set_offline(True)
                    expect(page.locator('#groupQr')).to_be_hidden()
                    expect(page.locator('#groupQr')).not_to_have_attribute('src')
                    expect(page.locator('#groupStatus')).to_contain_text('离线')
                    context.set_offline(False)
                    expect(page.locator('#groupQr')).to_be_visible()
                    # Advance the browser's wall and monotonic clock while it stays open.
                    current_ms=page.evaluate('Date.now()')
                    state['data']['expires_at']=datetime.fromtimestamp((current_ms+3000)/1000,timezone.utc).isoformat()
                    page.reload(wait_until='networkidle')
                    expect(page.locator('#groupQr')).to_be_visible()
                    page.clock.fast_forward(4000)
                    expect(page.locator('#groupQr')).to_be_hidden()
                    expect(page.locator('#groupQr')).not_to_have_attribute('src')
                    expect(page.locator('#groupStatus')).to_contain_text('已到期')
                    page.screenshot(path=str(OUT/f'group_expired_{mode}.png'))
                    checks.append(mode+': replaced image, cache-busted current settings, failed fetch/image, unknown/invalid expiry, offline hiding/recovery, open-page expiry')
                    # A bookmark or direct visit has a working homepage fallback.
                    expect(page.locator('#groupBack')).to_have_attribute('href','../')
                    assert page.evaluate("new URL(document.getElementById('groupBack').href).pathname")=='/BikeHunt/'
                    context.close()
                browser.close()
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)
            (OUT/'group_results.json').write_text(json.dumps({'checks':checks,'errors':errors},ensure_ascii=False,indent=2))
    assert not errors,errors
    print(json.dumps({'ok':True,'checks':checks},ensure_ascii=False))


if __name__=='__main__':main()
