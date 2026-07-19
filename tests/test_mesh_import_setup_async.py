from __future__ import annotations

import dataclasses
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QGroupBox, QPushButton, QWidget

from cdmw.core.archive_mesh_import_preview import build_mesh_import_preview
from cdmw.core.mesh_preflight import MeshImportPreflight
from cdmw.domain.mesh.session import InGameMeshSwapScopeSelection, MeshImportSetupSelection
from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.modding.scene_importer import SceneImportResult
from cdmw.ui.archive_browser.mesh_import_export import ArchiveMeshImportExportMixin
from cdmw.ui.archive_browser.mesh_direct_patch import ArchiveMeshDirectPatchMixin
from cdmw.ui.archive_browser.mesh_import_preflight_controller import (
    MeshImportSetupPreflightRequest,
    MeshImportSetupPreflightResult,
)
from cdmw.ui.archive_browser.mesh_launch_flow import ArchiveMeshLaunchFlowMixin
from cdmw.ui.archive_browser.mesh_setup_helpers import ArchiveMeshSetupHelperMixin
from cdmw.ui.archive_browser.mesh_swap_support import ArchiveMeshSwapSupportMixin
from cdmw.ui.archive_browser.mesh_swap_scope_preflight import (
    ArchiveMeshSwapScopePreflightRequest,
    ArchiveMeshSwapScopePreflightResult,
    prepare_archive_mesh_swap_scope,
)
from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext


def _entry(path: str, offset: int) -> ArchiveEntry:
    return ArchiveEntry(path, Path("0009/0.pamt"), Path("0009/0.paz"), offset, 1, 1, 0, 0)


def _dependencies(selected: ArchiveEntry, *entries: ArchiveEntry) -> ArchiveWorkflowDependencyContext:
    ordered_by_identity = {entry.identity: entry for entry in (selected, *entries)}
    ordered = tuple(ordered_by_identity.values())
    return ArchiveWorkflowDependencyContext(
        selected_entry=selected,
        entries=ordered,
        entries_by_normalized_path={entry.path.casefold(): (entry,) for entry in ordered},
        entries_by_basename={entry.basename.casefold(): (entry,) for entry in ordered},
        remote=False,
    )


def test_direct_mesh_import_filter_includes_zip_archives() -> None:
    file_filter = ArchiveMeshDirectPatchMixin._archive_mesh_import_file_filter()

    assert "*.zip" in file_filter.split(";;", 1)[0]
    assert "Model Archives (*.zip)" in file_filter


def test_mesh_import_preview_honours_pre_cancel_before_io(tmp_path: Path) -> None:
    stop_event = threading.Event()
    stop_event.set()
    with pytest.raises(RunCancelled):
        build_mesh_import_preview(
            _entry("character/model/test.pac", 1),
            tmp_path / "missing.obj",
            stop_event=stop_event,
        )


class _AsyncTaskOwner:
    def __init__(self) -> None:
        self.archive_entries_by_basename: dict[str, tuple[ArchiveEntry, ...]] = {}
        self.archive_mesh_import_setup_request_id = 0
        self._shutting_down = False
        self.threads: list[threading.Thread] = []
        self.stop_events: list[threading.Event] = []
        self.worker_kwargs: list[dict[str, object]] = []
        self.prompted_request_ids: list[int] = []

    @staticmethod
    def _has_valid_obj_roundtrip_sidecar(_path: Path) -> bool:
        return False

    def _run_utility_task_when_idle(self, **kwargs: object) -> None:
        self.worker_kwargs.append(dict(kwargs))
        stop_event = threading.Event()
        self.stop_events.append(stop_event)

        def run() -> None:
            try:
                task = kwargs["task"]
                if kwargs.get("task_accepts_progress"):
                    result = task(  # type: ignore[operator]
                        lambda _message: None,
                        lambda _current, _total, _detail: None,
                        stop_event,
                    )
                else:
                    result = task(lambda _message: None, stop_event)  # type: ignore[operator]
            except Exception as exc:
                on_error = kwargs.get("on_error")
                if callable(on_error):
                    on_error(str(exc))
            else:
                on_complete = kwargs.get("on_complete")
                if callable(on_complete):
                    on_complete(result)

        thread = threading.Thread(target=run)
        self.threads.append(thread)
        thread.start()

    def _prompt_archive_mesh_import_setup(self, *_args: object, **kwargs: object) -> MeshImportSetupSelection:
        prepared = kwargs["prepared_preflight"]
        self.prompted_request_ids.append(prepared.request_id)  # type: ignore[attr-defined]
        return MeshImportSetupSelection(scene_path=Path("prepared.obj"), import_mode="static_replacement")


