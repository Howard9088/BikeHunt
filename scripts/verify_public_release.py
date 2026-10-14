"""Verify the public manifest, exact snapshot bytes and HTML for this release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_PUBLIC_URL = 'https://howard9088.github.io/BikeHunt/'


class VerificationError(ValueError):
    """The CDN has not delivered a coherent release with the expected identity."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def validate_manifest(manifest: dict, expected_commit: str) -> None:
    require(isinstance(manifest, dict), 'Published manifest must be an object')
    require(type(manifest.get('schema_version')) is int and manifest['schema_version'] == 1,
            'Unsupported publication manifest schema')
    require(manifest.get('commit') == expected_commit, 'CDN still serving older manifest')
    generated_at = manifest.get('generated_at')
    require(isinstance(generated_at, str) and re.fullmatch(
        r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
        r'(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):?[0-5][0-9])',
        generated_at, re.IGNORECASE) is not None,
        'Manifest generated_at must be a timezone-aware ISO timestamp')
    try:
        published_at = datetime.fromisoformat(generated_at.upper())
    except ValueError as exc:
        raise VerificationError('Manifest generated_at is not a valid ISO timestamp') from exc
    require(published_at <= datetime.now(timezone.utc) + timedelta(minutes=5),
            'Manifest generated_at is more than five minutes in the future')
    require(manifest.get('version') == expected_commit + ':' + generated_at,
            'Manifest publication version conflicts')
    snapshot = manifest.get('snapshot')
    require(isinstance(snapshot, dict), 'Manifest snapshot metadata missing')
    # The exporter has one fixed public snapshot. Do not follow arbitrary URLs.
    require(snapshot.get('path') == 'data/site-data.json', 'Unexpected public snapshot path')
    require(type(snapshot.get('bytes')) is int and snapshot['bytes'] > 0,
            'Invalid snapshot byte length')
    require(isinstance(snapshot.get('sha256'), str)
            and re.fullmatch(r'[0-9a-f]{64}', snapshot['sha256']) is not None,
            'Invalid snapshot SHA-256')


def validate_snapshot(manifest: dict, snapshot_bytes: bytes, expected_commit: str) -> dict:
    """Check the raw response before parsing, then compare all publication identity fields."""
    validate_manifest(manifest, expected_commit)
    metadata = manifest['snapshot']
    require(len(snapshot_bytes) == metadata['bytes'], 'Snapshot byte length differs from manifest')
    require(hashlib.sha256(snapshot_bytes).hexdigest() == metadata['sha256'],
            'Snapshot SHA-256 differs from manifest')
    data = json.loads(snapshot_bytes)
    require(isinstance(data, dict), 'Published snapshot must be an object')
    publication = data.get('publication')
    require(isinstance(publication, dict), 'Snapshot publication metadata missing')
    require(publication.get('commit') == expected_commit == manifest['commit'],
            'CDN still serving older snapshot')
    require(publication.get('version') == manifest['version'],
            'Snapshot publication version differs from manifest')
    require(data.get('generated_at') == manifest['generated_at'],
            'Snapshot generated_at differs from manifest')
    return data


def validate_offer_labels(data: dict) -> None:
    # Check source-rule enrichment in the delivered projection, not only parser output.
    for family in data.get('details', {}).values():
        for detail in family['variants'].values():
            for quote in detail['offers']:
                offer = quote['offer']
                status = data.get('collection_status', {}).get(offer['source_code'], {})
                coverage = status.get('coverage', {})
                if (coverage.get('method') == 'shopify_public_feed_plus_product_jsonld'
                        and offer.get('collection_state') != 'retained'):
                    currency = offer['price']['currency']
                    require(f" · {currency} 报价" in offer.get('sales_region', ''),
                            'Published market/currency label conflicts: ' + offer['source_code'])
                    if coverage.get('market_country'):
                        require(offer['sales_region'].startswith((coverage['market_country'] + ' 市场',
                                                                '地区未核实 市场')),
                                'Published country label conflicts: ' + offer['source_code'])


def validate_html(html: str, expected_commit: str) -> None:
    require('世巡车队' in html and '骑行车队' not in html, 'Published team label conflicts')
    require('bikehunt-mark' in html and 'purchaseDisclaimerInfo' in html,
            'Published branding or purchase disclaimer missing')
    require(f'data-release="{expected_commit}"' in html and 'publicationInfo' in html,
            'CDN still serving older HTML')


def fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read()


def verify_release_once(base: str, expected_commit: str, attempt: int = 0) -> dict:
    base = base.rstrip('/') + '/'
    query = {'release': expected_commit, 'attempt': attempt}
    suffix = '?' + urllib.parse.urlencode(query)
    manifest = json.loads(fetch_bytes(base + 'data/publication.json' + suffix))
    validate_manifest(manifest, expected_commit)
    # Bind this download to the chosen build, including rebuilds of the same commit.
    snapshot_suffix = '?' + urllib.parse.urlencode({**query, 'version': manifest['version']})
    snapshot_bytes = fetch_bytes(base + manifest['snapshot']['path'] + snapshot_suffix)
    data = validate_snapshot(manifest, snapshot_bytes, expected_commit)
    validate_offer_labels(data)
    html = fetch_bytes(base + suffix).decode('utf-8')
    validate_html(html, expected_commit)
    return {'verified_public_url': base, 'commit': expected_commit,
            'publication': data['publication'], 'generated_at': data['generated_at'],
            'manifest': manifest, 'collection_status': data.get('collection_status', {})}


def verify_public_release(base: str, expected_commit: str, attempts: int = 18,
                          retry_delay: float = 10) -> dict:
    if attempts < 1:
        raise ValueError('At least one verification attempt is required')
    for attempt in range(attempts):
        try:
            return verify_release_once(base, expected_commit, attempt)
        except Exception as exc:
            # Manifest, snapshot and HTML may propagate through the CDN separately.
            if attempt == attempts - 1:
                raise RuntimeError('Public deployment not verified: ' + str(exc)) from exc
            time.sleep(retry_delay)
    raise AssertionError('Unreachable verification state')


def validate_local_release(directory: Path, expected_commit: str) -> dict:
    manifest = json.loads((directory/'data/publication.json').read_bytes())
    data = validate_snapshot(manifest, (directory/'data/site-data.json').read_bytes(), expected_commit)
    validate_offer_labels(data)
    validate_html((directory/'index.html').read_text(encoding='utf-8'), expected_commit)
    return {'verified_local_artifact': str(directory), 'commit': expected_commit,
            'manifest_bytes': (directory/'data/publication.json').stat().st_size,
            'snapshot_bytes': manifest['snapshot']['bytes']}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--local-dir', type=Path, help='Validate the build before any deployment')
    args = parser.parse_args(argv)
    if args.local_dir:
        print(json.dumps(validate_local_release(args.local_dir, os.environ['GITHUB_SHA'])))
        return
    receipt = verify_public_release(os.environ.get('BIKEHUNT_PUBLIC_URL', DEFAULT_PUBLIC_URL),
                                    os.environ['GITHUB_SHA'])
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
