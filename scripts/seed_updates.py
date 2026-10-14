"""空缓存优先恢复公开网站事件，保证新的事件 ID 超过已发布游标。"""
from __future__ import annotations

import json
import os
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

SQLITE_MAX_CURSOR = 2**63 - 2
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
EVENT_FIELDS = (
    "id", "event_key", "kind", "source_code", "source_name", "offer_id",
    "name_zh", "category", "old_price", "new_price", "currency", "stock",
    "observed_at", "url",
)


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
    if len({event["id"] for event in events}) != len(events):
        raise ValueError("Public event IDs must be unique")
    if len({event["event_key"] for event in events}) != len(events):
        raise ValueError("Public event keys must be unique")
    if any(event["id"] > cursor for event in events):
        raise ValueError("Public event ID exceeds its cursor")
    return events, cursor


def download_public_events(public_url: str) -> tuple[list[dict], int]:
    """通过 HTTPS 获取并验证网站事件，网络及解析错误最多退避重试三次。"""
    parsed = urlsplit(public_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("BIKEHUNT_PUBLIC_URL requires an HTTPS base URL")
    endpoint = urljoin(public_url.rstrip("/") + "/", "data/site-data.json")
    request = urllib.request.Request(
        endpoint, headers={"User-Agent": "BikeHunt/0.3"},
    )
    context = ssl.create_default_context(cafile=certifi.where())
    for attempt in range(3):
        try:
            with urllib.request.urlopen(
                request, timeout=12, context=context,
            ) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("Public snapshot exceeds the size limit")
            payload = json.loads(body)
            updates = payload["updates"]
            return validate_events(updates["items"], updates["cursor"])
        except Exception as exc:
            logger.warning(
                "公开游标恢复失败 attempt={}/3 {}",
                attempt + 1, type(exc).__name__,
            )
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Public cursor retry attempts exhausted")


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
    """只向空事件库导入公开记录，并保留 SQLite 自增序列的已发布上界。"""
    store = UpdateStore(root)
    existing = store.cursor()
    if existing:
        return {"source": "existing", "restored": 0, "cursor": existing}
    try:
        if public_url:
            try:
                rows, cursor = download_public_events(public_url)
                source = "published"
            except Exception as exc:
                logger.warning("使用仓库公开种子回退 {}", type(exc).__name__)
                rows, cursor = repository_events(root)
                source = "repository"
        else:
            rows, cursor = repository_events(root)
            source = "repository"
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT COALESCE(MAX(id),0) FROM events",
            ).fetchone()[0]
            if existing:
                return {
                    "source": "existing", "restored": 0, "cursor": existing,
                }
            db.executemany(
                "INSERT INTO events (" + ",".join(EVENT_FIELDS) + ") VALUES ("
                + ",".join("?" for _ in EVENT_FIELDS) + ")",
                [tuple(row[field] for field in EVENT_FIELDS) for row in rows],
            )
            sequence = db.execute(
                "SELECT seq FROM sqlite_sequence WHERE name='events'",
            ).fetchone()
            cursor = max(cursor, sequence[0] if sequence else 0)
            if sequence:
                db.execute(
                    "UPDATE sqlite_sequence SET seq=? WHERE name='events'",
                    (cursor,),
                )
            else:
                db.execute(
                    "INSERT INTO sqlite_sequence (name,seq) "
                    "VALUES ('events',?)",
                    (cursor,),
                )
        logger.info(
            "恢复公开事件 source={} rows={} cursor={}",
            source, len(rows), cursor,
        )
        return {"source": source, "restored": len(rows), "cursor": cursor}
    except Exception as exc:
        logger.error("公开事件种子不可恢复 {}", type(exc).__name__)
        raise


if __name__ == "__main__":
    print(json.dumps(restore_public_cursor(
        ROOT, os.environ.get("BIKEHUNT_PUBLIC_URL", ""),
    )))
