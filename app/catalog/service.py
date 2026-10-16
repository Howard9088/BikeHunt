"""后端唯一同款匹配与排序接口；不依赖前端自行算价。"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from app.catalog.models import (
    ColorChoice, ComparedOffer, FxSnapshot, Money, Offer, ProductCard, ProductComparison, VariantChoice,
)
from app.browse_taxonomy import browse_classification
from app.public_visibility import public_product
from app.localization import category_of, title_zh
from app.fit import garment_gender
from app.landed import convert_money, estimate_landed_cost, is_domestic_official_offer

QUOTE_MAX_AGE_SECONDS = 86400
STOCK_MAX_AGE_SECONDS = 3600
EVIDENCE_MAX_AGE_SECONDS = 30 * 86400


def normalized(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def same_variant(left: Offer, right: Offer) -> bool:
    """只用可靠标识合并；相似标题与商家 SKU 不能证明同款。"""
    a, b = left.identity, right.identity
    if normalized(a.brand) != normalized(b.brand):
        return False
    for field in ("size", "color", "year", "gender"):
        av, bv = normalized(getattr(a, field)), normalized(getattr(b, field))
        if av and bv and av != bv:
            return False
    if a.gtin and b.gtin:
        return a.gtin.zfill(14) == b.gtin.zfill(14)
    if a.mpn and b.mpn and normalized(a.mpn) == normalized(b.mpn):
        # 同一款服装缺失尺码不能与已知尺码混为一个 SKU。
        return normalized(a.size) == normalized(b.size)
    return left.offer_id == right.offer_id


def convert(value: Money | None, fx: FxSnapshot) -> Decimal | None:
    return convert_money(value, fx)


def _age(timestamp: datetime | None, now: datetime) -> float:
    if timestamp is None or timestamp.tzinfo is None:
        return float("inf")
    return (now - timestamp).total_seconds()


def _price_valid(value: str | None, now: datetime) -> bool:
    """公开有效期按日期含当天处理，无效日期不能用于现货选择。"""
    if value is None:
        return True
    try:
        return date.fromisoformat(value) >= now.date()
    except ValueError:
        return False


def compare_offer(offer: Offer, fx: FxSnapshot, now: datetime) -> ComparedOffer:
    """所有成本按传入的同一快照换算，缺项保持 None。"""
    landed = estimate_landed_cost(offer, fx, now)
    costs = {component.key: component for component in landed.components}
    product, shipping, tax = (costs[key].cny if key in costs else None
                              for key in ("product", "shipping", "tax"))
    domestic = is_domestic_official_offer(offer)
    total = landed.quoted_total_cny
    reasons: list[str] = []
    for check, label in ((offer.shipping_to_china, "境内配送" if domestic else "直邮中国"),):
        if check.status != "yes":
            reasons.append(label + ("不支持" if check.status == "no" else "待核实"))
        elif not 0 <= _age(check.checked_at, now) <= EVIDENCE_MAX_AGE_SECONDS:
            reasons.append(label + "核实记录已过期")
    card = offer.china_issued_card
    networks = offer.card_networks_evidence
    known_networks = {"visa", "mastercard", "american express", "amex", "jcb", "unionpay", "discover", "diners club"}
    network_supported = (bool(known_networks.intersection(x.casefold() for x in offer.accepted_card_networks))
                         and networks.status == "yes"
                         and 0 <= _age(networks.checked_at, now) <= EVIDENCE_MAX_AGE_SECONDS)
    if card.status == "no":
        reasons.append("中国发行信用卡不支持")
    elif card.status == "yes" and not 0 <= _age(card.checked_at, now) <= EVIDENCE_MAX_AGE_SECONDS:
        reasons.append("中国发行信用卡核实记录已过期")
    elif card.status != "yes" and not network_supported:
        reasons.append("银行卡支付条件待核实")
    if offer.collection_state == "retained":
        reasons.append("最近采集失败；保留历史报价，库存待重新核实")
    if offer.stock != "in_stock":
        reasons.append("已售罄" if offer.stock == "out_of_stock" else "库存待核实")
    if offer.stock == "in_stock" and not 0 <= _age(offer.fetched_at, now) <= STOCK_MAX_AGE_SECONDS:
        reasons.append("库存核实已过期；等待重新核实")
    if not 0 <= _age(offer.fetched_at, now) <= QUOTE_MAX_AGE_SECONDS:
        reasons.append("报价已过期" if offer.fetched_at else "旧缓存未记录采集时间")
    if offer.price_valid_until:
        try:
            if date.fromisoformat(offer.price_valid_until) < now.date():
                reasons.append("价格有效期已结束")
        except ValueError:
            reasons.append("价格有效期格式无效")
    if product is None:
        reasons.append("商品币种汇率缺失")
    if shipping is None:
        reasons.append("中国运费待确认" if offer.shipping is None else "运费币种汇率缺失")
    if tax is None and not domestic:
        reasons.append("中国进口税包含／预缴依据待核实" if offer.import_tax_handling != "unknown"
                       else "税费待确认" if offer.tax is None else "税费币种汇率缺失")
    if domestic and not landed.complete:
        reasons.append("境内配送与结算总额待确认")
    if not domestic and not landed.complete and all(value is not None for value in (product, shipping, tax)):
        reasons.append("运费与清关等总费用待确认")
    if fx.stale:
        reasons.append("汇率为过期缓存")
    reasons.extend(offer.purchase_requirements)
    discount = None
    if (offer.collection_state != "retained" and offer.data_kind == "live_snapshot"
            and 0 <= _age(offer.fetched_at, now) <= QUOTE_MAX_AGE_SECONDS
            and _price_valid(offer.price_valid_until, now)
            and offer.original_price and offer.original_price.currency == offer.price.currency
            and offer.original_price.amount > offer.price.amount):
        discount = int(((1 - offer.price.amount / offer.original_price.amount) * 100)
                       .quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return ComparedOffer(offer=offer, product_cny=product, shipping_cny=shipping,
                         tax_cny=tax, total_cny=total, eligible=not reasons,
                         reasons=reasons, fx_snapshot_id=fx.snapshot_id,
                         discount_pct=discount, landed_cost=landed)


def _identifier(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:20]


class ComparisonCatalog:
    def __init__(self, offers: list[Offer], fx: FxSnapshot,
                 now: datetime | None = None, *, public_only: bool = False) -> None:
        self.fx = fx
        self.public_only = public_only
        self.hidden_offer_ids: set[str] = set()
        self.now = now or datetime.now(timezone.utc)
        self.families: dict[str, list[list[Offer]]] = {}
        variants: list[list[Offer]] = []
        for offer in sorted(offers, key=lambda row: (row.source_code, row.offer_id)):
            group = next((g for g in variants if all(same_variant(offer, x) for x in g)), None)
            if group is None:
                variants.append([offer])
            else:
                group.append(offer)
        for variant in variants:
            primary = variant[0]
            ident = primary.identity
            gender = garment_gender(primary.name, next((x.identity.gender for x in variant
                                       if x.identity.gender), None), category_of(primary.name))
            if ident.mpn:
                family_key = f"{normalized(ident.brand)}|mpn:{normalized(ident.mpn)}|{normalized(ident.color)}|{gender}"
            else:
                family_key = f"{primary.source_code}|{primary.family_hint or primary.offer_id}|{normalized(ident.color)}"
            self.families.setdefault(_identifier(family_key), []).append(variant)
        if public_only:
            for product_id, family in list(self.families.items()):
                classification = browse_classification(product_id,
                    (offer for variant in family for offer in variant))
                if not public_product(classification._asdict()):
                    self.hidden_offer_ids.update(offer.offer_id for variant in family for offer in variant)
                    del self.families[product_id]

    @staticmethod
    def _variant_id(offers: list[Offer]) -> str:
        ident = offers[0].identity
        key = (f"{normalized(ident.brand)}|{normalized(ident.mpn)}|{normalized(ident.size)}|"
               f"{normalized(ident.color)}|{ident.gtin or ''}|{normalized(ident.year)}")
        if not ident.mpn and not ident.gtin:
            key = offers[0].offer_id
        return _identifier(key)

    def available(self, offer: Offer) -> bool:
        """Keep a reliable last-known stock observation until explicit sold-out.

        This is browsing/merchant access, not a guarantee of today's price,
        stock, payment eligibility, or discount validity.
        """
        return (offer.data_kind == "live_snapshot" and offer.stock == "in_stock"
                and offer.fetched_at is not None and offer.fetched_at.tzinfo is not None
                and _age(offer.fetched_at, self.now) >= 0)

    def current(self, offer: Offer) -> bool:
        return (self.available(offer) and offer.collection_state != "retained"
                and _age(offer.fetched_at, self.now) <= STOCK_MAX_AGE_SECONDS
                and _price_valid(offer.price_valid_until, self.now))

    def discounted(self, offer: Offer) -> bool:
        """A merchant's same-variant price pair, never a historical price drop."""
        return (self.available(offer) and offer.collection_state != "retained"
                and _age(offer.fetched_at, self.now) <= QUOTE_MAX_AGE_SECONDS
                and _price_valid(offer.price_valid_until, self.now)
                and offer.original_price is not None
                and offer.original_price.currency == offer.price.currency
                and offer.original_price.amount > offer.price.amount > 0)

    @staticmethod
    def color_group(offer: Offer) -> str:
        ident = offer.identity
        if normalized(ident.brand)=="maap" and ident.mpn and ident.mpn.startswith("MAP-"):
            return "maap|" + ident.mpn.split("_",1)[0]
        return offer.source_code + "|" + (offer.family_hint or offer.offer_id)

    def compare(self, product_id: str, variant_id: str | None = None) -> ProductComparison:
        """返回精确规格的全部渠道；缺失商品或规格抛出 KeyError。"""
        variants = self.families[product_id]
        choices = [VariantChoice(variant_id=self._variant_id(v), size=v[0].identity.size,
                                 source_count=len({x.source_code for x in v}),
                                 in_stock=any(self.available(x) for x in v),
                                 stock_state="in_stock" if any(self.available(x) for x in v) else
                                     "out_of_stock" if all(x.stock == "out_of_stock" for x in v) else "unknown",
                                 product_cny_from=min((convert(x.price,self.fx) for x in v
                                     if self.available(x) and convert(x.price,self.fx) is not None), default=None)) for v in variants]
        size_order = {s: i for i, s in enumerate(("XS", "S", "M", "L", "XL", "XXL", "XXXL"))}
        choices.sort(key=lambda v: size_order.get(v.size or "", 100))
        if variant_id is None:
            chosen = max(choices, key=lambda v: (v.in_stock,
                any(self.current(x) for group in variants if self._variant_id(group) == v.variant_id for x in group),
                v.source_count, -(size_order.get(v.size or "", 100))))
            variant_id = chosen.variant_id
        selected = next((v for v in variants if self._variant_id(v) == variant_id), None)
        if selected is None:
            raise KeyError(variant_id)
        compared = [compare_offer(x, self.fx, self.now) for x in selected]
        compared.sort(key=lambda x: (not self.available(x.offer),
                                     not self.current(x.offer),
                                     not is_domestic_official_offer(x.offer),
                                     not x.eligible,
                                     x.total_cny if x.eligible else Decimal("Infinity"),
                                     x.product_cny if x.product_cny is not None else Decimal("Infinity"),
                                     x.offer.source_code, x.offer.offer_id))
        primary = next((x for x in selected if x.source_code == "maap"), selected[0])
        recommended = next((x.offer.offer_id for x in compared if x.eligible), None)
        colors = [ColorChoice(product_id=pid,color=group[0][0].identity.color or "当前配色",
                             in_stock=any(self.available(x) for v in group for x in v))
                  for pid,group in self.families.items()
                  if self.color_group(group[0][0]) == self.color_group(primary)]
        classification = browse_classification(product_id,
            (offer for variant in variants for offer in variant), name=primary.name)
        return ProductComparison(product_id=product_id, variant_id=variant_id,
                                 identity=primary.identity, name=primary.name, image=primary.image,
                                 name_zh=title_zh(primary.name), category=classification.category,
                                 category_group=classification.category_group,
                                 variants=choices, colors=colors, offers=compared,
                                 recommended_offer_id=recommended, fx=self.fx)

    def search(self, query: str = "", category: str = "all",
               category_group: str | None = None) -> list[ProductCard]:
        """商品是入口；同颜色不同尺码合为一张卡，详情选择具体规格。"""
        cards: list[ProductCard] = []
        terms = normalized(query).split()
        for product_id, variants in self.families.items():
            detail = self.compare(product_id)
            if category != "all" and detail.category != category:
                continue
            if category_group and detail.category_group != category_group:
                continue
            text = normalized(" ".join(x.name + " " + title_zh(x.name) + " " + x.identity.brand + " " + (x.identity.mpn or "")
                                       for v in variants for x in v))
            if not all(term in text for term in terms):
                continue
            recommended = next((x for x in detail.offers if x.eligible), None)
            all_compared = [compare_offer(x,self.fx,self.now) for v in variants for x in v]
            in_stock = [x for x in all_compared if self.available(x.offer)]
            references = in_stock or all_compared
            discounted = [x for x in in_stock if self.discounted(x.offer)]
            reference = (min(discounted, key=lambda x: (x.product_cny if x.product_cny is not None else Decimal("Infinity"), x.offer.offer_id))
                         if discounted else recommended or min(references,key=lambda x: x.product_cny if x.product_cny is not None else Decimal("Infinity")))
            domestic_references = [x for x in in_stock if self.current(x.offer) and is_domestic_official_offer(x.offer)]
            if domestic_references:
                reference = min(domestic_references, key=lambda x: (
                    x.product_cny if x.product_cny is not None else Decimal("Infinity"),
                    x.offer.offer_id))
            reference_variant = next(v for v in variants if any(x.offer_id == reference.offer.offer_id for x in v))
            sources = {x.source_code for v in variants for x in v}
            card = ProductCard(
                product_id=product_id, name=detail.name, brand=detail.identity.brand,
                name_zh=detail.name_zh, category=detail.category,
                category_group=detail.category_group,
                gender=garment_gender(detail.name, next((x.identity.gender for v in variants for x in v
                                    if x.identity.gender), None), detail.category),
                color=detail.identity.color, image=detail.image,
                source_count=len(sources), variant_count=len(variants),
                source_codes=sorted(sources),
                reference_price=reference.offer.price, reference_cny=reference.product_cny,
                reference_source=reference.offer.source_name, reference_url=reference.offer.url, reference_offer_id=reference.offer.offer_id,
                reference_original_price=reference.offer.original_price,
                reference_variant_id=self._variant_id(reference_variant),
                reference_size=reference.offer.identity.size, reference_color=reference.offer.identity.color,
                reference_price_valid_until=reference.offer.price_valid_until,
                reference_data_kind=reference.offer.data_kind,
                discount_pct=reference.discount_pct,
                reference_stock=reference.offer.stock if self.available(reference.offer) or reference.offer.stock != "in_stock" else "unknown", reference_collection_state=reference.offer.collection_state, fetched_at=reference.offer.fetched_at,
                recommended_total_cny=recommended.total_cny if recommended else None,
                status="公开条件与费用已齐" if recommended else
                    "上次核实时有货；请到官网确认" if in_stock and not self.current(reference.offer)
                    else "渠道待核实",
                available_sizes=[v.size for v in detail.variants if v.in_stock and v.size],
                stock_state="in_stock" if in_stock else "out_of_stock" if all(x.offer.stock=="out_of_stock" for x in all_compared) else "unknown",
                purchase_requirements=sorted({r for v in variants for x in v for r in x.purchase_requirements}),
            )
            for source in sorted(sources):
                pool = [x for x in in_stock if x.offer.source_code == source
                        and x.offer.data_kind == "live_snapshot"]
                if not pool:
                    continue
                sale = [x for x in pool if self.discounted(x.offer)]
                chosen = min(sale or pool, key=lambda x: (
                    x.product_cny if x.product_cny is not None else Decimal("Infinity"), x.offer.offer_id))
                selected_variant = next(v for v in variants
                                        if any(x.offer_id == chosen.offer.offer_id for x in v))
                sizes = {x.offer.identity.size for x in pool if x.offer.identity.size}
                card.channel_quotes[source] = card.model_copy(update={
                    "channel_quotes": {},
                    "reference_price": chosen.offer.price,
                    "reference_cny": chosen.product_cny,
                    "reference_source": chosen.offer.source_name,
                    "reference_url": chosen.offer.url,
                    "reference_offer_id": chosen.offer.offer_id,
                    "reference_original_price": chosen.offer.original_price,
                    "reference_variant_id": self._variant_id(selected_variant),
                    "reference_size": chosen.offer.identity.size,
                    "reference_color": chosen.offer.identity.color,
                    "reference_price_valid_until": chosen.offer.price_valid_until,
                    "reference_data_kind": chosen.offer.data_kind,
                    "reference_stock": "in_stock",
                    "reference_collection_state": chosen.offer.collection_state,
                    "fetched_at": chosen.offer.fetched_at,
                    "discount_pct": chosen.discount_pct,
                    "recommended_total_cny": chosen.total_cny if chosen.eligible else None,
                    "status": "渠道现货" if self.current(chosen.offer) else "上次核实时有货；请到官网确认",
                    "purchase_requirements": list(chosen.offer.purchase_requirements),
                    "stock_state": "in_stock",
                    "available_sizes": list(dict.fromkeys(v.size for v in detail.variants if v.size in sizes)),
                    "image": chosen.offer.image or card.image,
                })
            cards.append(card)
        cards.sort(key=lambda x: (x.stock_state != "in_stock", -(x.fetched_at.timestamp() if x.fetched_at else 0),
                                  -x.source_count, normalized(x.name), x.product_id))
        return cards

