"""Archive Browser previews for formats the October 2026 game update changed.

PALOC tables now ship per string domain inside the LZ4 container, gameplay tables
moved to staticinfo header/body pairs, the DLC replaces some proxy meshes with
empty PAMs, and several encrypted binary formats have no content signature.
"""

from __future__ import annotations

import random
import struct
from pathlib import Path

import lz4.block
import pytest

from cdmw.core.archive_format import crypt_chacha20_filename, try_decrypt_archive_entry_data
from cdmw.core.archive_preview_result_builder import build_archive_preview_result
from cdmw.core.paloc_format import LocalizationEntry, encode_paloc
from cdmw.models import ArchiveEntry
from tests.test_pab_bind_transforms import fixture as pab_fixture
from tests.test_paloc_container import wrapped


@pytest.fixture
def stored(tmp_path, monkeypatch):
    """An unencrypted, uncompressed archive entry backed by its own PAZ file."""

    monkeypatch.setenv("CDMW_TEMP_CACHE_ROOT", str(tmp_path / "cache"))

    def make(path: str, payload: bytes, *, package: str = "0008") -> ArchiveEntry:
        folder = tmp_path / package
        folder.mkdir(parents=True, exist_ok=True)
        paz = folder / f"{len(list(folder.glob('*.paz')))}.paz"
        paz.write_bytes(payload)
        return ArchiveEntry(path, folder / "0.pamt", paz, 0, len(payload), len(payload), 0, 0)

    return make


def test_pab_preview_shows_the_skeleton_instead_of_raw_bytes(stored):
    entry = stored("character/model/1_pc/1_phm/phm_01.pab", pab_fixture()[0])

    result = build_archive_preview_result(entry)

    assert result.status == "ok"
    assert not result.warning_badge, result.detail_text
    assert result.preview_text.startswith("PAB skeleton preview for character/model/1_pc/1_phm/phm_01.pab")
    assert "Skeleton" in result.metadata_summary


def test_paloc_preview_lists_entries_from_the_compressed_container(stored):
    payload = encode_paloc([
        LocalizationEntry(7, "1103201245", "Sea-Worn\nCutlass"),
        LocalizationEntry(8, "item_desc_named", "A blade that survived the voyage."),
    ])
    entry = stored("gamedata/stringtable/binary__/eng/item.dlc_01.paloc", wrapped(payload))

    result = build_archive_preview_result(entry)

    assert "Localization Table" in result.metadata_summary
    text = result.preview_text
    assert "- Language folder: eng" in text
    assert "- String domain: item.dlc_01" in text
    assert "- Storage: LZ4 container" in text
    assert "- Entries: 2 (1 numeric keys, 1 named keys)" in text
    assert "  1103201245 = Sea-Worn\\nCutlass" in text
    assert "  item_desc_named = A blade that survived the voyage." in text
    assert "Decoded 2 localization entries." in result.detail_text


def test_unreadable_paloc_keeps_the_text_view_and_says_why(stored):
    container = bytearray(wrapped(encode_paloc([LocalizationEntry(1, "k", "v")])))
    struct.pack_into("<I", container, 5, 9)
    entry = stored("gamedata/stringtable/binary__/eng/board.paloc", bytes(container))

    result = build_archive_preview_result(entry)

    assert result.preferred_view == "text"
    assert "The localization table could not be decoded: unsupported PALOC container version 9" in result.detail_text


def _named_table(rows):
    body, directory = bytearray(), bytearray(struct.pack("<H", len(rows)))
    for key, name, fields in rows:
        directory += struct.pack("<II", key, len(body))
        encoded = name.encode("utf-8")
        body += struct.pack("<I", len(encoded)) + encoded + struct.pack("<I", key) + fields
    return bytes(directory), bytes(body)


