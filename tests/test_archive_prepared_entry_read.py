from __future__ import annotations

import hashlib
import struct
import threading
from dataclasses import replace
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


@pytest.mark.parametrize("extension", [".pam", ".pami", ".dds"])
def test_prepared_size_preserves_archive_provenance_and_integrity(tmp_path: Path, extension: str) -> None:
    prepared = tmp_path / f"prepared{extension}"
    payload = b"partial PAR payload"
    prepared.write_bytes(payload)
    entry = replace(
        _prepared_entry(prepared, expected_size=99),
        path=f"effect/mesh/leaf{extension}", flags=1, prepared_size=len(payload),
    )

    assert read_archive_entry_data(entry)[0] == payload
    assert entry.orig_size == 99
    prepared.write_bytes(b"X" * len(payload))
    with pytest.raises(ValueError, match="checksum changed"):
        read_archive_entry_data(entry)
    prepared.write_bytes(payload[:-1])
    with pytest.raises(ValueError, match="size changed"):
        read_archive_entry_data(entry)


def _partial_pam_payload() -> tuple[bytes, bytes]:
    import lz4.block

    geometry = b"ABCD" * 64
    packed = lz4.block.compress(geometry, store_size=False)
    prefix = bytearray(0x50)
    prefix[:4] = b"PAR "
    struct.pack_into("<I", prefix, 4, 0x1802)
    struct.pack_into("<III", prefix, 0x3C, len(prefix), len(geometry), len(packed))
    raw = bytes(prefix) + packed + b"PAM trailer!"
    struct.pack_into("<I", prefix, 0x44, 0)
    return raw, bytes(prefix) + geometry + b"PAM trailer!"


@pytest.mark.parametrize("prepared_source", [False, True])
def test_partial_pam_decompresses_geometry_and_preserves_prefix_and_trailer(tmp_path: Path, prepared_source: bool) -> None:
    raw, expected = _partial_pam_payload()
    path = tmp_path / "source.pam"
    path.write_bytes(raw)
    entry = replace(_raw_entry(path, raw, flags=1, orig_size=len(expected)), path="effect/leaf.pam")
    if prepared_source:
        entry = replace(
            entry, prepared_path=path, prepared_size=len(raw), flags=0x31,
            prepared_sha256=hashlib.sha256(raw).hexdigest(), prepared_note="ChaCha20,PartialRaw",
        )
    data, decompressed, note = read_archive_entry_data(entry)
    assert data == expected
    assert decompressed
    assert "PartialPAM" in note and "PartialRaw" not in note
    assert path.read_bytes() == raw
    assert entry.orig_size == len(expected)


@pytest.mark.parametrize("damage", ["truncated", "wrong_size"])
def test_prepared_partial_pam_rejects_invalid_geometry(tmp_path: Path, damage: str) -> None:
    raw, expected = _partial_pam_payload()
    raw = bytearray(raw)
    if damage == "truncated":
        raw = raw[:0x51]
    else:
        struct.pack_into("<I", raw, 0x40, 999)
    path = tmp_path / "source.pam"
    path.write_bytes(raw)
    entry = replace(
        _prepared_entry(path, expected_size=len(expected)), path="effect/leaf.pam", flags=1,
        prepared_size=len(raw),
    )
    with pytest.raises(ValueError, match="Partial PAM geometry block has inconsistent sizes"):
        read_archive_entry_data(entry)


def test_explicit_empty_prepared_source_rejects_added_bytes(tmp_path: Path) -> None:
    prepared = tmp_path / "empty.pam"
    prepared.write_bytes(b"")
    entry = replace(_prepared_entry(prepared, expected_size=99), prepared_size=0)
    assert read_archive_entry_data(entry)[0] == b""
    prepared.write_bytes(b"X")
    with pytest.raises(ValueError, match="size changed"):
        read_archive_entry_data(entry)


def test_prepared_archive_entry_honors_cancellation_before_read(tmp_path: Path) -> None:
    prepared = tmp_path / "prepared.pac"
    prepared.write_bytes(b"prepared payload")
    entry = _prepared_entry(prepared, expected_size=len(b"prepared payload"))
    stop_event = threading.Event()
    stop_event.set()

    with pytest.raises(RunCancelled):
        read_archive_entry_data(entry, stop_event=stop_event)


def _raw_entry(paz_file: Path, payload: bytes, *, flags: int = 0, orig_size: int | None = None) -> ArchiveEntry:
    return ArchiveEntry(
        path="text/raw_note.txt",
        pamt_path=paz_file.parent / "raw.pamt",
        paz_file=paz_file,
        offset=0,
        comp_size=len(payload),
        orig_size=len(payload) if orig_size is None else orig_size,
        flags=flags,
        paz_index=0,
    )


def test_raw_archive_entry_read_decodes_in_process_without_native_accelerator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A payload this process can decode never pays the accelerator round trip."""
    from cdmw.core import archive_accelerator

    paz = tmp_path / "raw.paz"
    paz.write_bytes(b"plain payload")

    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("The native accelerator must not run for an in-process decodable entry.")

    monkeypatch.setattr(archive_accelerator, "read_archive_entry_data_native", _fail_if_called)

    data, decompressed, note = read_archive_entry_data(_raw_entry(paz, b"plain payload"))

    assert data == b"plain payload"
    assert not decompressed
    assert note == ""


def test_raw_archive_entry_read_falls_back_to_native_for_undecodable_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cdmw.core import archive_accelerator

    paz = tmp_path / "raw.paz"
    paz.write_bytes(b"opaque")
    entry = _raw_entry(paz, b"opaque", flags=0x0F, orig_size=32)  # unsupported compression type

    monkeypatch.setattr(
        archive_accelerator,
        "read_archive_entry_data_native",
        lambda *_args, **_kwargs: (b"native bytes", True, "NativeRaw"),
    )

    assert read_archive_entry_data(entry) == (b"native bytes", True, "NativeRaw")


def test_raw_archive_entry_read_raises_the_in_process_error_when_native_cannot_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cdmw.core import archive_accelerator

    paz = tmp_path / "raw.paz"
    paz.write_bytes(b"opaque")
    entry = _raw_entry(paz, b"opaque", flags=0x0F, orig_size=32)

    monkeypatch.setattr(
        archive_accelerator,
        "read_archive_entry_data_native",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(ValueError, match="Unsupported archive compression type"):
        read_archive_entry_data(entry)
