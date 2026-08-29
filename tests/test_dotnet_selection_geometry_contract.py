from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
HELPER = (
    ROOT
    / "tools"
    / "dotnet_mesh_editor_experiment"
    / "bin"
    / "Release"
    / "net10.0-windows"
    / "cdmw-mesh-dotnet-editor.dll"
)


def test_selection_geometry_contract_executes_all_25_cases() -> None:
    assert HELPER.is_file(), f"Release Mesh Editor helper is missing: {HELPER}"
    with tempfile.TemporaryDirectory(prefix="cdmw-selection-geometry-") as temp_dir:
        report = Path(temp_dir) / "selection-geometry.json"
        completed = subprocess.run(
            (
                "dotnet",
                str(HELPER),
                "--headless-selection-geometry-contract",
                "--selection-geometry-report",
                str(report),
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        payload = json.loads(report.read_text(encoding="utf-8"))

    assert payload["schema"] == "cdmw_selection_geometry_contract_v1"
    assert payload["ok"] is True
    assert payload["case_count"] == 25
    assert len(payload["gates"]) == 25
    assert all(payload["gates"].values())
    assert payload["coordinate_epsilon"] == 1.0e-9
    assert payload["degenerate_squared_length"] == 1.0e-12
    assert payload["degenerate_projected_area"] == 1.0e-12
    assert payload["front_facing_projected_area"] == 0.01
    assert payload["boundary_policy"] == "inclusive"
    assert payload["repeated_iterations"] == 1000


def test_production_selection_geometry_consumers_use_the_single_owner() -> None:
    owner = (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "SelectionGeometry.cs").read_text(
        encoding="utf-8"
    )
    general = (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "MeshViewport.Geometry.cs").read_text(
        encoding="utf-8"
    )
    picking = (
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "MeshViewport.SelectionPicking.cs"
    ).read_text(encoding="utf-8")
    provisional = (
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "MeshViewport.ProvisionalStrokes.cs"
    ).read_text(encoding="utf-8")
    gpu_soak = (
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "HeadlessGpuInteractionSoak.cs"
    ).read_text(encoding="utf-8")

    assert "matching the native screen-selection owner" in owner
    assert "internal static bool SegmentsIntersect" in owner
    assert "internal static bool PolygonIntersectsTriangle" in owner
    assert "internal static bool RectangleIntersectsTriangle" in owner
    assert "internal static bool SubmeshAllowsSelection" in owner
    assert "LinesIntersect" not in general
    assert "PointInTriangle" not in general
    assert "SegmentIntersectsRectangle" not in general
    assert "DistanceToSegment" not in general
    assert "SelectionPointInTriangle" not in picking
    assert "SelectionSegmentsIntersect" not in picking
    assert "SelectionPolygonIntersectsTriangle" not in picking
    assert "SelectionPointInPolygon" not in picking
    assert "SelectionGeometry.RectangleIntersectsTriangle" in picking
    assert "SelectionGeometry.SubmeshAllowsSelection" in picking
    assert "private static float DistanceToSegment" not in provisional
    assert "SelectionGeometry.IsFrontFacingProjectedTriangle" in provisional
    assert "SelectionGeometry.SegmentsIntersect" in gpu_soak


def test_csharp_tolerance_policy_matches_authoritative_native_screen_selection() -> None:
    owner = (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "SelectionGeometry.cs").read_text(
        encoding="utf-8"
    )
    native = (
        ROOT / "native" / "cdmw_mesh_core" / "src" / "owners" / "session_state_02.cpp"
    ).read_text(encoding="utf-8")

    assert "CoordinateEpsilon = 1.0e-9" in owner
    assert "DegenerateSquaredLength = 1.0e-12" in owner
    assert "DegenerateProjectedArea = 1.0e-12" in owner
    assert "constexpr double epsilon = 1.0e-9" in native
    assert "const double t = length_squared <= 1.0e-12" in native
    assert "if (std::abs(area) <= 1.0e-12)" in native
