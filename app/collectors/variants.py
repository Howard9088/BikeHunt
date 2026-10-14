"""公开页面逐尺码库存提取：Rapha RSC JSON 与 Visma 可见选项。"""
from __future__ import annotations

import json
import re
from datetime import datetime

from loguru import logger
from scrapling.parser import Selector

from app.catalog.models import Offer, ProductIdentity
from app.collectors.parsers import money, offer_id, parse_jsonld

SIZES = {"XX-Small":"XXS", "X-Small":"XS", "Small":"S", "Medium":"M", "Large":"L", "X-Large":"XL", "XX-Large":"XXL"}


def parse_rapha(html: str, source: dict, url: str, fetched_at: datetime) -> list[Offer]:
    """只解析页面已有 JSON，不执行远端 JS；逐规格库存须与可见选项一致。"""
    page = Selector(html)
    base = parse_jsonld(html,source,url,fetched_at)
    if not base:
        return []
    chunks = []
    for script in page.css("script::text").getall():
        if not script.startswith("self.__next_f.push("):
            continue
        try:
            payload,_ = json.JSONDecoder().raw_decode(script.split("push(",1)[1])
            if len(payload)>1 and isinstance(payload[1],str):
                chunks.append(payload[1])
        except (ValueError,TypeError,IndexError):
            logger.debug("跳过不可解析的 Rapha 页面 JSON")
    content = "".join(chunks)
    product = None
    for match in re.finditer(r'\{\s*"region"\s*:\s*"[a-z]+"',content):
        try:
            candidate,_ = json.JSONDecoder().raw_decode(content[match.start():])
            if "variants" in candidate and "initialStockLevels" in candidate:
                product = candidate
                break
        except ValueError:
            continue
    if not product or product.get("isRestricted"):
        return []
    selected_sku = url.rstrip("/").rsplit("/",1)[-1]
    variant = next((v for v in product["variants"] if v.get("sku")==selected_sku),None)
    if not variant:
        return []
    price = money(variant.get("price"),variant.get("currency"))
    if not price or price != base[0].price:
        logger.warning("Rapha JSON-LD 与逐规格价格不一致；暂停发布 {}",url)
        return []
    labels = {i.attrib["value"]:i.attrib.get("aria-label","") for i in page.css('input[name="size"]')}
    stocks = product["initialStockLevels"]
    result = []
    for size in variant.get("sizes",[]):
        sku = size["sku"]
        code = sku[len(selected_sku):]
        label = labels.get(code,"")
        record = stocks.get(sku,{})
        in_stock = record.get("status")=="inStock" and record.get("level",0)>0
        dom_available = bool(label) and "out of stock" not in label.casefold()
        if in_stock != dom_available:
            logger.warning("Rapha 库存与可见尺码冲突，保留为待核实 {} {}",url,code)
            stock = "unknown"
        else:
            stock = "in_stock" if in_stock else "out_of_stock"
        identity = ProductIdentity(brand="Rapha",model=product["title"],mpn=selected_sku,
            size=SIZES.get(size["size"],size["size"]),color=variant.get("color"),
            gender=product.get("gender"),gtin=size.get("barcode"))
        result.append(base[0].model_copy(update={
            "offer_id":offer_id(source["code"],url,sku), "identity":identity, "stock":stock,
            "original_price":money(variant.get("wasPrice"),variant["currency"]),
            "family_hint":selected_sku, "identity_evidence":"Rapha 官网逐尺码 SKU、GTIN、库存 JSON 与可见尺码一致",
            "sales_region":source.get("sales_region",product.get("region","")),
            "purchase_requirements":["RCC 会员专享，需登录本人会员账号"] if product.get("rccProduct") else [],
        }))
    return result


