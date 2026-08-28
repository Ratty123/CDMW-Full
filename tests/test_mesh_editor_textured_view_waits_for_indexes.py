"""Textured view must wait for the shell's deferred texture lookup.

The shell builds its archive path/basename lookup on demand, and the Mesh
Editor's material context resolution used to run against the empty maps that
deferral leaves behind: every embedded material name then reported "no direct
visible DDS match" even though the archive holds the textures, which is how
Solid (Textured) failed on a model the Archive Browser preview textures fine
(`cd_phw_00_nude_00_0001_damian.pac`). Resolution now holds while the lookup
build is underway and retries when it lands, and every terminal failure also
tells the resident helper why, so the panel's status line stops claiming
"Loading textures..." forever.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, Signal, Slot
from PySide6.QtWidgets import QApplication

from cdmw.models import ArchiveEntry
from cdmw.ui.mesh_editor import MeshEditorTab
from tests.test_mesh_editor_action_bar import (
    _FakeProcess,
    _build_two_part_synthetic_mesh,
    _install_shared_dotnet_test_process,
)


def _archive_entry(path: str = "character/model/test/test_entry.pac") -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("0009/0.pamt"),
        paz_file=Path("0009/1.paz"),
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


class _FakeContextWorker(QObject):
    """Stands in for MeshArchiveMaterialContextWorker; records its inputs."""

    resolved = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    instances: list["_FakeContextWorker"] = []

    def __init__(self, request_id: int, entry: object, **kwargs: object) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.entry = entry
        self.kwargs = dict(kwargs)
        type(self).instances.append(self)

    @Slot()
    def run(self) -> None:
        pass

    def stop(self) -> None:
        pass


def _direct_tab(name: str, *, path_index: dict, ensure_calls: list):
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(
        settings=QSettings("CDMWTests", name),
        get_archive_texture_entries_by_normalized_path=lambda: path_index,
        get_archive_texture_entries_by_basename=lambda: path_index,
        get_archive_sidecar_entries_by_texture_path=lambda: {},
        get_archive_sidecar_entries_by_texture_basename=lambda: {},
        ensure_archive_texture_indexes=lambda: (ensure_calls.append("ensure"), True)[1],
    )
    tab.open_mesh_session(
        _build_two_part_synthetic_mesh(),
        session_id="direct-index-wait",
        mode="edit",
    )
    assert tab.standalone_controller is not None
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = False
    tab.standalone_dotnet_target_controller = tab.standalone_controller
    tab._connect_dotnet_protocol(process)
    session_id = tab.standalone_controller.session_view().session_id
    _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2", "viewport_display_modes_v1"),
        session_id=session_id,
    )
    tab.standalone_dotnet_lifecycle_session_id = session_id
    return app, tab, process


def _display_updates(process: _FakeProcess) -> list[dict[str, object]]:
    return [
        payload
        for payload in (json.loads(raw.decode("utf-8")) for raw in process.stdin_writes)
        if payload.get("event") == "viewport_display_update"
    ]


def test_missing_indexes_hold_the_resolution_instead_of_resolving_nothing() -> None:
    path_index: dict = {}
    ensure_calls: list = []
    app, tab, process = _direct_tab(
        "MeshEditorIndexWaitHolds",
        path_index=path_index,
        ensure_calls=ensure_calls,
    )
    entry = _archive_entry()
    tab.current_archive_selection = entry

    assert tab._handle_dotnet_protocol_event(
        {
            "event": "viewport_display_request",
            "session_id": "direct-index-wait",
            "request_id": 41,
            "process_generation": 1,
            "mode": "textured",
        }
    )

    # The request is honestly pending: no doomed resolver ran, the shell was
    # asked to build the lookup, and the retry is scheduled.
    assert ensure_calls == ["ensure"]
    assert tab.archive_material_context_thread is None
    assert tab.archive_material_context_pending is True
    assert tab.archive_texture_index_wait_timer.isActive()
    assert tab.standalone_dotnet_pending_textured_view is True
    assert [payload["mode"] for payload in _display_updates(process)][-1] == "untextured_faces"

    # The lookup lands; the retry resolves with the populated indexes.
    path_index["character/texture/test.dds"] = (entry,)
    companion = _archive_entry("character/model/test/test_companion.pac")
    tab.archive_material_context_companion_entry = companion
    _FakeContextWorker.instances.clear()
    with patch(
        "cdmw.ui.mesh_editor.tab.MeshArchiveMaterialContextWorker",
        _FakeContextWorker,
        create=True,
    ):
        tab._retry_archive_material_context_after_index_wait()
        assert len(_FakeContextWorker.instances) == 1
        worker = _FakeContextWorker.instances[0]
        assert worker.kwargs["companion_entry"] is companion
        assert worker.kwargs["entries_by_normalized_path"] is path_index
        assert tab.archive_material_context_thread is not None
        assert tab.archive_texture_index_wait_attempts == 0
        tab._cancel_archive_material_context_resolution()
        app.processEvents()

    tab.deleteLater()
    app.processEvents()


def test_no_shell_hook_keeps_the_old_immediate_resolution() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorIndexWaitNoHook"))
    entry = _archive_entry()
    tab.current_archive_selection = entry

    _FakeContextWorker.instances.clear()
    with patch(
        "cdmw.ui.mesh_editor.tab.MeshArchiveMaterialContextWorker",
        _FakeContextWorker,
        create=True,
    ):
        assert tab._start_archive_material_context_resolution(entry)
        # Without an index hook nothing would ever retry, so resolution runs
        # now, exactly as before, and fails through the resolver's own report.
        assert len(_FakeContextWorker.instances) == 1
        assert tab.archive_material_context_thread is not None
        assert not tab.archive_texture_index_wait_timer.isActive()
        tab._cancel_archive_material_context_resolution()
        app.processEvents()

    tab.deleteLater()
    app.processEvents()


def test_an_exhausted_wait_resolves_anyway_and_fails_honestly() -> None:
    from cdmw.ui.mesh_editor.tab_session_runtime import (
        ARCHIVE_TEXTURE_INDEX_WAIT_MAX_ATTEMPTS,
    )

    path_index: dict = {}
    ensure_calls: list = []
    app, tab, process = _direct_tab(
        "MeshEditorIndexWaitExhausted",
        path_index=path_index,
        ensure_calls=ensure_calls,
    )
    entry = _archive_entry()
    tab.current_archive_selection = entry
    tab.archive_texture_index_wait_attempts = ARCHIVE_TEXTURE_INDEX_WAIT_MAX_ATTEMPTS

    _FakeContextWorker.instances.clear()
    with patch(
        "cdmw.ui.mesh_editor.tab.MeshArchiveMaterialContextWorker",
        _FakeContextWorker,
        create=True,
    ):
        assert tab._start_archive_material_context_resolution(entry)
        assert len(_FakeContextWorker.instances) == 1
        assert tab.archive_texture_index_wait_attempts == 0
        tab._cancel_archive_material_context_resolution()
        app.processEvents()

    tab.deleteLater()
    app.processEvents()


def test_a_failed_textured_view_tells_the_helper_why() -> None:
    """The helper's status line must stop claiming "Loading textures..."."""

    path_index: dict = {}
    ensure_calls: list = []
    app, tab, process = _direct_tab(
        "MeshEditorTexturedFailureText",
        path_index=path_index,
        ensure_calls=ensure_calls,
    )
    # No archive selection: the direct resolver has nothing to resolve, so the
    # request fails immediately through _settle_requested_textured_view.
    tab.current_archive_selection = None

    assert tab._handle_dotnet_protocol_event(
        {
            "event": "viewport_display_request",
            "session_id": "direct-index-wait",
            "request_id": 42,
            "process_generation": 1,
            "mode": "textured",
        }
    )

    assert tab.standalone_dotnet_pending_textured_view is False
    updates = _display_updates(process)
    failure = updates[-1]
    assert failure["mode"] == "untextured_faces"
    assert failure["texture_request_failed"] is True
    assert "No resolved textures" in str(failure["failure_text"])

    tab.deleteLater()
    app.processEvents()
