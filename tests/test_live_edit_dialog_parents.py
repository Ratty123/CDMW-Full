"""File choosers and message boxes opened by Live Edit get a widget as their parent.

The Live Edit component is a QObject, not a QWidget. Qt refuses it as a dialog
parent ("missing signature"), which broke Import Replacement in alpha.6.
"""
from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.mesh_editor import replacement_flow, tab_rust_editor, tab_rust_process
from cdmw.ui.mesh_editor.live_edit import LiveEditComponent


class _Host(QWidget):
    def __init__(self, target) -> None:
        super().__init__()
        self._target = target

    def _current_target_entry(self):
        return self._target


def _session(replacement_state=None):
    shadow = SimpleNamespace(_session=lambda _id: SimpleNamespace(replacement_state=replacement_state))
    return SimpleNamespace(shadow_service=shadow, shadow_session_id="s1")


def test_import_replacement_opens_the_chooser_over_a_widget(monkeypatch):
    QApplication.instance() or QApplication([])
    target = SimpleNamespace(identity="pac:hero.pac", basename="hero.pac")
    host = _Host(target)
    component = LiveEditComponent(host)
    session = _session()
    component.standalone_rust_authoring_session = session
    component.standalone_rust_closing = False
    monkeypatch.setattr(replacement_flow, "archive_workflow_dependency_context", lambda _owner, _target: {})
    monkeypatch.setattr(replacement_flow, "source_path_override", None)
    parents = []

    def chooser(parent, caption, start, file_filter):
        # The real binding raises "missing signature" for anything but a QWidget or None.
        assert parent is None or isinstance(parent, QWidget), f"{type(parent).__name__} is not a widget"
        parents.append(parent)
        assert file_filter == "Mesh models (*.obj *.dae *.gltf *.glb *.fbx)"
        return "D:/models/hero.glb", ""

    monkeypatch.setattr(replacement_flow.QFileDialog, "getOpenFileName", staticmethod(chooser))
    event = replacement_flow.prepare_replacement_event(component, session, {"command": "replacement_choose"})
    assert parents == [host]
    assert event["arguments"]["source_path"] == "D:/models/hero.glb"
    host.deleteLater()


def test_dialog_parent_passes_widgets_and_none_through():
    QApplication.instance() or QApplication([])
    widget = QWidget()
    assert replacement_flow._dialog_parent(widget) is widget
    assert replacement_flow._dialog_parent(None) is None
    assert replacement_flow._dialog_parent(SimpleNamespace()) is None
    widget.deleteLater()


_DIALOG_CALLS = {
    "QFileDialog": {"getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory"},
    "QMessageBox": {"information", "warning", "critical", "question", "about"},
}


def test_the_component_code_never_passes_itself_as_a_dialog_parent():
    """``self`` in the editor mixins is the component; dialogs need ``self.window()``."""

    offenders = []
    for module in (tab_rust_editor, tab_rust_process):
        for node in ast.walk(ast.parse(inspect.getsource(module))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)):
                continue
            calls = _DIALOG_CALLS.get(node.func.value.id, set())
            if node.func.attr in calls and node.args and isinstance(node.args[0], ast.Name) \
                    and node.args[0].id == "self":
                offenders.append(f"{module.__name__}:{node.lineno}")
    assert offenders == []
