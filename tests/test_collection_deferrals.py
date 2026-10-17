"""Server-requested long backoff survives CI without caching diagnostics."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from scripts.collect_offers import saved_deferrals, persist_deferrals

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)


class CollectionDeferralTests(unittest.TestCase):
    def test_only_host_and_future_retry_time_persist_then_expire(self):
        until = NOW + timedelta(hours=2)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            persist_deferrals(root, 'oakley', [
                {'url': 'https://www.oakley.com/en-us/product/EXAMPLE?variant=123',
                 'retry_at': until.isoformat(), 'error': 'private diagnostic must not persist'},
                {'url': 'https://www.oakley.com/second', 'retry_at': (until-timedelta(hours=1)).isoformat()},
                {'url': 'https://expired.example/', 'retry_at': (NOW-timedelta(seconds=1)).isoformat()},
                {'url': 'https://invalid.example/', 'retry_at': 'unknown'},
            ], NOW)
            raw = (root/'source_deferrals/oakley.json').read_text()
            self.assertEqual(json.loads(raw), {'www.oakley.com': until.isoformat()})
            self.assertNotIn('private', raw)
            self.assertNotIn('variant', raw)
            self.assertEqual(saved_deferrals(root, 'oakley', NOW)['www.oakley.com'].retry_at, until)
            self.assertEqual(saved_deferrals(root, 'oakley', until), {})

    def test_source_files_do_not_overwrite_other_source_deferrals(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            until = NOW + timedelta(hours=1)
            for source in ('gobik', 'oakley'):
                persist_deferrals(root, source, [{'url': f'https://{source}.example/', 'retry_at': until.isoformat()}], NOW)
            persist_deferrals(root, 'oakley', [], NOW)
            self.assertTrue(saved_deferrals(root, 'gobik', NOW))
            self.assertEqual(saved_deferrals(root, 'oakley', NOW), {})


if __name__ == '__main__':
    unittest.main()
