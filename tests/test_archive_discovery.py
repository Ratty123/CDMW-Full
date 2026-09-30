from __future__ import annotations

import os
from pathlib import Path

import pytest

from cdmw.core import archive_scan_cache
from cdmw.core.archive_scan_cache import discover_pamt_files
from cdmw.models import ArchiveEntry


@pytest.mark.parametrize("live_parent", ["", "game_files"])
def test_archive_discovery_does_not_visit_backup_or_mod_library_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live_parent: str
) -> None:
    live_indexes = [
        tmp_path / live_parent / "0009" / "0.pamt",
        tmp_path / live_parent / "0036" / "0.pamt",
        tmp_path / "0.pamt",
    ]
    ignored_roots = [tmp_path / "BaCkUpS", tmp_path / "Cdmods"]
    ignored_indexes = [
        ignored_roots[0] / "vault" / "5c03e5214c46a260" / "files" / "0009" / "0.pamt",
        ignored_roots[1] / "some_mod" / "0009" / "0.pamt",
    ]
    for index in [*live_indexes, *ignored_indexes]:
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_bytes(b"synthetic index")

    real_scandir = os.scandir

    def checked_scandir(path: str | os.PathLike[str]):
        directory = Path(path)
        assert not any(directory.is_relative_to(root) for root in ignored_roots)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", checked_scandir)
    assert set(discover_pamt_files(tmp_path)) == set(live_indexes)


def test_explicit_backup_index_remains_available_for_inspection(tmp_path: Path) -> None:
    backup_index = tmp_path / "backups" / "vault" / "files" / "0009" / "0.pamt"
    backup_index.parent.mkdir(parents=True)
    backup_index.write_bytes(b"synthetic index")

    assert discover_pamt_files(backup_index) == [backup_index]


def test_legacy_scan_cache_with_backup_entries_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    indexes = [
        tmp_path / "0009" / "0.pamt",
        tmp_path / "backups" / "vault" / "files" / "0009" / "0.pamt",
    ]
    entries = []
    for index in indexes:
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_bytes(b"synthetic index")
        paz = index.with_suffix(".paz")
        paz.write_bytes(b"payload")
        entries.append(ArchiveEntry("text/hello.txt", index, paz, 0, 7, 7, 0, 0))

    cache_root = tmp_path / "cache"
    # Seed a valid cache using the previous policy, which included the backup index.
    with monkeypatch.context() as old_policy:
        old_policy.setattr(archive_scan_cache, "discover_pamt_files", lambda _: indexes)
        archive_scan_cache.save_archive_scan_cache(tmp_path, cache_root, entries)
        assert archive_scan_cache.load_archive_scan_cache(tmp_path, cache_root) is not None

    assert archive_scan_cache.load_archive_scan_cache(tmp_path, cache_root) is None
