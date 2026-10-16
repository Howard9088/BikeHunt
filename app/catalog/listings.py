"""Persistent first-public-listing facts, independent of inventory observations.

A builder may prepare pending identities but cannot date them. Only the public
receipt verifier may confirm a pending family after reading its exact published
snapshot. Old unknown history stays unknown; this is never a merchant launch date.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Iterable


def utc_timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError('Listing timestamp must be a string')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Invalid listing timestamp') from exc
    if stamp.tzinfo is None:
        raise ValueError('Listing timestamp must include a timezone')
    return stamp.astimezone(timezone.utc)


def family_records(catalog) -> list[dict]:
    """Exact existing family identities; new sizes are aliases, not new cards."""
    result = []
    for product_id, variants in catalog.families.items():
        offers = [offer for variant in variants for offer in variant]
        aliases = set()
        for offer in offers:
            identity = offer.identity
            # Keep exact family URLs and explicit color/year/model; never infer
            # cross-source equivalence from an image, title prefix or size token.
            key = [offer.source_code, offer.family_hint or offer.url,
                   identity.brand, identity.model, identity.color, identity.year, identity.gender]
            aliases.add(hashlib.sha256(json.dumps(key, ensure_ascii=False,
                separators=(',', ':')).encode()).hexdigest())
        result.append({'product_id': product_id, 'aliases': sorted(aliases),
                       'available': any(catalog.available(offer) for offer in offers)})
    return result


def validate_ledger(ledger: dict) -> None:
    if not isinstance(ledger, dict) or ledger.get('schema_version') != 1 or not isinstance(ledger.get('entries'), dict):
        raise ValueError('Invalid listing ledger schema')
    for product_id, row in ledger['entries'].items():
        if not isinstance(product_id, str) or not product_id or not isinstance(row, dict):
            raise ValueError('Invalid listing identity')
        if row.get('state') not in {'legacy_unknown', 'pending', 'confirmed'}:
            raise ValueError('Invalid listing state')
        aliases = row.get('aliases')
        if not isinstance(aliases, list) or not aliases or len(aliases) != len(set(aliases)) or any(not isinstance(x, str) or not re.fullmatch('[a-f0-9]{64}', x) for x in aliases):
            raise ValueError('Invalid listing aliases')
        if row['state'] == 'confirmed':
            stamp = utc_timestamp(row.get('first_listed_at'))
            receipt = row.get('receipt')
            if not isinstance(receipt, dict) or not re.fullmatch('[a-f0-9]{64}', str(receipt.get('snapshot_sha256', ''))) or not re.fullmatch('[a-f0-9]{40}', str(receipt.get('commit', ''))):
                raise ValueError('Confirmed listing requires exact public snapshot receipt')
            if utc_timestamp(receipt.get('verified_at')) != stamp:
                raise ValueError('Listing date is the actual receipt time')
        elif row.get('first_listed_at') is not None or row.get('receipt') is not None:
            raise ValueError('Unknown or pending listing cannot carry a date')


def bootstrap_legacy(families: Iterable[dict]) -> dict:
    """Register every already-public family without inventing historical dates."""
    ledger = {'schema_version': 1, 'entries': {}}
    for family in families:
        ledger['entries'][family['product_id']] = {'state': 'legacy_unknown',
            'aliases': sorted(set(family['aliases'])), 'first_listed_at': None}
    validate_ledger(ledger)
    return ledger


def prepare_listing_history(ledger: dict, families: Iterable[dict]) -> dict:
    """Prepare publication identities only. No build/refresh can date a listing."""
    validate_ledger(ledger)
    result = copy.deepcopy(ledger)
    for family in families:
        product_id = family['product_id']
        aliases = set(family['aliases'])
        known = [row for key, row in result['entries'].items()
                 if key == product_id or aliases.intersection(row['aliases'])]
        if not known:
            row = {'state': 'pending', 'aliases': sorted(aliases), 'first_listed_at': None}
        else:
            # A merger containing old unknown history must not look freshly new.
            legacy = next((x for x in known if x['state'] == 'legacy_unknown'), None)
            confirmed = [x for x in known if x['state'] == 'confirmed']
            selected = legacy or (min(confirmed, key=lambda x: utc_timestamp(x['first_listed_at'])) if confirmed else known[0])
            row = copy.deepcopy(selected)
            row['aliases'] = sorted(aliases.union(*(set(x['aliases']) for x in known)))
        result['entries'][product_id] = row
    # Missing/sold-out families are retained as tombstones, not deleted.
    validate_ledger(result)
    return result


def confirm_public_listing(published_ledger: dict, published_families: Iterable[dict], *,
                           verified_at: str, snapshot_sha256: str, commit: str,
                           snapshot_generated_at: str) -> dict:
    """Called only after the existing verifier validates the public SHA/commit.

