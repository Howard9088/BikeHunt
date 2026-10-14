"""后台刷新独立 Mock 测试：python tests/test_background.py，无网络或生产写入。"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.background import RefreshWorker


class BackgroundTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.worker = RefreshWorker(Path(self.temp.name))
        self.addCleanup(self.worker.stop)

    async def test_partial_collection_and_queued_rule_refresh(self) -> None:
        """重复价格刷新合并；不同类型排队，部分失败保留正确状态。"""
        gate = asyncio.Event()
        started = asyncio.Event()
        rule_started = asyncio.Event()
        rule_gate = asyncio.Event()
        calls: list[str] = []
        notifier = Mock()

        async def run(_function, arguments, **_kwargs):
            kind = Path(arguments[1]).name
            calls.append(kind)
            if kind == "collect_offers.py":
                started.set()
                await gate.wait()
                return subprocess.CompletedProcess(arguments, 0,
                    '{"offers":2,"errors":[]}\n{"offers":0,"errors":["timeout"]}\n', "")
            rule_started.set()
            await rule_gate.wait()
            return subprocess.CompletedProcess(arguments, 0,
                '{"results":[{"state":"translated"}]}\n', "")

        with patch("app.background.asyncio.to_thread", side_effect=run), \
                patch("app.background.PersonalNotifier", return_value=notifier):
            self.worker.refresh("prices")
            first = self.worker.task
            await started.wait()
            self.worker.refresh("prices")
            self.worker.refresh("rules")
            self.assertIs(self.worker.task, first)
            self.assertEqual(self.worker.pending, {"rules"})
            # Keep dispatch synchronous inside this Mock so its call can be inspected.
            async def run_with_dispatch(function, *arguments, **kwargs):
                if function == notifier.dispatch:
                    function()
                    return None
                return await run(function, *arguments, **kwargs)
            with patch("app.background.asyncio.to_thread", side_effect=run_with_dispatch):
                gate.set()
                await first
                saved = json.loads((self.worker.root/"data/refresh_status.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["state"], "partial")
                await asyncio.wait_for(rule_started.wait(), 2)
                rule_gate.set()
                if self.worker.task:
                    await self.worker.task
            self.assertEqual(calls, ["collect_offers.py", "collect_rules.py"])
            notifier.dispatch.assert_called_once()
            self.assertEqual(self.worker.status["state"], "success")

    async def test_stop_cancels_without_starting_pending_work(self) -> None:
        gate = asyncio.Event()
        async def run(*_args, **_kwargs):
            await gate.wait()
        with patch("app.background.asyncio.to_thread", side_effect=run):
            self.worker.refresh("prices")
            task = self.worker.task
            await asyncio.sleep(0)
            self.worker.refresh("rules")
            self.worker.stop()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0)
            self.assertIsNone(self.worker.task)
            self.assertFalse(self.worker.pending)
            self.worker.refresh("rules")
            self.assertIsNone(self.worker.task)

    async def test_timeout_is_failed_and_does_not_dispatch(self) -> None:
        notifier = Mock()
        with patch("app.background.asyncio.to_thread", side_effect=TimeoutError()), \
                patch("app.background.PersonalNotifier", return_value=notifier):
            self.worker.refresh("prices")
            await self.worker.task
            self.assertEqual(self.worker.status["state"], "failed")
            self.assertEqual(self.worker.status["error"], "TimeoutError")
            notifier.dispatch.assert_not_called()

    async def test_invalid_kind_never_starts_work(self) -> None:
        with self.assertRaises(ValueError):
            self.worker.refresh("invalid")
        self.assertIsNone(self.worker.task)


if __name__ == "__main__":
    unittest.main(verbosity=2)
