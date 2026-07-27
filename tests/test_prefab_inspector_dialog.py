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
    assert "Fully decoded" in dialog.banner.text()


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
    assert "not fully understand" in dialog.banner.text()


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
