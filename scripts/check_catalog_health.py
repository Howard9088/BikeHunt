"""Gate publication on unexplained catalog loss; report source/image failures.

Runs before and after the existing collector, not a separate scheduled task.
A failed gate leaves the last deployed Pages artifact untouched.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.catalog.storage import OfferRepository, atomic_json
from app.catalog.service import ComparisonCatalog
from app.fx import FxProvider


def capture(root=ROOT):
    rows=OfferRepository(root/'data').load()
    store=ComparisonCatalog(rows,FxProvider(root/'data/fx_latest.json').get(),public_only=True)
    cards=[card.model_dump(mode='json') for card in store.search()]
    return {'captured_at':datetime.now(timezone.utc).isoformat(),
            'cards':cards,'offers':{row.offer_id:row.model_dump(mode='json') for row in rows}}


def inspect(before, after):
    errors, warnings=[],[]
    old={row['product_id']:row for row in before['cards']}
    new={row['product_id']:row for row in after['cards']}
    missing=set(before['offers'])-set(after['offers'])
    if missing: errors.append(f'{len(missing)} prior exact offer records disappeared without a sold-out observation')
    if set(old)-set(new): errors.append(f'{len(set(old)-set(new))} public product families disappeared')
    for group in ['clothing','helmets','cleat_shoes','other','nutrition']:
        previous=[row for row in old.values() if row['category_group']==group and row['stock_state']=='in_stock']
        current=[row for row in new.values() if row['category_group']==group and row['stock_state']=='in_stock']
        if previous and not current:
            sold=all(new.get(row['product_id'],{}).get('stock_state')=='out_of_stock' for row in previous)
            (warnings if sold else errors).append(f'{group}: available category became empty'+(' (affirmative sold-out records retained)' if sold else ' without complete sold-out evidence'))
    for identifier,row in new.items():
        if identifier in old and row['category_group']!=old[identifier]['category_group']:
            errors.append(f'{identifier}: category changed during collection')
        if row['stock_state']!='in_stock':continue
        image=row.get('image')
        valid=isinstance(image,str) and urlsplit(image).scheme=='https' and bool(urlsplit(image).hostname)
        if not valid:
            message=f'{identifier}: in-stock product has no usable exact product image URL'
            (errors if identifier not in old or old[identifier].get('image') else warnings).append(message)
    for identifier,row in after['offers'].items():
        prior=before['offers'].get(identifier)
        if prior and row.get('collection_state')=='retained':
            # Retained is allowed only with the exact old observation, never a
            # synthetic current timestamp or in-stock resurrection.
            if row.get('fetched_at')!=prior.get('fetched_at') or row.get('stock')!=prior.get('stock'):
                errors.append(f'{identifier}: retained observation changed stock or verification time')
    return {'errors':errors,'warnings':warnings,'counts':dict(Counter(row['category_group'] for row in new.values() if row['stock_state']=='in_stock'))}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--before',type=Path,required=True)
    parser.add_argument('--capture',action='store_true')
    parser.add_argument('--built',type=Path)
    args=parser.parse_args()
    if args.capture:
        atomic_json(args.before,capture());print('Saved pre-update catalog baseline');return
    before=json.loads(args.before.read_text(encoding='utf-8'))
    after=capture()
    report=inspect(before,after)
    if args.built:
        payload=json.loads((args.built/'data/site-data.json').read_text(encoding='utf-8'))
        published={row['product_id']:row for row in payload['catalog']['items']}
        expected={row['product_id']:row for row in after['cards']}
        if set(published)!=set(expected):report['errors'].append('Built catalog dropped or added unexpected products')
        for identifier,row in published.items():
            if identifier in expected and any(row.get(key)!=expected[identifier].get(key) for key in ['category_group','image','stock_state','reference_stock']):
                report['errors'].append(f'{identifier}: built category/image/stock differs from collected catalog')
    for path in (ROOT/'data/collection_status').glob('*.json'):
        status=json.loads(path.read_text(encoding='utf-8'))
        if status.get('status') in ['failed','partial']:
            report['warnings'].append(path.stem+': collection '+status['status']+'; exact last-known observations kept at their original times')
    output=ROOT/'artifacts/catalog-health.json'
    atomic_json(output,report)
    for kind,rows in [('error',report['errors']),('warning',report['warnings'])]:
        for message in rows:print(f'::{kind} title=BikeHunt catalog health::{message}')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:
            f.write('\n### Catalog health\n\n'+json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=True))
    if report['errors']:raise SystemExit(1)


if __name__=='__main__':main()
