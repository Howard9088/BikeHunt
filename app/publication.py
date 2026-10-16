"""Stable public catalog bytes with separately bound, genuine verification times."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def offers_by_id(payload: dict) -> dict[str, dict]:
    offers: dict[str, dict] = {}
    for family in payload["details"].values():
        for detail in family["variants"].values():
            for quote in detail["offers"]:
                offer = quote["offer"]
                identifier = offer["offer_id"]
                if identifier in offers and offers[identifier] != offer:
                    raise ValueError("Conflicting public offer identity: " + identifier)
                offers[identifier] = offer
    return offers


def offer_identity(offer: dict) -> str:
    """Only fetched_at is observational; prices, scope and all evidence stay bound."""
    semantic = dict(offer)
    semantic.pop("fetched_at", None)
    return digest(semantic)


def semantic_projection(payload: dict) -> dict:
    """Exclude only observations mirrored by verification.json, never safety state.

    Evidence dates, FX reference date, eligibility/reasons, costs and all source
    identities remain significant. In particular, a failed refresh, expiry or
    recovery observed by the builder changes the catalog semantics.
    """
    result = copy.deepcopy(payload)
    for key in ("generated_at", "publication", "collection_status"):
        result.pop(key, None)
    result["catalog"]["fx"].pop("fetched_at", None)
    result["updates"]["fx"].pop("fetched_at", None)
    # Presentation recency order is observational; object identities are stable.
    result["catalog"]["items"].sort(key=lambda card: card["product_id"])
    for card in result["catalog"]["items"]:
        card.pop("fetched_at", None)
        for channel in card.get("channel_quotes", {}).values():
            channel.pop("fetched_at", None)
    for family in result["details"].values():
        for detail in family["variants"].values():
            detail["fx"].pop("fetched_at", None)
            for quote in detail["offers"]:
                quote["offer"].pop("fetched_at", None)
                # This one date is produced directly from offer.fetched_at by
                # estimate_landed_cost. Policy/tax/evidence dates are untouched.
                for component in (quote.get("landed_cost") or {}).get("components", []):
                    if component["key"] == "product":
                        for evidence in component.get("evidence", []):
                            evidence.pop("checked_on", None)
    return result


def observation_time(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):?[0-5]\d)", value):
        raise ValueError("Invalid cached observation time")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Cached observations require a timezone")
    return parsed


def reusable_observations(cached: dict, current: dict) -> bool:
    """A valid semantic hash cannot excuse poisoned excluded metadata in cache."""
    created, generated = observation_time(cached["generated_at"]), observation_time(current["generated_at"])
    if created is None or generated is None or created > generated:
        return False
    previous, fresh = offers_by_id(cached), offers_by_id(current)
    if previous.keys() != fresh.keys():
        return False
    def coherent(old, new):
        before, after = observation_time(old), observation_time(new)
        return ((before is None or before <= created)
                and (after is None or after <= generated)
                and (before is None or after is not None and before <= after))
    for identifier, offer in previous.items():
        latest = fresh[identifier]
        if not coherent(offer.get("fetched_at"), latest.get("fetched_at")):
            return False
        if offer.get("collection_state") == "retained" and offer.get("fetched_at") != latest.get("fetched_at"):
            return False
    old_fx, new_fx = cached["catalog"]["fx"], current["catalog"]["fx"]
    if not coherent(old_fx.get("fetched_at"), new_fx.get("fetched_at")):
        return False
    if cached["updates"]["fx"].get("fetched_at") != old_fx.get("fetched_at"):
        return False
    for parent in cached["catalog"]["items"]:
        for card in [parent, *parent.get("channel_quotes", {}).values()]:
            reference = previous[card["reference_offer_id"]]
            if card.get("fetched_at") != reference.get("fetched_at"):
                return False
    for family in cached["details"].values():
        for detail in family["variants"].values():
            if detail["fx"].get("fetched_at") != old_fx.get("fetched_at"):
                return False
            for quote in detail["offers"]:
                fetched = observation_time(quote["offer"].get("fetched_at"))
                for component in (quote.get("landed_cost") or {}).get("components", []):
                    if component["key"] == "product":
                        for evidence in component.get("evidence", []):
                            if evidence.get("checked_on") != (fetched.date().isoformat() if fetched else None):
                                return False
    return True


def build_publication(payload: dict, output: Path, cache: Path, *, allowed_status_urls=None) -> dict:
    """Write one schema-2 release; a cache hit reuses the exact catalog bytes.

    Cache contents need not have been deployed: they are byte reuse, not evidence
    of publication or verification. Each new manifest binds both output files.
    """
    from app.public_status import public_collection_status
    payload = copy.deepcopy(payload)
    current_offers = offers_by_id(payload)
    allowed = set(allowed_status_urls or ()) | {o['url'] for o in current_offers.values()}
    payload['collection_status'] = public_collection_status(payload.get('collection_status', {}), allowed)
    payload["verification_identities"] = {
        identifier: offer_identity(offer) for identifier, offer in sorted(current_offers.items())}
    semantic_hash = digest(semantic_projection(payload))
    commit = payload["publication"]["commit"]
    catalog_version = (commit or "local") + ":catalog:" + semantic_hash
    payload["publication"]["version"] = catalog_version
    raw: bytes | None = None
    cached_path = cache / "site-data.json"
    try:
        candidate = cached_path.read_bytes()
        cached = json.loads(candidate)
        if (cached["publication"]["commit"] == commit
                and cached["publication"]["version"] == catalog_version
                and digest(semantic_projection(cached)) == semantic_hash
                and cached.get("verification_identities") == payload["verification_identities"]
                and public_collection_status(cached.get('collection_status', {}), allowed) == cached.get('collection_status', {})
                and reusable_observations(cached, payload)):
            raw = candidate
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    changed = raw is None
    if changed:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        cache.mkdir(parents=True, exist_ok=True)
        temporary = cached_path.with_suffix(".json.tmp")
        temporary.write_bytes(raw)
        temporary.replace(cached_path)
    assert raw is not None
    catalog = json.loads(raw)
    catalog_hash = hashlib.sha256(raw).hexdigest()
    generated_at = payload["generated_at"]
    version = (commit or "local") + ":" + generated_at
    fx = payload["catalog"]["fx"]
    status = {
        "schema_version": 1, "version": version, "generated_at": generated_at,
        "commit": commit, "snapshot_sha256": catalog_hash,
        "run_id": payload["publication"].get("run_id"),
        "trigger": payload["publication"].get("trigger"),
        "offers": {identifier: {
            "content_sha256": payload["verification_identities"][identifier],
            "fetched_at": offer.get("fetched_at"),
            "collection_state": offer.get("collection_state", "current"),
        } for identifier, offer in sorted(current_offers.items())},
        "fx": {key: fx.get(key) for key in ("snapshot_id", "fetched_at", "stale")},
        "collection_status": payload["collection_status"],
    }
    status_raw = canonical_bytes(status)
    manifest = {
        "schema_version": 2, "version": version, "generated_at": generated_at,
        "commit": commit,
        "snapshot": {"path": "data/site-data.json", "bytes": len(raw),
                     "sha256": catalog_hash, "version": catalog_version,
                     "generated_at": catalog["generated_at"], "commit": commit,
                     "semantic_sha256": semantic_hash},
        "status": {"path": "data/verification.json", "bytes": len(status_raw),
                   "sha256": hashlib.sha256(status_raw).hexdigest()},
    }
    data = output / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "site-data.json").write_bytes(raw)
    (data / "verification.json").write_bytes(status_raw)
    # Write the small pointer last. Readers still verify all bytes and bindings.
    (data / "publication.json").write_bytes(canonical_bytes(manifest))
    return {"catalog_changed": changed, "catalog_sha256": catalog_hash,
            "semantic_sha256": semantic_hash, "snapshot_bytes": len(raw),
            "verification_bytes": len(status_raw), "manifest_bytes": len(canonical_bytes(manifest))}
