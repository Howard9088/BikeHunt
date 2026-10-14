"""Verify that GitHub Pages is serving this commit, not just an old successful build."""
import json
import os
import time
import urllib.request
base = os.environ.get('BIKEHUNT_PUBLIC_URL', 'https://howard9088.github.io/BikeHunt/').rstrip('/')+'/'
expected = os.environ['GITHUB_SHA']
last = None
for attempt in range(18):
    try:
        suffix = '?release='+expected+'&attempt='+str(attempt)
        with urllib.request.urlopen(base+'data/site-data.json'+suffix, timeout=20) as response:
            data = json.load(response)
        with urllib.request.urlopen(base+suffix, timeout=20) as response:
            html = response.read().decode('utf-8')
        assert data.get('publication',{}).get('commit') == expected, 'CDN still serving older snapshot'
        assert '世巡车队' in html and '骑行车队' not in html
        assert 'bikehunt-mark' in html and 'purchaseDisclaimerInfo' in html
        print(json.dumps({'verified_public_url':base,'commit':expected,'publication':data['publication'],'generated_at':data['generated_at'],'collection_status':data.get('collection_status',{})}, ensure_ascii=False))
        break
    except Exception as exc:
        last = exc
        if attempt == 17: raise RuntimeError('Public deployment not verified: '+str(last)) from exc
        time.sleep(10)
