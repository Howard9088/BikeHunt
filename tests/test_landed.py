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

NOW = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)
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

    def test_ef_hoodie_has_grounded_partial_estimate_without_shipping_or_route(self):
        offer = quote(source_code="ef_team_shop", name="Stamp Hoodie", shipping=None,
                      price=Money(amount="89", currency="USD"), shipping_to_china=Evidence())
        fx = rates(rates={"CNY": Decimal(1), "USD": Decimal("6.6927")})
        result = compare_offer(offer, fx, NOW)
        scenario = result.landed_cost.scenarios[0]
        self.assertEqual(result.product_cny, Decimal("595.65"))
        self.assertEqual(scenario.assessed_tax_cny, Decimal("119.13"))
        self.assertEqual(scenario.goods_and_tax_cny, Decimal("714.78"))
        self.assertEqual(scenario.subtotal_cny, Decimal("714.78"))
        self.assertEqual(scenario.included_components, ["product", "tax"])
        self.assertFalse(scenario.china_delivery_confirmed)
        self.assertIsNone(result.shipping_cny)
        self.assertIsNone(result.tax_cny)
        self.assertIsNone(result.total_cny)
        self.assertFalse(result.eligible)
        self.assertFalse(result.landed_cost.complete)
        self.assertIn("未明确列出中国大陆", result.landed_cost.components[1].note)
        self.assertTrue(any(x.url == "https://efprocycling.shop/us/shipping-policy/"
                            for x in result.landed_cost.evidence))
        catalog = ComparisonCatalog([offer], fx, NOW)
        card = catalog.search()[0]
        self.assertIsNone(card.recommended_total_cny)
        self.assertIsNone(catalog.compare(card.product_id).recommended_offer_id)

    def test_audited_casual_clothing_is_not_tied_to_browsing_category(self):
        for name in ["Stamp Hoodie", "Dispatched T-Shirt", "Team T shirt", "Team Tee", "Sweatshirt", "车队卫衣"]:
            with self.subTest(name=name):
                result = estimate_landed_cost(quote(name=name, shipping=None, source_code="ef_team_shop",
                                                     shipping_to_china=Evidence()), rates(), NOW)
                self.assertEqual(result.scenarios[0].payable_tax_cny, Decimal("140.00"))
        for name in ["Hoodie keyring", "T-shirt sticker", "Road helmet", "Cycling shoes", "GPS computer"]:
            with self.subTest(name=name):
                self.assertEqual(estimate_landed_cost(quote(name=name), rates(), NOW).scenarios, [])

    def test_explicit_zero_shipping_is_distinct_from_unknown_shipping(self):
        offer = quote(source_code="ef_team_shop", shipping=Money(amount=0, currency="CNY"))
        result = estimate_landed_cost(offer, rates(), NOW)
        self.assertEqual(result.components[1].cny, Decimal("0.00"))
        self.assertEqual(result.components[1].status, "quoted")
        self.assertIn("shipping", result.scenarios[0].included_components)
        self.assertNotIn("shipping", result.scenarios[0].missing_components)

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
                if check.status == "no":
                    self.assertEqual(result.scenarios, [])
                else:
                    self.assertEqual(result.scenarios[0].subtotal_cny, Decimal("840.00"))
                    self.assertIn("shipping", result.scenarios[0].missing_components)

    def test_unknown_shipping_and_tax_are_null_not_zero(self):
        result = compare_offer(quote(source_code="unknown", shipping=None, shipping_to_china=Evidence()), rates(), NOW)
        self.assertIsNone(result.shipping_cny)
        self.assertIsNone(result.tax_cny)
        self.assertEqual(result.landed_cost.known_subtotal_cny, Decimal("700.00"))
        scenario = result.landed_cost.scenarios[0]
        self.assertEqual(scenario.subtotal_cny, Decimal("840.00"))
        self.assertEqual(scenario.included_components, ["product", "tax"])
        self.assertEqual(scenario.missing_components, ["shipping", "clearance"])
        self.assertFalse(scenario.china_delivery_confirmed)
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
            self.assertEqual(result.landed_cost.scenarios[0].payable_tax_cny, Decimal("140.00"))
            self.assertFalse(result.landed_cost.scenarios[0].china_delivery_confirmed)
            self.assertIsNone(result.total_cny)
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
            if result.product_cny is None:
                self.assertEqual(result.landed_cost.scenarios, [])
            else:
                scenario = result.landed_cost.scenarios[0]
                self.assertEqual(scenario.subtotal_cny, Decimal("840.00"))
                self.assertIn("shipping", scenario.missing_components)
                self.assertNotIn("shipping", scenario.included_components)
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
        self.assertEqual(landed["scenarios"][0]["evidence"][0]["checked_on"], "2026-10-15")
        self.assertEqual(landed["scenarios"][0]["rate"], "0.20")
        self.assertTrue(all(s["code"] != "cbec" for s in landed["scenarios"]))
        self.assertTrue(any("不能自动套用 9.1%" in note for note in landed["notes"]))
        self.assertTrue(any("VAT" in note and "不自动扣除" in note for note in landed["notes"]))

    @unittest.skipUnless(shutil.which("node"), "Node is required for the UI rendering check")
    def test_ef_guide_step_three_reuses_partial_preview_without_a_full_total(self):
        offer = quote(source_code="ef_team_shop", name="Stamp Hoodie", shipping=None,
                      price=Money(amount="89", currency="USD"), shipping_to_china=Evidence())
        payload = compare_offer(offer, rates(rates={"USD": Decimal("6.6927")}), NOW).model_dump(mode="json")
        root = Path(__file__).resolve().parents[1]
        program = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const js=fs.readFileSync(process.argv[1],'utf8'),flows=fs.readFileSync(process.argv[2],'utf8');
