from __future__ import annotations

import json
from pathlib import Path

from cdmw.services import mesh_dotnet_experiment
from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExperimentPackage,
    MESH_DOTNET_EXPERIMENT_BINARY_NAME,
    resolve_mesh_dotnet_experiment_editor,
    write_mesh_dotnet_launch_diagnostics,
    write_mesh_dotnet_launch_manifest,
)


def _package(root: Path) -> MeshDotNetExperimentPackage:
    package_dir = root / "package"
    output_dir = package_dir / "output"
    output_dir.mkdir(parents=True)
    package = MeshDotNetExperimentPackage(
        package_dir=package_dir,
        mesh_path=package_dir / "mesh.obj",
        obj_sidecar_path=package_dir / "mesh.obj.meta.json",
        cdmeta_path=package_dir / "mesh.cdmeta.json",
        original_asset_hash_path=package_dir / "original_asset_hash.txt",
        status_path=package_dir / "dotnet_status.json",
        output_dir=output_dir,
        edit_operations_path=output_dir / "edit_operations.json",
        launch_manifest_path=package_dir / "dotnet_launch.json",
    )
    package.launch_manifest_path.write_text(json.dumps({"format": "test"}), encoding="utf-8")
    return package


def test_dotnet_executable_resolution_reports_missing_configured_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CDMW_MESH_DOTNET_EXPERIMENT_EXE", raising=False)
    monkeypatch.setattr(mesh_dotnet_experiment, "_repo_root", lambda: tmp_path)

    missing = tmp_path / MESH_DOTNET_EXPERIMENT_BINARY_NAME
    resolution = resolve_mesh_dotnet_experiment_editor(missing)

    payload = resolution.as_event_payload()
    assert payload["configured_path"] == str(missing)
    assert payload["resolved_path"] == str(missing)
    assert payload["exists"] is False
    assert payload["is_file"] is False
    assert payload["source"] == "missing"


def test_dotnet_launch_manifest_records_executable_arguments_and_embedded_parent(tmp_path: Path) -> None:
    package = _package(tmp_path)

    path = write_mesh_dotnet_launch_manifest(
        package,
        executable="C:/tools/cdmw-mesh-dotnet-editor.exe",
        arguments=("--input-package", package.package_dir, "--embedded"),
        embedded=True,
        parent_hwnd=12345,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["executable"] == "C:/tools/cdmw-mesh-dotnet-editor.exe"
    assert payload["arguments"] == ["--input-package", str(package.package_dir), "--embedded"]
    assert payload["embedded"] is True
    assert payload["parent_hwnd"] == 12345
    assert payload["launch"]["parent_hwnd"] == 12345
    assert payload["created_at"]


def test_dotnet_launch_diagnostics_preserves_process_error_tails(tmp_path: Path) -> None:
    package = _package(tmp_path)

    path = write_mesh_dotnet_launch_diagnostics(
        package,
        {
            "event": "mesh_dotnet_process_start_failed",
            "qprocess_error_string": "The system cannot find the file specified.",
            "stderr_tail": "native stderr tail",
            "stdout_tail": "native stdout tail",
            "package_dir": str(package.package_dir),
        },
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["event"] == "mesh_dotnet_process_start_failed"
    assert payload["qprocess_error_string"] == "The system cannot find the file specified."
    assert payload["stderr_tail"] == "native stderr tail"
    assert payload["stdout_tail"] == "native stdout tail"


def test_mesh_editor_tab_contains_persistent_dotnet_runtime_events() -> None:
    source = (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "mesh_editor" / "tab.py").read_text(encoding="utf-8")

    for event_name in (
        "mesh_dotnet_executable_resolved",
        "mesh_dotnet_package_start",
        "mesh_dotnet_package_ready",
        "mesh_dotnet_package_error",
        "mesh_dotnet_process_configured",
        "mesh_dotnet_process_start",
        "mesh_dotnet_process_started",
        "mesh_dotnet_process_start_failed",
        "mesh_dotnet_process_error",
        "mesh_dotnet_process_finished",
        "mesh_dotnet_embedded_parent_hwnd_unavailable",
    ):
        assert event_name in source
    assert "stderr_tail" in source
    assert "stdout_tail" in source
    assert "write_mesh_dotnet_launch_diagnostics" in source
