from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from unittest import mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cdmw.core.model_catalogue import resolve_importable_model_path
from cdmw.domain.library.scene_selection import ModelArchiveSelectionRequired
from cdmw.modding.scene_importer import import_scene_mesh_with_report
from cdmw.models import ArchiveEntry
from cdmw.services.settings_service import create_settings
from cdmw.ui.model_library.tab import ModelLibraryTab
from cdmw.ui.archive_browser import mesh_import_preflight_controller
from cdmw.workers.model_library_workers import (
    ModelLibraryImportPathRequest,
    ModelLibraryImportPathResult,
    resolve_model_library_import_path,
)


OBJ_TRIANGLE = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


def _write_model_zip(path: Path, members: tuple[str, ...]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for member in members:
            archive.writestr(member, OBJ_TRIANGLE)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_for(app: QApplication, predicate: object, timeout: float = 5.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def test_zip_with_one_model_resolves_directly_without_source_mutation() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        archive = root / "one.zip"
        output = root / "extracted"
        _write_model_zip(archive, ("scene/model.obj",))
        before = hashlib.sha256(archive.read_bytes()).hexdigest()

        resolved = resolve_importable_model_path(archive, extract_root=output)

        assert resolved == output / "scene" / "model.obj"
        assert resolved.read_text(encoding="utf-8") == OBJ_TRIANGLE
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == before


def test_multi_model_zip_requires_valid_explicit_member_before_extraction() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        archive = root / "many.zip"
        output = root / "extracted"
        _write_model_zip(archive, ("models/z.obj", "models/a.obj"))

        with pytest.raises(ModelArchiveSelectionRequired) as raised:
            resolve_importable_model_path(archive, extract_root=output)
        assert raised.value.members == ("models/a.obj", "models/z.obj")
        assert not output.exists()

        with pytest.raises(ValueError, match="Selected ZIP model member is not available"):
            resolve_importable_model_path(archive, extract_root=output, selected_member="models/missing.obj")
        assert not output.exists()

        resolved = resolve_importable_model_path(
            archive,
            extract_root=output,
            selected_member="models/z.obj",
        )
        assert resolved == output / "models" / "z.obj"


def test_scene_import_and_worker_continue_with_explicit_zip_member() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        archive = root / "scenes.zip"
        _write_model_zip(archive, ("first.obj", "second.obj"))

        unresolved = resolve_model_library_import_path(
            ModelLibraryImportPathRequest(kind="local", source_path=str(archive))
        )
        assert unresolved.import_path is None
        assert unresolved.candidate_members == ("first.obj", "second.obj")
        assert not (root / ".cdmw_extracted").exists()

        resolved = resolve_model_library_import_path(
            ModelLibraryImportPathRequest(
                kind="local",
                source_path=str(archive),
                selected_member="second.obj",
            )
        )
        assert resolved.import_path is not None
        assert resolved.selected_member == "second.obj"

        result = import_scene_mesh_with_report(archive, selected_member="second.obj")
        assert result.mesh.total_vertices == 3
        assert result.mesh.total_faces == 1
        assert "second.obj" in " ".join(result.diagnostics)


def test_compressed_gltf_keeps_exact_uncompressed_remedy_without_helper_dependency() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "compressed.gltf"
        path.write_text(
            '{"asset":{"version":"2.0"},"extensionsUsed":["EXT_meshopt_compression","KHR_draco_mesh_compression"]}',
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="Export an uncompressed GLB/glTF before importing"):
            import_scene_mesh_with_report(path)


def test_model_library_picker_reissues_worker_request_with_selected_member() -> None:
    app = _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        archive = root / "many.zip"
        resolved = root / "second.obj"
        archive.write_bytes(b"zip")
        resolved.write_text(OBJ_TRIANGLE, encoding="utf-8")
        settings = create_settings(settings_file_path=root / "settings.ini")
        tab = ModelLibraryTab(settings=settings, base_dir=root)
        payload = {"kind": "local", "name": "Many", "path": str(archive), "extension": ".zip"}
        tab._set_active_results_view("local", persist=False)
        tab._populate_results([payload])
        assert _wait_for(app, lambda: not tab._populating_results)
        requests: list[ModelLibraryImportPathRequest] = []
        emitted: list[str] = []
        tab.preview_mesh_requested.connect(lambda path, _payload: emitted.append(path))

        def fake_resolve(request: ModelLibraryImportPathRequest, **_kwargs: object) -> ModelLibraryImportPathResult:
            requests.append(request)
            if not request.selected_member:
                return ModelLibraryImportPathResult(None, archive, candidate_members=("first.obj", "second.obj"))
            return ModelLibraryImportPathResult(resolved, archive, selected_member=request.selected_member)

        with (
            mock.patch("cdmw.ui.model_library.tab.resolve_model_library_import_path", side_effect=fake_resolve),
            mock.patch("cdmw.ui.model_library.tab.QInputDialog.getItem", return_value=("second.obj", True)),
        ):
            tab.preview_selected_model()
            assert _wait_for(app, lambda: emitted == [str(resolved)])

        assert [request.selected_member for request in requests] == ["", "second.obj"]
        tab.request_shutdown()
        assert _wait_for(app, lambda: tab._task_thread is None)
        tab.close()
        tab.deleteLater()
        app.processEvents()


def test_full_import_preflight_continues_after_explicit_zip_selection() -> None:
    class Owner:
        archive_mesh_import_setup_request_id = 0
        archive_entries_by_basename: dict[str, tuple[ArchiveEntry, ...]] = {}
        _shutting_down = False

        def _run_utility_task_when_idle(self, **kwargs: object) -> None:
            self.worker = kwargs

        @staticmethod
        def _has_valid_obj_roundtrip_sidecar(_path: Path) -> bool:
            return False

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        archive = root / "full-import.zip"
        _write_model_zip(archive, ("first.obj", "second.obj"))
        owner = Owner()
        completed: list[object] = []
        entry = ArchiveEntry("character/model/target.pac", Path("0009/0.pamt"), Path("0009/0.paz"), 1, 1, 1, 0, 0)

        mesh_import_preflight_controller.dispatch_mesh_import_setup_preflight(
            owner,
            entry,
            archive,
            title="Full Import Model Replacement Setup",
            on_complete=completed.append,
            full_import_model_replacement=True,
        )
        worker = owner.worker
        selection = worker["task"](
            lambda _message: None,
            lambda _current, _total, _detail: None,
            threading.Event(),
        )
        assert isinstance(selection, mesh_import_preflight_controller.MeshImportMemberSelectionResult)

        with (
            mock.patch.object(mesh_import_preflight_controller.QInputDialog, "getItem", return_value=("second.obj", True)),
            mock.patch.object(mesh_import_preflight_controller, "dispatch_mesh_import_setup_preflight") as restart,
        ):
            worker["on_complete"](selection)

        assert completed == []
        assert restart.call_args.kwargs["selected_member"] == "second.obj"
        assert restart.call_args.kwargs["full_import_model_replacement"] is True