@pytest.mark.parametrize("selected", ["header", "body"])
def test_static_table_preview_lists_rows_from_its_pair(stored, selected):
    header, body = _named_table([(7, "Sword_Cutlass", b"\x01" * 9), (11, "Ship_Sail", b"\x02" * 3)])
    stem = "gamedata/binarystaticinfo__/bin/iteminfo.dlc_01"
    header_entry = stored(f"{stem}.staticinfoheader", header, package="dlc/0001")
    body_entry = stored(f"{stem}.staticinfobody", body, package="dlc/0001")
    entry, companion = (header_entry, body_entry) if selected == "header" else (body_entry, header_entry)
    companions = {companion.path.casefold(): (companion,)}

    result = build_archive_preview_result(entry, texture_entries_by_normalized_path=companions)

    text = result.preview_text
    assert "Static Data Table" in result.metadata_summary
    assert "- Table: iteminfo.dlc_01" in text
    assert "- Rows: 2" in text
    assert "- Row layout: name, then key" in text
    assert "  [0] key 7  Sword_Cutlass  (30 bytes)" in text
    assert "  [1] key 11  Ship_Sail  (20 bytes)" in text


def test_static_table_preview_shows_fields_of_a_decoded_table(stored):
    from tests.compact_item_fixtures import table
    from tests.test_static_table_records import inventory_row

    body, header = table([(1, inventory_row(1, "Money", 20, 240)), (2, inventory_row(2, "Character", 50, 240))], width=2)
    stem = "gamedata/binarystaticinfo__/bin/inventory"
    header_entry = stored(f"{stem}.staticinfoheader", header, package="0008")
    body_entry = stored(f"{stem}.staticinfobody", body, package="0008")

    result = build_archive_preview_result(
        body_entry, texture_entries_by_normalized_path={header_entry.path.casefold(): (header_entry,)})

    text = result.preview_text
    assert "Decoded fields of the first 2 rows (2 decoded):" in text
    assert "  key 2  Character" in text
    assert "    _defaultSlotCount (u16) = 50" in text
    assert "    _maxSlotCount (u16) = 240" in text
    assert "The closed inventory record schema decoded 2 of the first 2 rows." in result.detail_text


def test_static_table_preview_decodes_only_the_rows_it_prints(stored, monkeypatch):
    from cdmw.core import static_table_records
    from tests.compact_item_fixtures import table
    from tests.test_static_table_records import inventory_row

    calls = []
    original = static_table_records.decode_record
    monkeypatch.setattr(static_table_records, "decode_record", lambda *a, **k: calls.append(1) or original(*a, **k))
    body, header = table([(key, inventory_row(key, f"Bag{key}", 1, 10)) for key in range(1, 30)], width=2)
    stem = "gamedata/binarystaticinfo__/bin/inventory"
    header_entry = stored(f"{stem}.staticinfoheader", header, package="0008")
    body_entry = stored(f"{stem}.staticinfobody", body, package="0008")

    result = build_archive_preview_result(
        body_entry, texture_entries_by_normalized_path={header_entry.path.casefold(): (header_entry,)})

    assert len(calls) == 5
    assert "  [28] key 29  Bag29" in result.preview_text


def test_static_table_halves_are_never_mixed_across_archive_layers(stored):
    header, body = _named_table([(7, "Sword_Cutlass", b"")])
    stem = "gamedata/binarystaticinfo__/bin/iteminfo"
    header_entry = stored(f"{stem}.staticinfoheader", header, package="0008")
    other_layer = stored(f"{stem}.staticinfobody", body, package="dlc/0001")

    result = build_archive_preview_result(
        header_entry,
        texture_entries_by_normalized_path={other_layer.path.casefold(): (other_layer,)},
    )

    assert "iteminfo.staticinfobody was not available" in result.detail_text
    assert "- Rows:" not in result.preview_text


def test_empty_static_table_is_reported_as_empty(stored):
    stem = "gamedata/binarystaticinfo__/bin/questinfo.dlc_01"
    header_entry = stored(f"{stem}.staticinfoheader", b"\x00\x00")
    body_entry = stored(f"{stem}.staticinfobody", b"")

    result = build_archive_preview_result(
        header_entry,
        texture_entries_by_normalized_path={body_entry.path.casefold(): (body_entry,)},
    )

    assert "- Rows: 0 (empty table)" in result.preview_text
    assert "An empty current table replaces any older copy" in result.detail_text


