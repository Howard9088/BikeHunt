"""Restore exact published observations without collecting or inventing freshness."""
from __future__ import annotations

import copy
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.catalog.models import Offer
from app.publication import offers_by_id, observation_time

SOURCE_CODE = re.compile(r"^[a-z0-9_]{1,100}$")


def validate_baseline(data: dict, status: dict | None) -> tuple[list[Offer], dict]:
    """The caller first verifies manifest digests, including schema-2 status."""
    published_at = observation_time((status or data)["generated_at"])
    collection = (status or data).get("collection_status", {})
    if not isinstance(collection, dict):
        raise ValueError("Published collection status must be an object")
    for code, entry in collection.items():
        if not isinstance(code, str) or not SOURCE_CODE.fullmatch(code) or not isinstance(entry, dict):
            raise ValueError("Invalid published source identity")
        if entry.get("source_code", code) != code:
            raise ValueError("Published source status identity differs")
        attempted = observation_time(entry.get("attempted_at"))
        if attempted and attempted > published_at:
            raise ValueError("Published source attempt exceeds publication")
        if not isinstance(entry.get("errors", []), list) or any(not isinstance(error, dict) for error in entry.get("errors", [])):
            raise ValueError("Invalid published source errors")
    offers = []
    for identifier, raw in offers_by_id(data).items():
        value = dict(raw)
        if status is not None:
            # verify_status already binds these observations to this exact offer.
            value["fetched_at"] = status["offers"][identifier]["fetched_at"]
        offer = Offer.model_validate(value)
        if not SOURCE_CODE.fullmatch(offer.source_code) or not identifier or len(identifier) > 200:
            raise ValueError("Invalid published offer identity")
        fetched = observation_time(value.get("fetched_at"))
        if fetched and fetched > published_at:
            raise ValueError("Published offer observation exceeds publication")
        offers.append(offer)
    return offers, collection


def _newer(first: object, second: object) -> bool:
    """Unknown cannot replace known; equal observations preserve local state."""
    left, right = observation_time(first), observation_time(second)
    return left is not None and (right is None or left > right)


def _merge_status(local: dict, published: dict) -> dict:
    result = copy.deepcopy(published if _newer(published.get("attempted_at"), local.get("attempted_at")) else local)
    # A cache recovery must never shorten an outstanding server cooldown.
    errors = list(result.get("errors", []))
    for source in (local, published):
        for error in source.get("errors", []):
            retry_at = observation_time(error.get("retry_at"))
            if retry_at and retry_at > datetime.now(timezone.utc) and error not in errors:
                errors.append(error)
    if errors or "errors" in result:
        result["errors"] = errors
    return result


def baseline_writes(root: Path, offers: list[Offer], collection: dict) -> tuple[dict[Path, dict], int]:
    """Validate and prepare all writes before mutating any baseline files."""
    grouped = defaultdict(dict)
    for offer in offers:
        grouped[offer.source_code][offer.offer_id] = offer.model_dump(mode="json")
    writes = {}
    restored = 0
    for code, published in grouped.items():
        path = root / "data/offers" / (code + ".json")
        original = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"source_code": code, "offers": []}
        if original.get("source_code", code) != code or not isinstance(original.get("offers"), list):
            raise ValueError("Invalid local source snapshot: " + code)
        local = {}
        for raw in original["offers"]:
            offer = Offer.model_validate(raw)
            if offer.source_code != code:
                raise ValueError("Local offer source differs from snapshot")
            observation_time(raw.get("fetched_at"))
            if offer.offer_id in local and local[offer.offer_id] != raw:
                raise ValueError("Conflicting local offer identity")
            local[offer.offer_id] = raw
        changed = False
        for identifier, raw in published.items():
            if identifier not in local or _newer(raw.get("fetched_at"), local[identifier].get("fetched_at")):
                local[identifier] = raw
                restored += 1
                changed = True
        if changed:
            updated = {**original, "offers": list(local.values())}
            # Preserve envelope dates; none means unknown, never recovery time.
            known_times = [raw.get("fetched_at") for raw in local.values() if raw.get("fetched_at")]
            if original.get("collected_at"):
                known_times.append(original["collected_at"])
            updated["collected_at"] = max(known_times, key=observation_time) if known_times else None
            writes[path] = updated
    for code, published in collection.items():
        path = root / "data/collection_status" / (code + ".json")
        if path.exists():
            local = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(local, dict) or local.get("source_code", code) != code:
                raise ValueError("Invalid local collection status: " + code)
            merged = _merge_status(local, published)
            if merged != local:
                writes[path] = merged
        else:
            writes[path] = published
    return writes, restored
