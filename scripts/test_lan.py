"""验证手机应使用的 LAN 入口：python scripts/test_lan.py --host 192.168.1.112。"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    args = parser.parse_args()
    base = f"http://{args.host}:18888"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(3):
        try:
            with opener.open(base + "/api/health", timeout=3) as response:
                health = json.load(response)
            assert health.get("service") == "BikeHunt" and health.get("version") == "0.4.2", health
            with opener.open(base + "/web/", timeout=3) as response:
                assert b"gallery.js" in response.read()
            with opener.open(base + "/api/catalog", timeout=5) as response:
                catalog = json.load(response)
            assert catalog["items"]
            print(json.dumps({"ok": True, "url": base + "/web/", "products":len(catalog["items"])},ensure_ascii=True))
            return
        except Exception as exc:
            if attempt == 2:
                print(f"LAN FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
                raise SystemExit(1) from exc
            time.sleep(2 ** attempt)


if __name__ == "__main__":
    main()
