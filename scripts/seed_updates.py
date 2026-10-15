"""空缓存优先恢复公开网站事件，保证新的事件 ID 超过已发布游标。"""
from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import certifi
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.updates import UpdateStore
from app.catalog.storage import atomic_json
from app.public_recovery import baseline_writes, validate_baseline
from scripts.verify_public_release import validate_manifest, validate_snapshot, verify_status

SQLITE_MAX_CURSOR = 2**63 - 2
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_STATUS_BYTES = 8 * 1024 * 1024
EVENT_FIELDS = (
    "id", "event_key", "kind", "source_code", "source_name", "offer_id",
    "name_zh", "category", "old_price", "new_price", "currency", "stock",
    "observed_at", "url",
)


class PublicEventProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    offer_id: str = Field(min_length=1, max_length=200)
    url: str = Field(max_length=5000)
    name: str = Field(max_length=2000)
    brand: str = Field(max_length=500)
    model: str = Field(max_length=2000)
    color: str | None = Field(default=None, max_length=500)
    size: str | None = Field(default=None, max_length=500)
    image: str | None = Field(default=None, max_length=5000)
    product_id: str | None = Field(default=None, max_length=200)
    variant_id: str | None = Field(default=None, max_length=200)
    current_stock: Literal["in_stock", "out_of_stock", "unknown"] | None = None


