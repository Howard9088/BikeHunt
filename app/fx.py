"""统一 ECB 参考汇率快照；网络错误回退缓存并明确 stale。"""
from __future__ import annotations

import hashlib
import json
import ssl
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import certifi
from loguru import logger

from app.catalog.models import FxSnapshot
from app.catalog.storage import atomic_json

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
# Recheck hourly when a build runs; a successful daily reference remains valid
# for 24 hours. A failed recheck marks the fallback stale immediately.
FX_REFRESH_SECONDS = 3600
FX_MAX_AGE_SECONDS = 86400
_lock = threading.RLock()


def snapshot(payload: dict) -> FxSnapshot:
    """验证缓存汇率及日期；无效币种不参与换算。"""
    rates = {"CNY": Decimal(1)}
    for code, value in payload.get("rates", {}).items():
        try:
            rate = Decimal(str(value))
            if len(code) == 3 and rate.is_finite() and rate > 0:
                rates[code] = rate
        except (ValueError, ArithmeticError, TypeError):
            logger.warning("隔离无效汇率 {}", code)
    stale = bool(payload.get("stale"))
    try:
        fetched = datetime.fromisoformat(payload["fetched_at"])
        if fetched.tzinfo is None:
            raise ValueError("FX timestamp requires timezone")
        rate_date = datetime.fromisoformat(payload["rate_date"]).date()
        age = (datetime.now(timezone.utc) - fetched).total_seconds()
        day_age = (datetime.now(timezone.utc).date() - rate_date).days
        stale = stale or age > FX_MAX_AGE_SECONDS or age < -300 or not 0 <= day_age <= 7
    except (KeyError, ValueError, TypeError):
        fetched = None
        stale = True
    identifier = hashlib.sha256(json.dumps({"date": payload.get("rate_date"),
                                            "rates": {k: str(v) for k, v in sorted(rates.items())}},
                                           sort_keys=True).encode()).hexdigest()[:20]
    return FxSnapshot(snapshot_id=identifier, rate_date=payload.get("rate_date"),
                      fetched_at=fetched, rates=rates, stale=stale,
                      source=payload.get("source", "European Central Bank"),
                      source_url=payload.get("source_url", ECB_URL),
                      note="ECB 每日参考汇率；周末及节假日沿用最近公布日期，每小时尝试重新核对，成功核对后有效 24 小时；失败时保留上次成功数据并标记过期。信用卡实际入账汇率及手续费以发卡行为准。")


class FxProvider:
    def __init__(self, cache: Path) -> None:
        self.cache = cache

    def get(self, force: bool = False) -> FxSnapshot:
        """返回一个有效或明确标为过期的快照，避免采集故障导致目录 500。"""
        with _lock:
            cached: dict = {}
            try:
                cached = json.loads(self.cache.read_text(encoding="utf-8"))
                cached_snapshot = snapshot(cached)
                cache_age = ((datetime.now(timezone.utc) - cached_snapshot.fetched_at).total_seconds()
                             if cached_snapshot.fetched_at else float("inf"))
                if not force and not cached_snapshot.stale and cache_age <= FX_REFRESH_SECONDS:
                    return cached_snapshot
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                logger.warning("汇率缓存不可用 {}", exc)
            for attempt in range(3):
                try:
                    payload = self._fetch()
                    result = snapshot(payload)
                    if result.stale:
                        raise ValueError("ECB rates are outside the accepted date range")
                    atomic_json(self.cache, payload)
                    return result
                except Exception as exc:
                    logger.warning("汇率更新失败 attempt={}/3 {}", attempt + 1, exc)
                    if attempt < 2:
                        time.sleep(2 ** attempt)
            cached["stale"] = True
            return snapshot(cached)

    def _fetch(self) -> dict:
        context = ssl.create_default_context(cafile=certifi.where())
        request = urllib.request.Request(ECB_URL, headers={"User-Agent": "BikeHunt/0.3"})
        with urllib.request.urlopen(request, timeout=12, context=context) as response:
            body = response.read()
        root = ET.fromstring(body)
        day = next((node for node in root.iter() if node.tag.endswith("Cube")
                    and "time" in node.attrib), None)
        if day is None:
            raise ValueError("ECB dated rates block missing")
        eur = {"EUR": Decimal(1)}
        for node in day:
            if "currency" in node.attrib and "rate" in node.attrib:
                rate = Decimal(node.attrib["rate"])
                if not rate.is_finite() or rate <= 0:
                    raise ValueError("ECB invalid exchange rate")
                eur[node.attrib["currency"]] = rate
        if "CNY" not in eur:
            raise ValueError("ECB CNY rate missing")
        return {"source": "European Central Bank", "source_url": ECB_URL,
                "rate_date": day.attrib["time"], "fetched_at": datetime.now(timezone.utc).isoformat(),
                "base": "CNY", "rates": {code: str(eur["CNY"] / rate) for code, rate in eur.items()},
                "meaning": "1 unit of original currency converted to CNY"}

