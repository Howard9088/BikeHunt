"""个人浏览偏好与官网尺码表匹配；缺少测量依据时不猜测尺码。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import BaseModel, Field, ConfigDict

from app.catalog.models import ProductComparison

Gender = Literal["male", "female", "unisex", "unknown"]
APPAREL = {"jerseys", "bibs", "jackets", "suits"}


def garment_gender(name: str, declared: str | None, category: str) -> Gender:
    """以明确的官方款式或名称判定；中性装备不受男、女筛选限制。"""
    text = (declared or "").casefold().strip()
    if text in {"female", "women", "womens", "women's", "女款"}:
        return "female"
    if text in {"male", "men", "mens", "men's", "男款"}:
        return "male"
    if text in {"unisex", "男女通用"}:
        return "unisex"
    if re.search(r"\bwomen(?:'s|s)?\b|女款", name, re.I):
        return "female"
    if re.search(r"\bmen(?:'s|s)?\b|男款", name, re.I):
        return "male"
    return "unknown" if category in APPAREL else "unisex"


class ShopperProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gender: Literal["all", "male", "female"] = "all"
    height_cm: float | None = Field(default=None, ge=100, le=230, allow_inf_nan=False)
    weight_kg: float | None = Field(default=None, ge=25, le=250, allow_inf_nan=False)
    chest_cm: float | None = Field(default=None, ge=50, le=180, allow_inf_nan=False)


class MeasurementRange(BaseModel):
    minimum: float | None = None
    maximum: float | None = None
    min_inclusive: bool = True
    max_inclusive: bool = True

    def contains(self, value: float) -> bool:
        """保留官网边界重叠；边界处可同时给两个参考规格。"""
        lower = self.minimum is None or value > self.minimum or (self.min_inclusive and value == self.minimum)
        upper = self.maximum is None or value < self.maximum or (self.max_inclusive and value == self.maximum)
        return lower and upper


class SizeBand(BaseModel):
    size: str
    height_cm: MeasurementRange | None = None
    weight_kg: MeasurementRange | None = None
    chest_cm: MeasurementRange | None = None
    description_zh: str


class OfficialSizeChart(BaseModel):
    product_urls: list[str]
    source_url: str
    checked_at: datetime
    gender: Literal["male", "female", "unisex"]
    rows: list[SizeBand]


class FitAssessment(BaseModel):
    state: Literal["not_applicable", "no_chart", "needs_measurement", "reference", "unavailable"]
    note_zh: str
    candidate_sizes: list[str] = Field(default_factory=list)
    required_measurements: list[str] = Field(default_factory=list)
    source_url: str | None = None
    checked_at: datetime | None = None
    chart_rows: list[SizeBand] = Field(default_factory=list)


class FitGuideService:
    def __init__(self, root: Path) -> None:
        self.path = root / "data/fit_guides.json"

    def assess(self, detail: ProductComparison, profile: ShopperProfile,
               now: datetime | None = None) -> FitAssessment:
        """输入当前商品与偏好，仅从新鲜官方尺码范围选出仍有库存的候选。"""
        now = now or datetime.now(timezone.utc)
        if detail.category not in APPAREL:
            return FitAssessment(state="not_applicable", note_zh="这类装备按自身规格选择。")
        try:
            charts = [OfficialSizeChart.model_validate(row) for row in json.loads(self.path.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("尺码表暂不可读 {}", type(exc).__name__)
            charts = []
        urls = {quote.offer.url for quote in detail.offers}
        chart = next((row for row in charts if urls.intersection(row.product_urls)
                      and row.checked_at.tzinfo and 0 <= (now-row.checked_at).total_seconds() <= 30*86400), None)
        if chart is None:
            return FitAssessment(state="no_chart", note_zh="已记住身高、体重；这款完整官网尺码表仍待采集，暂不指定 S/M/L。")
        if profile.gender != "all" and chart.gender not in ("unisex", profile.gender):
            return FitAssessment(state="not_applicable", note_zh="这款与所选男款／女款偏好不符，可返回切换款式。")
        fields = [key for key in ("height_cm", "weight_kg", "chest_cm") if any(getattr(row, key) for row in chart.rows)]
        missing = [key for key in fields if getattr(profile, key) is None]
        common = {"source_url": chart.source_url, "checked_at": chart.checked_at, "chart_rows": chart.rows}
        if missing:
            return FitAssessment(state="needs_measurement", required_measurements=missing,
                note_zh="官网这款按胸围选码。补一个胸围（厘米），就能对照剩余现货；身高、体重已保留。" if missing == ["chest_cm"]
                else "官网尺码表还需要补充对应测量值。", **common)
        candidates = [row.size for row in chart.rows if all(getattr(row, key) is not None
            and getattr(row, key).contains(getattr(profile, key)) for key in fields)]
        available = {row.size for row in detail.variants if row.in_stock}
        stocked = [size for size in candidates if size in available]
        return FitAssessment(state="reference" if stocked else "unavailable", candidate_sizes=stocked,
            note_zh="官网尺码范围对应现货 " + " / ".join(stocked) + "，可作为试穿参考，仍需留意版型。" if stocked
            else "测量值对应的尺码目前没有已核实的现货；其他尺码继续保留供你比较。", **common)
