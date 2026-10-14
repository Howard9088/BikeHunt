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
                stock TEXT NOT NULL, observed_at TEXT NOT NULL, url TEXT NOT NULL)""")

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
                     new_price,currency,stock,observed_at,url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key,kind,offer.source_code,offer.source_name,offer.offer_id,title_zh(offer.name),
                     category_of(offer.name),str(old.price.amount) if old and old.price.currency==offer.price.currency else None,
                     str(offer.price.amount),offer.price.currency,offer.stock,observed,offer.url))
                if cursor.rowcount:
                    emitted.append(dict(db.execute("SELECT * FROM events WHERE id=?",(cursor.lastrowid,)).fetchone()))
        return emitted

    def latest(self, after: int = 0, limit: int = 30, category: str = "all") -> list[dict]:
        with self.connect() as db:
            query = "SELECT * FROM events WHERE id>?"
            params: list = [after]
            if category != "all":
                query += " AND category=?"
                params.append(category)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(min(100,max(1,limit)))
            return [dict(row) for row in db.execute(query,params).fetchall()]

    def cursor(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]

    def pending(self, after: int, limit: int = 100) -> list[dict]:
        """从最早未处理事件开始读取，避免批量刷新漏掉 100 条之后的更新。"""
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM events WHERE id>? ORDER BY id ASC LIMIT ?", (after, limit)).fetchall()]
