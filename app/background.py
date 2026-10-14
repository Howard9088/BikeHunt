"""有界采集任务与刷新节拍；查询不等待采集，来源失败独立记录。"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from app.catalog.storage import atomic_json
from app.notifications import PersonalNotifier


class RefreshWorker:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.task: asyncio.Task | None = None
        self.price_timer = None
        self.rule_timer = None
        self.pending: set[str] = set()
        self.stopped = False
        self.status = {"state":"idle", "price_interval_seconds":300,"rule_interval_seconds":86400}

    def start(self) -> None:
        self.stopped = False
        loop = asyncio.get_running_loop()
        self.price_timer = loop.call_later(300,self.schedule_prices)
        checked = []
        for path in (self.root/"data/rules").glob("*.json"):
            try:
                book=json.loads(path.read_text(encoding="utf-8"))
                checked.append(datetime.fromisoformat(book["checked_at"].replace("Z","+00:00")))
            except (OSError,ValueError,KeyError,TypeError):
                continue
        delay=max(60,86400-(datetime.now(timezone.utc)-min(checked)).total_seconds()) if checked else 60
        self.rule_timer = loop.call_later(delay,self.schedule_rules)

    def stop(self) -> None:
        self.stopped = True
        self.pending.clear()
        for timer in (self.price_timer,self.rule_timer):
            if timer:
                timer.cancel()
        if self.task:
            self.task.cancel()

    def schedule_prices(self) -> None:
        self.refresh("prices")
        self.price_timer = asyncio.get_running_loop().call_later(300,self.schedule_prices)

    def schedule_rules(self) -> None:
        self.refresh("rules")
        self.rule_timer = asyncio.get_running_loop().call_later(86400,self.schedule_rules)

    def refresh(self, kind: str) -> dict:
        """单任务执行，重复点击返回现有任务状态。"""
        if kind not in {"prices", "rules"}:
            raise ValueError("unknown refresh kind")
        if self.stopped:
            return self.status
        if self.task and not self.task.done():
            if self.status.get("kind") != kind:
                self.pending.add(kind)
            return self.status
        self.status = {key: value for key, value in self.status.items()
                       if key not in {"finished_at", "exit_code", "source_errors", "error"}}
        self.status.update(state="running", kind=kind, started_at=datetime.now(timezone.utc).isoformat())
        self.task=asyncio.create_task(self._run(kind))
        return self.status

    async def _run(self, kind: str) -> None:
        script="collect_offers.py" if kind=="prices" else "collect_rules.py"
        try:
            result=await asyncio.to_thread(subprocess.run,
                [sys.executable,str(self.root/"scripts"/script)],cwd=self.root,
                capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=240,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
            parsed = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
            if kind == "prices":
                failed = sum(bool(row.get("errors")) for row in parsed)
                succeeded = sum(row.get("offers", 0) > 0 for row in parsed)
            else:
                rows = parsed[-1].get("results", []) if parsed else []
                failed = sum(row.get("state") == "failed" for row in rows)
                succeeded = sum(row.get("state") != "failed" for row in rows)
            state = "failed" if result.returncode or not succeeded else "partial" if failed else "success"
            self.status={**self.status,"state":state,"source_errors":failed,
                         "finished_at":datetime.now(timezone.utc).isoformat(),"exit_code":result.returncode}
            atomic_json(self.root/"data"/"refresh_status.json",self.status)
            if kind=="prices" and result.returncode==0:
                await asyncio.to_thread(PersonalNotifier(self.root).dispatch)
            logger.info("后台采集 {} {}",kind,self.status["state"])
        except Exception as exc:
            self.status={**self.status,"state":"failed","error":type(exc).__name__}
            logger.error("后台采集失败 {} {}",kind,type(exc).__name__)
            atomic_json(self.root/"data"/"refresh_status.json",self.status)
        finally:
            self.task=None
            if self.pending and not self.stopped:
                next_kind="rules" if "rules" in self.pending else self.pending.pop()
                self.pending.discard(next_kind)
                asyncio.get_running_loop().call_soon(self.refresh,next_kind)
