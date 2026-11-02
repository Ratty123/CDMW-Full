"""Closed static-table records: owned fixtures, constrained edits and an opt-in corpus walk."""
import struct

import pytest

from cdmw.core._compact_static_schema import READERS, TABLE_READERS
from cdmw.core.static_table_records import (
    DECODED_TABLES,
    EDITABLE_FIELDS,
    StaticTableError,
    apply_field_edits,
    decode_static_table,
    root_ops,
    table_kind_for_stem,
)
from tests.compact_item_fixtures import table, text


def inventory_row(key, name, default, maximum):
    """InventoryInfo written field by field from the serializer order, not from the schema."""
    return (text(name) + struct.pack("<H", key)
            + bytes([0, 0, 1, 1, 1])                 # blocked, one-only, moveable, save count, check type
            + struct.pack("<HIH", default, 0, maximum)
            + bytes(4) + bytes(4) + bytes(4)         # pushable types, excluded types, move data
            + _local_string() + _local_string()      # alert text, inventory name
            + struct.pack("<II", 0, 0)               # NPC cooltime min/max
            + bytes(4))                              # collection item list


def _local_string():
    # LocalStringInfo: u8 category, u64 key, then its text.
    return b"\0" + bytes(8) + text("")


def wanted_row(key, name, use_target, increase):
    return text(name) + struct.pack("<HBBQ", key, 0, use_target, increase)


def _minimal(op, out, overrides, path=()):
    """Encode the smallest record a reader accepts: empty lists, absent options."""
    code = op[0]
    if code == "raw":
        out += bytes(op[1])
    elif code == "text":
        out += text("")
    elif code == "seq":
        for child in op[1:]:
            _minimal(child, out, overrides, path)
    elif code == "call":
        _minimal(READERS[op[1]], out, overrides, path)
    elif code in ("optional", "presence"):
        out += b"\0"
    elif code == "array":
        out += bytes(op[1])
    elif code == "repeat":
        for _ in range(op[1]):
            _minimal(op[2], out, overrides, path)
    elif code == "field":
        if not path and op[2] in overrides:
            out += overrides[op[2]]
        else:
            _minimal(op[3], out, overrides, path + (op[2],))
    elif code in ("variant", "tagged"):
        for tag, case in sorted(op[-1].items()):
            trial = bytearray()
            try:
                if code == "tagged":
                    _minimal(op[2], trial, overrides, path)
                _minimal(case, trial, overrides, path)
            except LookupError:
                continue
            out += tag.to_bytes(op[1], "little") + trial
            return
        raise LookupError("no encodable case")
    elif code == "unsupported":
        raise LookupError("unsupported")
    else:
        raise AssertionError(code)


def _key_width(kind):
    for op in root_ops(kind):
        if op[0] == "field" and op[2] == "_key":
            return op[3][1]
    raise AssertionError(kind)


def minimal_record(kind, key, name):
    width = _key_width(kind)
    out = bytearray()
    _minimal(READERS[TABLE_READERS[kind]], out, {"_stringKey": text(name), "_key": key.to_bytes(width, "little")})
    return bytes(out), width


@pytest.mark.parametrize("kind", sorted(DECODED_TABLES))
def test_every_decoded_table_reads_an_owned_minimal_record(kind):
    raw_a, width = minimal_record(kind, 3, f"{kind}_A")
    raw_b, _ = minimal_record(kind, 9, f"{kind}_B")
    body, header = table([(3, raw_a), (9, raw_b)], width=width)

    decoded = decode_static_table(kind, header, body)

    assert decoded.refused == ()
    assert [(r.key, r.name) for r in decoded.records] == [(3, f"{kind}_A"), (9, f"{kind}_B")]
    assert decoded.records[1].start == len(raw_a) and decoded.records[1].end == len(body)


def test_inventory_fields_decode_from_a_hand_written_row():
    body, header = table([(1, inventory_row(1, "Money", 20, 240)), (2, inventory_row(2, "Character", 50, 240))], width=2)

    rows = decode_static_table("inventory", header, body).records

    assert [(r.name, r.field("_defaultSlotCount").value, r.field("_maxSlotCount").value) for r in rows] == [
        ("Money", 20, 240), ("Character", 50, 240)]
    assert rows[0].field("_defaultSlotCount").shape == "u16"


