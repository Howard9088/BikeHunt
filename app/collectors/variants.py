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


def parse_visma(html: str, source: dict, url: str, fetched_at: datetime) -> list[Offer]:
    """每个可见尺码使用其自己的价格、库存状态和不可变商品选项 ID。"""
    page = Selector(html)
    base = parse_jsonld(html,source,url,fetched_at)
    if not base:
        return []
    images = page.css('.product__images .product__image img[src]')
    image = next((node.attrib["src"] for node in images
                  if node.attrib["src"].startswith("https://")
                  and "_crop_" not in node.attrib["src"]), base[0].image)
    result = []
    for node in page.css('input[name="purchasableId"][data-saleprice]'):
        ident = node.attrib.get("id","")
        labels = page.css(f'label[for="{ident}"]')
        size_nodes = labels[0].css('.product__variant__variant') if labels else []
        size = str(size_nodes[0].get_all_text(strip=True)).strip() if size_nodes else ""
        if not size or len(size)>10:
            continue
        text = node.attrib["data-saleprice"]
        currency = base[0].price.currency
        expected_symbol = {"EUR":"€","GBP":"£","USD":"$","DKK":"kr"}.get(currency)
        if not expected_symbol or expected_symbol not in text:
            continue
        price = money(re.sub(r"[^0-9.]","",text),currency)
        if price is None:
            continue
        stock_text = node.attrib.get("data-stock","").casefold()
        can_buy = node.attrib.get("data-purchasable")=="1"
        stock = "in_stock" if can_buy and ("in stock" in stock_text) else "out_of_stock" if not can_buy else "unknown"
        original_text = node.attrib.get("data-price","")
        original = money(re.sub(r"[^0-9.]","",original_text),currency) if expected_symbol in original_text else None
        result.append(base[0].model_copy(update={
            "offer_id":offer_id(source["code"],url,node.attrib["value"]),
            "identity":ProductIdentity(brand=base[0].identity.brand,model=base[0].name,size=size),
            "price":price, "original_price":original,"stock":stock,
            "image": image,
            "family_hint":url,"identity_evidence":"官方商品选项的尺码、对应价格、可购买状态及库存提示",
        }))
    return result
