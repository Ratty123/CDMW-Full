"""The Modify Original draft check must hand off to the Geometry open.

`_start_archive_modify_original_workspace` runs the draft fingerprint check as a
`UtilityWorker` task and then starts the workspace preparation task from that
task's completion handler. Qt delivers `UtilityWorker.completed` before
`QThread.finished`, so `worker_thread` is still set while the handler runs, and a
plain `_run_utility_task` refuses the second stage as "another background task is
still running". The refusal only reaches the status field, so the archive log ends
at the draft-check line and the Mesh Editor never opens.

This drives the real `UtilityControllerMixin` over real `QThread`s rather than a
stand-in for the ordering, because the ordering is the defect.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Mapping
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.domain.mesh.session import ModifyOriginalWorkflowSelection
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser import mesh_modify_original as modify_original_module
from cdmw.ui.archive_browser.mesh_modify_original import ArchiveMeshModifyOriginalMixin
from cdmw.ui.shell.log_controller import LogControllerMixin
from cdmw.ui.shell.utility_controller import UtilityControllerMixin


class _ModifyOriginalChainOwner(
    ArchiveMeshModifyOriginalMixin,
    UtilityControllerMixin,
    LogControllerMixin,
    QWidget,
):
    """Smallest real host for the two-stage Modify Original chain."""

    def __init__(self, settings_file_path: Path) -> None:
        super().__init__()
        self.settings_file_path = settings_file_path
        self.archive_entries_by_normalized_path: dict[str, tuple[ArchiveEntry, ...]] = {}
        self.archive_entries_by_basename: dict[str, tuple[ArchiveEntry, ...]] = {}
        self.archive_entries: tuple[ArchiveEntry, ...] = ()
        self.worker_thread = None
        self.utility_worker = None
        self.scan_worker = None
        self.archive_scan_worker = None
        self.archive_filter_worker = None
        self.build_worker = None
        self.dds_to_png_worker = None
        self.archive_basic_index_thread = None
        self.archive_sidecar_thread = None
        self.text_search_tab = None
        self.archive_browser_tab = None
        self.archive_sidecar_pending_start = False
        self.archive_filter_apply_pending = False
        self.archive_scan_finalize_pending = False
        self.archive_browser_refresh_pending = False
        self._shutting_down = False
        self._utility_updates_archive_progress = False
        self._utility_completion_handler = None
        self._utility_error_handler = None
        self.status_messages: list[tuple[str, bool]] = []
        self.log_messages: list[str] = []
        self.mesh_setup_calls: list[Mapping[str, object]] = []

    # Shell surfaces the utility runner touches, reduced to recorders.
    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.status_messages.append((str(message), bool(error)))

    def append_log(self, message: str) -> None:
        self.log_messages.append(str(message))

    def append_archive_log(self, message: str) -> None:
        self.log_messages.append(str(message))

    def set_busy(self, busy: bool, build_mode: bool = False) -> None:
        return None

    def _reset_archive_load_progress(self) -> None:
        return None

    def _set_archive_load_progress(self, *_args: object, **_kwargs: object) -> None:
        return None

    def _write_heartbeat(self, *_args: object, **_kwargs: object) -> None:
        return None

    def _release_startup_splash(self) -> None:
        return None

    def _write_crash_report(self, *_args: object, **_kwargs: object) -> None:
        return None

    def _collect_crash_context(self) -> dict[str, object]:
        return {}

    def _maybe_release_startup_after_archive_ready(self) -> None:
        return None

    # Canned prompt result: default in-app clone mode, no dialog.
    def _prompt_archive_modify_original_workspace_options(
        self,
        _entry: ArchiveEntry,
    ) -> ModifyOriginalWorkflowSelection:
        return ModifyOriginalWorkflowSelection(
            create_workspace=False,
            workspace_parent=None,
            include_family_files=True,
            open_workspace_after_create=False,
        )

    # The step the user never reached.
    def _open_modify_original_mesh_setup(
        self,
        _entry: ArchiveEntry,
        result: Mapping[str, object],
    ) -> None:
        self.mesh_setup_calls.append(result)


def _entry() -> ArchiveEntry:
    return ArchiveEntry(
        "character/model/1_pc/cd_pom_00_nude_10_0001.pac",
        Path("0009/0.pamt"),
        Path("0009/0.paz"),
        0,
        1,
        1,
        0,
        0,
    )


def _drain(app: QApplication, predicate, *, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def test_modify_original_draft_check_chains_into_geometry_open(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    source_data = b"synthetic modify original source asset"
    monkeypatch.setattr(
        modify_original_module,
        "read_modify_original_source_asset",
        lambda _entry, **_kwargs: (source_data, hashlib.sha256(source_data).hexdigest()),
    )
    workspace_dir = tmp_path / "session" / "cd_pom_00_nude_10_0001"
    obj_path = workspace_dir / "editable.obj"
    prepared: dict[str, object] = {
        "workspace_dir": workspace_dir,
        "obj_path": obj_path,
        "create_workspace": False,
        "resumed_draft": False,
        "workspace_mode": "internal_app_session",
        "source_asset_sha256": hashlib.sha256(source_data).hexdigest(),
    }
    monkeypatch.setattr(
        modify_original_module,
        "prepare_modify_original_workspace",
        lambda *_args, **_kwargs: prepared,
    )

    owner = _ModifyOriginalChainOwner(tmp_path / "settings.ini")
    try:
        owner._start_archive_modify_original_workspace(_entry())
        _drain(app, lambda: bool(owner.mesh_setup_calls))

        assert owner.mesh_setup_calls, (
            "Modify Original stopped after the draft check instead of opening Geometry. "
            f"Status trail: {owner.status_messages}. Log trail: {owner.log_messages}."
        )
        assert owner.mesh_setup_calls[0]["obj_path"] == obj_path
        refusals = [
            message
            for message, _error in owner.status_messages
            if "Another background task is still running" in message
        ]
        assert not refusals, f"Chained stage was refused as a concurrent task: {refusals}"
    finally:
        _drain(app, lambda: owner.worker_thread is None)
        owner.deleteLater()
        app.processEvents()
