from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services import mesh_dotnet_experiment
from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExperimentPackage,
    import_mesh_dotnet_experiment_output,
    mesh_dotnet_experiment_command,
    mesh_dotnet_experiment_output_obj_path,
    mesh_dotnet_material_parity_warnings,
    mesh_dotnet_renderer_blockers,
    write_mesh_dotnet_experiment_evaluation,
)
from cdmw.workers import mesh_editor_aux_workers, mesh_editor_workers
from tests.test_mesh_dotnet_experiment import _mesh


def test_dotnet_renderer_status_requires_exact_embedded_production_backend() -> None:
    valid = {"renderer": {"backend": "d3d11_vortice_shader", "gpu_backed": True, "renderer_blocked": False}}
    assert mesh_dotnet_renderer_blockers(valid, embedded=True) == ()
    invalid_renderers = (
        {},
        {"backend": "unknown", "gpu_backed": True, "renderer_blocked": False},
        {"backend": "headless_cpu_smoke", "gpu_backed": False, "renderer_blocked": False},
        {"backend": "wpf_viewport3d_gpu", "gpu_backed": True, "renderer_blocked": False},
        {"backend": "winforms_gdi_fallback", "gpu_backed": False, "renderer_blocked": False},
        {"backend": "d3d11_vortice_shader", "renderer_blocked": False},
        {"backend": "d3d11_vortice_shader", "gpu_backed": True},
        {"backend": "d3d11_vortice_shader", "gpu_backed": True, "renderer_blocked": True},
    )
    for renderer in invalid_renderers:
        blockers = mesh_dotnet_renderer_blockers({"renderer": renderer}, embedded=True)
        assert blockers
        assert "requires backend=d3d11_vortice_shader" in blockers[-1]
    for renderer in (
        {"backend": "wpf_viewport3d_gpu", "gpu_backed": True, "renderer_blocked": False},
        {"backend": "winforms_gdi_fallback", "gpu_backed": False, "renderer_blocked": False},
    ):
        assert mesh_dotnet_renderer_blockers(
            {"renderer": renderer}, embedded=True, developer_override=True
        ) == ()
    for renderer in ({}, {"backend": "unknown"}, {"backend": "headless_cpu_smoke"}):
        assert mesh_dotnet_renderer_blockers(
            {"renderer": renderer}, embedded=True, developer_override=True
        )


def test_dotnet_renderer_status_blocks_missing_material_parity_when_required() -> None:
    payload = {
        "renderer": {
            "backend": "d3d11_vortice_shader",
            "dds_resources": 1,
            "native_dds_parity": False,
            "dds_native_dxgi_upload": False,
            "dds_upload_mode": "bitmap_rgba_upload",
            "material_contract_gap": ["direct compressed DDS upload parity"],
        }
    }

    warnings = mesh_dotnet_material_parity_warnings(payload)
    blockers = mesh_dotnet_renderer_blockers(payload, require_material_parity=True)

    assert "native DDS parity is not available" in warnings
    assert "native DXGI DDS upload is not available" in warnings
    assert blockers
    assert blockers[0].startswith("material parity incomplete:")
    assert mesh_dotnet_renderer_blockers(payload, require_material_parity=True, developer_override=True) == ()


def test_dotnet_renderer_status_does_not_report_dds_gap_for_png_only_materials() -> None:
    payload = {
        "renderer": {
            "backend": "d3d11_vortice_shader",
            "dds_resources": 0,
            "native_dds_parity": False,
            "dds_native_dxgi_upload": False,
            "dds_upload_mode": "bitmap_rgba_upload",
            "material_contract_gap": [],
        }
    }

    assert mesh_dotnet_material_parity_warnings(payload) == ()
    assert mesh_dotnet_renderer_blockers(payload, require_material_parity=True) == ()


def test_dotnet_renderer_status_blocks_explicit_renderer_unavailable() -> None:
    payload = {"renderer": {"backend": "blocked_renderer_unavailable", "renderer_block_reason": "D3D11 failed"}}

    assert mesh_dotnet_renderer_blockers(payload) == ("blocked_renderer_unavailable: D3D11 failed",)


