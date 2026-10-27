"""Replace only the group QR on a byte-preserved published Pages snapshot."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen
import hashlib
import json
import time

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / '_site'
BASE = 'https://howard9088.github.io/BikeHunt/'
IMAGE = 'web/assets/community/group-20261027.jpg'


def download(path: str) -> bytes:
    """Read a fixed site path, retrying temporary network errors."""
    for attempt in range(3):
        try:
            with urlopen(Request(BASE + path, headers={'User-Agent': 'BikeHunt-QR-update'}), timeout=45) as response:
                if response.geturl().split('?', 1)[0] != BASE + path:
                    raise ValueError('Unexpected redirect: ' + path)
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError('unreachable')


def main() -> None:
    """Recreate current public files and change only the group assets."""
    publication = download('data/publication.json')
    manifest = json.loads(publication)
    assert manifest['schema_version'] == 2
    old_group = json.loads(download('data/community.json'))
    local_group = json.loads((SITE / 'data/community.json').read_text(encoding='utf-8'))
    assert local_group['available'] and local_group['image_url'] == '/' + IMAGE
    assert hashlib.sha256((SITE / IMAGE).read_bytes()).hexdigest() == '57747c565ac0d88ff649df14b0108cca47dc00e59cf12495e89f832979f48f70'
    paths = {p.relative_to(SITE).as_posix() for p in SITE.rglob('*') if p.is_file()}
    paths.update({'data/publication.json', 'data/site-data.json', 'data/verification.json'})
    old_image = old_group.get('image_url', '').lstrip('/')
    if old_image.startswith('web/assets/community/'):
        paths.add(old_image)
    paths -= {'.nojekyll', IMAGE, 'data/community.json'}
    def restore(path: str) -> None:
        data = download(path)
        target = SITE / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(restore, sorted(paths)))
    assert download('data/publication.json') == publication, 'Live site changed during copy'
    for field in ('snapshot', 'status'):
        metadata = manifest[field]
        raw = (SITE / metadata['path']).read_bytes()
        assert len(raw) == metadata['bytes'] and hashlib.sha256(raw).hexdigest() == metadata['sha256'], field
    css = SITE / 'web/group.css'
    css.write_bytes(css.read_bytes() + b'\n#groupQr[src*="group-20261027.jpg"]{object-fit:cover;object-position:center}\n')
    print('Preserved', len(paths), 'published files; replaced group QR only')


if __name__ == '__main__':
    main()
