from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_dotnet_experiment import MeshDotNetExperimentPackage
from cdmw.workers import mesh_editor_aux_workers, mesh_editor_workers
from tests.test_mesh_dotnet_experiment import _mesh


def test_dotnet_package_worker_keeps_modify_original_graph_for_shared_synthesis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    editable = _mesh()
    reference = _mesh()
    graph_input = SimpleNamespace(
        semantic_type="layer_color",
        slot_kind="material",
        preview_texture_path="C:/cache/layer.dds",
    )
    reference.submeshes[0].preview_material_texture_inputs = (graph_input,)
    captured: dict[str, object] = {}

    class Service:
        def working_mesh(self, _session_id: str, *, clone: bool) -> ParsedMesh:
            assert clone
            return editable

        def session_view(self, _session_id: str) -> object:
            return SimpleNamespace(selection=SimpleNamespace())

    def capture_package(mesh: ParsedMesh, **kwargs: object) -> object:
        captured["mesh"] = mesh
        captured["reference_mesh"] = kwargs["reference_mesh"]
        captured["include_material_resources"] = kwargs["include_material_resources"]
        return SimpleNamespace(package_dir=tmp_path)

    monkeypatch.setattr(
        mesh_editor_aux_workers,
        "build_mesh_dotnet_experiment_package",
        capture_package,
    )
    worker = mesh_editor_aux_workers.MeshDotNetExperimentPackageWorker(
        20,
        Service(),
        "session",
        reference_mesh=reference,
        mirror_reference_materials_to_editable=True,
        include_material_resources=False,
    )
    errors: list[str] = []
    worker.error.connect(lambda _request_id, message: errors.append(str(message)))

    worker.run()

    assert errors == []
    packaged_editable = captured["mesh"]
    packaged_reference = captured["reference_mesh"]
    assert isinstance(packaged_editable, ParsedMesh)
    assert isinstance(packaged_reference, ParsedMesh)
    assert captured["include_material_resources"] is False
    assert packaged_editable.submeshes[0].preview_material_texture_inputs
    assert packaged_reference.submeshes[0].preview_material_texture_inputs
    assert (
        packaged_editable.submeshes[0].preview_material_texture_inputs[0].semantic_type
        == "layer_color"
    )


def test_dotnet_output_import_worker_cancels_before_commit_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepare_started = threading.Event()
    release_prepare = threading.Event()

    class Service:
        commit_calls = 0

        def prepare_working_mesh_replacement(self, _session_id: str, mesh: ParsedMesh) -> object:
            prepare_started.set()
            assert release_prepare.wait(2.0)
            return SimpleNamespace(
                mesh=mesh,
                validation_report=SimpleNamespace(ok=True, blockers=(), warnings=()),
            )

        def commit_prepared_working_mesh_replacement(self, _prepared: object) -> object:
            self.commit_calls += 1
            return SimpleNamespace()

    package_dir = tmp_path / "cancel-before-commit"
    output_dir = package_dir / "output"
    output_dir.mkdir(parents=True)
    package = MeshDotNetExperimentPackage(
        package_dir=package_dir,
        mesh_path=package_dir / "mesh.obj",
        obj_sidecar_path=package_dir / "mesh.obj.meta.json",
        cdmeta_path=package_dir / "mesh.cdmeta.json",
        original_asset_hash_path=package_dir / "original_asset_hash.txt",
        status_path=output_dir / "dotnet_status.json",
        output_dir=output_dir,
        edit_operations_path=output_dir / "edit_operations.json",
        launch_manifest_path=package_dir / "dotnet_launch.json",
    )
    monkeypatch.setattr(mesh_editor_aux_workers, "import_mesh_dotnet_experiment_output", lambda *_args: _mesh())
    service = Service()
    worker = mesh_editor_workers.MeshDotNetExperimentOutputImportWorker(21, service, "session", package)
    completed: list[object] = []
    worker.completed.connect(lambda *args: completed.append(args))

    def cancel() -> None:
        assert prepare_started.wait(2.0)
        assert worker.stop()
        release_prepare.set()

    cancel_thread = threading.Thread(target=cancel)
    cancel_thread.start()
    worker.run()
    cancel_thread.join(2.0)

    assert service.commit_calls == 0
    assert completed == []


