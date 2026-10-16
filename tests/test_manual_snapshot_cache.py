"""A crawler cache must not replace the committed manual China observation."""
import copy
import json
import re
import shlex
import subprocess
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from app.catalog.models import FxSnapshot, Offer
from app.catalog.service import ComparisonCatalog

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = "data/offers/decathlon_cn.json"
COMMAND = "git restore --source=HEAD -- " + SNAPSHOT


class ManualSnapshotCacheTests(unittest.TestCase):
    def test_restore_is_unconditional_after_cache_before_consumers(self):
        workflow = (ROOT / ".github/workflows/pages.yml").read_text()
        steps = re.split(r"(?m)^      - ", workflow)[1:]
        cache = next(i for i, step in enumerate(steps)
                     if "uses: actions/cache/restore@" in step)
        restores = [(i, step) for i, step in enumerate(steps)
                    if "run: " + COMMAND in step]
        self.assertEqual(len(restores), 1)
        index, step = restores[0]
        self.assertGreater(index, cache)
        self.assertNotRegex(step, r"(?m)^\s+if:")
        self.assertEqual(step.split("run: ", 1)[1].strip(), COMMAND)
        for consumer in ["python scripts/seed_updates.py",
                         "python -m unittest discover",
                         "node scripts/test_pages_freshness.js"]:
            self.assertLess(index, next(i for i, value in enumerate(steps)
                                       if consumer in value))

    def test_restore_recovers_exact_manual_bytes_leaves_crawler_cache_and_ttl(self):
        committed = (ROOT / SNAPSHOT).read_bytes()
        payload = json.loads(committed)
        self.assertEqual(payload["verification_method"], "manual_public_selected_variant")
        crawl_sources = json.loads((ROOT / "data/crawl_sources.json").read_text())
        self.assertNotIn("decathlon_cn", {row["code"] for row in crawl_sources})
        old = copy.deepcopy(payload)
        old["collected_at"] = "2000-01-01T00:00:00Z"
        for row in old["offers"]:
            row["fetched_at"] = "2000-01-01T00:00:00Z"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manual = root / SNAPSHOT
            manual.parent.mkdir(parents=True)
            manual.write_bytes(committed)
            automatic = manual.with_name("visma.json")
            automatic.write_text('{"cache": "committed"}')

            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True,
                                      capture_output=True, text=True)

            git("init", "-q")
            # The fixture checks exact committed bytes, independently of the host's
            # global Windows checkout conversion. Change only this temporary repo.
            git("config", "core.autocrlf", "false")
            git("add", "data/offers")
            git("-c", "user.name=Snapshot Test", "-c",
                "user.email=snapshot-test@example.invalid", "commit", "-qm", "fixture")
            manual.write_text(json.dumps(old))
            automatic_cache = b'{"cache": "new automatic observation"}\n'
            automatic.write_bytes(automatic_cache)
            # Execute the exact command used by the workflow, without a shell.
            subprocess.run(shlex.split(COMMAND), cwd=root, check=True,
                           capture_output=True, text=True)
            self.assertEqual(manual.read_bytes(), committed)
            self.assertEqual(automatic.read_bytes(), automatic_cache)
            restored = json.loads(manual.read_bytes())
            self.assertEqual(restored["collected_at"], payload["collected_at"])
            fx = FxSnapshot(snapshot_id="manual-cache-test", rates={"CNY": Decimal(1)})
            for before, row in zip(payload["offers"], restored["offers"]):
                self.assertEqual(row["fetched_at"], before["fetched_at"])
                offer = Offer.model_validate(row)
                fresh = ComparisonCatalog([offer], fx, offer.fetched_at + timedelta(minutes=5))
                expired = ComparisonCatalog([offer], fx, offer.fetched_at + timedelta(hours=1, seconds=1))
                self.assertEqual(fresh.search()[0].stock_state, "in_stock")
                self.assertEqual(expired.search()[0].stock_state, "unknown")
                self.assertFalse(expired.search()[0].channel_quotes)


if __name__ == "__main__":
    unittest.main()
