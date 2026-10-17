"""Scrapling 静态/动态抓取；robots、每域限频和有界指数退避。"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from loguru import logger
import certifi
from scrapling.fetchers import DynamicFetcher, Fetcher
from scrapling.parser import Selector

from app.collectors.fetch_policy import CapturedPage, FetchPolicy

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
                 utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 policy: FetchPolicy | None = None,
                 browser_request: Callable | None = None,
                 page_action: Callable | None = None,
                 post_request: Callable | None = None) -> None:
        self.domains = domains
        self.request = request or Fetcher.get
        # The caller can use one public session for both verbs. No user/login
        # state is imported; default requests share only our first-party jar.
        session = getattr(self.request, '__self__', None)
        self.post_request = post_request or getattr(session, 'post', None) or Fetcher.post
        self.sleep = sleep
        self.clock = clock
        self.utcnow = utcnow
        self.robots: dict[str, RobotFileParser] = {}
        self.last_request: dict[str, float] = {}
        self.deferred: dict[str, SourceDeferred] = {}
        self.robots_failures: dict[str, CollectionError] = {}
        self.policy = policy or FetchPolicy()
        self.browser_request = browser_request or DynamicFetcher.fetch
        self.page_action = page_action
        self.variant_pages: list[bytes] = []
        # Only first-party cookies set by these public requests; never import a
        # user's browser/login state or persist cookies in the public snapshot.
        self.public_cookies: dict[str, dict[str, str]] = {}

    def _request(self, url: str, dynamic: bool = False, policy: FetchPolicy | None = None,
                 form_data: dict[str, str] | None = None):
        policy = policy or self.policy
        host = urlsplit(url).hostname or ""
        if urlsplit(url).scheme != "https" or host not in self.domains:
            raise CollectionError("URL outside configured HTTPS source domains")
        if host in self.deferred:
            raise self.deferred[host]
        # An uncertain form submission must never be automatically repeated.
        attempts = 1 if form_data is not None else 3
        for attempt in range(attempts):
            pause = 1 - (self.clock() - self.last_request.get(host, -1000))
            if pause > 0:
                self.sleep(pause)
            self.last_request[host] = self.clock()
            try:
                if dynamic:
                    # A retry must not publish partial snapshots from its failed
                    # predecessor alongside a subsequently successful capture.
                    self.variant_pages.clear()
                    action_errors: list[Exception] = []
                    def checked_action(page):
                        try:
                            self.page_action(page)
                        except Exception as exc:
                            action_errors.append(exc)
                            raise
                    response = self.browser_request(
                        url, headless=True,
                        real_chrome=os.environ.get("BIKEHUNT_REAL_CHROME", str(sys.platform == "win32")).lower() == "true",
                        timeout=policy.timeout_ms, disable_resources=True,
                        retries=1, block_ads=True, google_search=False,
                        useragent=USER_AGENT, wait_selector=policy.wait_selector,
                        page_action=checked_action if self.page_action else None,
                        cookies=[{'name':name, 'value':value, 'domain':host, 'path':'/'}
                                 for name, value in self.public_cookies.get(host, {}).items()],
                    )
                    if action_errors:
                        if isinstance(action_errors[0], SourceDeferred):
                            raise action_errors[0]
                        raise CollectionError("Dynamic variant capture did not finish") from action_errors[0]
                elif form_data is not None:
                    boundary = 'bikehunt-' + secrets.token_hex(16)
                    body = ''.join('--' + boundary + '\r\nContent-Disposition: form-data; name="'
                        + name + '"\r\n\r\n' + value + '\r\n' for name, value in form_data.items())
                    body += '--' + boundary + '--\r\n'
                    response = self.post_request(
                        url, timeout=20, retries=1, stealthy_headers=False,
                        verify=certificate_bundle(), follow_redirects=False, max_redirects=0,
                        headers={"User-Agent": USER_AGENT,
                                 "Content-Type": "multipart/form-data; boundary=" + boundary},
                        cookies=self.public_cookies.get(host, {}), data=body.encode('utf-8'),
                    )
                    if str(getattr(response, 'url', url)) != url:
                        raise CollectionError('Public localization unexpectedly followed a redirect')
                else:
                    response = self.request(
                        url, timeout=20, retries=1, stealthy_headers=False,
                        verify=certificate_bundle(),
                        headers={"User-Agent": USER_AGENT},
                        cookies=self.public_cookies.get(host, {}),
                    )
                cookies = getattr(response, 'cookies', {})
                if isinstance(cookies, dict):
                    self.public_cookies.setdefault(host, {}).update({
                        name:value for name, value in cookies.items()
                        if isinstance(name, str) and isinstance(value, str)})
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
            except SourceDeferred as exc:
                if dynamic:
                    self.variant_pages.clear()
                self.deferred[host] = exc
                raise
            except Exception as exc:
                # An action error may follow a denial or partially selected
                # product. Never repeat the browser selection sequence blindly.
                if dynamic and action_errors:
                    self.variant_pages.clear()
                    raise CollectionError("Dynamic variant capture did not finish") from action_errors[0]
                logger.warning("请求失败 collection_request_failed attempt={}/{}", attempt + 1, attempts)
                if attempt == attempts - 1:
                    raise CollectionError(f"Source request failed: {url}") from exc
                self.sleep(2 ** attempt)
        raise CollectionError("Request attempts exhausted")

    def _check_robots(self, url: str) -> None:
        """Check permission and the same per-origin crawl delay for either verb."""
        split = urlsplit(url)
        if split.scheme != 'https' or split.hostname not in self.domains:
            raise CollectionError('URL outside configured HTTPS source domains')
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

    def submit_public_localization(self, url: str, fields: dict[str, str],
                                   return_url: str) -> CapturedPage:
        """Submit one observed Shopify country form, then fetch its exact return.

        Only non-sensitive localization fields are accepted. The source adapter
        must verify the exposed form/option first. No user credentials, cookie
        presets, arbitrary POST endpoints or automatic redirects are supported.
        """
        action, target = urlsplit(url), urlsplit(return_url)
        expected = {'form_type', 'utf8', '_method', 'return_to', 'country_code'}
        if (action.scheme != 'https' or action.hostname not in self.domains
                or action.netloc != target.netloc or target.scheme != 'https'
                or action.username or action.password or action.port is not None
                or action.query or action.fragment or target.query or target.fragment
                or not re.fullmatch(r'/(?:[a-z]{2}(?:-[a-z]{2})?/)?localization', action.path)
                or not isinstance(fields, dict) or set(fields) != expected
                or any(not isinstance(value, str) or len(value) > 512 or '\r' in value or '\n' in value
                       for value in fields.values())
                or fields.get('form_type') != 'localization' or fields.get('utf8') != '✓'
                or fields.get('_method') != 'put' or fields.get('return_to') != target.path
                or not re.fullmatch(r'[A-Z]{2}', fields.get('country_code', ''))):
            raise CollectionError('Unsupported public localization form')
        # Check both paths before sending. A form must not cause a navigation
        # to a disallowed product even when its POST endpoint itself is allowed.
        self._check_robots(return_url)
        self._check_robots(url)
        response = self._request(url, form_data=fields)
        if response.status not in (200, 204, 302, 303):
            raise CollectionError('Public localization response was not successful')
        headers = getattr(response, 'headers', {}) or {}
        location = next((str(value) for key, value in headers.items() if key.casefold() == 'location'), None)
        if response.status in (302, 303) and not location:
            raise CollectionError('Public localization redirect is missing')
        if location is not None and urljoin(url, location) != return_url:
            raise CollectionError('Public localization redirect changed the exact product')
        capture = self.fetch(return_url, policy=FetchPolicy(mode='static'))
        if capture.url != return_url:
            raise CollectionError('Public localization return changed the exact product')
        return capture

    def fetch(self, url: str, dynamic: bool = False,
              policy: FetchPolicy | None = None) -> CapturedPage:
        """返回公开网页 Response；禁止或无法核实 robots 时抛出 CollectionError。"""
        policy = policy or self.policy
        dynamic = dynamic or policy.mode == "dynamic"
        self._check_robots(url)
        self.variant_pages.clear()
        response = self._request(url, dynamic, policy)
        if response.status != 200:
            raise CollectionError(f"Product HTTP {response.status}")
        final_url = str(getattr(response, "url", url))
        final = urlsplit(final_url)
        if final.scheme != "https" or final.hostname not in self.domains:
            raise CollectionError("Response redirected outside allowed HTTPS domains")
        if (policy.mode == "auto" and not dynamic and policy.wait_selector
                and not Selector(response.body.decode("utf-8", errors="replace")).css(policy.wait_selector)):
            return self.fetch(url, policy=policy.model_copy(update={"mode": "dynamic"}))
        logger.info("采集成功 {} HTTP {}", url, response.status)
        return CapturedPage(response.body, response.status, final_url,
                            dict(getattr(response, "headers", {}) or {}),
                            "dynamic" if dynamic else "static",
                            self.utcnow(), list(self.variant_pages))

