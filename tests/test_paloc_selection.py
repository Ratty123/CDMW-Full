"""Selected PALOC lookups retain names and reject damage outside the selection."""

import struct
from types import SimpleNamespace

import lz4.block
import pytest

from cdmw.core.paloc_format import (
    LocalizationEntry, LocalizationTable, PalocFormatError, encode_paloc,
    parse_paloc, select_paloc_entries,
)
from cdmw.services.new_item_snapshot import _localized_item_names


def _wrapped(payload):
    compressed = lz4.block.compress(payload, store_size=False)
    header = bytearray(512)
    header[:5] = b"paloc"
    struct.pack_into("<III", header, 5, 0, len(compressed), len(payload))
    header[200:206] = b"opaque"
    return bytes(header) + compressed


def _record(key, text):
    return struct.pack("<III", 7, 19, len(key)) + key + struct.pack("<I", len(text)) + text


ENTRIES = (
    LocalizationEntry(7, "100", "First name", 19),
    LocalizationEntry(38, "quest", "Unrelated dialogue"),
    LocalizationEntry(7, "100", "Second name"),
    LocalizationEntry(8, "blank", ""),
    LocalizationEntry(7, "名前", "سيف 日本語 Grüße"),
    LocalizationEntry(7, "", "Empty key is legal when reading"),
    LocalizationEntry(7, "controls", "ASCII\x00\x1f\x7f"),
)


@pytest.mark.parametrize("container", [False, True])
@pytest.mark.parametrize("keys", [
    frozenset({"100"}), frozenset(), frozenset({"missing"}),
    frozenset({"名前", "blank", ""}),
    frozenset(entry.key for entry in ENTRIES),
])
def test_selected_records_match_full_table_including_duplicates(container, keys):
    payload = encode_paloc(ENTRIES)
    data = _wrapped(payload) if container else payload
    selected = select_paloc_entries(data, iter(keys), name="owned.paloc")
    expected = tuple(entry for entry in ENTRIES if entry.key in keys)
    assert selected == expected
    assert selected == tuple(entry for entry in parse_paloc(data).entries if entry.key in keys)
    assert isinstance(selected, tuple)
    assert encode_paloc(parse_paloc(data)) == data


def _damaged_payload(damage):
    good = _record(b"100", b"Keep")
    bad = _record(b"unwanted", b"Unrelated text")
    if damage == "invalid_key":
        bad = _record(b"\xff", b"Unrelated text")
    elif damage == "invalid_text":
        bad = _record(b"unwanted", b"\xff\xfe")
    elif damage == "surrogate_text":
        bad = _record(b"unwanted", b"\xed\xa0\x80")
    elif damage == "truncated_header":
        bad = b"\x01"
    elif damage == "key_overrun":
        bad = struct.pack("<III", 7, 0, 9999) + b"k"
    elif damage == "text_overrun":
        bad = struct.pack("<III", 7, 0, 1) + b"k" + struct.pack("<I", 9999) + b"t"
    footer = 1 if damage == "count_small" else 3 if damage == "count_large" else 2
    return good + bad + struct.pack("<I", footer)


@pytest.mark.parametrize("container", [False, True])
@pytest.mark.parametrize("keys", [frozenset({"100"}), frozenset()])
@pytest.mark.parametrize("damage", [
    "invalid_key", "invalid_text", "surrogate_text", "truncated_header",
    "key_overrun", "text_overrun", "count_small", "count_large",
])
def test_damage_after_selected_record_is_still_rejected(container, keys, damage):
    payload = _damaged_payload(damage)
    data = _wrapped(payload) if container else payload
    with pytest.raises(PalocFormatError) as full:
        parse_paloc(data, name="damaged.paloc")
    with pytest.raises(PalocFormatError) as selected:
        select_paloc_entries(data, keys, name="damaged.paloc")
    assert str(selected.value) == str(full.value)
    if damage in {"invalid_key", "invalid_text", "surrogate_text"}:
        assert "record 1 is not UTF-8" in str(selected.value)


@pytest.mark.parametrize("damage", ["short", "version", "stored_size", "unpacked_size", "oversized", "lz4"])
def test_selected_reader_preserves_container_rejections(damage):
    data = bytearray(_wrapped(encode_paloc(ENTRIES)))
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
    else:
        data[512:] = bytes(len(data) - 512)
    with pytest.raises(PalocFormatError) as full:
        parse_paloc(bytes(data), name="container.paloc")
    with pytest.raises(PalocFormatError) as selected:
        select_paloc_entries(bytes(data), {"100"}, name="container.paloc")
    assert str(selected.value) == str(full.value)


