"""将最新公开支付、配送条件覆盖到缓存报价，旧规则变化后立即降级。"""
from __future__ import annotations

import json
from pathlib import Path

from app.catalog.models import Evidence, Money, Offer
from app.collectors.parsers import evidence


def _current(entry: dict, key: str, source: str, data: Path) -> bool:
    digest = entry.get("content_hash")
    if not digest:
        return True
    try:
        book = json.loads((data / "rules" / f"{source}.json").read_text(encoding="utf-8"))
        doc = next(d for d in book["documents"] if d["key"] == key)
        return (doc["state"] == "translated" and doc["content_hash"] == digest
                and doc.get("translated_hash") == digest)
    except (OSError, ValueError, KeyError, StopIteration):
        return False


def _checked_evidence(source: dict, field: str, key: str, code: str, data: Path) -> Evidence:
    """同一份已翻译原文重新核查后，证据时间随原文核查时间更新。"""
    result = evidence(source, field)
    if not result.content_hash:
        return result
    try:
        book = json.loads((data / "rules" / f"{code}.json").read_text(encoding="utf-8"))
        doc = next(d for d in book["documents"] if d["key"] == key)
        return result.model_copy(update={"checked_at": Evidence.model_validate(
            {**result.model_dump(), "checked_at": doc["checked_at"]}).checked_at})
    except (OSError, ValueError, KeyError, StopIteration):
        return result


def apply_source_rules(offer: Offer, source: dict, data: Path) -> Offer:
    """支付按商家公开卡种判断，不按发卡银行名字判断或伪造授权结果。"""
    update = {}
    code = source.get("rules_code", offer.source_code)
    shipping = source.get("china_shipping", {})
    if shipping.get("status") in ("yes", "no"):
        if _current(shipping, "shipping", code, data):
            check = _checked_evidence(source, "china_shipping", "shipping", code, data)
            update["shipping_to_china"] = check
            if check.status == "no":
                update["shipping"] = None
            elif source.get("china_shipping_cost"):
                update["shipping"] = Money.model_validate(source["china_shipping_cost"])
        else:
            update["shipping_to_china"] = Evidence(note="配送原文已变化，中文规则正在复核", scope="site")
            if offer.shipping_to_china.scope == "site":
                update["shipping"] = None
    payment = source.get("card_networks_evidence", {})
    if payment:
        if _current(payment, "payment", code, data):
            update["accepted_card_networks"] = source.get("accepted_card_networks", [])
            update["card_networks_evidence"] = _checked_evidence(source, "card_networks_evidence", "payment", code, data)
        else:
            update["accepted_card_networks"] = []
            update["card_networks_evidence"] = Evidence(note="支付原文已变化，卡种条件正在复核", scope="site")
    if source.get("china_credit_card"):
        update["china_issued_card"] = evidence(source, "china_credit_card")
    if source.get("dispatch_origin"):
        if _current(source.get("dispatch_origin_evidence",{}),"shipping",code,data):
            update["dispatch_origin"] = source["dispatch_origin"]
            update["dispatch_origin_evidence"] = _checked_evidence(source, "dispatch_origin_evidence", "shipping", code, data)
        else:
            update["dispatch_origin"] = None
            update["dispatch_origin_evidence"] = Evidence(note="发货规则已变化，仓库信息正在复核",scope="site")
    if not offer.sales_region and source.get("sales_region"):
        # A source description must not overwrite the market observed on this quote.
        update["sales_region"] = source["sales_region"]
    return offer.model_copy(update=update)