def _dotnet_output_test_package(tmp_path: Path) -> MeshDotNetExperimentPackage:
    package_dir = tmp_path / "package"
    output_dir = package_dir / "output"
    output_dir.mkdir(parents=True)
    return MeshDotNetExperimentPackage(
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


def test_dotnet_experiment_output_import_uses_output_obj_sidecar_and_operations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package = _dotnet_output_test_package(tmp_path)
    output_dir = package.output_dir
    package.mesh_path.write_text("input", encoding="utf-8")
    package.obj_sidecar_path.write_text(json.dumps({"format": "mesh_roundtrip_manifest_v2"}), encoding="utf-8")
    output_obj = output_dir / "mesh.obj"
    output_obj.write_text("edited", encoding="utf-8")
    package.edit_operations_path.write_text(
        json.dumps(
            [
                {
                    "operation": "replace_positions_same_count",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 3,
                    "source": "mesh.obj",
                }
            ]
        ),
        encoding="utf-8-sig",
    )

    imported = _mesh()

    def fake_import_obj(path: str) -> ParsedMesh:
        assert Path(path) == output_obj
        assert Path(f"{path}.meta.json").is_file()
        return imported

    monkeypatch.setattr(mesh_dotnet_experiment, "import_obj", fake_import_obj)

    assert mesh_dotnet_experiment_output_obj_path(package, {"edited_package": "."}) == output_obj.resolve()
    assert (
        mesh_dotnet_experiment_output_obj_path(package, {"edited_package": str(output_dir)})
        == output_obj.resolve()
    )
    mesh = import_mesh_dotnet_experiment_output(package, {"edited_package": "."})

    assert mesh is imported
    assert getattr(mesh, "_cdmw_edit_operations")[0]["operation"] == "replace_positions_same_count"
    assert getattr(mesh, "_cdmw_dotnet_authority_contract") == "dotnet_viewport_python_cpp_validation"


def test_dotnet_experiment_output_import_rejects_missing_operation_records(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package = _dotnet_output_test_package(tmp_path)
    output_dir = package.output_dir
    package.mesh_path.write_text("input", encoding="utf-8")
    package.obj_sidecar_path.write_text(json.dumps({"format": "mesh_roundtrip_manifest_v2"}), encoding="utf-8")
    (output_dir / "mesh.obj").write_text("edited", encoding="utf-8")
    monkeypatch.setattr(mesh_dotnet_experiment, "import_obj", lambda _path: _mesh())

    try:
        import_mesh_dotnet_experiment_output(package, {"edited_package": "."})
    except ValueError as exc:
        assert "authoritative edit operation records" in str(exc)
    else:
        raise AssertionError("missing edit operations should be rejected")


def test_dotnet_experiment_output_rejects_absolute_external_path(tmp_path: Path) -> None:
    package = _dotnet_output_test_package(tmp_path)
    external_obj = tmp_path / "external" / "mesh.obj"
    external_obj.parent.mkdir()
    external_obj.write_text("external", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes the package output directory"):
        mesh_dotnet_experiment_output_obj_path(package, {"edited_obj": str(external_obj)})

    assert not Path(f"{external_obj}.meta.json").exists()


@pytest.mark.parametrize("reported_path", ("../external/mesh.obj", r"..\external\mesh.obj"))
def test_dotnet_experiment_output_rejects_traversal(tmp_path: Path, reported_path: str) -> None:
    package = _dotnet_output_test_package(tmp_path)

    with pytest.raises(ValueError, match="contains traversal"):
        mesh_dotnet_experiment_output_obj_path(package, {"edited_obj": reported_path})


def test_dotnet_experiment_output_rejects_symlink_escape(tmp_path: Path) -> None:
    package = _dotnet_output_test_package(tmp_path)
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    (external_dir / "mesh.obj").write_text("external", encoding="utf-8")
    link = package.output_dir / "linked"
    try:
        link.symlink_to(external_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="escapes the package output directory"):
        mesh_dotnet_experiment_output_obj_path(package, {"edited_obj": "linked/mesh.obj"})


@pytest.mark.parametrize("input_field", ("mesh_path", "scene_mesh_path"))
def test_dotnet_experiment_output_rejects_input_obj_alias(tmp_path: Path, input_field: str) -> None:
    package = _dotnet_output_test_package(tmp_path)
    output_obj = package.output_dir / "mesh.obj"
    output_obj.write_text("input", encoding="utf-8")
    package = replace(package, **{input_field: output_obj})

    with pytest.raises(ValueError, match="aliases an input OBJ"):
        mesh_dotnet_experiment_output_obj_path(package, {"edited_obj": "mesh.obj"})


def test_dotnet_experiment_output_rejects_input_obj_hardlink_alias(tmp_path: Path) -> None:
    package = _dotnet_output_test_package(tmp_path)
    package.mesh_path.write_text("input", encoding="utf-8")
    output_obj = package.output_dir / "mesh.obj"
    try:
        output_obj.hardlink_to(package.mesh_path)
    except OSError as exc:
        pytest.skip(f"hard links are unavailable: {exc}")

    with pytest.raises(ValueError, match="aliases an input OBJ"):
        mesh_dotnet_experiment_output_obj_path(package, {"edited_obj": "mesh.obj"})


def test_dotnet_experiment_output_rejects_external_operations_before_sidecar_write(tmp_path: Path) -> None:
    package = _dotnet_output_test_package(tmp_path)
    package.obj_sidecar_path.write_text(json.dumps({"format": "mesh_roundtrip_manifest_v2"}), encoding="utf-8")
    output_obj = package.output_dir / "mesh.obj"
    output_obj.write_text("edited", encoding="utf-8")
    external_operations = tmp_path / "external_operations.json"
    external_operations.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes the package output directory"):
        import_mesh_dotnet_experiment_output(
            package,
            {"edited_obj": "mesh.obj", "edit_operations": str(external_operations)},
        )

    assert not Path(f"{output_obj}.meta.json").exists()


@pytest.mark.parametrize("field", ("status_path", "edit_operations_path"))
def test_dotnet_experiment_command_rejects_external_helper_output_paths(
    tmp_path: Path,
    field: str,
) -> None:
    package = _dotnet_output_test_package(tmp_path)
    escaped = replace(package, **{field: tmp_path / f"external-{field}.json"})

    with pytest.raises(ValueError, match="escapes the package output directory"):
        mesh_dotnet_experiment_command(tmp_path / "helper.exe", escaped)


def test_dotnet_experiment_rejects_output_root_outside_package(tmp_path: Path) -> None:
    package = _dotnet_output_test_package(tmp_path)
    external_output = tmp_path / "external-output"
    external_output.mkdir()

    with pytest.raises(ValueError, match="escapes its package root"):
        mesh_dotnet_experiment_command(
            tmp_path / "helper.exe",
            replace(package, output_dir=external_output),
        )


def test_dotnet_experiment_evaluation_writes_keep_drop_note(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
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

    path = write_mesh_dotnet_experiment_evaluation(
        package,
        {
            "event": "saved",
            "metrics": {"average_fps": 75.0, "frame_time_ms": 13.3, "memory_mb": 512},
            "native_baseline": {"average_fps": 60.0, "frame_time_ms": 16.6, "memory_mb": 400},
        },
        validation_report=SimpleNamespace(ok=True, blockers=(), warnings=("missing_tangents",)),
    )
    text = path.read_text(encoding="utf-8")

    assert path == output_dir / "dotnet_evaluation.md"
    assert "FPS" in text
    assert "75.0" in text
    assert "60.0" in text
    assert "Validation warnings: 1" in text
    assert "Keep/drop Recommendation:" in text


def test_dotnet_experiment_import_worker_writes_drop_evaluation_on_import_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "package"
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

    def fail_import(_package: MeshDotNetExperimentPackage, _payload: object) -> ParsedMesh:
        raise ValueError("bad edit operations")

    monkeypatch.setattr(mesh_editor_aux_workers, "import_mesh_dotnet_experiment_output", fail_import)
    worker = mesh_editor_workers.MeshDotNetExperimentOutputImportWorker(
        12,
        SimpleNamespace(),
        "session",
        package,
        {"event": "saved", "metrics": {"average_fps": 72.0}},
    )
    errors: list[tuple[int, str]] = []
    worker.error.connect(lambda request_id, message: errors.append((int(request_id), str(message))))

    worker.run()

    assert errors
    assert errors[0][0] == 12
    assert "Evaluation:" in errors[0][1]
    text = (output_dir / "dotnet_evaluation.md").read_text(encoding="utf-8")
    assert "Output validation: `blocked`" in text
    assert "Validation blockers: 1" in text
    assert "drop .NET output" in text
