from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest

from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.services.archive_read_service import read_archive_entry_data


def _prepared_entry(path: Path, *, expected_size: int) -> ArchiveEntry:
    return ArchiveEntry(
        path="model/example.pac",
        pamt_path=path.parent / "missing.pamt",
        paz_file=path.parent / "fallback.paz",
        offset=0,
        comp_size=max(0, expected_size - 2),
        orig_size=expected_size,
        flags=2,
        paz_index=0,
        prepared_path=path,
        prepared_sha256=(
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "synthetic-sha"
        ),
        prepared_note="LZ4",
    )


def test_prepared_archive_entry_reads_worker_materialized_bytes_without_archive_fallback(
    tmp_path: Path,
) -> None:
    prepared = tmp_path / "prepared.pac"
    prepared.write_bytes(b"prepared payload")
    (tmp_path / "fallback.paz").write_bytes(b"wrong fallback")
    entry = _prepared_entry(prepared, expected_size=len(b"prepared payload"))

    data, decompressed, note = read_archive_entry_data(entry)

    assert data == b"prepared payload"
    assert decompressed
    assert "LZ4" in note
    assert "standalone archive worker prepared source" in note


def test_missing_prepared_archive_entry_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "fallback.paz").write_bytes(b"must not be read")
    entry = _prepared_entry(tmp_path / "missing.pac", expected_size=16)

    with pytest.raises(ValueError, match="Prepared archive source is unavailable"):
        read_archive_entry_data(entry)


def test_changed_prepared_archive_entry_size_is_rejected(tmp_path: Path) -> None:
    prepared = tmp_path / "prepared.pac"
    prepared.write_bytes(b"short")
    entry = _prepared_entry(prepared, expected_size=99)

    with pytest.raises(ValueError, match="Prepared archive source size changed"):
        read_archive_entry_data(entry)


def test_changed_prepared_archive_entry_checksum_is_rejected(tmp_path: Path) -> None:
    prepared = tmp_path / "prepared.pac"
    prepared.write_bytes(b"first")
    entry = _prepared_entry(prepared, expected_size=5)
    prepared.write_bytes(b"other")

    with pytest.raises(ValueError, match="Prepared archive source checksum changed"):
        read_archive_entry_data(entry)


def test_prepared_archive_entry_honors_cancellation_before_read(tmp_path: Path) -> None:
    prepared = tmp_path / "prepared.pac"
    prepared.write_bytes(b"prepared payload")
    entry = _prepared_entry(prepared, expected_size=len(b"prepared payload"))
    stop_event = threading.Event()
    stop_event.set()

    with pytest.raises(RunCancelled):
        read_archive_entry_data(entry, stop_event=stop_event)
