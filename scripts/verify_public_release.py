"""Verify exact public catalog/status bytes and their shared release identity."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.publication import digest, offer_identity, offers_by_id, semantic_projection
from app.catalog.storage import collection_failed

DEFAULT_PUBLIC_URL = 'https://howard9088.github.io/BikeHunt/'


class VerificationError(ValueError):
    """The CDN has not delivered a coherent release with the expected identity."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def validate_timestamp(value: object, label: str) -> datetime:
    require(isinstance(value, str) and re.fullmatch(
        r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
        r'(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):?[0-5][0-9])',
        value, re.IGNORECASE) is not None,
        label + ' must be a timezone-aware ISO timestamp')
    try:
        parsed = datetime.fromisoformat(value.upper())
    except ValueError as exc:
        raise VerificationError(label + ' is not a valid ISO timestamp') from exc
    require(parsed <= datetime.now(timezone.utc) + timedelta(minutes=5),
            label + ' is more than five minutes in the future')
    return parsed


def valid_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def validate_file_metadata(metadata: object, name: str, path: str) -> None:
    require(isinstance(metadata, dict), 'Manifest ' + name.lower() + ' metadata missing')
    # Only these fixed public paths may be read; never follow manifest URLs.
    require(metadata.get('path') == path, 'Unexpected public ' + name.lower() + ' path')
    require(type(metadata.get('bytes')) is int and metadata['bytes'] > 0,
            'Invalid ' + name.lower() + ' byte length')
    require(valid_digest(metadata.get('sha256')), 'Invalid ' + name.lower() + ' SHA-256')


def validate_manifest(manifest: dict, expected_commit: str) -> None:
    require(isinstance(manifest, dict), 'Published manifest must be an object')
    require(type(manifest.get('schema_version')) is int and manifest['schema_version'] in (1, 2),
            'Unsupported publication manifest schema')
    require(manifest.get('commit') == expected_commit, 'CDN still serving older manifest')
    generated_at = manifest.get('generated_at')
    published_at = validate_timestamp(generated_at, 'Manifest generated_at')
    require(manifest.get('version') == expected_commit + ':' + generated_at,
            'Manifest publication version conflicts')
    snapshot = manifest.get('snapshot')
    validate_file_metadata(snapshot, 'Snapshot', 'data/site-data.json')
    if manifest['schema_version'] == 2:
        require(snapshot.get('commit') == expected_commit, 'Manifest references older snapshot commit')
        created_at = validate_timestamp(snapshot.get('generated_at'), 'Snapshot generated_at')
        require(created_at <= published_at, 'Snapshot generated_at is newer than manifest')
        require(valid_digest(snapshot.get('semantic_sha256')), 'Invalid snapshot semantic SHA-256')
        require(snapshot.get('version') == expected_commit + ':catalog:' + snapshot['semantic_sha256'],
                'Manifest snapshot publication version conflicts')
        validate_file_metadata(manifest.get('status'), 'Status', 'data/verification.json')


def parse_verified_bytes(raw: bytes, metadata: dict, name: str) -> dict:
    require(len(raw) == metadata['bytes'], name + ' byte length differs from manifest')
    require(hashlib.sha256(raw).hexdigest() == metadata['sha256'],
            name + ' SHA-256 differs from manifest')
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise VerificationError('Published ' + name.lower() + ' is not valid JSON') from exc
    require(isinstance(data, dict), 'Published ' + name.lower() + ' must be an object')
    return data