class _ImportOwner(_AsyncTaskOwner, ArchiveMeshImportExportMixin):
    pass


class _ImportDialogOwner(ArchiveMeshImportExportMixin, QWidget):
    pass


def _wait(thread: threading.Thread) -> None:
    thread.join(3.0)
    assert not thread.is_alive()


def test_mesh_import_setup_dialog_constructs_with_shared_control_text(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    owner = _ImportDialogOwner()
    captured: dict[str, object] = {}

    def reject(dialog: QDialog) -> int:
        captured["groups"] = [group.title() for group in dialog.findChildren(QGroupBox)]
        captured["buttons"] = [button.text() for button in dialog.findChildren(QPushButton)]
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", reject)
    result = owner._prompt_archive_mesh_import_setup(
        _entry("character/model/target.pac", 1),
        Path("source.gltf"),
        title="Mesh Import Setup",
        prepared_preflight=MeshImportSetupPreflightResult(
            request_id=1,
            scene_import_result=SceneImportResult(mesh=ParsedMesh(path="source.gltf")),
            original_mesh=None,
            profile=None,
            preflight=MeshImportPreflight("ready"),
            has_roundtrip_sidecar=False,
        ),
    )

    assert result is None
    assert "Preflight & Files" in captured["groups"]
    assert "Cancel" in captured["buttons"]
    assert app is QApplication.instance()


def test_mesh_import_preflight_dispatch_is_under_50ms_and_worker_owned() -> None:
    owner = _ImportOwner()
    main_thread = threading.get_ident()
    import_threads: list[int] = []
    completed: list[MeshImportSetupSelection | None] = []

    def slow_import(_path: Path, *, stop_event: threading.Event) -> SceneImportResult:
        import_threads.append(threading.get_ident())
        assert not stop_event.is_set()
        time.sleep(0.2)
        return SceneImportResult(mesh=ParsedMesh(path="source.obj"))

    with (
        patch("cdmw.ui.archive_browser.mesh_import_preflight_controller.import_scene_mesh_with_report", side_effect=slow_import),
        patch(
            "cdmw.ui.archive_browser.mesh_import_preflight_controller.read_archive_entry_baseline_data",
            return_value=type("Baseline", (), {"data": b"mesh"})(),
        ),
        patch("cdmw.ui.archive_browser.mesh_import_preflight_controller.parse_mesh", return_value=ParsedMesh(path="target.pac")),
        patch("cdmw.ui.archive_browser.mesh_import_preflight_controller.analyze_replacement_asset", return_value=None),
        patch(
            "cdmw.ui.archive_browser.mesh_import_preflight_controller.build_mesh_import_preflight",
            return_value=MeshImportPreflight("ready"),
        ),
    ):
        started = time.perf_counter()
        owner._prepare_archive_mesh_import_setup_async(
            _entry("character/model/target.pac", 1),
            Path("source.obj"),
            title="Setup",
            on_complete=completed.append,
        )
        elapsed = time.perf_counter() - started
        _wait(owner.threads[0])

    assert elapsed < 0.05
    assert import_threads == [owner.threads[0].ident]
    assert import_threads[0] != main_thread
    assert completed and isinstance(completed[0], MeshImportSetupSelection)
    assert owner.worker_kwargs[0]["task_accepts_progress"] is True
    assert owner.worker_kwargs[0]["task_accepts_cancel"] is True


def test_mesh_import_preflight_latest_request_wins() -> None:
    owner = _ImportOwner()
    release_first = threading.Event()
    first_started = threading.Event()

    def import_scene(path: Path, *, stop_event: threading.Event) -> SceneImportResult:
        if path.name == "first.obj":
            first_started.set()
            while not release_first.wait(0.005):
                if stop_event.is_set():
                    raise RunCancelled("Mesh import setup cancelled.")
        return SceneImportResult(mesh=ParsedMesh(path=str(path)))

    with (
        patch("cdmw.ui.archive_browser.mesh_import_preflight_controller.import_scene_mesh_with_report", side_effect=import_scene),
        patch(
            "cdmw.ui.archive_browser.mesh_import_preflight_controller.read_archive_entry_baseline_data",
            return_value=type("Baseline", (), {"data": b"mesh"})(),
        ),
        patch("cdmw.ui.archive_browser.mesh_import_preflight_controller.parse_mesh", return_value=ParsedMesh(path="target.pac")),
        patch("cdmw.ui.archive_browser.mesh_import_preflight_controller.analyze_replacement_asset", return_value=None),
        patch(
            "cdmw.ui.archive_browser.mesh_import_preflight_controller.build_mesh_import_preflight",
            return_value=MeshImportPreflight("ready"),
        ),
    ):
        owner._prepare_archive_mesh_import_setup_async(
            _entry("target.pac", 1),
            Path("first.obj"),
            title="First",
            on_complete=lambda _setup: None,
        )
        assert first_started.wait(1.0)
        owner._prepare_archive_mesh_import_setup_async(
            _entry("target.pac", 1),
            Path("second.obj"),
            title="Second",
            on_complete=lambda _setup: None,
        )
        _wait(owner.threads[1])
        release_first.set()
        _wait(owner.threads[0])

    assert owner.prompted_request_ids == [2]


def test_mesh_import_preflight_cancel_does_not_publish_or_warn() -> None:
    owner = _ImportOwner()
    started = threading.Event()

    def cancellable_import(_path: Path, *, stop_event: threading.Event) -> SceneImportResult:
        started.set()
        while not stop_event.wait(0.005):
            pass
        raise RunCancelled("Mesh import setup cancelled.")

    with (
        patch("cdmw.ui.archive_browser.mesh_import_preflight_controller.import_scene_mesh_with_report", side_effect=cancellable_import),
        patch("cdmw.ui.archive_browser.mesh_import_preflight_controller.QMessageBox.warning") as warning,
    ):
        owner._prepare_archive_mesh_import_setup_async(
            _entry("target.pac", 1),
            Path("source.obj"),
            title="Setup",
            on_complete=lambda _setup: None,
        )
        assert started.wait(1.0)
        owner.stop_events[0].set()
        _wait(owner.threads[0])

    assert owner.prompted_request_ids == []
    warning.assert_not_called()


class _SwapOwner(_AsyncTaskOwner, ArchiveMeshLaunchFlowMixin):
    def __init__(self) -> None:
        super().__init__()
        self.archive_in_game_mesh_swap_request_id = 0
        self.archive_in_game_mesh_swap_scope_request_id = 0
        self.archive_entries: list[ArchiveEntry] = []
        self.pending_in_game_mesh_swap_target = object()
        self.preflight_called = threading.Event()
        self.load_threads: list[int] = []

    @staticmethod
    def _same_archive_entry(_target: ArchiveEntry, _source: ArchiveEntry) -> bool:
        return False

    def set_status_message(self, *_args: object, **_kwargs: object) -> None:
        pass

    def _open_mesh_editor_for_entry(self, *_args: object, **_kwargs: object) -> None:
        pass

    @staticmethod
    def _prompt_archive_in_game_mesh_swap_scope(
        _target: ArchiveEntry,
        _source: ArchiveEntry,
        *,
        prepared_scope: ArchiveMeshSwapScopePreflightResult,
    ) -> InGameMeshSwapScopeSelection:
        assert prepared_scope.request_id > 0
        return InGameMeshSwapScopeSelection()

    def _load_archive_mesh_scene_import_result(
        self,
        _source: ArchiveEntry,
        *,
        stop_event: threading.Event,
    ) -> SceneImportResult:
        self.load_threads.append(threading.get_ident())
        assert not stop_event.is_set()
        time.sleep(0.2)
        return SceneImportResult(mesh=ParsedMesh(path="source.pac"))

    @staticmethod
    def _build_archive_swap_source_texture_evidence(
        _source: ArchiveEntry,
        *,
        dependencies: ArchiveWorkflowDependencyContext,
        stop_event: threading.Event,
    ) -> tuple[tuple[Path, ...], tuple[object, ...]]:
        assert isinstance(dependencies, ArchiveWorkflowDependencyContext)
        assert not stop_event.is_set()
        return (), ()

    @staticmethod
    def _build_in_game_mesh_swap_extra_specs(
        _target: ArchiveEntry,
        _source: ArchiveEntry,
        _scope: InGameMeshSwapScopeSelection,
        *,
        dependencies: ArchiveWorkflowDependencyContext,
        stop_event: threading.Event,
    ) -> tuple[object, ...]:
        assert isinstance(dependencies, ArchiveWorkflowDependencyContext)
        assert not stop_event.is_set()
        return ()

    @staticmethod
    def _archive_mesh_source_scene_path(_source: ArchiveEntry) -> Path:
        return Path("source.pac")

    @staticmethod
    def _archive_mesh_source_label(_source: ArchiveEntry) -> str:
        return "archive://source.pac"

    def _prepare_archive_mesh_import_setup_async(self, *_args: object, **_kwargs: object) -> int:
        self.preflight_called.set()
        return 1


def test_in_game_swap_archive_io_dispatch_is_under_50ms() -> None:
    owner = _SwapOwner()
    main_thread = threading.get_ident()
    scope_threads: list[int] = []

    def slow_scope(_owner: object, request: object, *, stop_event: threading.Event) -> object:
        scope_threads.append(threading.get_ident())
        assert not stop_event.is_set()
        time.sleep(0.1)
        return ArchiveMeshSwapScopePreflightResult(
            request_id=request.request_id,  # type: ignore[attr-defined]
            allow_character_scope=False,
            item_family_scope=False,
            same_weapon_folder=False,
            character_relationship_plan=None,
            source_related_entries=(),
            relationship_edges=(),
            unresolved_relationship_edges=(),
            source_sidecar_paths=frozenset(),
            source_appearance_paths=frozenset(),
            source_pbd_names=(),
            source_wrapper_count=0,
            target_wrapper_count=0,
            source_has_pbd_contract=False,
            source_has_larger_material_contract=False,
            preserve_source_contract_default=False,
        )

    with patch("cdmw.ui.archive_browser.mesh_launch_flow.prepare_archive_mesh_swap_scope", side_effect=slow_scope):
        started = time.perf_counter()
        owner._start_archive_in_game_mesh_swap(_entry("target.pac", 1), _entry("source.pac", 2))
        elapsed = time.perf_counter() - started
        _wait(owner.threads[0])
        deadline = time.perf_counter() + 1.0
        while len(owner.threads) < 2 and time.perf_counter() < deadline:
            time.sleep(0.005)
        assert len(owner.threads) == 2
        _wait(owner.threads[1])

    assert elapsed < 0.05
    assert scope_threads == [owner.threads[0].ident]
    assert scope_threads[0] != main_thread
    assert owner.load_threads == [owner.threads[1].ident]
    assert owner.load_threads[0] != main_thread
    assert owner.preflight_called.is_set()
    assert all(kwargs["task_accepts_progress"] is True for kwargs in owner.worker_kwargs)
    assert all(kwargs["task_accepts_cancel"] is True for kwargs in owner.worker_kwargs)


def test_v2_in_game_swap_freezes_merged_prepared_dependencies_without_legacy_catalogue(
    tmp_path: Path,
) -> None:
    target = _entry("character/model/target.pac", 11)
    target.prepared_path = tmp_path / "target.pac"
    source = _entry("character/model/source.pac", 22)
    source.prepared_path = tmp_path / "source.pac"
    sidecar = _entry("character/model/target.pac_xml", 33)
    sidecar.prepared_path = tmp_path / "target.pac_xml"
    texture = _entry("character/texture/source_d.dds", 44)
    texture.prepared_path = tmp_path / "source_d.dds"

    def snapshot(selected: ArchiveEntry, dependency: ArchiveEntry) -> ArchivePreviewDependencySet:
        entries = (selected, dependency)
        return ArchivePreviewDependencySet(
            session_id="session-a",
            entry_id=selected.offset,
            entries=entries,
            entries_by_normalized_path={entry.path.casefold(): (entry,) for entry in entries},
            entries_by_basename={entry.basename.casefold(): (entry,) for entry in entries},
            total_candidates=1,
            truncated=False,
        )

    snapshots = {
        target.identity: snapshot(target, sidecar),
        source.identity: snapshot(source, texture),
    }

    class _Bridge:
        displays_v2 = True

        @staticmethod
        def prepared_dependencies_for(entry: ArchiveEntry) -> ArchivePreviewDependencySet:
            return snapshots[entry.identity]

    class _PoisonEntries:
        def __iter__(self):
            raise AssertionError("v2 in-game swap touched the legacy global catalogue")

        def __bool__(self):
            raise AssertionError("v2 in-game swap inspected the legacy global catalogue")

    owner = _CapturedSwapOwner()
    owner.archive_remote_bridge = _Bridge()
    owner.archive_entries = _PoisonEntries()  # type: ignore[assignment]
    owner._start_archive_in_game_mesh_swap(target, source)

    captured: list[ArchiveWorkflowDependencyContext] = []

    def prepared_scope(
        _owner: object,
        request: ArchiveMeshSwapScopePreflightRequest,
        *,
        stop_event: threading.Event,
    ) -> ArchiveMeshSwapScopePreflightResult:
        assert not stop_event.is_set()
        captured.append(request.dependencies)
        return ArchiveMeshSwapScopePreflightResult(
            request_id=request.request_id,
            allow_character_scope=False,
            item_family_scope=False,
            same_weapon_folder=False,
            character_relationship_plan=None,
            source_related_entries=(),
            relationship_edges=(),
            unresolved_relationship_edges=(),
            source_sidecar_paths=frozenset(),
            source_appearance_paths=frozenset(),
            source_pbd_names=(),
            source_wrapper_count=0,
            target_wrapper_count=0,
            source_has_pbd_contract=False,
            source_has_larger_material_contract=False,
            preserve_source_contract_default=False,
        )

    with patch(
        "cdmw.ui.archive_browser.mesh_launch_flow.prepare_archive_mesh_swap_scope",
        side_effect=prepared_scope,
    ):
        owner.captured_tasks[0]["task"](
            lambda _message: None,
            lambda _current, _total, _detail: None,
            threading.Event(),
        )

    assert len(captured) == 1
    assert captured[0].remote
    assert tuple(entry.path for entry in captured[0].entries) == (
        "character/model/target.pac",
        "character/model/target.pac_xml",
        "character/model/source.pac",
        "character/texture/source_d.dds",
    )
    assert all(entry.prepared_path is not None for entry in captured[0].entries)


def test_v2_mesh_swap_preflight_real_support_uses_only_request_dependencies(
    tmp_path: Path,
) -> None:
    target = _entry("character/model/weapon/target.pac", 101)
    source = _entry("character/model/weapon/source.pac", 102)
    source_sidecar = _entry("character/model/weapon/source.pac_xml", 103)
    target_sidecar = _entry("character/model/weapon/target.pac_xml", 104)
    texture = _entry("character/texture/source_d.dds", 105)
    for entry in (target, source, source_sidecar, target_sidecar, texture):
        entry.prepared_path = tmp_path / entry.basename
    dependencies = ArchiveWorkflowDependencyContext(
        selected_entry=target,
        entries=(target, source, source_sidecar, target_sidecar, texture),
        entries_by_normalized_path={
            entry.path.casefold(): (entry,)
            for entry in (target, source, source_sidecar, target_sidecar, texture)
        },
        entries_by_basename={
            entry.basename.casefold(): (entry,)
            for entry in (target, source, source_sidecar, target_sidecar, texture)
        },
        remote=True,
    )

    class _Owner(ArchiveMeshSwapSupportMixin):
        @property
        def archive_entries(self) -> object:
            raise AssertionError("v2 mesh-swap support touched the legacy global catalogue")

        @property
        def archive_entries_by_normalized_path(self) -> object:
            raise AssertionError("v2 mesh-swap support touched the legacy path index")

        @property
        def archive_entries_by_basename(self) -> object:
            raise AssertionError("v2 mesh-swap support touched the legacy basename index")

        @property
        def archive_entries_by_extension(self) -> object:
            raise AssertionError("v2 mesh-swap support touched the legacy extension index")

    def sidecar_bytes(entry: ArchiveEntry, **_kwargs: object) -> tuple[bytes, bool, str]:
        payload = (
            b'<SkinnedMeshMaterialWrapper _pbdSimulationMaterialName="cloth">'
            if entry.identity == source_sidecar.identity
            else b"<SkinnedMeshMaterialWrapper>"
        )
        return payload, False, ""

    request = ArchiveMeshSwapScopePreflightRequest(
        1,
        target,
        source,
        dependencies,
    )
    with (
        patch(
            "cdmw.ui.archive_browser.mesh_swap_scope_preflight.read_archive_entry_data",
            side_effect=sidecar_bytes,
        ),
        patch(
            "cdmw.ui.archive_browser.mesh_swap_support.read_archive_entry_data",
            side_effect=sidecar_bytes,
        ),
    ):
        result = prepare_archive_mesh_swap_scope(
            _Owner(),
            request,
            stop_event=threading.Event(),
        )

    assert result.item_family_scope
    assert result.source_wrapper_count == 1
    assert result.target_wrapper_count == 1
    assert result.source_pbd_names == ("cloth",)


def test_mesh_swap_scope_preflight_honors_pre_cancel_and_is_frozen() -> None:
    target = _entry("target.pac", 1)
    source = _entry("source.pac", 2)
    request = ArchiveMeshSwapScopePreflightRequest(
        request_id=3,
        target_entry=target,
        source_entry=source,
        dependencies=_dependencies(target, source),
    )
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(RunCancelled):
        prepare_archive_mesh_swap_scope(object(), request, stop_event=cancelled)
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.request_id = 4  # type: ignore[misc]


def test_mesh_swap_scope_preflight_reads_material_contract_off_dialog_path() -> None:
    target = _entry("character/model/weapon/target.pac", 1)
    source = _entry("character/model/weapon/source.pac", 2)
    source_sidecar = _entry("character/model/weapon/source.pac_xml", 3)
    target_sidecar = _entry("character/model/weapon/target.pac_xml", 4)
    texture = _entry("character/texture/source_d.dds", 5)

    class Owner:
        archive_entries_by_extension: dict[str, tuple[ArchiveEntry, ...]] = {}

        @staticmethod
        def _archive_entries_allow_character_swap_scope(*_args: object) -> bool:
            return False

        @staticmethod
        def _archive_entry_is_equipment_model_for_swap(_entry: ArchiveEntry) -> bool:
            return True

        @staticmethod
        def _archive_entry_identity_key(entry: ArchiveEntry) -> object:
            return entry.identity

        @staticmethod
        def _archive_model_related_entries_for_swap(
            _entry: ArchiveEntry,
            *,
            dependencies: ArchiveWorkflowDependencyContext,
        ) -> tuple[ArchiveEntry, ...]:
            assert dependencies.entries
            return (source_sidecar, texture)

        @staticmethod
        def _archive_model_source_texture_entries_for_swap(
            _entry: ArchiveEntry,
            *,
            dependencies: ArchiveWorkflowDependencyContext,
            stop_event: threading.Event | None = None,
        ) -> tuple[ArchiveEntry, ...]:
            assert dependencies.entries
            assert stop_event is not None and not stop_event.is_set()
            return (texture,)

        @staticmethod
        def _archive_model_sidecar_entries_for_swap(
            entry: ArchiveEntry,
            *,
            dependencies: ArchiveWorkflowDependencyContext,
        ) -> tuple[ArchiveEntry, ...]:
            assert dependencies.entries
            return (source_sidecar,) if entry.identity == source.identity else (target_sidecar,)

        @staticmethod
        def _archive_entry_is_material_sidecar(entry: ArchiveEntry) -> bool:
            return entry.extension == ".pac_xml"

        @staticmethod
        def _archive_entry_is_appearance_descriptor(_entry: ArchiveEntry) -> bool:
            return False

        @staticmethod
        def _archive_entry_swap_companion_group(entry: ArchiveEntry) -> str:
            return entry.extension

    source_xml = (
        b'<SkinnedMeshMaterialWrapper _pbdSimulationMaterialName="cloth">'
        b"<SkinnedMeshMaterialWrapper>"
    )
    target_xml = b"<SkinnedMeshMaterialWrapper>"
    with patch(
        "cdmw.ui.archive_browser.mesh_swap_scope_preflight.read_archive_entry_data",
            side_effect=lambda entry, **_kwargs: (
            source_xml if entry.identity == source_sidecar.identity else target_xml,
            False,
            "",
        ),
    ):
        result = prepare_archive_mesh_swap_scope(
            Owner(),
            ArchiveMeshSwapScopePreflightRequest(
                1,
                target,
                source,
                _dependencies(target, source, source_sidecar, target_sidecar, texture),
            ),
            stop_event=threading.Event(),
        )

    assert result.item_family_scope
    assert result.source_wrapper_count == 2
    assert result.target_wrapper_count == 1
    assert result.source_pbd_names == ("cloth",)
    assert result.preserve_source_contract_default
    assert texture in result.source_related_entries


class _CapturedSwapOwner(_SwapOwner):
    def __init__(self) -> None:
        super().__init__()
        self.captured_tasks: list[dict[str, object]] = []
        self.prompt_count = 0

    def _run_utility_task_when_idle(self, **kwargs: object) -> None:
        self.captured_tasks.append(dict(kwargs))

    def _prompt_archive_in_game_mesh_swap_scope(
        self,
        _target: ArchiveEntry,
        _source: ArchiveEntry,
        *,
        prepared_scope: ArchiveMeshSwapScopePreflightResult,
    ) -> None:
        self.prompt_count += 1
        assert prepared_scope.request_id == self.archive_in_game_mesh_swap_scope_request_id


def test_mesh_swap_scope_stale_result_never_opens_dialog() -> None:
    owner = _CapturedSwapOwner()
    target = _entry("target.pac", 1)
    source = _entry("source.pac", 2)
    owner._start_archive_in_game_mesh_swap(target, source)
    owner._start_archive_in_game_mesh_swap(target, source)

    def result(request_id: int) -> ArchiveMeshSwapScopePreflightResult:
        return ArchiveMeshSwapScopePreflightResult(
            request_id=request_id,
            allow_character_scope=False,
            item_family_scope=False,
            same_weapon_folder=False,
            character_relationship_plan=None,
            source_related_entries=(),
            relationship_edges=(),
            unresolved_relationship_edges=(),
            source_sidecar_paths=frozenset(),
            source_appearance_paths=frozenset(),
            source_pbd_names=(),
            source_wrapper_count=0,
            target_wrapper_count=0,
            source_has_pbd_contract=False,
            source_has_larger_material_contract=False,
            preserve_source_contract_default=False,
        )

    owner.captured_tasks[0]["on_complete"](result(1))  # type: ignore[operator]
    assert owner.prompt_count == 0
    owner.captured_tasks[1]["on_complete"](result(2))  # type: ignore[operator]
    assert owner.prompt_count == 1


def test_static_placement_context_never_falls_back_to_ui_thread_io() -> None:
    with patch(
        "cdmw.ui.archive_browser.mesh_setup_helpers.describe_static_placement_context",
        side_effect=AssertionError("must not run without worker-preloaded meshes"),
    ):
        html, values = ArchiveMeshSetupHelperMixin._build_archive_static_placement_context_html(
            _entry("target.pac", 1),
            Path("source.obj"),
        )

    assert "async import preflight" in html
    assert values == {}


def test_external_import_callers_only_dispatch_async_preflight() -> None:
    for relative_path in (
        "cdmw/ui/archive_browser/mesh_patch_flow.py",
        "cdmw/ui/archive_browser/mesh_launch_flow.py",
        "cdmw/ui/archive_browser/mesh_modify_original.py",
    ):
        source = Path(relative_path).read_text(encoding="utf-8")
        assert "self._prepare_archive_mesh_import_setup_async(" in source
        assert "setup = self._prompt_archive_mesh_import_setup(" not in source
    setup_dialog_source = Path("cdmw/ui/archive_browser/mesh_import_export.py").read_text(encoding="utf-8")
    scope_dialog_source = Path("cdmw/ui/archive_browser/mesh_swap_scope_dialog.py").read_text(encoding="utf-8")
    placement_helper_source = Path("cdmw/ui/archive_browser/mesh_setup_helpers.py").read_text(encoding="utf-8")
    assert "import_scene_mesh_with_report(" not in setup_dialog_source
    assert "read_archive_entry_baseline_data(" not in setup_dialog_source
    assert "read_archive_entry_data(" not in scope_dialog_source
    assert "build_character_swap_plan(" not in scope_dialog_source
    assert "read_archive_entry_baseline_data(" not in placement_helper_source
    assert "import_scene_mesh(" not in placement_helper_source


def test_mesh_import_setup_request_is_frozen() -> None:
    request = MeshImportSetupPreflightRequest(
        request_id=1,
        entry=_entry("target.pac", 1),
        scene_path=Path("source.obj"),
        scene_import_result=None,
        original_mesh=None,
        force_static_replacement=False,
        archive_entries_by_basename={},
    )
    try:
        request.request_id = 2  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover - dataclass contract regression
        raise AssertionError("Mesh import setup request must remain immutable")
