"""Owned fixtures for the October 2026 compact archive index (no game assets)."""
from pathlib import Path
import struct

import pytest

from cdmw.core.archive_format import VfsPathResolver, parse_archive_pamt_bytes
from cdmw.core.archive_extraction import _decode_archive_entry_data
from cdmw.core.papgt_format import parse_papgt, read_papgt_directories


def compact_pamt(*, flags=0x100, paz_id=48, name=b"\x00\x04test", extensions=b"\x00.txt\x00"):
    data = bytearray(struct.pack("<III", 0, 1, 0x610E0232))
    data += struct.pack("<III", paz_id, 0, 5)
    data += struct.pack("<I", 0)
    data += struct.pack("<I", len(name)) + name
    data += struct.pack("<II", 0, 1)
    data += struct.pack("<IIIIHH", 0, 0, 5, 5, paz_id, flags)
    data += struct.pack("<I", len(extensions)) + extensions
    return bytes(data)


def test_compact_name_extension_sparse_paz_and_encryption_bits():
    entry, = parse_archive_pamt_bytes(compact_pamt(), Path("dlc/dlc_01/0009/0.pamt"))
    assert entry.path == "test.txt"
    assert entry.paz_file == Path("dlc/dlc_01/0009/48.paz")
    assert entry.flags == 0x100 and not entry.encrypted
    assert _decode_archive_entry_data(entry, b"hello") == (b"hello", False, "")
    encrypted, = parse_archive_pamt_bytes(compact_pamt(flags=0x130), Path("0.pamt"))
    assert encrypted.encrypted and encrypted.encryption_type == 3


def test_compact_parent_distance_crosses_a_varint_boundary():
    block = b"\x00\x04root" + b"\x00\x78" + b"x" * 120
    assert len(block) == 128
    block += b"\x80\x01\x05/leaf"
    assert VfsPathResolver(block, compact=True).get_full_path(128) == "root/leaf"


@pytest.mark.parametrize("name", [b"\x80", b"\x01\x01a", b"\x00", b"\x00\x05ab", b"\x80" * 5])
def test_compact_rejects_invalid_name_records(name):
    with pytest.raises(ValueError, match="Compact VFS"):
        parse_archive_pamt_bytes(compact_pamt(name=name), Path("0.pamt"))


@pytest.mark.parametrize("data", [compact_pamt(flags=0x200), compact_pamt()[:-1], compact_pamt(extensions=b"\x00bad\x00")])
def test_compact_rejects_invalid_extension_table(data):
    with pytest.raises(ValueError, match="extension"):
        parse_archive_pamt_bytes(data, Path("0.pamt"))


def compact_mount():
    names = b"0009\x000015\x00"
    return (b"\x81\x16\x02\x02" + struct.pack("<III", 0x7FFF00, 0, 123)
            + struct.pack("<III", 0x7FFF00, 5, 456) + struct.pack("<I", len(names)) + names + bytes(64))


def test_compact_mount_is_readable_but_not_accepted_by_legacy_writer_parser():
    rows = read_papgt_directories(compact_mount())
    assert [(r.name, r.pamt_checksum) for r in rows] == [("0009", 123), ("0015", 456)]
    with pytest.raises(ValueError):
        parse_papgt(compact_mount())


def test_compact_mount_rejects_a_missing_trailer():
    with pytest.raises(ValueError, match="Compact PAPGT"):
        read_papgt_directories(compact_mount()[:-1])


def test_legacy_mount_header_can_share_the_compact_marker():
    from cdmw.core.papgt_format import PapgtDirectory, serialize_papgt
    raw = serialize_papgt([PapgtDirectory("0009", 0, 1)], header=b"\x00\x00\x00\x02" + bytes(8))
    assert read_papgt_directories(raw) == parse_papgt(raw)


def test_compact_string_dictionary_reads_but_refuses_legacy_append():
    from cdmw.core.stringinfo_table import parse_stringinfo, append_stringinfo_strings, stringinfo_key
    text = "dlc_fixture"
    key = stringinfo_key(text)
    raw = struct.pack("<IIBI", 0, key, 0, len(text)) + text.encode()
    header = struct.pack("<HII", 1, key, 0)
    assert parse_stringinfo(raw, header)[0].text == text
    with pytest.raises(ValueError, match="read-only"):
        append_stringinfo_strings(raw, header, ["new_stem"])
    bad = bytearray(raw); bad[8] = 1
    with pytest.raises(ValueError, match="padding"):
        parse_stringinfo(bytes(bad), header)


def test_compact_named_table_keys_are_checked_even_when_id_equals_name_length():
    from cdmw.core.item_index import _parse_archive_iteminfo_rows, _parse_equip_type_names
    raw = struct.pack("<I", 4) + b"Test" + struct.pack("<I", 4)
    header = struct.pack("<HII", 1, 4, 0)
    record, = _parse_archive_iteminfo_rows(raw, header, {})
    assert (record.item_id, record.internal_name) == (4, "Test")
    assert _parse_equip_type_names(raw, header) == {4: "Test"}
    with pytest.raises(ValueError, match="directory key"):
        _parse_archive_iteminfo_rows(raw[:-4] + struct.pack("<I", 5), header, {})


def test_resident_view_includes_dlc_mounts_and_detects_mount_changes(tmp_path):
    from cdmw.core.archive_format import parse_archive_pamt
    from tests.archive_resident_index_fixtures import write_resident_index
    entries = []
    for relative, stem in [("", b"base"), ("dlc/dlc_01", b"dlc1")]:
        root = tmp_path / relative
        (root / "0009").mkdir(parents=True)
        (root / "0015").mkdir()
        (root / "meta").mkdir()
        mount = bytearray(compact_mount())
        struct.pack_into("<I", mount, 16, 0x7FFF01)  # optional, absent language package
        (root / "meta/0.papgt").write_bytes(mount)
        pamt = root / "0009/0.pamt"
        pamt.write_bytes(compact_pamt(name=b"\x00\x04" + stem))
        (root / "0009/48.paz").write_bytes(b"hello")
        entries.extend(parse_archive_pamt(pamt))
    source = write_resident_index(tmp_path, entries, tmp_path / "generation")
    view = source.open()
    assert {entry.path for entry in view.matching((".txt",))} == {"base.txt", "dlc1.txt"}
    mount = tmp_path / "dlc/dlc_01/meta/0.papgt"
    mount.write_bytes(mount.read_bytes() + b"x")
    with pytest.raises(ValueError, match="Archive source changed"):
        view.validate_sources()


def test_compact_pamt_cannot_enter_the_archive_writer(tmp_path):
    from cdmw.core.archive_patching import _parse_mutable_pamt
    path = tmp_path / "0.pamt"
    raw = compact_pamt()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="read-only"):
        _parse_mutable_pamt(path)
    assert path.read_bytes() == raw
