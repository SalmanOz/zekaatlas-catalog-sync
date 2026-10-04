from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from crawler import FetchError
from public_snapshot import sanitize_report, save_snapshot

SOURCE = {'slug': 'example', 'url': 'https://example.com/',
          'source_url': 'https://example.com/product', 'allowed_hosts': ['example.com']}
REPORT = {'batch_id': 'ignored', 'checked_at': '2026-10-04T03:37:00+00:00',
          'observations': [{**{k: v for k, v in SOURCE.items() if k != 'allowed_hosts'},
                            'checked_at': '2026-10-04T03:37:00+00:00', 'reachable': True,
                            'source_metadata': {'title': 'Official title', 'status': 200,
                                                'final_url': 'https://example.com/product'}}]}


class PublicSnapshotTests(unittest.TestCase):
    def test_only_public_contract_fields_are_saved(self):
        report = deepcopy(REPORT)
        report['INGEST_SECRET'] = 'must-never-be-committed'
        report['INGEST_ENDPOINT'] = 'https://private-site.example/api'
        report['observations'][0]['internal'] = 'private'
        report['observations'][0]['source_metadata']['authorization'] = 'secret'
        output = json.dumps(sanitize_report(report, [SOURCE]))
        self.assertNotIn('must-never', output)
        self.assertNotIn('private-site', output)
        self.assertNotIn('internal', output)
        self.assertNotIn('authorization', output)

    def test_identical_report_does_not_rewrite_file(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'data/latest.json'
            self.assertTrue(save_snapshot(REPORT, [SOURCE], output))
            before = output.stat().st_mtime_ns
            self.assertFalse(save_snapshot(REPORT, [SOURCE], output))
            self.assertEqual(output.stat().st_mtime_ns, before)
            report = deepcopy(REPORT)
            report['checked_at'] = '2026-10-05T03:37:00+00:00'
            report['observations'][0]['checked_at'] = report['checked_at']
            self.assertTrue(save_snapshot(report, [SOURCE], output))

    def test_unapproved_url_or_redirect_is_rejected(self):
        for key in ['url', 'source_url', 'final_url']:
            report = deepcopy(REPORT)
            target = report['observations'][0]['source_metadata'] if key == 'final_url' else report['observations'][0]
            target[key] = 'https://unapproved.example/'
            with self.subTest(key=key), self.assertRaises((ValueError, FetchError)):
                sanitize_report(report, [SOURCE])

    def test_diagnostics_cannot_contain_raw_requests_or_secrets(self):
        report = deepcopy(REPORT)
        report['observations'][0]['source_metadata']['reason'] = 'Authorization: secret'
        with self.assertRaises(ValueError):
            sanitize_report(report, [SOURCE])

    def test_timezones_and_status_are_checked(self):
        for field, value in [('checked_at', '2026-10-04T03:37:00'), ('status', 999)]:
            report = deepcopy(REPORT)
            target = report if field == 'checked_at' else report['observations'][0]['source_metadata']
            target[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                sanitize_report(report, [SOURCE])


if __name__ == '__main__':
    unittest.main()