def test_slot_edit_rewrites_only_its_two_bytes_and_keeps_the_directory():
    body, header = table([(1, inventory_row(1, "Money", 20, 240)), (2, inventory_row(2, "Character", 50, 240))], width=2)

    edit = apply_field_edits("inventory", header, body, {(2, "_defaultSlotCount"): 120, (2, "_maxSlotCount"): 480})

    assert edit.header == header and len(edit.body) == len(body)
    changed = [i for i, (a, b) in enumerate(zip(body, edit.body)) if a != b]
    character = decode_static_table("inventory", header, edit.body).records[1]
    spans = [character.field(name) for name in ("_defaultSlotCount", "_maxSlotCount")]
    assert all(any(f.start <= i < f.end for f in spans) for i in changed)
    assert (character.field("_defaultSlotCount").value, character.field("_maxSlotCount").value) == (120, 480)
    assert [(c.key, c.field, c.before, c.after) for c in edit.changes] == [
        (2, "_defaultSlotCount", 50, 120), (2, "_maxSlotCount", 240, 480)]


@pytest.mark.parametrize("edits, message", [
    ({(2, "_defaultSlotCount"): 300}, "default slots exceed the maximum"),
    ({(2, "_maxSlotCount"): 70000}, "outside"),
    ({(2, "_maxSlotCount"): "big"}, "not an integer"),
    ({(5, "_maxSlotCount"): 10}, "no row with key 5"),
    ({(2, "_keyGuideLocalStringInfo"): 1}, "not an editable field"),
    ({}, "No edits"),
])
def test_unsafe_slot_edits_are_refused(edits, message):
    body, header = table([(2, inventory_row(2, "Character", 50, 240))], width=2)
    with pytest.raises(StaticTableError, match=message):
        apply_field_edits("inventory", header, body, edits)


def test_bounty_increase_is_a_u64_edit():
    body, header = table([(262, wanted_row(262, "Wanted_Hernand", 0, 100))], width=2)

    edit = apply_field_edits("wantedinfo", header, body, {(262, "_increasePrice"): 900_000_000_000})

    row = decode_static_table("wantedinfo", header, edit.body).records[0]
    assert row.field("_increasePrice").value == 900_000_000_000 and row.field("_increasePrice").shape == "u64"


def test_character_scale_is_stored_as_a_finite_float():
    raw, width = minimal_record("characterinfo", 1004085, "Golem")
    body, header = table([(1004085, raw)], width=width)

    edit = apply_field_edits("characterinfo", header, body, {(1004085, "_characterScale"): 1.5})
    row = decode_static_table("characterinfo", header, edit.body).records[0]
    assert struct.unpack("<f", row.field("_characterScale").value.to_bytes(4, "little"))[0] == 1.5
    with pytest.raises(StaticTableError, match="outside"):
        apply_field_edits("characterinfo", header, body, {(1004085, "_characterScale"): float("nan")})


def test_tables_without_rules_and_unknown_stems_are_refused():
    body, header = table([(3, minimal_record("regioninfo", 3, "Region")[0])], width=_key_width("regioninfo"))
    with pytest.raises(StaticTableError, match="no editable fields"):
        apply_field_edits("regioninfo", header, body, {(3, "_key"): 4})
    with pytest.raises(StaticTableError, match="no closed record schema"):
        decode_static_table("bitmapposition", header, body)
    assert table_kind_for_stem("skillinfo") == "skill"
    assert table_kind_for_stem("characterinfo.dlc_01") == "characterinfo"
    assert table_kind_for_stem("bitmapposition") is None


def test_a_row_the_schema_refuses_is_reported_not_guessed():
    body, header = table([(1, inventory_row(1, "Money", 20, 240)),
                          (2, inventory_row(2, "Character", 50, 240) + bytes(8))], width=2)

    decoded = decode_static_table("inventory", header, body)

    assert [r.key for r in decoded.records] == [1]
    assert decoded.refused[0][0] == 2 and decoded.row_count == 2


def test_every_editable_field_has_its_rule_width_in_the_schema():
    for kind, rules in EDITABLE_FIELDS.items():
        shapes = {op[2]: op[3] for op in root_ops(kind) if op[0] == "field"}
        for name, rule in rules.items():
            shape = shapes[name]
            while shape[0] == "call" or (shape[0] == "seq" and len(shape) == 2):
                shape = READERS[shape[1]] if shape[0] == "call" else shape[1]
            assert shape == ("raw", rule.width), (kind, name, shape)


