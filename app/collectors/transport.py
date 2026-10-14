"""Scrapling 静态/动态抓取；robots、每域限频和有界指数退避。"""
from __future__ import annotations

import hashlib
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
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


class SourceDeferred(CollectionError):
    """服务端限流/维护；在 Retry-After 之前不发送后续请求。"""

    def __init__(self, message: str, retry_at: datetime) -> None:
        super().__init__(message)
        self.retry_at = retry_at


def retry_after(response, now: datetime) -> datetime:
    """支持秒数与 HTTP-date；缺失/损坏时至少等待 15 分钟。"""
    headers = getattr(response, "headers", {}) or {}
    value = next((str(v).strip() for k, v in headers.items()
                  if str(k).casefold() == "retry-after"), "")
    try:
        if value.isdigit():
            target = now + timedelta(seconds=int(value))
        else:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
        # Even Retry-After: 0 must not cause an immediate request burst.
        return max(target, now + timedelta(seconds=60))
    except (ValueError, TypeError, OverflowError):
        return now + timedelta(minutes=15)


class PublicPageFetcher:
    def __init__(self, domains: set[str], request: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.domains = domains
        self.request = request or Fetcher.get
        self.sleep = sleep
        self.clock = clock
        self.utcnow = utcnow
        self.robots: dict[str, RobotFileParser] = {}
        self.last_request: dict[str, float] = {}
        self.deferred: dict[str, SourceDeferred] = {}
        self.robots_failures: dict[str, CollectionError] = {}

    def _request(self, url: str, dynamic: bool = False):
        host = urlsplit(url).hostname or ""
        if urlsplit(url).scheme != "https" or host not in self.domains:
            raise CollectionError("URL outside configured HTTPS source domains")
        if host in self.deferred:
            raise self.deferred[host]
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
                headers = getattr(response, "headers", {}) or {}
                if response.status == 429 or (response.status == 503 and any(
                        str(key).casefold() == "retry-after" for key in headers)):
                    until = retry_after(response, self.utcnow())
                    error = SourceDeferred(
                        f"HTTP {response.status}; source deferred until {until.isoformat()}", until)
                    self.deferred[host] = error
                    raise error
                if response.status == 408 or response.status >= 500:
                    raise CollectionError(f"Retryable HTTP {response.status}")
                return response
            except SourceDeferred:
                raise
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
        if origin in self.robots_failures:
            raise self.robots_failures[origin]
        if origin not in self.robots:
            try:
                response = self._request(origin + "/robots.txt")
                robot = RobotFileParser(origin + "/robots.txt")
                if response.status in (404, 410):
                    robot.parse(["User-agent: *", "Allow: /"])
                elif response.status == 200:
                    body = response.body.decode("utf-8-sig", errors="replace")
                    if "<html" in body.casefold() or "<!doctype" in body.casefold():
                        raise CollectionError("Robots response is HTML; permission not verified")
                    robot.parse(body.splitlines())
                else:
                    raise CollectionError(f"Robots unavailable: HTTP {response.status}")
                self.robots[origin] = robot
            except CollectionError as exc:
                # Reusing a failed source must not repeatedly hit its robots endpoint.
                self.robots_failures[origin] = exc
                raise
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

