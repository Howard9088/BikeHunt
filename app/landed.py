"""Mainland-China budgeting: explicit charges and conditional tax stay separate.

No generic overseas-site tax rate, guessed delivery fee, or implicit free fee.
This is a one-item/order illustration, not a customs or checkout quotation.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

from app.catalog.models import (
    CostComponent, CostEvidence, Evidence, FxSnapshot, LandedCost, Money, Offer, TaxScenario,
)
from app.localization import category_of

RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "landed_cost_rules.json"
CENT = Decimal("0.01")


def convert_money(value: Money | None, fx: FxSnapshot) -> Decimal | None:
    if value is None:
        return None
    rate = fx.rates.get(value.currency)
    if rate is None or not rate.is_finite() or rate <= 0:
        return None
    return (value.amount * rate).quantize(CENT, rounding=ROUND_HALF_UP)


@lru_cache(maxsize=1)
def load_rules() -> dict:
    try:
        rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        return rules if isinstance(rules, dict) else {}
    except (OSError, ValueError):
        return {}


def _fresh(check: Evidence, now: datetime) -> bool:
    return (check.status == "yes" and check.checked_at is not None
            and check.checked_at.tzinfo is not None
            and 0 <= (now - check.checked_at).total_seconds() <= 30 * 86400)


def _rules_fresh(rules: dict, now: datetime) -> bool:
    try:
        age = (now.date() - date.fromisoformat(rules["checked_on"])).days
        return 0 <= age <= int(rules["review_after_days"])
    except (KeyError, TypeError, ValueError):
        return False


def _evidence(check: Evidence, title: str) -> list[CostEvidence]:
    if not check.url:
        return []
    return [CostEvidence(title=title, url=check.url,
                         checked_on=check.checked_at.date().isoformat() if check.checked_at else None)]


def _clothing(name: str, rule: dict) -> bool:
    # Product browsing categories are not tariff classifications. Exclude mixed
    # sets/accessories even when their titles contain a garment keyword.
    excluded = r"\b(helmet|shoe\w*|computer|electronic\w*|bottle|bundle|pack|kit|socks?|gloves?)\b|头盔|锁鞋|电子|套装"
    return category_of(name) in rule.get("categories", []) and not re.search(excluded, name, re.I)


def estimate_landed_cost(offer: Offer, fx: FxSnapshot, now: datetime) -> LandedCost:
    rules = load_rules()
    current_rules = _rules_fresh(rules, now)
    policy = rules.get("shipping", {}).get(offer.source_code, {})
    policy_current = bool(policy and current_rules and _fresh(offer.shipping_to_china, now)
                          and offer.shipping_to_china.url == policy.get("url"))
    notes = ["按一件商品单独下单估算；参考汇率不等于银行卡入账汇率。未知费用保留待确认。"]
    missing: list[str] = []
    evidence: list[CostEvidence] = []
    product = convert_money(offer.price, fx)
    components = [CostComponent(key="product", label="商品价", original=offer.price,
                               cny=product, status="quoted", evidence=[CostEvidence(
                                   title="商品原价与原币种", url=offer.url,
                                   checked_on=offer.fetched_at.date().isoformat() if offer.fetched_at else None)])]
    if product is None:
        missing.append("商品币种汇率")

    shipping_money = offer.shipping if offer.shipping_to_china.status != "no" else None
    shipping_status = "quoted" if shipping_money is not None else "unknown"
    shipping_note = "中国大陆运费须由商家按目的地确认；未知不按免运费处理。"
    if policy_current:
        shipping_note = policy["note"]
        evidence.append(CostEvidence(title="商家中国大陆整单运费", url=policy["url"],
                                     checked_on=policy["checked_on"]))
        if shipping_money is None:
            shipping_money = Money(amount=policy["amount"], currency=policy["currency"])
            shipping_status = "policy_estimate"
        notes.append(policy["price_note"])
        evidence.append(CostEvidence(title="商家展示价与 VAT 条款", url=policy["terms_url"],
                                     checked_on=policy["checked_on"]))
    if offer.shipping_to_china.status == "no":
        shipping_status = "unsupported"
        shipping_note = "此渠道当前不支持直邮中国大陆；不假设可使用转运，也不估填转运费用。"
    shipping = convert_money(shipping_money, fx)
    components.append(CostComponent(key="shipping", label="寄中国运费（单件整单）",
                                   original=shipping_money, cny=shipping, status=shipping_status,
                                   note=shipping_note,
                                   evidence=_evidence(offer.shipping_to_china, "中国大陆配送依据")))
    if shipping is None:
        missing.append("中国大陆运费" if shipping_money is None else "运费币种汇率")

    handling = offer.import_tax_handling
    tax = convert_money(offer.tax, fx)
    tax_status = "quoted" if offer.tax is not None else "unknown"
    tax_note = "尚未取得中国大陆进口税费报价；境外站点含税价不等于已包含中国进口税。"
    if handling == "included_in_price":
        if _fresh(offer.import_tax_evidence, now):
            tax, tax_status = Decimal("0.00"), "included"
            tax_note = "有依据确认中国进口税已含在商品报价中，此处新增税费为 0，不重复加税。"
        else:
            tax, tax_status = None, "unknown"
            tax_note = "含中国进口税的依据缺失或过期，不能确认包税，也不能重复加计旧税额。"
    elif handling == "prepaid_separately":
        if not _fresh(offer.import_tax_evidence, now):
            tax, tax_status = None, "unknown"
            tax_note = "预缴中国进口税的依据缺失或过期，预缴金额待核实。"
        else:
            tax_note = "商家另行预收的中国进口税只加计一次；不再叠加行邮税情景。"
    elif offer.tax is not None:
        tax_note = "使用已记录的独立税费报价；不另外叠加估算税。"
    components.append(CostComponent(key="tax", label="中国进口税（已报价）", original=offer.tax,
                                   cny=tax, status=tax_status, note=tax_note,
                                   evidence=_evidence(offer.import_tax_evidence, "中国进口税预付／包含依据")))
    if tax is None:
        missing.append("中国进口税／实际报关路径")
    clearance = convert_money(offer.clearance, fx)
    components.append(CostComponent(key="clearance", label="清关／代垫手续费", original=offer.clearance,
                                   cny=clearance, status="quoted" if offer.clearance is not None else "unknown",
                                   note="商家或承运商未报价时不按 0 元处理。"))
    if clearance is None:
        missing.append("清关／承运商代垫手续费" if offer.clearance is None else "清关费用币种汇率")

    scenarios: list[TaxScenario] = []
    clothing_rule = rules.get("personal_postal_clothing", {})
    can_estimate = (current_rules and clothing_rule and _clothing(offer.name, clothing_rule)
                    and _fresh(offer.shipping_to_china, now) and product is not None
                    and shipping is not None and offer.tax is None and handling == "unknown")
    if can_estimate:
        limit = Decimal(clothing_rule["parcel_value_limit_cny"])
        if product <= limit:
            rate = Decimal(clothing_rule["rate"])
            raw_tax = product * rate
            assessed = raw_tax.quantize(CENT, rounding=ROUND_HALF_UP)
            waived = raw_tax <= Decimal(clothing_rule["parcel_tax_waiver_cny"])
            payable = Decimal("0.00") if waived else assessed
            scenarios.append(TaxScenario(
                code="personal_postal_clothing", label="若按个人寄递服装征税（未确认）", rate=rate,
                tax_base_cny=product, assessed_tax_cny=assessed, payable_tax_cny=payable,
                subtotal_cny=product + shipping + payable + (clearance if clearance is not None else Decimal(0)),
                waiver_applied=waived, assumptions=clothing_rule["assumptions"],
                evidence=[CostEvidence(**entry) for entry in clothing_rule["evidence"]]))
        else:
            notes.append("商品参考价已超过个人寄递 2,000 元限值，暂不套用服装税情景；不可分割单件超限须经海关审核，其他情形可能需按货物报关。")
    elif not current_rules:
        notes.append("运税估算规则缺失或超过复核期限，暂停自动税费情景。")
    elif not _clothing(offer.name, clothing_rule) and tax is None:
        notes.append("此商品未匹配已审核的服装情景；头盔、鞋、电子产品和其他配件不套用服装税率。")

    cbec = rules.get("cbec", {})
    if cbec.get("note"):
        notes.append(cbec["note"])
        evidence.extend(CostEvidence(**entry) for entry in cbec.get("evidence", []))
    known = sum((component.cny for component in components if component.cny is not None), Decimal(0)) if product is not None else None
    # Preserve the original explicit-quote contract. Known extra clearance must
    # be present; an estimate must NEVER fill the missing quoted tax value.
    explicit = all(value is not None for value in (product, shipping, tax))
    clearance_required = bool(policy.get("clearance_extra")) or offer.clearance is not None
    complete = bool(explicit and shipping_status != "policy_estimate"
                    and (not clearance_required or clearance is not None))
    quoted_total = known if complete else None
    return LandedCost(components=components, known_subtotal_cny=known,
                      quoted_total_cny=quoted_total, complete=complete,
                      shipping_scope="order" if policy_current else "unknown",
                      scenarios=scenarios, missing=missing, notes=notes, evidence=evidence,
                      fx_snapshot_id=fx.snapshot_id)
