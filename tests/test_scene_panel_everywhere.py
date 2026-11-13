"""The Scene panel beside the other 3D previews (P5, 2026-11-13).

Model Library, Create New Item's preview, Character Finder and the reference
preview window get the panel through cdmw.ui.preview.scene_panel_binding: it
lists the files and parts of the package the host applied, sends the ticks to
the host as hidden parts, and shows only while the host is shown and the model
has more than one part. Those previews cannot open the Mesh Editor, so the
panel there has the visibility actions only.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

from cdmw.ui.preview.scene_panel_binding import attach_scene_panel

SWORD = "character/model/cd_phm_02_sword_0015.pac"
SHEATH = "character/model/cd_phm_02_sword_0015_in.pac"


class _Controller(QObject):
    package_applied = Signal(str, int)


class _Host(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.controller = _Controller()
        self.hidden: list[list[int]] = []

    def set_hidden_source_submeshes(self, indices) -> bool:
        self.hidden.append(list(indices))
        return True


def _batch(index: int, path: str, local: int) -> dict:
    return {"index": index, "material_name": f"part {index}", "editor_identity": {
        "source_model_path": path, "source_submesh_index": index, "source_local_submesh_index": local}}


def _package(tmp_path, batches) -> str:
    folder = tmp_path / f"package-{len(batches)}"
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps({"batches": batches}), encoding="utf-8")
    return str(folder)


def _window():
    QApplication.instance() or QApplication([])
    window = QWidget()
    layout = QVBoxLayout(window)
    stack = QStackedWidget()
    host, other = _Host(), QWidget()
    stack.addWidget(other)
    stack.addWidget(host)
    layout.addWidget(stack, 1)
    binding = attach_scene_panel(host, stack)
    stack.setCurrentWidget(host)
    window.show()
    QApplication.processEvents()
    return window, stack, host, other, binding


def test_the_panel_lists_the_applied_package_and_hides_parts_in_the_host(tmp_path) -> None:
    window, stack, host, other, binding = _window()
    panel = binding.panel
    host.controller.package_applied.emit(
        _package(tmp_path, [_batch(0, SWORD, 0), _batch(1, SWORD, 1), _batch(2, SHEATH, 0)]), 1)
    QApplication.processEvents()
    assert panel.isVisible() and panel.parentWidget().objectName() == "ScenePanelRow"
    assert stack.parentWidget() is panel.parentWidget()  # beside the stack, in its place
    panel.set_hidden_indices((2,))
    assert host.hidden[-1] == [2]
    # Visibility actions only: these previews do not open the Mesh Editor.
    labels = [label for label, _call, _enabled in panel.context_actions(None)]
    assert "Open in Mesh Editor" not in labels and not panel.edit_set_button.isVisible()
    # The panel follows the 3D page.
    stack.setCurrentWidget(other)
    QApplication.processEvents()
    assert not panel.isVisible()
    stack.setCurrentWidget(host)
    QApplication.processEvents()
    assert panel.isVisible()
    window.close()


def test_a_single_part_model_shows_no_panel(tmp_path) -> None:
    window, _stack, host, _other, binding = _window()
    host.controller.package_applied.emit(_package(tmp_path, [_batch(0, SWORD, 0)]), 1)
    QApplication.processEvents()
    assert not binding.panel.isVisible()
    window.close()


def test_ticks_carry_over_when_the_same_files_load_again(tmp_path) -> None:
    window, _stack, host, _other, binding = _window()
    batches = [_batch(0, SWORD, 0), _batch(1, SWORD, 1)]
    host.controller.package_applied.emit(_package(tmp_path, batches), 1)
    binding.panel.set_hidden_indices((1,))
    host.hidden.clear()
    (tmp_path / "again").mkdir()
    (tmp_path / "again" / "manifest.json").write_text(json.dumps({"batches": batches}), encoding="utf-8")
    host.controller.package_applied.emit(str(tmp_path / "again"), 2)
    assert host.hidden == [[1]] and binding.panel.hidden_indices == (1,)
    window.close()
