"""Shared browser assertions for the final, same-tab external-exit modal.

These checks exercise the rendered controls rather than accepting a native
``window.confirm`` event, so a missing or bypassed confirmation cannot pass.
"""
from urllib.parse import urlparse

from playwright.sync_api import expect

DISCLAIMER = '本站仅提供商品与优惠信息，不参与交易。价格、库存、尺码及折扣可能变化，信息不保证完全准确，请以实际商家页面及结算信息为准，并在购买前自行核实。购买、付款、配送、退换货，以及买错商品或尺码不合适等问题，请直接联系实际商家。法律规定本站应承担的责任除外。'


def assert_exit_closed(page):
    """The element may be retained after closing, but must never be open early."""
    expect(page.locator('#externalExitDialog[open]')).to_have_count(0)


def assert_exit_layout(page):
    dialog = page.locator('#externalExitDialog')
    assert dialog.evaluate('el => el.scrollWidth <= el.clientWidth + 1'), 'Exit modal overflows horizontally'
    for region in dialog.locator('.external-exit-scroll, .external-exit-content, .external-exit-actions').all():
        assert region.evaluate('el => el.scrollWidth <= el.clientWidth + 1'), 'Exit content overflows horizontally'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Page overflows horizontally'
    box = dialog.bounding_box()
    viewport = page.viewport_size
    assert box and viewport
    assert box['x'] >= -1 and box['x'] + box['width'] <= viewport['width'] + 1, box
    assert box['y'] >= -1 and box['y'] + box['height'] <= viewport['height'] + 1, box


def assert_exit_dialog(page, target, *, official=False, image=None):
    dialog = page.locator('#externalExitDialog')
    expect(dialog).to_be_visible()
    expect(dialog).to_have_attribute('open', '')
    assert dialog.evaluate("el => el.tagName === 'DIALOG' && el.matches(':modal')"), 'Exit must be a modal HTML dialog'
    expect(page.locator('#externalExitDomain')).to_have_text(urlparse(target).hostname)
    points = page.locator('#externalExitPoints > li')
    expect(points).to_have_count(4)
    expect(page.locator('#externalExitPoints > li .external-exit-number')).to_have_text(['1', '2', '3', '4'])
    for point, required in zip(points.all(), ['不参与交易', '核对浏览器地址栏中的域名', '重定向、第三方链接、访问环境及用户操作', '法律规定本站应承担的责任除外']):
        expect(point).to_be_visible()
        expect(point).to_contain_text(required)
    expect(points.nth(1)).to_contain_text('警惕仿冒网站')
    expect(page.locator('#externalExitPoints > .external-exit-important')).to_have_count(1)
    expect(points.nth(1)).to_have_class('external-exit-important')
    expect(points.nth(1)).to_contain_text('重点提醒')
    expect(points.nth(1).locator('strong')).to_have_text('请始终核对浏览器地址栏中的域名，警惕仿冒网站。')
    assert points.nth(1).locator('p').evaluate('(node) => getComputedStyle(node).color') == 'rgb(145, 32, 24)'
    assert int(points.nth(1).locator('strong').evaluate('(node) => getComputedStyle(node).fontWeight')) >= 700
    expect(points.nth(2)).to_contain_text('发现异常请停止访问或操作')
    expect(page.locator('#externalExitCancel')).to_have_text('取消')
    expect(page.locator('#externalExitConfirm')).to_have_text('确认并前往官网' if official else '确认并前往目标网站')
    expect(page.locator('#externalExitConfirm')).to_be_enabled()
    details = dialog.locator('details').filter(has_text=DISCLAIMER)
    expect(details).to_have_count(1)
    expect(details).to_contain_text(DISCLAIMER)
    if image is not None:
        expect(page.locator('#externalExitImage')).to_have_attribute('src', image)
    assert_exit_layout(page)
    return dialog


def open_final_exit(page, target, *, official=False, image=None, **click_options):
    assert_exit_closed(page)
    page.locator('#registrationContinue').click(**click_options)
    return assert_exit_dialog(page, target, official=official, image=image)


def cancel_exit_dialog(page, *, escape=False):
    expect(page.locator('#externalExitDialog')).to_be_visible()
    if escape:
        page.keyboard.press('Escape')
    else:
        page.locator('#externalExitCancel').click()
    assert_exit_closed(page)


def confirm_exit_dialog(page, target, *, official=False):
    assert_exit_dialog(page, target, official=official)
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#externalExitConfirm').click()
    expect(page).to_have_url(target)


def assert_exit_focus_trap(page):
    """Both traversal directions stay inside the modal, including at the ends."""
    dialog = page.locator('#externalExitDialog')
    assert dialog.evaluate('el => el.contains(document.activeElement)'), 'Focus must enter the exit modal'
    focusable = dialog.locator('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex="0"]').filter(visible=True)
    assert focusable.count() >= 3, 'Cancel, confirmation and disclosure must remain keyboard accessible'
    focusable.last.focus()
    page.keyboard.press('Tab')
    expect(focusable.first).to_be_focused()
    page.keyboard.press('Shift+Tab')
    expect(focusable.last).to_be_focused()
    for key in ['Tab', 'Shift+Tab']:
        for _ in range(focusable.count() + 2):
            page.keyboard.press(key)
            assert dialog.evaluate('el => el.contains(document.activeElement)'), f'{key} escaped the exit modal'
