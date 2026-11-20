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


def test_flows_can_keep_their_pickers_on_the_component():
    """Hair, archive refit and cloth collision store their pickers on ``tab``, the component.

    Those are host names, and a read-only host property made the first Hair entry,
    Choose from Archives in Refit and the cloth collision picker fail with
    "property ... has no setter".
    """

    QApplication.instance() or QApplication([])
    host = QWidget()
    component = LiveEditComponent(host)
    for name in ("_hair_context_preparation", "_archive_refit_picker", "_cloth_collision_picker", "_hair_picker"):
        marker = object()
        setattr(component, name, marker)
        assert getattr(host, name) is marker and getattr(component, name) is marker
    host.deleteLater()


def test_the_hair_setup_choice_reaches_the_component():
    """Hair Tools setup leaves its character and context on the tab; the hair flow reads them from the component."""

    from cdmw.ui.mesh_editor.hair_flow import hair_character_for_target

    QApplication.instance() or QApplication([])
    host = QWidget()
    component = LiveEditComponent(host)
    host._pending_hair_character = "Oongka"
    host._pending_hair_context = "context"
    assert component._pending_hair_context == "context"
    assert hair_character_for_target(component, SimpleNamespace(path="unrelated/path.pac")) == "Oongka"
    component._pending_hair_context = None
    assert host._pending_hair_context is None
    host.deleteLater()


def _flows_called_with_the_component():
    """(module, function) pairs the component's own code calls with ``self`` as the first argument."""

    found = set()
    for module in (tab_rust_editor, tab_rust_process):
        tree = ast.parse(inspect.getsource(module))
        imported = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cdmw.ui.mesh_editor."):
                for alias in node.names:
                    imported[alias.asname or alias.name] = (node.module, alias.name)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in imported
                    and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "self"):
                found.add(imported[node.func.id])
    return sorted(found)


def _tab_names(tree):
    """Names read from ``tab``, and names the module itself assigns on ``tab`` (state it keeps there)."""

    reads, writes = set(), set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in {"getattr", "hasattr"} and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name) and node.args[0].id == "tab"
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
            reads.add(node.args[1].value)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "tab":
            (writes if isinstance(node.ctx, ast.Store) else reads).add(node.attr)
    return reads, writes


def test_flows_that_receive_the_component_read_only_declared_names():
    """A flow that reads a host name the component does not declare gets ``None`` back.

    ``archive_session_dependencies`` was missing, so Fit to body and Hair Tools no
    longer saw the session's own archive files (same class as the PR 38 pickers).
    """

    import importlib

    from cdmw.ui.mesh_editor.live_edit import component as component_module

    known = set(component_module.HOST_NAMES) | set(component_module.STATE_NAMES) | set(dir(LiveEditComponent))
    flows = _flows_called_with_the_component()
    assert ("cdmw.ui.mesh_editor.hair_flow", "prepare_hair_event") in flows
    assert ("cdmw.ui.mesh_editor.refit_reference_preparation", "prepare_refit_fit_event") in flows
    missing = []
    for module_name, function_name in flows:
        tree = ast.parse(inspect.getsource(importlib.import_module(module_name)))
        _, kept_by_module = _tab_names(tree)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == function_name and node.args.args \
                    and node.args.args[0].arg == "tab":
                reads, _ = _tab_names(node)
                missing.extend(
                    f"{module_name}.{function_name}: {name}" for name in sorted(reads - known - kept_by_module)
                )
    assert missing == []


def test_the_session_dependencies_reach_the_hair_and_refit_flows():
    QApplication.instance() or QApplication([])
    host = QWidget()
    component = LiveEditComponent(host)
    marker = object()
    host.archive_session_dependencies = marker
    assert component.archive_session_dependencies is marker
    host.deleteLater()
