#!/usr/bin/env python3
"""Assemble the shared public Pages allowlist; never copy pipeline/review state."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
from pathlib import Path
import shutil
import tempfile

from bhakti_boundary_timebase import (boundary_transaction, boundary_snapshot,
    require_boundary_snapshot, require_completed_boundary_transaction)

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT_FILES = ('index.html', 'manifest.webmanifest', 'sw.js', 'robots.txt', 'sitemap.xml', 'CNAME')


def assemble_public_site(root: Path) -> None:
    root = Path(root)
    songs = sorted((path for path in (root / 'songs').iterdir() if path.is_dir()), key=lambda path: str(path.resolve()))
    with ExitStack() as locks:
        for song in songs:
            locks.enter_context(boundary_transaction(song))
        _assemble_locked(root, songs)


def _assemble_locked(root: Path, songs: list[Path]) -> None:
    for song in songs:
        require_completed_boundary_transaction(song)
    files = [root / name for name in PUBLIC_ROOT_FILES]
    files.append(root / 'data/songs.js')
    files.extend(path for path in (root / 'assets').rglob('*') if path.is_file())
    files.extend(song / name for song in songs for name in ('index.html', 'data.js') if (song / name).is_file())
    # Retain the deployment's internal-file check and reject symlinks rather
    # than following an apparently public path into private source material.
    for path in files:
        relative = path.relative_to(root)
        if (any((root / Path(*relative.parts[:index])).is_symlink() for index in range(1, len(relative.parts) + 1))
                or path.name in {'AGENTS.md', 'README.md', '.gitignore'}
                or path.suffix == '.py' or {'docs', 'scripts'} & set(relative.parts)):
            raise RuntimeError(f'internal or linked file in public allowlist: {relative}')
    snapshots = {song: boundary_snapshot(song, [song / 'index.html', song / 'data.js']) for song in songs}
    fingerprints = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    with tempfile.TemporaryDirectory(prefix='.public-site-', dir=root) as temporary:
        staged = Path(temporary) / 'site'
        staged.mkdir()
        for source in files:
            destination = staged / source.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        # Validate the copied snapshot as well as current inputs. A completed
        # old→new transition can evade a pending-only check but not this binding.
        current = sorted((path for path in (root / 'songs').iterdir() if path.is_dir()), key=lambda path: str(path.resolve()))
        if current != songs:
            raise RuntimeError('public assembly song population changed')
        for song, snapshot in snapshots.items():
            require_boundary_snapshot(song, snapshot)
        for path, fingerprint in fingerprints.items():
            copied = staged / path.relative_to(root)
            if (hashlib.sha256(path.read_bytes()).hexdigest() != fingerprint
                    or hashlib.sha256(copied.read_bytes()).hexdigest() != fingerprint):
                raise RuntimeError('public assembly snapshot changed: ' + str(path.relative_to(root)))
        destination = root / '_site'
        if destination.is_symlink():
            raise RuntimeError('public artifact destination must not be a symlink')
        if destination.exists():
            shutil.rmtree(destination)
        staged.replace(destination)


if __name__ == '__main__':
    assemble_public_site(ROOT)
