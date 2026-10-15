"""Exact-identity display metadata for price events; never match by a title."""
from __future__ import annotations

from app.catalog.models import Offer
from app.catalog.service import ComparisonCatalog
from app.public_visibility import public_product


def event_product(offer: Offer) -> dict:
    identity = offer.identity
    return {"offer_id": offer.offer_id, "url": offer.url, "name": offer.name,
            "brand": identity.brand, "model": identity.mpn or identity.model,
            "color": identity.color, "size": identity.size, "image": offer.image}


def enrich_events(events: list[dict], catalog: ComparisonCatalog, *, include_hidden: bool = False) -> list[dict]:
    """Preserve event-time metadata; enrich legacy rows only by exact offer ID + URL.

    Current state and catalog routes are separate from historical event prices/stock.
    A missing current offer cannot borrow another product's picture or buyable state.
    """
    exact = {offer.offer_id: (offer, product_id, catalog._variant_id(variant))
             for product_id, variants in catalog.families.items()
             for variant in variants for offer in variant}
    result = []
    for original in events:
        if catalog.public_only and not include_hidden and (original.get("offer_id") in catalog.hidden_offer_ids
                or not public_product(original) or not public_product(original.get("product") or {})):
            continue
        event = dict(original)
        stored = event.get("product")
        product = dict(stored) if (isinstance(stored, dict)
            and stored.get("offer_id") == event.get("offer_id")
            and stored.get("url") == event.get("url")) else None
        match = exact.get(event.get("offer_id"))
        if match and match[0].url == event.get("url"):
            offer, product_id, variant_id = match
            product = product or event_product(offer)
            product.update(product_id=product_id, variant_id=variant_id,
                           current_stock=offer.stock)
        elif product:
            product.update(product_id=None, variant_id=None, current_stock="unknown")
        event["product"] = product
        result.append(event)
    return result
