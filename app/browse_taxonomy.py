"""Reviewed browse groups, independent of legacy leaf, fit, and tax categories.

The catalog's identity/offer grouping happens before this module is consulted.
An explicit review applies only to its stable product ID and saved source URL;
neither a brand name nor a footwear URL proves cleat compatibility.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Literal, NamedTuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.localization import category_of

if TYPE_CHECKING:
    from app.catalog.models import Offer

CategoryGroup = Literal["road_equipment", "clothing", "helmets", "cleat_shoes", "other"]

# The all/reset state is internal compatibility data, never a sixth visible group.
CATEGORY_GROUPS = [
    {"code": "road_equipment", "name": "自行车"},
    {"code": "clothing", "name": "骑行服饰"},
    {"code": "cleat_shoes", "name": "锁鞋"},
    {"code": "helmets", "name": "头盔"},
    {"code": "other", "name": "配件与周边"},
]

_TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data/browse-taxonomy.json"
_GROUP_CODES = {row["code"] for row in CATEGORY_GROUPS}
_VARIANT_QUERY_KEYS = {"variant", "preselectedvariant"}


class BrowseClassification(NamedTuple):
    category: str
    category_group: CategoryGroup


def canonical_product_url(url: str) -> str:
    """Ignore only known size/variant selectors, preserving product query IDs.

Source identity and exact product path remain mandatory. In particular, two
generic /product?id= URLs must not collapse into the same reviewed identity.
"""
    parsed = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key.casefold() not in _VARIANT_QUERY_KEYS]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                       parsed.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


@lru_cache(maxsize=1)
def _reviewed_products() -> dict[str, dict]:
    data = json.loads(_TAXONOMY_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported browse taxonomy schema")
    result: dict[str, dict] = {}
    for row in data["products"]:
        product_id = row["product_id"]
        if product_id in result or row["category_group"] not in _GROUP_CODES:
            raise ValueError("Duplicate product or unknown browse group")
        if not row["source_codes"] or not row["source_url"] or not row["category"]:
            raise ValueError("Browse review requires a product source and leaf category")
        result[product_id] = {**row, "canonical_url": canonical_product_url(row["source_url"])}
    return result


def _fallback(name: str) -> BrowseClassification:
    """Keep explicit garments/helmets discoverable; leave unknown types Other.

Future model-only names need their own review. A shoe, a shoe brand, or a
cycling-shoe label alone does not establish a cleat-compatible product.
"""
    text = name.casefold()
    if re.search(r"\b(?:key\s*ring|keychain|souvenir|sticker|poster)\b", text):
        return BrowseClassification("accessories", "other")
    if re.search(r"\b(?:shoe\s*covers?|overshoes?)\b", text):
        return BrowseClassification("accessories", "clothing")
    category = category_of(name)
    if category in {"jerseys", "bibs", "jackets", "suits"}:
        return BrowseClassification(category, "clothing")
    if category == "helmets":
        if re.search(r"\b(?:bags?|covers?|liners?|pads?|visors?|straps?|spares?)\b", text):
            return BrowseClassification("accessories", "other")
        return BrowseClassification(category, "helmets")
    # category_of intentionally retains legacy shoe/QUOC matching for callers
    # such as tax and notifications. It is not a browse cleat-compatibility test.
    if category == "shoes":
        return BrowseClassification("accessories", "other")
    return BrowseClassification(category, "other")


def browse_classification(product_id: str, offers: Iterable[Offer], *,
                          name: str | None = None) -> BrowseClassification:
    """Return the reviewed leaf and group without modifying any offer facts.

Pass all offers in the existing family so a selected size or source does not
alter navigation. A stale/mismatched review cannot classify an unrelated URL.
"""
    family = tuple(offers)
    reviewed = _reviewed_products().get(product_id)
    if reviewed and any(
        offer.source_code in reviewed["source_codes"]
        and canonical_product_url(offer.url) == reviewed["canonical_url"]
        for offer in family
    ):
        return BrowseClassification(reviewed["category"], reviewed["category_group"])
    return _fallback(name if name is not None else family[0].name if family else "")
