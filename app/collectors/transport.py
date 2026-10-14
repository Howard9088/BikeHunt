"""Scrapling 静态/动态抓取；robots、每域限频和有界指数退避。"""
from __future__ import annotations

import hashlib
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from loguru import logger
import certifi
from scrapling.fetchers import DynamicFetcher, Fetcher

USER_AGENT = "BikeHunt/0.3 (public product information)"


def certificate_bundle() -> str:
    """为 Windows libcurl 提供 ASCII 证书路径，保持 TLS 证书验证开启。"""
    original = Path(certifi.where())
    if str(original).isascii():
        return str(original)
    body = original.read_bytes()
    target = Path(tempfile.gettempdir()) / ("bikehunt-ca-" + hashlib.sha256(body).hexdigest()[:16] + ".pem")
    if not target.exists():
        target.write_bytes(body)
    return str(target)


class CollectionError(RuntimeError):
    """来源不可访问或不允许采集。"""


class PublicPageFetcher:
    def __init__(self, domains: set[str], request: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.domains = domains
        self.request = request or Fetcher.get
        self.sleep = sleep
        self.clock = clock
        self.robots: dict[str, RobotFileParser] = {}
        self.last_request: dict[str, float] = {}

    def _request(self, url: str, dynamic: bool = False):
        host = urlsplit(url).hostname or ""
        if urlsplit(url).scheme != "https" or host not in self.domains:
            raise CollectionError("URL outside configured HTTPS source domains")
        for attempt in range(3):
            pause = 1 - (self.clock() - self.last_request.get(host, -1000))
            if pause > 0:
                self.sleep(pause)
            self.last_request[host] = self.clock()
            try:
                if dynamic:
                    response = DynamicFetcher.fetch(
                        url, headless=True, real_chrome=True, timeout=20000,
                        retries=1, block_ads=True, google_search=False,
                        useragent=USER_AGENT,
                    )
                else:
                    response = self.request(
                        url, timeout=20, retries=1, stealthy_headers=False,
                        verify=certificate_bundle(),
                        headers={"User-Agent": USER_AGENT},
                    )
                if response.status in (408, 429) or response.status >= 500:
                    raise CollectionError(f"Retryable HTTP {response.status}")
                return response
            except Exception as exc:
                logger.warning("请求失败 {} attempt={}/3 {}", url, attempt + 1, exc)
                if attempt == 2:
                    raise CollectionError(f"Source request failed: {url}") from exc
                self.sleep(2 ** attempt)
        raise CollectionError("Request attempts exhausted")

    def fetch(self, url: str, dynamic: bool = False):
        """返回公开网页 Response；禁止或无法核实 robots 时抛出 CollectionError。"""
        split = urlsplit(url)
        origin = f"{split.scheme}://{split.netloc}"
        if origin not in self.robots:
            response = self._request(origin + "/robots.txt")
            robot = RobotFileParser(origin + "/robots.txt")
            if response.status in (404, 410):
                robot.parse(["User-agent: *", "Allow: /"])
            elif response.status == 200:
                robot.parse(response.body.decode("utf-8", errors="replace").splitlines())
            else:
                raise CollectionError(f"Robots unavailable: HTTP {response.status}")
            self.robots[origin] = robot
        robot = self.robots[origin]
        if not robot.can_fetch(USER_AGENT, url):
            raise CollectionError("robots.txt forbids this product URL")
        crawl_delay = robot.crawl_delay(USER_AGENT) or robot.crawl_delay("*") or 1
        host = split.hostname or ""
        pause = crawl_delay - (self.clock() - self.last_request.get(host, -1000))
        if pause > 0:
            self.sleep(pause)
        response = self._request(url, dynamic)
        if response.status != 200:
            raise CollectionError(f"Product HTTP {response.status}")
        logger.info("采集成功 {} HTTP {}", url, response.status)
        return response
