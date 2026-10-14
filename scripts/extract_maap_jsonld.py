from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "maap_sample.html"
OUTPUT = ROOT / "data" / "products_maap.json"


class JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.capture = False
        self.parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "script":
            return
        attr_map = dict(attrs)
        if attr_map.get("type") == "application/ld+json":
            self.capture = True
            self.parts = []

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self.capture:
            self.blocks.append("".join(self.parts))
            self.capture = False
            self.parts = []


def main() -> None:
    html = INPUT.read_text(encoding="utf-8", errors="ignore")
    parser = JsonLdParser()
    parser.feed(html)

    products: list[dict] = []
    seen: set[str] = set()

    for block in parser.blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue

        if not isinstance(data, dict) or data.get("@type") != "CollectionPage":
            continue

        entities = data.get("mainEntity") or []
        if not isinstance(entities, list):
            continue

        for item in entities:
            if not isinstance(item, dict) or item.get("@type") != "Product":
                continue

            url = item.get("url") or item.get("@id")
            if not url or url in seen:
                continue
            seen.add(url)

            offer = item.get("offers") if isinstance(item.get("offers"), dict) else {}
            spec = offer.get("priceSpecification") if isinstance(offer.get("priceSpecification"), dict) else {}

            try:
                current = float(offer.get("price"))
            except (TypeError, ValueError):
                current = None
            try:
                original = float(spec.get("price"))
            except (TypeError, ValueError):
                original = None

            discount_pct = None
            if current is not None and original and original > current:
                discount_pct = round((1 - current / original) * 100)

            images = item.get("image")
            if isinstance(images, list):
                image = images[0] if images else None
            else:
                image = images

            brand_obj = item.get("brand")
            brand = brand_obj.get("name") if isinstance(brand_obj, dict) else brand_obj

            products.append(
                {
                    "source": "MAAP",
                    "source_code": "maap",
                    "name": item.get("name"),
                    "brand": brand or "MAAP",
                    "sku": item.get("sku"),
                    "url": url,
                    "image": image,
                    "currency": offer.get("priceCurrency"),
                    "price": current,
                    "original_price": original,
                    "discount_pct": discount_pct,
                    "availability": offer.get("availability"),
                    "price_valid_until": offer.get("priceValidUntil"),
                }
            )

    OUTPUT.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Extracted {len(products)} MAAP products -> {OUTPUT}")


if __name__ == "__main__":
    main()
