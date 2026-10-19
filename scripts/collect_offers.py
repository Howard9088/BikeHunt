"""Scrapling 公开商品采集：python scripts/collect_offers.py [--source maap]。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
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

from app.catalog.storage import OfferRepository, atomic_json
from app.collectors.parsers import parse_jsonld, parse_teamcycles
from app.collectors.variants import parse_rapha, parse_visma
from app.collectors.woocommerce import parse_woocommerce
from app.collectors.saved_team_catalogs import parse_lotto, parse_redbull_catalog
from app.collectors.shopify import collect_shopify_catalog
from app.collectors.nutrition import parse_nutrition
from app.collectors.pelotan import parse_pelotan
from app.collectors.maurten_nutrition import parse_maurten_nutrition
from app.collectors.enervit_nutrition import parse_enervit_nutrition
from app.collectors.embedded_catalogs import parse_assos, parse_pns, parse_kask
from app.collectors.transport import CollectionError, PublicPageFetcher, SourceDeferred
from app.collectors.fetch_policy import source_policy
from app.collectors.discovery import SourceSpec, discover
from app.collectors.rendered import collect_variants, kask_page_action, parse_pissei, parse_kask_rendered
from app.collectors.rendered import parse_unox
from app.collectors.remaining import parse_redbull_product, parse_topfanz, topfanz_page_action
from app.collectors.remaining import parse_canyon_product, parse_colnago_product
from app.collectors.specialized import parse_specialized
from app.collectors.gobik import parse_gobik, preserve_gobik_identity, fetch_gobik_product
from app.collectors.oakley import collect_oakley_product
from scrapling.fetchers import FetcherSession
from app.collectors.transport import certificate_bundle


def saved_deferrals(data_dir: Path, code: str, now: datetime) -> dict[str, SourceDeferred]:
    """在服务端指定的恢复时间前，后续定时运行也不再次请求该域。"""
    try:
        status = json.loads((data_dir / "collection_status" / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        status = {}
    try:
        safe = json.loads((data_dir / "source_deferrals" / f"{code}.json").read_text())
    except (OSError, ValueError):
        safe = {}
    errors = list(status.get("errors", []))
    if isinstance(safe, dict):
        errors.extend({"url": "https://" + host + "/", "retry_at": until}
                      for host, until in safe.items() if isinstance(host, str) and re.fullmatch(r"[a-z0-9.-]+", host))
    pending = {}
    for error in errors:
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


def persist_deferrals(data_dir: Path, code: str, errors: list[dict], now: datetime) -> None:
    """Persist only host/retry times across CI; never raw errors or page evidence."""
    safe = {}
    for error in errors:
        try:
            host = urlsplit(error['url']).hostname
            until = datetime.fromisoformat(error['retry_at'].replace('Z', '+00:00'))
            if host and until.tzinfo is not None and until > now:
                if host not in safe or until > datetime.fromisoformat(safe[host]):
                    safe[host] = until.isoformat()
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    atomic_json(data_dir / 'source_deferrals' / f'{code}.json', safe)


def public_diagnostic_codes() -> set[str]:
    from app.collectors import gobik, oakley, decathlon_cn
    return set().union(*(getattr(module, 'PUBLIC_DIAGNOSTICS', frozenset())
                         for module in (gobik, oakley, decathlon_cn)))


def error_record(url: str, exc: Exception) -> dict:
    row = {"url": url, "error": str(exc)}
    # A finite diagnostic vocabulary lets CI locate failures without exposing
    # exception text, URLs, stock response bodies or other private evidence.
    reasons = {
        "Decathlon selected stock request failed": "stock_request_failed",
        "Decathlon selected stock response is unverified": "stock_shape_unverified",
        "Decathlon selected stock DOM did not settle": "stock_dom_mismatch",
        "Decathlon selected size could not be verified": "selected_size_unverified",
        "Decathlon exact size selector is ambiguous": "ambiguous_size_selector",
        "Decathlon stock selection is not isolated": "decathlon_selection_not_isolated",
        "Decathlon stock request is not uniquely tied to selection": "decathlon_request_not_unique",
        "Decathlon selected stock response is missing": "decathlon_response_missing",
        "Decathlon item code repeated across different sizes": "decathlon_repeated_item",
        "Decathlon stock request competed with another selection": "decathlon_competing_request",
        "Ambiguous or unsupported Decathlon size list": "size_list_unverified",
        "Decathlon online stock access denied": "source_access_denied",
        "No validated per-variant offers; snapshot not replaced": "no_validated_variants",
        "Dynamic variant capture did not finish": "variant_capture_failed",
    }
    diagnostic, current, seen = [], exc, set()
    allowed = public_diagnostic_codes()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        markers = getattr(current, 'diagnostics', ())
        if isinstance(markers, (list, tuple)):
            diagnostic.extend(item for item in markers if isinstance(item, str) and item in allowed)
        if str(current) in reasons:
            diagnostic.append(reasons[str(current)])
        if type(current).__name__ == 'TimeoutError':
            diagnostic.append('browser_timeout')
        current = current.__cause__
    if diagnostic:
        row['diagnostics'] = list(dict.fromkeys(diagnostic))
    if isinstance(exc, SourceDeferred):
        row["retry_at"] = exc.retry_at.isoformat()
    return row


def print_public_collection_result(code: str, count: int, errors: list[dict]) -> None:
    # Diagnostics remain in local collection_status; CI console gets no body or URL.
    kinds = ['collection_deferred' if row.get('retry_at') else 'collection_failed'
             for row in errors]
    allowed = {'stock_request_failed', 'stock_shape_unverified', 'stock_dom_mismatch',
               'selected_size_unverified', 'ambiguous_size_selector', 'size_list_unverified',
               'source_access_denied', 'no_validated_variants', 'variant_capture_failed', 'browser_timeout',
               'decathlon_selection_not_isolated', 'decathlon_request_not_unique', 'decathlon_response_missing',
               'decathlon_repeated_item', 'decathlon_competing_request'} | public_diagnostic_codes()
    diagnostics = sorted({reason for row in errors for reason in row.get('diagnostics', [])
                          if isinstance(reason, str) and reason in allowed})
    result = {'source': code, 'offers': count, 'errors': kinds}
    if diagnostics:
        result['diagnostics'] = diagnostics
    print(json.dumps(result, ensure_ascii=True))


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
    """一个来源使用独立公共会话；不读取用户登录凭据。"""
    if settings.get('public_session'):
        with FetcherSession(stealthy_headers=False, verify=certificate_bundle()) as session:
            _collect_source(settings, repository, source_map, request=session.get)
    else:
        _collect_source(settings, repository, source_map)


def _collect_source(settings: dict, repository: OfferRepository, source_map: dict,
                    request=None) -> None:
    code = settings["code"]
    source = source_map[code]
    policy = source_policy(settings)
    fetcher = PublicPageFetcher(set(settings["domains"]), policy=policy, request=request)
    if settings.get("variant_profile") == "kask":
        fetcher.page_action = kask_page_action(fetcher.variant_pages)
    elif settings.get("variant_profile") == "topfanz":
        fetcher.page_action = topfanz_page_action(fetcher.variant_pages)
    if settings.get("parser") == "decathlon_cn":
        from app.collectors.decathlon_cn import decathlon_cn_page_action
        fetcher.page_action = decathlon_cn_page_action(fetcher.variant_pages)
    previous = [row for row in repository.load() if row.source_code == code] if code in {
        'gobik', 'oakley', 'decathlon_cn'} else []
    fetcher.deferred.update(saved_deferrals(ROOT / "data", code, datetime.now(timezone.utc)))
    if settings.get("parser") == "shopify":
        result = collect_shopify_catalog(fetcher, settings, source, datetime.now(timezone.utc), ROOT / "data" / "raw")
        persist_deferrals(ROOT / "data", code, result.errors, datetime.now(timezone.utc))
        repository.save(code, result.offers, datetime.now(timezone.utc), result.errors, result.coverage)
        print_public_collection_result(code, len(result.offers), result.errors)
        return
    rows = []
    errors: list[dict] = []
    urls = list(settings["urls"])
    if settings.get("discovery"):
        discovery = settings["discovery"]
        try:
            found = discover(SourceSpec(code, frozenset(settings["domains"]),
                tuple(discovery["catalog_urls"]), discovery["product_link_pattern"],
                policy.model_copy(update={"wait_selector": None,
                    "mode": discovery.get("mode", "static")})), fetcher)
            urls = list(dict.fromkeys([*urls, *found]))[:policy.max_products]
        except Exception as exc:
            errors.append(error_record(discovery["catalog_urls"][0], exc))
    for url in urls:
        try:
            if settings["parser"] == "oakley":
                result = collect_oakley_product(fetcher, url, source, previous)
                for request_url, capture in result.pages.items():
                    raw_path = ROOT / 'data' / 'raw' / ('oakley_' + hashlib.sha256(request_url.encode()).hexdigest()[:16] + '.html')
                    raw_path.parent.mkdir(exist_ok=True)
                    raw_path.write_bytes(capture.body)
                rows.extend(result.offers)
                errors.extend(result.errors)
                continue
            response = fetch_gobik_product(fetcher, url) if code == "gobik" else fetcher.fetch(url)
            if code in {"gobik", "maurten_nutrition", "sis_nutrition", "enervit_nutrition"} and response.url != url:
                raise CollectionError("Response changed the configured product or market URL")
            fetched_at = datetime.now(timezone.utc)
            raw_path = ROOT / "data" / "raw" / (code + "_" + hashlib.sha256(url.encode()).hexdigest()[:16] + ".html")
            raw_path.parent.mkdir(exist_ok=True)
            raw_path.write_bytes(response.body)
            parse = {"enervit_nutrition":parse_enervit_nutrition,"pelotan":parse_pelotan,"nutrition":parse_nutrition,"maurten_nutrition":parse_maurten_nutrition,"gobik":parse_gobik,"specialized":parse_specialized,"colnago":parse_colnago_product,"canyon":parse_canyon_product,"redbull_product":parse_redbull_product,"topfanz":parse_topfanz,"unox":parse_unox,"pissei":parse_pissei,"lotto":parse_lotto,"redbull_catalog":parse_redbull_catalog,"woocommerce":parse_woocommerce,"teamcycles":parse_teamcycles,"rapha":parse_rapha,"visma":parse_visma,"assos":parse_assos,"pns":parse_pns,"kask":parse_kask_rendered}.get(settings["parser"],parse_jsonld)
            if settings["parser"] == "decathlon_cn":
                from app.collectors.decathlon_cn import parse_decathlon_cn
                parse = parse_decathlon_cn
            parsed = collect_variants(response, source, parse)
            if not parsed and policy.mode == "auto" and response.fetch_mode == "static":
                response = fetcher.fetch(url, policy=policy.model_copy(update={"mode": "dynamic"}))
                raw_path.write_bytes(response.body)
                parsed = collect_variants(response, source, parse)
            if code == 'gobik':
                parsed = preserve_gobik_identity(parsed, previous)
            elif code == 'decathlon_cn':
                from app.collectors.decathlon_cn import preserve_decathlon_cn_identity
                parsed = preserve_decathlon_cn_identity(parsed, previous)
            if not parsed:
                raise CollectionError("No validated per-variant offers; snapshot not replaced")
            parsed = [row.model_copy(update={'collection_url':url}) for row in parsed]
            for index, body in enumerate(response.variant_pages):
                extension = '.json' if body.lstrip().startswith(b'{') else '.html'
                raw_path.with_name(raw_path.stem + f'.variant-{index}' + extension).write_bytes(body)
            from app.catalog.storage import atomic_json
            atomic_json(raw_path.with_suffix('.diagnostic.json'), {
                'url':url, 'observed_at':response.observed_at.isoformat(),
                'fetch_mode':response.fetch_mode, 'evidence_sha256':response.evidence_sha256,
                'variant_snapshots':len(response.variant_pages), 'offers':len(parsed)})
            if settings.get("product_level_only"):
                parsed = [row.model_copy(update={"stock": "unknown",
                    "sales_region": source.get("sales_region", ""),
                    "purchase_requirements": row.purchase_requirements + ["仅商品级报价；逐尺码库存尚未核实"]}) for row in parsed]
            declared_gender = settings.get("gender_by_url", {}).get(url)
            if declared_gender in ("male", "female", "unisex") and settings.get("gender_evidence_url"):
                parsed = [row.model_copy(update={"identity": row.identity.model_copy(
                    update={"gender": declared_gender}),
                    "identity_evidence": row.identity_evidence + "；官方款式分区：" + settings["gender_evidence_url"]}) for row in parsed]
            rows.extend(parsed)
            logger.info("{} {} 条逐规格报价", code, len(parsed))
        except Exception as exc:
            logger.error("来源隔离 {} collection_failed", code)
            errors.append(error_record(url, exc))
    persist_deferrals(ROOT / "data", code, errors, datetime.now(timezone.utc))
    repository.save(code, rows, datetime.now(timezone.utc), errors, {
        "scope":"configured_product_pages", "scope_note":settings.get("scope_note", "指定商品页面，非完整目录"),
        "collected_product_count":len({row.family_hint if code == "decathlon_cn" else (row.collection_url or row.url).split("?",1)[0] for row in rows}),
        "configured_page_count":len(urls), "fetch_mode":policy.mode,
        "dynamic_offer_count":sum(row.fetch_mode == "dynamic" for row in rows),
        "sized_offer_count":sum(bool(row.identity.size) for row in rows),
        "partial":True, "complete":False})
    print_public_collection_result(code, len(rows), errors)


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

