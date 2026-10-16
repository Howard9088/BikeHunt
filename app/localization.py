"""骑行术语与产品类型的中文显示；保留品牌、系列和英文原名。"""
from __future__ import annotations

import re

CATEGORIES = [
    {"code": "all", "name": "全部"},
    {"code": "jerseys", "name": "骑行上衣"},
    {"code": "bibs", "name": "骑行裤"},
    {"code": "jackets", "name": "外套与背心"},
    {"code": "shoes", "name": "锁鞋"},
    {"code": "helmets", "name": "头盔"},
    {"code": "accessories", "name": "配件与周边"},
]
TERMS = [
    (r"Winter Sweater", "冬季毛衣"),
    (r"T-Shirt", "T恤"),
    (r"Beanie", "针织帽"),
    (r"Scarf", "围巾"),
    (r"Backpack", "背包"),
    (r"Weekender", "旅行包"),
    (r"Seat Bag", "坐垫包"),
    (r"Phone Strap", "手机挂绳"),
    (r"Keyring", "钥匙扣"),
    (r"Bandana", "头巾"),
    (r"Microfiber Towel", "超细纤维毛巾"),
    (r"Ventral Air Mips CPSC", "Ventral Air Mips 骑行头盔（CPSC 版）"),
    (r"Cycling jersey men", "男款骑行上衣"),
    (r"Cycling jersey women", "女款骑行上衣"),
    (r"Cycling jersey kids", "童款骑行上衣"),
    (r"Long Sleeve Cycling Jersey|Long Sleeve Jersey|LS Jersey", "长袖骑行上衣"),
    (r"Short Sleeve Cycling Jersey|Short Sleeve Jersey", "短袖骑行上衣"),
    (r"Deep Winter Bib Tight", "深冬背带长裤"),
    (r"Thermal Bib Tight", "保暖背带长裤"),
    (r"Bib Tight(?:s)?", "背带长裤"),
    (r"Bib Short(?:s)?", "背带短裤"),
    (r"\bBib\b", "背带骑行短裤"),
    (r"LS Race Suit", "长袖竞赛连体骑行服"),
    (r"Race Suit", "竞赛连体骑行服"),
    (r"SS Jacket", "短袖骑行夹克"),
    (r"Jersey", "骑行上衣"),
    (r"Jacket", "骑行夹克"),
    (r"Vest|Gilet", "骑行背心"),
    (r"Cycling Helmet|Helmet", "骑行头盔"),
    (r"Cycling Shoes|Shoes", "骑行锁鞋"),
    (r"Socks", "骑行袜"),
    (r"Bottle", "水壶"),
    (r"Cargo", "多口袋"),
    (r"Team Visma\s*\|\s*Lease a Bike", "维斯玛车队"),
    (r"Uranium Black Matt", "哑光黑色"),
    (r"Hydrogen White", "白色"),
    (r"Dark Navy", "深藏蓝色"),
    (r"Ultramarine", "群青蓝色"),
    (r"\bMen's\b|\bMens\b", "男款"),
    (r"\bWomen's\b|\bWomens\b", "女款"),
    (r"Regular", "标准裤长"),
    (r"\bMen\b", "男款"),
    (r"\bWomen\b", "女款"),
    (r"Black", "黑色"),
    (r"\bBlue\b", "蓝色"),
    (r"\bWhite\b", "白色"),
    (r"Ghost Gray", "浅灰色"),
    (r"Midnight", "午夜蓝"),
    (r"Antartica|Antarctica", "Antarctica 配色"),
    (r"Mauve", "淡紫色"),
    (r"Meadow", "草绿色"),
]


def category_of(name: str) -> str:
    """按明确商品术语分类，不推断未提供的产品参数。"""
    text = name.casefold()
    if "helmet" in text or "头盔" in text or "ventral air mips" in text:
        return "helmets"
    if "shoe" in text or "quoc" in text:
        return "shoes"
    if "bib" in text or "背带短裤" in text or "背带骑行裤" in text:
        return "bibs"
    if "jacket" in text or "vest" in text or "gilet" in text:
        return "jackets"
    if "jersey" in text or "race suit" in text or "骑行服" in text:
        return "jerseys"
    return "accessories"


def title_zh(name: str) -> str:
    """中文产品名称；英文系列保留，不添加未采集的材料/功能宣传。"""
    result = re.sub(r"^MAAP\s+", "", name, flags=re.I)
    for pattern, replacement in TERMS:
        result = re.sub(pattern, replacement, result, flags=re.I)
    result = re.sub(r"\bTeam Bib Evo\b", "Team Evo 背带骑行短裤", result, flags=re.I)
    if "QUOC M3 Pro" in result:
        result += " 联名骑行锁鞋"
    return result.strip()
