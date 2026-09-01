from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess, QSettings, QThread
from PySide6.QtWidgets import QApplication

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_rust_authoring import RustMeshCancellationError
from cdmw.services.mesh_rust_contract import (
    RUST_MESH_AUTHORING_PACKAGE,
    RUST_MESH_CONTROL_CONTRACT_FILE,
    RUST_MESH_CONTROL_CONTRACT_SCHEMA,
    RUST_MESH_EDIT_BACKEND,
    RUST_MESH_EDITOR_PROTOCOL,
    RUST_MESH_PROVENANCE_FILE,
    RUST_MESH_PROVENANCE_SCHEMA,
    RUST_MESH_RENDERER,
    RUST_PREVIEW_BACKEND,
    RUST_PREVIEW_PACKAGE,
    RUST_PREVIEW_PROTOCOL,
    RUST_PREVIEW_REQUIRED_CAPABILITIES,
    RustMeshExecutableResolution,
    rust_mesh_editor_file_signature,
)
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from cdmw.ui.mesh_editor.tab_rust_editor import (
    MESH_EDITOR_BACKEND_RUST,
    MESH_EDITOR_BACKEND_SETTING,
    MESH_EDITOR_BACKEND_VORTICE,
)
from cdmw.workers.mesh_rust_editor_workers import (
    MeshRustProtocolWorker,
    MeshRustSessionDisposeWorker,
    MeshRustSessionPrepareWorker,
)


def _tab(tmp_path: Path, *, backend: str | None = None) -> MeshEditorTab:
    application = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.clear()
    if backend is not None:
        settings.setValue(MESH_EDITOR_BACKEND_SETTING, backend)
        settings.sync()
    tab = MeshEditorTab(settings=settings)
    application.processEvents()
    return tab


def _archive_entry(
    tmp_path: Path,
    *,
    package: str = "0009",
    offset: int = 0,
    paz_index: int = 0,
) -> ArchiveEntry:
    return ArchiveEntry(
        path="character/model/material-context.pac",
        pamt_path=tmp_path / package / "0.pamt",
        paz_file=tmp_path / package / "0.paz",
        offset=offset,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=paz_index,
    )


def _dispose(tab: MeshEditorTab) -> None:
    application = QApplication.instance()
    tab.deleteLater()
    if application is not None:
        application.processEvents()


