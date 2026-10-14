"""站点规则采集、中文摘要与版本管理；原文变化后停止沿用旧结论。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field

from app.catalog.storage import atomic_json
from app.collectors.transport import PublicPageFetcher


class RuleDocument(BaseModel):
    key: str
    title_zh: str
    url: str
    content_hash: str
    checked_at: datetime
    summary_zh: list[str] = Field(default_factory=list)
    state: Literal["translated", "pending_translation", "changed", "failed"]
    translated_hash: str | None = None


class RuleBook(BaseModel):
    source_code: str
    name: str
    version: int = 0
    checked_at: datetime | None = None
    documents: list[RuleDocument] = Field(default_factory=list)


class PolicyRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.folder = root / "data" / "rules"
        self.raw = root / "storage" / "policy_raw"

    def get(self, code: str, name: str = "") -> RuleBook:
        if not re.fullmatch(r"[a-z0-9_]+", code):
            raise ValueError("Invalid source code")
        path = self.folder / f"{code}.json"
        if not path.exists():
            return RuleBook(source_code=code,name=name or code)
        try:
            return RuleBook.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.debug("规则尚未采集 {} {}", code, type(exc).__name__)
            return RuleBook(source_code=code, name=name or code)

    def capture(self, code: str, name: str, key: str, title: str, url: str,
                text: str, checked_at: datetime) -> RuleDocument:
        """固化正文指纹；相同正文只更新时间，变更保留上一份中文并标记待复核。"""
        if len(text.strip()) < 80:
            raise ValueError("Policy body incomplete; do not publish a title-only page")
        if not re.fullmatch(r"[a-z0-9_]+", key):
            raise ValueError("Invalid document key")
        normalized = re.sub(r"\s+", " ", text).strip()
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        book = self.get(code, name)
        existing = next((d for d in book.documents if d.key == key), None)
        changed = bool(existing and existing.content_hash != digest)
        document = RuleDocument(
            key=key, title_zh=title, url=url, content_hash=digest,
            checked_at=checked_at, summary_zh=existing.summary_zh if existing else [],
            translated_hash=existing.translated_hash if existing else None,
            state="changed" if changed else existing.state if existing else "pending_translation",
        )
        book.documents = [d for d in book.documents if d.key != key] + [document]
        book.checked_at = checked_at
        book.name = name
        if existing is None or changed:
            book.version += 1
        raw_document = {
            "url": url, "checked_at": checked_at.isoformat(), "content_hash": digest, "text": text,
        }
        atomic_json(self.root / "storage" / "policy_history" / code / f"{key}_{digest}.json", raw_document)
        atomic_json(self.raw / f"{code}_{key}.json", raw_document)
        atomic_json(self.folder / f"{code}.json", book.model_dump(mode="json"))
        return document

    def translate(self, code: str, key: str, expected_hash: str,
                  summary_zh: list[str]) -> RuleBook:
        """仅发布与最新正文指纹对应的中文摘要，防止检查期间覆盖新规则。"""
        book = self.get(code)
        document = next(d for d in book.documents if d.key == key)
        if document.content_hash != expected_hash:
            raise ValueError("Source changed while translating; reread latest source")
        if not summary_zh or not all(re.search(r"[\u4e00-\u9fff]", line) for line in summary_zh):
            raise ValueError("Chinese summary is required")
        document.summary_zh = summary_zh
        document.translated_hash = expected_hash
        document.state = "translated"
        atomic_json(self.folder / f"{code}.json", book.model_dump(mode="json"))
        return book


def collect_rules(root: Path, source_code: str | None = None) -> dict:
    """用 Scrapling 采集配置内规则；失败保留可复盘的上一版。"""
    config = json.loads((root / "data" / "rule_sources.json").read_text(encoding="utf-8"))
    repository = PolicyRepository(root)
    results = []
    for source in config:
        if source_code and source["code"] != source_code:
            continue
        fetcher = PublicPageFetcher(set(source["domains"]))
        for entry in source["documents"]:
            try:
                page = fetcher.fetch(entry["url"], dynamic=entry.get("dynamic", False))
                nodes = page.css(entry.get("selector", "main"))
                texts = [str(n.get_all_text(separator="\n", strip=True)) for n in nodes]
                text = max(texts, key=len) if texts else str(page.get_all_text(separator="\n", strip=True))
                if len(text) < 80 and entry.get("allow_dynamic", False):
                    page = fetcher.fetch(entry["url"], dynamic=True)
                    text = str(page.get_all_text(separator="\n", strip=True))
                for marker in ("\nLatest news", "\nWas this article helpful?", "\n我们使用 Cookie"):
                    text = text.split(marker, 1)[0]
                if entry.get("start_marker"):
                    if entry["start_marker"] not in text:
                        raise ValueError("Policy section start missing")
                    text = text.split(entry["start_marker"],1)[1]
                if entry.get("end_marker"):
                    if entry["end_marker"] not in text:
                        raise ValueError("Policy section end missing")
                    text = text.split(entry["end_marker"],1)[0]
                document = repository.capture(source["code"], source["name"], entry["key"],
                                              entry["title_zh"], entry["url"], text,
                                              datetime.now(timezone.utc))
                results.append({"source": source["code"], "key": entry["key"], "state": document.state})
            except Exception as exc:
                logger.error("规则采集失败 {} {} {}", source["code"], entry["key"], type(exc).__name__)
                results.append({"source": source["code"], "key": entry["key"], "state": "failed", "error": str(exc)[:200]})
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "results": results}
