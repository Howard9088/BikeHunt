"""真实无头浏览器回归：验证 JS 生成的库存、尺码；不访问任何商家。"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from scrapling.fetchers import DynamicFetcher


def main() -> None:
    """本地 Mock 网页延迟生成规格，浏览器等待后必须读取到对应库存。"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'<html><body>Loading<script>setTimeout(()=>{document.body.innerHTML=\'<div id="variant" data-stock="in_stock">M</div>\'},200)</script></body></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = DynamicFetcher.fetch(
            f"http://127.0.0.1:{server.server_port}/",
            headless=True,
            real_chrome=sys.platform == "win32",
            timeout=12000,
            retries=1,
            wait_selector="#variant",
            google_search=False,
        )
        node = response.css("#variant")[0]
        assert response.status == 200 and node.css("::text").get() == "M"
        assert node.attrib.get("data-stock") == "in_stock"
        print(json.dumps({"dynamic_runtime_ok": True, "rendered_size": "M", "stock": "in_stock"}))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    main()
