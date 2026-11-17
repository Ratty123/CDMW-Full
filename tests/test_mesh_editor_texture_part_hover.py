"""Pointing at a part in the Textures panel lights it up in the 3D view (2026-11-17).

Fredric: "If you hover over a part, it should highlight the model in the viewport so its
easier to find what is what to edit."
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.textures_panel import NO_PART, MeshEditorTexturesPanel, TextureThumbnailLoader

_APP = QApplication.instance() or QApplication([])


def _manifest() -> dict[str, object]:
    return {
        "textures": [
            {"label": "chest_d.dds", "role": "base_color", "file": {"path": "t0.dds", "sha256": "A" * 64},
             "material_indices_by_lod": [[0]]},
            {"label": "arms_n.dds", "role": "normal", "file": {"path": "t1.dds", "sha256": "B" * 64},
             "material_indices_by_lod": [[3]]},
        ],
        "state": {
            "skeleton": {"parts": [{"index": 0, "name": "Chest"}, {"index": 3, "name": "Arms"}]},
            "archive_refit_assets": [
                {"path": "character/model/upper.pac", "part_indices": [0]},
                {"path": "character/model/arms.pac", "part_indices": [3]},
            ],
        },
    }


def _settle() -> None:
    for _ in range(5):
        _APP.processEvents()


def test_the_panel_says_which_part_the_pointer_is_over(tmp_path: Path) -> None:
    panel = MeshEditorTexturesPanel(thumbnail_loader=TextureThumbnailLoader(decoder=lambda *_args: None))
    hovered: list[int] = []
    panel.part_hovered.connect(hovered.append)
    try:
        panel.resize(420, 400)
        panel.show()
        panel.set_manifest(_manifest(), session_root=tmp_path)
        arms = panel.part_item(3)
        arms.setExpanded(True)
        _settle()
        tree, viewport = panel.tree, panel.tree.viewport()

        def point_at(item) -> None:
            QTest.mouseMove(viewport, tree.visualItemRect(item).center())
            _settle()

        point_at(arms)  # a part's own row
        assert hovered == [3]
        point_at(arms.child(0))  # one of its textures: the same part, said once
        assert hovered == [3]
        point_at(panel.part_item(0))
        assert hovered == [3, 0]
        point_at(tree.topLevelItem(0))  # a file header is no part
        assert hovered == [3, 0, NO_PART]
        point_at(arms.child(0))
        assert hovered[-1] == 3
        # Below the rows, and off the list altogether, nothing is lit.
        QTest.mouseMove(viewport, QPoint(40, viewport.height() - 4))
        _settle()
        assert hovered[-1] == NO_PART
        point_at(arms)
        _APP.sendEvent(viewport, QEvent(QEvent.Type.Leave))
        assert hovered[-2:] == [3, NO_PART]
        # A hidden or cleared panel lights nothing either.
        point_at(arms)
        panel.hide()
        assert hovered[-2:] == [3, NO_PART]
        panel.show()
        point_at(panel.part_item(0))
        panel.clear()
        assert hovered[-2:] == [0, NO_PART]
    finally:
        panel.shutdown()
        panel.deleteLater()


@pytest.mark.parametrize("announced", [True, False])
def test_the_mesh_editor_sends_the_part_to_an_editor_that_takes_it(tmp_path: Path, announced: bool) -> None:
    from cdmw.services.mesh_rust_contract import (
        RUST_HOST_HIGHLIGHT_PART_CAPABILITY, RUST_MESH_EDIT_BACKEND, RUST_MESH_RENDERER)
    from tests.test_mesh_rust_embedding import _tab

    tab = _tab(tmp_path)
    sent: list[dict] = []
    try:
        tab.standalone_rust_process = SimpleNamespace(processId=lambda: 77)
        tab.standalone_native_host_frame.attach_child_window = lambda *_args: (True, "")
        tab._send_rust_message = lambda payload: sent.append(dict(payload)) or True
        dock = tab.standalone_workspace.textures_dock
        # No editor yet: nothing is sent, and nothing is remembered as lit.
        dock.part_hovered.emit(2)
        assert tab.standalone_rust_highlight_part_supported is False
        capabilities = ["embedded_child_window_v1", *([RUST_HOST_HIGHLIGHT_PART_CAPABILITY] if announced else [])]
        tab._handle_rust_hello({"renderer": RUST_MESH_RENDERER, "edit_backend": RUST_MESH_EDIT_BACKEND,
                                "capabilities": capabilities, "child_hwnd": 123, "embedded_parent_hwnd": 456})
        tab.live_edit.standalone_rust_ready = True
        sent.clear()
        dock.part_hovered.emit(1)
        dock.part_hovered.emit(1)
        dock.part_hovered.emit(4)
        dock.part_hovered.emit(NO_PART)
        highlights = [(m["event"], m["index"]) for m in sent if m.get("event") == "highlight_part"]
        if announced:
            # Once per change, and null when the pointer leaves; the selection is the editor's.
            assert highlights == [("highlight_part", 1), ("highlight_part", 4), ("highlight_part", None)]
            assert not any(m.get("event") == "select_parts" for m in sent)
        else:
            # An editor that does not know the message would end its session on it.
            assert highlights == []
        # A helper started again lights nothing until its own hello.
        tab._reset_rust_protocol_state()
        assert tab.standalone_rust_highlight_part_supported is False
        assert tab.standalone_rust_highlighted_part is None
    finally:
        tab.deleteLater()
        _APP.processEvents()
