"""Validate payment evidence independently of prices, shipping and eligibility.

The identity catalog records exact sources and market labels, not payment claims.
Research may leave a method unknown, but may never omit its reason or borrow a
policy from another retailer or country. Production builds require full coverage.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

REQUIRED_METHODS = frozenset(('cards', 'china_issued_cards', 'paypal', 'apple_pay',
                             'google_pay', 'alipay', 'wechat_pay', 'unionpay',
                             'bank_transfer_local', 'gift_cards', 'instalments'))
STATUSES = frozenset(('supported', 'conditional', 'not_supported', 'unknown', 'historical'))
EVIDENCE = frozenset(('official_text', 'official_icons_only', 'historical_official', 'unavailable', 'mixed'))
KEY = re.compile(r'[a-z][a-z0-9_]{0,70}\Z')
HOST = re.compile(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}\Z')


def text(value, maximum=2500):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def china_valid(value):
    return text(value) or (isinstance(value, dict) and text(value.get('status'), 100)
                           and ('evidence_class' not in value or text(value['evidence_class'], 100)) and text(value.get('note')))


def dated(value, today=None):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return False
    try:
        return date.fromisoformat(value) <= (today or datetime.now(timezone.utc).date())
    except ValueError:
        return False


def https(value, hosts):
    if not isinstance(value, str) or any(c.isspace() for c in value) or any(c in value for c in '\\<>"'):
        return False
    try:
        u = urlsplit(value)
        return (u.scheme == 'https' and u.netloc == u.hostname and u.hostname in hosts
                and not u.username and not u.password and not u.port)
    except (ValueError, TypeError):
        return False


def evidence_url(value, channel, urls):
    return https(value, channel['reference_hosts']) or any(
        a['url'] == value and a['owner_page'] in urls for a in channel.get('reference_assets', []))


def strings(value, predicate, nonempty=False):
    return isinstance(value, list) and (bool(value) or not nonempty) and all(predicate(x) for x in value)


def validate_payment_channels(data):
    if (not isinstance(data, dict) or data.get('schema_version') != 1
            or not text(data.get('revision'), 100) or not isinstance(data.get('channels'), list)
            or not 0 < len(data['channels']) <= 100):
        raise ValueError('Invalid payment channel catalog')
    seen = set()
    for c in data['channels']:
        if (not isinstance(c, dict) or not KEY.fullmatch(c.get('source_code', ''))
                or c['source_code'] in seen or not text(c.get('merchant_name'), 200)
                or not text(c.get('identity_note'))
                or not strings(c.get('sales_regions'), lambda x: text(x, 200), True)
                or not strings(c.get('merchant_hosts'), lambda x: isinstance(x, str) and HOST.fullmatch(x), True)
                or not strings(c.get('reference_hosts'), lambda x: isinstance(x, str) and HOST.fullmatch(x))
                or not strings(c.get('directory_codes'), lambda x: isinstance(x, str) and KEY.fullmatch(x))
                or not https(c.get('base_url'), c['merchant_hosts'])):
            raise ValueError('Invalid payment channel identity')
        if not strings(c.get('reference_assets', []), lambda a: isinstance(a, dict)
                       and https(a.get('owner_page'), c['reference_hosts'])
                       and https(a.get('url'), [urlsplit(a.get('url', '')).hostname])):
            raise ValueError('Invalid owned payment asset')
        seen.add(c['source_code'])
    return data


def validate_payment_methods(data, catalog, *, require_complete=False, today=None):
    validate_payment_channels(catalog)
    if (not isinstance(data, dict) or data.get('schema_version') != 1
            or not text(data.get('revision'), 100) or not dated(data.get('checked_at'), today)
            or not text(data.get('payment_caveat')) or not isinstance(data.get('entries'), list)
            or len(data['entries']) > 150):
        raise ValueError('Invalid payment data')
    channels = {c['source_code']: c for c in catalog['channels']}
    seen = set()
    covered = set()
    for row in data['entries']:
        if not isinstance(row, dict):
            raise ValueError('Invalid payment row')
        channel = channels.get(row.get('source_code'))
        key = (row.get('source_code'), row.get('scope'), row.get('sales_region'))
        if (not channel or key in seen or not text(row.get('merchant_name'), 200)
                or row.get('scope') not in ('market', 'merchant') or not text(row.get('scope_note'))
                or row.get('merchant_evidence_status') not in EVIDENCE
                or not strings(row.get('merchant_hosts'), lambda x: x in channel['merchant_hosts'], True)
                or len(set(row['merchant_hosts'])) != len(row['merchant_hosts'])
                or not strings(row.get('scope_evidence_urls'), lambda x: https(x, channel['reference_hosts']))):
            raise ValueError(f'Invalid payment merchant scope: {key}')
        if row['scope'] == 'market':
            if row['sales_region'] not in channel['sales_regions']:
                raise ValueError(f'Wrong payment market: {key}')
            covered.add((row['source_code'], row['sales_region']))
        else:
            if (row['sales_region'] is not None or not row['scope_evidence_urls']
                    or row['merchant_evidence_status'] not in ('official_text', 'mixed')):
                raise ValueError('Merchant-wide scope needs explicit official evidence')
            covered.update((row['source_code'], m) for m in channel['sales_regions'])
        methods = row.get('methods')
        if not isinstance(methods, list) or not len(REQUIRED_METHODS) <= len(methods) <= 60:
            raise ValueError(f'Incomplete payment matrix: {key}')
        method_keys = set()
        for method in methods:
            if (not isinstance(method, dict) or not KEY.fullmatch(method.get('method_key', ''))
                    or method['method_key'] in method_keys or not text(method.get('name'), 200)
                    or method.get('status') not in STATUSES
                    or not all(text(method.get(x)) for x in ('note', 'account_region_constraints'))
                    or not china_valid(method.get('china_applicability'))
                    or not all(x not in method or text(method[x]) for x in ('evidence_class', 'merchant_evidence_detail'))
                    or not all(x not in method or (strings(method[x], lambda n: text(n, 100)) and len(method[x]) <= 30)
                               for x in ('card_networks', 'networks'))
                    or not strings(method.get('evidence_urls'), lambda x: evidence_url(x, channel, method['evidence_urls']))
                    or not (dated(method.get('checked_at'), today) or (method.get('checked_at') is None
                              and method['status'] == 'unknown' and not method['evidence_urls']))):
                raise ValueError(f'Invalid payment evidence: {key} / {method.get("method_key") if isinstance(method, dict) else 'invalid'}')
            if method['status'] != 'unknown' and (not method['evidence_urls'] or not method.get('checked_at')):
                raise ValueError('Payment claim requires dated official evidence')
            evidence = row['merchant_evidence_status']
            if evidence == 'unavailable' and method['status'] != 'unknown':
                raise ValueError('Unavailable evidence cannot assert a payment claim')
            if evidence == 'historical_official' and method['status'] not in ('historical', 'unknown'):
                raise ValueError('Historical evidence cannot assert current support')
            if method.get('merchant_evidence_status', evidence) not in EVIDENCE:
                raise ValueError('Invalid per-method evidence type')
            if ('official_icons_only' in (evidence, method.get('merchant_evidence_status'))
                    and method['status'] in ('supported', 'not_supported')):
                raise ValueError('Logos cannot prove support or rejection')
            method_keys.add(method['method_key'])
        if not REQUIRED_METHODS <= method_keys:
            raise ValueError(f'Missing required payment category: {key}')
        if 'channels' in row:
            if not isinstance(row['channels'], list) or not 2 <= len(row['channels']) <= 10:
                raise ValueError('Invalid separate merchant channels')
            hosts = set()
            for child in row['channels']:
                if (not isinstance(child, dict) or child.get('channels')
                        or any(child.get(k) != row[k] for k in ('source_code', 'sales_region', 'scope'))
                        or not strings(child.get('merchant_hosts'), lambda h: h in row['merchant_hosts'] and h not in hosts, True)):
                    raise ValueError('Mixed merchant subchannel scope')
                hosts.update(child['merchant_hosts'])
                other_hosts = set(row['merchant_hosts']) - set(child['merchant_hosts'])
                child_catalog = {**catalog, 'channels': [
                    {**c, 'reference_hosts': [h for h in c['reference_hosts'] if h not in other_hosts]}
                    if c['source_code'] == row['source_code'] else c for c in catalog['channels']]}
                validate_payment_methods({**data, 'entries': [child]}, child_catalog, today=today)
            if hosts != set(row['merchant_hosts']):
                raise ValueError('Unbound aggregate merchant')
        seen.add(key)
    expected = {(c['source_code'], m) for c in channels.values() for m in c['sales_regions']}
    if require_complete and covered != expected:
        raise ValueError(f'Payment coverage incomplete: {sorted(expected - covered)}')
    return data


def read_payment_methods(root):
    catalog = validate_payment_channels(json.loads((root / 'web/payment-channels.json').read_text(encoding='utf-8')))
    data = json.loads((root / 'web/payment-methods.json').read_text(encoding='utf-8'))
    return validate_payment_methods(data, catalog, require_complete=True)
