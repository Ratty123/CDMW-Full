from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_dialog_callbacks_d3d11_loading_part_01 import (
    _d3d11_loading_step_011,
)
from cdmw.ui.archive_browser.static_replacement_dialog_mesh_diagnostics_callbacks import (
    create_alignment_mesh_diagnostics_callbacks,
)


class _QProcess:
    NotRunning = 0


class _DeletedProcess(_QProcess):
    def state(self) -> int:
        raise RuntimeError(
            "libshiboken: Internal C++ object (PySide6.QtCore.QProcess) already deleted."
        )


class _QThread:
    def isRunning(self) -> bool:  # noqa: N802
        return False


class _PreviewModel:
    pass


class _Cursor:
    def __init__(self) -> None:
        self._position = 0

    def position(self) -> int:
        return self._position

    def setPosition(self, position: int) -> None:  # noqa: N802
        self._position = int(position)


class _TextWidget:
    def __init__(self) -> None:
        self.text = ""
        self.cursor = _Cursor()

    def textCursor(self) -> _Cursor:  # noqa: N802
        return self.cursor

    def setPlainText(self, text: str) -> None:  # noqa: N802
        self.text = text

    def setTextCursor(self, cursor: _Cursor) -> None:  # noqa: N802
        self.cursor = cursor


def test_loading_watchdog_clears_a_deleted_qprocess_without_raising() -> None:
    process = _DeletedProcess()
    state = SimpleNamespace(
        alignment_d3d11_state={
            "process": process,
            "thread": None,
            "queued_model": None,
            "pending_model": None,
            "active_package": None,
        },
        QProcess=_QProcess,
        QThread=_QThread,
        ModelPreviewData=_PreviewModel,
        Path=Path,
        _alignment_d3d11_request_active_helper=lambda **values: any(values.values()),
    )

    _d3d11_loading_step_011(state)

    assert state._alignment_d3d11_request_active() is False
    assert state.alignment_d3d11_state["process"] is None


def test_auto_diagnostics_tolerates_a_deleted_qprocess() -> None:
    process = _DeletedProcess()
    d3d11_state = {"process": process}
    text_widget = _TextWidget()

    def append_safe(lines: list[str], label: str, callback: object) -> None:
        lines.append(f"{label}: {callback()}")  # type: ignore[operator]

    callbacks = create_alignment_mesh_diagnostics_callbacks(
        {
            "List": list,
            "ModelPreviewData": _PreviewModel,
            "Path": Path,
            "QApplication": object,
            "QPlainTextEdit": _TextWidget,
            "QProcess": _QProcess,
            "_alignment_d3d11_preview_active": lambda: False,
            "_alignment_mesh_edit_tab_active": lambda: False,
            "_alignment_preview_source_face_limit": lambda: 0,
            "_mesh_edit_raw_preview_active": lambda: False,
            "_mesh_editor_diagnostics_append_safe_value_helper": append_safe,
            "_mesh_editor_diagnostics_copied_status_helper": lambda: "copied",
            "_mesh_editor_diagnostics_manifest_lines": lambda _package: [],
            "_mesh_editor_diagnostics_model_lines": lambda *_args, **_kwargs: [],
            "_mesh_editor_diagnostics_record_text_helper": (
                lambda _state, _text, *, auto: True
            ),
            "_mesh_editor_diagnostics_source_mesh_lines": (
                lambda *_args, **_kwargs: []
            ),
            "_mesh_editor_diagnostics_text_widget_helper": (
                lambda state: state["text_widget"]
            ),
            "_source_index_is_enabled_renderable": lambda _index: True,
            "alignment_d3d11_preview_status_label": None,
            "alignment_d3d11_preview_host": object(),
            "alignment_d3d11_state": d3d11_state,
            "dialog": object(),
            "embedded_alignment_builder": True,
            "entry": SimpleNamespace(path="test.pac", basename="test.pac"),
            "highlighted_source_indices": set(),
            "json": json,
            "mesh_edit_enabled_checkbox": None,
            "mesh_edit_scope_combo": None,
            "mesh_edit_show_vertices_checkbox": None,
            "mesh_edit_tool_combo": None,
            "mesh_editor_diagnostics_state": {"text_widget": text_widget},
            "obj_path": Path("test.obj"),
            "preview_mode_combo": None,
            "preview_performance_label": None,
            "preview_render_mode_combo": None,
            "preview_renderer_combo": None,
            "preview_visible_mode_combo": None,
            "replacement_mesh_base_for_mapping": None,
            "replacement_mesh_for_mapping": None,
            "replacement_preview_model": None,
            "selected_source_part": {},
            "self": object(),
            "texture_files_for_mapping": (),
            "texture_sets": {},
            "time": time,
            "prompt_shell_context": {"alignment_d3d11_state": d3d11_state},
        }
    )

    callbacks._refresh_mesh_editor_diagnostics(auto=True)

    assert d3d11_state["process"] is None
    assert "process_state: deleted" in text_widget.text
