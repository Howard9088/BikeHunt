"""独立 Mock 验收：python tests/test_feature_flows.py，所有数据仅在临时目录。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.catalog.models import Evidence, Money
from app.catalog.service import compare_offer
from app.catalog.storage import atomic_json
from app.localization import category_of, title_zh
from app.notifications import PersonalNotifier
from app.policies import PolicyRepository
from app.source_rules import apply_source_rules
from app.updates import UpdateStore
from test_catalog import NOW, make_fx, make_offer


class FeatureFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_card_networks_allow_china_issued_cards_without_bank_name_whitelist(self):
        row = make_offer(china_issued_card=Evidence(), accepted_card_networks=["Visa", "Mastercard"],
                         card_networks_evidence=Evidence(status="yes", url="https://example.org/payment", checked_at=NOW))
        self.assertTrue(compare_offer(row, make_fx(), NOW).eligible)
        self.assertEqual(row.china_issued_card.status, "unknown")  # 不能伪造银行实测

    def test_explicit_issuer_restriction_overrides_supported_networks(self):
        row = make_offer(china_issued_card=Evidence(status="no"), accepted_card_networks=["Visa"],
                         card_networks_evidence=Evidence(status="yes", url="https://example.org", checked_at=NOW))
        self.assertFalse(compare_offer(row, make_fx(), NOW).eligible)

    def test_unknown_or_stale_networks_cannot_claim_payment_support(self):
        for check, networks in [(Evidence(), ["Visa"]),
                                (Evidence(status="yes", url="https://example.org", checked_at=NOW-timedelta(days=31)), ["Visa"]),
                                (Evidence(status="yes", url="https://example.org", checked_at=NOW), ["Apple Pay"])]:
            row = make_offer(china_issued_card=Evidence(), accepted_card_networks=networks, card_networks_evidence=check)
            self.assertFalse(compare_offer(row, make_fx(), NOW).eligible)

    def capture_rule(self, text="China shipping 47.95 EUR. " * 8, key="shipping"):
        repo = PolicyRepository(self.root)
        doc = repo.capture("a", "Mock", key, "中文规则", "https://example.org/policy", text, NOW)
        repo.translate("a", key, doc.content_hash, ["仅为 Mock 中国配送规则。"])
        return repo, doc

    def test_policy_same_body_keeps_version_changed_body_requires_new_translation(self):
        repo, doc = self.capture_rule()
        same = repo.capture("a", "Mock", "shipping", "中文规则", doc.url, "China shipping 47.95 EUR. " * 8, NOW)
        self.assertEqual(same.state, "translated")
        self.assertEqual(repo.get("a").version, 1)
        changed = repo.capture("a", "Mock", "shipping", "中文规则", doc.url, "China shipping 59.95 EUR. " * 8, NOW)
        self.assertEqual(changed.state, "changed")
        self.assertEqual(repo.get("a").version, 2)
        self.assertEqual(len(list((self.root/"storage/policy_history/a").glob("*.json"))), 2)
        with self.assertRaises(ValueError):
            repo.translate("a", "shipping", doc.content_hash, ["旧译文不能覆盖新规则。"])

    def test_title_only_and_english_translation_are_rejected(self):
        repo, doc = self.capture_rule()
        with self.assertRaises(ValueError):
            repo.capture("a", "Mock", "shipping", "标题", doc.url, "Title only", NOW)
        with self.assertRaises(ValueError):
            repo.translate("a", "shipping", doc.content_hash, ["English only"])

    def test_policy_change_invalidates_cached_shipping_cost(self):
        repo, doc = self.capture_rule()
        source = {"china_shipping":{"status":"yes", "checked_at":NOW.isoformat(), "evidence_url":doc.url,
                                    "content_hash":doc.content_hash},
                  "china_shipping_cost":{"amount":"47.95", "currency":"EUR"}}
        cached = make_offer(shipping_to_china=Evidence(status="yes", url=doc.url, checked_at=NOW, scope="site"))
        self.assertEqual(apply_source_rules(cached, source, self.root/"data").shipping.amount, Money(amount="47.95", currency="EUR").amount)
        repo.capture("a", "Mock", "shipping", "标题", doc.url, "China no longer available. "*8, NOW)
        degraded = apply_source_rules(cached, source, self.root/"data")
        self.assertEqual(degraded.shipping_to_china.status, "unknown")
        self.assertIsNone(degraded.shipping)

    def test_real_price_change_only_and_new_offer_not_fake_discount(self):
        store = UpdateStore(self.root)
        old = make_offer()
        self.assertEqual(store.capture([old], [old.model_copy(update={"fetched_at":NOW+timedelta(seconds=1)})]), [])
        changed = make_offer(price="80", fetched_at=NOW+timedelta(seconds=2))
        event = store.capture([old], [changed])[0]
        self.assertEqual((event["kind"], event["old_price"], event["new_price"]), ("price_changed", "100", "80"))
        self.assertEqual(store.capture([old], [changed]), [])
        new = store.capture([], [make_offer("b")])[0]
        self.assertEqual(new["kind"], "new_offer")
        self.assertIsNone(new["old_price"])
        self.assertEqual(store.capture([], [make_offer("legacy", fetched_at=None)]), [])

    def test_same_price_inventory_change_is_published_once(self):
        store = UpdateStore(self.root)
        old = make_offer()
        sold = make_offer(stock="out_of_stock", fetched_at=NOW+timedelta(seconds=1))
        event = store.capture([old], [sold])[0]
        self.assertEqual(event["kind"], "inventory_changed")
        self.assertEqual(event["stock"], "out_of_stock")
        self.assertEqual(store.capture([old], [sold]), [])

    def test_unchanged_translated_rules_use_latest_check_date(self):
        repo, doc = self.capture_rule()
        old_date = NOW-timedelta(days=40)
        source = {"rules_code":"a", "china_shipping":{"status":"yes", "checked_at":old_date.isoformat(),
                  "evidence_url":doc.url, "content_hash":doc.content_hash}}
        repo.capture("a", "Mock", "shipping", "标题", doc.url, "China shipping 47.95 EUR. "*8, NOW)
        offer = make_offer(source_code="regional")
        self.assertEqual(apply_source_rules(offer, source, self.root/"data").shipping_to_china.checked_at, NOW)

    def notifier(self, request=None):
        return PersonalNotifier(self.root, request=request or Mock(), fx_loader=make_fx)

    def bind_mock(self, notifier, device="mock-device", categories=None):
        notifier.configure("AT_mock_private_token")
        notifier.save_preferences(device, categories or ["all"], True)
        with notifier.events.connect() as db:
            db.execute("UPDATE subscribers SET uid=? WHERE device=?", ("UID_mock", device))

    def test_not_configured_not_bound_not_opted_in_never_sends(self):
        request = Mock()
        notifier = self.notifier(request)
        notifier.events.capture([], [make_offer()])
        notifier.dispatch()
        self.assertFalse(notifier.create_binding("mock")["configured"])
        notifier.configure("AT_mock_private_token")
        notifier.preferences("mock")
        notifier.dispatch()
        request.assert_not_called()

    def test_qr_creation_caches_and_polling_is_at_least_ten_seconds(self):
        request = Mock(side_effect=[{"data":{"url":"https://wxpusher.zjiecode.com/qr/mock.png", "code":"mock"}},
                                    {"data":None}, {"data":"UID_mock"}])
        notifier = self.notifier(request)
        notifier.configure("AT_mock_private_token")
        notifier.preferences("mock")
        notifier.create_binding("mock")
        notifier.create_binding("mock")
        self.assertEqual(request.call_count, 1)
        with patch("app.notifications.time.time", return_value=1000):
            notifier.binding_status("mock")
            notifier.binding_status("mock")
        self.assertEqual(request.call_count, 2)
        with patch("app.notifications.time.time", return_value=1011):
            self.assertTrue(notifier.binding_status("mock")["bound"])
        self.assertTrue(notifier.preferences("mock")["enabled"])
        self.assertFalse((self.root/"data/notifications.json").exists())

    def test_push_is_category_filtered_converted_and_idempotent(self):
        request = Mock(return_value={"data":[{"code":1000, "sendRecordId":123}]})
        notifier = self.notifier(request)
        self.bind_mock(notifier, categories=["jerseys"])
        notifier.events.capture([], [make_offer("helmet", name="POC Ventral Air Mips CPSC"), make_offer("jersey")])
        notifier.dispatch()
        notifier.dispatch()
        self.assertEqual(request.call_count, 1)
        content = request.call_args.args[2]["content"]
        self.assertIn("人民币 700.00 元", content)
        self.assertNotIn("POC", content)
        with notifier.events.connect() as db:
            self.assertEqual(db.execute("SELECT state FROM deliveries").fetchone()[0], "queued")

    def test_ambiguous_send_not_automatically_duplicated(self):
        request = Mock(side_effect=TimeoutError())
        notifier = self.notifier(request)
        self.bind_mock(notifier)
        notifier.events.capture([], [make_offer()])
        notifier.dispatch()
        notifier.dispatch()
        self.assertEqual(request.call_count, 1)
        self.assertFalse(request.call_args.kwargs["allow_ambiguous_retry"])
        with notifier.events.connect() as db:
            self.assertEqual(db.execute("SELECT state FROM deliveries").fetchone()[0], "delivery_unknown")

    def test_two_devices_for_same_uid_do_not_duplicate_the_same_message(self):
        request = Mock(return_value={"data":[{"code":1000}]})
        notifier = self.notifier(request)
        self.bind_mock(notifier, "device-a")
        self.bind_mock(notifier, "device-b")
        notifier.events.capture([], [make_offer()])
        notifier.dispatch()
        self.assertEqual(request.call_count, 1)

    def test_more_than_one_batch_keeps_earliest_unprocessed_events(self):
        request = Mock(return_value={"data":[{"code":1000}]})
        notifier = self.notifier(request)
        self.bind_mock(notifier)
        notifier.events.capture([], [make_offer(str(index)) for index in range(105)])
        notifier.dispatch()
        self.assertEqual(notifier.events.pending(100)[0]["id"], 101)
        notifier.dispatch()
        self.assertEqual(request.call_count, 2)

    def test_chinese_names_and_product_types(self):
        self.assertEqual(category_of("POC Ventral Air Mips CPSC Uranium Black Matt"), "helmets")
        self.assertIn("骑行头盔", title_zh("POC Ventral Air Mips CPSC Uranium Black Matt"))
        self.assertIn("男款骑行上衣", title_zh("Cycling jersey men 2026"))
        self.assertEqual(category_of("Team Bib Evo"), "bibs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
