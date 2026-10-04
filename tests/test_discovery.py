from copy import deepcopy
import json
import unittest
from unittest.mock import Mock, patch

from crawler import (Crawler, FetchError, HF_SPACES_API, MAX_BODY_BYTES, Response,
                     discover_spaces, hf_space_slug, parse_space_discoveries)
from public_snapshot import sanitize_report

CHECKED = '2026-10-04T03:37:00+00:00'


def encode(records):
    return json.dumps(records).encode()


class SpaceDiscoveryTests(unittest.TestCase):
    def test_only_public_non_disabled_non_gated_spaces_become_candidates(self):
        records = [
            {'id': 'owner/public', 'private': False, 'sdk': 'gradio',
             'cardData': {'short_description': 'Useful public demo'}},
            {'id': 'owner/private', 'private': True},
            {'id': 'owner/disabled', 'disabled': True},
            {'id': 'owner/gated', 'gated': 'auto'},
            {'id': 'owner/paused', 'runtime': {'stage': 'PAUSED'}},
            {'id': 'owner/invalid-flag', 'private': 'false'},
            {'id': 'owner/unknown-visibility'},
        ]
        observations = parse_space_discoveries(encode(records), CHECKED)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]['slug'], 'hf-owner-public')
        self.assertEqual(observations[0]['url'], 'https://huggingface.co/spaces/owner/public')
        self.assertEqual(observations[0]['source_metadata']['meta_description'], 'Useful public demo')
        self.assertNotIn('category', observations[0])
        self.assertNotIn('published', observations[0])

    def test_ids_cannot_introduce_arbitrary_urls_or_paths_and_duplicates_are_removed(self):
        records = [{'id': value, 'private': False, 'url': 'http://127.0.0.1/'} for value in [
            'owner/good', 'owner/good', '../escape', 'owner/../../secret',
            'https://evil.example', 'owner/tool?query=1', 'owner/tool#fragment']]
        results = parse_space_discoveries(encode(records), CHECKED)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['source_url'], 'https://huggingface.co/spaces/owner/good')

    def test_response_size_record_count_and_shape_are_bounded(self):
        for body in [b' ' * (MAX_BODY_BYTES + 1), encode([{'id': 'o/s'}] * 11), encode({'spaces': []}), b'bad json']:
            with self.subTest(length=len(body)), self.assertRaises(FetchError):
                parse_space_discoveries(body, CHECKED)

    def test_slug_is_deterministic_and_at_most_80_characters(self):
        space_id = 'owner_' + 'a' * 50 + '/' + 'b' * 96
        slug = hf_space_slug(space_id)
        self.assertLessEqual(len(slug), 80)
        self.assertTrue(slug.startswith('hf-owner-'))
        self.assertEqual(slug, hf_space_slug(space_id))
        self.assertNotEqual(slug, hf_space_slug(space_id[:-1] + 'c'))

    def test_descriptions_are_short_metadata_and_never_readme_contents(self):
        result = parse_space_discoveries(encode([{
            'id': 'owner/demo', 'private': False, 'readme': 'FULL THIRD PARTY DOCUMENT',
            'cardData': {'short_description': 'x' * 1000}}]), CHECKED)[0]
        self.assertEqual(len(result['source_metadata']['meta_description']), 300)
        self.assertNotIn('FULL THIRD PARTY', json.dumps(result))

    def test_robots_denial_prevents_api_request(self):
        http = Mock()
        with patch.object(Crawler, 'robots_allowed', return_value=False):
            with self.assertRaisesRegex(FetchError, 'discovery_robots_denied'):
                discover_spaces(http, CHECKED)
        http.request.assert_not_called()

    def test_fixed_public_api_request_does_not_follow_redirect(self):
        http = Mock()
        http.request.return_value = Response(302, {'location': 'https://evil.example'}, b'', HF_SPACES_API)
        with patch.object(Crawler, 'robots_allowed', return_value=True):
            with self.assertRaisesRegex(FetchError, 'discovery_http_302'):
                discover_spaces(http, CHECKED)
        http.request.assert_called_once_with(HF_SPACES_API, {'huggingface.co'}, headers={'Accept': 'application/json'})

    def test_snapshot_accepts_only_exact_hf_spaces_paths_and_matching_slug(self):
        candidate = parse_space_discoveries(encode([{'id': 'owner/demo', 'private': False}]), CHECKED)[0]
        report = {'checked_at': CHECKED, 'observations': [candidate]}
        self.assertEqual(len(sanitize_report(report, [])['observations']), 1)
        for field, value in [('source_url', 'https://huggingface.co/models/owner/demo'),
                             ('source_url', 'https://huggingface.co.evil.example/spaces/owner/demo'),
                             ('slug', 'another-tool')]:
            changed = deepcopy(report)
            changed['observations'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises((ValueError, FetchError)):
                sanitize_report(changed, [])
        redirected = deepcopy(report)
        redirected['observations'][0]['source_metadata']['final_url'] = 'https://huggingface.co/api/spaces'
        with self.assertRaisesRegex(ValueError, 'Discovery redirect'):
            sanitize_report(redirected, [])

    def test_snapshot_discovery_limit_is_independent_of_curated_sources(self):
        candidate = parse_space_discoveries(encode([{'id': 'owner/demo', 'private': False}]), CHECKED)[0]
        report = {'checked_at': CHECKED, 'observations': [candidate] * 11}
        with self.assertRaisesRegex(ValueError, 'discovery limit'):
            sanitize_report(report, [])


if __name__ == '__main__':
    unittest.main()
