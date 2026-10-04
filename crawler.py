#!/usr/bin/env python3
"""Bounded, robots-aware official-source metadata checks using only Python stdlib."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import hmac
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import sys
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

USER_AGENT = "ZekaAtlasBot/1.0"
MAX_SOURCES = 40
MAX_BODY_BYTES = 1_048_576
MAX_REDIRECTS = 3
MAX_DISCOVERIES = 10
HF_SPACES_API = "https://huggingface.co/api/spaces?sort=trendingScore&direction=-1&limit=10"
HF_SPACE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class FetchError(Exception):
    pass


def validate_url(url: str, allowed_hosts: set[str] | None = None) -> str:
    """HTTPS, exact hosts, no credentials or alternate ports; strip fragments."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if (parts.scheme != "https" or not host or parts.username or parts.password
                or parts.port not in (None, 443) or not host.isascii()
                or host.endswith(".") or "\\" in url or any(ord(c) < 32 for c in url)):
            raise ValueError
        if allowed_hosts is not None and host not in allowed_hosts:
            raise FetchError("host_not_allowlisted")
        return urlunsplit(("https", host, parts.path or "/", parts.query, ""))
    except (ValueError, TypeError):
        raise FetchError("invalid_https_url") from None


def public_addresses(host: str) -> list[str]:
    """Reject every mixed/private DNS answer and pin the connection to checked IPs."""
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(
            host, 443, type=socket.SOCK_STREAM)})
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise FetchError("non_public_address")
        return addresses
    except (OSError, ValueError):
        raise FetchError("dns_lookup_failed") from None


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, timeout: int):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str


class SafeHTTP:
    def __init__(self, delay: float = 2, timeout: int = 15):
        self.delay = delay
        self.timeout = timeout
        self.last_request: dict[str, float] = {}
        self.host_delays: dict[str, float] = {}

    def request(self, url: str, allowed_hosts: set[str] | None = None, *,
                method: str = "GET", body: bytes | None = None,
                headers: dict[str, str] | None = None) -> Response:
        url = validate_url(url, allowed_hosts)
        parts = urlsplit(url)
        host = parts.hostname
        addresses = public_addresses(host)
        pause = self.host_delays.get(host, self.delay) - (
            time.monotonic() - self.last_request.get(host, 0))
        if pause > 0:
            time.sleep(pause)
        request_headers = {"User-Agent": USER_AGENT,
                           "Accept": "text/html,text/plain;q=0.9",
                           "Accept-Encoding": "identity"}
        request_headers.update(headers or {})
        connection = PinnedHTTPSConnection(host, addresses[0], self.timeout)
        try:
            self.last_request[host] = time.monotonic()
            path = parts.path + ("?" + parts.query if parts.query else "")
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            response_headers = {k.lower(): v for k, v in response.getheaders()}
            length = response_headers.get("content-length")
            if length and int(length) > MAX_BODY_BYTES:
                raise FetchError("response_too_large")
            response_body = response.read(MAX_BODY_BYTES + 1)
            if len(response_body) > MAX_BODY_BYTES:
                raise FetchError("response_too_large")
            if response_headers.get("content-encoding", "identity") != "identity":
                raise FetchError("compressed_response_not_supported")
            return Response(response.status, response_headers, response_body, url)
        except (OSError, http.client.HTTPException, ValueError):
            raise FetchError("network_or_protocol_error") from None
        finally:
            connection.close()


def decode(response: Response) -> str:
    match = re.search(r"charset=[\"']?([\w-]+)", response.headers.get("content-type", ""))
    charset = match.group(1) if match else "utf-8"
    try:
        return response.body.decode(charset, errors="replace")
    except LookupError:
        return response.body.decode("utf-8", errors="replace")


def clean_text(value: str, length: int) -> str:
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", value).split())[:length]


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.title: list[str] = []
        self.description = ""
        self.og_description = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() == "meta":
            attributes = {k.lower(): v or "" for k, v in attrs}
            name = attributes.get("name", "").lower()
            prop = attributes.get("property", "").lower()
            if name == "description" and not self.description:
                self.description = attributes.get("content", "")
            if prop == "og:description" and not self.og_description:
                self.og_description = attributes.get("content", "")

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)


def extract_metadata(html: str) -> dict[str, str]:
    parser = MetadataParser()
    parser.feed(html)
    return {"title": clean_text("".join(parser.title), 300),
            "meta_description": clean_text(parser.description or parser.og_description, 1000)}


