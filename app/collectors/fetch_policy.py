"""抓取策略与可追溯页面；普通请求和浏览器共享同一数据契约。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FetchPolicy(BaseModel):
    """控制单个来源的渲染方式、等待条件及发现上限。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["static", "dynamic", "auto"] = "static"
    wait_selector: str | None = None
    timeout_ms: int = Field(default=30000, ge=1000, le=60000)
    max_pages: int = Field(default=3, ge=1, le=20)
    max_products: int = Field(default=20, ge=1, le=100)


@dataclass
class CapturedPage:
    """保留实际 HTML、HTTP 结果、渲染方式和每个被选中规格的页面证据。"""

    body: bytes
    status: int
    url: str
    headers: dict
    fetch_mode: Literal["static", "dynamic"]
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    variant_pages: list[bytes] = field(default_factory=list)

    @property
    def evidence_sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


def source_policy(settings: dict) -> FetchPolicy:
    """兼容已有 dynamic 布尔配置，显式 fetch_policy 优先。"""
    return FetchPolicy.model_validate(
        settings.get("fetch_policy")
        or {"mode": "dynamic" if settings.get("dynamic") else "static"}
    )
