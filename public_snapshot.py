#!/usr/bin/env python3
"""Persist only allowlisted public-source observations; discard unknown fields."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re

from crawler import (MAX_DISCOVERIES, build_batch, clean_text, hf_space_id_from_url,
                     hf_space_slug, load_manifest, validate_url)


def sanitize_report(report: dict, sources: list[dict]) -> dict:
    known = {(item['slug'], item['source_url']): item for item in sources}
    observations = []
    discovered_count = 0
    checked_at = report['checked_at']
    if datetime.fromisoformat(checked_at).tzinfo is None:
        raise ValueError('Report timestamp must include its timezone')
    for item in report['observations']:
        source_url = validate_url(item['source_url'])
        entry = known.get((item['slug'], source_url))
        is_discovery = not entry
        if not entry:
            space_id = hf_space_id_from_url(source_url)
            if (item['slug'] != hf_space_slug(space_id)
                    or item['source_metadata'].get('reason') != 'discovered_from_huggingface_api'):
                raise ValueError('Report contains an unapproved discovery source')
            entry = {'slug': item['slug'], 'url': source_url,
                     'source_url': source_url, 'allowed_hosts': ['huggingface.co']}
            discovered_count += 1
            if discovered_count > MAX_DISCOVERIES:
                raise ValueError('Report exceeds the discovery limit')
        if validate_url(item['url']) != entry['url']:
            raise ValueError('Report contains a source outside the curated manifest')
        if datetime.fromisoformat(item['checked_at']).tzinfo is None:
            raise ValueError('Observation timestamp must include its timezone')
        if not isinstance(item['reachable'], bool):
            raise ValueError('Invalid reachability value')
        metadata = {}
        raw = item['source_metadata']
        for key, limit in [('title', 300), ('meta_description', 1000)]:
            if key in raw:
                metadata[key] = clean_text(str(raw[key]), limit)
        if 'status' in raw:
            status = raw['status']
            if type(status) is not int or not 100 <= status <= 599:
                raise ValueError('Invalid source HTTP status')
            metadata['status'] = status
        if 'final_url' in raw:
            metadata['final_url'] = validate_url(raw['final_url'], set(entry['allowed_hosts']))
            if is_discovery and metadata['final_url'] != source_url:
                raise ValueError('Discovery redirect is outside its approved Space page')
        if 'reason' in raw:
            if not re.fullmatch(r'[a-z0-9_]{1,100}', raw['reason']):
                raise ValueError('Unexpected non-public diagnostic value')
            metadata['reason'] = raw['reason']
        observations.append({'slug': entry['slug'], 'url': entry['url'],
                             'source_url': source_url, 'reachable': item['reachable'],
                             'checked_at': item['checked_at'], 'source_metadata': metadata})
    if len(observations) > len(sources) + discovered_count:
        raise ValueError('Report exceeds the curated source count')
    return build_batch(observations, checked_at)


def save_snapshot(report: dict, sources: list[dict], destination: Path) -> bool:
    content = (json.dumps(sanitize_report(report, sources), ensure_ascii=False,
                          sort_keys=True, indent=2) + '\n').encode('utf-8')
    if destination.exists() and destination.read_bytes() == content:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=Path('out/observations.json'))
    parser.add_argument('--manifest', type=Path, default=Path('manifest.json'))
    parser.add_argument('--output', type=Path, default=Path('data/latest.json'))
    args = parser.parse_args()
    changed = save_snapshot(json.loads(args.report.read_text(encoding='utf-8')),
                            load_manifest(args.manifest), args.output)
    print('Public snapshot updated' if changed else 'Public snapshot unchanged')


if __name__ == '__main__':
    main()
