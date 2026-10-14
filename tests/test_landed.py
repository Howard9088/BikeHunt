"""Landed-budget regressions: no network, purchase, or live-data mutations."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.catalog.models import Evidence, FxSnapshot, Money, Offer, ProductIdentity
from app.catalog.service import ComparisonCatalog, compare_offer
from app.landed import estimate_landed_cost

NOW = datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc)
SHIPPING_URL = "https://www.teamvismaleaseabike.com/shop-delivery/"


def quote(**updates) -> Offer:
    values = dict(
        offer_id="test-visma-M", source_code="visma", source_name="Visma",
        identity=ProductIdentity(brand="Visma", model="Jersey", size="M", color="Yellow"),
        name="Cycling jersey men 2026", url="https://www.teamvismaleaseabike.com/shop/test/",
        price=Money(amount="100", currency="USD"), shipping=Money(amount="47.95", currency="EUR"),
        fetched_at=NOW, stock="in_stock",
        shipping_to_china=Evidence(status="yes", url=SHIPPING_URL, checked_at=NOW, scope="site"),
        china_issued_card=Evidence(status="yes", url="https://example.org/payment", checked_at=NOW),
    )
    values.update(updates)
    return Offer(**values)


def rates(**updates) -> FxSnapshot:
    values = dict(snapshot_id="test-landed-fx", rates={"CNY": Decimal(1), "USD": Decimal(7), "EUR": Decimal(8)},
                  rate_date="2026-10-14", fetched_at=NOW)
    values.update(updates)
    return FxSnapshot(**values)


def tax_evidence(**updates) -> Evidence:
    values = dict(status="yes", url="https://example.org/china-checkout", checked_at=NOW)
    values.update(updates)
    return Evidence(**values)


class LandedCostTests(unittest.TestCase):
    def test_mixed_currency_components_preserve_originals_and_one_snapshot(self):
        result = compare_offer(quote(), rates(), NOW)
        landed = result.landed_cost
        self.assertEqual(result.product_cny, Decimal("700.00"))
        self.assertEqual(result.shipping_cny, Decimal("383.60"))
        self.assertEqual(landed.known_subtotal_cny, Decimal("1083.60"))
        self.assertEqual(landed.scenarios[0].tax_base_cny, Decimal("700.00"))
        self.assertEqual(landed.scenarios[0].payable_tax_cny, Decimal("140.00"))
        self.assertEqual(landed.scenarios[0].subtotal_cny, Decimal("1223.60"))
        self.assertEqual([c.original.currency for c in landed.components[:2]], ["USD", "EUR"])
        self.assertEqual(result.fx_snapshot_id, landed.fx_snapshot_id)
        self.assertEqual(landed.shipping_scope, "order")
        self.assertEqual(landed.quantity, 1)

    def test_scenario_never_becomes_confirmed_tax_total_or_recommendation(self):
        offer = quote()
        result = compare_offer(offer, rates(), NOW)
        self.assertIsNone(result.tax_cny)
        self.assertIsNone(result.total_cny)
        self.assertFalse(result.eligible)
        self.assertFalse(result.landed_cost.complete)
        self.assertIn("中国进口税／实际报关路径", result.landed_cost.missing)
        self.assertIn("清关／承运商代垫手续费", result.landed_cost.missing)
        store = ComparisonCatalog([offer], rates(), NOW)
        card = store.search()[0]
        self.assertIsNone(card.recommended_total_cny)
        self.assertIsNone(store.compare(card.product_id).recommended_offer_id)

    def test_policy_fallback_needs_matching_fresh_direct_shipping_evidence(self):
        landed = estimate_landed_cost(quote(shipping=None), rates(), NOW)
        shipping = landed.components[1]
        self.assertEqual(shipping.original, Money(amount="47.95", currency="EUR"))
        self.assertEqual(shipping.status, "policy_estimate")
        for check in [Evidence(), Evidence(status="no"),
                      tax_evidence(url="https://example.org/unrelated"),
                      tax_evidence(url=SHIPPING_URL, checked_at=NOW-timedelta(days=31))]:
            with self.subTest(check=check):
                result = estimate_landed_cost(quote(shipping=None, shipping_to_china=check), rates(), NOW)
                self.assertIsNone(result.components[1].cny)
                self.assertEqual(result.scenarios, [])

    def test_unknown_shipping_and_tax_are_null_not_zero(self):
        result = compare_offer(quote(source_code="unknown", shipping=None, shipping_to_china=Evidence()), rates(), NOW)
        self.assertIsNone(result.shipping_cny)
        self.assertIsNone(result.tax_cny)
        self.assertEqual(result.landed_cost.known_subtotal_cny, Decimal("700.00"))
        self.assertEqual(result.landed_cost.scenarios, [])
        self.assertIsNone(result.landed_cost.components[3].cny)

    def test_unsupported_channels_do_not_gain_shipping_or_tax_estimates(self):
        for code in ["maap", "teamcycles", "sigmasports", "poc"]:
            with self.subTest(code=code):
                result = compare_offer(quote(source_code=code, shipping_to_china=Evidence(status="no")), rates(), NOW)
                self.assertIsNone(result.shipping_cny)
                self.assertEqual(result.landed_cost.components[1].status, "unsupported")
                self.assertEqual(result.landed_cost.scenarios, [])
                self.assertFalse(result.eligible)

    def test_rapha_regional_tax_is_not_china_import_tax(self):
        for code in ["rapha", "rapha_kr"]:
            result = compare_offer(quote(source_code=code, shipping=None, shipping_to_china=Evidence()), rates(), NOW)
            self.assertIsNone(result.tax_cny)
            self.assertEqual(result.landed_cost.scenarios, [])
            self.assertIn("境外站点含税价不等于已包含中国进口税", result.landed_cost.components[2].note)

    def test_included_tax_is_not_added_twice(self):
        result = compare_offer(quote(import_tax_handling="included_in_price", import_tax_evidence=tax_evidence(),
                                     tax=Money(amount="20", currency="USD"), clearance=Money(amount=0, currency="CNY")), rates(), NOW)
        self.assertEqual(result.tax_cny, Decimal("0.00"))
        self.assertEqual(result.total_cny, Decimal("1083.60"))
        self.assertEqual(result.landed_cost.scenarios, [])
        self.assertEqual(result.landed_cost.components[2].status, "included")
        self.assertEqual(result.landed_cost.components[2].original.amount, Decimal(20))

    def test_prepaid_separate_tax_is_added_exactly_once(self):
        result = compare_offer(quote(import_tax_handling="prepaid_separately", import_tax_evidence=tax_evidence(),
                                     tax=Money(amount="5", currency="USD"), clearance=Money(amount=0, currency="CNY")), rates(), NOW)
        self.assertEqual(result.tax_cny, Decimal("35.00"))
        self.assertEqual(result.total_cny, Decimal("1118.60"))
        self.assertEqual(result.landed_cost.scenarios, [])

    def test_unverified_or_stale_ddp_neither_creates_free_tax_nor_duplicates_it(self):
        for handling in ["included_in_price", "prepaid_separately"]:
            for check in [Evidence(), tax_evidence(checked_at=NOW-timedelta(days=31)),
                          tax_evidence(checked_at=NOW+timedelta(seconds=1))]:
                with self.subTest(handling=handling, check=check):
                    result = compare_offer(quote(import_tax_handling=handling, import_tax_evidence=check,
                                                 tax=Money(amount="20", currency="USD")), rates(), NOW)
                    self.assertIsNone(result.tax_cny)
                    self.assertIsNone(result.total_cny)
                    self.assertEqual(result.landed_cost.scenarios, [])
                    self.assertFalse(result.eligible)

    def test_prepaid_tax_with_missing_amount_stays_unknown(self):
        result = compare_offer(quote(import_tax_handling="prepaid_separately", import_tax_evidence=tax_evidence()), rates(), NOW)
        self.assertIsNone(result.tax_cny)
        self.assertEqual(result.landed_cost.scenarios, [])

    def test_explicit_zero_tax_stays_zero_but_visma_clearance_stays_unknown(self):
        result = compare_offer(quote(tax=Money(amount=0, currency="CNY")), rates(), NOW)
        self.assertEqual(result.tax_cny, Decimal("0.00"))
        self.assertEqual(result.landed_cost.scenarios, [])
        self.assertIsNone(result.total_cny)
        self.assertFalse(result.eligible)

    def test_waiver_is_whole_parcel_threshold_not_a_fifty_yuan_deduction(self):
        for price, payable, exempt in [("245", "0", True), ("250", "0", True),
                                       ("250.01", "50.00", False), ("251", "50.20", False),
                                       ("1000", "200.00", False)]:
            with self.subTest(price=price):
                scenario = estimate_landed_cost(quote(price=Money(amount=price, currency="CNY")), rates(), NOW).scenarios[0]
                self.assertEqual(scenario.payable_tax_cny, Decimal(payable))
                self.assertEqual(scenario.waiver_applied, exempt)
                self.assertTrue(any("合单" in assumption for assumption in scenario.assumptions))

    def test_personal_parcel_value_boundary_requires_review_above_limit(self):
        equal = estimate_landed_cost(quote(price=Money(amount="2000", currency="CNY")), rates(), NOW)
        self.assertEqual(equal.scenarios[0].payable_tax_cny, Decimal("400.00"))
        above = estimate_landed_cost(quote(price=Money(amount="2000.01", currency="CNY")), rates(), NOW)
        self.assertEqual(above.scenarios, [])
        self.assertTrue(any("不可分割单件" in note and "海关审核" in note for note in above.notes))

    def test_no_clothing_rate_for_helmets_shoes_electronics_or_mixed_sets(self):
        for name in ["Road helmet", "Cycling shoes", "GPS bike computer", "Jersey and bottle bundle", "Jersey kit", "Electronic heated vest", "Socks"]:
            with self.subTest(name=name):
                result = estimate_landed_cost(quote(name=name), rates(), NOW)
                self.assertEqual(result.scenarios, [])
                self.assertIsNone(result.components[2].cny)

    def test_missing_fx_is_never_a_zero_cost(self):
        for fx in [rates(rates={"CNY": Decimal(1), "USD": Decimal(7)}),
                   rates(rates={"CNY": Decimal(1), "EUR": Decimal(8)})]:
            result = compare_offer(quote(), fx, NOW)
            self.assertEqual(result.landed_cost.scenarios, [])
            self.assertIsNone(result.total_cny)
            self.assertFalse(result.eligible)

    def test_stale_fx_cannot_rank_the_estimate_as_recommended(self):
        result = compare_offer(quote(), rates(stale=True), NOW)
        self.assertFalse(result.eligible)
        self.assertIn("汇率为过期缓存", result.reasons)

    def test_expired_rule_review_stops_automatic_scenarios(self):
        later = NOW + timedelta(days=31)
        result = estimate_landed_cost(quote(shipping_to_china=tax_evidence(url=SHIPPING_URL, checked_at=later)), rates(), later)
        self.assertEqual(result.scenarios, [])
        self.assertTrue(any("复核期限" in note for note in result.notes))

    def test_explicit_clearance_contributes_once_and_retains_currency(self):
        landed = estimate_landed_cost(quote(clearance=Money(amount="2", currency="EUR")), rates(), NOW)
        self.assertEqual(landed.known_subtotal_cny, Decimal("1099.60"))
        self.assertEqual(landed.scenarios[0].subtotal_cny, Decimal("1239.60"))
        self.assertEqual(landed.components[3].original.currency, "EUR")

    def test_rules_and_currency_evidence_survive_json_serialization(self):
        result = compare_offer(quote(), rates(), NOW).model_dump(mode="json")
        landed = result["landed_cost"]
        self.assertEqual(landed["components"][1]["original"], {"amount": "47.95", "currency": "EUR"})
        self.assertEqual(landed["scenarios"][0]["evidence"][0]["checked_on"], "2026-10-14")
        self.assertEqual(landed["scenarios"][0]["rate"], "0.20")
        self.assertTrue(all(s["code"] != "cbec" for s in landed["scenarios"]))
        self.assertTrue(any("不能自动套用 9.1%" in note for note in landed["notes"]))
        self.assertTrue(any("VAT" in note and "不自动扣除" in note for note in landed["notes"]))

    @unittest.skipUnless(shutil.which("node"), "Node is required for the UI rendering check")
    def test_breakdown_ui_renders_partial_labels_and_escapes_content(self):
        payload = compare_offer(quote(), rates(), NOW).model_dump(mode="json")
        payload["landed_cost"]["notes"].append('<img src=x onerror="bad()">')
        source = Path(__file__).resolve().parents[1] / "web" / "gallery.js"
        program = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const js=fs.readFileSync(process.argv[1],'utf8');
const helpers=js.slice(js.indexOf('const e='),js.indexOf('function timeText('));
const renderer=js.slice(js.indexOf('function landedCostMarkup('),js.indexOf('function offerAvailable('));
const ctx={Intl,URL,Map,Math,Number,String};vm.createContext(ctx);vm.runInContext(helpers+renderer,ctx);
const payload=JSON.parse(fs.readFileSync(0,'utf8'));
const html=ctx.landedCostMarkup(payload);
for(const text of ['条件估算','实际报关路径未确认','不能视为完整到手价','未知费用没有按 0 元','€47.95','2026-10-14'])assert.ok(html.includes(text),text);
assert.ok(!html.includes('<img src=x'));assert.ok(html.includes('&lt;img'));
assert.ok(!html.includes('预计总成本'));
"""
        subprocess.run(["node", "-e", program, str(source)], input=json.dumps(payload), text=True,
                       capture_output=True, check=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
