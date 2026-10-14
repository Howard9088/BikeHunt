"""启动或复用 BikeHunt，健康检查成功后打开浏览器。"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:18888"


def health() -> dict | None:
    """查询本地健康接口；启动期间的不可达返回 None。"""
    try:
        with urllib.request.urlopen(BASE + "/api/health", timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        logger.debug("健康检查未就绪 {}", exc)
        return None


def main() -> int:
    """有界退避等待服务就绪；复用已运行服务，不创建重复进程。"""
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    logger.remove()
    logger.add(logs / "startup.log", rotation="1 MB", retention=3, encoding="utf-8")
    current = health()
    if current and current.get("service") == "BikeHunt":
        if current.get("version") != "0.4.2":
            raise RuntimeError("An older BikeHunt service is running; restart it to load 0.4.2.")
    else:
        try:
            with socket.create_connection(("127.0.0.1", 18888), timeout=1):
                raise RuntimeError("Port 18888 belongs to an unrecognized service.")
        except OSError:
            pass
        with (logs / "server.stdout.log").open("a", encoding="utf-8") as stdout, \
                (logs / "server.stderr.log").open("a", encoding="utf-8") as stderr:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "18888"],
                cwd=ROOT, stdout=stdout, stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        for attempt in range(6):
            current = health()
            if current and current.get("service") == "BikeHunt":
                break
            if process.poll() is not None:
                raise RuntimeError("Server exited; check logs/server.stderr.log.")
            time.sleep(min(2, 0.25 * 2 ** attempt))
        else:
            raise RuntimeError("Server did not become ready; check logs/server.stderr.log.")
    logger.info("BikeHunt ready {}", BASE)
    webbrowser.open(BASE + "/web/")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logger.exception("启动失败")
        print(f"BikeHunt startup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