def test_names_keep_all_languages_duplicate_order_and_english_display_authority():
    english = LocalizationTable((
        LocalizationEntry(7, "100", " First "),
        LocalizationEntry(7, "100", "Final"),
        LocalizationEntry(7, "200", " "),
        LocalizationEntry(38, "unwanted", "Dialogue"),
    ))
    german = encode_paloc((
        LocalizationEntry(38, "unwanted", "Andere Geschichte"),
        LocalizationEntry(7, "100", " Schwert "),
        LocalizationEntry(7, "100", "Schwert"),
        LocalizationEntry(7, "200", "Stiefel"),
    ))
    arabic = _wrapped(encode_paloc((
        LocalizationEntry(7, "100", "سيف"),
        LocalizationEntry(7, "200", " "),
    )))
    sources = {"ger": german, "ara": arabic}
    entries = {lang: SimpleNamespace(path=lang) for lang in ("eng", "ger", "ara")}
    rows = {1: SimpleNamespace(name_key="100"), 2: SimpleNamespace(name_key="200"),
            3: SimpleNamespace(name_key="missing"), 4: SimpleNamespace(name_key=None)}
    display, names = _localized_item_names(rows, entries, english, lambda entry: sources[entry.path], None)
    assert display == {1: "Final"}
    assert names == {1: ("First", "Final", "Schwert", "سيف"), 2: ("Stiefel",), 3: (), 4: ()}


def test_empty_and_short_table_validation_is_not_bypassed_for_no_keys():
    assert select_paloc_entries(struct.pack("<I", 0), ()) == ()
    with pytest.raises(PalocFormatError, match="too short"):
        select_paloc_entries(b"\x00", ())


@pytest.mark.parametrize("container", [False, True])
@pytest.mark.parametrize("outer_compressed", [False, True])
def test_encrypted_validation_retains_exact_source_bytes(container, outer_compressed):
    from pathlib import Path

    from cdmw.core.archive_format import crypt_chacha20_filename, try_decrypt_archive_entry_data
    from cdmw.models import ArchiveEntry

    payload = encode_paloc(ENTRIES)
    data = _wrapped(payload) if container else payload
    stored = lz4.block.compress(data, store_size=False) if outer_compressed else data
    entry = ArchiveEntry(
        path="gamedata/stringtable/binary__/eng/item.paloc",
        pamt_path=Path("owned/0.pamt"), paz_file=Path("owned/0.paz"),
        offset=0, comp_size=len(stored), orig_size=len(data), paz_index=0,
        flags=(3 << 4) | (2 if outer_compressed else 0),
    )
    encrypted = crypt_chacha20_filename(stored, entry.basename)
    assert try_decrypt_archive_entry_data(entry, encrypted) == (stored, "ChaCha20")


@pytest.mark.parametrize("container", [False, True])
@pytest.mark.parametrize("outer_compressed", [False, True])
@pytest.mark.parametrize("damage", [
    "invalid_key", "invalid_text", "surrogate_text", "truncated_header",
    "key_overrun", "text_overrun", "count_small", "count_large",
])
def test_encrypted_validation_preserves_full_parser_error(container, outer_compressed, damage):
    from pathlib import Path

    from cdmw.core.archive_format import crypt_chacha20_filename, try_decrypt_archive_entry_data
    from cdmw.models import ArchiveEntry

    payload = _damaged_payload(damage)
    data = _wrapped(payload) if container else payload
    stored = lz4.block.compress(data, store_size=False) if outer_compressed else data
    entry = ArchiveEntry(
        path="gamedata/stringtable/binary__/eng/item.paloc",
        pamt_path=Path("owned/0.pamt"), paz_file=Path("owned/0.paz"),
        offset=0, comp_size=len(stored), orig_size=len(data), paz_index=0,
        flags=(3 << 4) | (2 if outer_compressed else 0),
    )
    encrypted = crypt_chacha20_filename(stored, entry.basename)
    with pytest.raises(PalocFormatError) as expected:
        parse_paloc(data)
    with pytest.raises(ValueError) as actual:
        try_decrypt_archive_entry_data(entry, encrypted)
    context = f"Could not validate decoded localization table {entry.path} ({entry.package_label})"
    assert str(actual.value) == f"{context}: {expected.value}"
