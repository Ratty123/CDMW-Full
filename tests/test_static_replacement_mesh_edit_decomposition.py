from __future__ import annotations

import ast
import inspect
from pathlib import Path

from cdmw.ui.archive_browser import static_replacement_dialog_mesh_edit_callbacks as facade
from cdmw.ui.archive_browser import static_replacement_mesh_edit_builder as builder
from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT


ROOT = Path(__file__).resolve().parents[1]
OWNER_ROOT = ROOT / "cdmw" / "ui" / "archive_browser"


class _Signal:
    def __init__(self) -> None:
        self.slots: list[object] = []

    def connect(self, slot: object) -> None:
        self.slots.append(slot)


class _Widget:
    def __init__(self) -> None:
        self.toggled = _Signal()
        self.clicked = _Signal()
        self.triggered = _Signal()
        self.currentIndexChanged = _Signal()
        self.valueChanged = _Signal()
        self.editingFinished = _Signal()
        self.timeout = _Signal()

    def addStretch(self, *_args: object) -> None:
        pass

    def addLayout(self, *_args: object) -> None:
        pass

    def addWidget(self, *_args: object) -> None:
        pass

    def setSingleShot(self, *_args: object) -> None:
        pass

    def setInterval(self, *_args: object) -> None:
        pass


class _Tabs:
    def __init__(self, mesh_tab: object) -> None:
        self._mesh_tab = mesh_tab

    def currentIndex(self) -> int:
        return 0

    def widget(self, _index: int) -> object:
        return self._mesh_tab

    def tabText(self, _index: int) -> str:
        return "Mesh Editing"


def _context() -> dict[str, object]:
    widget = _Widget()
    mesh_tab = object()
    context: dict[str, object] = {
        "QTimer": lambda _parent=None: _Widget(),
        "control_tabs": _Tabs(mesh_tab),
        "dialog": _Widget(),
        "mesh_edit_tab": mesh_tab,
        "mesh_edit_button_row": _Widget(),
        "mesh_edit_layout": _Widget(),
        "mesh_edit_reset_part_button": _Widget(),
        "mesh_edit_full_reset_button": _Widget(),
        "mesh_edit_status_label": _Widget(),
        "_mesh_edit_pending_live_normals_initial_state_helper": lambda: None,
    }
    for name in (
        "mesh_edit_enabled_checkbox",
        "mesh_edit_show_vertices_checkbox",
        "mesh_edit_mirror_checkbox",
        "mesh_edit_scope_combo",
        "mesh_edit_part_combo",
        "mesh_edit_tool_combo",
        "mesh_edit_delete_mode_combo",
        "mesh_edit_falloff_combo",
        "mesh_edit_iterations_spin",
        "mesh_edit_selection_mode_combo",
        "mesh_edit_selection_depth_combo",
        "mesh_edit_radius_spin",
        "mesh_edit_strength_spin",
        "mesh_edit_clear_selection_button",
        "mesh_edit_select_part_button",
        "mesh_edit_invert_selection_button",
        "mesh_edit_grow_selection_button",
        "mesh_edit_shrink_selection_button",
        "mesh_edit_smooth_selection_button",
        "mesh_edit_subdivide_selection_button",
        "mesh_edit_refine_smooth_selection_button",
        "mesh_edit_split_selection_button",
        "mesh_edit_delete_faces_button",
        "mesh_edit_undo_button",
        "mesh_edit_redo_button",
        "morph_slider_create_button",
        "morph_slider_import_action",
        "morph_slider_add_action",
        "morph_slider_reload_action",
        "morph_slider_reset_button",
        "morph_slider_bake_button",
    ):
        context[name] = widget if name == "mesh_edit_enabled_checkbox" else _Widget()
    return context


def test_factory_preserves_public_order_identity_and_patch_seam(monkeypatch) -> None:
    context = _context()
    captured: list[object] = []
    original_create_state = builder.create_mesh_edit_state
    sentinel = object()

    def capture_state(values: dict[str, object], module_globals: dict[str, object]):
        state = original_create_state(values, module_globals)
        captured.append(state)
        return state

    monkeypatch.setattr(builder, "create_mesh_edit_state", capture_state)
    monkeypatch.setattr(facade, "MeshEditCommandWorker", sentinel)
    callbacks = facade.create_alignment_mesh_edit_callbacks(context)

    assert tuple(vars(callbacks)) == builder.PUBLIC_CALLBACK_NAMES
    assert len(builder.PUBLIC_CALLBACK_NAMES) == len(set(builder.PUBLIC_CALLBACK_NAMES)) == 102
    enabled_signal = context["mesh_edit_enabled_checkbox"].toggled
    assert enabled_signal.slots == [callbacks._mesh_edit_enabled_toggled]
    assert tuple(inspect.signature(callbacks._mesh_edit_apply_preview_payload).parameters) == (
        "payload",
    )
    assert tuple(inspect.signature(callbacks._mesh_editor_action_bar_action_requested).parameters) == (
        "action",
    )
    assert captured[0].MeshEditCommandWorker is sentinel
    captured[0]._mesh_edit_current_tool = lambda: "grab"
    captured[0]._mesh_edit_target_mode_for_tool_helper = lambda tool: f"mode:{tool}"
    assert callbacks._mesh_edit_target_mode_for_tool() == "mode:grab"


def test_mesh_edit_owners_are_bounded_static_python() -> None:
    owner_paths = {
        Path(factory.__module__.replace(".", "/") + ".py")
        for factory in builder._CALLBACK_FACTORIES
    }
    owner_paths.update(
        {
            Path("cdmw/ui/archive_browser/static_replacement_mesh_edit_builder.py"),
            Path("cdmw/ui/archive_browser/static_replacement_mesh_edit_context.py"),
            Path("cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py"),
        }
    )
    assert len(owner_paths) == 17
    for relative_path in sorted(owner_paths):
        path = ROOT / relative_path
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert len(source.splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT, relative_path
        assert "exec(" not in source
        assert "compile(" not in source
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.end_lineno - node.lineno + 1 <= 150, (
                    relative_path,
                    node.name,
                )
