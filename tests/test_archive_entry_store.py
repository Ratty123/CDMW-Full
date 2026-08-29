from __future__ import annotations

import threading
from pathlib import Path

import pytest

from cdmw.core.archive_entry_store import ArchiveEntryStore, write_archive_entry_store
from cdmw.domain.cancellation import RunCancelled
from cdmw.models import ArchiveEntry


def _entries(root: Path) -> list[ArchiveEntry]:
    pamt = root / "archive" / "0.pamt"
    return [
        ArchiveEntry(
            path=path,
            pamt_path=pamt,
            paz_file=pamt.parent / f"{index % 2}.paz",
            offset=index * 100,
            comp_size=40 + index,
            orig_size=80 + index,
            flags=index % 4,
            paz_index=index % 2,
        )
        for index, path in enumerate(
            (
                "character/body/model.pac",
                "character/body/model.pam",
                "texture/body/base.dds",
                "texture/body/normal.dds",
                "ui/icons/model.dds",
            )
        )
    ]


def test_entry_store_materializes_rows_and_indexes_on_demand(tmp_path: Path) -> None:
    entries = _entries(tmp_path)
    store_path = write_archive_entry_store(tmp_path / "entry-store", entries)

    with ArchiveEntryStore(store_path) as store:
        assert len(store) == len(entries)
        assert [store.entry(index).identity for index in range(len(store))] == [
            entry.identity for entry in entries
        ]
        assert store.row_ids_for_extension(".dds") == (2, 3, 4)
        assert store.row_ids_for_path("TEXTURE\\BODY\\BASE.DDS") == (2,)
        assert [entry.path for entry in store.iter_entries((4, 0))] == [
            "ui/icons/model.dds",
            "character/body/model.pac",
        ]


def test_entry_store_publish_replaces_prior_complete_store(tmp_path: Path) -> None:
    target = tmp_path / "entry-store"
    write_archive_entry_store(target, _entries(tmp_path)[:2])
    write_archive_entry_store(target, _entries(tmp_path))

    with ArchiveEntryStore(target) as store:
        assert len(store) == 5
        assert store.row_ids_for_extension(".pac") == (0,)


def test_empty_entry_store_is_valid(tmp_path: Path) -> None:
    target = write_archive_entry_store(tmp_path / "empty-store", [])

    with ArchiveEntryStore(target) as store:
        assert len(store) == 0
        assert store.row_ids_for_extension(".dds") == ()


def test_entry_store_cancellation_preserves_prior_store(tmp_path: Path) -> None:
    target = tmp_path / "entry-store"
    write_archive_entry_store(target, _entries(tmp_path))
    stop_event = threading.Event()
    stop_event.set()

    with pytest.raises(RunCancelled):
        write_archive_entry_store(target, _entries(tmp_path), stop_event=stop_event)

    with ArchiveEntryStore(target) as store:
        assert len(store) == 5