def snapshot_offers(data: dict) -> dict:
    """Enumerate the exact projected offer identities, rejecting ambiguous duplicates."""
    identities = data.get('verification_identities')
    require(isinstance(identities, dict), 'Snapshot verification identities missing')
    require(all(isinstance(key, str) and key and valid_digest(value)
                for key, value in identities.items()), 'Invalid snapshot offer content identity')
    families = data.get('details')
    require(isinstance(families, dict), 'Snapshot details missing')
    offers, family_ids = {}, {}
    for product_id, family in families.items():
        require(isinstance(family, dict) and isinstance(family.get('variants'), dict),
                'Snapshot variants missing')
        family_ids[product_id] = set()
        for detail in family['variants'].values():
            require(isinstance(detail, dict) and isinstance(detail.get('offers'), list),
                    'Snapshot offers missing')
            for quote in detail['offers']:
                require(isinstance(quote, dict) and isinstance(quote.get('offer'), dict),
                        'Invalid snapshot offer')
                offer = quote['offer']
                offer_id = offer.get('offer_id')
                require(isinstance(offer_id, str) and bool(offer_id), 'Snapshot offer ID missing')
                require(offer.get('collection_state') in ('current', 'retained'),
                        'Invalid snapshot offer collection state: ' + offer_id)
                require(offer_id not in offers or offers[offer_id] == offer,
                        'Conflicting duplicate snapshot offer: ' + offer_id)
                offers[offer_id] = offer
                family_ids[product_id].add(offer_id)
    require(set(offers) == set(identities), 'Snapshot offer identities do not match exact offer IDs')
    require(offers == offers_by_id(data), 'Snapshot offer projection conflicts')
    for offer_id, offer in offers.items():
        require(identities[offer_id] == offer_identity(offer),
                'Snapshot offer content identity differs: ' + offer_id)
    catalog = data.get('catalog')
    require(isinstance(catalog, dict) and isinstance(catalog.get('items'), list),
            'Snapshot catalog missing')
    for card in catalog['items']:
        require(isinstance(card, dict), 'Invalid snapshot catalog card')
        reference = card.get('reference_offer_id')
        require(isinstance(reference, str) and reference in family_ids.get(card.get('product_id'), set()),
                'Snapshot catalog reference offer ID missing or mismatched')
        require(card.get('reference_collection_state') == offers[reference]['collection_state'],
                'Snapshot catalog reference offer collection state differs')
        if 'reference_original_price' in card or 'reference_variant_id' in card:
            detail = families[card['product_id']]['variants'].get(card.get('reference_variant_id'), {})
            quote = next((row for row in detail.get('offers', [])
                          if row['offer']['offer_id'] == reference), None)
            require(quote is not None, 'Snapshot discount reference variant differs')
            offer = quote['offer']
            identity = offer.get('identity') or {}
            expected = {'reference_price': offer.get('price'),
                        'reference_original_price': offer.get('original_price'),
                        'reference_cny': quote.get('product_cny'),
                        'reference_source': offer.get('source_name'),
                        'reference_size': identity.get('size'),
                        'reference_color': identity.get('color'),
                        'reference_price_valid_until': offer.get('price_valid_until'),
                        'reference_data_kind': offer.get('data_kind', 'live_snapshot'),
                        'fetched_at': offer.get('fetched_at')}
            if 'reference_url' in card:
                expected['reference_url'] = offer.get('url')
            require(all(key in card and card[key] == value for key, value in expected.items()),
                    'Snapshot discount facts differ from exact reference offer')
    return offers


def validate_snapshot(manifest: dict, snapshot_bytes: bytes, expected_commit: str) -> dict:
    """Check raw bytes first, then the catalog's own publication identity."""
    validate_manifest(manifest, expected_commit)
    data = parse_verified_bytes(snapshot_bytes, manifest['snapshot'], 'Snapshot')
    publication = data.get('publication')
    require(isinstance(publication, dict), 'Snapshot publication metadata missing')
    require(publication.get('commit') == expected_commit == manifest['commit'],
            'CDN still serving older snapshot')
    identity = manifest['snapshot'] if manifest['schema_version'] == 2 else manifest
    require(publication.get('version') == identity['version'],
            'Snapshot publication version differs from manifest')
    require(data.get('generated_at') == identity['generated_at'],
            'Snapshot generated_at differs from manifest')
    if manifest['schema_version'] == 2:
        snapshot_offers(data)
        try:
            semantic_hash = digest(semantic_projection(data))
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise VerificationError('Invalid snapshot semantic projection') from exc
        require(semantic_hash == identity['semantic_sha256'],
                'Snapshot semantic SHA-256 differs from manifest')
    return data


