from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_dialog_callback_factories import (
    create_alignment_d3d11_package_lifecycle_callbacks,
    create_alignment_mesh_diagnostics_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_diagnostics import (
    mesh_editor_diagnostics_append_safe_value,
    mesh_editor_diagnostics_copied_status,
    mesh_editor_diagnostics_initial_state,
    mesh_editor_diagnostics_record_text,
    mesh_editor_diagnostics_set_text_widget,
    mesh_editor_diagnostics_text_widget,
)


def test_mesh_editor_diagnostics_copied_status_preserves_copy() -> None:
    assert mesh_editor_diagnostics_copied_status() == "Mesh Editor diagnostics copied."


def test_mesh_editor_diagnostics_state_tracks_text_widget() -> None:
    state = mesh_editor_diagnostics_initial_state()
    widget = object()

    assert state == {"text_widget": None, "last_text": ""}
    assert mesh_editor_diagnostics_text_widget(state) is None

    mesh_editor_diagnostics_set_text_widget(state, widget)

    assert mesh_editor_diagnostics_text_widget(state) is widget


def test_mesh_editor_diagnostics_record_text_skips_repeated_auto_update() -> None:
    state = mesh_editor_diagnostics_initial_state()

    assert mesh_editor_diagnostics_record_text(state, "first", auto=True) is True
    assert mesh_editor_diagnostics_record_text(state, "first", auto=True) is False
    assert mesh_editor_diagnostics_record_text(state, "first", auto=False) is True
    assert mesh_editor_diagnostics_record_text(state, "second", auto=True) is True
    assert state["last_text"] == "second"


def test_mesh_editor_diagnostics_append_safe_value_records_values_and_errors() -> None:
    lines: list[str] = []

    mesh_editor_diagnostics_append_safe_value(lines, "ok", lambda: 7)
    mesh_editor_diagnostics_append_safe_value(lines, "bad", lambda: (_ for _ in ()).throw(ValueError("nope")))

    assert lines == ["ok: 7", "bad: <error: nope>"]


class _FakeCursor:
    def __init__(self) -> None:
        self._position = 0

    def position(self) -> int:
        return self._position

    def setPosition(self, position: int) -> None:
        self._position = int(position)


class _FakeTextEdit:
    def __init__(self) -> None:
        self.text = ""
        self._cursor = _FakeCursor()

    def textCursor(self) -> _FakeCursor:
        return self._cursor

    def setPlainText(self, text: str) -> None:
        self.text = text

    def setTextCursor(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def toPlainText(self) -> str:
        return self.text


class _FakeValueWidget:
    def __init__(self, value: object) -> None:
        self.value = value

    def currentData(self) -> object:
        return self.value

    def isChecked(self) -> bool:
        return bool(self.value)

    def text(self) -> str:
        return str(self.value)


class _FakeProcess:
    def state(self) -> str:
        return "ProcessState.Running"

    def program(self) -> str:
        return "host.exe"

    def arguments(self) -> list[str]:
        return ["--preview-package", "old-package"]


class _FakeQObject:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass


def _fake_slot(*_args: object, **_kwargs: object) -> object:
    def _decorator(func: object) -> object:
        return func

    return _decorator


def test_alignment_d3d11_mesh_edit_tab_active_reads_context_checkbox() -> None:
    checkbox = _FakeValueWidget(False)
    callbacks = create_alignment_d3d11_package_lifecycle_callbacks(
        {
            "QObject": _FakeQObject,
            "Slot": _fake_slot,
            "dialog": object(),
            "mesh_edit_enabled_checkbox": checkbox,
        }
    )

    assert callbacks._alignment_mesh_edit_tab_active() is False
    checkbox.value = True
    assert callbacks._alignment_mesh_edit_tab_active() is True


def test_mesh_editor_diagnostics_uses_late_prompt_context_values() -> None:
    live_context: dict[str, object] = {}
    diagnostics_state = {"text_widget": _FakeTextEdit(), "last_text": ""}
    callbacks = create_alignment_mesh_diagnostics_callbacks(
        {
            "List": list,
            "ModelPreviewData": type("FakeModelPreviewData", (), {}),
            "Path": Path,
            "QPlainTextEdit": _FakeTextEdit,
            "QProcess": _FakeProcess,
            "prompt_shell_context": live_context,
            "_mesh_editor_diagnostics_append_safe_value_helper": mesh_editor_diagnostics_append_safe_value,
            "_mesh_editor_diagnostics_copied_status_helper": mesh_editor_diagnostics_copied_status,
            "_mesh_editor_diagnostics_manifest_lines": lambda package: [f"manifest: {package}"],
            "_mesh_editor_diagnostics_model_lines": lambda label, model, **_kwargs: [f"{label}: {model}"],
            "_mesh_editor_diagnostics_record_text_helper": mesh_editor_diagnostics_record_text,
            "_mesh_editor_diagnostics_source_mesh_lines": lambda label, mesh, **_kwargs: [f"{label}: {mesh}"],
            "_mesh_editor_diagnostics_text_widget_helper": mesh_editor_diagnostics_text_widget,
            "_source_index_is_enabled_renderable": lambda _index: True,
            "embedded_alignment_builder": True,
            "entry": SimpleNamespace(path="target.pac"),
            "find_native_d3d11_host": lambda: "host.exe",
            "json": __import__("json"),
            "mesh_editor_diagnostics_state": diagnostics_state,
            "obj_path": "source.obj",
            "self": SimpleNamespace(set_status_message=lambda *_args, **_kwargs: None),
            "time": SimpleNamespace(strftime=lambda _fmt: "now"),
        }
    )
    live_context.update(
        {
            "_alignment_d3d11_preview_active": lambda: True,
            "_alignment_mesh_edit_tab_active": lambda: True,
            "_alignment_preview_source_face_limit": lambda: 456,
            "_get_texture_sets": lambda: {"mat": SimpleNamespace(slots={})},
            "_mesh_edit_raw_preview_active": lambda: True,
            "alignment_d3d11_preview_status_label": _FakeValueWidget("100% Preview ready."),
            "alignment_d3d11_state": {
                "active_package": "new-package",
                "process": _FakeProcess(),
                "status_file": "new-status.json",
                "status_payload_text": '{"event":"loaded"}',
            },
            "highlighted_source_indices": {7, 2},
            "mesh_edit_enabled_checkbox": _FakeValueWidget(True),
            "mesh_edit_scope_combo": _FakeValueWidget("all"),
            "mesh_edit_show_vertices_checkbox": _FakeValueWidget(True),
            "mesh_edit_tool_combo": _FakeValueWidget("move"),
            "preview_mode_combo": _FakeValueWidget("side_by_side"),
            "preview_performance_label": _FakeValueWidget("ready in 1 ms"),
            "preview_render_mode_combo": _FakeValueWidget("lit"),
            "preview_renderer_combo": _FakeValueWidget("d3d11"),
            "preview_visible_mode_combo": _FakeValueWidget("mesh_base_first"),
            "replacement_mesh_base_for_mapping": "base-mesh",
            "replacement_mesh_for_mapping": "live-mesh",
            "replacement_preview_model": "live-model",
            "selected_source_part": {"index": 3},
            "texture_files_for_mapping": [Path("a.dds")],
        }
    )

    callbacks._refresh_mesh_editor_diagnostics()
    text = diagnostics_state["text_widget"].toPlainText()

    assert "<error:" not in text
    assert "d3d11_active: True" in text
    assert "preview_timing_label: ready in 1 ms" in text
    assert "source_face_limit: 456" in text
    assert "selected_source: 3" in text
    assert "highlighted_sources: (2, 7)" in text
    assert "replacement_mesh_for_mapping: live-mesh" in text
    assert "replacement_preview_model: live-model" in text
    assert "texture_files_for_mapping=1 texture_sets=1" in text
    assert "process_start_arguments: --preview-package old-package" in text
    assert "process_arguments:" not in text