class PublicEvent(BaseModel):
    """公开事件 Schema；金额是 currency 对应的货币元字符串。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: int = Field(ge=1, le=SQLITE_MAX_CURSOR)
    event_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["new_offer", "inventory_changed", "price_changed"]
    source_code: str = Field(pattern=r"^[a-z0-9_]+$", max_length=100)
    source_name: str = Field(min_length=1, max_length=500)
    offer_id: str = Field(min_length=1, max_length=200)
    name_zh: str = Field(min_length=1, max_length=2000)
    category: Literal[
        "jerseys", "bibs", "jackets", "shoes", "helmets", "accessories"
    ]
    old_price: str | None
    new_price: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    stock: Literal["in_stock", "out_of_stock", "unknown"]
    observed_at: str
    url: str = Field(max_length=5000)
    product: PublicEventProduct | None = None
    recovered_history: bool = False
    original_id: int | None = Field(default=None, ge=1, le=SQLITE_MAX_CURSOR)
    recovery_snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_name", "offer_id", "name_zh")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Event text must not be blank")
        return value

    @field_validator("old_price", "new_price")
    @classmethod
    def validate_amount(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                amount = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError("Event amount must be decimal") from exc
            if not amount.is_finite() or amount < 0:
                raise ValueError("Event amount must be finite and nonnegative")
        return value

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: str) -> str:
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Event timestamp requires timezone")
        return value

    @field_validator("url")
    @classmethod
    def require_public_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password):
            raise ValueError("Event URL requires HTTPS without credentials")
        return value


def validate_events(items: object, cursor: object) -> tuple[list[dict], int]:
    """原子校验事件与非负游标；拒绝重复 ID、重复键及超过游标的记录。"""
    if type(cursor) is not int or not 0 <= cursor <= SQLITE_MAX_CURSOR:
        raise ValueError("Public cursor must be a nonnegative SQLite integer")
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError("Public events require an array of at most 100 rows")
    events = [PublicEvent.model_validate(item).model_dump() for item in items]
    if any(event.get("product") and (event["product"]["offer_id"] != event["offer_id"] or event["product"]["url"] != event["url"]) for event in events):
        raise ValueError("Product metadata must bind to the exact event offer and URL")
    if any((event["recovered_history"] and not (event["original_id"] and event["recovery_snapshot_sha256"]))
           or (not event["recovered_history"] and (event["original_id"] is not None or event["recovery_snapshot_sha256"] is not None)) for event in events):
        raise ValueError("Recovered historical events require their original identity and evidence")
    if len({event["id"] for event in events}) != len(events):
        raise ValueError("Public event IDs must be unique")
    if len({event["event_key"] for event in events}) != len(events):
        raise ValueError("Public event keys must be unique")
    if any(event["id"] > cursor for event in events):
        raise ValueError("Public event ID exceeds its cursor")
    return events, cursor


def download_public_snapshot(public_url: str) -> tuple[dict, dict | None]:
    """Read only bounded, fixed own-site paths; bind every file to one release."""
    parsed = urlsplit(public_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("BIKEHUNT_PUBLIC_URL requires an HTTPS base URL")
    base = public_url.rstrip("/") + "/"
    context = ssl.create_default_context(cafile=certifi.where())

    def read(path: str, limit: int) -> bytes:
        request = urllib.request.Request(urljoin(base, path),
            headers={"User-Agent": "BikeHunt/0.3", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=12, context=context) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else None
            if final_url and (urlsplit(final_url).scheme != "https" or urlsplit(final_url).netloc != parsed.netloc):
                raise ValueError("Public recovery redirected outside its own site")
            body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Public recovery file exceeds the size limit")
        return body

    for attempt in range(3):
        try:
            manifest = json.loads(read("data/publication.json", MAX_MANIFEST_BYTES))
            commit = manifest.get("commit")
            if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
                raise ValueError("Invalid public release commit")
            validate_manifest(manifest, commit)
            if manifest["snapshot"]["bytes"] > MAX_RESPONSE_BYTES:
                raise ValueError("Public snapshot exceeds the size limit")
            data = validate_snapshot(manifest,
                read("data/site-data.json", MAX_RESPONSE_BYTES), commit)
            status = None
            if manifest["schema_version"] == 2:
                if manifest["status"]["bytes"] > MAX_STATUS_BYTES:
                    raise ValueError("Public status exceeds the size limit")
                status = verify_status(manifest,
                    read("data/verification.json", MAX_STATUS_BYTES), data, commit)
            validate_events(data["updates"]["items"], data["updates"]["cursor"])
            validate_baseline(data, status)
            return data, status
        except Exception as exc:
            logger.warning("公开基线恢复失败 attempt={}/3 {}", attempt + 1, type(exc).__name__)
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Public recovery retry attempts exhausted")


def download_public_events(public_url: str) -> tuple[list[dict], int]:
    """Compatibility entry point; events are always release-bound."""
    data, _ = download_public_snapshot(public_url)
    return validate_events(data["updates"]["items"], data["updates"]["cursor"])


def checkpoint_cursor(root: Path) -> int:
    """An explicit, audited historic publication floor reserves IDs, not events."""
    path = root / "data/event_cursor_checkpoint.json"
    if not path.exists():
        return 0
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("Event cursor checkpoint exceeds the size limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"schema_version", "cursor", "commit", "generated_at", "snapshot_sha256"}:
        raise ValueError("Invalid event cursor checkpoint schema")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported event cursor checkpoint")
    validate_events([], value["cursor"])
    if value["cursor"] < 1 or not isinstance(value["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", value["commit"]):
        raise ValueError("Invalid event cursor checkpoint identity")
    if not isinstance(value["snapshot_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["snapshot_sha256"]):
        raise ValueError("Invalid event cursor checkpoint digest")
    from scripts.verify_public_release import validate_timestamp
    validate_timestamp(value["generated_at"], "Checkpoint publication")
    return value["cursor"]


def history_recovery(root: Path, floor: int) -> dict | None:
    """A bounded audit artifact contains both exact windows and the known IDs."""
    path = root / "data/event_history_recovery.json"
    if not path.exists():
        return None
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Event recovery artifact exceeds size limit")
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(artifact, dict) or set(artifact) != {"schema_version", "prior_publication", "affected_publication", "prior_offer_ids", "prior_offer_baseline", "restored_events", "replayed_events"}:
        raise ValueError("Invalid event recovery artifact")
    if type(artifact["schema_version"]) is not int or artifact["schema_version"] != 1:
        raise ValueError("Unsupported event history recovery")
    checkpoint = json.loads((root / "data/event_cursor_checkpoint.json").read_text(encoding="utf-8"))
    prior, affected = artifact["prior_publication"], artifact["affected_publication"]
    if prior != {key: checkpoint[key] for key in ("commit", "generated_at", "cursor", "snapshot_sha256")} or floor != prior["cursor"]:
        raise ValueError("Historical recovery does not match the audited checkpoint")
    from scripts.verify_public_release import validate_timestamp
    prior_at = validate_timestamp(prior["generated_at"], "Prior recovery publication")
    affected_at = validate_timestamp(affected["generated_at"], "Affected recovery publication")
    if affected_at <= prior_at or not re.fullmatch(r"[0-9a-f]{40}", affected.get("commit", "")) or not re.fullmatch(r"[0-9a-f]{64}", affected.get("snapshot_sha256", "")):
        raise ValueError("Invalid affected recovery publication")
    known = artifact["prior_offer_ids"]
    if not isinstance(known, list) or len(known) > 100000 or any(not isinstance(key, str) or not key or len(key) > 200 for key in known) or len(set(known)) != len(known):
        raise ValueError("Invalid recovery offer identities")
    baseline = artifact["prior_offer_baseline"]
    if not isinstance(baseline, dict) or set(baseline) != set(known):
        raise ValueError("Recovery offer baseline must match the exact prior identities")
    from app.catalog.models import Money
    for offer in baseline.values():
        if not isinstance(offer, dict) or set(offer) != {"url", "price", "stock"}:
            raise ValueError("Invalid recovery offer baseline")
        Money.model_validate(offer["price"])
    restored, _ = validate_events(artifact["restored_events"], prior["cursor"])
    replayed, _ = validate_events(artifact["replayed_events"], affected["cursor"])
    for row in restored:
        if row["offer_id"] not in known or datetime.fromisoformat(row["observed_at"]) > prior_at or row["recovered_history"]:
            raise ValueError("Historical event is not supported by the prior snapshot")
    for row in replayed:
        previous = baseline.get(row["offer_id"], {})
        if (previous.get("url") != row["url"] or previous.get("stock") != row["stock"]
                or previous.get("price", {}).get("currency") != row["currency"]
                or Decimal(previous.get("price", {}).get("amount", "NaN")) != Decimal(row["new_price"])):
            raise ValueError("Replay differs from the prior offer state; preserve this event")
        if (row["kind"] != "new_offer" or row["offer_id"] not in known or row["recovered_history"]
                or not prior_at < datetime.fromisoformat(row["observed_at"]) <= affected_at):
            raise ValueError("Replay suppression lacks prior-offer evidence")
    return {**artifact, "restored_events": restored, "replayed_events": replayed}


def validate_recovery_markers(value: object, cursor: int) -> dict:
    if not isinstance(value, dict) or len(value) > 10:
        raise ValueError("Invalid published history recovery markers")
    for key, record in value.items():
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key) or not isinstance(record, dict) or set(record) != {"affected_snapshot_sha256", "completed_cursor"}:
            raise ValueError("Invalid published history recovery identity")
        if not isinstance(record["affected_snapshot_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", record["affected_snapshot_sha256"]):
            raise ValueError("Invalid published recovery affected snapshot")
        validate_events([], record["completed_cursor"])
        if not 0 < record["completed_cursor"] <= cursor:
            raise ValueError("Published recovery completion exceeds event cursor")
    return value


def proven_incident_replay(row, artifact: dict) -> bool:
    """Additional warm-cache rows need the same exact state and incident scope."""
    if row["kind"] != "new_offer" or not 0 < row["id"] <= artifact["affected_publication"]["cursor"]:
        return False
    previous = artifact["prior_offer_baseline"].get(row["offer_id"])
    if not previous:
        return False
    try:
        observed = datetime.fromisoformat(row["observed_at"])
        prior = datetime.fromisoformat(artifact["prior_publication"]["generated_at"])
        affected = datetime.fromisoformat(artifact["affected_publication"]["generated_at"])
        return (prior < observed <= affected and row["url"] == previous["url"]
                and row["stock"] == previous["stock"]
                and row["currency"] == previous["price"]["currency"]
                and Decimal(row["new_price"]) == Decimal(previous["price"]["amount"]))
    except (ValueError, TypeError, InvalidOperation):
        return False


def apply_history_recovery(db, artifact: dict | None) -> tuple[int, int]:
    if artifact is None:
        return 0, 0
    suppressed, recovered = 0, 0
    for row in artifact["replayed_events"]:
        existing = db.execute("SELECT * FROM events WHERE event_key=?", (row["event_key"],)).fetchone()
        if existing:
            # No fuzzy name/price matching, and never suppress unknown current events.
            if any(existing[field] != row[field] for field in EVENT_FIELDS):
                raise ValueError("Replay evidence conflicts with the stored event")
    for row in db.execute("SELECT * FROM events WHERE kind='new_offer' AND recovered_history=0 AND id<=?",
                          (artifact["affected_publication"]["cursor"],)).fetchall():
        if proven_incident_replay(row, artifact):
            suppressed += db.execute("INSERT OR IGNORE INTO suppressed_events VALUES (?,?,?,?)",
                (row["event_key"], "Exact prior offer state in the cold-cache incident ID/time window",
                 artifact["prior_publication"]["snapshot_sha256"],
                 artifact["affected_publication"]["snapshot_sha256"])).rowcount
    prior_sha = artifact["prior_publication"]["snapshot_sha256"]
    affected_sha = artifact["affected_publication"]["snapshot_sha256"]
    completed = db.execute("SELECT * FROM event_recovery_runs WHERE snapshot_sha256=?", (prior_sha,)).fetchone()
    if completed:
        if completed["affected_snapshot_sha256"] != affected_sha:
            raise ValueError("Conflicting history recovery completion identity")
        return 0, suppressed
    for row in sorted(artifact["restored_events"], key=lambda item: item["id"]):
        if db.execute("SELECT 1 FROM events WHERE event_key=?", (row["event_key"],)).fetchone():
            continue
        columns = EVENT_FIELDS[1:]
        inserted = db.execute("INSERT INTO events (" + ",".join(columns) + ") VALUES ("
            + ",".join("?" for _ in columns) + ")", tuple(row[field] for field in columns))
        db.execute("UPDATE events SET recovered_history=1,original_id=?,recovery_snapshot_sha256=?,product_json=? WHERE id=?",
            (row["id"], artifact["prior_publication"]["snapshot_sha256"],
             json.dumps(row["product"], ensure_ascii=False) if row.get("product") else None, inserted.lastrowid))
        recovered += 1
    final_cursor = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()[0]
    db.execute("INSERT INTO event_recovery_runs VALUES (?,?,?)", (prior_sha, affected_sha, final_cursor))
    return recovered, suppressed


def repository_events(root: Path) -> tuple[list[dict], int]:
    """读取仓库公开种子；缺失意味着首次发布，无效种子会中止构建。"""
    path = root / "data/public_updates.json"
    if not path.exists():
        return [], 0
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError("Repository event seed must be an array")
    cursor = max(
        (item.get("id", 0) for item in items if isinstance(item, dict)),
        default=0,
    )
    return validate_events(items, cursor)


def restore_public_cursor(root: Path, public_url: str = "") -> dict:
    """Reconcile published events and offer baselines before any collection.

    A configured existing site must verify successfully. An old repository seed
    is not a substitute for its cursor or offer history during an outage.
    """
    store = UpdateStore(root)
    existing = store.cursor()
    floor = checkpoint_cursor(root)
    recovery = history_recovery(root, floor)
    writes, restored_offers = {}, 0
    markers = {}
    if public_url:
        data, status = download_public_snapshot(public_url)
        rows, cursor = validate_events(data["updates"]["items"], data["updates"]["cursor"])
        markers = validate_recovery_markers(data["updates"].get("history_recovery", {}), cursor)
        offers, collection = validate_baseline(data, status)
        writes, restored_offers = baseline_writes(root, offers, collection)
        source = "published"
    elif existing:
        rows, cursor, source = [], existing, "existing"
    else:
        rows, cursor = repository_events(root)
        source = "repository"
    restored = 0
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for row in rows:
            by_id = db.execute("SELECT event_key FROM events WHERE id=?", (row["id"],)).fetchone()
            by_key = db.execute("SELECT id FROM events WHERE event_key=?", (row["event_key"],)).fetchone()
            if by_id and by_id[0] != row["event_key"] or by_key and by_key[0] != row["id"]:
                raise ValueError("Published event ID conflicts with local history; explicit migration required")
            if not by_id:
                db.execute("INSERT INTO events (" + ",".join(EVENT_FIELDS) + ") VALUES ("
                    + ",".join("?" for _ in EVENT_FIELDS) + ")", tuple(row[field] for field in EVENT_FIELDS))
                restored += 1
            if row["recovered_history"]:
                db.execute("UPDATE events SET recovered_history=1,original_id=?,recovery_snapshot_sha256=? WHERE id=?",
                    (row["original_id"], row["recovery_snapshot_sha256"], row["id"]))
            if row.get("product"):
                db.execute("UPDATE events SET product_json=COALESCE(product_json,?) WHERE id=?",
                    (json.dumps(row["product"], ensure_ascii=False), row["id"]))
        sequence = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
        cursor = max(cursor, existing, floor, sequence[0] if sequence else 0)
        if sequence:
            db.execute("UPDATE sqlite_sequence SET seq=? WHERE name='events'", (cursor,))
        else:
            db.execute("INSERT INTO sqlite_sequence (name,seq) VALUES ('events',?)", (cursor,))
        for key, marker in markers.items():
            known = db.execute("SELECT * FROM event_recovery_runs WHERE snapshot_sha256=?", (key,)).fetchone()
            if known and known["affected_snapshot_sha256"] != marker["affected_snapshot_sha256"]:
                raise ValueError("Conflicting local and published recovery markers")
            db.execute("INSERT INTO event_recovery_runs VALUES (?,?,?) ON CONFLICT(snapshot_sha256) "
                "DO UPDATE SET completed_cursor=MAX(completed_cursor,excluded.completed_cursor)",
                (key, marker["affected_snapshot_sha256"], marker["completed_cursor"]))
        recovered, suppressed = apply_history_recovery(db, recovery)
        cursor = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()[0]
        # All remote/local records were validated before any write; retries are
        # idempotent. A file failure rolls back event changes and stops collection.
        for path, value in writes.items():
            atomic_json(path, value)
    result = {"source": source, "restored": restored, "cursor": cursor}
    if recovery:
        result.update(recovered_history=recovered, suppressed_replays=suppressed)
    if public_url:
        result["restored_offers"] = restored_offers
    logger.info("恢复公开基线 {}", result)
    return result


if __name__ == "__main__":
    print(json.dumps(restore_public_cursor(
        ROOT, os.environ.get("BIKEHUNT_PUBLIC_URL", ""),
    )))

