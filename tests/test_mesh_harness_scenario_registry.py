from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tools.mesh_harness import cli, scenario_runner
from tools.mesh_harness.constants import _REAL_MESH_EDITOR_VISUAL_SCENARIO
from tools.mesh_harness.scenario_registry import SCENARIOS, scenario_metadata, validate_scenario_registry


def test_mesh_harness_registry_has_one_production_vortice_renderer() -> None:
    production = scenario_metadata("real-archive-mesh-editor-dotnet-edit-smoke")
    synthetic = scenario_metadata("full-suite-smoke")

    assert production.scenario_role == "production_visual_proof"
    assert production.expected_renderer_backend == "d3d11_vortice_shader"
    assert production.expected_edit_backend == "cdmw_mesh_core_0.1"
    assert production.compatibility_only is False
    assert production.normal_qa is False
    assert "real-archive-mesh-editor-d3d11-edit-smoke" not in SCENARIOS
    assert all(row.compatibility_only is False for row in SCENARIOS.values())
    assert synthetic.scenario_role == "service_regression"
    assert synthetic.expected_backend == "native-mesh-core-or-python-fallback"
    assert synthetic.normal_qa is True


def test_registry_validation_rejects_non_vortice_production_or_default_legacy() -> None:
    rows = list(SCENARIOS.values())
    production_index = next(index for index, row in enumerate(rows) if row.scenario_role == "production_visual_proof")

    wrong_renderer = list(rows)
    wrong_renderer[production_index] = replace(
        wrong_renderer[production_index],
        expected_renderer_backend="winforms_gdi_fallback",
    )
    with pytest.raises(ValueError, match=".NET/Vortice"):
        validate_scenario_registry(wrong_renderer)

    scheduled_legacy = list(rows)
    scheduled_legacy[0] = replace(
        scheduled_legacy[0],
        name="retired-native-renderer",
        scenario_role="native_renderer_compatibility",
        expected_backend="legacy-cpp-d3d11",
        compatibility_only=False,
    )
    with pytest.raises(ValueError, match="compatibility-only"):
        validate_scenario_registry(scheduled_legacy)

    unclassified_visual = list(rows)
    unclassified_visual[production_index] = replace(
        unclassified_visual[production_index],
        scenario_role="real_game_visual_probe",
    )
    with pytest.raises(ValueError, match="canonical production .NET/Vortice proof role"):
        validate_scenario_registry(unclassified_visual)


def test_nonvisual_harness_metadata_names_optional_backends_truthfully() -> None:
    assert scenario_metadata("service-smoke").expected_backend == "native-mesh-core-or-python-fallback"
    assert scenario_metadata("asset-authoring-mesh-health").expected_backend == "python+optional-meshoptimizer"
    assert scenario_metadata("asset-authoring-uv-report").expected_backend == "python+optional-xatlas"
    assert scenario_metadata("real-archive-app-workflow-smoke").expected_backend == "qt-offscreen+python"


def test_default_cli_uses_dotnet_real_proof_and_game_root_resolution_order(monkeypatch, tmp_path: Path) -> None:
    environment_root = tmp_path / "environment-game"
    explicit_root = tmp_path / "explicit-game"
    calls: list[tuple[str, Path, Path]] = []
    monkeypatch.setenv("CDMW_GAME_ROOT", str(environment_root))
    monkeypatch.setattr(
        scenario_runner,
        "run_scenario",
        lambda scenario, output, *, game_root, **_kwargs: calls.append((scenario, output, game_root)) or {"ok": True},
    )

    assert cli.main(["--output", str(tmp_path / "environment-output")]) == 0
    assert cli.main(["--game-root", str(explicit_root), "--output", str(tmp_path / "explicit-output")]) == 0
    assert calls[0] == (_REAL_MESH_EDITOR_VISUAL_SCENARIO, tmp_path / "environment-output", environment_root)
    assert calls[1] == (_REAL_MESH_EDITOR_VISUAL_SCENARIO, tmp_path / "explicit-output", explicit_root)
