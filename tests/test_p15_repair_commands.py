"""Section 8.7 E2 and the mirror half of E6: the Mesh Editor's mirrored commands per document.

Real Mesh Editor tabs (the real mixin and its protocol channel); only the helper
launch is stubbed, as in the parking repair tests.
"""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QWidget

from cdmw.ui.commands import registry as registry_module
from cdmw.ui.commands.registry import CommandRegistry
from cdmw.ui.mesh_editor.editor_commands import registry_id, set_command_owner
from tests.test_p15_repair_parking import _ready_tab

_ROWS = [{"id": "tool.move", "label": "Move", "keys": ["G"], "reason": ""}]


def _two_documents(tmp_path, monkeypatch):
    host = QWidget()
    host.command_registry = CommandRegistry(host)
    first = _ready_tab(tmp_path / "a", monkeypatch)
    second = _ready_tab(tmp_path / "b", monkeypatch)
    for tab in (first[0], second[0]):
        tab.setParent(host)
    return host, first, second


def test_a_palette_command_goes_to_the_shown_document(tmp_path, monkeypatch) -> None:
    host, (a, *_, ), (b, *_, ) = _two_documents(tmp_path, monkeypatch)
    registry = host.command_registry
    a_lines, b_lines = [], []
    monkeypatch.setattr(a, "_send_rust_message", lambda line: a_lines.append(line) or True)
    monkeypatch.setattr(b, "_send_rust_message", lambda line: b_lines.append(line) or True)
    a._mirror_rust_commands(list(_ROWS))
    b._mirror_rust_commands(list(_ROWS))
    set_command_owner(registry, a)  # the documents view showed A
    # B reported last; the command still goes to the document that is shown.
    b._mirror_rust_commands(list(_ROWS))
    registry.run(registry_id("tool.move"))
    assert len(a_lines) == 1 and not b_lines


def test_closing_one_document_keeps_the_other_s_commands(tmp_path, monkeypatch) -> None:
    host, (a, *_, ), (b, *_, ) = _two_documents(tmp_path, monkeypatch)
    registry = host.command_registry
    a._mirror_rust_commands(list(_ROWS))
    b._mirror_rust_commands(list(_ROWS))
    set_command_owner(registry, b)
    a._clear_rust_commands()  # A's helper closed
    assert registry_id("tool.move") in registry
    b._clear_rust_commands()
    assert registry_id("tool.move") not in registry


def test_an_edit_outside_a_window_with_a_registry_still_mirrors(monkeypatch) -> None:
    """Browse's edit component and detached tool windows find the application's registry."""

    from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin

    registry = CommandRegistry()
    monkeypatch.setattr(registry_module, "command_registry", lambda: registry)
    component = SimpleNamespace(window=lambda: QWidget())
    assert MeshEditorRustProcessMixin._rust_command_registry(component) is registry
    no_window = SimpleNamespace()
    assert MeshEditorRustProcessMixin._rust_command_registry(no_window) is registry


def test_showing_a_document_tab_offers_its_commands(tmp_path, monkeypatch) -> None:
    """The real documents view: switching tabs makes the shown document the owner."""

    from cdmw.ui.mesh_editor.editor_commands import _mirrors
    from tests.test_p15_repair_documents import _view

    view = _view(tmp_path)
    host = QWidget()
    host.command_registry = CommandRegistry(host)
    view.setParent(host)
    first = view.active
    second = view.add_document()
    for document in (first, second):
        document._mirror_rust_commands(list(_ROWS))
    view.tab_bar.setCurrentIndex(0)
    assert _mirrors(host.command_registry).shown().owner() is first.live_edit
    view.tab_bar.setCurrentIndex(1)
    assert _mirrors(host.command_registry).shown().owner() is second.live_edit
