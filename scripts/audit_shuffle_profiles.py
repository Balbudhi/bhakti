#!/usr/bin/env python3
"""Require exact reader/media/profile publication pairing; no assessment calls."""
import argparse
import json
from pathlib import Path
import bhakti_shuffle_profiles as profiles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        document = profiles.validate_public_profiles(args.root)
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'blocked', 'error': str(exc)})); return 1
    counts = {kind: sum(row[kind]['status'] == 'accepted' for row in document['profiles'].values())
              for kind in ('semantic', 'audio')}
    print(json.dumps({'status': 'accepted', 'songs': len(document['profiles']), 'features': counts,
                      'revision': document['revision']}))
    return 0


if __name__ == '__main__': raise SystemExit(main())
