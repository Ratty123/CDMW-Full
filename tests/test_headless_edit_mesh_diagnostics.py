from __future__ import annotations

from pathlib import Path

from tools.mesh_harness import scenario_runner
from tools.mesh_harness.edit_mesh_diagnostics import (
    _original_texture_factory_contract,
    _screen_region,
)
from tools.mesh_harness.scenario_registry import scenario_metadata


def test_original_texture_factory_contract_executes_the_three_resolver_dependencies() -> None:
    report = _original_texture_factory_contract()

    assert report["ok"] is True
    assert report["dependencies"] == {
        "_original_reference_texture_preview_set_native_package_path_helper": True,
        "_apply_native_preview_core_material_manifest_helper": True,
        "_native_manifest_input_from_descriptor": True,
    }


def test_lasso_region_keeps_the_native_selection_vocabulary() -> None:
    region = _screen_region("lasso")

    assert region["mode"] == "lasso"
    assert region["selection_mode"] == "lasso"
    assert len(region["points"]) == 4


def test_headless_diagnostic_registry_declares_both_real_backends() -> None:
    metadata = scenario_metadata("headless-edit-mesh-diagnostics")

    assert metadata.headless is True
    assert metadata.visual is False
    assert metadata.real_game is False
    assert metadata.process_ownership == "harness"
    assert metadata.expected_renderer_backend == "d3d11_vortice_shader"
    assert metadata.expected_edit_backend == "cdmw_mesh_core_0.1"


def test_scenario_runner_routes_the_full_headless_diagnostic(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        scenario_runner,
        "run_headless_edit_mesh_diagnostics",
        lambda output_dir: {
            "ok": True,
            "renderer_backend": "d3d11_vortice_shader",
            "edit_backend": "cdmw_mesh_core_0.1",
            "output_dir": str(output_dir),
        },
    )

    result = scenario_runner.run_scenario(
        "headless-edit-mesh-diagnostics", tmp_path
    )

    assert result["ok"] is True
    assert result["headless_edit_mesh_diagnostics"]["output_dir"] == str(tmp_path)
    assert (tmp_path / "result.json").is_file()
    assert (tmp_path / "evidence_report.json").is_file()


def test_dotnet_hidden_suite_names_every_selection_shape_target_and_tool() -> None:
    source = (
        Path("tools/dotnet_mesh_editor_experiment/ExperimentForm.EditMeshToolDiagnostics.cs")
        .read_text(encoding="utf-8")
    )

    assert 'new[] { "vertex", "edge", "face" }' in source
    assert 'new[] { "brush", "lasso", "rectangle" }' in source
    assert 'new[] { "move", "grab", "smooth", "inflate", "pinch" }' in source
    assert "HasTexturedMaterialResources" in source
    assert "EditMeshToolListContract.RowOrder" in source
    assert '"pointer_p95_at_most_20_ms"' in source
    assert '"no_pointer_sample_over_100_ms"' in source
    assert '"terminal_reconciliation_at_most_250_ms"' in source
