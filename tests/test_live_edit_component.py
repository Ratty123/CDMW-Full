"""P4 V2: the embedded Mesh Editor is a component with its own state and a declared host."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from cdmw.ui.mesh_editor import tab_rust_editor, tab_rust_process
from cdmw.ui.mesh_editor.live_edit import (
    HOST_NAMES,
    STATE_NAMES,
    LiveEditComponent,
    moved_method_names,
)


def _names_used_by_the_editor_code() -> tuple[set[str], set[str]]:
    """(names its code assigns on self, names it reads or calls on self)."""

    stored, read = set(), set()
    for module in (tab_rust_editor, tab_rust_process):
        tree = ast.parse(inspect.getsource(module))
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name.startswith("MeshEditor")]:
            for node in ast.walk(cls):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
                    (stored if isinstance(node.ctx, ast.Store) else read).add(node.attr)
                if (isinstance(node, ast.Call) and getattr(node.func, "id", "") in {"getattr", "hasattr"}
                        and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "self"
                        and isinstance(node.args[1], ast.Constant)):
                    read.add(node.args[1].value)
    return stored, read


def test_the_component_reads_only_what_its_host_declares():
    stored, read = _names_used_by_the_editor_code()
    methods = set(moved_method_names())
    own = {name for name in vars(LiveEditComponent) if not name.startswith("__")}
    assert set(STATE_NAMES) == stored - methods, "STATE_NAMES must list exactly what the editor code assigns"
    undeclared = read - stored - methods - own - set(HOST_NAMES)
    assert undeclared == set(), f"the editor reads host names it does not declare: {sorted(undeclared)}"
    assert not set(HOST_NAMES) & set(STATE_NAMES)


def test_state_names_cannot_shadow_qt():
    qt = set(dir(QWidget))
    assert not qt & set(STATE_NAMES)
    assert not qt & set(moved_method_names())


class _SecondHost(QWidget):
    """The smallest host that is not the Mesh Editor tab."""

    status_message_requested = Signal(str, bool)
    switch_item_piece_requested = Signal(int)

    def __init__(self, tmp_path: Path) -> None:
        super().__init__()
        from cdmw.ui.mesh_editor.rust_host import RustMeshEditorHostFrame

        self.settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
        self.theme_key = "graphite"
        self.item_set_contexts = ()
        self.standalone_controller = None
        self.standalone_status_label = QLabel(self)
        self.standalone_native_host_frame = RustMeshEditorHostFrame(self)
        self.messages: list[tuple[str, bool]] = []
        self.status_message_requested.connect(lambda text, error: self.messages.append((text, error)))
        self.live_edit = LiveEditComponent(self)
        self.live_edit._initialize_rust_editor_runtime_state()


def test_a_second_host_carries_the_component(tmp_path):
    app = QApplication.instance() or QApplication([])
    host = _SecondHost(tmp_path)
    component = host.live_edit
    try:
        assert component.host is host and component.parent() is host
        assert not component.is_ready and not component.is_busy and not component.finish_accepted
        assert component.standalone_rust_process is None
        # Its state is its own: the host has none of it.
        assert "standalone_rust_process" not in vars(host)
        # Opening a controller without a mesh session is refused through the host's status.
        component.open(SimpleNamespace(active_session_id=""))
        app.processEvents()
        assert host.messages and host.messages[-1][1] is True
        assert host.standalone_status_label.text() == host.messages[-1][0]
        assert not component.is_busy
        component.close_edit("test closed")
    finally:
        host.deleteLater()
        app.processEvents()


def test_the_tab_forwards_state_and_methods_to_its_component():
    from cdmw.ui.mesh_editor.tab import MeshEditorTab

    assert isinstance(vars(MeshEditorTab)["standalone_rust_process"], property)
    assert "MeshEditorRustEditorMixin" not in {base.__name__ for base in MeshEditorTab.__mro__}
    for name in moved_method_names():
        assert name in vars(MeshEditorTab), name
