"""Values the Prefab Inspector can now change: more numeric types, each element of
a fixed-size array, any text, and an emptied string.

Every write here goes through a writer that already existed: fixed-size values
in place (nothing moves), text through the relocating path rewriter. What is new
is which values are offered, so the tests check both that the offer is made
and that the bytes written are exactly the ones asked for.
"""

from __future__ import annotations

import struct

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.core.prefab_binary_edit import (
    PrefabEditError,
    PrefabPathEdit,
    rewrite_prefab_paths,
    rewrite_prefab_placements,
)
from cdmw.domain.archives.prefab_values import (
    Placement,
    array_elements,
    decode_value,
    describe_value,
    editable_kind,
    encode_value,
    write_placement,
)
from cdmw.ui.archive_browser.prefab_inspector_dialog import (
    PrefabInspectorDialog,
)
from cdmw.ui.archive_browser.prefab_inspector_editing import (
    PLACEMENT_ROLE,
)
from tests.test_prefab_binary import _assemble, _typedef
from tests.test_prefab_inspector_dialog import PATH, _build, _path_row


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _transform(x: float) -> bytes:
    return write_placement(Placement((1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0), (x, 2.0, 3.0)))


def _transform_array(*xs: float) -> bytes:
    """A root holding one ``Transform[]`` of len(xs) whole transforms."""
    root = _typedef("SceneObject", ("_transforms", "Transform", 3, 40, 0x1000))

    def blob_for(_base: int) -> bytearray:
        blob = bytearray(struct.pack("<H", 2) + (0b1).to_bytes(6, "little"))
        blob += b"\x00" + struct.pack("<I", len(xs)) + b"".join(_transform(x) for x in xs)
        return blob

    return _assemble((root,), blob_for)


# -- value types -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_name", "raw", "value"),
    [
        ("int", struct.pack("<i", -7), -7),
        ("ItemKey", struct.pack("<I", 4_000_000_000), 4_000_000_000),
    ],
)
def test_int_and_item_key_are_whole_numbers_at_their_stored_width(type_name, raw, value) -> None:
    assert editable_kind(type_name, raw) == "int"
    assert decode_value(type_name, raw) == value
    assert encode_value(type_name, raw, value) == raw


def test_an_item_key_refuses_a_value_it_cannot_hold() -> None:
    with pytest.raises(ValueError, match="does not fit"):
        encode_value("ItemKey", struct.pack("<I", 1), -1)


@pytest.mark.parametrize("count", [2, 4])
def test_float_vectors_round_trip(count: int) -> None:
    type_name = f"float{count}"
    values = tuple(float(index) + 0.5 for index in range(count))
    raw = struct.pack(f"<{count}f", *values)
    assert editable_kind(type_name, raw) == type_name
    assert decode_value(type_name, raw) == values
    assert encode_value(type_name, raw, values) == raw
    assert describe_value(type_name, raw).startswith("(0.5, 1.5")
    with pytest.raises(ValueError, match=f"exactly {count}"):
        encode_value(type_name, raw, values[:-1])


def test_a_type_whose_layout_is_unconfirmed_stays_read_only() -> None:
    """Colour byte order is not established, so no editor is offered for it."""
    assert editable_kind("Color", bytes(4)) == ""
    assert editable_kind("int", bytes(8)) == "", "a width that disagrees is never guessed at"


def test_an_array_splits_into_whole_elements_only() -> None:
    raw = _transform(1.0) + _transform(2.0)
    elements = array_elements("Transform[]", raw)
    assert [(kind, start) for kind, start, _raw in elements] == [("Transform", 0), ("Transform", 40)]
    assert array_elements("Transform[]", raw[:-4]) == (), "a ragged array is left whole"
    assert array_elements("Transform", raw) == (), "only arrays are split"
    assert array_elements("Mystery[]", raw) == (), "an element of unknown width is left whole"


# -- writers ---------------------------------------------------------------------


def test_one_element_of_an_array_is_written_in_place() -> None:
    data = _transform_array(1.0, 1.0)
    document = decode_prefab_binary(data)
    (array,) = document.root_numbers
    assert array.type_name == "Transform[]"
    second = array.offset + 40

    moved = _transform(9.0)
    result = rewrite_prefab_placements(data, {second: (_transform(1.0), moved)}).data

    assert len(result) == len(data)
    assert result[second : second + 40] == moved
    assert result[:second] == data[:second] and result[second + 40 :] == data[second + 40 :]
    assert decode_prefab_binary(result).walk_complete


