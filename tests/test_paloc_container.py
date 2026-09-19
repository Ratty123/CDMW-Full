"""The compressed PALOC container must survive reading and New Item export."""

from pathlib import Path
import struct
import sys

import lz4.block
import pytest

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import crypt_chacha20_filename, parse_archive_pamt
from cdmw.core.paloc_format import (
    LocalizationEntry, PalocFormatError, add_localization_entries, encode_paloc,
    parse_paloc, rebuild_is_exact, replace_text,
)
from cdmw.models import ArchiveEntry


def wrapped(payload):
    # A valid literal-only LZ4 block deliberately differs from the normal encoder.
    size = len(payload)
    block = bytearray([min(size, 15) << 4])
    if size >= 15:
        remaining = size - 15
        while remaining >= 255:
            block.append(255)
            remaining -= 255
        block.append(remaining)
    block.extend(payload)
    header = bytearray(512)
    header[:5] = b"paloc"
    struct.pack_into("<III", header, 5, 0, len(block), size)
    return bytes(header + block)


@pytest.fixture
def container():
    return wrapped(encode_paloc([
        LocalizationEntry(7, "100", "Repeated item name " * 16),
        LocalizationEntry(8, "101", "Description"),
    ]))


def test_container_round_trip_preserves_original_compressed_bytes(container):
    table = parse_paloc(container)
    assert len(table) == 2
    assert table.index()["101"].text == "Description"
    assert encode_paloc(table) == container
    assert rebuild_is_exact(container)
    empty = wrapped(encode_paloc(()))
    assert encode_paloc(parse_paloc(empty)) == empty


def test_text_edits_and_added_names_keep_container_and_update_sizes(container):
    # Opaque header bytes belong to the source and must survive an edit.
    container = container[:200] + b"opaque" + container[206:]
    table, missing = replace_text(parse_paloc(container), {"100": "A different name"})
    table = add_localization_entries(table, [LocalizationEntry(7, "200", "New name")])
    encoded = encode_paloc(table)
    assert not missing
    assert encoded[:9] == container[:9]
    assert encoded[17:512] == container[17:512]
    stored, unpacked = struct.unpack_from("<II", encoded, 9)
    assert stored == len(encoded) - 512
    payload = lz4.block.decompress(encoded[512:], uncompressed_size=unpacked)
    assert len(payload) == unpacked
    assert parse_paloc(payload).entries == table.entries
    assert parse_paloc(encoded).index()["200"].text == "New name"


@pytest.mark.parametrize("damage", ["short", "version", "stored_size", "unpacked_size", "oversized", "lz4", "footer"])
def test_malformed_containers_are_refused(container, damage):
    data = bytearray(container)
    if damage == "short":
        data = data[:100]
    elif damage == "version":
        struct.pack_into("<I", data, 5, 1)
    elif damage == "stored_size":
        struct.pack_into("<I", data, 9, len(data))
    elif damage == "unpacked_size":
        struct.pack_into("<I", data, 13, struct.unpack_from("<I", data, 13)[0] + 1)
    elif damage == "oversized":
        struct.pack_into("<I", data, 13, 0xFFFFFFFF)
    elif damage == "lz4":
        data[512:] = bytes(len(data) - 512)
    else:
        payload = encode_paloc([LocalizationEntry(7, "100", "Name")])
        data = wrapped(payload[:-4] + struct.pack("<I", 2))
    with pytest.raises(PalocFormatError):
        parse_paloc(bytes(data))


def archived_paloc(tmp_path, data, *, encrypted=True, outer_compressed=False):
    path = "gamedata/stringtable/binary__/eng/item.paloc"
    stored = lz4.block.compress(data, store_size=False) if outer_compressed else data
    paz = tmp_path / "0.paz"
    paz.write_bytes(crypt_chacha20_filename(stored, "item.paloc") if encrypted else stored)
    return ArchiveEntry(path=path, pamt_path=tmp_path / "0.pamt", paz_file=paz,
                        offset=0, comp_size=len(stored), orig_size=len(data),
                        flags=((3 << 4) if encrypted else 0) | (2 if outer_compressed else 0), paz_index=0)


