"""验证 GitHub Pages 静态站点：.venv/Scripts/python scripts/test_pages_ui.py。"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import traceback
import urllib.request
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote, urljoin, urlparse

from loguru import logger
from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.fx import snapshot
from app.pages import build_public_site

SITE = ROOT / "_site"
OUTPUT = ROOT / "artifacts" / "acceptance"
PREFIX = "/BikeHunt/"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def read_published_data(base: str) -> dict:
    """读取公开网址的实际快照；请求失败按 1/2 秒退避，最多尝试三次。"""
    request = urllib.request.Request(urljoin(base, "data/site-data.json"),
                                     headers={"User-Agent": "BikeHunt-Pages-Acceptance/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)
        except Exception as error:
            logger.warning("公开数据读取失败 attempt={}/3 {}", attempt + 1, error)
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Published snapshot unavailable")


@contextmanager
def public_server() -> Iterator[tuple[str, list[dict]]]:
    """以随机本地端口提供 /BikeHunt/ 静态目录，退出时关闭监听。"""
    responses: list[dict] = []

    class Handler(SimpleHTTPRequestHandler):
        def translate_path(self, path: str) -> str:
            parsed = unquote(urlparse(path).path)
            relative = parsed[len(PREFIX):] if parsed.startswith(PREFIX) else "__outside_site__"
            target = (SITE / relative).resolve()
            if not target.is_relative_to(SITE.resolve()):
                target = SITE / "__outside_site__"
            return str(target)

        def send_response(self, code: int, message: str | None = None) -> None:
            responses.append({"path": self.path, "status": code})
            super().send_response(code, message)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}{PREFIX}", responses
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def assert_public_links(page: Page) -> None:
    """检查当前页面实际呈现的链接没有本机配置入口。"""
    local_links = page.locator("a[href]").evaluate_all(r"""links => links
        .map(link => link.getAttribute('href'))
        .filter(href => /^https?:\/\/(?:127(?:\.\d+){3}|localhost|\[::1\])(?::|\/|$)/i.test(href))""")
    assert not local_links, f"公开页显示本机链接：{local_links}"


def capture(page: Page, name: str, results: dict) -> None:
    """保存验收截图，先等待弹层动画结束并检查本机链接。"""
    assert_public_links(page)
    page.locator("#sheet").evaluate(
        "el => Promise.all(el.getAnimations().map(animation => animation.finished.catch(() => {})))"
    )
    if name.endswith("_feed"):
        photo = page.locator(".card img").first
        state = photo.evaluate("""async image => {
            await Promise.race([
                image.decode().catch(() => {}),
                new Promise(resolve => setTimeout(resolve, 8000))
            ]);
            return {src: image.src, complete: image.complete, width: image.naturalWidth};
        }""")
        results.setdefault("product_images", []).append({"screenshot": name, **state})
    path = OUTPUT / f'{results["artifact_prefix"]}{name}.png'
    page.screenshot(path=str(path))
    results["screenshots"].append(str(path))


def open_product(page: Page, product_id: str) -> None:
    """从商品卡打开真实规格弹层。"""
    page.locator(f'.card[data-id="{product_id}"] .compare-button').click()
    expect(page.locator("#variant")).to_be_attached()


def close_panel(page: Page) -> None:
    page.locator("#close").click()
    expect(page.locator("#sheet")).to_have_attribute("aria-hidden", "true")


def exercise(base: str, data: dict, results: dict) -> None:
    """在真实 Chrome 中验证桌面和手机的公开站点主流程。"""
    catalog = data["catalog"]["items"]
    assert 40 <= len(catalog) <= 60, f"公开商品数量异常：{len(catalog)}"
    multi = next(card for card in catalog if card["source_count"] > 1)
    family = data["details"][multi["product_id"]]
    multi_detail = family["variants"][family["default"]]
    selected = next(variant for variant in multi_detail["variants"]
                    if variant["in_stock"] and variant["source_count"] > 1)
    selected_detail = family["variants"][selected["variant_id"]]
    visma = next(card for card in catalog if card["name"] == "Cycling jersey men - The Architect")
    colored = next(card for card in catalog
                   if len(data["details"][card["product_id"]]["variants"]
                          [data["details"][card["product_id"]]["default"]]["colors"]) > 1)

    errors: list[str] = []
    backend_requests: list[dict] = []
    event_sources: list[str] = []
    local_http_errors: list[dict] = []
    external_failed_requests: list[dict] = []
    requests: list[dict] = []
    local_origin = urlparse(base).netloc
    public_prefix = urlparse(base).path

    def request_observed(request) -> None:
        parsed = urlparse(request.url)
        entry = {"url": request.url, "type": request.resource_type, "method": request.method}
        if parsed.netloc == local_origin:
            requests.append(entry)
        if "/api/" in parsed.path or request.resource_type == "eventsource":
            backend_requests.append(entry)

    def response_observed(response) -> None:
        parsed = urlparse(response.url)
        if parsed.netloc == local_origin and parsed.path.startswith(public_prefix) and response.status >= 400:
            local_http_errors.append({"url": response.url, "status": response.status})

    def request_failed(request) -> None:
        if urlparse(request.url).netloc != local_origin:
            external_failed_requests.append({"url": request.url, "error": request.failure})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROME, headless=True)
        try:
            for mobile in (False, True):
                context = browser.new_context(
                    viewport={"width": 390 if mobile else 1440, "height": 844 if mobile else 900},
                    is_mobile=mobile, has_touch=mobile, device_scale_factor=1,
                )
                context.on("request", request_observed)
                context.on("response", response_observed)
                context.on("requestfailed", request_failed)
                context.add_init_script("""window.__pagesEventSources = [];
                    const originalEventSource = window.EventSource;
                    window.EventSource = function(url, options) {
                        window.__pagesEventSources.push(String(url));
                        return new originalEventSource(url, options);
                    };""")
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.set_default_timeout(15000)
                try:
                    page.goto(base, wait_until="domcontentloaded")
                    expect(page.locator(".card")).to_have_count(len(catalog))
                    expect(page.locator(".card").first).to_be_visible()
                    expect(page.locator("#categoryNav button")).to_have_count(7)
                    assert page.evaluate("window.BIKEHUNT_PAGES === true")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    label = "mobile" if mobile else "desktop"
                    capture(page, f"{label}_feed", results)
                    results["checks"].append(f"{label}_subdirectory_loads_{len(catalog)}_products")

                    page.locator("#browseSettings").click()
                    page.locator('[data-choice="grid"]').click()
                    open_product(page, multi["product_id"])
                    expect(page.locator(".offer")).to_have_count(0)
                    page.locator("#variant").select_option(selected["variant_id"])
                    expect(page.locator(".offer")).to_have_count(len(selected_detail["offers"]))
                    expect(page.locator(".offers h4")).to_contain_text(selected_detail["identity"]["size"])
                    expect(page.locator(".spec-note")).to_contain_text(
                        selected_detail["identity"]["color"] or "原站核对颜色"
                    )
                    assert len({offer["offer"]["identity"]["size"]
                                for offer in selected_detail["offers"]}) == 1
                    capture(page, f"{label}_comparison", results)
                    close_panel(page)
                    results["checks"].append(f"{label}_selects_same_spec_multi_source_prices")

                    if not mobile:
                        open_product(page, colored["product_id"])
                        expect(page.locator("#colorChoice")).to_be_attached()
                        colors = page.locator("#colorChoice option").evaluate_all(
                            "options => options.map(option => ({id: option.value, color: option.textContent}))"
                        )
                        other = next(color for color in colors if color["id"] != colored["product_id"])
                        page.locator("#colorChoice").select_option(other["id"])
                        expect(page.locator(".spec-note")).to_contain_text(other["color"])
                        expect(page.locator("#variant")).to_have_value("")
                        page.locator("[data-variant]").first.click()
                        expect(page.locator(".offer")).not_to_have_count(0)
                        capture(page, "desktop_color_size", results)
                        close_panel(page)
                        results["checks"].append("color_switch_resets_size_then_compares_selected_color")

                        page.locator('[data-tab="teams"]').click()
                        teams = data["directories"]["teams"]
                        expect(page.locator(".directory-card")).to_have_count(18)
                        assert page.locator(".directory-card").evaluate_all(
                            "cards => cards.map(card => card.dataset.source)"
                        ) == [team["code"] for team in teams]
                        expect(page.locator(".directory-intro")).to_contain_text(
                            data["directories"]["team_ranking"]["ranking_date"]
                        )
                        for index, team in enumerate(teams):
                            expect(page.locator(".team-rank").nth(index)).to_have_text(
                                f'UCI 第 {team["world_rank"]} 名'
                            )
                        expect(page.locator(".team-logo img")).to_have_count(18)
                        page.locator(".team-logo img").evaluate_all(
                            "images => Promise.all(images.map(image => image.decode()))"
                        )
                        logo_state = page.locator(".team-logo img").evaluate_all(
                            "images => images.map(image => ({src: image.getAttribute('src'), width: image.naturalWidth}))"
                        )
                        assert all(logo["src"].startswith(public_prefix + "web/") and logo["width"] > 0
                                   for logo in logo_state), logo_state
                        results["logos"] = logo_state
                        page.set_viewport_size({"width": 1440, "height": 2300})
                        capture(page, "desktop_18_teams_uci", results)
                        results["checks"].append("18_subpath_team_logos_decoded_and_uci_rank_order")
                        continue

                    page.locator('[data-gender="female"]').click()
                    female_count = sum(card["gender"] in ("female", "unisex") for card in catalog)
                    expect(page.locator(".card")).to_have_count(female_count)
                    page.reload(wait_until="domcontentloaded")
                    expect(page.locator('[data-gender="female"]')).to_have_attribute("aria-pressed", "true")
                    expect(page.locator(".card")).to_have_count(female_count)
                    page.locator('[data-gender="male"]').click()
                    male_count = sum(card["gender"] in ("male", "unisex") for card in catalog)
                    expect(page.locator(".card")).to_have_count(male_count)
                    page.locator("#bodyProfile").click()
                    page.locator("#heightCm").fill("175")
                    page.locator("#weightKg").fill("68")
                    page.locator('#profileForm button[type="submit"]').click()
                    page.reload(wait_until="domcontentloaded")
                    expect(page.locator('[data-gender="male"]')).to_have_attribute("aria-pressed", "true")
                    expect(page.locator("#bodyProfile")).to_have_text("175 cm / 68 kg")
                    expect(page.locator(".card")).to_have_count(male_count)
                    open_product(page, visma["product_id"])
                    expect(page.locator("#fitReference")).to_contain_text("补一个胸围")
                    page.locator("#chestCm").fill("99")
                    page.locator("#chestForm button").click()
                    expect(page.locator(".fit-candidates strong")).to_have_text("M")
                    capture(page, "mobile_visma_fit_M", results)
                    results["checks"].append("female_male_height_weight_persist_and_visma_chest99_reference_M")
                    page.locator("[data-variant]").first.click()
                    expect(page.locator(".offer .payment-feasibility").first).to_contain_text("中国发行卡")
                    expect(page.locator(".offer .payment-feasibility").first).to_contain_text("不保证")
                    expect(page.locator(".registration-help,.purchase-readiness,[data-merchant-guide]")).to_have_count(0)
                    page.locator(".guide-start").first.click()
                    expect(page.locator("#routeComparison")).to_be_visible()
                    expect(page.locator("#routeComparison [data-route]")).to_have_count(3)
                    expect(page.locator("#routeContinue")).to_be_disabled()
                    expect(page.locator(".registration-help")).to_have_count(0)
                    capture(page, "mobile_route_comparison", results)
                    page.locator("[data-route-select=direct]").click()
                    expect(page.locator("[data-route-select=direct]")).to_have_attribute("aria-pressed", "true")
                    expect(page.locator("#routeContinue")).to_be_enabled()
                    page.locator("#routeContinue").click()
                    expect(page.locator("#registrationInterstitial")).to_be_visible()
                    expect(page.locator("#registrationInterstitial .registration-help")).to_have_count(1)
                    expect(page.locator("#registrationInterstitial [data-registration-source=visma][data-registration-scope=market]")).to_have_count(1)
                    assert page.evaluate("history.state.bikehuntPurchase.url").startswith("https://www.teamvismaleaseabike.com/")
                    capture(page, "mobile_registration_interstitial", results)
                    page.locator("#registrationCancel").click()
                    expect(page.locator("#routeComparison")).to_be_visible()
                    expect(page.locator("[data-route-select=direct]")).to_have_attribute("aria-pressed", "true")
                    expect(page.locator(".registration-help")).to_have_count(0)
                    results["checks"].append("real_route_controls_then_scoped_registration_and_cancel_preserves_route")
                    close_panel(page)

                    expect(page.locator("#wechatReminder")).to_have_count(0)
                    expect(page.locator("#wechatCommunity")).to_be_visible()
                    page.locator("#wechatCommunity").click()
                    expect(page).to_have_url(base + "group/")
                    expect(page.locator("#groupTitle")).to_have_text("骑游海淘交流群")
                    if data["community"].get("available"):
                        expect(page.locator("#groupQr")).to_be_visible()
                    else:
                        expect(page.locator("#groupQr")).to_be_hidden()
                        expect(page.locator("#groupStatus")).to_contain_text("更新")
                    capture(page, "mobile_wechat_community", results)
                    page.go_back(wait_until="networkidle")
                    expect(page).to_have_url(base)
                    results["checks"].append("standalone_wechat_reminder_removed_and_group_entry_preserved")

                    page.locator("#priceMessages").click()
                    expect(page.locator(".message-card").first).to_be_visible()
                    expect(page.locator(".message-card").first).to_contain_text("¥")
                    capture(page, "mobile_price_messages", results)
                    close_panel(page)
                    page.locator("#refreshPrices").click()
                    expect(page.locator("#refreshPrices")).to_have_text("检查最新发布", timeout=20000)
                    expect(page.locator("#refreshPrices")).to_be_enabled()
                    expect(page.locator(".card")).to_have_count(male_count)
                    results["checks"].append("published_price_messages_and_snapshot_refresh")
                except Exception:
                    path = OUTPUT / f'{results["artifact_prefix"]}{"mobile" if mobile else "desktop"}_failure.png'
                    page.screenshot(path=str(path))
                    results["screenshots"].append(str(path))
                    raise
                finally:
                    event_sources.extend(page.evaluate("window.__pagesEventSources || []"))
                    context.close()
        finally:
            browser.close()
            results["page_errors"] = errors
            results["backend_requests"] = backend_requests
            results["event_source_constructions"] = event_sources
            results["local_http_errors"] = local_http_errors
            results["external_failed_requests"] = external_failed_requests
            results["local_requests"] = requests
    assert not errors, errors
    assert not backend_requests, f"静态站点仍访问 API 或 SSE：{backend_requests}"
    assert not event_sources, f"静态站点仍建立 SSE：{event_sources}"
    assert not local_http_errors, local_http_errors
    results["checks"].append("no_api_http_no_sse_no_local_links_no_missing_subpath_assets")


def main() -> None:
    """默认构建本地站；--url 仅验收远端，失败仍保存独立诊断。"""
    parser = argparse.ArgumentParser(description="验收本地构建或已发布的 BikeHunt Pages 网站")
    parser.add_argument("--url", help="已发布网站根网址，例如 https://howard9088.github.io/BikeHunt/")
    args = parser.parse_args()
    base = None
    if args.url:
        parsed = urlparse(args.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
            parser.error("--url 必须是没有查询参数和片段的 HTTP/HTTPS 网站根网址")
        base = args.url.rstrip("/") + "/"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: dict = {"ok": False, "checks": [], "screenshots": [],
                     "mode": "published" if base else "local_preview",
                     "artifact_prefix": "pages_published_" if base else "pages_"}
    try:
        if base:
            results["url"] = base
            data = read_published_data(base)
        else:
            # 验收沿用真实汇率快照，不在 UI 测试中访问 ECB 或改写汇率缓存。
            fx = snapshot(json.loads((ROOT / "data" / "fx_latest.json").read_text(encoding="utf-8")))
            results["build"] = build_public_site(ROOT, fx)
            data = json.loads((SITE / "data" / "site-data.json").read_text(encoding="utf-8"))
        results["product_count"] = len(data["catalog"]["items"])
        results["offer_count"] = data["catalog"]["offer_count"]
        if base:
            exercise(base, data, results)
        else:
            with public_server() as (preview_base, responses):
                results["url"] = preview_base
                try:
                    exercise(preview_base, data, results)
                finally:
                    results["server_responses"] = responses
            results["temporary_server_closed"] = True
        results["ok"] = True
    except Exception as error:
        results["error"] = f"{type(error).__name__}: {error}"
        results["traceback"] = traceback.format_exc()
        raise
    finally:
        target = OUTPUT / f'{results["artifact_prefix"]}results.json'
        target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": results["ok"], "checks": results["checks"], "result": str(target),
                          "error": results.get("error")}, ensure_ascii=True))


if __name__ == "__main__":
    main()

