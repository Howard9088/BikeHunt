from __future__ import annotations

import json
from pathlib import Path

from scrapling.fetchers import Fetcher

ROOT = Path(__file__).resolve().parents[1]
URL = "https://maap.cc/collections/archive-sale-man"
RAW = ROOT / "data" / "maap_live.html"
OUT = ROOT / "data" / "products_maap.json"


def product_rows(response):
    rows = []
    seen = set()

    for raw in response.css('script[type="application/ld+json"]::text').getall():
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("@type") != "CollectionPage":
            continue

        entities = data.get("mainEntity") or []
        if not isinstance(entities, list):
            continue

        for item in entities:
            if not isinstance(item, dict) or item.get("@type") != "Product":
                continue

            offer = item.get("offers") if isinstance(item.get("offers"), dict) else {}
            spec = offer.get("priceSpecification") if isinstance(offer.get("priceSpecification"), dict) else {}
            url = item.get("url") or item.get("@id")
            if not url or url in seen:
                continue
            seen.add(url)

            def number(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            current = number(offer.get("price"))
            original = number(spec.get("price"))
            discount = round((1 - current / original) * 100) if current is not None and original and original > current else None

            imgs = item.get("image")
            image = imgs[0] if isinstance(imgs, list) and imgs else imgs if isinstance(imgs, str) else None
            brand_obj = item.get("brand")
            brand = brand_obj.get("name") if isinstance(brand_obj, dict) else brand_obj

            rows.append({
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
                "discount_pct": discount,
                "availability": offer.get("availability"),
                "price_valid_until": offer.get("priceValidUntil"),
            })

    return rows


def main():
    response = Fetcher.get(URL, timeout=30)
    if response.status != 200:
        raise SystemExit(f"MAAP HTTP {response.status}")

    RAW.write_text(response.text, encoding="utf-8")
    rows = product_rows(response)
    if not rows:
        raise SystemExit("MAAP returned no product rows; parser not accepted.")

    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"MAAP OK: {len(rows)} products -> {OUT}")


if __name__ == "__main__":
    main()