Arguments must come from that verified snapshot, never an unserved local build.
The receipt timestamp records observation of successful public visibility, not
an assumed server deployment instant. Caller persists the result for a later
successful publication; this function never starts another deployment.
"""
    validate_ledger(published_ledger)
    when = utc_timestamp(verified_at)
    if utc_timestamp(snapshot_generated_at) > when:
        raise ValueError('Cannot verify a snapshot before it was generated')
    if not re.fullmatch('[a-f0-9]{64}', snapshot_sha256) or not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('Invalid public receipt identity')
    result = copy.deepcopy(published_ledger)
    for family in published_families:
        row = result['entries'].get(family['product_id'])
        if not row or row['state'] != 'pending' or family['available'] is not True:
            continue
        if not set(family['aliases']).issubset(row['aliases']):
            raise ValueError('Published family does not match the prepared ledger')
        row['state'] = 'confirmed'
        row['first_listed_at'] = when.isoformat()
        row['receipt'] = {'verified_at': when.isoformat(),
                          'snapshot_sha256': snapshot_sha256, 'commit': commit}
    validate_ledger(result)
    return result


def first_listed_at(ledger: dict, product_id: str) -> str | None:
    row = ledger['entries'].get(product_id)
    return row.get('first_listed_at') if row and row['state'] == 'confirmed' else None


def snapshot_families(snapshot: dict) -> list[dict]:
    """Only exact families actually present in a verified public snapshot."""
    result=[]
    for card in snapshot['catalog']['items']:
        aliases=set()
        for detail in snapshot.get('details',{}).get(card['product_id'],{}).get('variants',{}).values():
            for quote in detail.get('offers',[]):
                offer=quote['offer'];identity=offer['identity']
                key=[offer['source_code'],offer.get('family_hint') or offer['url'],identity['brand'],identity['model'],identity.get('color'),identity.get('year'),identity.get('gender')]
                aliases.add(hashlib.sha256(json.dumps(key,ensure_ascii=False,separators=(',',':')).encode()).hexdigest())
        if not aliases: continue
        candidates=[card,*card.get('channel_quotes',{}).values()]
        def reliable(c):
            try: observed=utc_timestamp(c.get('fetched_at'))
            except ValueError: return False
            return (c.get('stock_state')=='in_stock' and c.get('reference_stock')=='in_stock'
                and c.get('reference_data_kind','live_snapshot')=='live_snapshot'
                and observed<=utc_timestamp(snapshot['generated_at']))
        available=any(reliable(c) for c in candidates)
        result.append({'product_id':card['product_id'],'aliases':sorted(aliases),'available':available})
    return result


def read_listing_history(root) -> dict:
    """Runtime receipts are reconciled with verified public state by seed_updates."""
    from pathlib import Path
    for path in [Path(root)/'data/listing_receipts/ledger.json',Path(root)/'data/listing_history.json']:
        try:
            ledger=json.loads(path.read_text());validate_ledger(ledger);return ledger
        except (OSError,ValueError,TypeError): continue
    return bootstrap_legacy([])


def recover_listing_history(root, snapshot: dict, manifest: dict | None) -> dict:
    """Accept cached new receipts only for this exact verified public release.

    If a receipt cache was lost, an already-public pending family becomes
    unknown, never freshly dated by a later successful run.
    """
    from pathlib import Path
    from app.catalog.storage import atomic_json
    published=snapshot.get('listing_history')
    if published is not None: validate_ledger(published)
    else:
        try:
            published=json.loads((Path(root)/'data/listing_history.json').read_text());validate_ledger(published)
        except (OSError,ValueError,TypeError): published=bootstrap_legacy([])
    families=snapshot_families(snapshot)
    result=prepare_listing_history(published,families)
    cached=read_listing_history(root)
    now=datetime.now(timezone.utc)
    for family in families:
        key=family['product_id'];row=result['entries'][key]
        if row['state']!='pending': continue
        candidate=cached['entries'].get(key,{})
        receipt=candidate.get('receipt',{})
        if (manifest and candidate.get('state')=='confirmed' and family['available']
            and set(family['aliases']).issubset(candidate['aliases'])
            and receipt.get('commit')==manifest['commit']
            and receipt.get('snapshot_sha256')==manifest['snapshot']['sha256']
            and utc_timestamp(manifest['generated_at'])<=utc_timestamp(receipt['verified_at'])<=now):
            result['entries'][key]=copy.deepcopy(candidate)
        else:
            row['state']='legacy_unknown';row['first_listed_at']=None;row.pop('receipt',None)
    atomic_json(Path(root)/'data/listing_receipts/ledger.json',result)
    return result
