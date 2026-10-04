import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from crawler import (Crawler, FetchError, MAX_BODY_BYTES, Response, SafeHTTP,
                     build_batch, extract_metadata, load_manifest,
                     public_addresses, send_batch, sign_payload, validate_url)

CHECKED = "2026-10-04T12:00:00+00:00"
ENTRY = {"slug": "example", "url": "https://example.com/",
         "source_url": "https://example.com/product", "allowed_hosts": ["example.com"]}


def response(url, status=200, body="", content_type="text/html", **headers):
    return Response(status, {"content-type": content_type, **headers}, body.encode(), url)


class FakeHTTP:
    delay = 2

    def __init__(self, pages):
        self.pages = pages
        self.calls = []
        self.host_delays = {}

    def request(self, url, allowed_hosts=None, **kwargs):
        validate_url(url, allowed_hosts)
        self.calls.append((url, kwargs))
        value = self.pages[url]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class CrawlerTests(unittest.TestCase):
    def test_robots_denial_prevents_target_request(self):
        http = FakeHTTP({"https://example.com/robots.txt": response(
            "https://example.com/robots.txt", body="User-agent: *\nDisallow: /product", content_type="text/plain")})
        result = Crawler(http).check(ENTRY, CHECKED)
        self.assertFalse(result["reachable"])
        self.assertEqual(result["source_metadata"]["reason"], "robots_denied")
        self.assertEqual(len(http.calls), 1)

    def test_unavailable_robots_fails_closed(self):
        http = FakeHTTP({"https://example.com/robots.txt": response("x", 503)})
        result = Crawler(http).check(ENTRY, CHECKED)
        self.assertEqual(result["source_metadata"]["reason"], "robots_unavailable")
        self.assertEqual(len(http.calls), 1)

    def test_html_robots_challenge_is_not_treated_as_permission(self):
        http = FakeHTTP({"https://example.com/robots.txt": response("x", body="<html>Challenge</html>")})
        result = Crawler(http).check(ENTRY, CHECKED)
        self.assertEqual(result["source_metadata"]["reason"], "robots_invalid_response")
        self.assertEqual(len(http.calls), 1)

    def test_metadata_and_robots_delay_are_respected(self):
        http = FakeHTTP({
            "https://example.com/robots.txt": response("x", body="User-agent: *\nCrawl-delay: 8", content_type="text/plain"),
            "https://example.com/product": response("x", body='<title> Test &amp; Learn </title><meta name="description" content="Short description">')})
        result = Crawler(http).check(ENTRY, CHECKED)
        self.assertTrue(result["reachable"])
        self.assertEqual(result["source_metadata"]["title"], "Test & Learn")
        self.assertEqual(http.host_delays["example.com"], 8)

    def test_redirect_cannot_escape_host_allowlist(self):
        http = FakeHTTP({
            "https://example.com/robots.txt": response("x", 404),
            "https://example.com/product": response("x", 302, location="https://evil.example/private")})
        result = Crawler(http).check(ENTRY, CHECKED)
        self.assertEqual(result["source_metadata"]["reason"], "host_not_allowlisted")
        self.assertEqual(len(http.calls), 2)

    def test_redirect_destination_robots_are_checked(self):
        entry = {**ENTRY, "allowed_hosts": ["example.com", "other.example"]}
        http = FakeHTTP({
            "https://example.com/robots.txt": response("x", 404),
            "https://example.com/product": response("x", 302, location="https://other.example/product"),
            "https://other.example/robots.txt": response("x", body="User-agent: *\nDisallow: /", content_type="text/plain")})
        result = Crawler(http).check(entry, CHECKED)
        self.assertEqual(result["source_metadata"]["reason"], "robots_denied")
        self.assertEqual(len(http.calls), 3)

    def test_redirect_loop_is_bounded(self):
        http = FakeHTTP({
            "https://example.com/robots.txt": response("x", 404),
            "https://example.com/product": response("x", 302, location="/product")})
        result = Crawler(http).check(ENTRY, CHECKED)
        self.assertEqual(result["source_metadata"]["reason"], "redirect_limit")
        self.assertEqual(len(http.calls), 5)

    def test_extraction_limits_and_open_graph_fallback(self):
        metadata = extract_metadata('<title>' + 'a' * 1000 + '</title><meta property="og:description" content="' + 'b' * 2000 + '">')
        self.assertEqual(len(metadata["title"]), 300)
        self.assertEqual(len(metadata["meta_description"]), 1000)


