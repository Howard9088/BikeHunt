"""Mock transition evidence and durable daily publishing fences; never contact Xiaohongshu."""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
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
        self.at = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)

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

    def test_schedule_preparation_waits_until_16_shanghai(self):
        result = self.publisher.check_schedule(self.at - timedelta(minutes=15))
        self.assertEqual(result["status"], "waiting")
        self.assertEqual(result["wait_seconds"], 900)
        self.assertFalse(result["can_publish"])
        self.assertEqual(result["preparation_at"], "2026-10-15T15:45:00+08:00")
        self.assertEqual(result["scheduled_at"], "2026-10-15T16:00:00+08:00")
        almost_open = self.publisher.check_schedule(self.at - timedelta(microseconds=1))
        self.assertEqual(almost_open["wait_seconds"], 1)

    def test_schedule_opening_and_closing_boundaries(self):
        for offset in (0, 3599):
            with self.subTest(offset=offset):
                result = self.publisher.check_schedule(self.at + timedelta(seconds=offset))
                self.assertEqual(result["status"], "open")
                self.assertTrue(result["can_publish"])
        result = self.publisher.check_schedule(self.at + timedelta(hours=1))
        self.assertEqual(result["status"], "missed")
        self.assertTrue(result["alert_required"])

    def test_late_wakeup_is_reported_even_without_price_changes(self):
        self.assertEqual(self.publisher.prepare(self.at)["status"], "no_changes")
        result = self.publisher.check_schedule(self.at + timedelta(hours=1, minutes=49))
        self.assertEqual(result["status"], "missed")
        self.assertEqual(result["lateness_seconds"], 6540)
        self.assertFalse(result["can_publish"])
        self.assertTrue(result["alert_required"])
        persisted = json.loads((self.publisher.folder / "schedule.json").read_text())
        self.assertEqual(persisted, result)
        with self.publisher.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM posts").fetchone()[0], 0)

    def test_schedule_uses_shanghai_date_across_utc_midnight(self):
        result = self.publisher.check_schedule(datetime(2026, 10, 15, 23, 45, tzinfo=timezone.utc))
        self.assertEqual(result["day"], "2026-10-16")
        self.assertEqual(result["status"], "outside_preparation")
        self.assertEqual(result["wait_seconds"], 0)
        self.assertTrue(result["alert_required"])
        with self.assertRaises(ValueError):
            self.publisher.check_schedule(datetime(2026, 10, 16, 18))

    def test_scheduled_cli_reports_missed_before_any_collection_or_reservation(self):
        from scripts import publish_xhs

        (self.publisher.folder / "config.json").write_text(
            json.dumps({"account_id": "12345678"}), encoding="utf-8"
        )
        output = io.StringIO()
        with (
            patch.object(publish_xhs, "ROOT", self.root),
            patch.object(sys, "argv", ["publish_xhs.py", "check-schedule"]),
            patch("app.social_publishing.datetime") as clock,
            patch.object(DailyPublisher, "prepare", side_effect=AssertionError("must check time first")),
            patch.object(DailyPublisher, "reserve", side_effect=AssertionError("must not reserve late")),
            redirect_stdout(output),
        ):
            clock.now.return_value = self.at + timedelta(hours=1, minutes=49)
            publish_xhs.main()
        self.assertEqual(json.loads(output.getvalue())["status"], "missed")

    def test_former_18_hour_cannot_reserve_or_submit(self):
        job = self.ready()["job_id"]
        old_hour = self.at + timedelta(hours=2)
        self.assertEqual(self.publisher.check_schedule(old_hour)["status"], "missed")
        with self.assertRaisesRegex(ValueError, "16:00"):
            self.publisher.reserve(old_hour)
        with self.assertRaisesRegex(ValueError, "Outside"):
            self.publisher.begin(job, old_hour)

    def test_cli_configuration_uses_16_shanghai(self):
        from scripts import publish_xhs

        with (
            patch.object(publish_xhs, "ROOT", self.root),
            patch.object(sys, "argv", ["publish_xhs.py", "configure", "--account", "12345678"]),
            redirect_stdout(io.StringIO()),
        ):
            publish_xhs.main()
        config = json.loads((self.publisher.folder / "config.json").read_text())
        self.assertEqual(config["hour"], 16)
        self.assertEqual(config["timezone"], "Asia/Shanghai")

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