def validate_observation(value: object, baseline: object, published_at: datetime,
                         created_at: datetime, label: str) -> datetime | None:
    """Null means unknown; known observations cannot regress or exceed their run."""
    original = validate_timestamp(baseline, 'Snapshot ' + label) if baseline is not None else None
    if original is not None:
        require(original <= created_at, 'Snapshot observation is newer than catalog')
    observed = validate_timestamp(value, label) if value is not None else None
    if observed is not None:
        require(observed <= published_at, label + ' is newer than status')
    if original is not None:
        require(observed is not None and observed >= original, label + ' regresses from snapshot')
    return observed


def same_observation(first: object, second: object) -> bool:
    if first == second:
        return True
    if first is None or second is None:
        return False
    return validate_timestamp(first, 'Observation timestamp') == validate_timestamp(second, 'Observation timestamp')


def verify_status(manifest: dict, status_bytes: bytes, data: dict,
                  expected_commit: str) -> dict:
    """Validate the latest status, bound to the exact already-validated catalog."""
    validate_manifest(manifest, expected_commit)
    require(manifest['schema_version'] == 2, 'Verification status requires schema 2 manifest')
    publication = data.get('publication')
    require(isinstance(publication, dict)
            and publication.get('version') == manifest['snapshot']['version']
            and publication.get('commit') == manifest['snapshot']['commit']
            and data.get('generated_at') == manifest['snapshot']['generated_at'],
            'Status catalog argument differs from manifest snapshot identity')
    status = parse_verified_bytes(status_bytes, manifest['status'], 'Status')
    require(type(status.get('schema_version')) is int and status['schema_version'] == 1,
            'Unsupported verification status schema')
    for field in ('version', 'generated_at', 'commit'):
        require(status.get(field) == manifest[field], 'Status ' + field + ' differs from manifest')
    require(status.get('snapshot_sha256') == manifest['snapshot']['sha256'],
            'Status snapshot SHA-256 differs from manifest')
    offers = snapshot_offers(data)
    published_at = validate_timestamp(status['generated_at'], 'Status generated_at')
    created_at = validate_timestamp(data.get('generated_at'), 'Snapshot generated_at')
    collection = status.get('collection_status')
    require(isinstance(collection, dict), 'Status collection_status missing')
    require(all(isinstance(value, dict) for value in collection.values()),
            'Invalid status collection_status entry')
    for source_code, source in collection.items():
        require('source_code' not in source or source['source_code'] == source_code,
                'Source collection identity differs')
        if 'attempted_at' in source:
            attempted = validate_timestamp(source['attempted_at'], 'Source attempted_at')
            require(attempted <= published_at, 'Source attempted_at is newer than status')
        if 'errors' in source:
            require(isinstance(source['errors'], list)
                    and all(isinstance(error, dict) for error in source['errors']),
                    'Invalid source collection errors')
    updates = status.get('offers')
    require(isinstance(updates, dict) and set(updates) == set(offers),
            'Status offer IDs do not match exact snapshot offer IDs')
    for offer_id, offer in offers.items():
        update = updates[offer_id]
        require(isinstance(update, dict), 'Invalid verification status offer: ' + offer_id)
        require(update.get('content_sha256') == data['verification_identities'][offer_id],
                'Status offer content identity differs: ' + offer_id)
        require(update.get('collection_state') == offer['collection_state'],
                'Status offer collection state differs: ' + offer_id)
        require('fetched_at' in update, 'Status offer fetched_at missing: ' + offer_id)
        observed_at = validate_observation(update['fetched_at'], offer.get('fetched_at'),
                                           published_at, created_at, 'Status offer fetched_at: ' + offer_id)
        if offer['collection_state'] == 'retained':
            require(same_observation(update['fetched_at'], offer.get('fetched_at')),
                    'Retained offer verification time changed: ' + offer_id)
        source = collection.get(offer.get('source_code'), {})
        errors = source.get('errors') or []
        require(isinstance(errors, list) and all(isinstance(error, dict) for error in errors),
                'Invalid source collection errors')
        failed = collection_failed(offer, source)
        if failed:
            attempted_at = validate_timestamp(source.get('attempted_at'), 'Source attempted_at')
            require(attempted_at <= published_at, 'Source attempted_at is newer than status')
            if observed_at is None or attempted_at > observed_at:
                require(offer['collection_state'] == 'retained',
                        'Failed source offer is not retained: ' + offer_id)
            original = offer.get('fetched_at')
            if original is None or attempted_at > validate_timestamp(original, 'Snapshot offer fetched_at'):
                require(same_observation(update['fetched_at'], original),
                        'Failed source cannot renew offer verification time: ' + offer_id)
    fx = status.get('fx')
    baseline_fx = data['catalog'].get('fx')
    require(isinstance(baseline_fx, dict) and isinstance(fx, dict), 'Status or snapshot FX missing')
    require(isinstance(baseline_fx.get('snapshot_id'), str) and bool(baseline_fx['snapshot_id'])
            and fx.get('snapshot_id') == baseline_fx['snapshot_id'], 'Status FX snapshot identity differs')
    require(type(fx.get('stale')) is bool and type(baseline_fx.get('stale')) is bool
            and fx['stale'] == baseline_fx['stale'], 'Status FX stale state differs')
    require('fetched_at' in fx, 'Status FX fetched_at missing')
    validate_observation(fx['fetched_at'], baseline_fx.get('fetched_at'), published_at,
                         created_at, 'Status FX fetched_at')
    fx_copies = [data.get('updates', {}).get('fx')]
    fx_copies.extend(detail.get('fx') for family in data['details'].values()
                     for detail in family['variants'].values())
    for item in fx_copies:
        require(isinstance(item, dict) and item.get('snapshot_id') == baseline_fx['snapshot_id'],
                'Snapshot FX copies have conflicting identity')
        require(type(item.get('stale')) is bool and item['stale'] == baseline_fx['stale']
                and same_observation(item.get('fetched_at'), baseline_fx.get('fetched_at')),
                'Snapshot FX copies have conflicting state or observation')
    return status


