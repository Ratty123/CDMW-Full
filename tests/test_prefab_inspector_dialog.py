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

from cdmw.ui.archive_browser.prefab_inspector_dialog import (  # noqa: E402
    PrefabInspectorDialog,
    _looks_like_asset_path,
    _value_label,
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
    types += _text("SceneObject") + struct.pack("<H", 2)
    types += _member("_socketName", "IndexedStringA", KIND_STRING, 1)
    types += _member("_meshFile", "ReflectObjectPtr", KIND_POINTER, 8)
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
    assert ("file path", PATH) in _rows(dialog)
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
    assert _looks_like_asset_path(value) is expected
    assert _value_label(value) == ("file path" if expected else "text")