def test_an_array_write_that_straddles_two_elements_is_refused() -> None:
    data = _transform_array(1.0, 1.0)
    (array,) = decode_prefab_binary(data).root_numbers
    with pytest.raises(PrefabEditError, match="No decoded value"):
        rewrite_prefab_placements(data, {array.offset + 20: _transform(9.0)})


def test_an_offset_inside_a_scalar_value_is_refused() -> None:
    data = _build(tint=True)
    (tint,) = decode_prefab_binary(data).root_numbers
    with pytest.raises(PrefabEditError, match="No decoded value"):
        rewrite_prefab_placements(data, {tint.offset + 2: b"\x00\x00"})


def test_an_empty_replacement_clears_the_string_it_names() -> None:
    data = _build()
    (socket,) = [item for item in decode_prefab_binary(data).all_strings() if item.text == "Pelvis_R_Socket"]

    result = rewrite_prefab_paths(data, [PrefabPathEdit(socket.offset, socket.text, "")])

    after = decode_prefab_binary(result.data)
    assert after.walk_complete
    assert [item.text for item in after.all_strings()] == ["", PATH]
    assert len(result.data) == len(data) - len("Pelvis_R_Socket")


def test_an_empty_value_in_a_mapping_still_means_leave_it() -> None:
    data = _build()
    assert rewrite_prefab_paths(data, {"Pelvis_R_Socket": ""}).data == data


# -- the Inspector ----------------------------------------------------------------


def _row(dialog: PrefabInspectorDialog, text: str):
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if child.text(2) == text:
                return child
    raise AssertionError(f"no row shows {text!r}")


def test_a_socket_name_is_editable_text_and_applies(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    row = _row(dialog, "Pelvis_R_Socket")
    assert dialog._row_is_changeable(row)

    row.setText(2, "Hand_R_Socket_Longer")
    assert dialog._warning_for("Pelvis_R_Socket", "Hand_R_Socket_Longer") == "", "text has no path shape"
    dialog._confirm_changes = lambda: True
    dialog._apply_changes()

    document = decode_prefab_binary(dialog.result_payload.data)
    assert [item.text for item in document.all_strings()] == ["Hand_R_Socket_Longer", PATH]


def test_the_file_row_is_selected_first_so_choose_file_is_live(qt_app: QApplication) -> None:
    known = {".pac": (PATH, "character/model/1_pc/weapon/other.pac")}
    dialog = PrefabInspectorDialog(_build(), known_paths=known)
    assert dialog.tree.currentItem() is _path_row(dialog)


def test_emptying_a_path_row_clears_it_with_a_warning(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    _path_row(dialog).setText(2, "")

    assert dialog.collect_path_edits()[0].new_text == ""
    lines, warnings = dialog._pending_changes()
    assert [line.after for line in lines] == ["(empty)"]
    assert warnings and "empty" in warnings[0]


def test_each_transform_in_an_array_gets_its_own_placement_row(qt_app: QApplication) -> None:
    data = _transform_array(1.0, 1.0)
    dialog = PrefabInspectorDialog(data)
    (array,) = decode_prefab_binary(data).root_numbers
    rows = [
        dialog.tree.topLevelItem(index).child(child_index)
        for index in range(dialog.tree.topLevelItemCount())
        for child_index in range(dialog.tree.topLevelItem(index).childCount())
    ]
    placed = [row for row in rows if row.data(0, PLACEMENT_ROLE)]
    assert [row.data(0, PLACEMENT_ROLE)[0] for row in placed] == [array.offset, array.offset + 40]
    assert [row.text(0)[-1] for row in placed] == ["1", "2"]

    # Two equal points are still two points: moving one must not move the other,
    # unlike the world/tiled transform pair.
    first = placed[0]
    was = Placement((1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0), (1.0, 2.0, 3.0))
    now = Placement((1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0), (9.0, 2.0, 3.0))
    dialog._value_edits[array.offset] = (_transform(1.0), write_placement(now))
    dialog._sync_twin_placements(first, was, now)
    assert array.offset + 40 not in dialog._value_edits

    dialog._confirm_changes = lambda: True
    dialog._apply_changes()
    written = dialog.result_payload.data
    assert written[array.offset : array.offset + 40] == write_placement(now)
    assert written[array.offset + 40 : array.offset + 80] == _transform(1.0)