def validate_offer_labels(data: dict) -> None:
    # Check source-rule enrichment in the delivered projection, not only parser output.
    for family in data.get('details', {}).values():
        for detail in family['variants'].values():
            for quote in detail['offers']:
                offer = quote['offer']
                status = data.get('collection_status', {}).get(offer['source_code'], {})
                coverage = status.get('coverage') or {}
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
    require('bikehunt-lockup' in html and 'bikehunt-logo.svg' in html and 'purchaseDisclaimerInfo' in html,
            'Published branding or purchase disclaimer missing')
    require(f'data-release="{expected_commit}"' in html and 'publicationInfo' in html,
            'CDN still serving older HTML')


def fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read()


def verify_release_once(base: str, expected_commit: str, attempt: int = 0, *,
                        expected_run_id: str | None = None,
                        expected_run_attempt: str | None = None) -> dict:
    base = base.rstrip('/') + '/'
    query = {'release': expected_commit, 'attempt': attempt}
    suffix = '?' + urllib.parse.urlencode(query)
    manifest = json.loads(fetch_bytes(base + 'data/publication.json' + suffix))
    validate_manifest(manifest, expected_commit)
    # Include the selected verification run even when the catalog is byte-identical.
    snapshot_suffix = '?' + urllib.parse.urlencode({**query, 'version': manifest['version']})
    snapshot_bytes = fetch_bytes(base + manifest['snapshot']['path'] + snapshot_suffix)
    data = validate_snapshot(manifest, snapshot_bytes, expected_commit)
    status = None
    if manifest['schema_version'] == 2:
        status_bytes = fetch_bytes(base + manifest['status']['path'] + snapshot_suffix)
        status = verify_status(manifest, status_bytes, data, expected_commit)
    if expected_run_id is not None:
        require(status is not None and str(status.get('run_id')) == str(expected_run_id),
                'CDN still serving a different workflow run')
    if expected_run_attempt is not None:
        require(status is not None and str(status.get('run_attempt')) == str(expected_run_attempt),
                'CDN still serving a different workflow attempt')
    current_data = {**data, 'collection_status': status['collection_status']} if status else data
    validate_offer_labels(current_data)
    html = fetch_bytes(base + suffix).decode('utf-8')
    validate_html(html, expected_commit)
    receipt = {'verified_public_url': base, 'commit': expected_commit,
               'publication': {'version': manifest['version'], 'commit': manifest['commit']}
                    if status else data['publication'],
               'generated_at': manifest['generated_at'],
               'manifest': manifest, 'collection_status': current_data.get('collection_status', {})}
    if status:
        receipt.update(verification=status, snapshot_publication=data['publication'],
                       snapshot_generated_at=data['generated_at'])
    receipt['verified_at'] = datetime.now(timezone.utc).isoformat()
    if 'listing_history' in data:
        from app.catalog.listings import confirm_public_listing, snapshot_families
        receipt['listing_history'] = confirm_public_listing(data['listing_history'], snapshot_families(data),
            verified_at=receipt['verified_at'], snapshot_sha256=manifest['snapshot']['sha256'],
            commit=expected_commit, snapshot_generated_at=data['generated_at'])
    return receipt


