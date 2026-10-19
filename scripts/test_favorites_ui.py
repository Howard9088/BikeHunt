"""Hermetic local favorites regression; synthetic catalog, no outside requests."""
import json, os, shutil, threading
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs,urlparse
from playwright.sync_api import expect,sync_playwright
from test_featured_deals_ui import ROOT,QuietHandler
from test_nutrition_ui import fixture

OUT=ROOT/'artifacts/favorites'
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}/web/'
    try:
      with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=os.environ.get('CHROME_EXECUTABLE') or shutil.which('chromium'),headless=True)
        for width,height in [(1440,900),(390,844),(320,740)]:
          state=fixture(base);errors=[]
          context=browser.new_context(viewport={'width':width,'height':height})
          context.add_init_script('window.BIKEHUNT_PAGES=true')
          def intercept(route):
            url=urlparse(route.request.url)
            if url.netloc!=urlparse(base).netloc:return route.abort()
            if not url.path.startswith('/api/'):return route.continue_()
            if url.path=='/api/catalog':result=state['catalog']
            elif url.path.startswith('/api/catalog/'):
              card=next(c for c in state['catalog']['items'] if c['product_id']==url.path.rsplit('/',1)[-1])
              variant=parse_qs(url.query).get('variant_id',[card['reference_variant_id']])[0];result=state['details'][variant]
            elif url.path=='/api/directories':result=state['directories']
            elif url.path=='/api/updates':result={'items':[],'cursor':0,'fx':state['catalog']['fx']}
            else:result={}
            route.fulfill(content_type='application/json',body=json.dumps(result))
          context.route('**/*',intercept)
          page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
          page.goto(base,wait_until='networkidle')
          heart=page.locator('#grid [data-favorite]').first
          expect(heart).to_be_visible();heart.focus();page.keyboard.press('Space')
          expect(heart).to_have_attribute('aria-pressed','true');expect(page.locator('#sheet')).not_to_have_class('sheet open')
          expect(page.locator('#myFavorites')).to_contain_text('(1)')
          stored=page.evaluate('JSON.parse(localStorage.getItem("bikehuntFavoritesV1"))');assert stored['items'][0]['variantId'] is None
          page.reload(wait_until='networkidle');expect(heart).to_have_attribute('aria-pressed','true')
          page.locator('#grid .compare-button').first.click();expect(page.locator('.favorite-detail')).to_have_attribute('aria-pressed','true')
          page.locator('.favorite-detail').click();expect(page.locator('.favorite-detail')).to_have_attribute('aria-pressed','false')
          apple=next(k for k,d in state['details'].items() if d['identity']['size'].startswith('Apple'))
          page.locator('#variant').select_option(apple);expect(page.locator('.offers')).to_contain_text('Apple')
          page.locator('.favorite-detail').click()
          assert page.evaluate('JSON.parse(localStorage.getItem("bikehuntFavoritesV1")).items[0].variantId')==apple
          page.locator('#close').click();expect(heart).to_have_attribute('aria-pressed','true')
          page.locator('#myFavorites').click();expect(page.locator('#favoritesPanel')).to_contain_text('Apple')
          expect(page.locator('#favoritesPanel')).to_contain_text('仅保存在此浏览器');expect(page.locator('.favorite-item')).to_have_count(1)
          assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
          page.screenshot(path=str(OUT/f'favorites-{width}.png'),full_page=True)
          page.locator('[data-favorite-open]').click();expect(page.locator('#variant')).to_have_value('')
          page.keyboard.press('Escape');expect(page.locator('#myFavorites')).to_be_focused()
          # Latest catalog value wins over saved data; sold-out stays visible in favorites.
          card=next(c for c in state['catalog']['items'] if c['brand']=='SiS')
          card.update(stock_state='out_of_stock',reference_price={'amount':'99','currency':'GBP'},reference_collection_state='retained')
          page.reload(wait_until='networkidle');page.locator('#myFavorites').click()
          expect(page.locator('.favorite-item')).to_contain_text('售罄');expect(page.locator('.favorite-item')).to_contain_text('99.00')
          # Missing catalog entries are bookmarks only, no old price or purchase button.
          state['catalog']['items']=[c for c in state['catalog']['items'] if c['brand']!='SiS']
          page.reload(wait_until='networkidle');page.locator('#myFavorites').click()
          expect(page.locator('.favorite-item')).to_contain_text('当前目录暂无此商品');expect(page.locator('[data-favorite-open]')).to_have_count(0)
          expect(page.locator('.favorite-item')).not_to_contain_text('99.00')
          page.locator('#favoritesPanel [data-favorite]').focus();page.keyboard.press('Enter')
          expect(page.locator('.favorites-empty')).to_be_visible();expect(page.locator('[data-favorites-browse]')).to_be_focused()
          # Malformed data is recoverable; a new user action writes a valid store.
          state=fixture(base)
          page.evaluate('localStorage.setItem("bikehuntFavoritesV1","broken")');page.reload(wait_until='networkidle')
          page.locator('#myFavorites').click();expect(page.locator('#favoriteNotice')).to_contain_text('无法读取')
          page.locator('#close').click();heart.click();expect(heart).to_have_attribute('aria-pressed','true')
          # Real storage event from another same-origin tab updates all surfaces.
          other=context.new_page();other.goto(base,wait_until='networkidle')
          other.locator('#grid [data-favorite]').first.click();expect(heart).to_have_attribute('aria-pressed','false');other.close()
          assert not errors,errors
          context.close()
        # Disabled browser storage must leave browsing and session toggles usable.
        context=browser.new_context();context.add_init_script('window.BIKEHUNT_PAGES=true;Object.defineProperty(window,"localStorage",{get(){throw Error("blocked")}})')
        state=fixture(base);context.route('**/*',intercept);page=context.new_page();page.goto(base,wait_until='networkidle')
        page.locator('#grid [data-favorite]').first.click();page.locator('#myFavorites').click()
        expect(page.locator('#favoriteNotice')).to_contain_text('未能保存');expect(page.locator('.favorite-item')).to_have_count(1)
        context.close();browser.close()
    finally:server.shutdown();server.server_close()
    print('PASS favorites desktop/390/320, keyboard, persistence, explicit size, multi-surface and cross-tab sync, refreshed/sold-out/removed catalog, malformed and denied storage.')
if __name__=='__main__':main()