def test_empty_placeholder_pam_says_it_has_no_geometry(stored):
    placeholder = b"PAR \x05\x18" + bytes(1034)
    entry = stored("leveldata/rootlevel/sectorlevel/proxylod/sector_-2_-6_6_2.pam", placeholder)

    result = build_archive_preview_result(entry)

    assert result.preview_model is None
    assert "This PAM declares no submeshes, so it has no geometry to preview." in result.detail_text
    assert "failed to recover geometry" not in result.detail_text


def _encrypted(path, plain, *, compress):
    stored_bytes = lz4.block.compress(plain, store_size=False) if compress else plain
    entry = ArchiveEntry(
        path, pamt_path=Path("owned/0.pamt"), paz_file=Path("owned/0.paz"),
        offset=0, comp_size=len(stored_bytes), orig_size=len(plain), paz_index=0,
        flags=(3 << 4) | (2 if compress else 0),
    )
    return entry, stored_bytes


@pytest.mark.parametrize("path, compress", [
    ("ui/bin__/questinfo_game.uibinary", True),
    ("gamedata/savepreset/bin/puzzle_maze_0001.save", True),
    ("shadercache__/d3d12/windows/sky.pars", False),
    ("gamedata/binarymisc__/bin/dlc_01.admeta", False),
])
def test_encrypted_binary_without_a_content_signature_decrypts(path, compress):
    # Unrecognizable binary: no text, no known magic, few readable strings.
    plain = random.Random(path).randbytes(4096) + bytes(2048)
    entry, stored_bytes = _encrypted(path, plain, compress=compress)
    encrypted = crypt_chacha20_filename(stored_bytes, entry.basename)

    assert try_decrypt_archive_entry_data(entry, encrypted) == (stored_bytes, "ChaCha20")


def test_lz4_entry_that_does_not_decrypt_to_its_declared_size_is_refused():
    entry, _stored = _encrypted("ui/bin__/title_component_game.uibinary", bytes(4096), compress=True)
    garbage = random.Random(3).randbytes(entry.comp_size)

    with pytest.raises(ValueError, match="ChaCha20 decryption validation failed"):
        try_decrypt_archive_entry_data(entry, garbage)


@pytest.mark.parametrize("compress", [False, True])
def test_plaintext_stored_under_an_encryption_flag_is_returned_unchanged(compress):
    plain = ("Plain help text that was never encrypted.\n" * 40).encode("ascii")
    entry, stored_bytes = _encrypted("miscellaneous/readme.txt", plain, compress=compress)

    assert try_decrypt_archive_entry_data(entry, stored_bytes) == (stored_bytes, "ChaCha20FlagMismatch")


# Exact bytes of the files the DLC update shipped (game 1.0.0.3446).
DLC_ADMETA = bytes.fromhex("06000000") + b"dlc_01" + bytes.fromhex("01000000")
DLC_CONTENT_GROUP_KEYS = bytes.fromhex("06000000" "e9030000" "ea030000" "eb030000" "ed030000" "ee030000" "723a0f00")
GIMMICK_CACHE_HEAD = bytes.fromhex("df050000" "2e864c09" "16000000") + bytes(64)


@pytest.mark.parametrize("path, payload, expected", [
    ("gamedata/binarymisc__/bin/dlc_01.admeta", DLC_ADMETA, "DLC id: dlc_01"),
    ("gamedata/binarymisc__/bin/dlc_01.contentgroupkeymap", DLC_CONTENT_GROUP_KEYS, "  5: 998002"),
    ("gamedata/binarygimmickchart__/bin/gimmickchartcacheddata.dlc_01.binarygimmickcacheddata",
     GIMMICK_CACHE_HEAD, "Record count: 1,503"),
])
def test_dlc_metadata_files_show_their_fields(stored, path, payload, expected):
    result = build_archive_preview_result(stored(path, payload))
    assert result.status == "ok"
    assert expected in result.preview_text


def test_dlc_metadata_with_another_layout_falls_back_and_says_why(stored):
    result = build_archive_preview_result(stored("gamedata/binarymisc__/bin/dlc_01.contentgroupkeymap",
                                                 DLC_CONTENT_GROUP_KEYS[:-1]))
    assert "does not have the shipped DLC metadata layout" in result.detail_text
