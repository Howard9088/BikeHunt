"""Buyer-facing payment copy must not expose implementation diagnostics."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class PublicPaymentCopyTests(unittest.TestCase):
    def test_payment_and_shipping_copy_uses_buyer_language(self):
        for name in ('payment-methods.js', 'purchase-readiness.js'):
            text = (ROOT / 'web' / name).read_text(encoding='utf-8')
            for phrase in ('读取或校验', '旧卡种字段', '旧卡种记录', '读取本地配送摘要',
                           '证据层级：', '取证限制：', '未实测注册、绑卡或付款',
                           '没有实测注册、绑卡或付款'):
                self.assertNotIn(phrase, text, (name, phrase))
        payment = (ROOT / 'web/payment-methods.js').read_text(encoding='utf-8')
        self.assertIn('支付说明暂时无法加载', payment)
        self.assertIn('卡组织支持不等于中国发行卡获批', payment)
        self.assertIn('官方明确不支持', payment)
        shipping = (ROOT / 'web/purchase-readiness.js').read_text(encoding='utf-8')
        self.assertIn('未确认的费用不按 0 计算', shipping)
        self.assertIn('明确禁止时不要使用', shipping)

    def test_published_method_descriptions_have_no_parser_diagnostics(self):
        data = json.loads((ROOT / 'web/payment-methods.json').read_text(encoding='utf-8'))
        visible = []
        for entry in data['entries']:
            visible.append(entry.get('scope_note', ''))
            for method in entry['methods']:
                visible.extend(str(method.get(key, '')) for key in
                               ('note', 'account_region_constraints'))
        for text in visible:
            for phrase in ('HTTP404', 'HTML 中为隐藏模板', '空篮隐藏模板',
                           'Shopify或PayPal脚本配置'):
                self.assertNotIn(phrase, text)
