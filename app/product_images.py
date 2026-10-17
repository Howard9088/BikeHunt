"""Publish byte-identical official images, bound to their exact original URLs."""
import hashlib
import json
import re
import shutil
from urllib.parse import urlsplit


def publish_product_images(root, output):
    manifest=root/'web/product-images.json'
    if not manifest.exists():return
    data=json.loads(manifest.read_text(encoding='utf-8'))
    mapping={}
    for row in data['assets']:
        source=urlsplit(row['source_url'])
        if source.scheme!='https' or source.hostname not in {'assets.oakley.com','assets2.oakley.com'} or source.username or source.password:
            raise ValueError('Product image source must be its recorded official CDN')
        if not re.fullmatch(r'[a-f0-9]{64}\.(png|jpg|webp)',row['file']):raise ValueError('Invalid product image asset')
        asset=root/'web/assets/product-images'/row['file']
        body=asset.read_bytes()
        signature=body.startswith(b'\x89PNG\r\n\x1a\n') or body.startswith(b'\xff\xd8\xff') or body[:4]==b'RIFF' and body[8:12]==b'WEBP'
        if not signature or len(body)!=row['bytes'] or hashlib.sha256(body).hexdigest()!=row['sha256'] or not row['file'].startswith(row['sha256']+'.'):
            raise ValueError('Exact product image bytes differ from source receipt')
        target=output/'web/assets/product-images'/row['file'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(asset,target);mapping[row['source_url']]=row['file']
    (output/'web/product-images.js').write_text('const BikeHuntProductImages=Object.freeze('+json.dumps(mapping)+');\n',encoding='utf-8')
    shutil.copy2(manifest,output/'web/product-images.json')
