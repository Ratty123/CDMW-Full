from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QPushButton

from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.catalogue_operations import (
    ArchiveExportCollisionPolicy,
    ArchiveExportItem,
    ArchiveExportResult,
    ArchiveExportSelectionKind,
)
from cdmw.ui.archive_browser.extraction import ArchiveExtractionMixin
from cdmw.ui.archive_browser.remote_window_bridge import ArchiveRemoteExportSelection
from cdmw.ui.texture_workflow.workers import TextureWorkflowWorkerMixin


_APPLICATION: QApplication | None = None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


class _ExportService(QObject):
    progress = Signal(str, object)
    batch_ready = Signal(str, str, object)
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[tuple[object, int]] = []
        self.cancelled: list[str] = []

    def export(self, request: object, *, ui_generation: int) -> str:
        self.requests.append((request, ui_generation))
        return f"export-{len(self.requests)}"

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True


class _RemoteExportHarness(ArchiveExtractionMixin):
    def __init__(self, output_root: Path) -> None:
        _app()
        self.output_root = output_root
        self.archive_catalogue_service = _ExportService()
        self.archive_remote_bridge = SimpleNamespace(
            displays_v2=True,
            current_session=ArchiveSessionHandle("session-a", "C:/Game", "fingerprint", 10, 2, True),
        )
        self.archive_remote_actions_safe = True
        self.archive_extract_root_edit = QLineEdit()
        self.original_dds_edit = QLineEdit()
        self.filters_edit = QPlainTextEdit()
        self.workflow_tab = object()
        self.build_worker = None
        self.dds_to_png_worker = None
        self.utility_worker = None
        self.stop_button = QPushButton()
        self.statuses: list[tuple[str, bool]] = []
        self.busy_states: list[bool] = []
        self.busy_modes: list[bool] = []
        self.archive_logs: list[str] = []
        self.logs: list[str] = []
        self.progress: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.dashboard_refreshes = 0
        self.activated: list[object] = []

    def _suggest_archive_extract_root(self) -> Path:
        return self.output_root

    def _prompt_remote_archive_extract_options(
        self,
        requested_count: int,
        output_root: Path,
    ) -> tuple[bool, ArchiveExportCollisionPolicy]:
        assert requested_count == 43
        assert output_root == self.output_root.resolve()
        return True, ArchiveExportCollisionPolicy.OVERWRITE

    def set_busy(self, busy: bool, *, build_mode: bool) -> None:
        self.busy_states.append(busy)
        self.busy_modes.append(build_mode)

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.statuses.append((message, error))

    def _set_archive_load_progress(self, *args: object, **kwargs: object) -> None:
        self.progress.append((args, kwargs))

    def append_archive_log(self, message: str, **_kwargs: object) -> None:
        self.archive_logs.append(message)

    def append_log(self, message: str) -> None:
        self.logs.append(message)

    def _refresh_dashboard(self) -> None:
        self.dashboard_refreshes += 1

    def _activate_tool_widget(self, widget: object) -> None:
        self.activated.append(widget)


def test_remote_export_submits_server_side_selection_and_handles_result(tmp_path: Path) -> None:
    output_root = tmp_path / "export"
    harness = _RemoteExportHarness(output_root)
    selection = ArchiveRemoteExportSelection(
        ArchiveExportSelectionKind.FOLDER,
        43,
        folder_path="0009/texture",
        extensions=(".dds",),
    )

    harness._run_remote_archive_export(selection, description="Exporting folder...")

    service = harness.archive_catalogue_service
    assert len(service.requests) == 1
    request, generation = service.requests[0]
    assert generation == 1
    assert request.session_id == "session-a"
    assert request.selection_kind is ArchiveExportSelectionKind.FOLDER
    assert request.folder_path == "0009/texture"
    assert request.entry_ids == ()
    assert request.extensions == (".dds",)
    assert request.include_package_root
    assert request.replace_destination
    assert request.collision_policy is ArchiveExportCollisionPolicy.OVERWRITE
    assert harness.busy_states == [True]
    assert harness.busy_modes == [True]

    exported_items = (
        ArchiveExportItem("texture/albedo.dds", str(output_root / "0009/texture/albedo.dds"), "exported"),
        ArchiveExportItem("texture/normal.dds", str(output_root / "0009/texture/normal_2.dds"), "renamed"),
    )
    service.batch_ready.emit(
        "export-1",
        "export",
        ArchiveExportResult(
            "session-a",
            43,
            2,
            0,
            0,
            False,
            str(output_root / "cdmw-export-manifest.json"),
            exported_items,
            False,
        ),
    )
    service.result_ready.emit(
        "export-1",
        "export",
        ArchiveExportResult(
            "session-a",
            43,
            2,
            0,
            0,
            False,
            str(output_root / "cdmw-export-manifest.json"),
            (),
            False,
        ),
    )

    assert harness.busy_states == [True, False]
    assert harness.archive_extract_root_edit.text() == str(output_root.resolve())
    assert harness.dashboard_refreshes == 1
    assert "2 extracted, 1 renamed, 0 skipped, 0 failed" in harness._dashboard_last_result_text
    assert harness._archive_remote_export_request_id is None


