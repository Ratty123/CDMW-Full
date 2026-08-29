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


def test_stroke_sample_buffer_contract_executes_csharp_behavior() -> None:
    assert HELPER.is_file(), f"Release Mesh Editor helper is missing: {HELPER}"
    with tempfile.TemporaryDirectory(prefix="cdmw-stroke-samples-") as temp_dir:
        report = Path(temp_dir) / "stroke-samples.json"
        completed = subprocess.run(
            (
                "dotnet",
                str(HELPER),
                "--headless-stroke-sample-buffer-contract",
                "--stroke-sample-buffer-report",
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

    assert payload["schema"] == "cdmw_stroke_sample_buffer_contract_v1"
    assert payload["ok"] is True
    assert all(payload["gates"].values())
    assert payload["raw_samples"] == 2401
    assert payload["straight_retained_samples"] < 60
    assert payload["curved_retained_samples"] == 256
    assert payload["max_samples"] == 256
    assert payload["min_spacing_pixels"] == 2.5
    assert payload["max_interval_ms"] == 50
    assert payload["smooth_coverage_max_error_pixels"] <= 3.0
    assert payload["terminal_processing_ms"] < 10.0


def test_lasso_toggle_and_protocol_paths_use_the_executable_buffer_owner() -> None:
    program = (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "Program.cs").read_text(encoding="utf-8")
    paint = (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "MeshViewport.SelectionPaint.cs").read_text(encoding="utf-8")
    runtime = (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.Runtime.cs").read_text(encoding="utf-8")

    assert "StrokeSampleBuffer _selectionLassoPoints" in program
    assert "StrokeSampleBuffer _selectionPaintPathPoints" in program
    assert "StrokeSampleBuffer _selectionPaintPendingPath" in paint
    assert 'merged["screen_path"] = BoundedProtocolStrokePath(path);' in runtime