def formatted_money(text: str, currency: str):
    """解析已经标明币种的显示金额；不把逗号小数点丢掉，也不猜测美元种类。"""
    symbols = {"EUR": "€", "GBP": "£", "USD": "$", "CAD": "$", "AUD": "$",
               "NZD": "$", "DKK": "kr", "SEK": "kr", "NOK": "kr"}
    symbol = symbols.get(currency)
    if not symbol or (symbol not in text and currency not in text):
        return None
    value = text.replace(currency, "").replace(symbol, "")
    value = re.sub(r"\s+", "", value)
    if not re.fullmatch(r"[0-9]+(?:[.,][0-9]+)*", value):
        return None
    if "." in value and "," in value:
        decimal = "." if value.rfind(".") > value.rfind(",") else ","
        thousands = "," if decimal == "." else "."
        integer, fraction = value.rsplit(decimal, 1)
        if len(fraction) != 2 or not re.fullmatch(r"[0-9]{1,3}(?:" + re.escape(thousands) + r"[0-9]{3})+", integer):
            return None
        value = integer.replace(thousands, "") + "." + fraction
    elif "." in value or "," in value:
        sep = "." if "." in value else ","
        parts = value.split(sep)
        if len(parts) == 2 and len(parts[1]) == 2:
            value = ".".join(parts)
        elif 1 <= len(parts[0]) <= 3 and all(len(part) == 3 for part in parts[1:]):
            value = "".join(parts)
        else:
            return None
    return money(value, currency)


def parse_visma(html: str, source: dict, url: str, fetched_at: datetime) -> list[Offer]:
    """商品选项独立报价；使用明确的当前市场币种，不套用固定 EUR JSON-LD。"""
    page = Selector(html)
    base = parse_jsonld(html, source, url, fetched_at)
    if not base:
        return []
    currencies = set()
    for script in page.css("script::text").getall():
        currencies.update(re.findall(r"\bapp\.shop\.productCurrency\s*=\s*['\"]([A-Z]{3})['\"]\s*;", script))
    if len(currencies) > 1:
        logger.warning("Visma 当前市场币种冲突 {}", url)
        return []
    currency = next(iter(currencies), base[0].price.currency)
    region = page.css('meta[name="shop-country"]::attr(content)').get("")
    region = region if re.fullmatch(r"[A-Z]{2}", region) else ""
    images = page.css('.product__images .product__image img[src]')
    image = next((node.attrib["src"] for node in images
                  if node.attrib["src"].startswith("https://")
                  and "_crop_" not in node.attrib["src"]), base[0].image)
    labels = {label.attrib.get("for"): label for label in page.css("label[for]")}
    result = []
    seen = set()
    for node in page.css('input[name="purchasableId"]'):
        value = node.attrib.get("value", "")
        if value in seen:
            continue
        seen.add(value)
        label = labels.get(node.attrib.get("id", ""))
        size_nodes = label.css('.product__variant__variant') if label is not None else []
        size = str(size_nodes[0].get_all_text(strip=True)).strip() if size_nodes else ""
        if not value or not size or len(size) > 24:
            logger.warning("Visma 商品选项缺少 ID 或尺码；保留旧快照 {}", url)
            return []
        price = formatted_money(node.attrib.get("data-saleprice", ""), currency)
        if price is None:
            logger.warning("Visma 逐规格价格/币种未验证；保留旧快照 {} {}", url, size)
            return []
        visible = label.css('.product__variant__price:not(.product__variant__price--old)')
        if visible and formatted_money(str(visible[-1].get_all_text(strip=True)), currency) != price:
            logger.warning("Visma 可见价格与商品选项冲突；保留旧快照 {} {}", url, size)
            return []
        stock_text = str(Selector(node.attrib.get("data-stock", "")).get_all_text(strip=True)).casefold()
        can_buy = node.attrib.get("data-purchasable")
        if can_buy == "1" and "in stock" in stock_text and "disabled" not in node.attrib:
            stock = "in_stock"
        elif can_buy == "0" and "in stock" not in stock_text:
            stock = "out_of_stock"
        else:
            stock = "unknown"
        original = formatted_money(node.attrib.get("data-price", ""), currency)
        if original and original.amount <= price.amount:
            original = None
        result.append(base[0].model_copy(update={
            "offer_id": offer_id(source["code"], url, value),
            "identity": ProductIdentity(brand=base[0].identity.brand, model=base[0].name, size=size),
            "price": price, "original_price": original, "stock": stock,
            "image": image, "sales_region": f"{region} 市场报价（{currency}）" if region else "",
            "family_hint": url,
            "identity_evidence": "官方商品选项的尺码、对应价格、可购买状态及库存提示；当前市场币种：" + currency,
        }))
    return result
