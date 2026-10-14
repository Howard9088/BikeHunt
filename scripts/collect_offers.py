"""Scrapling 公开商品采集：python scripts/collect_offers.py [--source maap]。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from loguru import logger

from app.catalog.storage import OfferRepository
from app.collectors.parsers import parse_jsonld, parse_teamcycles
from app.collectors.variants import parse_rapha, parse_visma
from app.collectors.shopify import collect_shopify_catalog
from app.collectors.embedded_catalogs import parse_assos, parse_pns, parse_kask
from app.collectors.transport import CollectionError, PublicPageFetcher, SourceDeferred


def saved_deferrals(data_dir: Path, code: str, now: datetime) -> dict[str, SourceDeferred]:
    """在服务端指定的恢复时间前，后续定时运行也不再次请求该域。"""
    try:
        status = json.loads((data_dir / "collection_status" / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    pending = {}
    for error in status.get("errors", []):
        try:
            until = datetime.fromisoformat(error.get("retry_at", "").replace("Z", "+00:00"))
            host = urlsplit(error["url"]).hostname
            if until.tzinfo is not None and until > now and host:
                if host not in pending or pending[host].retry_at < until:
                    pending[host] = SourceDeferred(
                        f"Source remains deferred until {until.isoformat()}", until)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    return pending


def error_record(url: str, exc: Exception) -> dict:
    row = {"url": url, "error": str(exc)}
    if isinstance(exc, SourceDeferred):
        row["retry_at"] = exc.retry_at.isoformat()
    return row


def source_groups(settings_list: list[dict]) -> list[list[dict]]:
    """Connected host sets are serialized; independent domains use at most 3 workers."""
    groups = []
    for settings in settings_list:
        hosts = set(settings["domains"])
        members = [settings]
        untouched = []
        for group_hosts, group_members in groups:
            if hosts.intersection(group_hosts):
                hosts.update(group_hosts)
                members.extend(group_members)
            else:
                untouched.append((group_hosts, group_members))
        groups = untouched + [(hosts, members)]
    return [members for _, members in groups]


def collect_source(settings: dict, repository: OfferRepository, source_map: dict) -> None:
    code = settings["code"]
    source = source_map[code]
    fetcher = PublicPageFetcher(set(settings["domains"]))
    fetcher.deferred.update(saved_deferrals(ROOT / "data", code, datetime.now(timezone.utc)))
    if settings.get("parser") == "shopify":
        result = collect_shopify_catalog(fetcher, settings, source, datetime.now(timezone.utc), ROOT / "data" / "raw")
        repository.save(code, result.offers, datetime.now(timezone.utc), result.errors, result.coverage)
        print(json.dumps({"source":code, "offers":len(result.offers), "errors":result.errors, "coverage":result.coverage}, ensure_ascii=True))
        return
    rows = []
    errors: list[dict] = []
    for url in settings["urls"]:
        try:
            response = fetcher.fetch(url, dynamic=settings.get("dynamic", False))
            fetched_at = datetime.now(timezone.utc)
            raw_path = ROOT / "data" / "raw" / (code + "_" + hashlib.sha256(url.encode()).hexdigest()[:16] + ".html")
            raw_path.parent.mkdir(exist_ok=True)
            raw_path.write_bytes(response.body)
            parse = {"teamcycles":parse_teamcycles,"rapha":parse_rapha,"visma":parse_visma,"assos":parse_assos,"pns":parse_pns,"kask":parse_kask}.get(settings["parser"],parse_jsonld)
            parsed = parse(response.body.decode("utf-8", errors="replace"), source, url, fetched_at)
            if not parsed:
                raise CollectionError("No validated per-variant offers; snapshot not replaced")
            declared_gender = settings.get("gender_by_url", {}).get(url)
            if declared_gender in ("male", "female", "unisex") and settings.get("gender_evidence_url"):
                parsed = [row.model_copy(update={"identity": row.identity.model_copy(
                    update={"gender": declared_gender}),
                    "identity_evidence": row.identity_evidence + "；官方款式分区：" + settings["gender_evidence_url"]}) for row in parsed]
            rows.extend(parsed)
            logger.info("{} {} 条逐规格报价", code, len(parsed))
        except Exception as exc:
            logger.error("来源隔离 {} {} {}", code, url, exc)
            errors.append(error_record(url, exc))
    repository.save(code, rows, datetime.now(timezone.utc), errors, {
        "scope":"configured_product_pages", "scope_note":settings.get("scope_note", "指定商品页面，非完整目录"),
        "collected_product_count":len({row.url.split("?",1)[0] for row in rows}),
        "configured_page_count":len(settings["urls"]), "partial":True, "complete":False})
    print(json.dumps({"source": code, "offers": len(rows), "errors": errors}, ensure_ascii=True))


def main() -> None:
    """按配置采集来源；解析为空或失败保留上次成功报价并记录错误。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="仅刷新一个来源 code")
    args = parser.parse_args()
    (ROOT / "logs").mkdir(exist_ok=True)
    logger.add(ROOT / "logs" / "collection.log", rotation="5 MB", retention=5, encoding="utf-8")
    config = json.loads((ROOT / "data" / "crawl_sources.json").read_text(encoding="utf-8"))
    repository = OfferRepository(ROOT / "data")
    source_map = {s["code"]: s for s in repository.sources()}
    requested = [s for s in config if not args.source or s["code"] == args.source]
    if not requested:
        parser.error("来源 code 不在采集配置中")
    def collect_group(group):
        for settings in group:
            collect_source(settings, repository, source_map)
    with ThreadPoolExecutor(max_workers=min(3, len(requested))) as pool:
        futures = [pool.submit(collect_group, group) for group in source_groups(requested)]
        for future in futures:
            future.result()


if __name__ == "__main__":
    main()

