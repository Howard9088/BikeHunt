"""Mock transition evidence and durable daily publishing fences; never contact Xiaohongshu."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.social_publishing import DailyPublisher
import test_promotion as evidence_tests


class DailyPublishingTests(unittest.TestCase):
    """Reuse the synthetic evidence harness and its baseline safety tests."""

    def setUp(self):
        evidence_tests.PromotionTests.setUp(self)
        self.publisher = DailyPublisher(self.root, "12345678")
        self.at = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)

    offer = evidence_tests.PromotionTests.offer
    snapshot = evidence_tests.PromotionTests.snapshot
    transition = evidence_tests.PromotionTests.transition

    def ready(self):
        self.transition(at=self.at - timedelta(minutes=1))
        return self.publisher.reserve(self.at)

    def test_no_update_no_post_and_outside_hour_rejected(self):
        self.assertEqual(self.publisher.reserve(self.at)["status"], "no_changes")
        with self.assertRaises(ValueError):
            self.publisher.reserve(self.at - timedelta(hours=1))

    def test_daily_maximum_and_receipt_deduplication(self):
        result = self.ready()
        self.assertEqual(result["status"], "reserved")
        self.assertLessEqual(len(result["payload"]["title"]), 20)
        self.assertLessEqual(len(result["payload"]["text"]), 1000)
        self.assertEqual(self.publisher.reserve(self.at)["status"], "daily_limit")
        job = result["job_id"]
        self.publisher.begin(job, self.at)
        note = "1234567890abcdef12345678"
        receipt = self.publisher.receipt(job, note, "https://www.xiaohongshu.com/explore/" + note)
        self.assertEqual(receipt["note_id"], note)
        self.assertEqual(self.publisher.prepare(self.at)["status"], "no_changes")

    def test_crash_after_begin_fences_retry_even_on_next_day(self):
        job = self.ready()["job_id"]
        self.publisher.begin(job, self.at)
        self.publisher.unknown(job)
        with self.assertRaisesRegex(ValueError, "unresolved"):
            self.publisher.reserve(self.at + timedelta(days=1))

    def test_stock_changed_between_reservation_and_submit_blocks(self):
        job = self.ready()["job_id"]
        self.transition(price="80", stock="out_of_stock", at=self.at)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.publisher.begin(job, self.at + timedelta(seconds=1))

    def test_stale_source_and_initial_discovery_never_publish(self):
        self.transition(at=self.at - timedelta(hours=2))
        self.assertEqual(self.publisher.reserve(self.at)["status"], "no_changes")

    def test_receipt_requires_exact_note_id_and_unresolved_job(self):
        job = self.ready()["job_id"]
        with self.assertRaises(ValueError):
            self.publisher.receipt(job, "1234567890abcdef12345678", "https://example.com/")
        with self.assertRaises(ValueError):
            self.publisher.receipt(
                job,
                "1234567890abcdef12345678",
                "https://www.xiaohongshu.com/explore/1234567890abcdef12345678",
            )


if __name__ == "__main__":
    unittest.main()
