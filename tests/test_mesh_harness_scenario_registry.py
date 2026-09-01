from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tools.mesh_harness import cli, scenario_runner
from tools.mesh_harness.constants import _REAL_MESH_EDITOR_PRODUCTION_SCENARIO
from tools.mesh_harness.scenario_registry import SCENARIOS, scenario_metadata, validate_scenario_registry


def test_mesh_harness_registry_has_one_production_rust_renderer() -> None:
    production = scenario_metadata("real-archive-rust-preview-smoke")
    legacy = scenario_metadata("real-archive-mesh-editor-dotnet-edit-smoke")
    synthetic = scenario_metadata("full-suite-smoke")

    assert production.scenario_role == "production_rendering_proof"
    assert production.expected_renderer_backend == "wgpu_d3d12_rust"
    assert production.expected_edit_backend == ""
    assert production.compatibility_only is False
    assert production.normal_qa is False
    assert production.headless is True
    assert legacy.scenario_role == "legacy_vortice_reference"
    assert legacy.compatibility_only is True
    assert "real-archive-mesh-editor-d3d11-edit-smoke" not in SCENARIOS
    assert synthetic.scenario_role == "service_regression"
    assert synthetic.expected_backend == "native-mesh-core-or-python-fallback"
    assert synthetic.normal_qa is True


def test_registry_validation_rejects_non_rust_production_or_default_legacy() -> None:
    rows = list(SCENARIOS.values())
    production_index = next(
        index for index, row in enumerate(rows) if row.scenario_role == "production_rendering_proof"
    )

    wrong_renderer = list(rows)
    wrong_renderer[production_index] = replace(
        wrong_renderer[production_index],
        expected_renderer_backend="d3d11_vortice_shader",
    )
    with pytest.raises(ValueError, match="Rust/wgpu/D3D12"):
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

    visible_production = list(rows)
    visible_production[production_index] = replace(
        visible_production[production_index],
        headless=False,
        visual=True,
    )
    with pytest.raises(ValueError, match="Visible Mesh Editor automation is compatibility-only"):
        validate_scenario_registry(visible_production)


def test_nonvisual_harness_metadata_names_optional_backends_truthfully() -> None:
    assert scenario_metadata("service-smoke").expected_backend == "native-mesh-core-or-python-fallback"
    assert scenario_metadata("asset-authoring-mesh-health").expected_backend == "python"
    assert scenario_metadata("asset-authoring-uv-report").expected_backend == "python+optional-xatlas"
    assert scenario_metadata("real-archive-app-workflow-smoke").expected_backend == "qt-offscreen+python"
    load = scenario_metadata("real-archive-mesh-editor-load-smoke")
    assert load.expected_backend == "qt-offscreen+python"
    assert load.scenario_role == "real_archive_mesh_editor_load"
    assert load.real_game is True


def test_real_archive_mesh_editor_load_scenario_dispatches_registered_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    game_root = tmp_path / "game"
    proof = {"ok": True, "read_only": True, "runs": [{"label": "cold"}]}
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setattr(
        scenario_runner,
        "run_real_archive_mesh_editor_load_smoke",
        lambda root, output: calls.append((root, output)) or proof,
    )

    result = scenario_runner.run_scenario(
        "real-archive-mesh-editor-load-smoke",
        tmp_path / "output",
        game_root=game_root,
    )

    assert result["ok"] is True
    assert result["real_archive_mesh_editor_load"] == proof
    assert calls == [(game_root, tmp_path / "output")]


def test_default_cli_uses_rust_real_proof_and_game_root_resolution_order(monkeypatch, tmp_path: Path) -> None:
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
    assert calls[0] == (_REAL_MESH_EDITOR_PRODUCTION_SCENARIO, tmp_path / "environment-output", environment_root)
    assert calls[1] == (_REAL_MESH_EDITOR_PRODUCTION_SCENARIO, tmp_path / "explicit-output", explicit_root)