@pytest.mark.real_game
def test_every_installed_row_decodes_or_is_refused_by_a_closed_variant():
    from tools.placement_studio import corpus
    from cdmw.core.archive_extraction import read_archive_entry_data

    if not corpus.game_root().is_dir():
        pytest.skip("needs the installed game")
    root = "gamedata/binarystaticinfo__/bin/"
    pairs = {}
    for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
        path = corpus.normalize_game_path(entry.path)
        if path.startswith(root) and path.endswith((".staticinfoheader", ".staticinfobody")):
            stem, _, ext = path[len(root):].rpartition(".")
            if table_kind_for_stem(stem):
                pairs.setdefault(stem, {})[ext] = read_archive_entry_data(entry)[0]
    # Only variant refusals are acceptable; a size-bound refusal would mean a limit is too low.
    closed = ("This compact static variant has not been qualified.",
              "Unsupported compact static discriminant.")
    decoded = refused = 0
    for stem, pair in sorted(pairs.items()):
        if not pair.get("staticinfobody"):
            continue
        result = decode_static_table(table_kind_for_stem(stem), pair["staticinfoheader"], pair["staticinfobody"])
        decoded += len(result.records)
        refused += len(result.refused)
        assert all(reason in closed for _key, reason in result.refused), (stem, result.refused[:3])
    assert decoded > 100000 and refused < decoded // 100


def test_service_writes_the_edited_pair_as_loose_files(tmp_path):
    from cdmw.services.structured_sidecar_edit_service import StaticTableEditRequest, write_static_table_edits

    body, header = table([(2, inventory_row(2, "Character", 50, 240))], width=2)
    result = write_static_table_edits(StaticTableEditRequest(
        "inventory.dlc_01", header, body, {(2, "_maxSlotCount"): 500}, tmp_path / "out"))

    assert result.header_path.read_bytes() == header
    edited = decode_static_table("inventory", header, result.body_path.read_bytes()).records[0]
    assert edited.field("_maxSlotCount").value == 500
    assert result.body_path.name == "inventory.dlc_01.staticinfobody"
    assert result.proof_lines[-1] == "Row 2 _maxSlotCount: 240 -> 500"
    with pytest.raises(ValueError, match="no closed record schema"):
        write_static_table_edits(StaticTableEditRequest("bitmapposition", header, body, {(2, "_key"): 1}, tmp_path))


def test_an_edit_refuses_a_row_whose_inline_key_differs_from_the_header():
    body, header = table([(2, inventory_row(3, "Character", 50, 240))], width=2)
    with pytest.raises(StaticTableError, match="different inline key"):
        apply_field_edits("inventory", header, body, {(2, "_maxSlotCount"): 300})


def test_stems_with_path_components_are_refused(tmp_path):
    from cdmw.services.structured_sidecar_edit_service import StaticTableEditRequest, write_static_table_edits

    body, header = table([(2, inventory_row(2, "Character", 50, 240))], width=2)
    for stem in ("inventory.dlc_01/../../x", "inventory/../x", "..", "inventory.x"):
        assert table_kind_for_stem(stem) is None
        with pytest.raises(ValueError, match="no closed record schema"):
            write_static_table_edits(StaticTableEditRequest(stem, header, body, {(2, "_maxSlotCount"): 9}, tmp_path / "out"))
    assert not (tmp_path / "out").exists() and not list(tmp_path.parent.glob("x.static*"))


def test_a_member_read_in_two_parts_shows_both_parts():
    width = _key_width("fieldinfo")
    out = bytearray()
    # Both reads of the member get the same override: each part must come back as its own u32.
    _minimal(READERS[TABLE_READERS["fieldinfo"]], out, {
        "_stringKey": text("Field"), "_key": (4).to_bytes(width, "little"), "_startSectorIndex": struct.pack("<I", 7)})
    body, header = table([(4, bytes(out))], width=width)

    field = decode_static_table("fieldinfo", header, body).records[0].field("_startSectorIndex")

    assert field.shape == "u32+u32" and field.value == (7, 7) and field.end - field.start == 8
