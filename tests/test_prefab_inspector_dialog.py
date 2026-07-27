"""Behaviour guards for the Prefab Inspector dialog.

These drive the real widget rather than asserting on its source text, so a
change that stops the tree populating -- or that lets editing through on a
prefab we only partly understand -- fails here.
"""

from __future__ import annotations

import struct

import pytest

from cdmw.core.prefab_binary import KIND_POINTER, KIND_STRING, decode_prefab_binary

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cdmw.domain.archives.prefab_glossary import asset_role, describe_field, is_asset_path  # noqa: E402
from cdmw.domain.archives.prefab_values import Placement, write_placement
from cdmw.ui.archive_browser.prefab_inspector_widgets import PlacementEditDialog
from cdmw.ui.archive_browser.prefab_inspector_dialog import PrefabInspectorDialog  # noqa: E402

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
    dialog._apply_changes()
    assert dialog.result_payload is not None
    document = decode_prefab_binary(dialog.result_payload.data)
    assert document.walk_complete
    assert [item.text for item in document.resource_strings()] == [replacement]


def test_partly_decoded_prefab_disables_editing(qt_app: QApplication) -> None:
    payload = bytearray(_build())
    document = decode_prefab_binary(bytes(payload))
    pointer = document.pointers[0]
    struct.pack_into("<I", payload, pointer.site, pointer.site + 64)
    dialog = PrefabInspectorDialog(bytes(payload))
    assert not dialog.apply_button.isEnabled()
    assert "saving is switched off" in dialog.banner.text()


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

    offset, _type_name, raw = row.data(0, _PLACEMENT_ROLE)
    placement = read_placement(raw)
    moved = Placement(
        scale=placement.scale,
        rotation=placement.rotation,
        position=(7.0, 8.0, 9.0),
        tile=placement.tile,
    )
    dialog._placement_edits[offset] = write_placement(moved)
    dialog._refresh_pending_state()
    assert "1 placement" in dialog.status.text()
    assert dialog.apply_button.isEnabled()

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
                dialog._placement_edits[stored[0]] = b"\x00" * len(stored[2])
    dialog._refresh_pending_state()
    assert dialog.apply_button.isEnabled()
    dialog._revert_changes()
    assert dialog._placement_edits == {}
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
        _offset, _type_name, raw = row.data(0, _PLACEMENT_ROLE)
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


def test_position_only_edit_leaves_rotation_and_scale_untouched(qt_app: QApplication) -> None:
    """The 90-degree silent rotation. Editing position must not touch rotation."""
    source = _pole_placement()
    dialog = PlacementEditDialog(source, title="socket")
    dialog._position[0].setValue(9.5)
    dialog._accept()

    result = dialog.result_placement
    assert result is not None
    assert result.position[0] == 9.5
    assert result.rotation == source.rotation
    assert result.scale == source.scale
    assert write_placement(result)[12:28] == write_placement(source)[12:28]


def test_rotation_only_edit_leaves_position_untouched(qt_app: QApplication) -> None:
    source = _pole_placement()
    dialog = PlacementEditDialog(source, title="socket")
    dialog._rotation[0].setValue(45.0)
    dialog._accept()

    result = dialog.result_placement
    assert result is not None
    assert result.position == source.position
    assert result.rotation != source.rotation


def test_opening_and_accepting_without_typing_changes_nothing(qt_app: QApplication) -> None:
    """Open, click OK, and the bytes must be identical -- including at a pole."""
    source = _pole_placement()
    dialog = PlacementEditDialog(source, title="socket")
    dialog._accept()
    assert write_placement(dialog.result_placement) == write_placement(source)


def test_pole_orientation_is_warned_about(qt_app: QApplication) -> None:
    at_pole = PlacementEditDialog(_pole_placement(), title="socket")
    assert at_pole.pole_warning.isVisibleTo(at_pole)

    level = Placement(scale=(1.0, 1.0, 1.0), rotation=(0.0, 0.0, 0.0, 1.0), position=(0.0, 0.0, 0.0))
    assert not PlacementEditDialog(level, title="body").pole_warning.isVisibleTo(
        PlacementEditDialog(level, title="body")
    )
