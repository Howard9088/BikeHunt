"""Bounded public Shopify catalogs, with independently matched per-variant prices.

All HTTP goes through the caller's PublicPageFetcher (robots, domain allow-list,
throttling and Retry-After). A collection never falls back to the whole shop.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import evidence, money, offer_id, parse_jsonld
from app.collectors.transport import CollectionError, PublicPageFetcher, SourceDeferred
from app.collectors.fetch_policy import source_policy

MAX_PRODUCTS = 25
_SIZE_WORDS = {"size", "taglia", "taille", "maat", "accessory size", "accessoiregrootte"}
_COLOR_WORDS = {"color", "colour", "colore", "couleur", "kleur"}
_SIZE_VALUES = re.compile(r"^(?:[2-6]?X{0,3}[SL]|M|OSFA|OSFM|UNI|ONE SIZE)$", re.I)


@dataclass
class ShopifyCollectionResult:
    offers: list[Offer] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)


def shopify_market_currency(html: str) -> str:
    """Read the active market explicitly; '$' or a configured default is not proof."""
    currencies = set()
    for match in re.finditer(r"\bShopify\.currency\s*=\s*(\{[^;]+?\})\s*;", html):
        try:
            currency = json.loads(match.group(1)).get("active")
            if isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency):
                currencies.add(currency)
        except (ValueError, AttributeError):
            pass
    if len(currencies) != 1:
        raise CollectionError("Shopify active market currency is missing or contradictory")
    return currencies.pop()


def shopify_market_country(html: str) -> str | None:
    countries = set(re.findall(r"\bShopify\.country\s*=\s*['\"]([A-Z]{2})['\"]\s*;", html))
    if len(countries) > 1:
        raise CollectionError("Shopify active market country is contradictory")
    return next(iter(countries), None)


def _catalog_urls(catalog_url: str) -> tuple[str, str]:
    split = urlsplit(catalog_url)
    if (split.scheme != "https" or not split.hostname or split.username or
            split.password or split.query or split.fragment):
        raise CollectionError("Shopify catalog must be a plain HTTPS storefront/collection URL")
    path = split.path.rstrip("/")
    if "/collections/" in path:
        prefix, collection = path.split("/collections/", 1)
        if not re.fullmatch(r"[A-Za-z0-9-]+", collection):
            raise CollectionError("Only one explicitly scoped Shopify collection is supported")
    elif path and not re.fullmatch(r"/[A-Za-z]{2}(?:-[A-Za-z]{2})?", path):
        raise CollectionError("Shopify brand catalog must be the storefront or locale root")
    else:
        prefix = path
    origin = f"{split.scheme}://{split.netloc}"
    return origin + path + "/products.json", origin + prefix + "/products/"


def _product_url(product: dict, products_root: str) -> str:
    handle = product.get("handle")
    if not isinstance(handle, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", handle):
        raise CollectionError("Invalid Shopify product handle")
    return products_root + handle


def _variant_id(url: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get("variant", [])
    return values[0] if len(values) == 1 and values[0].isdigit() else None


def _options(product: dict, variant: dict) -> tuple[str | None, str | None]:
    """Keep multi-item bundle sizes distinct; never invent a size from a SKU."""
    sizes, other, colors = [], [], []
    options = product.get("options", [])
    if not isinstance(options, list):
        raise CollectionError("Shopify product options are malformed")
    for index, option in enumerate(options, start=1):
        if not isinstance(option, dict):
            raise CollectionError("Shopify option must declare its name and position")
        position = option.get("position", index)
        if type(position) is not int or position not in (1, 2, 3):
            raise CollectionError("Invalid Shopify option position")
        name = str(option.get("name", "")).strip()
        value = variant.get(f"option{position}")
        if value is None:
            continue
        value = str(value).strip()
        if not value or (name.casefold() == "title" and value == "Default Title"):
            continue
        choices = option.get("values", [])
        if isinstance(choices, list) and choices and value not in map(str, choices):
            raise CollectionError("Shopify variant option is absent from its declared values")
        label = name.casefold()
        # Some stores accidentally name their size option '3XL'. Only a whole
        # declared option consisting of conventional size labels permits this.
        conventional_sizes = bool(choices) and all(_SIZE_VALUES.fullmatch(str(v)) for v in choices)
        if label in _COLOR_WORDS:
            colors.append(value)
        elif label in _SIZE_WORDS or re.search(r"\b(?:size|taglia|taille|maat)\b", label) or conventional_sizes:
            sizes.append((name, value))
        else:
            other.append((name, value))
    dimensions = sizes + other
    if len(dimensions) == 1:
        size = dimensions[0][1] if sizes else f"{dimensions[0][0]}: {dimensions[0][1]}"
    else:
        size = " / ".join(f"{name}: {value}" for name, value in dimensions) or None
    return size, " / ".join(colors) or None


def _image(product: dict, variant: dict, fallback: str | None, page_url: str) -> str | None:
    featured = variant.get("featured_image") or {}
    images = product.get("images") or []
    candidate = featured.get("src") if isinstance(featured, dict) else None
    if not candidate and images and isinstance(images[0], dict):
        candidate = images[0].get("src")
    candidate = urljoin(page_url, candidate or fallback or "")
    return candidate if urlsplit(candidate).scheme == "https" and candidate != page_url else None


def parse_shopify_product(product: dict, html: str, source: dict, page_url: str,
                          fetched_at: datetime, currency: str | None = None) -> list[Offer]:
    """Match feed variants to same-page JSON-LD by exact Shopify variant ID.

    Missing/mismatched prices fail the product closed. Conflicting stock becomes
    unknown. Merchant SKUs are not promoted to manufacturer IDs. Only validated
    GTINs explicitly published for this exact variant can enter the identity.
    """
    page_currency = shopify_market_currency(html)
    if currency is not None and currency != page_currency:
        raise CollectionError("Shopify product market differs from the catalog market")
    name = product.get("title")
    product_id = str(product.get("id", ""))
    variants = product.get("variants")
    if not isinstance(name, str) or not name.strip() or not product_id.isdigit() or not isinstance(variants, list) or not variants:
        raise CollectionError("Shopify product identity/variants are missing")
    page = urlsplit(page_url)
    verified = {}
    for row in parse_jsonld(html, source, page_url, fetched_at):
        split = urlsplit(row.url)
        vid = _variant_id(row.url)
        if vid and split.hostname == page.hostname and split.path.rstrip("/") == page.path.rstrip("/"):
            if vid in verified and verified[vid].price != row.price:
                raise CollectionError("Contradictory Shopify structured prices for one variant")
            verified[vid] = row
    result, seen = [], set()
    tags = product.get("tags", [])
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",")]
    tags = {str(tag).casefold() for tag in tags}
    genders = {gender for label, gender in {"uomo": "male", "men": "male", "donna": "female",
               "women": "female", "unisex": "unisex"}.items() if label in tags}
    gender = next(iter(genders)) if len(genders) == 1 else None
    years = {tag for tag in tags if re.fullmatch(r"20\d{2}", tag)}
    year = next(iter(years)) if len(years) == 1 else None
    for variant in variants:
        if not isinstance(variant, dict):
            raise CollectionError("Malformed Shopify variant")
        vid = str(variant.get("id", ""))
        if not vid.isdigit() or vid in seen:
            raise CollectionError("Missing or duplicate Shopify variant ID")
        seen.add(vid)
        row = verified.get(vid)
        quoted = money(variant.get("price"), page_currency)
        if row is None or quoted is None or quoted != row.price:
            raise CollectionError(f"Shopify variant {vid}: feed price/currency lacks matching page evidence")
        if variant.get("product_id") is not None and str(variant["product_id"]) != product_id:
            raise CollectionError("Shopify variant belongs to a different product")
        size, color = _options(product, variant)
        brand = (source.get("brand") if source.get("type") == "brand_official" else None) or product.get("vendor") or row.identity.brand
        if not isinstance(brand, str) or not brand.strip():
            raise CollectionError("Shopify product brand is missing")
        identity = ProductIdentity(brand=brand, model=name, size=size, color=color,
                                   gtin=row.identity.gtin, year=year, gender=gender)
        available = variant.get("available")
        feed_stock = "in_stock" if available is True else "out_of_stock" if available is False else "unknown"
        stock = feed_stock if row.stock == feed_stock else "unknown"
        original = money(variant.get("compare_at_price"), page_currency)
        if original and original.amount <= quoted.amount:
            original = None
        url = urlunsplit((page.scheme, page.netloc, page.path, "variant=" + vid, ""))
        result.append(row.model_copy(update={
            "offer_id": offer_id(source["code"], page_url, vid), "identity": identity,
            "name": name, "url": url, "price": quoted, "original_price": original,
            "stock": stock, "image": _image(product, variant, row.image, page_url),
            "family_hint": "shopify:" + product_id,
            "sales_region": f"{shopify_market_country(html) or '地区未核实'} 市场 · {page_currency} 报价；未验证其他市场库存",
            "shipping_to_china": evidence(source, "china_shipping"),
            "china_issued_card": evidence(source, "china_credit_card"),
            "identity_evidence": "官方 Shopify 商品系列；逐规格 ID、价格及币种与商品页 JSON-LD 一致；尺码来自公开选项；商家 SKU 不作为跨站型号"
                + ("；库存证据冲突，待核实" if stock == "unknown" else "；可购买状态与商品页一致"),
        }))
    return result


def _error(url: str, exc: Exception) -> dict:
    result = {"url": url, "error": str(exc)}
    if isinstance(exc, SourceDeferred):
        result["retry_at"] = exc.retry_at.isoformat()
    return result


def collect_shopify_catalog(fetcher: PublicPageFetcher, settings: dict, source: dict,
                            fetched_at: datetime, raw_dir: Path | None = None) -> ShopifyCollectionResult:
    """Collect at most 25 products; preserve detailed failures for snapshot retention.

    Settings: catalog_url (store locale root or exact collection), max_products
    (1..25), optional scope_note. The caller owns repository persistence.
    """
    result = ShopifyCollectionResult()
    catalog_url = settings.get("catalog_url", "")
    limit = settings.get("max_products", MAX_PRODUCTS)
    if type(limit) is not int or not 1 <= limit <= MAX_PRODUCTS:
        result.errors.append({"url": catalog_url, "error": "max_products must be an integer from 1 to 25"})
        return result
    result.coverage = {"method": "shopify_public_feed_plus_product_jsonld", "catalog_url": catalog_url,
        "scope": "collection" if "/collections/" in catalog_url else "brand_catalog",
        "scope_note": settings.get("scope_note", "仅覆盖指定商品系列或官网目录的有界公开样本"),
        "product_limit": limit, "discovered_product_count": 0, "collected_product_count": 0,
        "offer_count": 0, "complete": False, "partial": True}

    captured = {}
    policy = source_policy(settings)

    def fetch_text(url: str, suffix: str, dynamic: bool = False) -> str:
        response = (fetcher.fetch(url, policy=policy.model_copy(update={"mode":"dynamic"}))
                    if dynamic else fetcher.fetch(url))
        final_url = str(getattr(response, "url", url))
        requested, final = urlsplit(url), urlsplit(final_url)
        if (final.scheme != "https" or final.hostname != requested.hostname
                or final.path.rstrip("/") != requested.path.rstrip("/")):
            raise CollectionError("Shopify request redirected outside the exact source/market path: "
                                  + requested.path + " -> " + final.scheme + "://"
                                  + (final.hostname or "") + final.path)
        if raw_dir is not None:
            raw_dir.mkdir(parents=True, exist_ok=True)
            name = source["code"] + "_" + hashlib.sha256(url.encode()).hexdigest()[:16] + suffix
            (raw_dir / name).write_bytes(response.body)
        captured[url] = response
        return response.body.decode("utf-8-sig", errors="replace")

    try:
        feed_base, products_root = _catalog_urls(catalog_url)
        market_html = fetch_text(catalog_url, ".html")
        currency = shopify_market_currency(market_html)
        country = shopify_market_country(market_html)
        feed_url = f"{feed_base}?limit={limit}&page=1"
        payload = json.loads(fetch_text(feed_url, ".json"))
        products = payload.get("products") if isinstance(payload, dict) else None
        if not isinstance(products, list) or not products:
            raise CollectionError("Shopify scoped feed contains no products; old snapshot retained")
        if len(products) > limit:
            raise CollectionError("Shopify server ignored the requested product limit")
        if any(not isinstance(product, dict) for product in products):
            raise CollectionError("Shopify feed contains a malformed product")
        urls = [_product_url(product, products_root) for product in products]
        if len(set(urls)) != len(urls):
            raise CollectionError("Shopify feed contains duplicate product handles")
        result.coverage.update({"feed_url": feed_url, "currency": currency, "market_country": country,
            "discovered_product_count": len(products), "feed_exhausted": len(products) < limit})
    except Exception as exc:
        result.errors.append(_error(catalog_url, exc))
        return result
    for index, (product, url) in enumerate(zip(products, urls)):
        if url in settings.get("excluded_urls", []):
            result.errors.append(_error(url, CollectionError("Collection paused for this URL after an unresolved access failure")))
            continue
        try:
            html = fetch_text(url, ".html")
            product_country = shopify_market_country(html)
            if country and product_country and country != product_country:
                raise CollectionError("Shopify product country differs from catalog market")
            try:
                rows = parse_shopify_product(product, html, source, url, fetched_at, currency)
            except CollectionError:
                if policy.mode != 'auto':
                    raise
                html = fetch_text(url, '.rendered.html', dynamic=True)
                dynamic_country = shopify_market_country(html)
                if country and dynamic_country and country != dynamic_country:
                    raise CollectionError('Rendered product country differs from the catalog market')
                rows = parse_shopify_product(product, html, source, url, fetched_at, currency)
            if not rows:
                raise CollectionError("No validated Shopify variants")
            capture = captured[url]
            result.offers.extend(row.model_copy(update={
                'fetch_mode':getattr(capture, 'fetch_mode', 'static'),
                'evidence_sha256':hashlib.sha256(capture.body).hexdigest(),
                'fetched_at':getattr(capture, 'observed_at', fetched_at)}) for row in rows)
            result.coverage["collected_product_count"] += 1
        except SourceDeferred as exc:
            # No further request on this domain; mark not-yet-refreshed products
            # as failed so the existing repository marks their stock retained.
            result.errors.extend(_error(pending, exc) for pending in urls[index:])
            break
        except Exception as exc:
            result.errors.append(_error(url, exc))
    complete = len(products) < limit and not result.errors
    result.coverage.update({"offer_count": len(result.offers), "complete": complete, "partial": not complete,
        "fetch_mode":policy.mode, "dynamic_offer_count":sum(r.fetch_mode == 'dynamic' for r in result.offers)})
    return result