class SecurityTests(unittest.TestCase):
    def test_url_credentials_ports_non_https_and_host_suffix_are_rejected(self):
        for url in ["http://example.com", "https://u:p@example.com", "https://example.com:8443",
                    "https://example.com.evil.test", "https://example.com./", "https://example.com/\nheader"]:
            with self.subTest(url=url), self.assertRaises(FetchError):
                validate_url(url, {"example.com"})

    def test_private_and_mixed_dns_are_rejected_before_connect(self):
        for addresses in [["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"],
                          ["::1"], ["8.8.8.8", "192.168.1.1"]]:
            answers = [(socket_family, 1, 6, "", (ip, 443))
                       for ip in addresses for socket_family in [2]]
            with self.subTest(addresses=addresses), patch("crawler.socket.getaddrinfo", return_value=answers):
                with self.assertRaises(FetchError):
                    public_addresses("example.com")

    def test_response_bytes_are_bounded_even_without_content_length(self):
        class RawResponse:
            status = 200
            def getheaders(self):
                return [("Content-Type", "text/html")]
            def read(self, limit):
                self.requested_limit = limit
                return b"x" * (MAX_BODY_BYTES + 1)
        class Connection:
            def __init__(self, *args): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return RawResponse()
            def close(self): pass
        with patch("crawler.public_addresses", return_value=["8.8.8.8"]), patch("crawler.PinnedHTTPSConnection", Connection):
            with self.assertRaisesRegex(FetchError, "response_too_large"):
                SafeHTTP(delay=0).request("https://example.com")

    def test_exact_raw_body_signature_changes_on_tampering(self):
        actual = sign_payload("a" * 32, "1791115200", b'{"x":1}')
        self.assertEqual(actual, "7a1aa021596be78503d6ac3436e50cb244249fb1409aa1588a217671fb3e5c29")
        self.assertNotEqual(actual, sign_payload("a" * 32, "1791115200", b'{"x":2}'))
        self.assertNotEqual(actual, sign_payload("a" * 32, "1791115201", b'{"x":1}'))

    def test_ingest_redirect_never_forwards_signature(self):
        http = FakeHTTP({"https://site.example/api/ingest/tools": response("x", 302, location="https://evil.example")})
        with self.assertRaisesRegex(FetchError, "ingest_redirect_refused"):
            send_batch({"batch_id": "x", "observations": []}, "https://site.example/api/ingest/tools", "a" * 32, http)
        self.assertEqual(len(http.calls), 1)

    def test_ingest_retry_keeps_identical_body_and_batch_id(self):
        http = FakeHTTP({"https://site.example/api/ingest/tools": [response("x", 503), response("x", 200)]})
        with patch("crawler.time.sleep"):
            send_batch({"batch_id": "x", "observations": []}, "https://site.example/api/ingest/tools", "a" * 32, http)
        self.assertEqual(http.calls[0][1]["body"], http.calls[1][1]["body"])
        self.assertEqual(len(http.calls), 2)


class BatchTests(unittest.TestCase):
    def test_batch_deduplication_and_order_independent_id(self):
        a = {"slug": "a", "source_url": "https://example.com/a", "checked_at": CHECKED}
        b = {"slug": "b", "source_url": "https://example.com/b", "checked_at": CHECKED}
        first = build_batch([b, a, a], CHECKED)
        second = build_batch([a, b], CHECKED)
        self.assertEqual(first, second)
        self.assertEqual(len(first["observations"]), 2)
        changed = build_batch([{**a, "checked_at": "2026-10-05T12:00:00+00:00"}, b], CHECKED)
        self.assertNotEqual(first["batch_id"], changed["batch_id"])

    def test_manifest_deduplicates_and_enforces_max_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps({"version": 1, "sources": [ENTRY, ENTRY]}))
            self.assertEqual(len(load_manifest(path)), 1)
            path.write_text(json.dumps({"version": 1, "sources": [ENTRY] * 41}))
            with self.assertRaises(ValueError):
                load_manifest(path)

    def test_curated_manifest_is_valid_and_has_unique_slugs(self):
        sources = load_manifest(Path(__file__).parent.parent / "manifest.json")
        self.assertEqual(len(sources), 30)
        self.assertEqual(len({item["slug"] for item in sources}), len(sources))


if __name__ == "__main__":
    unittest.main()
