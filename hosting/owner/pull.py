"""Copy the durable owner queue over SSH; never process or mutate it."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import uuid

from deploy import MAX_EXPORT, local_forbidden_roots, destination_path, ssh, write_private


def validate_export(raw):
    if len(raw) > MAX_EXPORT:
        raise ValueError('Owner snapshot exceeds limit')
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {'version', 'requests'} or type(data['version']) is not int or data['version'] != 1 or not isinstance(data['requests'], list) or len(data['requests']) > 1000:
        raise ValueError('Unexpected owner snapshot schema')
    ids = set()
    total = 0
    for entry in data['requests']:
        if not isinstance(entry, dict) or set(entry) != {'id', 'text', 'createdAt', 'status'} or any(not isinstance(value, str) for value in entry.values()):
            raise ValueError('Unexpected owner request schema')
        if str(uuid.UUID(entry['id'])) != entry['id'] or entry['id'] in ids or entry['status'] != 'queued' or not entry['text'].strip():
            raise ValueError('Invalid owner request')
        created = datetime.fromisoformat(entry['createdAt'].replace('Z', '+00:00'))
        if created.tzinfo is None:
            raise ValueError('Request timestamp requires time zone')
        size = len(entry['text'].encode('utf-8'))
        if size > 65536:
            raise ValueError('Owner request exceeds limit')
        total += size
        ids.add(entry['id'])
    if total > 16 * 1024 * 1024:
        raise ValueError('Owner snapshot text exceeds limit')
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path.home() / '.config' / 'bhakti' / 'owner-private' / 'requests.json')
    args = parser.parse_args()
    destination_path(args.output, local_forbidden_roots())
    raw = validate_export(ssh('export'))
    write_private(args.output, raw, local_forbidden_roots())
    print('Private owner queue snapshot saved. No processing was started.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Owner queue export failed; existing snapshot preserved and private details withheld.', file=sys.stderr)
        sys.exit(1)
