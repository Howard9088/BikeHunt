"""Read-only official research, deliberately outside offers and live-stock APIs."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from app.localization import CATEGORIES

BROWSE_CATEGORIES = [CATEGORIES[0]] + [
    {"code": "road_bikes", "name": "整车"},
    {"code": "frames", "name": "车架"},
    {"code": "bike_parts", "name": "零部件"},
] + CATEGORIES[1:]
REFERENCE_HOSTS = {
    "trek": ("www.trekbikes.com", "/us/en_US/"),
    "specialized": ("www.specialized.com", "/us/en/"),
    "canyon": ("www.canyon.com", "/en-us/"),
    "colnago": ("www.colnago.com", "/en-us/"),
}


def read_road_references(root: Path) -> dict:
    path = root / "data/road_equipment_references.json"
    if not path.exists():
        return {"schema_version": 1, "brands": [], "products": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported road-reference schema")
    for row in data["brands"] + data["products"]:
        code = row.get("source_code", row.get("code"))
        url = urlsplit(row["url"])
        expected = REFERENCE_HOSTS.get(code)
        if not expected or url.scheme != "https" or url.netloc != expected[0] or not url.path.startswith(expected[1]):
            raise ValueError("Unreviewed official road-reference destination")
    for row in data["products"]:
        if (row.get("stock") != "unknown" or row.get("data_kind") != "research_reference"
                or row.get("observed_at") is not None or row.get("available_sizes") != []
                or row.get("eligible") is not False or row.get("recommended_total_cny") is not None
                or not 0 < row["price"] < row["reference_price"]
                or row.get("discount_deadline") is not None):
            raise ValueError("Road research cannot assert live availability or a deadline")
    return data
