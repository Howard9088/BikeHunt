"""Validate screenshot config/assets; optional first-launch coverage gate only."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.registration_guides import read_registration_guides, registration_assets

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--require-screenshots', action='store_true',
                        help='First launch acceptance only; do not require this for later safety withdrawals.')
    args = parser.parse_args()
    data = read_registration_guides(args.root)
    assets = registration_assets(args.root, data)
    if args.require_screenshots and not assets:
        raise SystemExit('First screenshot launch needs at least one verified real image; do not publish an empty-only launch.')
    print(json.dumps({'revision': data['revision'], 'entries': len(data['entries']),
                      'verified_images': len(assets), 'valid': True}, ensure_ascii=False))