const helpers=js.slice(js.indexOf('const e='),js.indexOf('function timeText('));
const renderer=js.slice(js.indexOf('function landedCostMarkup('),js.indexOf('function inventoryVerified('));
const guide=flows.slice(flows.indexOf('function renderGuide('),flows.indexOf('function updateGuideVerificationMetadata('));
const quote=JSON.parse(fs.readFileSync(0,'utf8'));
let html='';
const ctx={Intl,URL,Map,Math,Number,String,guideContext:{quote,detail:{identity:{size:'M'}},book:{documents:[]}},guideStep:2,
  offerAvailable:()=>true,guideMap:()=>'',openPanel:(_title,content)=>html=content,
  document:{getElementById:()=>({})}};
vm.createContext(ctx);vm.runInContext(helpers+renderer+guide,ctx);ctx.renderGuide();
for(const text of ['第 3 步','US$89.00','595.65','119.13','714.78','商品 + 预估税小计','寄中国运费','清关／代垫手续费','待确认','实际报关路径未确认','中国大陆配送仍待核实','不能视为完整到手价'])assert.ok(html.includes(text),text);
assert.ok(!html.includes('预计总成本'));assert.ok(!html.includes('商品 + 整单运费'));
assert.ok(html.indexOf('119.13')<html.indexOf('查看已报价费用'));
"""
        subprocess.run(["node", "-e", program, str(root / "web/gallery.js"), str(root / "web/flows.js")],
                       input=json.dumps(payload), text=True, capture_output=True, check=True)

    @unittest.skipUnless(shutil.which("node"), "Node is required for the UI rendering check")
    def test_optional_shipping_budget_is_local_validated_and_never_a_quote(self):
        offer = quote(source_code="ef_team_shop", name="Stamp Hoodie", shipping=None,
                      price=Money(amount="89", currency="USD"), shipping_to_china=Evidence())
        fx = rates(rates={"USD": Decimal("6.6927"), "CNY": Decimal(1), "EUR": Decimal(8)})
        payload = compare_offer(offer, fx, NOW).model_dump(mode="json")
        known = compare_offer(quote(), fx, NOW).model_dump(mode="json")
        unsupported = compare_offer(offer.model_copy(update={"shipping_to_china": Evidence(status="no")}), fx, NOW).model_dump(mode="json")
        ddp = compare_offer(offer.model_copy(update={"import_tax_handling": "included_in_price", "import_tax_evidence": tax_evidence()}), fx, NOW).model_dump(mode="json")
        source = Path(__file__).resolve().parents[1] / "web" / "gallery.js"
        program = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const js=fs.readFileSync(process.argv[1],'utf8');
const helpers=js.slice(js.indexOf('const e='),js.indexOf('function timeText('));
const renderer=js.slice(js.indexOf('function landedCostMarkup('),js.indexOf('function inventoryVerified('));
const ctx={Intl,URL,Map,Math,Number,String};vm.createContext(ctx);vm.runInContext(helpers+renderer,ctx);
const data=JSON.parse(fs.readFileSync(0,'utf8')),original=JSON.stringify(data),html=ctx.landedCostMarkup(data.unknown);
assert.ok(html.includes('data-shipping-budget type="text"'));assert.ok(html.includes('留空表示未知'));
assert.ok(!html.match(/data-shipping-budget[^>]*value=/));
for(const text of ['自己的运费预算','不是商家报价','未知清关／代垫手续费仍需另计','不代表商家免邮','中国大陆配送仍待核实'])assert.ok(html.includes(text),text);
for(const item of [data.known,data.unsupported,data.ddp])assert.ok(!ctx.landedCostMarkup(item).includes('data-shipping-budget type='));
const calc=raw=>ctx.shippingBudgetPreview(raw,'714.78');
for(const raw of ['', ' ',null,undefined])assert.equal(calc(raw).status,'empty');
for(const raw of ['-1','-0','NaN','Infinity','1e2','1e309','100000.01','1000000','999999999999999999','0.001','abc','<img src=x>'])assert.equal(calc(raw).status,'invalid',raw);
for(const [raw,amount,total] of [['0',0,714.78],['0.00',0,714.78],['120.50',120.5,835.28],['0.01',.01,714.79],['100000',100000,100714.78]]){
  const value=calc(raw);assert.equal(value.status,'valid');assert.equal(value.shipping_cny,amount);assert.equal(value.subtotal_cny,total);
}
for(const base of [null,'',NaN,Infinity,-1,'9007199254740992'])assert.equal(ctx.shippingBudgetPreview('100',base).status,'invalid');
// Exercise production event handling with DOM-shaped nodes. It changes only the
// local preview, leaving the quote, actual shipping, eligibility and evidence intact.
const nodes=Object.fromEntries(['error','result','shipping','subtotal','zero'].map(k=>[k,{textContent:'',hidden:true}]));
const box={dataset:{subtotal:'714.78'},querySelector:selector=>nodes[selector.slice(13,-1)]};
const attributes={};const input={value:'',matches:s=>s==='[data-shipping-budget]',closest:()=>box,setAttribute:(k,v)=>attributes[k]=v};
const edit=value=>{input.value=value;ctx.updateShippingBudget({target:input});};
edit('');assert.equal(nodes.result.hidden,true);assert.equal(nodes.subtotal.textContent,'');assert.equal(attributes['aria-invalid'],'false');
edit('120.50');assert.equal(nodes.result.hidden,false);assert.ok(nodes.subtotal.textContent.includes('835.28'));assert.ok(nodes.shipping.textContent.includes('120.50'));assert.equal(nodes.zero.hidden,true);
edit('0');assert.equal(nodes.zero.hidden,false);assert.ok(nodes.subtotal.textContent.includes('714.78'));
edit('-1');assert.equal(nodes.result.hidden,true);assert.equal(nodes.error.hidden,false);assert.equal(attributes['aria-invalid'],'true');assert.equal(nodes.subtotal.textContent,'');
edit('');assert.equal(nodes.result.hidden,true);assert.equal(nodes.error.hidden,true);assert.equal(nodes.subtotal.textContent,'');assert.equal(attributes['aria-invalid'],'false');
assert.equal(JSON.stringify(data),original);assert.equal(data.unknown.shipping_cny,null);assert.equal(data.unknown.total_cny,null);assert.equal(data.unknown.eligible,false);assert.equal(data.unknown.landed_cost.complete,false);
assert.equal(js.split("document.addEventListener('input',updateShippingBudget);").length-1,1);
"""
        subprocess.run(["node", "-e", program, str(source)],
                       input=json.dumps({"unknown": payload, "known": known, "unsupported": unsupported, "ddp": ddp}),
                       text=True, capture_output=True, check=True)

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