class Crawler:
    def __init__(self, http: SafeHTTP):
        self.http = http
        self.robots: dict[tuple, RobotFileParser] = {}

    def robots_allowed(self, url: str, hosts: set[str]) -> bool:
        parts = urlsplit(validate_url(url, hosts))
        origin = "https://" + parts.hostname
        cache_key = (origin, tuple(sorted(hosts)))
        if cache_key not in self.robots:
            current = origin + "/robots.txt"
            for attempt in range(MAX_REDIRECTS + 1):
                response = self.http.request(current, hosts)
                if response.status not in REDIRECT_STATUSES:
                    break
                if attempt == MAX_REDIRECTS or not response.headers.get("location"):
                    raise FetchError("robots_redirect_limit")
                current = validate_url(urljoin(current, response.headers["location"]), hosts)
            parser = RobotFileParser()
            if response.status == 404:
                parser.parse([])
            elif response.status == 200:
                content_type = response.headers.get("content-type", "text/plain").lower()
                if "html" in content_type:
                    raise FetchError("robots_invalid_response")
                parser.parse(decode(response).splitlines())
            else:
                raise FetchError("robots_unavailable")
            delay = parser.crawl_delay(USER_AGENT) or self.http.delay
            rate = parser.request_rate(USER_AGENT)
            if rate:
                delay = max(delay, rate.seconds / rate.requests)
            if delay > 120:
                raise FetchError("robots_delay_exceeds_run_budget")
            self.http.host_delays[parts.hostname] = max(self.http.delay, delay)
            self.robots[cache_key] = parser
        return self.robots[cache_key].can_fetch(USER_AGENT, url)

    def check(self, entry: dict, checked_at: str) -> dict:
        observation = {"slug": entry["slug"], "url": entry["url"],
                       "source_url": entry["source_url"], "checked_at": checked_at,
                       "reachable": False, "source_metadata": {}}
        hosts = set(entry["allowed_hosts"])
        current = entry["source_url"]
        metadata = observation["source_metadata"]
        try:
            for attempt in range(MAX_REDIRECTS + 1):
                current = validate_url(current, hosts)
                if not self.robots_allowed(current, hosts):
                    raise FetchError("robots_denied")
                response = self.http.request(current, hosts)
                metadata.update(status=response.status, final_url=current)
                if response.status not in REDIRECT_STATUSES:
                    break
                if attempt == MAX_REDIRECTS or not response.headers.get("location"):
                    raise FetchError("redirect_limit")
                current = validate_url(urljoin(current, response.headers["location"]), hosts)
            if response.status != 200:
                raise FetchError("http_" + str(response.status))
            if "text/html" not in response.headers.get("content-type", "").lower():
                raise FetchError("not_public_html")
            metadata.update(extract_metadata(decode(response)))
            observation["reachable"] = True
        except FetchError as error:
            metadata["reason"] = clean_text(str(error), 500)
        return observation


def load_manifest(path: Path, limit: int = MAX_SOURCES) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    sources = document["sources"]
    if document.get("version") != 1 or not 1 <= limit <= MAX_SOURCES or len(sources) > MAX_SOURCES:
        raise ValueError("Manifest must have version 1 and at most 40 sources")
    unique = {}
    for entry in sources:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", entry["slug"]):
            raise ValueError("Invalid tool slug")
        hosts = {host.lower() for host in entry["allowed_hosts"]}
        if not hosts or len(hosts) > 5:
            raise ValueError("Use 1–5 explicit source hosts")
        entry["source_url"] = validate_url(entry["source_url"], hosts)
        entry["url"] = validate_url(entry["url"])
        entry["allowed_hosts"] = sorted(hosts)
        key = (entry["slug"], entry["source_url"])
        if key in unique and unique[key] != entry:
            raise ValueError("Conflicting duplicate source")
        unique[key] = entry
    return sorted(unique.values(), key=lambda entry: (entry["slug"], entry["source_url"]))[:limit]



def hf_space_slug(space_id: str) -> str:
    if not HF_SPACE_ID.fullmatch(space_id):
        raise FetchError("invalid_space_id")
    normalized = re.sub(r"[^a-z0-9]+", "-", space_id.lower()).strip("-")
    slug = "hf-" + normalized
    return slug if len(slug) <= 80 else slug[:71].rstrip("-") + "-" + sha256(space_id.encode()).hexdigest()[:8]


def hf_space_id_from_url(url: str) -> str:
    url = validate_url(url, {"huggingface.co"})
    parts = urlsplit(url)
    space_id = parts.path.removeprefix("/spaces/")
    if not parts.path.startswith("/spaces/") or parts.query or not HF_SPACE_ID.fullmatch(space_id):
        raise FetchError("invalid_space_url")
    return space_id


