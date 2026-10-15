"""Reversible public merchandising policy; source research and taxonomy stay intact."""
from __future__ import annotations

from pathlib import Path
from app.browse_taxonomy import CATEGORY_GROUPS
from app.road_equipment import BROWSE_CATEGORIES, read_road_references

# Re-enable only with the matching web/public-visibility.js flag and regression review.
BICYCLES_PUBLIC = False
BICYCLE_CATEGORIES = frozenset({"road_bikes", "frames"})


def public_product(row: dict) -> bool:
    return BICYCLES_PUBLIC or (row.get("category_group") != "road_equipment"
                              and row.get("category") not in BICYCLE_CATEGORIES)


def public_category_groups() -> list[dict]:
    return [dict(row) for row in CATEGORY_GROUPS
            if BICYCLES_PUBLIC or row["code"] != "road_equipment"]


def public_categories() -> list[dict]:
    return [dict(row) for row in BROWSE_CATEGORIES
            if BICYCLES_PUBLIC or row["code"] not in BICYCLE_CATEGORIES]


def public_road_references(root: Path) -> dict:
    data = read_road_references(root)
    if BICYCLES_PUBLIC:
        return data
    products = [row for row in data["products"] if public_product(row)]
    brands = []
    for brand in data["brands"]:
        visible = [row for row in products if row["source_code"] == brand["code"]]
        if visible:
            # An accessory reference must never lead to the old bicycle outlet.
            brands.append({**brand, "url": visible[0]["url"],
                           "note": "美国站配件研究参考；中国直邮、转运许可、库存、支付和退换条件均待核实。"})
    return {**data, "brands": brands, "products": products}


def public_directory_data(data: dict, references: dict) -> dict:
    if BICYCLES_PUBLIC:
        return data
    brands = {row["code"]: row for row in references["brands"]}
    result = []
    for entry in data["brands"]:
        if not entry.get("road_reference"):
            result.append(entry)
        elif entry["code"] in brands:
            reference = brands[entry["code"]]
            result.append({**entry, "name_zh": entry["name"] + " 配件",
                           "official_url": reference["url"], "shop_url": reference["url"],
                           "shop_evidence_url": reference["url"], "reference_note": reference["note"],
                           "reference_category_group": "other"})
    return {**data, "brands": result}


def public_directories(root: Path) -> dict:
    from app.discovery import directories
    return public_directory_data(directories(root), public_road_references(root))
