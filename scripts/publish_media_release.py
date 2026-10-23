#!/usr/bin/env python3
"""Upload listener audio to one GitHub Release and write its public URL map.

GitHub Pages has a 1 GiB published-site limit, so high-quality audio belongs in
release assets rather than the Pages artifact or Git history. New or changed audio uses content-addressed immutable asset names. Unchanged
legacy assets retain their existing URLs, so older live readers never start
playing a different recording while new pages are being deployed.
"""

from __future__ import annotations

from contextlib import ExitStack
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import quote, unquote

from bhakti_model_routes import atomic_json

from bhakti_boundary_timebase import (boundary_transaction, boundary_snapshot,
    require_boundary_snapshot, require_completed_boundary_transaction)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "media.json"
PREFERRED = (".webm", ".ogg", ".flac", ".wav", ".mp3", ".m4a")
MIME_TYPES = {
    ".webm": "audio/webm; codecs=opus",
    ".ogg": "audio/ogg; codecs=opus",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}


def command(*parts: str, capture: bool = False) -> str:
    result = subprocess.run(parts, cwd=ROOT, check=True, text=True,
                            capture_output=capture)
    return result.stdout.strip() if capture else ""


def repository_name() -> str:
    return command("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner", capture=True)


def release_assets(repository: str, tag: str) -> dict[str, int]:
    try:
        payload = command("gh", "api", f"repos/{repository}/releases/tags/{tag}", capture=True)
    except subprocess.CalledProcessError:
        command("gh", "release", "create", tag, "--repo", repository, "--target", "main",
                "--title", "Bhakti listener audio", "--notes",
                "High-quality listener audio for bhakti.eeshan.xyz. Reader code is deployed separately through GitHub Pages.")
        payload = command("gh", "api", f"repos/{repository}/releases/tags/{tag}", capture=True)
    release = json.loads(payload)
    return {str(asset["name"]): int(asset["size"]) for asset in release.get("assets", [])}


def local_audio(selected_slugs: set[str] | None = None) -> dict[str, list[tuple[Path, str, str]]]:
    songs: dict[str, list[tuple[Path, str, str]]] = {}
    for directory in sorted((ROOT / "songs").iterdir()):
        if not directory.is_dir():
            continue
        if selected_slugs is not None and directory.name not in selected_slugs:
            continue
        sources = []
        for suffix in PREFERRED:
            path = directory / f"audio{suffix}"
            if path.is_file():
                sources.append((path, f"{directory.name}{suffix}", MIME_TYPES[suffix]))
        if sources:
            songs[directory.name] = sources
    return songs


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def needs_upload(remote_size: int | None, local_size: int,
                 previous_hash: str | None, local_hash: str) -> bool:
    return remote_size != local_size or (previous_hash is not None and previous_hash != local_hash)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="media-v1")
    parser.add_argument("--repository", default="")
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--song", action="append", default=[], metavar="SLUG",
                        help="Publish only this song's listener audio; repeat for a small release batch.")
    args = parser.parse_args()

    selected = set(args.song) if args.song else None
    directories = sorted((directory.resolve() for directory in (ROOT / 'songs').iterdir()
        if directory.is_dir() and (selected is None or directory.name in selected)))
    for directory in directories:
        require_completed_boundary_transaction(directory)
    with ExitStack() as locks:
        # The shared manifest has one writer at a time, then song locks always
        # follow resolved-path order. Boundary installers only take a song lock.
        locks.enter_context(boundary_transaction(MANIFEST))
        for directory in directories:
            locks.enter_context(boundary_transaction(directory))
        return publish_locked(args, selected, directories)


def publish_locked(args, selected, directories) -> int:
    local = local_audio(selected)
    if selected:
        missing = sorted(selected - set(local))
        if missing:
            raise SystemExit(f"selected songs lack listener audio: {', '.join(missing)}")
    snapshots = {directory: boundary_snapshot(directory,
        [directory / name for name in ('data.js', 'index.html')]
        + [path for path, _, _ in local.get(directory.name, [])]) for directory in directories}
    def check_inputs():
        current = sorted(directory.resolve() for directory in (ROOT / 'songs').iterdir()
            if directory.is_dir() and (selected is None or directory.name in selected))
        if current != directories:
            raise RuntimeError('media publication song population changed')
        for directory, snapshot in snapshots.items():
            require_boundary_snapshot(directory, snapshot)
    check_inputs()
    repository = args.repository or repository_name()
    base = f"https://github.com/{repository}/releases/download/{quote(args.tag, safe='')}"
    previous_bytes = MANIFEST.read_bytes() if MANIFEST.is_file() else None
    previous = json.loads(previous_bytes) if previous_bytes is not None else {}
    manifest_songs = dict(previous.get('songs', {})) if isinstance(previous, dict) else {}
    upload_root = ROOT / '.transcription'
    upload_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='media-release-', dir=upload_root) as temporary:
        frozen = []
        for slug, sources in local.items():
            for path, _, mime_type in sources:
                staged = Path(temporary) / f'{slug}{path.suffix}'
                # A hardlink would share an inode with an in-place edit. Copy
                # first, then compute the name from the exact isolated bytes.
                shutil.copy2(path, staged)
                fingerprint = sha256(staged)
                name = f'{slug}-{fingerprint}{path.suffix}'
                for row in manifest_songs.get(slug, []):
                    src = row.get('src', '')
                    if (row.get('sha256') == fingerprint and row.get('type') == mime_type
                            and src.startswith(base + '/')):
                        candidate = unquote(src[len(base) + 1:])
                        if candidate and Path(candidate).name == candidate:
                            name = candidate
                            break
                named = staged.with_name(name)
                staged.replace(named)
                frozen.append((slug, named, mime_type, fingerprint))
        check_inputs()
        assets = {} if args.manifest_only else release_assets(repository, args.tag)
        check_inputs()
        pending = []
        published = {slug: [] for slug in local}
        for slug, staged, mime_type, fingerprint in frozen:
            if sha256(staged) != fingerprint:
                raise RuntimeError('immutable upload snapshot changed before publication')
            published[slug].append({'src': f"{base}/{quote(staged.name, safe='')}",
                'type': mime_type, 'sha256': fingerprint})
            if not args.manifest_only:
                remote_size = assets.get(staged.name)
                if remote_size is None:
                    pending.append(str(staged))
                elif remote_size != staged.stat().st_size:
                    raise RuntimeError(f'immutable media asset conflicts with local content: {staged.name}')
        check_inputs()
        if pending:
            command('gh', 'release', 'upload', args.tag, '--repo', repository, *pending)
        check_inputs()
        if (MANIFEST.read_bytes() if MANIFEST.is_file() else None) != previous_bytes:
            raise RuntimeError('media manifest changed during publication')
        for slug, rows in published.items():
            manifest_songs[slug] = rows
        output = {'schemaVersion': 2, 'repository': repository, 'releaseTag': args.tag,
            'songs': {slug: manifest_songs[slug] for slug in sorted(manifest_songs)}}
        atomic_json(MANIFEST, output)
    print(json.dumps({'repository': repository, 'tag': args.tag, 'localSongs': len(local),
        'uploadedAssets': len(pending), 'manifestSongs': len(manifest_songs)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
