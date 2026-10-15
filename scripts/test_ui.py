"""真实桌面/手机浏览器验收：运行前先启动 BikeHunt。"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from test_catalog_messages_ui import assert_single_category_layer

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "acceptance"
BASE = "http://127.0.0.1:18888"


def read_json(path: str):
    with urllib.request.urlopen(BASE + path, timeout=15) as response:
        return json.load(response)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = read_json("/api/catalog")
    assert data["source_count"] >= 2
    multi = next(p for p in data["items"] if p["source_count"] > 1)
    detail = read_json("/api/catalog/" + multi["product_id"])
    rapha_male = next(p for p in data['items'] if p['brand']=='Rapha' and p['name'].startswith("Men's"))
    assert len(detail["offers"]) >= 2
    assert {p["fx_snapshot_id"] for p in detail["offers"]} == {detail["fx"]["snapshot_id"]}
    assert detail["recommended_offer_id"] is None  # 当前真实数据的条件尚未齐全
    assert all(o["total_cny"] is None for o in detail["offers"])
    results = {"source_count":data["source_count"],"offer_count":data["offer_count"],
               "product_count":len(data["items"]),"multi_source_product":multi["name"],
               "checks":[]}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe", headless=True)
        desktop = browser.new_context(viewport={"width":1440,"height":900})
        page = desktop.new_page()
        errors=[]
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE + "/web/", wait_until="domcontentloaded")
        expect(page.locator(".card").first).to_be_visible(timeout=15000)
        assert not page.locator("body").evaluate("el=>el.classList.contains('grid-mode')")
        assert_single_category_layer(page)
        assert page.locator("#grid").evaluate("el=>getComputedStyle(el).scrollSnapType") == "y mandatory"
        page.locator(".card img").first.evaluate("img=>img.decode().catch(()=>{})")
        page.screenshot(path=str(OUTPUT / "desktop_feed.png"))
        page.mouse.move(720,420)
        page.mouse.wheel(0,850)
        expect(page.locator("#position")).to_have_text("2 / " + str(len(data["items"])), timeout=5000)
        results["checks"].append("desktop_mouse_wheel_snap")
        page.locator("#prev").click()
        expect(page.locator("#position")).to_have_text("1 / " + str(len(data["items"])))
        page.locator(f'.card[data-id="{multi["product_id"]}"] .compare-button').click()
        expect(page.locator('.offer')).to_have_count(0)
        page.locator('#variant').select_option(detail['variant_id'])
        expect(page.locator(".offer")).to_have_count(2)
        expect(page.locator("#variant")).to_have_value(detail["variant_id"])
        page.locator("#sheet").evaluate("el=>Promise.all(el.getAnimations().map(a=>a.finished.catch(()=>{})))")
        page.screenshot(path=str(OUTPUT / "desktop_comparison.png"))
        choices = detail["variants"]
        different = next(v for v in choices if v["variant_id"] != detail["variant_id"] and v['in_stock'])
        page.locator("#variant").select_option(different["variant_id"])
        expect(page.locator(".offer")).to_have_count(different["source_count"])
        results["checks"].append("variant_changes_quote_count")
        page.locator("#close").click()
        page.locator('#browseSettings').click()
        page.locator('button[data-choice="grid"]').click()
        assert page.locator("body").evaluate("el=>el.classList.contains('grid-mode')")
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("body")).to_have_class("grid-mode")
        page.locator("#q").fill("no-such-mock-product")
        expect(page.locator("#grid .empty")).to_contain_text("没有找到")
        page.locator("#resetSearch").click()
        expect(page.locator(".card")).to_have_count(len(data["items"]))
        results["checks"].append("grid_preference_and_search")
        page.locator('[data-tab="teams"]').click()
        expect(page.locator('.directory-card')).to_have_count(18)
        expect(page.locator('.directory-card').first).to_have_attribute('data-source','uae')
        expect(page.locator('.directory-intro')).to_contain_text('2026-10-13')
        expect(page.locator('.team-logo img')).to_have_count(18)
        page.locator('.team-logo img').evaluate_all('imgs=>Promise.all(imgs.map(img=>img.decode()))')
        assert page.locator('.team-logo').evaluate_all('els=>els.every(el=>getComputedStyle(el).backgroundColor==="rgba(0, 0, 0, 0)")')
        assert page.locator('.directory-card').evaluate_all('els=>els.every(el=>el.querySelectorAll(".team-logo img").length===1)')
        page.set_viewport_size({'width':1440,'height':2300})
        page.screenshot(path=str(OUTPUT/'desktop_teams_ranked.png'))
        results['checks'].append('18_single_team_logos_no_background_uci_2026_order')
        assert not errors, errors
        desktop.close()

        mobile = browser.new_context(viewport={"width":390,"height":844},is_mobile=True,has_touch=True,device_scale_factor=1)
        page = mobile.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE + "/web/", wait_until="domcontentloaded")
        expect(page.locator(".card").first).to_be_visible()
        page.locator(".card img").first.evaluate("img=>img.decode().catch(()=>{})")
        box = page.locator(".compare-button").first.bounding_box()
        assert box and box["y"] + box["height"] <= 844
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUTPUT / "mobile_feed.png"))
        client = mobile.new_cdp_session(page)
        client.send("Input.dispatchTouchEvent",{"type":"touchStart","touchPoints":[{"x":180,"y":570}]})
        for step in range(1,11):
            client.send("Input.dispatchTouchEvent",{"type":"touchMove","touchPoints":[{"x":180,"y":570-step*35}]})
            page.wait_for_timeout(18)
        assert page.locator("#grid").evaluate("el=>el.scrollTop") > 100
        client.send("Input.dispatchTouchEvent",{"type":"touchEnd","touchPoints":[]})
        page.wait_for_function("document.querySelector('#grid').scrollTop > 500",timeout=5000)
        page.wait_for_function("!document.querySelector('#grid').classList.contains('gesture-moving')")
        expect(page.locator("#position")).to_have_text("2 / " + str(len(data["items"])))
        results["checks"].append("mobile_real_touch_swipe")
        down_start=page.locator('#grid').bounding_box()['y']+40
        client.send("Input.dispatchTouchEvent",{"type":"touchStart","touchPoints":[{"x":180,"y":down_start}]})
        for step in range(1,11):
            client.send("Input.dispatchTouchEvent",{"type":"touchMove","touchPoints":[{"x":180,"y":down_start+step*35}]})
            page.wait_for_timeout(18)
        client.send("Input.dispatchTouchEvent",{"type":"touchEnd","touchPoints":[]})
        page.wait_for_function("!document.querySelector('#grid').classList.contains('gesture-moving')")
        expect(page.locator("#position")).to_have_text("1 / " + str(len(data["items"])))
        results["checks"].append("mobile_finger_follow_and_down_swipe_one_card")
        page.locator(f'.card[data-id="{multi["product_id"]}"] .compare-button').click()
        page.locator('#variant').select_option(detail['variant_id'])
        expect(page.locator(".offer")).to_have_count(2)
        page.locator("#sheet").evaluate("el=>Promise.all(el.getAnimations().map(a=>a.finished.catch(()=>{})))")
        page.screenshot(path=str(OUTPUT / "mobile_comparison.png"))
        page.locator("#close").click()
        page.locator("#sheet").evaluate("el=>Promise.all(el.getAnimations().map(a=>a.finished.catch(()=>{})))")
        page.locator('#browseSettings').click()
        page.locator('button[data-choice="grid"]').click()
        page.screenshot(path=str(OUTPUT / "mobile_grid.png"))
        page.locator('[data-category-group="helmets"]').click()
        expect(page.locator('[data-category-group="helmets"]')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('.card').first).to_contain_text('骑行头盔')
        assert all(c['category']=='helmets' for c in read_json('/api/catalog?category=helmets')['items'])
        results['checks'].append('product_type_helmet_chinese')
        page.locator('[data-category-group="helmets"]').click()
        expect(page.locator('[data-category-group][aria-pressed=true]')).to_have_count(0)
        page.locator('[data-tab="teams"]').click()
        expect(page.locator('.directory-card')).to_have_count(18)
        page.screenshot(path=str(OUTPUT/'mobile_teams_ranked.png'))
        page.locator('.directory-card[data-source="visma"]').click()
        expect(page.locator('#sheetBody')).to_contain_text('中国：运费 47.95 欧元')
        page.locator('#sheet').evaluate("el=>Promise.all(el.getAnimations().map(a=>a.finished.catch(()=>{})))")
        page.screenshot(path=str(OUTPUT / 'mobile_chinese_rules.png'))
        page.locator('#sourceProducts').click()
        expect(page.locator('.card')).to_have_count(2)
        visma_shirt=next(row for row in data['items'] if row['name']=='Cycling jersey men - The Architect')
        image=page.locator(f'.card[data-id="{visma_shirt["product_id"]}"] img')
        assert '_crop_' not in image.get_attribute('src')
        image.evaluate('img=>img.decode()')
        page.locator('#browseSettings').click()
        page.locator('button[data-choice="feed"]').click()
        expect(page.locator('#sheet')).not_to_have_class('sheet open')
        page.locator('#sheet').evaluate("el=>Promise.all(el.getAnimations().map(a=>a.finished.catch(()=>{})))")
        page.locator(f'.card[data-id="{visma_shirt["product_id"]}"]').scroll_into_view_if_needed()
        page.screenshot(path=str(OUTPUT/'mobile_complete_jersey.png'))
        results['checks'].append('visma_full_gallery_image_no_social_preview_crop')
        page.locator('.card .compare-button').first.click()
        page.locator('[data-variant]').first.click()
        expect(page.locator('.offer .payment-feasibility').first).to_contain_text('中国发行卡')
        expect(page.locator('.registration-help,.purchase-readiness,.cost-estimate,[data-merchant-guide]')).to_have_count(0)
        page.locator('.guide-start').first.click()
        expect(page.locator('#routeComparison')).to_be_visible()
        expect(page.locator('#routeComparison [data-route]')).to_have_count(3)
        expect(page.locator('#routeContinue')).to_be_disabled()
        expect(page.locator('.registration-help')).to_have_count(0)
        page.screenshot(path=str(OUTPUT / 'mobile_route_comparison.png'))
        page.locator('[data-route-select=direct]').click()
        expect(page.locator('[data-route-select=direct]')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#routeContinue')).to_be_enabled()
        page.locator('#routeContinue').click()
        expect(page.locator('#registrationInterstitial')).to_be_visible()
        expect(page.locator('#registrationInterstitial [data-registration-source=visma][data-registration-scope=market]')).to_have_count(1)
        page.screenshot(path=str(OUTPUT / 'mobile_registration_interstitial.png'))
        page.locator('#registrationCancel').click()
        expect(page.locator('#routeComparison')).to_be_visible()
        expect(page.locator('[data-route-select=direct]')).to_have_attribute('aria-pressed', 'true')
        results['checks'].append('team_chinese_rules_route_selection_then_scoped_registration')
        page.locator('#close').click()
        page.locator('[data-tab="products"]').click()
        page.locator('[data-gender="female"]').click()
        assert page.locator('.card').count()==sum(row['gender'] in ('female','unisex') for row in data['items'])
        page.locator('[data-category-group="clothing"]').click()
        female_clothing = [row for row in data['items']
                           if row['category_group'] == 'clothing' and row['gender'] in ('female', 'unisex')]
        expect(page.locator('.card')).to_have_count(len(female_clothing))
        assert set(page.locator('.card').evaluate_all('cards => cards.map(card => card.dataset.id)')) == {
            row['product_id'] for row in female_clothing}
        female_product = next(row for row in female_clothing if row['gender'] == 'female')
        expect(page.locator(f'.card[data-id="{female_product["product_id"]}"]')).to_contain_text('女款')
        page.locator('[data-gender="male"]').click()
        page.locator('[data-category-group="clothing"]').click()
        expect(page.locator('[data-category-group][aria-pressed=true]')).to_have_count(0)
        page.locator('#bodyProfile').click()
        page.locator('#heightCm').fill('175')
        page.locator('#weightKg').fill('68')
        page.locator('#profileForm button[type="submit"]').click()
        expect(page.locator('#bodyProfile')).to_have_text('175 cm / 68 kg')
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('[data-gender="male"]')).to_have_attribute('aria-pressed','true')
        expect(page.locator('#bodyProfile')).to_have_text('175 cm / 68 kg')
        page.locator(f'.card[data-id="{visma_shirt["product_id"]}"] .compare-button').click()
        expect(page.locator('#fitReference')).to_contain_text('补一个胸围')
        page.locator('#chestCm').fill('99')
        page.locator('#chestForm button').click()
        expect(page.locator('.fit-candidates')).to_contain_text('M')
        page.screenshot(path=str(OUTPUT/'mobile_personal_fit.png'))
        page.locator('#close').click()
        page.locator('[data-gender="all"]').click()
        results['checks'].append('gender_height_weight_persist_and_official_chest_stock_reference')
        page.locator('[data-tab="brands"]').click()
        page.locator('[data-source="rapha"]').click()
        page.locator('#sourceProducts').click()
        expect(page.locator('.card')).to_have_count(2)
        page.locator(f'.card[data-id="{rapha_male["product_id"]}"] .compare-button').click()
        expect(page.locator('[data-variant]')).to_have_count(2)
        expect(page.locator('.size-choices')).to_contain_text('XS')
        expect(page.locator('.size-choices')).to_contain_text('S')
        page.locator('[data-variant]').first.click()
        expect(page.locator('.offer')).to_have_count(2)
        expect(page.locator('.offers')).to_contain_text('RCC 会员专享')
        page.screenshot(path=str(OUTPUT / 'mobile_rapha_inventory.png'))
        results['checks'].append('rapha_xs_s_only_and_two_region_spec_prices')
        page.locator('#close').click()
        expect(page.locator('#wechatReminder')).to_have_count(0)
        expect(page.locator('#wechatCommunity')).to_be_visible()
        page.locator('#priceMessages').click()
        expect(page.locator('.message-card').first).to_contain_text('新发现报价')
        expect(page.locator('.message-card').first).to_contain_text('¥')
        page.locator('#close').click()
        results['checks'].append('standalone_wechat_reminder_removed_and_real_price_messages')
        page.locator('#wechatCommunity').click()
        expect(page.locator('#groupTitle')).to_have_text('骑游海淘交流群')
        expect(page.locator('#groupStatus')).not_to_have_text('正在读取群二维码…')
        page.go_back(wait_until='networkidle')
        results['checks'].append('wechat_group_stable_entry')
        assert not errors, errors
        mobile.close()

        short = browser.new_context(viewport={"width":375,"height":667},is_mobile=True,has_touch=True)
        page = short.new_page()
        page.goto(BASE + "/web/", wait_until="domcontentloaded")
        expect(page.locator(".card").first).to_be_visible()
        box = page.locator(".compare-button").first.bounding_box()
        assert box and box["y"] + box["height"] <= 667, box
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        results["checks"].append("small_phone_cta_visible_no_overflow")
        assert page.locator('#q').evaluate('el=>parseFloat(getComputedStyle(el).fontSize)')>=16
        client=short.new_cdp_session(page)
        for _ in range(2):
            client.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':350,'y':380}]})
            client.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
            page.wait_for_timeout(100)
        assert page.evaluate('visualViewport.scale')==1
        results['checks'].append('double_tap_no_zoom_and_search_no_focus_zoom')
        short.close()
        browser.close()
    (OUTPUT / "results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(results,ensure_ascii=True))


if __name__ == "__main__":
    main()

