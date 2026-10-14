"""共享数据契约；金额单位为 currency 对应的货币元。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Money(Record):
    amount: Decimal = Field(ge=0, allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class Evidence(Record):
    status: Literal["yes", "no", "unknown"] = "unknown"
    url: str | None = None
    checked_at: datetime | None = None
    note: str = ""
    scope: Literal["site", "offer"] = "offer"
    content_hash: str | None = None

    @model_validator(mode="after")
    def require_evidence(self) -> Evidence:
        """肯定结论必须附公开依据及核实时间。"""
        if self.status == "yes" and (not self.url or not self.checked_at):
            raise ValueError("Confirmed eligibility requires URL and checked_at")
        return self


class ProductIdentity(Record):
    brand: str
    model: str
    gtin: str | None = None
    mpn: str | None = None
    size: str | None = None
    color: str | None = None
    year: str | None = None
    gender: str | None = None

    @field_validator("gtin")
    @classmethod
    def valid_gtin(cls, value: str | None) -> str | None:
        if not value:
            return None
        if not value.isdigit() or len(value) not in (8, 12, 13, 14):
            raise ValueError("Invalid GTIN length")
        digits = [int(x) for x in value]
        checksum = sum(x * (3 if i % 2 == 0 else 1)
                       for i, x in enumerate(reversed(digits[:-1])))
        if (10 - checksum % 10) % 10 != digits[-1]:
            raise ValueError("Invalid GTIN checksum")
        return value


class Offer(Record):
    offer_id: str
    source_code: str
    source_name: str
    identity: ProductIdentity
    name: str
    url: str
    image: str | None = None
    price: Money
    original_price: Money | None = None
    shipping: Money | None = None
    tax: Money | None = None
    stock: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    shipping_to_china: Evidence = Field(default_factory=Evidence)
    china_issued_card: Evidence = Field(default_factory=Evidence)
    accepted_card_networks: list[str] = Field(default_factory=list)
    card_networks_evidence: Evidence = Field(default_factory=Evidence)
    fetched_at: datetime | None = None
    price_valid_until: str | None = None
    collection_state: Literal["current", "retained"] = "current"
    data_kind: Literal["live_snapshot", "legacy_cache"] = "live_snapshot"
    family_hint: str = ""
    identity_evidence: str = ""
    sales_region: str = ""
    dispatch_origin: str | None = None
    dispatch_origin_evidence: Evidence = Field(default_factory=Evidence)
    purchase_requirements: list[str] = Field(default_factory=list)


class FxSnapshot(Record):
    snapshot_id: str
    rate_date: str | None = None
    fetched_at: datetime | None = None
    rates: dict[str, Decimal]
    source: str = "European Central Bank"
    source_url: str = ""
    stale: bool = False
    note: str = ""


class ComparedOffer(Record):
    offer: Offer
    product_cny: Decimal | None
    shipping_cny: Decimal | None
    tax_cny: Decimal | None
    total_cny: Decimal | None
    eligible: bool
    reasons: list[str]
    fx_snapshot_id: str
    discount_pct: int | None = None


class VariantChoice(Record):
    stock_state: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    variant_id: str
    size: str | None
    source_count: int
    in_stock: bool
    product_cny_from: Decimal | None = None


class ColorChoice(Record):
    product_id: str
    color: str
    in_stock: bool


class ProductComparison(Record):
    product_id: str
    variant_id: str
    identity: ProductIdentity
    name: str
    name_zh: str = ""
    category: str = "accessories"
    image: str | None
    variants: list[VariantChoice]
    colors: list[ColorChoice] = Field(default_factory=list)
    offers: list[ComparedOffer]
    recommended_offer_id: str | None
    fx: FxSnapshot


class ProductCard(Record):
    product_id: str
    name: str
    name_zh: str = ""
    category: str = "accessories"
    gender: Literal["male", "female", "unisex", "unknown"] = "unknown"
    brand: str
    color: str | None
    image: str | None
    source_count: int
    variant_count: int
    source_codes: list[str] = Field(default_factory=list)
    reference_price: Money
    reference_cny: Decimal | None
    reference_source: str
    reference_collection_state: Literal["current", "retained"] = "current"
    reference_stock: Literal["in_stock", "out_of_stock", "unknown"]
    fetched_at: datetime | None
    discount_pct: int | None
    recommended_total_cny: Decimal | None
    status: str
    available_sizes: list[str] = Field(default_factory=list)
    stock_state: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    purchase_requirements: list[str] = Field(default_factory=list)

