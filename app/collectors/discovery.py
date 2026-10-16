"""从明确的官网分类发现有限商品；不跟随外站、账户或结算入口。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from scrapling.parser import Selector

from app.collectors.fetch_policy import FetchPolicy
from app.collectors.transport import PublicPageFetcher


@dataclass(frozen=True)
class SourceSpec:
    """明确的商家、分类范围和商品链接匹配规则。"""

    code: str
    domains: frozenset[str]
    catalog_urls: tuple[str, ...]
    product_link_pattern: str
    policy: FetchPolicy = field(default_factory=FetchPolicy)


def discover(source: SourceSpec, fetcher: PublicPageFetcher) -> list[str]:
    """只遍历指定分类的 next 分页，返回去重且受数量上限约束的商品地址。"""
    pending = list(source.catalog_urls)
    seen: set[str] = set()
    products: dict[str, None] = {}
    origins = {(urlsplit(u).hostname, urlsplit(u).path.rstrip("/")) for u in pending}
    pattern = re.compile(source.product_link_pattern)
    while (
        pending
        and len(seen) < source.policy.max_pages
        and len(products) < source.policy.max_products
    ):
        url = pending.pop(0)
        if url in seen:
            continue
        seen.add(url)
        response = fetcher.fetch(url, policy=source.policy)
        page = Selector(response.body.decode("utf-8", errors="replace"))
        for link in page.css("a[href]"):
            target = urldefrag(urljoin(response.url, link.attrib["href"].strip()))[0]
            split = urlsplit(target)
            if (
                split.scheme != "https"
                or split.hostname not in source.domains
                or split.username
                or split.password
            ):
                continue
            if any(
                word in split.path.casefold()
                for word in ("/cart", "/checkout", "/account", "/login")
            ):
                continue
            if pattern.search(split.path):
                clean = urlunsplit((split.scheme, split.netloc, split.path, "", ""))
                products.setdefault(clean, None)
                if len(products) >= source.policy.max_products:
                    break
            elif (
                "next" in link.attrib.get("rel", "").split()
                and (split.hostname, split.path.rstrip("/")) in origins
                and target not in seen
            ):
                pending.append(target)
    return list(products)
