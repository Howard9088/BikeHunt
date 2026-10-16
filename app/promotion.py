"""Local, evidence-bound promotional drafts. No network clients or publishing hooks."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from app.catalog.models import FxSnapshot, Money, Offer, ProductIdentity
from app.catalog.service import ComparisonCatalog, STOCK_MAX_AGE_SECONDS
from app.catalog.storage import OfferRepository, atomic_json
from app.updates import UpdateStore

HOMEPAGE_URL = "https://howard9088.github.io/BikeHunt/"
MAX_WINDOW = timedelta(days=7)
_CONTEXT_FIELDS = {"offer_id", "source_code", "url", "identity", "price", "stock",
                   "sales_region", "family_hint", "fetched_at", "data_kind", "collection_state"}


def timestamp(value: object) -> datetime | None:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        return result.astimezone(timezone.utc) if isinstance(result, datetime) and result.tzinfo else None
    except (ValueError, OverflowError):
        return None


def amount(value: object) -> Decimal | None:
    try:
        result = Decimal(value) if isinstance(value, (str, Decimal)) else None
        return result if result is not None and result.is_finite() and result >= 0 else None
    except InvalidOperation:
        return None


def display_amount(value: object) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def safe_https(value: object, hosts: set[str] | None = None, product: bool = False) -> bool:
    """Accept explicit HTTPS product evidence, never credentials, redirects or tracking."""
    if not isinstance(value, str) or len(value) > 5000:
        return False
    decoded = unquote(unquote(value))
    if any(ord(c) < 33 or ord(c) == 127 for c in decoded) or "\\" in decoded:
        return False
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        if (url.scheme != "https" or not host or url.username or url.password
                or url.port not in (None, 443) or url.fragment or "." not in host
                or host.endswith(".") or host.endswith((".localhost", ".local"))):
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass
        if hosts is not None and host not in hosts:
            return False
        path = unquote(unquote(url.path))
        parts = [part.casefold() for part in path.split("/") if part]
        if any(part in {".", ".."} for part in parts):
            return False
        if product:
            if not parts or (len(parts) == 1 and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", parts[0])):
                return False
            if any(part in {"search", "cart", "checkout", "account", "login", "redirect", "go"} for part in parts):
                return False
            if "collections" in parts and "products" not in parts:
                return False
            for key, val in parse_qsl(url.query, keep_blank_values=True):
                if host == "shops.topfanz.com" and key == "id" and re.fullmatch(r"\d{1,20}", val):
                    continue
                if host == "www.redbullshop.com" and key == "preselectedVariant" and re.fullmatch(r"M-RBB\d{6,15}", val):
                    continue
                if host == "www.colnago.com" and key == "Size" and re.fullmatch(r"[A-Za-z0-9.-]{1,30}", val):
                    continue
                if key not in {"variant", "size", "color", "sku", "pid"} or not re.fullmatch(r"[A-Za-z0-9_.-]{1,150}", val):
                    return False
        return True
    except (ValueError, UnicodeError):
        return False


def _context(raw: object) -> dict | None:
    try:
        value = json.loads(raw) if isinstance(raw, str) else None
        if not isinstance(value, dict) or set(value) != _CONTEXT_FIELDS:
            return None
        ProductIdentity.model_validate(value["identity"])
        Money.model_validate(value["price"])
        if value["stock"] not in {"in_stock", "out_of_stock", "unknown"}:
            return None
        return value
    except (ValueError, TypeError):
        return None


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


class PromotionPreparer:
    """A durable local queue; draft identity excludes timestamps and size variants."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.output = self.root / "storage/promotions"
        # Refuse a symlink route into the public build or anywhere outside storage.
        if not self.output.resolve().is_relative_to(self.root / "storage"):
            raise ValueError("Promotion output must stay in local storage/promotions")
        self.output.mkdir(parents=True, exist_ok=True)
        self.store = UpdateStore(self.root)
        self.path = self.output / "queue.sqlite3"
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), started_at TEXT NOT NULL, cursor INTEGER NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS drafts (
                draft_key TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                member_keys TEXT NOT NULL, package_json TEXT NOT NULL)""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _sources(self) -> tuple[dict, dict, dict]:
        sources = {row["code"]: row for row in _read_json(self.root / "data/sources.json", [])
                   if isinstance(row, dict) and isinstance(row.get("code"), str)}
        crawls = {row["code"]: row for row in _read_json(self.root / "data/crawl_sources.json", [])
                  if isinstance(row, dict) and isinstance(row.get("code"), str)}
        health = {p.stem: _read_json(p, {}) for p in (self.root / "data/collection_status").glob("*.json")}
        return sources, crawls, health

    def _candidate(self, event: dict, offers: dict, routes: dict, latest: dict,
                   suppressed: set, sources: dict, crawls: dict, health: dict,
                   now: datetime) -> tuple[dict | None, str | None]:
        def skip(reason):
            return None, reason
        if event["event_key"] in suppressed:
            return skip("suppressed_event")
        if event.get("recovered_history"):
            return skip("recovered_history")
        if event["kind"] == "new_offer":
            return skip("first_discovery")
        if event["kind"] not in {"price_changed", "inventory_changed"}:
            return skip("unsupported_event_kind")
        if event["event_key"] != latest.get(event["offer_id"]):
            return skip("superseded_event")
        old, captured = _context(event.get("old_context_json")), _context(event.get("current_context_json"))
        if old is None or captured is None:
            return skip("missing_transition_evidence")
        offer = offers.get(event["offer_id"])
        if offer is None:
            return skip("current_offer_missing")
        current = json.loads(UpdateStore.context_json(offer))
        for key in ("offer_id", "source_code", "url", "sales_region", "identity", "family_hint"):
            if old[key] != captured[key] or captured[key] != current[key]:
                return skip("exact_identity_or_market_changed")
        if (event["source_code"] != offer.source_code or event["url"] != offer.url
                or not isinstance(old["sales_region"], str) or not old["sales_region"].strip()):
            return skip("missing_or_mismatched_market")
        ident = offer.identity
        if not all(isinstance(x, str) and x.strip() for x in
                   (ident.brand, ident.model, ident.color, ident.size, offer.name, offer.source_name)):
            return skip("missing_product_metadata")
        if (old["data_kind"] != "live_snapshot" or captured["data_kind"] != "live_snapshot"
                or offer.data_kind != "live_snapshot"):
            return skip("legacy_offer_evidence")
        if old["collection_state"] != "current" or captured["collection_state"] != "current" or offer.collection_state != "current":
            return skip("retained_or_failed_offer")
        old_price, new_price = amount(event["old_price"]), amount(event["new_price"])
        if old_price is None or new_price is None:
            return skip("missing_or_invalid_price")
        if (old["price"]["currency"] != event["currency"] or captured["price"]["currency"] != event["currency"]
                or offer.price.currency != event["currency"]):
            return skip("currency_changed")
        if amount(old["price"]["amount"]) != old_price or amount(captured["price"]["amount"]) != new_price:
            return skip("event_price_evidence_mismatch")
        if ((event["kind"] == "inventory_changed" and old_price != new_price)
                or (event["kind"] == "price_changed" and old_price == new_price)):
            return skip("event_kind_evidence_mismatch")
        if offer.price.amount != new_price:
            return skip("current_price_changed")
        if event.get("old_stock") != old["stock"] or event["stock"] != captured["stock"]:
            return skip("event_stock_evidence_mismatch")
        if offer.stock != "in_stock" or captured["stock"] != "in_stock":
            return skip("current_stock_not_in_stock")
        observed, prior = timestamp(event["observed_at"]), timestamp(old["fetched_at"])
        fetched, captured_at = timestamp(offer.fetched_at), timestamp(captured["fetched_at"])
        if (not observed or not prior or not fetched or captured_at != observed
                or not prior < observed <= fetched <= now):
            return skip("invalid_observation_order")
        if (now - fetched).total_seconds() > STOCK_MAX_AGE_SECONDS:
            return skip("stale_offer")
        if offer.price_valid_until:
            try:
                if date.fromisoformat(offer.price_valid_until) < now.date():
                    return skip("expired_price")
            except ValueError:
                return skip("invalid_price_expiry")
        source = sources.get(offer.source_code)
        status = health.get(offer.source_code)
        if not source or source.get("enabled") is not True:
            return skip("source_not_enabled")
        if (not isinstance(status, dict) or status.get("source_code") != offer.source_code
                or status.get("status") != "success" or status.get("errors") != []):
            return skip("source_not_healthy")
        attempted = timestamp(status.get("attempted_at"))
        if not attempted or not fetched <= attempted <= now or (now - attempted).total_seconds() > STOCK_MAX_AGE_SECONDS:
            return skip("source_verification_stale_or_incoherent")
        domains = crawls.get(offer.source_code, {}).get("domains", [])
        hosts = {x for x in domains if isinstance(x, str)} if isinstance(domains, list) else set()
        if safe_https(source.get("base_url")):
            hosts.add(urlsplit(source["base_url"]).hostname)
        if not hosts or not safe_https(offer.url, hosts, product=True):
            return skip("unsafe_or_unbound_product_url")
        route = routes.get(offer.offer_id)
        if (not route or not all(re.fullmatch(r"[0-9a-f]{20}", x) for x in route)
                or not safe_https(HOMEPAGE_URL, {"howard9088.github.io"})):
            return skip("missing_internal_reference")
        changes = []
        if new_price < old_price:
            changes.append("price_drop")
        if event.get("old_stock") == "out_of_stock" and captured["stock"] == "in_stock":
            changes.append("restock")
        if not changes:
            return skip("not_price_drop_or_proven_restock")
        # A manufacturer model/color or one exact source product page binds sizes.
        family = ident.mpn or offer.family_hint or offer.url.split("?", 1)[0]
        group = {"brand": ident.brand, "model": ident.model, "manufacturer_model": ident.mpn,
                 "family": family, "color": ident.color, "year": ident.year, "gender": ident.gender,
                 "source_code": offer.source_code, "market": offer.sales_region,
                 "currency": offer.price.currency, "old_price": display_amount(old_price),
                 "new_price": display_amount(new_price), "changes": changes}
        key = hashlib.sha256(json.dumps(group, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":")).encode()).hexdigest()
        return {"draft_key": key, "group": group, "event_key": event["event_key"],
                "event_id": event["id"], "offer_id": offer.offer_id, "name": offer.name,
                "source_name": offer.source_name, "size": ident.size, "product_url": offer.url,
                "image_url": offer.image if safe_https(offer.image) else None,
                "product_id": route[0], "variant_id": route[1], "old_stock": event.get("old_stock"),
                "current_stock": offer.stock, "observed_at": observed.isoformat(),
                "verified_at": fetched.isoformat(), "source_verified_at": attempted.isoformat(),
                "valid_until": (fetched + timedelta(seconds=STOCK_MAX_AGE_SECONDS)).isoformat()}, None

    @staticmethod
    def _package(key: str, candidates: list[dict], created_at: str, now: datetime) -> dict:
        candidates.sort(key=lambda row: (row["size"], row["offer_id"]))
        first, group = candidates[0], candidates[0]["group"]
        sizes = sorted({row["size"] for row in candidates})
        labels = {"price_drop": "降价", "restock": "补货"}
        title = " / ".join(labels[x] for x in group["changes"]) + "：" + first["name"]
        price = group["currency"] + " " + group["new_price"]
        price_text = (group["currency"] + " " + group["old_price"] + " → " + price
                      if "price_drop" in group["changes"] else "当前商品参考价：" + price)
        lines = [title, "配色：" + group["color"] + "；本次核实尺码：" + "、".join(sizes),
                 "来源：" + first["source_name"] + "；市场：" + group["market"], price_text,
                 "核实时间（UTC）：" + min(row["verified_at"] for row in candidates)]
        lines.extend("商家商品页：" + url for url in sorted({row["product_url"] for row in candidates}))
        lines += ["BikeHunt 网站入口：" + HOMEPAGE_URL,
                  "商品价格及库存会变化，以商家结账时为准；运费、税费、配送与支付条件须另行核对。"]
        return {"schema_version": 1, "draft_key": key, "status": "pending_review",
                "publication_state": "not_published", "created_at": created_at,
                "checked_at": now.isoformat(), "valid_until": min(row["valid_until"] for row in candidates),
                "review_required": True, "homepage_url": HOMEPAGE_URL,
                "reference_note": "网站入口为首页；product_id / variant_id 是本地精确核对标识，不是可点击的商品深链。",
                "group": group, "sizes": sizes, "evidence": candidates, "draft_text": "\n".join(lines)}

    def prepare(self, *, now: datetime | None = None, since: datetime | None = None,
                until: datetime | None = None) -> dict:
        now = timestamp(now or datetime.now(timezone.utc))
        if now is None:
            raise ValueError("Current time requires a timezone")
        if (since is None) != (until is None):
            raise ValueError("Historical review requires both --since and --until")
        explicit_window = since is not None
        if explicit_window:
            since, until = timestamp(since), timestamp(until)
            if not since or not until or not since < until <= now or until - since > MAX_WINDOW:
                raise ValueError("Review window must be timezone-aware, in the past, and at most seven days")
        offers_list = OfferRepository(self.root / "data").load()
        offers = {row.offer_id: row for row in offers_list}
        catalog = ComparisonCatalog(offers_list, FxSnapshot(snapshot_id="local-reference", rates={}), now)
        routes = {offer.offer_id: (pid, catalog._variant_id(variant))
                  for pid, variants in catalog.families.items() for variant in variants for offer in variant}
        sources, crawls, health = self._sources()
        with self.store.connect() as event_db:
            # One snapshot binds selection, latest-state supersession and suppression.
            event_db.execute("BEGIN")
            events = [dict(row) for row in event_db.execute("SELECT * FROM events ORDER BY id")]
            suppressed = {row[0] for row in event_db.execute("SELECT event_key FROM suppressed_events")}
            cursor = event_db.execute("SELECT MAX(COALESCE((SELECT MAX(id) FROM events),0), "
                "COALESCE((SELECT seq FROM sqlite_sequence WHERE name='events'),0))").fetchone()[0]
        event_by_key = {row["event_key"]: row for row in events}
        latest_rows = {}
        for row in events:
            observed = timestamp(row["observed_at"])
            if observed is None:
                continue
            order = observed, row["id"]
            if order > latest_rows.get(row["offer_id"], (datetime.min.replace(tzinfo=timezone.utc), 0)):
                latest_rows[row["offer_id"]] = order
        latest = {row["offer_id"]: row["event_key"] for row in events
                  if (timestamp(row["observed_at"]), row["id"]) == latest_rows.get(row["offer_id"])}
        db = self._connect()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                state = db.execute("SELECT * FROM state WHERE id=1").fetchone()
                initialized = state is None
                if initialized:
                    db.execute("INSERT INTO state VALUES (1,?,?)", (now.isoformat(), cursor))
                    started_at, previous_cursor = now, cursor
                else:
                    started_at, previous_cursor = timestamp(state["started_at"]), state["cursor"]
                    if started_at is None or cursor < previous_cursor:
                        raise ValueError("Local event history moved backward; preserve the queue and inspect the history")
                selected, skipped = [], Counter()
                for row in events:
                    observed = timestamp(row["observed_at"])
                    if explicit_window:
                        if observed and since <= observed <= until:
                            selected.append(row)
                    elif not initialized and row["id"] > previous_cursor:
                        if observed and observed >= started_at:
                            selected.append(row)
                        else:
                            skipped["before_monitoring_start"] += 1
                existing = {row["draft_key"]: dict(row) for row in db.execute("SELECT * FROM drafts")}
                members = {key: set(json.loads(row["member_keys"])) for key, row in existing.items()}
                evaluated = {}
                def evaluate(row):
                    key = row["event_key"]
                    if key not in evaluated:
                        evaluated[key] = self._candidate(row, offers, routes, latest, suppressed, sources, crawls, health, now)
                    return evaluated[key]
                for event in selected:
                    candidate, reason = evaluate(event)
                    if candidate:
                        members.setdefault(candidate["draft_key"], set()).add(event["event_key"])
                    else:
                        skipped[reason] += 1
                created = updated = invalidated = 0
                packages = []
                for key, keys in sorted(members.items()):
                    candidates, reasons = [], Counter()
                    for event_key in sorted(keys):
                        event = event_by_key.get(event_key)
                        candidate, reason = evaluate(event) if event else (None, "event_missing")
                        if candidate and candidate["draft_key"] == key:
                            candidates.append(candidate)
                        else:
                            reasons[reason or "transition_changed"] += 1
                    old_row = existing.get(key)
                    created_at = old_row["created_at"] if old_row else now.isoformat()
                    if candidates:
                        package = self._package(key, candidates, created_at, now)
                    else:
                        package = json.loads(old_row["package_json"])
                        package.update(status="invalidated", checked_at=now.isoformat(),
                            invalidation_reasons=dict(reasons),
                            draft_text="[已失效，勿发布] 当前证据未通过复核：" + "、".join(sorted(reasons)))
                    previous = json.loads(old_row["package_json"]) if old_row else None
                    if not previous:
                        created += 1
                    elif package["status"] == "invalidated" and previous["status"] != "invalidated":
                        invalidated += 1
                    elif {k: v for k, v in package.items() if k != "checked_at"} != {k: v for k, v in previous.items() if k != "checked_at"}:
                        updated += 1
                    db.execute("INSERT INTO drafts VALUES (?,?,?,?) ON CONFLICT(draft_key) DO UPDATE SET "
                               "member_keys=excluded.member_keys,package_json=excluded.package_json",
                               (key, created_at, json.dumps(sorted(keys)), json.dumps(package, ensure_ascii=False)))
                    packages.append(package)
                db.execute("UPDATE state SET cursor=? WHERE id=1", (max(cursor, previous_cursor),))
                report = {"schema_version": 1, "mode": "local_drafts_only", "initialized": initialized,
                          "started_at": started_at.isoformat(), "cursor": cursor,
                          "window": {"since": since.isoformat(), "until": until.isoformat()} if explicit_window else None,
                          "selected_events": len(selected), "created": created, "updated": updated,
                          "invalidated": invalidated, "skipped": dict(sorted(skipped.items())),
                          "pending_review": sum(p["status"] == "pending_review" for p in packages),
                          "network_requests": 0, "published": 0, "output": str(self.output)}
            # SQLite is authoritative. A failed export can be regenerated on the next run.
            for package in packages:
                folder = self.output / "drafts" / package["draft_key"]
                atomic_json(folder / "package.json", package)
                text = ("[待人工复核；尚未发布]\n" if package["status"] == "pending_review" else "") + package["draft_text"] + "\n"
                temporary = folder / "draft.txt.tmp"
                temporary.write_text(text, encoding="utf-8")
                temporary.replace(folder / "draft.txt")
            atomic_json(self.output / "queue.json", {"report": report, "drafts": packages})
            atomic_json(self.output / "last_run.json", report)
            return report
        finally:
            db.close()
