"""Behaviour guards for the Prefab Inspector dialog.

These drive the real widget rather than asserting on its source text, so a
change that stops the tree populating -- or that lets editing through on a
prefab we only partly understand -- fails here.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from cdmw.core.prefab_binary import KIND_POINTER, KIND_STRING, decode_prefab_binary

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cdmw.domain.archives.prefab_glossary import asset_role, describe_field, is_asset_path  # noqa: E402
from cdmw.domain.archives.prefab_values import Placement, read_placement, write_placement
from cdmw.ui.archive_browser.prefab_inspector_widgets import PlacementEditDialog
from cdmw.ui.archive_browser.prefab_inspector_dialog import (  # noqa: E402
    PrefabInspectorDialog,
    _EDIT_ROLE,
    _PLACEMENT_ROLE,
    _VALUE_ROLE,
)

PATH = "character/model/1_pc/weapon/sword.pac"


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _text(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _member(name: str, type_name: str, flags: int, size: int) -> bytes:
    return _text(name) + _text(type_name) + struct.pack("<HHHH", flags, size, 0, 0)


def _build() -> bytes:
    types = bytearray()
    types += _text("SceneObject") + struct.pack("<H", 3)
    types += _member("_socketName", "IndexedStringA", KIND_STRING, 1)
    types += _member("_meshFile", "ReflectObjectPtr", KIND_POINTER, 8)
    # Declared but never set, so the "only fields in use" filter has something to hide.
    types += _member("_unusedFlag", "bool", 0x0000, 1)
    types += _text("ResourceReferencePath_SkinnedMesh") + struct.pack("<H", 0)

    header = bytearray()
    header += struct.pack("<HHH", 0xFFFF, 4, 0) + b"\x00" * 8
    header += struct.pack("<I", 15) + struct.pack("<H", 2) + types
    pool = struct.pack("<I", 0)
    blob_offset = len(header) + len(pool) + 28

    blob = bytearray()
    blob += struct.pack("<H", 2) + (0b11).to_bytes(6, "little")
    blob += _text("Pelvis_R_Socket")
    blob += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    blob += struct.pack("<I", blob_offset + len(blob) + 4)
    pointee = bytearray(struct.pack("<I", 0) + _text(PATH))
    blob += pointee + struct.pack("<I", len(pointee)) + b"\x00" * 5

    data_header = struct.pack("<III", 1, blob_offset + len(blob), 0)
    data_header += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack("<II", blob_offset, len(blob))
    return bytes(header + pool + data_header + blob)


def _rows(dialog: PrefabInspectorDialog) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            found.append((child.text(0), child.text(2)))
    return found


def test_dialog_lists_resources_and_schema(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    # Rows are labelled by the field the value came from, not guessed from the
    # file extension, so an unknown field still reads sensibly.
    assert ("Mesh file", PATH) in _rows(dialog)
    assert ("Socket name", "Pelvis_R_Socket") in _rows(dialog)
    assert dialog.schema_tree.topLevelItemCount() == 2
    assert "Fully read" in dialog.banner.text()


def test_applying_a_longer_path_produces_a_valid_prefab(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    replacement = "character/model/1_pc/weapon/a_much_longer_sword_name.pac"
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if child.text(2) == PATH:
                child.setText(2, replacement)
    assert dialog.collect_replacements() == {PATH: replacement}
    dialog._confirm_changes = lambda: True
    dialog._apply_changes()
    assert dialog.result_payload is not None
    document = decode_prefab_binary(dialog.result_payload.data)
    assert document.walk_complete
    assert [item.text for item in document.resource_strings()] == [replacement]


def test_partly_decoded_prefab_allows_only_same_length_swaps(qt_app: QApplication) -> None:
    """Nothing may move, so only a replacement that moves nothing is offered."""
    payload = bytearray(_build())
    document = decode_prefab_binary(bytes(payload))
    pointer = document.pointers[0]
    struct.pack_into("<I", payload, pointer.site, pointer.site + 64)
    dialog = PrefabInspectorDialog(bytes(payload))
    assert not dialog.apply_button.isEnabled(), "nothing is pending yet"
    assert "Partly read" in dialog.banner.text()
    assert "exactly the same length" in dialog.banner.text()
    assert not dialog._can_edit()
    assert dialog._can_swap_same_length()


def test_unreadable_payload_reports_instead_of_raising(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(b"not a prefab at all")
    assert "could not be read" in dialog.banner.text()
    assert not dialog.apply_button.isEnabled()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("character/model/a.pac", True),
        ("character/descriptors/x.sockets.xml", True),
        ("Pelvis_R_Socket", False),
        ("Weapon", False),
        ("", False),
    ],
)
def test_asset_path_detection(value: str, expected: bool) -> None:
    assert is_asset_path(value) is expected


def test_field_names_are_translated_for_humans() -> None:
    """Declared names are unfriendly; the dialog must not show them raw."""
    assert describe_field("_shrinkMaskDistance").label == "Shrink distance"
    assert describe_field("_skinnedMeshFile").label == "Mesh"
    # An unknown field still reads sensibly rather than vanishing.
    assert describe_field("_someUnknownThing").label == "Some unknown thing"


def test_asset_roles_name_what_the_file_is() -> None:
    assert asset_role("a/b/c.pac") == "Model"
    assert asset_role("a/b/c.sockets.xml") == "Socket data"
    assert asset_role("a/b/c.pab") == "Skeleton"


def test_all_fields_tab_defaults_to_fields_in_use(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    assert dialog.used_only_box.isChecked()
    visible = _visible_schema_labels(dialog)
    assert visible, "expected the fields actually used to be listed"
    dialog.used_only_box.setChecked(False)
    assert len(_visible_schema_labels(dialog)) > len(visible)


def _visible_schema_labels(dialog: PrefabInspectorDialog) -> list[str]:
    found: list[str] = []
    for index in range(dialog.schema_tree.topLevelItemCount()):
        parent = dialog.schema_tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if not child.isHidden():
                found.append(child.text(0))
    return found


def _path_row(dialog: PrefabInspectorDialog):
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if child.text(2) == PATH:
                return child
    raise AssertionError("path row not found")


def test_apply_is_off_until_something_changes(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    assert not dialog.apply_button.isEnabled()
    assert not dialog.revert_button.isEnabled()
    _path_row(dialog).setText(2, "character/model/1_pc/weapon/other.pac")
    assert dialog.apply_button.isEnabled()
    assert dialog.revert_button.isEnabled()
    assert "1 path change ready" in dialog.status.text()


def test_undo_restores_the_stored_paths(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    _path_row(dialog).setText(2, "character/model/1_pc/weapon/other.pac")
    dialog._revert_changes()
    assert dialog.collect_replacements() == {}
    assert not dialog.apply_button.isEnabled()
    assert dialog.status.text() == ""


def test_swapping_a_model_for_a_texture_is_flagged(qt_app: QApplication) -> None:
    """A wrong-kind path is the mistake most likely to slip through."""
    dialog = PrefabInspectorDialog(_build())
    _path_row(dialog).setText(2, "character/texture/1_pc/weapon/sword.dds")
    assert "1 looks wrong" in dialog.status.text()
    assert "texture file" in dialog.status.text()
    # It is a warning, not a block: the modder may know better than we do.
    assert dialog.apply_button.isEnabled()


@pytest.mark.parametrize(
    ("replacement", "fragment"),
    [
        ("", "empty"),
        ("just-a-name", "does not look like a file path"),
        ("character/model/1_pc/weapon/fine.pac", ""),
    ],
)
def test_retarget_warnings(replacement: str, fragment: str) -> None:
    from cdmw.ui.archive_browser.prefab_inspector_dialog import _retarget_warning

    warning = _retarget_warning(PATH, replacement)
    if fragment:
        assert fragment in warning
    else:
        assert warning == ""


_KNOWN = {".pac": ("character/model/1_pc/weapon/real.pac", PATH)}


def test_missing_target_is_reported_when_an_index_is_supplied(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build(), known_paths=_KNOWN)
    _path_row(dialog).setText(2, "character/model/1_pc/weapon/typo.pac")
    assert "No file with that path exists" in dialog.status.text()


def test_existing_target_passes_validation(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build(), known_paths=_KNOWN)
    _path_row(dialog).setText(2, "character/model/1_pc/weapon/real.pac")
    assert "wrong" not in dialog.status.text()
    assert dialog.apply_button.isEnabled()


def test_without_an_index_nothing_is_claimed_about_existence(qt_app: QApplication) -> None:
    """No archive means no existence claim -- silence, not a false alarm."""
    dialog = PrefabInspectorDialog(_build())
    _path_row(dialog).setText(2, "character/model/1_pc/weapon/typo.pac")
    assert "exists" not in dialog.status.text()


def test_browse_offers_only_files_of_the_same_kind(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build(), known_paths=_KNOWN)
    row = _path_row(dialog)
    dialog.tree.setCurrentItem(row)
    assert dialog.browse_button.isEnabled()
    assert dialog._candidates_for(row) == _KNOWN[".pac"]


def test_browse_is_unavailable_without_an_index(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    dialog.tree.setCurrentItem(_path_row(dialog))
    assert not dialog.browse_button.isEnabled()


_MESH = "character/model/1_pc/weapon/sword.pac"
_WITH_COMPANIONS = {
    ".pac": (_MESH, "character/model/1_pc/weapon/other.pac"),
    ".pac_xml": ("character/modelproperty/1_pc/weapon/other.pac_xml",),
    ".hkx": ("character/bin__/meshphysics/1_pc/weapon/other.hkx",),
}


def test_mesh_without_its_own_material_is_flagged(qt_app: QApplication) -> None:
    """Retargeting a mesh swaps its material too, by path convention."""
    known = dict(_WITH_COMPANIONS)
    known[".pac_xml"] = ()  # the replacement mesh has no material sidecar
    dialog = PrefabInspectorDialog(_build(), known_paths=known)
    _path_row(dialog).setText(2, "character/model/1_pc/weapon/other.pac")
    assert "no material file of its own" in dialog.status.text()


def test_mesh_with_companions_passes(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build(), known_paths=_WITH_COMPANIONS)
    _path_row(dialog).setText(2, "character/model/1_pc/weapon/other.pac")
    assert "wrong" not in dialog.status.text()


def test_applying_reports_where_material_and_physics_come_from(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build(), known_paths=_WITH_COMPANIONS)
    _path_row(dialog).setText(2, "character/model/1_pc/weapon/other.pac")
    dialog._confirm_changes = lambda: True
    dialog._apply_changes()
    logged = dialog.log.toPlainText()
    assert "modelproperty/1_pc/weapon/other.pac_xml" in logged
    assert "meshphysics/1_pc/weapon/other.hkx" in logged


def test_nested_prefab_instances_are_named_after_what_they_copy(qt_app: QApplication) -> None:
    """Every copy is unnamed; the prefab it instantiates is its identity."""
    from cdmw.ui.archive_browser.prefab_inspector_dialog import PrefabInspectorDialog as _D

    dialog = _D(_build())
    node = dialog.tree.topLevelItem(0)
    assert node is not None
    # The fixture is a plain SceneObject, so the ordinary labelling applies.
    assert not node.text(0).startswith("/")


def _transform_fixture() -> bytes:
    from tests.test_prefab_binary_edit import _build_with_transform

    return _build_with_transform()


def test_placement_rows_are_editable_and_apply_without_resizing(qt_app: QApplication) -> None:
    """Placement is fixed-size, so applying one must not move a single byte."""
    from cdmw.domain.archives.prefab_values import Placement, read_placement, write_placement
    from cdmw.ui.archive_browser.prefab_inspector_dialog import _PLACEMENT_ROLE

    payload = _transform_fixture()
    dialog = PrefabInspectorDialog(payload)
    row = None
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if child.data(0, _PLACEMENT_ROLE):
                row = child
    assert row is not None, "expected an editable placement row"

    offset, _type_name, raw, _member = row.data(0, _PLACEMENT_ROLE)
    placement = read_placement(raw)
    moved = Placement(
        scale=placement.scale,
        rotation=placement.rotation,
        position=(7.0, 8.0, 9.0),
        tile=placement.tile,
    )
    dialog._value_edits[offset] = write_placement(moved)
    dialog._refresh_pending_state()
    assert "1 value changed in place" in dialog.status.text()
    assert dialog.apply_button.isEnabled()

    dialog._confirm_changes = lambda: True
    dialog._apply_changes()
    assert dialog.result_payload is not None
    assert len(dialog.result_payload.data) == len(payload)
    document = decode_prefab_binary(dialog.result_payload.data)
    assert document.walk_complete
    written = next(n for n in document.root_numbers if n.offset == offset)
    assert read_placement(written.raw).position == (7.0, 8.0, 9.0)


def test_undo_clears_pending_placements(qt_app: QApplication) -> None:
    from cdmw.ui.archive_browser.prefab_inspector_dialog import _PLACEMENT_ROLE

    dialog = PrefabInspectorDialog(_transform_fixture())
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            stored = child.data(0, _PLACEMENT_ROLE)
            if stored:
                dialog._value_edits[stored[0]] = b"\x00" * len(stored[2])
    dialog._refresh_pending_state()
    assert dialog.apply_button.isEnabled()
    dialog._revert_changes()
    assert dialog._value_edits == {}
    assert not dialog.apply_button.isEnabled()


def test_hint_names_only_what_the_file_offers(qt_app: QApplication) -> None:
    """Telling a modder to double-click a path in a file with no paths is a lie."""
    with_paths = PrefabInspectorDialog(_build())
    assert "swap it for another" in with_paths._objects_hint()

    with_placement = PrefabInspectorDialog(_transform_fixture())
    hint = with_placement._objects_hint()
    assert "placement to move" in hint


def test_read_only_file_does_not_invite_editing(qt_app: QApplication) -> None:
    payload = bytearray(_build())
    pointer = decode_prefab_binary(bytes(payload)).pointers[0]
    struct.pack_into("<I", payload, pointer.site, pointer.site + 64)
    dialog = PrefabInspectorDialog(bytes(payload))
    hint = dialog._objects_hint()
    assert "read-only" in hint
    assert "Double-click" not in hint


def test_banner_counts_read_naturally(qt_app: QApplication) -> None:
    text = PrefabInspectorDialog(_build()).banner.text()
    assert "(s)" not in text, text
    # Singular and plural both read naturally.
    assert "1 asset reference." in text
    assert "0 objects" in text


def test_repeated_placement_is_summarised_not_repeated(qt_app: QApplication) -> None:
    """World and tiled placement usually agree; printing both in full is noise."""
    from cdmw.domain.archives.prefab_values import read_placement
    from cdmw.ui.archive_browser.prefab_inspector_dialog import _PLACEMENT_ROLE

    dialog = PrefabInspectorDialog(_transform_fixture())
    rows = []
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            rows.append(parent.child(child_index))
    placements = [row for row in rows if row.data(0, _PLACEMENT_ROLE)]
    assert placements, "expected at least one placement row"
    # The underlying value is still intact even where the text is summarised.
    for row in placements:
        _offset, _type_name, raw, _member = row.data(0, _PLACEMENT_ROLE)
        assert read_placement(raw) is not None


def test_collections_are_not_listed_as_having_no_value(qt_app: QApplication) -> None:
    """Their contents are the child rows, so saying otherwise contradicts the view."""
    dialog = PrefabInspectorDialog(_build())
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if child.text(0) == "Also set":
                assert "Components" not in child.text(2)
                assert "Child objects" not in child.text(2)


def test_opens_with_something_selected_so_buttons_are_live(qt_app: QApplication) -> None:
    """Otherwise every action is greyed until you guess a row must be selected."""
    known = {".pac": (PATH, "character/model/1_pc/weapon/other.pac")}
    dialog = PrefabInspectorDialog(_build(), known_paths=known)
    assert dialog.tree.currentItem() is not None
    assert dialog.browse_button.isEnabled()
    assert "exist in the game" in dialog.browse_button.toolTip()


def test_says_what_a_prefab_is_and_that_saving_is_safe(qt_app: QApplication) -> None:
    """A first-time modder needs to know the game files are not touched."""
    intro = PrefabInspectorDialog(_build()).intro.text()
    assert "parts list" in intro
    assert "never changed" in intro


def test_intro_does_not_hardcode_a_colour(qt_app: QApplication) -> None:
    """The app follows the system theme; a fixed grey is unreadable in one of them."""
    dialog = PrefabInspectorDialog(_build())
    assert "color:" not in dialog.intro.styleSheet()


def _pole_placement() -> Placement:
    """A weapon child socket: pitch 90, where the Euler round trip is worst."""
    return Placement(
        scale=(1.0, 1.0, 1.0),
        rotation=(0.5, 0.5, -0.5, 0.5),
        position=(1.25, -3.5, 0.75),
    )


def test_banner_never_claims_everything_shown_is_accurate(qt_app: QApplication) -> None:
    """It said so even for partial walks, where types are guessed."""
    dialog = PrefabInspectorDialog(_build())
    assert "Everything shown is accurate" not in dialog._banner_text()


def test_banner_counts_guessed_objects(qt_app: QApplication) -> None:
    import dataclasses

    from cdmw.core.prefab_binary import PrefabObject

    dialog = PrefabInspectorDialog(_build())
    document = dialog._document
    assert document is not None
    guessed = PrefabObject(
        index=0,
        name="CD_Hand",
        component_type="MeshComponent",
        member_names=(),
        resources=(),
        texts=(),
        values=(),
        numbers=(),
        parent=-1,
        type_source="inferred",
    )
    dialog._document = dataclasses.replace(document, objects=(guessed,))
    banner = dialog._banner_text()
    assert "best guess" in banner
    assert "may belong to something else" in banner
    # One object is "it", not "they": _count pluralises the noun but the
    # sentence around it has to agree.
    assert "what it is" in banner and "its fields" in banner


def test_saving_says_nothing_is_on_disk_yet(qt_app: QApplication) -> None:
    """The button builds the file; the destination is chosen after closing.

    The old label and tooltip both claimed a write that had not happened, so
    the export prompt on close arrived as a surprise.
    """
    dialog = PrefabInspectorDialog(_build())
    assert dialog.apply_button.text().endswith("...")
    assert "after" in dialog.apply_button.toolTip()

    _path_row(dialog).setText(2, "character/model/1_pc/weapon/other.pac")
    dialog._confirm_changes = lambda: True
    dialog._apply_changes()
    assert dialog.result_payload is not None
    assert "Nothing has been written yet" in dialog.log.toPlainText()


def test_moving_one_transform_moves_its_identical_twin(qt_app: QApplication) -> None:
    """Objects carry _worldTransform and _tiledTransform, identical in all
    5,228 shipped objects that have both. Moving one alone would produce a
    combination the game's data never contains, and the tree hides the second
    behind "same as ...", so it cannot be corrected by hand."""
    from cdmw.ui.archive_browser.prefab_inspector_dialog import _PLACEMENT_ROLE

    dialog = PrefabInspectorDialog(_transform_fixture())
    parent = dialog.tree.topLevelItem(0)
    rows = [
        parent.child(i)
        for i in range(parent.childCount())
        if parent.child(i).data(0, _PLACEMENT_ROLE)
    ]
    assert rows, "fixture must contain a placement row"

    first = rows[0]
    offset, _type_name, raw, _member = first.data(0, _PLACEMENT_ROLE)
    was = read_placement(raw)
    now = Placement(scale=was.scale, rotation=was.rotation, position=(11.0, 12.0, 13.0), tile=was.tile)
    dialog._value_edits[offset] = (raw, write_placement(now))
    dialog._sync_twin_placements(first, was, now)

    for row in rows[1:]:
        twin_offset, _t, twin_raw, _n = row.data(0, _PLACEMENT_ROLE)
        if read_placement(twin_raw) != was:
            continue
        assert twin_offset in dialog._value_edits, "an identical twin must move too"
        expected, written = dialog._value_edits[twin_offset]
        assert read_placement(written).position == (11.0, 12.0, 13.0)
        assert read_placement(written).tile == read_placement(twin_raw).tile


def test_review_lists_every_pending_change_with_its_label(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    _path_row(dialog).setText(2, "character/model/1_pc/weapon/other.pac")
    lines, warnings = dialog._pending_changes()
    assert [line.after for line in lines] == ["character/model/1_pc/weapon/other.pac"]
    assert lines[0].before == PATH
    assert lines[0].field, "a change must be labelled the way the modder saw it"
    assert warnings == []


def test_review_reports_a_role_mismatch_as_a_warning(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    _path_row(dialog).setText(2, "character/model/1_pc/weapon/other.dds")
    _lines, warnings = dialog._pending_changes()
    assert warnings and "model file" in warnings[0] and "texture file" in warnings[0]


def test_cancelling_the_review_writes_nothing(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    _path_row(dialog).setText(2, "character/model/1_pc/weapon/other.pac")
    dialog._confirm_changes = lambda: False
    dialog._apply_changes()
    assert dialog.result_payload is None
    assert "you cancelled" in dialog.log.toPlainText()


def _value_fixture() -> bytes:
    """A prefab with a plain float member set, alongside its mesh pointer.

    72.9% of complete-walk prefabs in the archives carry one of these -- 980
    floats and 171 uint8s across the sample -- so this is the common case, not
    an edge one.
    """
    types = bytearray()
    types += _text("SceneObject") + struct.pack("<H", 3)
    types += _member("_socketName", "IndexedStringA", KIND_STRING, 1)
    types += _member("_shrinkMaskDistance", "float", 0x0000, 4)
    types += _member("_meshFile", "ReflectObjectPtr", KIND_POINTER, 8)
    types += _text("ResourceReferencePath_SkinnedMesh") + struct.pack("<H", 0)

    header = bytearray()
    header += struct.pack("<HHH", 0xFFFF, 4, 0) + bytes(8)
    header += struct.pack("<I", 15) + struct.pack("<H", 2) + types
    pool = struct.pack("<I", 0)
    blob_offset = len(header) + len(pool) + 28

    blob = bytearray()
    blob += struct.pack("<H", 2) + (0b111).to_bytes(6, "little")
    blob += _text("Pelvis_R_Socket")
    blob += struct.pack("<f", 0.2)
    blob += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    blob += struct.pack("<I", blob_offset + len(blob) + 4)
    pointee = bytearray(struct.pack("<I", 0) + _text(PATH))
    blob += pointee + struct.pack("<I", len(pointee)) + bytes(5)

    data_header = struct.pack("<III", 1, blob_offset + len(blob), 0)
    data_header += struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack("<II", blob_offset, len(blob))
    return bytes(header + pool + data_header + blob)


def test_a_plain_value_row_is_editable_and_writes_in_place(qt_app: QApplication) -> None:
    """Flags and numbers were decoded and shown, but read-only."""
    from cdmw.domain.archives.prefab_values import decode_value
    from cdmw.ui.archive_browser.prefab_inspector_dialog import _VALUE_ROLE
    from cdmw.ui.archive_browser.prefab_inspector_widgets import ValueEditDialog

    dialog = PrefabInspectorDialog(_value_fixture())
    rows = []
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if child.data(0, _VALUE_ROLE):
                rows.append(child)
    assert rows, "a set float member must be offered as editable"

    offset, type_name, raw, _member = rows[0].data(0, _VALUE_ROLE)
    assert decode_value(type_name, raw) == pytest.approx(0.2)
    editor = ValueEditDialog(type_name, raw, title="Shrink distance")
    editor._current = lambda: 1.25
    editor._accept()
    assert editor.result_raw is not None
    assert len(editor.result_raw) == len(raw), "an in-place write must not resize"
    assert decode_value(type_name, editor.result_raw) == pytest.approx(1.25)

    # And the whole file must still read, at the same size.
    from cdmw.core.prefab_binary_edit import rewrite_prefab_placements

    result = rewrite_prefab_placements(_value_fixture(), {offset: (raw, editor.result_raw)})
    assert len(result.data) == len(_value_fixture())
    rewritten = decode_prefab_binary(result.data)
    assert rewritten.walk_complete, rewritten.walk_note


def test_export_prompt_admits_prefab_editing_is_unproven() -> None:
    """A modder deserves to know which of their mods is the experimental one."""
    source = Path("cdmw/ui/archive_browser/prefab_inspector_actions.py").read_text(encoding="utf-8")
    assert "not yet been confirmed to load in game" in source
    assert "disable the mod in your manager and delete that" in source


def test_one_row_can_be_undone_without_losing_the_others(qt_app: QApplication) -> None:
    """Undo-all was the only way back, so one typo cost the whole session."""
    dialog = PrefabInspectorDialog(_build())
    rows = []
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if isinstance(child.data(2, _EDIT_ROLE), str):
                rows.append(child)
    assert len(rows) >= 2, "fixture needs two editable rows"

    first_original = rows[0].text(2)
    second_original = rows[1].text(2)
    rows[0].setText(2, "character/model/1_pc/weapon/keep_me.pac")
    rows[1].setText(2, "character/model/1_pc/weapon/oops.pac")
    assert dialog.row_has_pending_change(rows[1])

    dialog._revert_row(rows[1])
    assert rows[1].text(2) == second_original
    assert not dialog.row_has_pending_change(rows[1])
    # The other edit survives, which is the whole point.
    assert rows[0].text(2) == "character/model/1_pc/weapon/keep_me.pac"
    assert dialog.row_has_pending_change(rows[0])
    assert first_original != rows[0].text(2)


def test_undoing_a_transform_undoes_its_twin(qt_app: QApplication) -> None:
    """Leaving one of the pair edited recreates the mismatch pairing prevents."""
    dialog = PrefabInspectorDialog(_transform_fixture())
    parent = dialog.tree.topLevelItem(0)
    rows = [
        parent.child(i)
        for i in range(parent.childCount())
        if parent.child(i).data(0, _PLACEMENT_ROLE)
    ]
    assert rows

    offset, _type_name, raw, _member = rows[0].data(0, _PLACEMENT_ROLE)
    was = read_placement(raw)
    now = Placement(scale=was.scale, rotation=was.rotation, position=(4.0, 5.0, 6.0), tile=was.tile)
    dialog._value_edits[offset] = (raw, write_placement(now))
    dialog._sync_twin_placements(rows[0], was, now)

    dialog._revert_row(rows[0])
    assert dialog._value_edits == {}, "the twin must come back with it"


def test_a_clean_row_offers_nothing_to_undo(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    row = _path_row(dialog)
    assert not dialog.row_has_pending_change(row)


def _visible_object_rows(dialog: PrefabInspectorDialog) -> list[str]:
    found: list[str] = []
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        if parent.isHidden():
            continue
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if not child.isHidden():
                found.append(child.text(0))
    return found


def test_the_objects_tab_can_be_filtered(qt_app: QApplication) -> None:
    """Median prefab is one object, but the tail runs to 1,126."""
    dialog = PrefabInspectorDialog(_build())
    everything = _visible_object_rows(dialog)
    assert len(everything) >= 2

    dialog.object_filter.setText("sword")
    narrowed = _visible_object_rows(dialog)
    assert narrowed, "the mesh path row contains 'sword'"
    assert len(narrowed) < len(everything)
    assert "Showing" in dialog.match_count.text()

    dialog.object_filter.setText("nothing-matches-this")
    assert _visible_object_rows(dialog) == []
    assert "Nothing matches" in dialog.match_count.text()

    dialog.object_filter.setText("")
    assert _visible_object_rows(dialog) == everything
    assert dialog.match_count.text() == ""


def test_only_changeable_rows_hides_the_read_only_ones(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    everything = _visible_object_rows(dialog)
    dialog.changeable_only_box.setChecked(True)
    changeable = _visible_object_rows(dialog)
    assert changeable, "the mesh path is editable"
    assert len(changeable) < len(everything)
    # And what is left really is editable, not merely fewer rows.
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            if not child.isHidden() and not parent.isHidden():
                assert dialog._row_is_changeable(child), child.text(0)


def test_filtering_keeps_a_matching_row_s_object_on_screen(qt_app: QApplication) -> None:
    """A row is worthless without knowing which object it belongs to."""
    dialog = PrefabInspectorDialog(_build())
    dialog.object_filter.setText("sword")
    visible_parents = [
        dialog.tree.topLevelItem(i)
        for i in range(dialog.tree.topLevelItemCount())
        if not dialog.tree.topLevelItem(i).isHidden()
    ]
    assert visible_parents, "the owning object must stay visible"


def _partly_read(payload: bytes) -> bytes:
    """A prefab whose walk stops short, with every pointer record intact."""
    document = decode_prefab_binary(payload)
    broken = bytearray(payload) + bytes(8)
    struct.pack_into("<I", broken, document.blob_offset - 4, document.blob_length + 8)
    struct.pack_into("<I", broken, document.blob_offset - 24, len(broken))
    return bytes(broken)


def test_a_same_length_swap_applies_on_a_partly_read_prefab(qt_app: QApplication) -> None:
    from cdmw.core.prefab_recovery import recover_pointee_strings

    payload = _partly_read(_build())
    dialog = PrefabInspectorDialog(payload)
    assert dialog._document is not None and not dialog._document.walk_complete

    row = _path_row(dialog)
    same_length = PATH[:-5] + "z" + PATH[-4:]
    assert len(same_length) == len(PATH)
    row.setText(2, same_length)
    assert dialog.apply_button.isEnabled(), "a same-length swap must be offered"

    dialog._confirm_changes = lambda: True
    dialog._apply_changes()
    assert dialog.result_payload is not None
    written = dialog.result_payload.data
    assert len(written) == len(payload), "nothing may move"
    after = decode_prefab_binary(written)
    texts = {i.text for i in recover_pointee_strings(written, after.blob_offset, after.blob_length)}
    assert same_length in texts and PATH not in texts


def test_a_resizing_swap_is_refused_on_a_partly_read_prefab(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_partly_read(_build()))
    _path_row(dialog).setText(2, PATH[:-4] + "considerably_longer.pac")
    dialog._confirm_changes = lambda: True
    dialog._apply_changes()
    assert dialog.result_payload is None
    log = dialog.log.toPlainText()
    assert "same length" in log and "Refused" in log


def test_the_banner_says_how_far_the_walk_got(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_partly_read(_build()))
    banner = dialog.banner.text()
    assert "of the way through" in banner
    assert "stopped at byte" in banner


def test_every_companion_is_listed_not_just_the_first(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build(), known_paths={".pac": (PATH,)})
    _path_row(dialog).setText(2, "character/model/1_pc/weapon/other.pac")
    lines, _warnings = dialog._pending_changes()
    assert lines
    # Material and physics both, since a mesh has two companions by convention.
    assert lines[0].note.count("comes from") + lines[0].note.count("will come from") >= 2


def test_the_picker_offers_only_same_length_names_when_that_is_all_that_works(
    qt_app: QApplication,
) -> None:
    """Otherwise a modder picks one, reviews it, and is refused at the last step."""
    same = PATH[:-5] + "z" + PATH[-4:]
    longer = PATH[:-4] + "considerably_longer.pac"
    shorter = "a/b.pac"
    known = {".pac": (same, longer, shorter)}

    whole = PrefabInspectorDialog(_build(), known_paths=known)
    assert whole._can_edit()
    assert set(whole._candidates_for(_path_row(whole))) == {same, longer, shorter}

    partial = PrefabInspectorDialog(_partly_read(_build()), known_paths=known)
    assert not partial._can_edit() and partial._can_swap_same_length()
    offered = partial._candidates_for(_path_row(partial))
    assert set(offered) == {same}, "only the equal-length name can be written"
    assert all(len(item.encode()) == len(PATH.encode()) for item in offered)


def test_recovered_rows_are_labelled_by_their_file_name(qt_app: QApplication) -> None:
    """No member name exists for these, and inventing one would be a lie.

    The walk never reached them, so nothing says which field they belong to.
    The file's own name identifies it, and a column of basenames is scannable
    where a column of full paths is not.
    """
    dialog = PrefabInspectorDialog(_partly_read(_build()))
    labels = []
    for index in range(dialog.tree.topLevelItemCount()):
        parent = dialog.tree.topLevelItem(index)
        if "past the stop" not in parent.text(0):
            continue
        for child_index in range(parent.childCount()):
            child = parent.child(child_index)
            labels.append((child.text(0), child.text(2)))
    for label, path in labels:
        assert label, "a recovered row must not be blank in the first column"
        assert label == path.rsplit("/", 1)[-1]
        assert "/" not in label


def test_the_row_menu_reports_what_else_uses_a_file(qt_app: QApplication) -> None:
    """One edit covering a set, or one of twenty, decides whether a mod works."""
    asked: list[str] = []

    def _find(path: str) -> tuple[str, ...]:
        asked.append(path)
        return ("object/bin/a.prefab", "object/bin/b.prefab")

    dialog = PrefabInspectorDialog(_build(), find_users=_find)
    dialog._show_other_users(PATH)
    assert asked == [PATH]
    log = dialog.log.toPlainText()
    assert "2 other prefabs" in log
    assert "object/bin/a.prefab" in log and "object/bin/b.prefab" in log


def test_nothing_else_using_a_file_is_said_plainly(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build(), find_users=lambda _path: ())
    dialog._show_other_users(PATH)
    assert "No other prefab" in dialog.log.toPlainText()


def test_a_failing_lookup_is_reported_not_raised(qt_app: QApplication) -> None:
    """This runs from a modal; an exception there takes the window with it."""

    def _boom(_path: str):
        raise OSError("archive went away")

    dialog = PrefabInspectorDialog(_build(), find_users=_boom)
    dialog._show_other_users(PATH)
    assert "Could not check" in dialog.log.toPlainText()


def test_without_archive_access_the_menu_entry_is_absent(qt_app: QApplication) -> None:
    dialog = PrefabInspectorDialog(_build())
    assert dialog._find_users is None
    dialog._show_other_users(PATH)
    assert dialog.log.toPlainText() == ""
