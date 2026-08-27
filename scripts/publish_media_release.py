#!/usr/bin/env python3
"""Upload listener audio to one GitHub Release and write its public URL map.

GitHub Pages has a 1 GiB published-site limit, so high-quality audio belongs in
release assets rather than the Pages artifact or Git history. Asset names are
stable (`<song-slug>.<extension>`), allowing a reader URL to survive later
metadata and UI changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import quote


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


def link_for_upload(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


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

    repository = args.repository or repository_name()
    base = f"https://github.com/{repository}/releases/download/{quote(args.tag, safe='')}"
    previous = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else {}
    manifest_songs = dict(previous.get("songs", {})) if isinstance(previous, dict) else {}
    previous_hashes = {
        source.get("src", "").rsplit("/", 1)[-1]: source.get("sha256")
        for sources in manifest_songs.values() if isinstance(sources, list)
        for source in sources if isinstance(source, dict)
    }
    selected = set(args.song) if args.song else None
    local = local_audio(selected)
    if selected:
        missing = sorted(selected - set(local))
        if missing:
            raise SystemExit(f"selected songs lack listener audio: {', '.join(missing)}")
    assets = {} if args.manifest_only else release_assets(repository, args.tag)

    pending: list[tuple[Path, str]] = []
    for slug, sources in local.items():
        published = []
        for path, asset_name, mime_type in sources:
            fingerprint = sha256(path)
            published.append({"src": f"{base}/{quote(asset_name, safe='')}",
                              "type": mime_type, "sha256": fingerprint})
            previous_hash = previous_hashes.get(quote(asset_name, safe=""))
            if not args.manifest_only and needs_upload(
                assets.get(asset_name), path.stat().st_size, previous_hash, fingerprint
            ):
                pending.append((path, asset_name))
        manifest_songs[slug] = published

    if pending:
        upload_root = ROOT / ".transcription"
        upload_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="media-release-", dir=upload_root) as temporary:
            staged = []
            for source, asset_name in pending:
                target = Path(temporary) / asset_name
                link_for_upload(source, target)
                staged.append(str(target))
            command("gh", "release", "upload", args.tag, "--repo", repository, "--clobber", *staged)

    output = {
        "schemaVersion": 2,
        "repository": repository,
        "releaseTag": args.tag,
        "songs": {slug: manifest_songs[slug] for slug in sorted(manifest_songs)},
    }
    MANIFEST.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"repository": repository, "tag": args.tag, "localSongs": len(local),
                      "uploadedAssets": len(pending), "manifestSongs": len(manifest_songs)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
