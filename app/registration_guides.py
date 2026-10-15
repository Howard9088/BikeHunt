"""Validate and publish only reviewed, local registration screenshot assets.

Market records bind to the exact source_code/sales_region strings. Public account
pages have their own scope and cannot satisfy a missing market-specific record.
Dates record observation, not a made-up expiry. Mark changed pages needs_review.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

TRUSTED_HOSTS = {
    'maap': ['maap.cc', 'www.maap.cc', 'support.maap.cc'], 'teamcycles': ['www.teamcycles.com'],
    'sigmasports': ['www.sigmasports.com'], 'rapha': ['www.rapha.cc'], 'rapha_kr': ['www.rapha.cc'],
    'poc': ['poc.com'], 'visma': ['www.teamvismaleaseabike.com'],
    'amazon_us': ['www.amazon.com'], 'amazon_uk': ['www.amazon.co.uk'],
    'amazon_de': ['www.amazon.de'], 'amazon_jp': ['www.amazon.co.jp'],
    'fizik': ['www.fizik.com'], 'santini': ['www.santinicycling.com'], 'soudal': ['thewolfpack.shop'],
    'ineos': ['store.netcompanyineos.com'], 'bahrain': ['alecycling.com'],
    'decathlon': ['shop.decathloncmacgmteam.com'], 'picnic': ['teampicnicpostnl.store'],
    'castelli': ['www.castelli-cycling.com'], 'assos': ['www.assos.com'], 'pns': ['pasnormalstudios.com'],
    'kask': ['www.kask.com'], 'groupama': ['shop.bioracer.com'], 'ef_team_shop': ['efprocycling.shop'],
    'uae': ['www.pissei.com'], 'nsn': ['www.ekoi.com'], 'lotto': ['www.lotto-intermarche.be'],
    'redbull': ['www.redbullshop.com'],
}
ASSET = re.compile(r'assets/registration/[a-z0-9][a-z0-9_-]*\.(?:png|jpg|jpeg|webp)\Z')
TIMESTAMP = re.compile(r'\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?\Z')


def text(value, limit=300):
    return isinstance(value, str) and 0 < len(value.strip()) and len(value) <= limit


def timestamp(value, now):
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= now
    except ValueError:
        return False


def source_url(value, code):
    if not isinstance(value, str) or len(value) > 1500 or code not in TRUSTED_HOSTS:
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == 'https' and url.netloc in TRUSTED_HOSTS[code]
                and not url.username and not url.password and not url.port and not url.query
                and not url.fragment and bool(url.path) and not any(c.isspace() for c in value)
                and not any(c in value for c in ('\\', '<', '>')))
    except ValueError:
        return False


def validate_registration_guides(data, now=None):
    now = now or datetime.now(timezone.utc)
    if (not isinstance(data, dict) or data.get('schemaVersion') != 1
            or not text(data.get('revision'), 100) or not isinstance(data.get('entries'), list)
            or len(data['entries']) > 200):
        raise ValueError('Invalid registration screenshot configuration')
    keys = set()
    for entry in data['entries']:
        if not isinstance(entry, dict):
            raise ValueError('Invalid registration screenshot entry')
        scope, market, code = entry.get('scope'), entry.get('salesRegion'), entry.get('sourceCode')
        if (not isinstance(code, str) or code not in TRUSTED_HOSTS or scope not in ('market', 'public_account')
                or (not text(market) if scope == 'market' else market is not None)
                or not text(entry.get('marketLabel'), 120) or not text(entry.get('revision'), 100)
                or entry.get('status') not in ('verified', 'needs_review', 'unverified')
                or not isinstance(entry.get('frames'), list) or len(entry['frames']) > 12
                or (entry['status'] == 'verified' and not entry['frames'])
                or (entry['status'] != 'verified' and not text(entry.get('reviewReason'), 500))
                or ('checkedAt' in entry and not timestamp(entry['checkedAt'], now))):
            raise ValueError('Invalid registration screenshot entry')
        key = (code, scope, market)
        if key in keys:
            raise ValueError('Duplicate registration screenshot source/market/scope')
        keys.add(key)
        frame_ids = set()
        for frame in entry['frames']:
            if not isinstance(frame, dict):
                raise ValueError('Invalid registration screenshot frame')
            viewport = frame.get('viewport', {})
            if (not text(frame.get('id'), 80) or frame['id'] in frame_ids
                    or frame.get('screenshotKind') != 'real'
                    or not isinstance(frame.get('asset'), str) or not ASSET.fullmatch(frame['asset'])
                    or not source_url(frame.get('sourceUrl'), code)
                    or not timestamp(frame.get('verifiedAt'), now)
                    or not text(frame.get('caption'), 500) or not text(frame.get('alt'), 500)
                    or not isinstance(viewport, dict)
                    or not all(type(viewport.get(k)) is int and 100 <= viewport[k] <= 16000 for k in ('width', 'height'))
                    or not isinstance(frame.get('annotations'), list) or not 1 <= len(frame['annotations']) <= 12):
                raise ValueError('Invalid real registration screenshot frame')
            frame_ids.add(frame['id'])
            for note in frame['annotations']:
                if (not isinstance(note, dict) or not text(note.get('label'), 120)
                        or not text(note.get('description'), 500)
                        or not all(type(note.get(k)) in (int, float) and 0 <= note[k] <= 100 for k in ('x', 'y', 'width', 'height'))
                        or note['width'] <= 0 or note['height'] <= 0
                        or note['x'] + note['width'] > 100 or note['y'] + note['height'] > 100):
                    raise ValueError('Invalid registration screenshot annotation')
    return data


def read_registration_guides(root, now=None):
    raw = (Path(root) / 'web/registration-guides.json').read_text(encoding='utf-8')
    if len(raw) > 400000:
        raise ValueError('Registration screenshot configuration is too large')
    return validate_registration_guides(json.loads(raw), now)


def registration_assets(root, data):
    """Disabled images need not exist and are never exported. Active assets fail closed."""
    root = Path(root).resolve()
    asset_root = root / 'web/assets/registration'
    paths = {}
    for entry in data['entries']:
        if entry['status'] != 'verified':
            continue
        for frame in entry['frames']:
            asset = frame['asset']
            path = (root / 'web' / asset).resolve()
            if not path.is_relative_to(asset_root) or not path.is_file():
                raise ValueError('Registration screenshot missing or outside trusted asset directory: ' + asset)
            signature = path.read_bytes()[:12]
            valid = ((path.suffix == '.png' and signature.startswith(b'\x89PNG\r\n\x1a\n'))
                     or (path.suffix in ('.jpg', '.jpeg') and signature.startswith(b'\xff\xd8\xff'))
                     or (path.suffix == '.webp' and signature[:4] == b'RIFF' and signature[8:12] == b'WEBP'))
            if not valid:
                raise ValueError('Registration screenshot is not the declared image format: ' + asset)
            paths[asset] = path
    return paths


def publish_registration_guides(root, output, data):
    paths = registration_assets(root, data)
    target = Path(output) / 'web'
    target.mkdir(parents=True, exist_ok=True)
    (target / 'registration-guides.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for asset, source in paths.items():
        destination = target / asset
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return len(paths)
