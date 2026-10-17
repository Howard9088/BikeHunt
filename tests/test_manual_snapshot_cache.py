"""Committed historical observations bootstrap clean CI; refreshed caches survive runs."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AutomatedSnapshotCacheTests(unittest.TestCase):
    def test_cache_is_restored_after_fixture_tests_before_collection(self):
        workflow = (ROOT / '.github/workflows/pages.yml').read_text()
        # Each job has its own workspace; the read-only article preflight does
        # not run fixture writers. Enforce ordering within the publishing job.
        publish = re.split(r'(?m)^  publish:\n', workflow, maxsplit=1)[1]
        steps = re.split(r'(?m)^      - ', publish)[1:]
        cache = next(i for i, step in enumerate(steps)
                     if 'uses: actions/cache/restore@' in step and 'data/offers' in step)
        tests = next(i for i, step in enumerate(steps) if 'python -m unittest discover' in step)
        collect = next(i for i, step in enumerate(steps) if 'python scripts/collect_offers.py' in step)
        self.assertLess(tests, cache)
        self.assertLess(cache, collect)
        self.assertIn('id: public_data_restore', steps[cache])
        self.assertIn("if: always() && steps.public_data_restore.outcome == 'success'", workflow)
        self.assertNotIn('git restore --source=HEAD -- data/offers', workflow)
        self.assertEqual(workflow.count("cron: '8,23,38,53 * * * *'"), 1)

    def test_article_gate_covers_scheduled_and_push_releases(self):
        workflow = (ROOT / '.github/workflows/pages.yml').read_text()
        preflight, publish = re.split(r'(?m)^  publish:\n', workflow, maxsplit=1)
        self.assertIn('  article-check:', preflight)
        self.assertIn('python scripts/test_why_overseas_ui.py', preflight)
        self.assertNotIn('python scripts/collect_offers.py', preflight)
        self.assertIn('    needs: article-check', publish)
        article_step = next(step for step in re.split(r'(?m)^      - ', publish)
                            if 'python scripts/test_why_overseas_ui.py' in step)
        self.assertNotIn('if:', article_step)

    def test_all_three_sources_use_existing_pipeline(self):
        config = {row['code']: row for row in json.loads((ROOT/'data/crawl_sources.json').read_text())}
        self.assertEqual(len(config), 35)
        for code in ('gobik', 'oakley', 'decathlon_cn'):
            self.assertEqual(config[code]['parser'], code)
            self.assertTrue(config[code]['urls'])
            baseline = json.loads((ROOT/'data/offers'/f'{code}.json').read_text())
            self.assertEqual(baseline['verification_method'], 'manual_public_selected_variant')
            self.assertTrue(all(row['fetched_at'].startswith('2026-10-16') for row in baseline['offers']))

    def test_public_workflow_does_not_export_private_state_or_evidence(self):
        workflow = (ROOT/'.github/workflows/pages.yml').read_text()
        for forbidden in ['storage/updates.sqlite3', 'storage/policy_raw', 'storage/policy_history',
                          'data/raw', 'manual_evidence', 'data/collection_status', 'actions/upload-artifact@']:
            self.assertNotIn(forbidden, workflow)
        self.assertIn('restore-keys: bikehunt-public-data-v2-', workflow)
        self.assertIn('python scripts/seed_updates.py', workflow)
        self.assertIn('uses: actions/upload-pages-artifact@', workflow)


if __name__ == '__main__':
    unittest.main()
