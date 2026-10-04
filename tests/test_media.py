import unittest
from unittest.mock import Mock, patch
from crawler import Crawler, FetchError, Response, extract_metadata
from public_snapshot import sanitize_report

CHECKED = '2026-10-04T03:37:00+00:00'


class MediaMetadataTests(unittest.TestCase):
    def test_cdn_unavailable_robots_status_is_distinct_from_disallow_and_server_failure(self):
        for status in [400, 403, 410]:
            http = Mock(delay=2)
            http.host_delays = {}
            http.request.return_value = Response(status, {}, b'', '')
            self.assertTrue(Crawler(http).robots_allowed('https://cdn.example/p.png', {'cdn.example'}, static_media=True))
            with self.assertRaises(FetchError):
                Crawler(http).robots_allowed('https://cdn.example/p.png', {'cdn.example'})
        for status in [401, 429, 503]:
            http = Mock(delay=2)
            http.host_delays = {}
            http.request.return_value = Response(status, {}, b'', '')
            with self.assertRaises(FetchError):
                Crawler(http).robots_allowed('https://cdn.example/p.png', {'cdn.example'}, static_media=True)
        http = Mock(delay=2)
        http.host_delays = {}
        http.request.return_value = Response(200, {'content-type': 'text/plain'}, b'User-agent: *\nDisallow: /', '')
        self.assertFalse(Crawler(http).robots_allowed('https://cdn.example/p.png', {'cdn.example'}, static_media=True))
        for headers, body in [({'content-type': 'text/html'}, b'challenge'),
                              ({}, b'<!DOCTYPE html><html>challenge</html>')]:
            http.request.return_value = Response(403, headers, body, '')
            with self.assertRaises(FetchError):
                Crawler(http).robots_allowed('https://cdn.example/p.png', {'cdn.example'}, static_media=True)

    def test_relative_icons_and_approved_cdn_previews_resolve(self):
        html = '<link rel="apple-touch-icon" href="/logo.png"><meta property="og:image" content="https://cdn.example/preview.webp">'
        result = extract_metadata(html, 'https://tool.example/product', {'tool.example', 'cdn.example'})
        self.assertEqual(result['media'], {'logo_url': 'https://tool.example/logo.png',
                                         'preview_image_url': 'https://cdn.example/preview.webp'})

    def test_unapproved_private_data_and_credential_urls_are_omitted(self):
        for url in ['http://127.0.0.1/logo.png', 'data:image/png;base64,a',
                    'https://cdn.example.evil.test/p.png', 'https://user:pass@cdn.example/p.png']:
            with self.subTest(url=url):
                result = extract_metadata(f'<meta property="og:image" content="{url}">',
                                          'https://tool.example/', {'tool.example', 'cdn.example'})
                self.assertNotIn('media', result)

    def test_only_head_and_image_content_type_are_accepted(self):
        http = Mock()
        http.request.return_value = Response(200, {'content-type': 'text/html'}, b'', 'https://cdn.example/p.png')
        crawler = Crawler(http)
        with patch.object(crawler, 'robots_allowed', return_value=True):
            self.assertIsNone(crawler.check_media('https://cdn.example/p.png', {'cdn.example'}))
        http.request.assert_called_once_with('https://cdn.example/p.png', {'cdn.example'},
                                             method='HEAD', headers={'Accept': 'image/*'})

    def test_robots_denied_and_private_dns_never_expose_media(self):
        http = Mock()
        crawler = Crawler(http)
        with patch.object(crawler, 'robots_allowed', return_value=False):
            self.assertIsNone(crawler.check_media('https://cdn.example/p.png', {'cdn.example'}))
        http.request.assert_not_called()
        http.request.side_effect = FetchError('non_public_address')
        with patch.object(crawler, 'robots_allowed', return_value=True):
            self.assertIsNone(crawler.check_media('https://cdn.example/p.png', {'cdn.example'}))

    def test_redirect_stays_allowlisted_and_rechecks_robots(self):
        http = Mock()
        http.request.return_value = Response(302, {'location': 'https://evil.test/p.png'}, b'', '')
        crawler = Crawler(http)
        with patch.object(crawler, 'robots_allowed', return_value=True):
            self.assertIsNone(crawler.check_media('https://cdn.example/p.png', {'cdn.example'}))
        self.assertEqual(http.request.call_count, 1)
        http.request.side_effect = [Response(302, {'location': '/new.webp'}, b'', ''),
                                    Response(200, {'content-type': 'image/webp'}, b'', '')]
        with patch.object(crawler, 'robots_allowed', side_effect=[True, False]) as robots:
            self.assertIsNone(crawler.check_media('https://cdn.example/p.png', {'cdn.example'}))
        self.assertEqual(robots.call_args_list[-1].args[0], 'https://cdn.example/new.webp')

    def test_snapshot_keeps_only_approved_public_media_contract(self):
        entry = {'slug': 'tool', 'url': 'https://tool.example/', 'source_url': 'https://tool.example/',
                 'allowed_hosts': ['tool.example'], 'media_hosts': ['cdn.example']}
        observation = dict(slug='tool', url=entry['url'], source_url=entry['url'], checked_at=CHECKED,
                           reachable=True, source_metadata={'media': {'logo_url': 'https://cdn.example/logo.png',
                                                                     'secret': 'never-keep'}})
        report = {'checked_at': CHECKED, 'observations': [observation]}
        result = sanitize_report(report, [entry])
        self.assertEqual(result['observations'][0]['source_metadata']['media'],
                         {'logo_url': 'https://cdn.example/logo.png'})
        observation['source_metadata']['media']['logo_url'] = 'https://evil.test/logo.png'
        with self.assertRaises(FetchError):
            sanitize_report(report, [entry])


if __name__ == '__main__':
    unittest.main()
