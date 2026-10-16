"""来源快照读取、旧 MAAP 格式兼容与原子写入。"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from app.catalog.models import Offer
from app.collectors.parsers import (
    evidence, manufacturer_identity, money, offer_id, stock_status,
)


def atomic_json(path: Path, payload) -> None:
    """先写临时文件后替换，避免查询读到半写入的快照。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class OfferRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def sources(self) -> list[dict]:
        try:
            return json.loads((self.data_dir / "sources.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("来源清单读取失败 {}", exc)
            return []

    def load(self) -> list[Offer]:
        """逐条验证并隔离坏记录；一个来源损坏不影响其他来源。"""
        rows: list[Offer] = []
        for path in sorted((self.data_dir / "offers").glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                for item in payload.get("offers", []):
                    try:
                        row = Offer.model_validate(item)
                        # Failed refreshes preserve historical values without presenting them as current stock.
                        status_path = self.data_dir / "collection_status" / (row.source_code + ".json")
                        try:
                            status = json.loads(status_path.read_text(encoding="utf-8"))
                            attempted = datetime.fromisoformat(status.get("attempted_at", ""))
                            failed_urls = {str(error.get("url", "")).split("?", 1)[0]
                                           for error in status.get("errors", [])}
                            failed = (status.get("status") == "failed"
                                      or row.url.split("?", 1)[0] in failed_urls
                                      or (row.collection_url or '').split('?', 1)[0] in failed_urls)
                            if failed and (row.fetched_at is None or attempted > row.fetched_at):
                                row = row.model_copy(update={"collection_state": "retained"})
                        except (OSError, ValueError, TypeError):
                            pass
                        rows.append(row)
                    except (ValidationError, TypeError) as exc:
                        logger.warning("隔离无效报价 {} {}", path.name, exc)
            except (OSError, json.JSONDecodeError, AttributeError) as exc:
                logger.error("来源快照不可读 {} {}", path.name, exc)
        # 使用实际 URL 去重：新版逐规格抓取替代旧版同页第一规格缓存。
        refreshed_urls = {row.url.split("?", 1)[0] for row in rows if row.source_code == "maap"}
        source = next((s for s in self.sources() if s["code"] == "maap"),
                      {"code": "maap", "name": "MAAP 官网"})
        try:
            old = json.loads((self.data_dir / "products_maap.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = []
        for item in old:
            try:
                if item["url"] in refreshed_urls:
                    continue
                quoted = money(item.get("price"), item.get("currency"))
                if quoted is None:
                    continue
                sku = item.get("sku", "")
                rows.append(Offer(
                    offer_id=offer_id("maap", item["url"], sku), source_code="maap",
                    source_name=source["name"],
                    identity=manufacturer_identity(item.get("brand", "MAAP"), item["name"], sku),
                    name=item["name"], url=item["url"], image=item.get("image"), price=quoted,
                    # 旧 JSON 未记录采集时间及原价币种，不能伪造。
                    original_price=None, stock=stock_status(item.get("availability")),
                    data_kind="legacy_cache", fetched_at=None,
                    shipping_to_china=evidence(source, "china_shipping"),
                    china_issued_card=evidence(source, "china_credit_card"),
                    identity_evidence="旧 MAAP 官网 SKU；采集时间未记录",
                ))
            except (KeyError, TypeError, ValidationError) as exc:
                logger.warning("隔离旧报价 {}", exc)
        from app.source_rules import apply_source_rules
        sources = {s["code"]: s for s in self.sources()}
        return [apply_source_rules(row, sources.get(row.source_code, {}), self.data_dir)
                for row in {row.offer_id: row for row in rows}.values()]

    def save(self, code: str, offers: list[Offer], fetched_at: datetime,
             errors: list[dict], coverage: dict | None = None) -> None:
        """同页成功替换、失败页面保留旧数据；完全失败不覆盖有效快照。"""
        existing = [row for row in self.load() if row.source_code == code
                    and row.data_kind != "legacy_cache"]
        success_urls = {(row.collection_url or row.url).split("?", 1)[0] for row in offers}
        merged = [row for row in existing
                  if (row.collection_url or row.url).split("?", 1)[0] not in success_urls]
        merged.extend(offers)
        if offers:
            atomic_json(self.data_dir / "offers" / f"{code}.json", {
                "source_code": code, "collected_at": fetched_at.isoformat(),
                "offers": [row.model_dump(mode="json") for row in merged],
            })
            from app.updates import UpdateStore
            UpdateStore(self.data_dir.parent).capture(existing, offers)
        atomic_json(self.data_dir / "collection_status" / f"{code}.json", {
            "source_code": code, "attempted_at": fetched_at.isoformat(),
            "new_offer_count": len(offers), "retained_offer_count": len(merged),
            "coverage": coverage,
            "errors": errors, "status": "success" if offers and not errors else
            "partial" if offers else "failed",
        })

