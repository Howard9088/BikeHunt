"""Validate complete payment research and, optionally, its exact built assets."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.payment_methods import read_payment_methods


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local-dir', type=Path)
    args = parser.parse_args()
    data = read_payment_methods(ROOT)
    assets = ('payment-methods.js', 'payment-methods.json', 'payment-channels.json')
    hashes = {}
    for name in assets:
        content = (ROOT / 'web' / name).read_bytes()
        hashes[name] = hashlib.sha256(content).hexdigest()
        if args.local_dir and (args.local_dir / 'web' / name).read_bytes() != content:
            raise ValueError('Built payment asset differs from validated source: ' + name)
    print(json.dumps({'status': 'passed', 'entries': len(data['entries']),
                      'methods': sum(len(row['methods']) for row in data['entries']),
                      'asset_sha256': hashes}, ensure_ascii=False))


if __name__ == '__main__':
    main()
