#!/usr/bin/env python3
"""Bind already edited readers to explicit source-review receipts, with no API calls.

This writes only the private assessment registry. It never publishes repair
receipts or changes model assessments, audio, readers, or completion ledgers.
The caller refreshes the catalogue once after preparing the entire release.
Receipt hashes establish identity, not correctness: a reviewer must actually
check every original feature against the corrected meaning before retaining it.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path

from bhakti_boundary_timebase import boundary_transaction
import bhakti_shuffle_profiles as profiles


def refresh(root, slugs, *, apply=False):
    root = Path(root)
    slugs = list(dict.fromkeys(slugs))
    if not slugs or any(not slug or Path(slug).name != slug for slug in slugs):
        raise ValueError('reviewed text refresh requires existing song slugs')
    snapshots = {}
    def snapshot(path):
        value = path.read_bytes()
        snapshots[path] = value
        return value
    for name in (profiles.POLICY, profiles.TAXONOMY, profiles.REVIEWS,
                 profiles.TEXT_REPAIRS, 'data/song_tag_overrides.json', 'data/media.json'):
        snapshot(root / name)
    policy, reviews, taxonomy = profiles._configuration(root)
    updated = copy.deepcopy(reviews)
    for slug in slugs:
        source = snapshot(root / 'songs' / slug / 'data.js').decode('utf-8')
        reader = profiles.parse_javascript_sources({slug: source})[slug]
        queue_id = hashlib.blake2s(slug.encode(), digest_size=4).hexdigest()
        stored = reviews['profiles'].get(queue_id)
        amendment = profiles.reviewed_editorial_text_revision(root, slug, reader, stored)
        record = copy.deepcopy(stored)
        record['semantic']['editorialTextRevision'] = amendment
        media_hash = profiles.recording_sha256(root, slug, reader)
        public = profiles.project_song_profile(queue_id, slug, reader, taxonomy, media_hash, record,
                                               required=True, qualification=policy, root=root)
        if any(key in json.dumps(public) for key in ('priorLines', 'editorialTextRevision', 'lineEvidence')):
            raise ValueError('private text review evidence leaked into public profile')
        updated['profiles'][queue_id] = record
    with boundary_transaction(root / 'data'):
        for path, expected in snapshots.items():
            if path.read_bytes() != expected:
                raise ValueError(f'text refresh input changed during preparation: {path}')
        if apply and updated != reviews:
            profiles.atomic_text(root / profiles.REVIEWS, json.dumps(updated, ensure_ascii=False, indent=2) + '\n')
            print(profiles.REVIEWS)
        else:
            print(('current' if updated == reviews else 'validated without writing') + ': ' + ', '.join(slugs))
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('slugs', nargs='+')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--apply', action='store_true', help='store validated amendments; otherwise check only')
    args = parser.parse_args()
    refresh(args.root, args.slugs, apply=args.apply)


if __name__ == '__main__':
    main()