def verify_public_release(base: str, expected_commit: str, attempts: int = 18,
                          retry_delay: float = 10, *, expected_run_id: str | None = None,
                          expected_run_attempt: str | None = None) -> dict:
    if attempts < 1:
        raise ValueError('At least one verification attempt is required')
    for attempt in range(attempts):
        try:
            return verify_release_once(base, expected_commit, attempt,
                **({'expected_run_id': expected_run_id, 'expected_run_attempt': expected_run_attempt}
                   if expected_run_id is not None or expected_run_attempt is not None else {}))
        except Exception as exc:
            # Manifest, catalog, status and HTML can propagate through the CDN separately.
            if attempt == attempts - 1:
                raise RuntimeError('Public deployment not verified: ' + str(exc)) from exc
            time.sleep(retry_delay)
    raise AssertionError('Unreachable verification state')


def validate_local_release(directory: Path, expected_commit: str) -> dict:
    manifest_bytes = (directory/'data/publication.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    data = validate_snapshot(manifest, (directory/'data/site-data.json').read_bytes(), expected_commit)
    status = None
    if manifest['schema_version'] == 2:
        status = verify_status(manifest, (directory/'data/verification.json').read_bytes(),
                               data, expected_commit)
    current_data = {**data, 'collection_status': status['collection_status']} if status else data
    validate_offer_labels(current_data)
    validate_html((directory/'index.html').read_text(encoding='utf-8'), expected_commit)
    receipt = {'verified_local_artifact': str(directory), 'commit': expected_commit,
               'manifest_bytes': len(manifest_bytes), 'snapshot_bytes': manifest['snapshot']['bytes']}
    if status:
        receipt['status_bytes'] = manifest['status']['bytes']
    return receipt


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--local-dir', type=Path, help='Validate the build before any deployment')
    parser.add_argument('--record-listings', action='store_true', help='Persist minimal first-public receipts only after public verification')
    args = parser.parse_args(argv)
    if args.local_dir:
        print(json.dumps(validate_local_release(args.local_dir, os.environ['GITHUB_SHA'])))
        return
    receipt = verify_public_release(os.environ.get('BIKEHUNT_PUBLIC_URL', DEFAULT_PUBLIC_URL),
                                    os.environ['GITHUB_SHA'],
                                    expected_run_id=os.environ.get('GITHUB_RUN_ID'),
                                    expected_run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT'))
    history = receipt.pop('listing_history', None)
    if args.record_listings and history is not None:
        from app.catalog.storage import atomic_json
        atomic_json(Path(__file__).resolve().parents[1]/'data/listing_receipts/ledger.json', history)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