def test_dotnet_output_import_worker_late_cancel_cannot_suppress_commit_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commit_started = threading.Event()
    release_commit = threading.Event()

    class Service:
        def prepare_working_mesh_replacement(self, _session_id: str, mesh: ParsedMesh) -> object:
            return SimpleNamespace(
                mesh=mesh,
                validation_report=SimpleNamespace(ok=True, blockers=(), warnings=()),
            )

        def commit_prepared_working_mesh_replacement(self, _prepared: object) -> object:
            commit_started.set()
            assert release_commit.wait(2.0)
            return SimpleNamespace(revision=1)

    package_dir = tmp_path / "late-cancel"
    output_dir = package_dir / "output"
    output_dir.mkdir(parents=True)
    package = MeshDotNetExperimentPackage(
        package_dir=package_dir,
        mesh_path=package_dir / "mesh.obj",
        obj_sidecar_path=package_dir / "mesh.obj.meta.json",
        cdmeta_path=package_dir / "mesh.cdmeta.json",
        original_asset_hash_path=package_dir / "original_asset_hash.txt",
        status_path=output_dir / "dotnet_status.json",
        output_dir=output_dir,
        edit_operations_path=output_dir / "edit_operations.json",
        launch_manifest_path=package_dir / "dotnet_launch.json",
    )
    monkeypatch.setattr(mesh_editor_aux_workers, "import_mesh_dotnet_experiment_output", lambda *_args: _mesh())
    worker = mesh_editor_workers.MeshDotNetExperimentOutputImportWorker(22, Service(), "session", package)
    completed: list[tuple[object, ...]] = []
    worker.completed.connect(lambda *args: completed.append(args))
    stop_results: list[bool] = []

    def cancel_late() -> None:
        assert commit_started.wait(2.0)
        stop_results.append(worker.stop())
        release_commit.set()

    cancel_thread = threading.Thread(target=cancel_late)
    cancel_thread.start()
    worker.run()
    cancel_thread.join(2.0)

    assert stop_results == [False]
    assert len(completed) == 1
    assert completed[0][0] == 22


def test_dotnet_output_import_worker_rejects_precommit_validation_blocker_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Service:
        commit_calls = 0

        def prepare_working_mesh_replacement(self, _session_id: str, mesh: ParsedMesh) -> object:
            return SimpleNamespace(
                mesh=mesh,
                validation_report=SimpleNamespace(
                    ok=False,
                    blockers=(SimpleNamespace(message="invalid export"),),
                    warnings=(),
                ),
            )

        def commit_prepared_working_mesh_replacement(self, _prepared: object) -> object:
            self.commit_calls += 1
            return SimpleNamespace()

    package_dir = tmp_path / "precommit-blocker"
    output_dir = package_dir / "output"
    output_dir.mkdir(parents=True)
    package = MeshDotNetExperimentPackage(
        package_dir=package_dir,
        mesh_path=package_dir / "mesh.obj",
        obj_sidecar_path=package_dir / "mesh.obj.meta.json",
        cdmeta_path=package_dir / "mesh.cdmeta.json",
        original_asset_hash_path=package_dir / "original_asset_hash.txt",
        status_path=output_dir / "dotnet_status.json",
        output_dir=output_dir,
        edit_operations_path=output_dir / "edit_operations.json",
        launch_manifest_path=package_dir / "dotnet_launch.json",
    )
    monkeypatch.setattr(mesh_editor_aux_workers, "import_mesh_dotnet_experiment_output", lambda *_args: _mesh())
    service = Service()
    worker = mesh_editor_workers.MeshDotNetExperimentOutputImportWorker(23, service, "session", package)
    errors: list[str] = []
    worker.error.connect(lambda _request_id, message: errors.append(str(message)))

    worker.run()

    assert service.commit_calls == 0
    assert errors and "invalid export" in errors[0]