@pytest.mark.parametrize("outer_compressed", [False, True])
@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("use_container", [False, True])
def test_archive_read_accepts_supported_paloc_encodings(tmp_path, container, outer_compressed, encrypted, use_container):
    expected = container if use_container else encode_paloc(parse_paloc(container).entries)
    entry = archived_paloc(tmp_path, expected, encrypted=encrypted, outer_compressed=outer_compressed)
    data, _decompressed, note = read_archive_entry_data(entry)
    assert data == expected
    assert ("ChaCha20" in note) == encrypted
    assert len(parse_paloc(data)) == 2


@pytest.mark.parametrize("outer_compressed", [False, True])
@pytest.mark.parametrize("damage,reason", [
    ("version", "unsupported PALOC container version 1"),
    ("lz4", "PALOC container LZ4 decompression failed"),
    ("footer", "the footer counts 2 records but the table walks 1"),
])
def test_encrypted_paloc_failure_keeps_the_parser_reason(tmp_path, container, outer_compressed, damage, reason):
    data = bytearray(container)
    if damage == "version":
        struct.pack_into("<I", data, 5, 1)
    elif damage == "lz4":
        data[512:] = bytes(len(data) - 512)
    else:
        payload = encode_paloc([LocalizationEntry(7, "100", "Name")])
        data = wrapped(payload[:-4] + struct.pack("<I", 2))
    entry = archived_paloc(tmp_path, bytes(data), outer_compressed=outer_compressed)
    before = entry.paz_file.read_bytes()
    with pytest.raises(ValueError) as caught:
        read_archive_entry_data(entry)
    message = str(caught.value)
    assert reason in message
    assert entry.path in message
    assert entry.package_label in message
    assert "ChaCha20 decryption validation failed" not in message
    assert entry.paz_file.read_bytes() == before


def test_archive_lz4_failure_keeps_the_compression_stage(tmp_path, container):
    entry = archived_paloc(tmp_path, container, outer_compressed=True)
    entry.paz_file.write_bytes(crypt_chacha20_filename(bytes(entry.comp_size), "item.paloc"))
    with pytest.raises(ValueError, match="archive LZ4 decompression failed") as caught:
        read_archive_entry_data(entry)
    assert entry.path in str(caught.value)
    assert entry.package_label in str(caught.value)


def test_new_item_loads_and_exports_wrapped_names(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_current_item_names import current_files
    from test_new_item_service import LOC, TEMPLATE, NAME_KEY, build_package, _read
    from cdmw.domain.new_item.spec import NewItemSpec
    from cdmw.services.new_item_service import NewItemService
    from cdmw.workers.new_item_workers import snapshot_task

    files = current_files()
    path = f"{LOC}/eng/item.paloc"
    files[path] = wrapped(files[path])
    pamt = build_package(tmp_path / "game", files)
    entries = parse_archive_pamt(pamt)
    source_bytes = {p: p.read_bytes() for p in (pamt, pamt.with_suffix(".paz"))}
    service = NewItemService()
    snapshot = snapshot_task(entries, service=service, read_entry=_read)(lambda _: None, None)
    assert snapshot.item_display_names()[TEMPLATE] == "Wolf's Fang"
    plan = service.plan(NewItemSpec(template_key=TEMPLATE, internal_name="Wrapped_Clone_OneHandSword",
                                    display_names={"eng": "Wrapped Clone"}), snapshot)
    service.export_loose(plan, tmp_path / "mod", manager="JMM")
    from cdmw.services.new_item_mod_base import mod_folder_payloads
    exported = mod_folder_payloads(tmp_path / "mod")[path].read_bytes()
    assert exported == plan.loose_files[path]
    assert exported.startswith(b"paloc")
    table = parse_paloc(exported)
    assert table.index()[NAME_KEY].text == "Wolf's Fang"
    assert table.index()[plan.spec.name_key].text == "Wrapped Clone"
    assert all(p.read_bytes() == before for p, before in source_bytes.items())