def test_remote_export_cancel_is_forwarded_without_starting_legacy_worker(tmp_path: Path) -> None:
    harness = _RemoteExportHarness(tmp_path / "export")
    selection = ArchiveRemoteExportSelection(
        ArchiveExportSelectionKind.QUERY,
        43,
        query_id="query-a",
    )
    harness._run_remote_archive_export(selection, description="Exporting filtered entries...")

    harness._cancel_remote_archive_export()

    assert harness.archive_catalogue_service.cancelled == ["export-1"]
    harness.archive_catalogue_service.request_cancelled.emit("export-1")
    assert harness.busy_states == [True, False]
    assert harness.statuses[-1] == ("Archive export cancelled.", False)


def test_main_stop_action_cancels_remote_archive_export(tmp_path: Path) -> None:
    harness = _RemoteExportHarness(tmp_path / "export")
    selection = ArchiveRemoteExportSelection(
        ArchiveExportSelectionKind.QUERY,
        43,
        query_id="query-a",
    )
    harness._run_remote_archive_export(selection, description="Exporting filtered entries...")
    harness.stop_button.setEnabled(True)

    TextureWorkflowWorkerMixin.stop_build(harness)

    assert harness.archive_catalogue_service.cancelled == ["export-1"]
    assert not harness.stop_button.isEnabled()
    assert harness.statuses[-1] == (
        "Stop requested. Waiting for the archive export to exit cleanly...",
        False,
    )


def test_empty_remote_dds_export_does_not_repoint_the_workflow(tmp_path: Path) -> None:
    harness = _RemoteExportHarness(tmp_path / "export")
    selection = ArchiveRemoteExportSelection(
        ArchiveExportSelectionKind.QUERY,
        43,
        query_id="query-a",
        all_dds=True,
        extensions=(".dds",),
    )
    harness._run_remote_archive_export(
        selection,
        set_original_dds_root=True,
        allow_original_dds_root=True,
        description="Exporting DDS entries...",
    )

    harness.archive_catalogue_service.result_ready.emit(
        "export-1",
        "export",
        ArchiveExportResult("session-a", 0, 0, 0, 0, False, None, (), False),
    )

    assert harness.original_dds_edit.text() == ""
    assert harness.activated == []
    assert harness.statuses[-1] == ("No DDS files matched the archive selection.", True)


def test_remote_dds_handoff_filters_the_actual_renamed_worker_output(tmp_path: Path) -> None:
    output_root = tmp_path / "export"
    harness = _RemoteExportHarness(output_root)
    selection = ArchiveRemoteExportSelection(
        ArchiveExportSelectionKind.QUERY,
        43,
        query_id="query-a",
        all_dds=True,
        extensions=(".dds",),
    )
    harness._run_remote_archive_export(
        selection,
        set_original_dds_root=True,
        allow_original_dds_root=True,
        description="Exporting DDS entries...",
    )
    renamed_path = output_root.resolve() / "0009" / "texture" / "albedo_2.dds"
    harness.archive_catalogue_service.batch_ready.emit(
        "export-1",
        "export",
        ArchiveExportResult(
            "session-a",
            1,
            1,
            0,
            0,
            False,
            str(output_root / "cdmw-export-manifest.json"),
            (ArchiveExportItem("texture/albedo.dds", str(renamed_path), "renamed"),),
            False,
        ),
    )
    harness.archive_catalogue_service.result_ready.emit(
        "export-1",
        "export",
        ArchiveExportResult("session-a", 1, 1, 0, 0, False, None, (), False),
    )

    assert harness.original_dds_edit.text() == str(output_root.resolve())
    assert harness.filters_edit.toPlainText() == "0009/texture/albedo_2.dds"
    assert harness.activated == [harness.workflow_tab]
