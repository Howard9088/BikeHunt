"""Allowlisted public collection health, never exception text or response bodies."""
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit


def public_urls(root: Path) -> set[str]:
    urls = set()
    try:
        for row in json.loads((root/'data/crawl_sources.json').read_text()):
            urls.update(row.get('urls', []))
            if row.get('catalog_url'): urls.add(row['catalog_url'])
    except (OSError, ValueError, TypeError):
        pass
    for path in (root/'data/offers').glob('*.json'):
        try:
            for row in json.loads(path.read_text()).get('offers', []):
                for key in ['url', 'collection_url']:
                    if row.get(key): urls.add(row[key])
        except (OSError, ValueError, TypeError):
            continue
    return {u for u in urls if isinstance(u,str) and urlsplit(u).scheme=='https' and not urlsplit(u).username and not urlsplit(u).password}


def _time(value):
    if not isinstance(value,str): return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return value if parsed.tzinfo is not None else None
    except ValueError:
        return None


def public_collection_status(raw: dict, allowed_urls: set[str]) -> dict:
    result={}
    for code, row in raw.items():
        if not isinstance(row,dict): continue
        entry={'source_code':code,'errors':[]}
        if _time(row.get('attempted_at')): entry['attempted_at']=row['attempted_at']
        for key in ['new_offer_count','retained_offer_count']:
            if type(row.get(key)) is int and row[key]>=0: entry[key]=row[key]
        if row.get('status') in ['success','partial','failed']: entry['status']=row['status']
        observations = row.get('successful_offer_observations')
        if isinstance(observations, dict):
            safe_observations = {key: stamp for key, stamp in observations.items()
                if isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', key)
                and _time(stamp)}
            if safe_observations: entry['successful_offer_observations'] = safe_observations

        coverage={}
        for key in ['collected_product_count','configured_page_count','dynamic_offer_count','sized_offer_count']:
            value=(row.get('coverage') or {}).get(key)
            if type(value) is int and value>=0: coverage[key]=value
        for key in ['partial','complete']:
            value=(row.get('coverage') or {}).get(key)
            if type(value) is bool: coverage[key]=value
        if coverage: entry['coverage']=coverage
        for error in row.get('errors',[]):
            if not isinstance(error,dict): continue
            retry=_time(error.get('retry_at'))
            safe={'error':'collection_deferred' if retry else 'collection_failed'}
            url=error.get('url')
            if isinstance(url,str) and url in allowed_urls: safe['url']=url
            if retry: safe['retry_at']=retry
            entry['errors'].append(safe)
        result[code]=entry
    return result