def _provenanced_resolution(root: Path, *, payload: bytes = b"rust-helper") -> RustMeshExecutableResolution:
    root.mkdir(parents=True, exist_ok=True)
    executable = root / "cdmw_mesh_lab.exe"
    executable.write_bytes(payload)
    contract_path = executable.with_name(RUST_MESH_CONTROL_CONTRACT_FILE)
    contract_path.write_text(
        json.dumps({"schema": RUST_MESH_CONTROL_CONTRACT_SCHEMA, "ok": True, "row_count": 1, "rows": [{}]}),
        encoding="utf-8",
    )
    contract_bytes = contract_path.read_bytes()
    executable.with_name(RUST_MESH_PROVENANCE_FILE).write_text(
        json.dumps(
            {
                "schema": RUST_MESH_PROVENANCE_SCHEMA,
                "renderer": RUST_MESH_RENDERER,
                "edit_backend": RUST_MESH_EDIT_BACKEND,
                "protocol": RUST_MESH_EDITOR_PROTOCOL,
                "authoring_package": RUST_MESH_AUTHORING_PACKAGE,
                "preview_protocol": RUST_PREVIEW_PROTOCOL,
                "preview_package": RUST_PREVIEW_PACKAGE,
                "preview_backend": RUST_PREVIEW_BACKEND,
                "control_contract": RUST_MESH_CONTROL_CONTRACT_FILE,
                "control_contract_schema": RUST_MESH_CONTROL_CONTRACT_SCHEMA,
                "capabilities": [
                    "embedded_child_window_v1",
                    "rust_preview_runtime_v1",
                ],
                "preview_capabilities": list(RUST_PREVIEW_REQUIRED_CAPABILITIES),
                "locked_dependencies": True,
                "executable_sha256": hashlib.sha256(payload).hexdigest(),
                "control_contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return RustMeshExecutableResolution(
        resolved_path=str(executable),
        source="configured",
        exists=True,
        is_file=True,
    )


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def connect(self, callback: object) -> None:
        self.callbacks.append(callback)


class _BufferedProcess:
    def __init__(
        self,
        *,
        stdout_chunks: tuple[bytes, ...] = (),
        stderr_chunks: tuple[bytes, ...] = (),
    ) -> None:
        self.stdout_chunks = list(stdout_chunks)
        self.stderr_chunks = list(stderr_chunks)
        self.deleted = False

    def readAllStandardOutput(self) -> bytes:  # noqa: N802 - Qt-compatible test double
        return self.stdout_chunks.pop(0) if self.stdout_chunks else b""

    def readAllStandardError(self) -> bytes:  # noqa: N802 - Qt-compatible test double
        return self.stderr_chunks.pop(0) if self.stderr_chunks else b""

    def state(self) -> QProcess.ProcessState:
        return QProcess.ProcessState.NotRunning

    def deleteLater(self) -> None:  # noqa: N802 - Qt-compatible test double
        self.deleted = True


class _LaunchProcess:
    def __init__(self) -> None:
        self.started = _FakeSignal()
        self.readyReadStandardOutput = _FakeSignal()
        self.readyReadStandardError = _FakeSignal()
        self.errorOccurred = _FakeSignal()
        self.finished = _FakeSignal()
        self.environment = None
        self.start_called = False
        self.arguments: list[str] = []

    def setProcessChannelMode(self, _mode: object) -> None:  # noqa: N802
        pass

    def setProgram(self, _program: str) -> None:  # noqa: N802
        pass

    def setArguments(self, arguments: list[str]) -> None:  # noqa: N802
        self.arguments = list(arguments)

    def setWorkingDirectory(self, _path: str) -> None:  # noqa: N802
        pass

    def setProcessEnvironment(self, environment: object) -> None:  # noqa: N802
        self.environment = environment

    def start(self) -> None:
        self.start_called = True


def test_rust_is_the_only_backend_and_legacy_preference_is_ignored(tmp_path: Path) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_VORTICE)
    assert tab.mesh_editor_backend_combo is None
    assert tab.mesh_editor_backend_label is None
    assert tab._selected_mesh_editor_backend() == MESH_EDITOR_BACKEND_RUST
    assert tab.settings.value(MESH_EDITOR_BACKEND_SETTING) == MESH_EDITOR_BACKEND_VORTICE
    _dispose(tab)


def test_rust_preflight_recomputes_open_state_after_busy_or_unavailable(tmp_path: Path) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    tab.current_archive_selection = object()  # type: ignore[assignment]
    available = RustMeshExecutableResolution(
        resolved_path=str(tmp_path / "cdmw_mesh_lab.exe"),
        source="configured",
        exists=True,
        is_file=True,
    )
    tab.standalone_rust_checked_executable = available.resolved_path
    tab.standalone_rust_checked_executable_signature = ""
    tab.standalone_rust_incompatible_reason = ""
    with (
        patch(
            "cdmw.ui.mesh_editor.tab_rust_editor.resolve_rust_mesh_editor",
            return_value=available,
        ),
        patch(
            "cdmw.ui.mesh_editor.tab_rust_editor.rust_mesh_editor_file_signature",
            return_value="",
        ),
    ):
        tab._sync_mesh_editor_backend_controls(task_active=True)
        assert not tab.open_selected_mesh_button.isEnabled()
        tab._sync_mesh_editor_backend_controls(task_active=False)
        assert tab.open_selected_mesh_button.isEnabled()
    _dispose(tab)


def test_missing_or_incompatible_rust_disables_open_with_visible_reason(tmp_path: Path) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    tab.open_selected_mesh_button.setEnabled(True)
    missing = RustMeshExecutableResolution(resolved_path="missing.exe", source="missing")
    with patch("cdmw.ui.mesh_editor.tab_rust_editor.resolve_rust_mesh_editor", return_value=missing):
        tab._sync_mesh_editor_backend_controls(has_active_session=False, task_active=False)

    assert not tab.open_selected_mesh_button.isEnabled()
    assert "unavailable" in tab.mesh_editor_backend_reason_label.text().lower()
    assert "not found" in tab.mesh_editor_backend_reason_label.text().lower()

    tab.open_selected_mesh_button.setEnabled(True)
    tab.standalone_rust_incompatible_reason = "protocol version does not match"
    same_path = RustMeshExecutableResolution(
        resolved_path=tab.standalone_rust_checked_executable,
        source="configured",
        exists=True,
        is_file=True,
    )
    with patch("cdmw.ui.mesh_editor.tab_rust_editor.resolve_rust_mesh_editor", return_value=same_path):
        tab._sync_mesh_editor_backend_controls(has_active_session=False, task_active=False)
    assert not tab.open_selected_mesh_button.isEnabled()
    assert "protocol version does not match" in tab.mesh_editor_backend_reason_label.text()
    _dispose(tab)


def test_start_revalidates_instead_of_trusting_the_selector_cache(tmp_path: Path) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    resolution = _provenanced_resolution(tmp_path / "helper")
    tab.standalone_rust_checked_executable = resolution.resolved_path
    tab.standalone_rust_checked_executable_signature = rust_mesh_editor_file_signature(
        resolution
    )
    tab.standalone_rust_incompatible_reason = ""

    with (
        patch(
            "cdmw.ui.mesh_editor.tab_rust_editor.resolve_rust_mesh_editor",
            return_value=resolution,
        ),
        patch(
            "cdmw.ui.mesh_editor.tab_rust_editor.validate_rust_mesh_editor_package",
            return_value="Rust provenance protocol does not match",
        ),
    ):
        tab._start_rust_editor_requested(object())

    assert tab.standalone_rust_prepare_thread is None
    assert "protocol does not match" in tab.standalone_status_label.text()
    _dispose(tab)


def test_rust_session_passes_resolved_preview_textures_to_the_shadow_builder(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    editable_part = SimpleNamespace(material="body", name="body")
    preview_part = SimpleNamespace(
        material_name="body",
        name="body",
        source_submesh_index=0,
        preview_texture_dds_path=str(tmp_path / "body_base.dds"),
    )
    tab.standalone_archive_material_preview_model = SimpleNamespace(
        path="character/body.pac",
        meshes=[preview_part],
    )
    package_root = tmp_path / "archive-preview-package"
    package_root.mkdir()
    tab.archive_material_context_package_path = str(package_root)
    controller = SimpleNamespace()

    copied = tab._prime_rust_preview_material_context(controller)

    assert copied == 1
    context = controller._cdmw_rust_mesh_preview_material_context
    assert context.preview_model is not tab.standalone_archive_material_preview_model
    assert context.preview_model.path == "character/body.pac"
    assert len(context.preview_model.submeshes) == 1
    captured_part = context.preview_model.submeshes[0]
    assert captured_part.material_name == "body"
    assert captured_part.source_submesh_index == 0
    assert captured_part.preview_texture_dds_path == str(tmp_path / "body_base.dds")
    assert context.material_package_path == str(package_root)
    assert context.unavailable_reason == ""
    assert not hasattr(editable_part, "preview_texture_dds_path")
    _dispose(tab)


def test_rust_texture_handoff_captures_only_matching_archive_entries(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    preview_part = SimpleNamespace(
        source_submesh_index=0,
        texture_name="CD_PGM_00_Nude_00_0001_Hand",
        material_name="CD_PHM_00_Nude_0001_hand",
    )
    tab.standalone_archive_material_preview_model = SimpleNamespace(
        path="character/model/body.pac",
        meshes=[preview_part],
    )
    matching = ArchiveEntry(
        path="character/texture/cd_phm_00_nude_00_0001_hand.dds",
        pamt_path=tmp_path / "source.pamt",
        paz_file=tmp_path / "source.paz",
        offset=10,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    unrelated = ArchiveEntry(
        path="character/texture/unrelated.dds",
        pamt_path=tmp_path / "source.pamt",
        paz_file=tmp_path / "source.paz",
        offset=20,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    tab._archive_texture_indexes = lambda: (  # type: ignore[method-assign]
        {},
        {
            matching.basename.casefold(): (matching, unrelated),
            unrelated.basename.casefold(): (unrelated,),
        },
    )
    target = ArchiveEntry(
        path="character/model/1_pc/9_pgm/nude/cd_pgm_00_nude_00_0001.pac",
        pamt_path=tmp_path / "source.pamt",
        paz_file=tmp_path / "source.paz",
        offset=30,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    tab.current_archive_selection = unrelated
    tab.current_request = SimpleNamespace(target_entry=target)
    controller = SimpleNamespace()

    tab._prime_rust_preview_material_context(controller)

    context = controller._cdmw_rust_mesh_preview_material_context
    assert [entry.path for entry in context.texture_entries] == [matching.path]
    assert context.texture_entries[0] is not matching
    assert context.target_entry is not target
    assert context.target_entry.path == target.path
    _dispose(tab)


def test_rust_material_failure_is_compact_while_shadow_fallback_still_runs(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    controller = SimpleNamespace(active_session_id="mesh-session")
    tab.standalone_controller = controller  # type: ignore[assignment]
    tab.standalone_rust_material_wait_session_id = "mesh-session"
    tab.standalone_rust_material_wait_controller = controller
    starts: list[object] = []
    tab._start_rust_editor_requested = starts.append  # type: ignore[method-assign]
    verbose = (
        "Recovered 3 material slots.\n"
        "3 embedded material base names had no direct visible DDS match.\n"
        "Texture Slot Mapping\n"
        + "diagnostic detail " * 100
    )

    assert tab._resume_rust_editor_after_material_context(
        available=False,
        reason=verbose,
    )

    assert starts == [controller]
    assert (
        tab.standalone_rust_texture_unavailable_reason
        == "No matching archive DDS textures were resolved for this mesh."
    )
    assert "Texture Slot Mapping" not in tab.standalone_status_label.text()
    assert len(tab.standalone_status_label.text()) < 220
    _dispose(tab)


def test_prepare_worker_forwards_cancellation_into_texture_resolution(
    tmp_path: Path,
) -> None:
    application = QApplication.instance() or QApplication([])
    service = object()
    worker = MeshRustSessionPrepareWorker(
        17,
        SimpleNamespace(active_session_id="mesh-session", mesh_service=service),
        tmp_path / "session-cancelled",
        process_generation=3,
    )
    entered = threading.Event()
    release = threading.Event()
    observed_tokens: list[threading.Event] = []
    prepared: list[object] = []
    errors: list[str] = []
    finished: list[bool] = []
    worker.prepared.connect(lambda _request_id, session: prepared.append(session))
    worker.error.connect(lambda _request_id, message: errors.append(message))
    worker.finished.connect(lambda: finished.append(True))

    def blocked_create(
        _controller: object,
        _root: Path,
        **kwargs: object,
    ) -> object:
        token = kwargs.get("stop_event")
        assert isinstance(token, threading.Event)
        observed_tokens.append(token)
        entered.set()
        assert release.wait(timeout=5.0)
        if token.is_set():
            raise RustMeshCancellationError("cancelled")
        raise AssertionError("the preparation token was not cancelled")

    run_thread = threading.Thread(target=worker.run)
    with patch(
        "cdmw.workers.mesh_rust_editor_workers.RustMeshAuthoringSession.create",
        side_effect=blocked_create,
    ):
        run_thread.start()
        try:
            assert entered.wait(timeout=5.0)
            worker.stop()
            release.set()
            run_thread.join(timeout=5.0)
        finally:
            release.set()
            run_thread.join(timeout=5.0)

    assert not run_thread.is_alive()
    application.processEvents()
    assert len(observed_tokens) == 1
    assert observed_tokens[0].is_set()
    assert prepared == []
    assert errors == []
    assert finished == [True]
    assert not (tmp_path / "session-cancelled").exists()


def test_prepare_worker_discards_result_when_authoritative_session_changes(
    tmp_path: Path,
) -> None:
    application = QApplication.instance() or QApplication([])
    service = object()
    controller = SimpleNamespace(
        active_session_id="mesh-session",
        mesh_service=service,
    )
    session_root = tmp_path / "session-stale"
    worker = MeshRustSessionPrepareWorker(
        23,
        controller,
        session_root,
        process_generation=4,
    )
    prepared: list[object] = []
    errors: list[str] = []
    finished: list[bool] = []
    cancelled: list[bool] = []
    worker.prepared.connect(lambda _request_id, session: prepared.append(session))
    worker.error.connect(lambda _request_id, message: errors.append(message))
    worker.finished.connect(lambda: finished.append(True))

    def create_then_replace_session(
        _controller: object,
        root: Path,
        **_kwargs: object,
    ) -> object:
        root.mkdir(parents=True)
        root_stat = root.stat()
        controller.active_session_id = "replacement-session"
        return SimpleNamespace(
            authoritative_service=service,
            authoritative_session_id="mesh-session",
            process_generation=4,
            root_identity=(int(root_stat.st_dev), int(root_stat.st_ino)),
            cancel=lambda: cancelled.append(True),
        )

    with patch(
        "cdmw.workers.mesh_rust_editor_workers.RustMeshAuthoringSession.create",
        side_effect=create_then_replace_session,
    ):
        worker.run()

    application.processEvents()
    assert prepared == []
    assert errors == []
    assert finished == [True]
    assert cancelled == [True]
    assert not session_root.exists()


def test_prepare_worker_rejects_changed_session_before_creating_shadow(
    tmp_path: Path,
) -> None:
    controller = SimpleNamespace(
        active_session_id="mesh-session",
        mesh_service=object(),
    )
    worker = MeshRustSessionPrepareWorker(
        29,
        controller,
        tmp_path / "session-never-created",
        process_generation=5,
    )
    controller.active_session_id = "replacement-session"
    create_calls: list[bool] = []
    prepared: list[object] = []
    errors: list[str] = []
    finished: list[bool] = []
    worker.prepared.connect(lambda _request_id, session: prepared.append(session))
    worker.error.connect(lambda _request_id, message: errors.append(message))
    worker.finished.connect(lambda: finished.append(True))

    with patch(
        "cdmw.workers.mesh_rust_editor_workers.RustMeshAuthoringSession.create",
        side_effect=lambda *_args, **_kwargs: create_calls.append(True),
    ):
        worker.run()

    assert create_calls == []
    assert prepared == []
    assert errors == []
    assert finished == [True]
    assert not (tmp_path / "session-never-created").exists()


def test_prepare_worker_discards_shadow_when_controller_service_changes(
    tmp_path: Path,
) -> None:
    application = QApplication.instance() or QApplication([])
    original_service = object()
    controller = SimpleNamespace(
        active_session_id="mesh-session",
        mesh_service=original_service,
    )
    session_root = tmp_path / "session-service-stale"
    worker = MeshRustSessionPrepareWorker(
        30,
        controller,
        session_root,
        process_generation=6,
    )
    prepared: list[object] = []
    errors: list[str] = []
    finished: list[bool] = []
    cancelled: list[bool] = []
    worker.prepared.connect(lambda _request_id, session: prepared.append(session))
    worker.error.connect(lambda _request_id, message: errors.append(message))
    worker.finished.connect(lambda: finished.append(True))

    def create_then_replace_service(
        _controller: object,
        root: Path,
        **_kwargs: object,
    ) -> object:
        root.mkdir(parents=True)
        root_stat = root.stat()
        controller.mesh_service = object()
        return SimpleNamespace(
            authoritative_service=original_service,
            authoritative_session_id="mesh-session",
            process_generation=6,
            root_identity=(int(root_stat.st_dev), int(root_stat.st_ino)),
            cancel=lambda: cancelled.append(True),
        )

    with patch(
        "cdmw.workers.mesh_rust_editor_workers.RustMeshAuthoringSession.create",
        side_effect=create_then_replace_service,
    ):
        worker.run()

    application.processEvents()
    assert prepared == []
    assert errors == []
    assert finished == [True]
    assert cancelled == [True]
    assert not session_root.exists()


def test_closing_during_prepare_stops_worker_before_controller_and_lease_release(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    events: list[str] = []
    service = object()
    controller = SimpleNamespace(
        active_session_id="mesh-session",
        mesh_service=service,
        close_active_session=lambda: events.append("controller_close"),
    )
    tab.standalone_controller = controller  # type: ignore[assignment]
    tab.standalone_live_stroke_dispatcher = None
    tab.archive_material_context_package_lease = SimpleNamespace(
        release=lambda: events.append("lease_release")
    )
    tab.standalone_rust_prepare_request_id = 31
    tab.standalone_rust_prepare_active_request_id = 31
    tab.standalone_rust_prepare_controller = controller
    tab.standalone_rust_prepare_service = service
    tab.standalone_rust_prepare_session_id = "mesh-session"
    tab.standalone_rust_prepare_process_generation = 7
    tab.standalone_rust_process_generation = 7
    tab.standalone_rust_target_controller = controller
    prepare_thread = QThread(tab)
    tab.standalone_rust_prepare_thread = prepare_thread
    tab.standalone_rust_prepare_worker = SimpleNamespace(
        stop=lambda: events.append("prepare_stop")
    )

    tab.close_standalone_session()

    assert events == ["prepare_stop", "controller_close", "lease_release"]
    assert tab.standalone_controller is None
    assert tab.standalone_rust_prepare_request_id == 32
    assert tab.standalone_rust_prepare_active_request_id == 0
    assert tab.standalone_rust_prepare_controller is None

    disposed: list[object] = []
    launched: list[object] = []
    stale_session = SimpleNamespace(
        root=tmp_path / "stale-session",
        authoritative_session_id="mesh-session",
        process_generation=7,
    )
    tab.standalone_rust_prepare_thread = None
    tab.standalone_rust_prepare_worker = None
    prepare_thread.deleteLater()
    tab._start_rust_dispose_worker = (  # type: ignore[method-assign]
        lambda session, _root: disposed.append(session)
    )
    tab._launch_rust_editor_process = launched.append  # type: ignore[method-assign]

    tab._handle_rust_session_prepared(31, stale_session)

    assert disposed == [stale_session]
    assert launched == []
    _dispose(tab)


def test_prepared_result_rejects_replaced_controller_with_same_session_id(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    service = object()
    original = SimpleNamespace(active_session_id="mesh-session", mesh_service=service)
    replacement = SimpleNamespace(active_session_id="mesh-session", mesh_service=service)
    tab.standalone_controller = replacement  # type: ignore[assignment]
    tab.standalone_rust_prepare_request_id = 37
    tab.standalone_rust_prepare_active_request_id = 37
    tab.standalone_rust_prepare_controller = original
    tab.standalone_rust_prepare_service = service
    tab.standalone_rust_prepare_session_id = "mesh-session"
    tab.standalone_rust_prepare_process_generation = 9
    tab.standalone_rust_process_generation = 9
    tab.standalone_rust_target_controller = original
    stale_session = SimpleNamespace(
        root=tmp_path / "identity-stale",
        authoritative_service=service,
        authoritative_session_id="mesh-session",
        process_generation=9,
    )
    disposed: list[object] = []
    launched: list[object] = []
    tab._start_rust_dispose_worker = (  # type: ignore[method-assign]
        lambda session, _root: disposed.append(session)
    )
    tab._launch_rust_editor_process = launched.append  # type: ignore[method-assign]

    tab._handle_rust_session_prepared(37, stale_session)

    assert disposed == [stale_session]
    assert launched == []
    assert tab.standalone_rust_prepare_request_id == 38
    _dispose(tab)


def test_prepared_result_rejects_replaced_service_on_same_controller_and_session(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    original_service = object()
    replacement_service = object()
    controller = SimpleNamespace(
        active_session_id="mesh-session",
        mesh_service=replacement_service,
    )
    tab.standalone_controller = controller  # type: ignore[assignment]
    tab.standalone_rust_prepare_request_id = 41
    tab.standalone_rust_prepare_active_request_id = 41
    tab.standalone_rust_prepare_controller = controller
    tab.standalone_rust_prepare_service = original_service
    tab.standalone_rust_prepare_session_id = "mesh-session"
    tab.standalone_rust_prepare_process_generation = 11
    tab.standalone_rust_process_generation = 11
    tab.standalone_rust_target_controller = controller
    stale_session = SimpleNamespace(
        root=tmp_path / "service-stale",
        authoritative_service=original_service,
        authoritative_session_id="mesh-session",
        process_generation=11,
    )
    disposed: list[object] = []
    launched: list[object] = []
    tab._start_rust_dispose_worker = (  # type: ignore[method-assign]
        lambda session, _root: disposed.append(session)
    )
    tab._launch_rust_editor_process = launched.append  # type: ignore[method-assign]

    tab._handle_rust_session_prepared(41, stale_session)

    assert disposed == [stale_session]
    assert launched == []
    assert tab.standalone_rust_prepare_request_id == 42
    assert tab.standalone_rust_prepare_service is None
    _dispose(tab)


def test_late_prepared_sessions_queue_behind_disposer_without_clearing_live_refs(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    application = QApplication.instance() or QApplication([])
    owned_root = tmp_path / "rust-owned"
    owned_root.mkdir()
    tab.standalone_rust_owned_root = owned_root
    active_dispose_session = object()
    active_dispose_root = tmp_path / "active-dispose"
    live_session = object()
    live_root = tmp_path / "live-session"
    live_controller = object()
    tab.standalone_rust_authoring_session = live_session
    tab.standalone_rust_session_root = live_root
    tab.standalone_rust_target_controller = live_controller
    active_thread = QThread(tab)
    tab.standalone_rust_dispose_thread = active_thread
    tab.standalone_rust_dispose_worker = SimpleNamespace(stop=lambda: None)
    tab.standalone_rust_dispose_active_session = active_dispose_session
    tab.standalone_rust_dispose_active_root = active_dispose_root

    def disposable_session(name: str) -> object:
        root = owned_root / name
        root.mkdir()
        root_stat = root.stat()
        return SimpleNamespace(
            root=root,
            root_identity=(int(root_stat.st_dev), int(root_stat.st_ino)),
            closed=False,
            cancel=lambda: None,
        )

    late_one = disposable_session("session-late-one")
    late_two = disposable_session("session-late-two")

    tab._handle_rust_session_prepared(71, late_one)
    tab._handle_rust_session_prepared(72, late_two)

    assert tab.standalone_rust_dispose_queue == [
        (late_one, late_one.root),
        (late_two, late_two.root),
    ]

    tab._handle_rust_dispose_thread_finished(active_thread)

    deadline = time.monotonic() + 5.0
    while (
        tab.standalone_rust_dispose_thread is not None
        or tab.standalone_rust_dispose_queue
    ) and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    application.processEvents()

    assert tab.standalone_rust_dispose_thread is None
    assert tab.standalone_rust_dispose_queue == []
    assert not late_one.root.exists()
    assert not late_two.root.exists()
    assert tab.standalone_rust_authoring_session is live_session
    assert tab.standalone_rust_session_root == live_root
    assert tab.standalone_rust_target_controller is live_controller
    active_thread.deleteLater()
    _dispose(tab)


def test_rust_open_during_dispose_queues_exactly_one_relaunch_for_same_session(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    controller = SimpleNamespace(active_session_id="current-session", mesh_service=object())
    disposed_session = object()
    disposed_root = tmp_path / "disposed-session"
    dispose_thread = QThread(tab)
    tab.standalone_controller = controller  # type: ignore[assignment]
    tab.standalone_rust_process_generation = 7
    tab.standalone_rust_authoring_session = disposed_session
    tab.standalone_rust_session_root = disposed_root
    tab.standalone_rust_dispose_thread = dispose_thread
    tab.standalone_rust_dispose_worker = SimpleNamespace(stop=lambda: None)
    tab.standalone_rust_dispose_active_session = disposed_session
    tab.standalone_rust_dispose_active_root = disposed_root

    tab._start_rust_editor_requested(controller)
    first_request = tab.standalone_rust_relaunch_request
    tab._start_rust_editor_requested(controller)

    assert first_request is not None
    assert tab.standalone_rust_relaunch_request is first_request
    assert "starting or running" in tab.standalone_status_label.text().lower()

    launched: list[object] = []
    tab._start_selected_mesh_editor = launched.append  # type: ignore[method-assign]
    tab._handle_rust_dispose_thread_finished(dispose_thread)

    assert launched == [controller]
    assert tab.standalone_rust_relaunch_request is None
    dispose_thread.deleteLater()
    tab.standalone_controller = None
    _dispose(tab)


def test_queued_rust_relaunch_rejects_session_and_generation_changes(
    tmp_path: Path,
) -> None:
    for index, stale_kind in enumerate(("session", "generation"), start=1):
        case_root = tmp_path / str(index)
        case_root.mkdir()
        tab = _tab(case_root, backend=MESH_EDITOR_BACKEND_RUST)
        controller = SimpleNamespace(active_session_id="current-session", mesh_service=object())
        disposed_session = object()
        disposed_root = tmp_path / f"disposed-{stale_kind}"
        dispose_thread = QThread(tab)
        tab.standalone_controller = controller  # type: ignore[assignment]
        tab.standalone_rust_process_generation = 11
        tab.standalone_rust_authoring_session = disposed_session
        tab.standalone_rust_session_root = disposed_root
        tab.standalone_rust_dispose_thread = dispose_thread
        tab.standalone_rust_dispose_worker = SimpleNamespace(stop=lambda: None)
        tab.standalone_rust_dispose_active_session = disposed_session
        tab.standalone_rust_dispose_active_root = disposed_root
        assert tab._queue_rust_relaunch_after_dispose(controller)

        if stale_kind == "session":
            controller.active_session_id = "replacement-session"
        else:
            tab.standalone_rust_process_generation += 1

        launched: list[object] = []
        tab._start_selected_mesh_editor = launched.append  # type: ignore[method-assign]
        tab._handle_rust_dispose_thread_finished(dispose_thread)

        assert launched == []
        assert tab.standalone_rust_relaunch_request is None
        dispose_thread.deleteLater()
        tab.standalone_controller = None
        _dispose(tab)


def test_rust_ready_status_keeps_the_explicit_untextured_reason(tmp_path: Path) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    tab.standalone_rust_hello_received = True
    tab.standalone_rust_texture_unavailable_reason = (
        "Resolved Archive Browser material bindings did not contain readable DDS texture payloads."
    )

    tab._handle_rust_ready({})

    assert "untextured neutral surface" in tab.standalone_status_label.text()
    assert "readable DDS" in tab.standalone_status_label.text()
    _dispose(tab)


def test_process_launch_revalidates_provenance_after_shadow_preparation(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    resolution = _provenanced_resolution(tmp_path / "helper")
    tab.standalone_rust_executable_path = Path(resolution.resolved_path)
    tab.standalone_rust_launch_executable_signature = rust_mesh_editor_file_signature(
        resolution
    )
    failures: list[str] = []
    tab._fail_rust_editor = (  # type: ignore[method-assign]
        lambda message, **_kwargs: failures.append(message)
    )

    with (
        patch(
            "cdmw.ui.mesh_editor.tab_rust_editor.resolve_rust_mesh_editor",
            return_value=resolution,
        ),
        patch(
            "cdmw.ui.mesh_editor.tab_rust_editor.validate_rust_mesh_editor_package",
            return_value="Rust provenance renderer does not match",
        ),
    ):
        tab._launch_rust_editor_process(
            SimpleNamespace(manifest_path=tmp_path / "session.json")
        )

    assert tab.standalone_rust_process is None
    assert failures and "renderer does not match" in failures[0]
    _dispose(tab)


def test_process_launch_rejects_a_compatible_package_swap_during_preparation(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    original = _provenanced_resolution(tmp_path / "original", payload=b"original-helper")
    replacement = _provenanced_resolution(
        tmp_path / "replacement",
        payload=b"replacement-helper",
    )
    tab.standalone_rust_executable_path = Path(original.resolved_path)
    tab.standalone_rust_launch_executable_signature = rust_mesh_editor_file_signature(
        original
    )
    failures: list[str] = []
    tab._fail_rust_editor = (  # type: ignore[method-assign]
        lambda message, **_kwargs: failures.append(message)
    )

    with patch(
        "cdmw.ui.mesh_editor.tab_rust_editor.resolve_rust_mesh_editor",
        return_value=replacement,
    ):
        tab._launch_rust_editor_process(
            SimpleNamespace(manifest_path=tmp_path / "session.json")
        )

    assert tab.standalone_rust_process is None
    assert failures and "changed while its shadow session" in failures[0]
    _dispose(tab)


def test_direct_route_never_launches_vortice_even_with_legacy_preference(tmp_path: Path) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_VORTICE)
    calls: list[tuple[str, object]] = []
    controller = object()
    tab._dotnet_editor_executable_path = lambda **_kwargs: Path("vortice.exe")  # type: ignore[method-assign]
    tab._start_dotnet_editor_requested = (  # type: ignore[method-assign]
        lambda target, *, embedded: calls.append(("vortice", (target, embedded)))
    )
    tab._start_rust_editor_requested = lambda target: calls.append(("rust", target))  # type: ignore[method-assign]

    tab._start_selected_mesh_editor(controller)
    assert calls == [("rust", controller)]
    _dispose(tab)


def test_rust_launch_waits_for_material_context_then_resumes_the_same_session(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    controller = SimpleNamespace(active_session_id="mesh-session")
    tab.standalone_controller = controller  # type: ignore[assignment]
    tab._archive_material_preview_model_ready = lambda _model: False  # type: ignore[method-assign]
    tab._start_archive_material_context_resolution = lambda: True  # type: ignore[method-assign]
    starts: list[object] = []
    tab._start_rust_editor_requested = starts.append  # type: ignore[method-assign]

    tab._start_selected_mesh_editor(controller)

    assert starts == []
    assert tab.standalone_rust_material_wait_session_id == "mesh-session"
    assert tab.standalone_rust_material_wait_controller is controller
    assert tab._resume_rust_editor_after_material_context(available=True)
    assert starts == [controller]
    assert tab.standalone_rust_material_wait_session_id == ""
    assert tab.standalone_rust_material_wait_controller is None
    _dispose(tab)


def test_rust_launch_waits_when_material_metadata_only_has_a_non_dds_preview(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    controller = SimpleNamespace(active_session_id="mesh-session")
    tab.standalone_controller = controller  # type: ignore[assignment]
    preview_model = SimpleNamespace(
        meshes=[SimpleNamespace(preview_texture_path="decoded-preview.png")]
    )
    tab.standalone_archive_material_preview_model = preview_model
    assert tab._archive_material_preview_model_ready(preview_model)
    resolutions: list[bool] = []
    tab._start_archive_material_context_resolution = (  # type: ignore[method-assign]
        lambda: resolutions.append(True) or True
    )
    starts: list[object] = []
    tab._start_rust_editor_requested = starts.append  # type: ignore[method-assign]

    tab._start_selected_mesh_editor(controller)

    assert resolutions == [True]
    assert starts == []
    assert tab.standalone_rust_material_wait_session_id == "mesh-session"
    _dispose(tab)


def test_rust_launch_verifies_the_owned_package_even_when_dds_metadata_and_index_exist(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    controller = SimpleNamespace(active_session_id="mesh-session")
    tab.standalone_controller = controller  # type: ignore[assignment]
    preview_model = SimpleNamespace(
        meshes=[SimpleNamespace(preview_texture_dds_path="body.dds")]
    )
    tab.standalone_archive_material_preview_model = preview_model
    tab._archive_texture_indexes = lambda: (  # type: ignore[method-assign]
        {},
        {"body.dds": (object(),)},
    )
    resolutions: list[bool] = []
    tab._start_archive_material_context_resolution = (  # type: ignore[method-assign]
        lambda: resolutions.append(True) or True
    )
    starts: list[object] = []
    tab._start_rust_editor_requested = starts.append  # type: ignore[method-assign]

    tab._start_selected_mesh_editor(controller)

    assert resolutions == [True]
    assert starts == []
    assert tab.standalone_rust_material_wait_session_id == "mesh-session"
    _dispose(tab)


def test_rust_launch_skips_resolution_after_package_and_model_are_published_together(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    controller = SimpleNamespace(active_session_id="mesh-session")
    tab.standalone_controller = controller  # type: ignore[assignment]
    tab.archive_material_context_verified_for_rust = True
    resolutions: list[bool] = []
    tab._start_archive_material_context_resolution = (  # type: ignore[method-assign]
        lambda: resolutions.append(True) or True
    )
    starts: list[object] = []
    tab._start_rust_editor_requested = starts.append  # type: ignore[method-assign]

    tab._start_selected_mesh_editor(controller)

    assert resolutions == []
    assert starts == [controller]
    assert tab.standalone_rust_material_wait_session_id == ""
    _dispose(tab)


def test_cancelled_or_stale_material_wait_cannot_launch_rust(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    original = SimpleNamespace(active_session_id="original-session")
    tab.standalone_controller = original  # type: ignore[assignment]
    tab._archive_material_preview_model_ready = lambda _model: False  # type: ignore[method-assign]
    tab._start_archive_material_context_resolution = lambda: True  # type: ignore[method-assign]
    starts: list[object] = []
    tab._start_rust_editor_requested = starts.append  # type: ignore[method-assign]

    tab._start_selected_mesh_editor(original)
    tab.standalone_controller = SimpleNamespace(active_session_id="original-session")  # type: ignore[assignment]
    assert tab._resume_rust_editor_after_material_context(available=True)
    assert starts == []

    tab.standalone_controller = original  # type: ignore[assignment]
    tab._start_selected_mesh_editor(original)
    tab._cancel_rust_material_context_wait()
    assert not tab._resume_rust_editor_after_material_context(available=True)
    assert starts == []
    _dispose(tab)


def test_material_worker_result_resumes_the_waiting_rust_launch(tmp_path: Path) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    controller = SimpleNamespace(active_session_id="mesh-session")
    tab.standalone_controller = controller  # type: ignore[assignment]
    tab.standalone_rust_material_wait_session_id = "mesh-session"
    tab.standalone_rust_material_wait_controller = controller
    tab.archive_material_context_request_id = 19
    tab.archive_material_context_pending = True
    starts: list[object] = []
    tab._start_rust_editor_requested = starts.append  # type: ignore[method-assign]
    preview_model = SimpleNamespace(meshes=())

    tab._handle_archive_material_context_resolved(19, preview_model)

    assert tab.standalone_archive_material_preview_model is preview_model
    assert not tab.archive_material_context_pending
    assert starts == [controller]
    _dispose(tab)


def test_material_context_result_atomically_replaces_package_before_rust_resumes(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    entry = _archive_entry(tmp_path)
    tab.current_archive_selection = entry
    controller = SimpleNamespace(active_session_id="mesh-session")
    tab.standalone_controller = controller  # type: ignore[assignment]
    tab.standalone_rust_material_wait_session_id = "mesh-session"
    tab.standalone_rust_material_wait_controller = controller
    tab.archive_material_context_request_id = 23
    tab.archive_material_context_request_identity = entry.identity
    tab.archive_material_context_pending = True
    old_releases: list[bool] = []
    new_releases: list[bool] = []
    old_lease = SimpleNamespace(release=lambda: old_releases.append(True))
    new_lease = SimpleNamespace(release=lambda: new_releases.append(True))
    tab.archive_material_context_package_path = str(tmp_path / "geometry-package")
    tab.archive_material_context_package_lease = old_lease
    preview_model = SimpleNamespace(meshes=())
    resolved_package = tmp_path / "textured-package"
    result = SimpleNamespace(
        preview_model=preview_model,
        material_package_path=str(resolved_package),
        material_package_lease=new_lease,
        source_identity=entry.identity,
        release=lambda: new_lease.release(),
    )
    starts: list[object] = []
    tab._start_rust_editor_requested = starts.append  # type: ignore[method-assign]

    tab._handle_archive_material_context_result(23, result)

    assert old_releases == [True]
    assert new_releases == []
    assert tab.archive_material_context_package_path == str(resolved_package)
    assert tab.archive_material_context_package_lease is new_lease
    assert tab.archive_material_context_source_identity == entry.identity
    assert tab.standalone_archive_material_preview_model is preview_model
    assert tab.archive_material_context_verified_for_rust
    assert not tab.archive_material_context_pending
    assert starts == [controller]
    tab._replace_archive_material_context_package_lease(None)
    assert new_releases == [True]
    _dispose(tab)


def test_stale_material_context_result_releases_its_package_without_publication(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    tab.archive_material_context_request_id = 31
    tab.archive_material_context_package_path = str(tmp_path / "current-package")
    releases: list[bool] = []
    lease = SimpleNamespace(release=lambda: releases.append(True))
    result = SimpleNamespace(
        preview_model=SimpleNamespace(meshes=()),
        material_package_path=str(tmp_path / "stale-package"),
        material_package_lease=lease,
        release=lambda: lease.release(),
    )

    tab._handle_archive_material_context_result(30, result)

    assert releases == [True]
    assert tab.archive_material_context_package_path == str(tmp_path / "current-package")
    assert tab.standalone_archive_material_preview_model is None
    assert not tab.archive_material_context_verified_for_rust
    _dispose(tab)


def test_full_material_resolution_clears_the_stale_geometry_only_package(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    entry = _archive_entry(tmp_path)
    tab.current_archive_selection = entry
    controller = SimpleNamespace(active_session_id="mesh-session")
    tab.standalone_controller = controller  # type: ignore[assignment]
    tab.standalone_rust_material_wait_session_id = "mesh-session"
    tab.standalone_rust_material_wait_controller = controller
    tab.archive_material_context_request_id = 41
    tab.archive_material_context_request_identity = entry.identity
    stale_releases: list[bool] = []
    tab.archive_material_context_package_path = str(tmp_path / "geometry-only-package")
    tab.archive_material_context_package_lease = SimpleNamespace(
        release=lambda: stale_releases.append(True)
    )
    preview_model = SimpleNamespace(
        meshes=(
            SimpleNamespace(
                preview_texture_dds_path=str(tmp_path / "resolved-cache.dds")
            ),
        )
    )
    result = SimpleNamespace(
        preview_model=preview_model,
        material_package_path="",
        material_package_lease=None,
        source_identity=entry.identity,
        release=lambda: None,
    )
    starts: list[object] = []
    tab._start_rust_editor_requested = starts.append  # type: ignore[method-assign]

    tab._handle_archive_material_context_result(41, result)

    assert stale_releases == [True]
    assert tab.archive_material_context_package_path == ""
    assert tab.archive_material_context_package_lease is None
    assert tab.standalone_archive_material_preview_model is preview_model
    assert tab.archive_material_context_verified_for_rust
    assert tab.archive_material_context_source_identity == entry.identity
    assert starts == [controller]
    _dispose(tab)


def test_material_context_result_rejects_a_same_path_archive_collision(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    entry = _archive_entry(tmp_path)
    stale_entry = _archive_entry(tmp_path, package="0010", offset=8, paz_index=1)
    tab.current_archive_selection = entry
    tab.archive_material_context_request_id = 47
    tab.archive_material_context_request_identity = entry.identity
    tab.archive_material_context_pending = True
    old_lease = SimpleNamespace(release=lambda: None)
    stale_releases: list[bool] = []
    stale_lease = SimpleNamespace(release=lambda: stale_releases.append(True))
    tab.archive_material_context_package_path = str(tmp_path / "current-package")
    tab.archive_material_context_package_lease = old_lease
    result = SimpleNamespace(
        preview_model=SimpleNamespace(meshes=()),
        material_package_path=str(tmp_path / "stale-package"),
        material_package_lease=stale_lease,
        source_identity=stale_entry.identity,
        release=lambda: stale_lease.release(),
    )

    tab._handle_archive_material_context_result(47, result)

    assert stale_releases == [True]
    assert tab.archive_material_context_package_path == str(tmp_path / "current-package")
    assert tab.archive_material_context_package_lease is old_lease
    assert tab.standalone_archive_material_preview_model is None
    assert not tab.archive_material_context_verified_for_rust
    assert tab.archive_material_context_source_identity is None
    _dispose(tab)


def test_material_context_cancel_invalidates_queued_result_without_live_worker(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    tab.archive_material_context_request_id = 19
    tab.archive_material_context_worker = None
    tab.archive_material_context_thread = None

    tab._cancel_archive_material_context_resolution()

    assert tab.archive_material_context_request_id == 20
    assert not tab.archive_material_context_pending
    _dispose(tab)


def test_new_rust_session_restarts_material_resolution_after_old_thread_cleanup(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    entry = ArchiveEntry(
        path="character/model/new-session.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=64,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    controller = SimpleNamespace(active_session_id="new-rust-session")
    tab.current_archive_selection = entry
    tab.standalone_controller = controller  # type: ignore[assignment]

    class OldWorker:
        def deleteLater(self) -> None:  # noqa: N802 - Qt-compatible test double
            pass

    class OldThread:
        def wait(self, _milliseconds: int) -> bool:
            return True

        def deleteLater(self) -> None:  # noqa: N802 - Qt-compatible test double
            pass

    old_worker = OldWorker()
    old_thread = OldThread()
    tab.archive_material_context_worker = old_worker  # type: ignore[assignment]
    tab.archive_material_context_thread = old_thread  # type: ignore[assignment]
    tab.archive_material_context_pending = False
    starts: list[object] = []
    tab._start_rust_editor_requested = starts.append  # type: ignore[method-assign]

    tab._start_selected_mesh_editor(controller)

    assert starts == []
    assert tab.archive_material_context_pending
    assert tab.standalone_rust_material_wait_session_id == "new-rust-session"
    retry_entry = tab.archive_material_context_retry_after_cleanup_entry
    assert retry_entry.identity == entry.identity
    assert retry_entry is not entry

    restarts: list[ArchiveEntry] = []
    tab._start_archive_material_context_resolution = (  # type: ignore[method-assign]
        lambda target=None: restarts.append(target) or True
    )
    tab._cleanup_archive_material_context_worker(old_thread, old_worker)  # type: ignore[arg-type]
    app.processEvents()

    assert len(restarts) == 1
    assert restarts[0].identity == entry.identity
    assert starts == []
    assert tab._resume_rust_editor_after_material_context(available=True)
    assert starts == [controller]
    _dispose(tab)


def test_cancelling_deferred_material_restart_prevents_cleanup_from_replaying_it(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    entry = ArchiveEntry(
        path="character/model/cancelled-session.pac",
        pamt_path=tmp_path / "0009" / "0.pamt",
        paz_file=tmp_path / "0009" / "0.paz",
        offset=80,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    controller = SimpleNamespace(active_session_id="cancelled-rust-session")
    tab.current_archive_selection = entry
    tab.standalone_controller = controller  # type: ignore[assignment]

    class OldWorker:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

        def deleteLater(self) -> None:  # noqa: N802 - Qt-compatible test double
            pass

    class OldThread:
        def __init__(self) -> None:
            self.interrupted = False
            self.quit_requested = False

        def wait(self, _milliseconds: int) -> bool:
            return True

        def requestInterruption(self) -> None:  # noqa: N802
            self.interrupted = True

        def quit(self) -> None:
            self.quit_requested = True

        def deleteLater(self) -> None:  # noqa: N802 - Qt-compatible test double
            pass

    old_worker = OldWorker()
    old_thread = OldThread()
    tab.archive_material_context_worker = old_worker  # type: ignore[assignment]
    tab.archive_material_context_thread = old_thread  # type: ignore[assignment]
    tab.archive_material_context_pending = False

    assert tab._start_archive_material_context_resolution(entry)
    tab._cancel_archive_material_context_resolution()
    tab._cleanup_archive_material_context_worker(old_thread, old_worker)  # type: ignore[arg-type]
    app.processEvents()

    assert old_worker.stopped
    assert old_thread.interrupted and old_thread.quit_requested
    assert tab.archive_material_context_retry_after_cleanup_entry is None
    assert not tab.archive_material_context_pending
    _dispose(tab)


def test_replayed_and_wrong_generation_protocol_messages_are_rejected(tmp_path: Path) -> None:
    tab = _tab(tmp_path)
    tab.standalone_rust_authoring_session = SimpleNamespace(session_id="rust-session")  # type: ignore[assignment]
    tab.standalone_rust_process_generation = 4
    tab.standalone_rust_ready = True
    tab._start_next_rust_protocol_worker = lambda: None  # type: ignore[method-assign]
    errors: list[str] = []
    failures: list[str] = []
    tab._send_rust_error_response = (  # type: ignore[method-assign]
        lambda _request, message: errors.append(message)
    )
    tab._fail_rust_editor = (  # type: ignore[method-assign]
        lambda message, **_kwargs: failures.append(message)
    )
    event = {
        "event": "command_request",
        "protocol": "cdmw_rust_mesh_editor_protocol_v1",
        "session_id": "rust-session",
        "request_id": 1,
        "base_revision": 0,
        "process_generation": 4,
        "command": "state",
    }

    tab._handle_rust_protocol_event(dict(event))
    tab._handle_rust_protocol_event(dict(event))
    stale = dict(event, request_id=2, process_generation=3)
    tab._handle_rust_protocol_event(stale)

    assert len(tab.standalone_rust_protocol_queue) == 1
    assert errors == ["Mesh Editor request was replayed or out of order"]
    assert failures and "generation is stale" in failures[0]
    tab.standalone_rust_authoring_session = None
    _dispose(tab)


def test_shutdown_inventory_includes_all_rust_lifecycle_workers(tmp_path: Path) -> None:
    tab = _tab(tmp_path)
    names = {name for name, _thread, _worker in tab.iter_shutdown_workers()}
    assert {
        "standalone_rust_prepare",
        "standalone_rust_protocol",
        "standalone_rust_dispose",
    }.issubset(names)
    _dispose(tab)


def test_finish_close_requests_authoring_cancel_and_waits_for_terminal_result(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path)
    calls: list[str] = []
    session = SimpleNamespace(
        closed=False,
        request_cancel=lambda: calls.append("cancel") or True,
    )
    worker = SimpleNamespace(stop=lambda: calls.append("worker_stop"))
    tab.standalone_rust_authoring_session = session  # type: ignore[assignment]
    tab.standalone_rust_protocol_thread = object()  # type: ignore[assignment]
    tab.standalone_rust_protocol_worker = worker  # type: ignore[assignment]
    tab.standalone_rust_active_event = {"event": "finish_request"}

    tab._stop_rust_editor_process(reason="close")

    assert calls == ["cancel"]
    assert tab.standalone_rust_stop_after_protocol is True
    assert "unchanged" in tab.standalone_status_label.text().lower()
    tab.standalone_rust_protocol_thread = None
    tab.standalone_rust_protocol_worker = None
    tab.standalone_rust_authoring_session = None
    _dispose(tab)


def test_finish_close_does_not_claim_unchanged_after_commit_boundary(tmp_path: Path) -> None:
    tab = _tab(tmp_path)
    session = SimpleNamespace(closed=False, request_cancel=lambda: False)
    tab.standalone_rust_authoring_session = session  # type: ignore[assignment]
    tab.standalone_rust_protocol_thread = object()  # type: ignore[assignment]
    tab.standalone_rust_protocol_worker = SimpleNamespace(stop=lambda: None)  # type: ignore[assignment]
    tab.standalone_rust_active_event = {"event": "finish_request"}

    tab._stop_rust_editor_process(reason="close")

    assert "waiting for its terminal result" in tab.standalone_status_label.text().lower()
    assert "unchanged" not in tab.standalone_status_label.text().lower()
    tab.standalone_rust_protocol_thread = None
    tab.standalone_rust_protocol_worker = None
    tab.standalone_rust_authoring_session = None
    _dispose(tab)


def test_failed_to_start_detaches_process_before_cleanup(tmp_path: Path) -> None:
    tab = _tab(tmp_path)
    process = QProcess(tab)
    tab.standalone_rust_process = process
    failures: list[str] = []
    tab._fail_rust_editor = lambda message, **_kwargs: failures.append(message)  # type: ignore[method-assign]

    tab._handle_rust_process_error(process, QProcess.ProcessError.FailedToStart)

    assert tab.standalone_rust_process is None
    assert failures and "process failed" in failures[0].lower()
    _dispose(tab)


def test_launch_requests_a_full_rust_backtrace(tmp_path: Path) -> None:
    tab = _tab(tmp_path, backend=MESH_EDITOR_BACKEND_RUST)
    resolution = _provenanced_resolution(tmp_path / "full-backtrace-helper")
    tab.standalone_rust_executable_path = Path(resolution.resolved_path)
    tab.standalone_rust_launch_executable_signature = rust_mesh_editor_file_signature(
        resolution
    )
    process = _LaunchProcess()

    with (
        patch(
            "cdmw.ui.mesh_editor.tab_rust_editor.resolve_rust_mesh_editor",
            return_value=resolution,
        ),
        patch("cdmw.ui.mesh_editor.tab_rust_editor.QProcess", return_value=process),
    ):
        tab._launch_rust_editor_process(
            SimpleNamespace(manifest_path=tmp_path / "session.json")
        )

    assert process.start_called
    assert process.environment.value("RUST_BACKTRACE") == "full"
    assert process.arguments[:2] == ["--cdmw-session", str(tmp_path / "session.json")]
    assert process.arguments[2] == "--embedded-parent-hwnd"
    assert int(process.arguments[3]) > 0
    tab.standalone_rust_process = None
    _dispose(tab)


def test_fast_exit_drains_both_streams_and_keeps_the_panic_not_backtrace_note(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path)
    final_event = {"event": "terminal-before-ready-read"}
    panic = (
        "renderer startup\n"
        "thread 'main' panicked at apps/cdmw_mesh_lab/src/main.rs:42:9:\n"
        "request_device failed: DXGI_ERROR_DEVICE_REMOVED\n"
        "stack backtrace:\n"
        + "".join(f"{index}: cdmw_mesh_lab::frame_{index}\n" for index in range(4_000))
        + "note: Some details are omitted, run with `RUST_BACKTRACE=full` for a verbose backtrace.\n"
    )
    process = _BufferedProcess(
        stdout_chunks=((json.dumps(final_event) + "\n").encode("utf-8"),),
        stderr_chunks=(panic.encode("utf-8"),),
    )
    events: list[dict[str, object]] = []
    tab.standalone_rust_process = process  # type: ignore[assignment]
    tab._handle_rust_protocol_event = events.append  # type: ignore[method-assign]

    tab._handle_rust_process_finished(process, 101, QProcess.ExitStatus.CrashExit)  # type: ignore[arg-type]

    status = tab.standalone_status_label.text()
    assert events == [final_event]
    assert process.deleted
    assert "panicked at apps/cdmw_mesh_lab/src/main.rs:42:9" in status
    assert "request_device failed: DXGI_ERROR_DEVICE_REMOVED" in status
    assert "Some details are omitted" not in status
    assert "frame_3999" not in status
    assert len(status) < 2_500
    _dispose(tab)


def test_crash_error_uses_output_that_only_arrives_with_finished(tmp_path: Path) -> None:
    tab = _tab(tmp_path)
    final_event = {"event": "final-after-error"}
    process = _BufferedProcess(
        stdout_chunks=(b"", (json.dumps(final_event) + "\n").encode("utf-8")),
        stderr_chunks=(
            b"",
            (
                "thread 'main' panicked at crates/renderer/src/device.rs:88:5:\n"
                "no compatible D3D12 adapter was available\n"
                "stack backtrace:\n"
                "0: cdmw_mesh_lab::renderer::open\n"
            ).encode("utf-8"),
        ),
    )
    events: list[dict[str, object]] = []
    tab.standalone_rust_process = process  # type: ignore[assignment]
    tab._handle_rust_protocol_event = events.append  # type: ignore[method-assign]

    tab._handle_rust_process_error(process, QProcess.ProcessError.Crashed)  # type: ignore[arg-type]
    assert "process failed" in tab.standalone_status_label.text().lower()

    tab._handle_rust_process_finished(process, 101, QProcess.ExitStatus.CrashExit)  # type: ignore[arg-type]

    status = tab.standalone_status_label.text()
    assert events == [final_event]
    assert "panicked at crates/renderer/src/device.rs:88:5" in status
    assert "no compatible D3D12 adapter was available" in status
    assert "renderer::open" not in status
    _dispose(tab)


def test_protocol_cancel_ack_uses_the_versioned_cancel_event() -> None:
    application = QApplication.instance() or QApplication([])
    calls: list[str] = []
    session = SimpleNamespace(
        closed=True,
        cancel=lambda: calls.append("cancel"),
    )
    event = {
        "event": "cancel",
        "protocol": "cdmw_rust_mesh_editor_protocol_v1",
        "session_id": "rust-session",
        "request_id": 8,
        "base_revision": 3,
        "process_generation": 4,
    }
    worker = MeshRustProtocolWorker(12, session, event)  # type: ignore[arg-type]
    completed: list[tuple[dict[str, object], bool]] = []
    worker.completed.connect(
        lambda _worker_id, _client_id, response, accepted: completed.append(
            (response, accepted)
        )
    )

    worker.run()
    application.processEvents()

    assert calls == ["cancel"]
    assert completed == [
        (
            {
                "event": "cancel",
                "protocol": "cdmw_rust_mesh_editor_protocol_v1",
                "session_id": "rust-session",
                "request_id": 8,
                "base_revision": 3,
                "process_generation": 4,
                "ok": True,
                "payload": {"status": "cancelled"},
            },
            False,
        )
    ]


def test_protocol_worker_preserves_qobject_event_when_moved_to_thread() -> None:
    event = {
        "event": "command_request",
        "request_id": 8,
    }
    worker = MeshRustProtocolWorker(12, SimpleNamespace(), event)  # type: ignore[arg-type]
    thread = QThread()

    assert callable(worker.event)
    assert callable(worker.thread)

    worker.moveToThread(thread)

    assert worker.thread() is thread

    thread.finished.connect(worker.deleteLater)
    thread.start()
    thread.quit()
    assert thread.wait(2_000)


def test_dispose_worker_removes_owned_root_and_reports_completion(
    tmp_path: Path,
) -> None:
    owned_root = tmp_path / "rust-owned"
    session_root = owned_root / "session-success"
    session_root.mkdir(parents=True)
    root_stat = session_root.stat()
    session = SimpleNamespace(
        closed=False,
        root_identity=(int(root_stat.st_dev), int(root_stat.st_ino)),
        cancel=lambda: None,
    )
    worker = MeshRustSessionDisposeWorker(session, session_root, owned_root)
    completed: list[str] = []
    errors: list[str] = []
    finished: list[bool] = []
    worker.completed.connect(completed.append)
    worker.error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert completed == [str(session_root)]
    assert errors == []
    assert finished == [True]
    assert not session_root.exists()


def test_stopped_dispose_worker_still_removes_exact_owned_session_root(
    tmp_path: Path,
) -> None:
    owned_root = tmp_path / "rust-owned"
    session_root = owned_root / "session-exact"
    session_root.mkdir(parents=True)
    (session_root / "manifest.json").write_text("{}", encoding="utf-8")
    root_stat = session_root.stat()
    cancel_calls: list[str] = []

    def failing_cancel() -> None:
        cancel_calls.append("cancel")
        raise RuntimeError("shadow cancellation failed")

    session = SimpleNamespace(
        closed=False,
        root_identity=(int(root_stat.st_dev), int(root_stat.st_ino)),
        cancel=failing_cancel,
    )
    worker = MeshRustSessionDisposeWorker(session, session_root, owned_root)
    completed: list[str] = []
    errors: list[str] = []
    finished: list[bool] = []
    worker.completed.connect(completed.append)
    worker.error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.stop()
    worker.run()

    assert cancel_calls == ["cancel"]
    assert completed == []
    assert errors == []
    assert finished == [True]
    assert not session_root.exists()
    assert not list(owned_root.glob(".rust-mesh-dispose-*"))


def test_dispose_worker_stopped_during_cancel_still_removes_owned_root(
    tmp_path: Path,
) -> None:
    owned_root = tmp_path / "rust-owned"
    session_root = owned_root / "session-during-stop"
    session_root.mkdir(parents=True)
    (session_root / "document.json").write_text("{}", encoding="utf-8")
    root_stat = session_root.stat()
    cancel_entered = threading.Event()
    release_cancel = threading.Event()

    def blocking_cancel() -> None:
        cancel_entered.set()
        assert release_cancel.wait(timeout=5.0)

    session = SimpleNamespace(
        closed=False,
        root_identity=(int(root_stat.st_dev), int(root_stat.st_ino)),
        cancel=blocking_cancel,
    )
    worker = MeshRustSessionDisposeWorker(session, session_root, owned_root)
    completed: list[str] = []
    errors: list[str] = []
    finished: list[bool] = []
    worker.completed.connect(completed.append)
    worker.error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))
    run_thread = threading.Thread(target=worker.run)

    run_thread.start()
    try:
        assert cancel_entered.wait(timeout=5.0)
        worker.stop()
        release_cancel.set()
        run_thread.join(timeout=5.0)
    finally:
        release_cancel.set()
        run_thread.join(timeout=5.0)

    assert not run_thread.is_alive()
    application = QApplication.instance()
    if application is not None:
        application.processEvents()
    assert completed == []
    assert errors == []
    assert finished == [True]
    assert not session_root.exists()
    assert not list(owned_root.glob(".rust-mesh-dispose-*"))


def test_stopped_dispose_worker_cannot_remove_mismatched_session_root(
    tmp_path: Path,
) -> None:
    owned_root = tmp_path / "rust-owned"
    expected_root = owned_root / "session-expected"
    mismatched_root = owned_root / "session-mismatched"
    expected_root.mkdir(parents=True)
    mismatched_root.mkdir()
    (expected_root / "expected.json").write_text("expected", encoding="utf-8")
    (mismatched_root / "other.json").write_text("other", encoding="utf-8")
    expected_stat = expected_root.stat()
    session = SimpleNamespace(
        closed=True,
        root_identity=(int(expected_stat.st_dev), int(expected_stat.st_ino)),
        cancel=lambda: None,
    )
    worker = MeshRustSessionDisposeWorker(
        session,
        mismatched_root,
        owned_root,
    )
    completed: list[str] = []
    errors: list[str] = []
    finished: list[bool] = []
    worker.completed.connect(completed.append)
    worker.error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.stop()
    worker.run()

    assert completed == []
    assert errors == []
    assert finished == [True]
    assert (expected_root / "expected.json").read_text(encoding="utf-8") == "expected"
    assert (mismatched_root / "other.json").read_text(encoding="utf-8") == "other"
    assert not list(owned_root.glob(".rust-mesh-dispose-*"))


def test_dispose_worker_reports_identity_mismatch_and_finishes(
    tmp_path: Path,
) -> None:
    owned_root = tmp_path / "rust-owned"
    expected_root = owned_root / "session-expected"
    mismatched_root = owned_root / "session-mismatched"
    expected_root.mkdir(parents=True)
    mismatched_root.mkdir()
    (mismatched_root / "other.json").write_text("other", encoding="utf-8")
    expected_stat = expected_root.stat()
    session = SimpleNamespace(
        closed=True,
        root_identity=(int(expected_stat.st_dev), int(expected_stat.st_ino)),
        cancel=lambda: None,
    )
    worker = MeshRustSessionDisposeWorker(session, mismatched_root, owned_root)
    completed: list[str] = []
    errors: list[str] = []
    finished: list[bool] = []
    worker.completed.connect(completed.append)
    worker.error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert completed == []
    assert errors == ["Refusing to clean a replaced Rust Mesh session directory"]
    assert finished == [True]
    assert (mismatched_root / "other.json").read_text(encoding="utf-8") == "other"
    assert not list(owned_root.glob(".rust-mesh-dispose-*"))
