"""价格变更持久化与网站消息；同价重复采集不制造降价事件。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from app.catalog.models import Offer
from app.localization import category_of, title_zh
from app.update_views import event_product


class UpdateStore:
    def __init__(self, root: Path) -> None:
        self.path = root / "storage" / "updates.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT UNIQUE NOT NULL,
                kind TEXT NOT NULL, source_code TEXT NOT NULL, source_name TEXT NOT NULL,
                offer_id TEXT NOT NULL, name_zh TEXT NOT NULL, category TEXT NOT NULL,
                old_price TEXT, new_price TEXT NOT NULL, currency TEXT NOT NULL,
                stock TEXT NOT NULL, observed_at TEXT NOT NULL, url TEXT NOT NULL, product_json TEXT)""")
            if "product_json" not in {row[1] for row in db.execute("PRAGMA table_info(events)")}:
                db.execute("ALTER TABLE events ADD COLUMN product_json TEXT")
            columns = {row[1] for row in db.execute("PRAGMA table_info(events)")}
            for name, definition in (("recovered_history", "INTEGER NOT NULL DEFAULT 0"),
                                     ("original_id", "INTEGER"), ("recovery_snapshot_sha256", "TEXT"),
                                     ("old_stock", "TEXT"), ("old_context_json", "TEXT"),
                                     ("current_context_json", "TEXT")):
                if name not in columns:
                    db.execute("ALTER TABLE events ADD COLUMN " + name + " " + definition)
            db.execute("""CREATE TABLE IF NOT EXISTS suppressed_events (
                event_key TEXT PRIMARY KEY, reason TEXT NOT NULL,
                prior_snapshot_sha256 TEXT NOT NULL, affected_snapshot_sha256 TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS event_recovery_runs (
                snapshot_sha256 TEXT PRIMARY KEY, affected_snapshot_sha256 TEXT NOT NULL,
                completed_cursor INTEGER NOT NULL)""")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """事务结束后关闭连接，防止 Windows 锁住 SQLite 文件。"""
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def capture(self, previous: list[Offer], current: list[Offer]) -> list[dict]:
        """金额或币种变化、新报价生成事件；初次发现不伪称降价。"""
        before = {o.offer_id: o for o in previous}
        emitted = []
        with self.connect() as db:
            for offer in {o.offer_id:o for o in current}.values():
                old = before.get(offer.offer_id)
                if old and old.price == offer.price and old.stock == offer.stock:
                    continue
                if not offer.fetched_at:
                    continue
                kind = "new_offer" if old is None else "inventory_changed" if old.price == offer.price else "price_changed"
                observed = offer.fetched_at.isoformat()
                key = hashlib.sha256(f"{offer.offer_id}|{observed}|{offer.price}|{offer.stock}".encode()).hexdigest()
                cursor = db.execute("""INSERT OR IGNORE INTO events
                    (event_key,kind,source_code,source_name,offer_id,name_zh,category,old_price,
                     new_price,currency,stock,observed_at,url,product_json,old_stock,old_context_json,
                     current_context_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key,kind,offer.source_code,offer.source_name,offer.offer_id,title_zh(offer.name),
                     category_of(offer.name),str(old.price.amount) if old and old.price.currency==offer.price.currency else None,
                     str(offer.price.amount),offer.price.currency,offer.stock,observed,offer.url,json.dumps(event_product(offer),ensure_ascii=False),
                     old.stock if old else None, self.context_json(old) if old else None, self.context_json(offer)))
                if cursor.rowcount:
                    emitted.append(self.decode(db.execute("SELECT * FROM events WHERE id=?",(cursor.lastrowid,)).fetchone()))
        return emitted

    def latest(self, after: int = 0, limit: int = 30, category: str = "all") -> list[dict]:
        with self.connect() as db:
            query = "SELECT * FROM events WHERE id>? AND event_key NOT IN (SELECT event_key FROM suppressed_events)"
            params: list = [after]
            if category != "all":
                query += " AND category=?"
                params.append(category)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(min(100,max(1,limit)))
            return [self.decode(row) for row in db.execute(query,params).fetchall()]

    @staticmethod
    def context_json(offer: Offer) -> str:
        """Local transition evidence. Never infer a past market from today's source config."""
        fields = {"offer_id", "source_code", "url", "identity", "price", "stock",
                  "sales_region", "family_hint", "fetched_at", "data_kind", "collection_state"}
        return json.dumps(offer.model_dump(mode="json", include=fields), ensure_ascii=False,
                          sort_keys=True)

    @staticmethod
    def decode(row) -> dict:
        event = dict(row)
        # Exact transition contexts are intentionally local-only. A recovered public
        # row has NULL contexts and cannot become a promotional claim.
        event.pop("old_context_json", None)
        event.pop("current_context_json", None)
        if event.get("recovered_history"):
            event["recovered_history"] = True
        else:
            for name in ("recovered_history", "original_id", "recovery_snapshot_sha256"):
                event.pop(name, None)
        raw = event.pop("product_json", None)
        try:
            product = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            product = None
        if product is not None:
            event["product"] = product
        return event

    def cursor(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT MAX(COALESCE((SELECT MAX(id) FROM events),0), "
                              "COALESCE((SELECT seq FROM sqlite_sequence WHERE name='events'),0))").fetchone()[0]

    def history_recovery(self) -> dict:
        """Published completion identities prevent replay after history ages out."""
        with self.connect() as db:
            return {row["snapshot_sha256"]: {"affected_snapshot_sha256": row["affected_snapshot_sha256"],
                    "completed_cursor": row["completed_cursor"]}
                    for row in db.execute("SELECT * FROM event_recovery_runs ORDER BY snapshot_sha256")}

    def pending(self, after: int, limit: int = 100) -> list[dict]:
        """从最早未处理事件开始读取，避免批量刷新漏掉 100 条之后的更新。"""
        with self.connect() as db:
            return [self.decode(row) for row in db.execute(
                "SELECT * FROM events WHERE id>? AND recovered_history=0 "
                "AND event_key NOT IN (SELECT event_key FROM suppressed_events) ORDER BY id ASC LIMIT ?", (after, limit)).fetchall()]