def parse_space_discoveries(body: bytes, checked_at: str) -> list[dict]:
    if len(body) > MAX_BODY_BYTES:
        raise FetchError("discovery_response_too_large")
    try:
        records = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise FetchError("discovery_invalid_json") from None
    if not isinstance(records, list) or len(records) > MAX_DISCOVERIES:
        raise FetchError("discovery_record_limit")
    observations = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        space_id = record.get("id")
        if not isinstance(space_id, str) or not HF_SPACE_ID.fullmatch(space_id) or space_id in seen:
            continue
        if record.get("private") is not False or any(
                record.get(key, False) is not False for key in ("disabled", "gated")):
            continue
        runtime = record.get("runtime", {})
        if isinstance(runtime, dict) and runtime.get("stage") in {
                "PAUSED", "STOPPED", "RUNTIME_ERROR", "BUILD_ERROR", "DELETED", "NO_APP_FILE"}:
            continue
        seen.add(space_id)
        url = "https://huggingface.co/spaces/" + space_id
        card = record.get("cardData", {})
        description = card.get("short_description", "") if isinstance(card, dict) else ""
        if not isinstance(description, str):
            description = ""
        if not description:
            sdk = record.get("sdk")
            label = sdk if sdk in {"gradio", "streamlit", "docker", "static"} else "yapay zeka"
            description = f"Hugging Face üzerinde sunulan herkese açık bir {label} demosu. Yayına alınmadan önce editör incelemesi gerekir."
        observations.append({"slug": hf_space_slug(space_id), "url": url,
                             "source_url": url, "reachable": True, "checked_at": checked_at,
                             "source_metadata": {"title": "Hugging Face: " + space_id,
                                                 "meta_description": clean_text(description, 300),
                                                 "status": 200,
                                                 "reason": "discovered_from_huggingface_api"}})
    return observations


def discover_spaces(http: SafeHTTP, checked_at: str) -> list[dict]:
    hosts = {"huggingface.co"}
    if not Crawler(http).robots_allowed(HF_SPACES_API, hosts):
        raise FetchError("discovery_robots_denied")
    response = http.request(HF_SPACES_API, hosts, headers={"Accept": "application/json"})
    if response.status != 200:
        raise FetchError("discovery_http_" + str(response.status))
    if "application/json" not in response.headers.get("content-type", "").lower():
        raise FetchError("discovery_not_json")
    return parse_space_discoveries(response.body, checked_at)


def canonical_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_batch(observations: list[dict], checked_at: str) -> dict:
    unique = {(item["slug"], item["source_url"]): item for item in observations}
    ordered = sorted(unique.values(), key=lambda item: (item["slug"], item["source_url"]))
    return {"batch_id": sha256(canonical_bytes(ordered)).hexdigest(),
            "checked_at": checked_at, "observations": ordered}


def sign_payload(secret: str, timestamp: str, raw_body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + raw_body,
                    sha256).hexdigest()


def send_batch(batch: dict, endpoint: str, secret: str, http: SafeHTTP) -> None:
    endpoint = validate_url(endpoint)
    if len(secret) < 32:
        raise ValueError("INGEST_SECRET must contain at least 32 characters")
    raw_body = canonical_bytes(batch)
    for attempt in range(3):
        timestamp = str(int(time.time()))
        response = http.request(endpoint, method="POST", body=raw_body, headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "X-Ingest-Timestamp": timestamp,
            "X-Ingest-Signature": sign_payload(secret, timestamp, raw_body)})
        if 200 <= response.status < 300:
            return
        if response.status in REDIRECT_STATUSES:
            raise FetchError("ingest_redirect_refused")
        if response.status not in (429, 500, 502, 503, 504) or attempt == 2:
            raise FetchError("ingest_http_" + str(response.status))
        time.sleep(2 ** (attempt + 1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("out/observations.json"))
    parser.add_argument("--limit", type=int, default=MAX_SOURCES)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--no-discovery", action="store_true", help="Check only curated sources")
    args = parser.parse_args()
    try:
        sources = load_manifest(args.manifest, args.limit)
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        http = SafeHTTP()
        crawler = Crawler(http)
        observations = [crawler.check(source, checked_at) for source in sources]
        discoveries = []
        if not args.no_discovery:
            try:
                discoveries = discover_spaces(http, checked_at)
                observations.extend(discoveries)
            except FetchError as error:
                print(f"Discovery skipped: {clean_text(str(error), 100)}")
        batch = build_batch(observations, checked_at)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_bytes(batch) + b"\n")
        reached = sum(item["reachable"] for item in observations
                      if item["source_metadata"].get("reason") != "discovered_from_huggingface_api")
        print(f"Checked {len(sources)} curated sources; {reached} public HTML responses; "
              f"{len(discoveries)} public Spaces discovered for moderation; batch {batch['batch_id']}")
        if args.send:
            endpoint = os.environ.get("INGEST_ENDPOINT", "")
            secret = os.environ.get("INGEST_SECRET", "")
            if not endpoint or not secret:
                raise ValueError("Set INGEST_ENDPOINT and INGEST_SECRET before --send")
            send_batch(batch, endpoint, secret, http)
            print("Signed batch accepted by site")
        return 0
    except (FetchError, ValueError, KeyError, OSError) as error:
        print(f"Crawler failed: {clean_text(str(error), 500)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
