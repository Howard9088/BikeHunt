"""公开游标恢复独立 Mock 测试：python tests/test_seed_updates.py。"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import call, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.catalog.models import Money, Offer, ProductIdentity
from app.updates import UpdateStore
from scripts import seed_updates as seed

PUBLIC_URL = "https://example.org/BikeHunt/"


def public_event(event_id: int) -> dict:
    """返回金额单位为 USD 元的完整公开 Mock 事件。"""
    return {
        "id": event_id,
        "event_key": hashlib.sha256(
            f"mock-event-{event_id}".encode(),
        ).hexdigest(),
        "kind": "new_offer", "source_code": "mock", "source_name": "Mock 商城",
        "offer_id": f"mock-{event_id}", "name_zh": "Mock 骑行上衣",
        "category": "jerseys", "old_price": None, "new_price": "100.00",
        "currency": "USD", "stock": "in_stock",
        "observed_at": "2026-10-14T00:00:00+00:00",
        "url": f"https://example.org/product/{event_id}",
    }


class SeedUpdatesTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="bikehunt-seed-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "data").mkdir()
        self.write_seed([public_event(5)])

    def write_seed(self, events: list[dict]) -> None:
        (self.root / "data/public_updates.json").write_text(
            json.dumps(events, ensure_ascii=False), encoding="utf-8",
        )

    def published_response(
        self, events: list[dict], cursor: int,
    ) -> io.BytesIO:
        data = {"updates": {"items": events, "cursor": cursor}}
        return io.BytesIO(json.dumps(data).encode())

    def next_event_id(self) -> int:
        """走正式事件捕获入口，验证 SQLite 下一条自增 ID。"""
        offer = Offer(
            offer_id="new-mock-offer", source_code="mock",
            source_name="Mock 商城",
            identity=ProductIdentity(brand="Mock", model="Jersey"),
            name="Mock Jersey", url="https://example.org/new-product",
            price=Money(amount="90.00", currency="USD"), stock="in_stock",
            fetched_at=datetime.now(timezone.utc),
        )
        return UpdateStore(self.root).capture([], [offer])[0]["id"]

    def test_published_cursor_wins_over_old_repository_seed(self) -> None:
        with patch.object(
            seed.urllib.request, "urlopen",
            return_value=self.published_response([public_event(86)], 100),
        ) as request:
            result = seed.restore_public_cursor(self.root, PUBLIC_URL)
        self.assertEqual(result, {
            "source": "published", "restored": 1, "cursor": 100,
        })
        self.assertEqual(UpdateStore(self.root).latest()[0]["id"], 86)
        self.assertEqual(self.next_event_id(), 101)
        self.assertEqual(
            request.call_args.args[0].full_url,
            PUBLIC_URL + "data/site-data.json",
        )
        self.assertEqual(request.call_args.kwargs["timeout"], 12)

    def test_cursor_without_records_still_reserves_sequence(self) -> None:
        with patch.object(
            seed.urllib.request, "urlopen",
            return_value=self.published_response([], 200),
        ):
            result = seed.restore_public_cursor(self.root, PUBLIC_URL)
        self.assertEqual(result["cursor"], 200)
        self.assertEqual(self.next_event_id(), 201)

    def test_cache_loss_never_reuses_published_event_id(self) -> None:
        self.write_seed([public_event(85)])
        with patch.object(
            seed.urllib.request, "urlopen",
            return_value=self.published_response([public_event(86)], 86),
        ):
            seed.restore_public_cursor(self.root, PUBLIC_URL)
        self.assertEqual(self.next_event_id(), 87)
        self.assertEqual(UpdateStore(self.root).latest(after=86)[0]["id"], 87)

    def test_nonempty_event_database_skips_network_and_keeps_ids(self) -> None:
        seed.restore_public_cursor(self.root)
        with patch.object(seed.urllib.request, "urlopen") as request:
            result = seed.restore_public_cursor(self.root, PUBLIC_URL)
        request.assert_not_called()
        self.assertEqual(result, {
            "source": "existing", "restored": 0, "cursor": 5,
        })
        self.assertEqual(self.next_event_id(), 6)

    def test_network_retries_with_backoff_then_uses_repository(self) -> None:
        with (
            patch.object(
                seed.urllib.request, "urlopen",
                side_effect=URLError("Mock offline"),
            ) as request,
            patch.object(seed.time, "sleep") as sleep,
        ):
            result = seed.restore_public_cursor(self.root, PUBLIC_URL)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(1), call(2)])
        self.assertEqual(result, {
            "source": "repository", "restored": 1, "cursor": 5,
        })
        self.assertEqual(self.next_event_id(), 6)

    def test_transient_failure_recovers_published_cursor(self) -> None:
        with (
            patch.object(seed.urllib.request, "urlopen", side_effect=[
                URLError("Mock retry"),
                self.published_response([public_event(8)], 9),
            ]) as request,
            patch.object(seed.time, "sleep") as sleep,
        ):
            result = seed.restore_public_cursor(self.root, PUBLIC_URL)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(1)
        self.assertEqual(result["source"], "published")
        self.assertEqual(self.next_event_id(), 10)

    def test_invalid_published_cursor_falls_back_atomically(self) -> None:
        with (
            patch.object(
                seed.urllib.request, "urlopen",
                side_effect=lambda *args, **kwargs: self.published_response(
                    [public_event(8)], 7,
                ),
            ),
            patch.object(seed.time, "sleep"),
        ):
            result = seed.restore_public_cursor(self.root, PUBLIC_URL)
        self.assertEqual(result["source"], "repository")
        self.assertEqual(
            [row["id"] for row in UpdateStore(self.root).latest()], [5],
        )

    def test_invalid_repository_seed_fails_atomically(self) -> None:
        invalid = public_event(6)
        invalid["new_price"] = "NaN"
        self.write_seed([public_event(5), invalid])
        with self.assertRaises(ValueError):
            seed.restore_public_cursor(self.root)
        self.assertEqual(UpdateStore(self.root).latest(), [])

    def test_missing_seed_is_a_valid_first_publication(self) -> None:
        (self.root / "data/public_updates.json").unlink()
        self.assertEqual(seed.restore_public_cursor(self.root)["cursor"], 0)
        self.assertEqual(self.next_event_id(), 1)

    def test_validation_rejects_malformed_public_event_fields(self) -> None:
        changes = (
            {"id": True}, {"id": "8"}, {"new_price": "Infinity"},
            {"old_price": "-1"}, {"currency": "usd"}, {"stock": "guessed"},
            {"observed_at": "2026-10-14T00:00:00"},
            {"url": "http://example.org/product"},
            {"url": "https://user:password@example.org/product"},
            {"event_key": "invalid"}, {"name_zh": " "},
            {"private_token": "must-not-import"},
        )
        for update in changes:
            with self.subTest(update=update), self.assertRaises(ValueError):
                seed.validate_events([public_event(8) | update], 8)

    def test_validation_rejects_duplicates_and_invalid_cursors(self) -> None:
        for cursor in (True, -1, "8", 8.0, 2**63 - 1):
            with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                seed.validate_events([], cursor)
        duplicate_key = public_event(9) | {
            "event_key": public_event(8)["event_key"],
        }
        cases = (
            ([public_event(8), public_event(8)], 8),
            ([public_event(8), duplicate_key], 9),
            ([public_event(8)], 7),
            ([public_event(8)] * 101, 8),
        )
        for events, cursor in cases:
            with (
                self.subTest(events=len(events), cursor=cursor),
                self.assertRaises(ValueError),
            ):
                seed.validate_events(events, cursor)


if __name__ == "__main__":
    unittest.main(verbosity=2)
