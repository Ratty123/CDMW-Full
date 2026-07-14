from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_dotnet_experiment import MeshDotNetExperimentPackage
from cdmw.workers import mesh_editor_aux_workers, mesh_editor_workers
from tests.test_mesh_dotnet_experiment import _mesh


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
