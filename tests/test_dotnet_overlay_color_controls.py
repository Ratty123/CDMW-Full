from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


def _source(name: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (
        root / "tools" / "dotnet_mesh_editor_experiment" / name
    ).read_text(encoding="utf-8")


def test_overlay_appearance_controls_persist_colors_and_bounded_sizes() -> None:
    root = Path(__file__).resolve().parents[1]
    project = root / "tools" / "dotnet_mesh_editor_experiment" / "Cdmw.MeshEditorExperiment.csproj"
    with tempfile.TemporaryDirectory(prefix="cdmw-overlay-controls-") as temp_dir:
        report_path = Path(temp_dir) / "layout.json"
        completed = subprocess.run(
            [
                "dotnet",
                "run",
                "--project",
                str(project),
                "--configuration",
                "Release",
                "--no-launch-profile",
                "--",
                "--headless-edit-mesh-layout-smoke",
                "--layout-report",
                str(report_path),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        report = json.loads(report_path.read_text(encoding="utf-8"))

    proof = report["overlay_appearance"]
    assert proof["schema"] == "cdmw_mesh_overlay_preferences_v3"
    assert proof["save_load"] is True
    assert proof["v1_migration"] is True
    assert proof["v2_migration"] is True
    assert proof["controls"] == {
        "control_count": 7,
        "wire_width": 2.25,
        "vertex_size": 11.5,
        "selection_color": "#708090",
        "live_selection_color": "#A0B0C0",
    }


def test_wire_vertices_and_custom_selection_colors_render_in_all_backends() -> None:
    root = Path(__file__).resolve().parents[1]
    project = root / "tools" / "dotnet_mesh_editor_experiment" / "Cdmw.MeshEditorExperiment.csproj"
    with tempfile.TemporaryDirectory(prefix="cdmw-selection-renderer-") as temp_dir:
        report_path = Path(temp_dir) / "renderer.json"
        completed = subprocess.run(
            [
                "dotnet",
                "run",
                "--project",
                str(project),
                "--configuration",
                "Release",
                "--no-launch-profile",
                "--",
                "--headless-gpu-sparse-soak",
                "--gpu-soak-smoke",
                "--gpu-soak-vertices",
                "1000",
                "--gpu-soak-updates",
                "4",
                "--gpu-soak-warmup",
                "1",
                "--gpu-soak-no-cadence",
                "--gpu-soak-report",
                str(report_path),
            ],
            cwd=root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stderr
        report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["gates"]["wire_vertices_draws_no_solid_fill"] is True
    assert report["gates"]["custom_selection_colors_reach_d3d11_draws"] is True
    assert report["gates"]["custom_selection_colors_reach_wpf_and_gdi_paths"] is True
    d3d = report["xray_overlay_proof"]
    # X-Ray draws the chosen colours, and falls back to the automatic
    # high-contrast palette only for an untouched preference. Both directions
    # matter: dropping either one is a defect the reader sees immediately.
    assert d3d["chosen_palette_active"] is True
    assert d3d["xray_wire_color"] == "#0C2238"
    assert d3d["xray_vertex_color"] == "#4E5A7B"
    assert d3d["automatic_palette_active"] is True
    assert d3d["configured_selection_color"] == "#919CA7"
    assert d3d["configured_live_selection_color"] == "#B2BDC8"
    assert d3d["last_committed_selection_draw_color"] == "#919CA7"
    assert d3d["last_live_selection_draw_color"] == "#B2BDC8"
    assert d3d["committed_selection_primitives_after"] > d3d["committed_selection_primitives_before"]
    assert d3d["live_selection_primitives_after"] > d3d["live_selection_primitives_before"]
    for backend in ("wpf", "gdi"):
        proof = report["fallback_selection_color_proof"][backend]
        assert proof["committed_color"] == "#919CA7"
        assert proof["live_color"] == "#B2BDC8"
        assert all(
            proof[key] is True
            for key in (
                "committed_faces",
                "committed_wires",
                "committed_vertices",
                "live_faces",
                "live_wires",
                "live_vertices",
            )
        )


def test_opening_morph_page_preserves_renderer_and_camera_state() -> None:
    root = Path(__file__).resolve().parents[1]
    project = root / "tools" / "dotnet_mesh_editor_experiment" / "Cdmw.MeshEditorExperiment.csproj"
    with tempfile.TemporaryDirectory(prefix="cdmw-morph-page-stability-") as temp_dir:
        report_path = Path(temp_dir) / "morph.json"
        completed = subprocess.run(
            [
                "dotnet",
                "run",
                "--project",
                str(project),
                "--configuration",
                "Release",
                "--no-launch-profile",
                "--",
                "--headless-morph-page-stability-smoke",
                "--morph-stability-report",
                str(report_path),
            ],
            cwd=root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stderr
        report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["ok"] is True
    assert report["redraw_scope"] == "tool_column"
    assert report["before"] == report["after"]
    assert report["before"]["source_parse_count"] == 1
    assert report["before"]["geometry_upload_count"] == 1
    assert report["before"]["active_tool"] == "orbit"
    assert report["before"]["helper_pid"] > 0
    assert report["before"]["viewport_hwnd"] > 0
    assert len(report["activation_cases"]) == 9
    assert all(case["stable"] for case in report["activation_cases"])


def test_xray_state_reaches_each_render_pane_and_refreshes_the_gpu_viewport() -> None:
    controls = _source("ExperimentForm.Controls.cs")
    display_modes = _source("MeshViewport.DisplayModes.cs")
    presentation = _source("MeshViewport.Presentation.cs")
    split_view = _source("MeshViewport.SplitView.cs")
    panes = _source("D3D11MaterialViewport.Panes.cs")

    assert "_viewport.SetXRayEnabled(_xray.Checked)" in controls
    assert "if (!_xray.Checked && _previewMode.SelectedIndex == 6)" in controls
    assert "public void SetXRayEnabled(bool enabled)" in display_modes
    assert "context.XRay = enabled;" in display_modes
    assert "UpdateGpuViewport();" in display_modes
    assert '"xray" => new(normalized, false, true, true, true, false)' in display_modes
    assert "public bool XRay { get; set; }" in presentation
    assert "context.XRay," in split_view
    assert "bool XRay," in panes
    assert "_overlayShowXRay = pane.XRay || display.XRay;" in panes


def test_xray_renderer_uses_no_depth_wire_and_vertex_passes_with_hidden_gpu_proof() -> None:
    overlay = _source("D3D11MaterialViewport.Overlay.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")
    selection = _source("MeshViewport.SelectionPicking.cs")
    headless = _source("HeadlessGpuSparseSoak.cs") + _source("HeadlessGpuSparseSoak.XRay.cs")

    no_depth = overlay.index("_overlayCommandDepthMode = 1;")
    xray_wire = overlay.index("DrawD3D11WireOverlay();", no_depth)
    xray_vertices = overlay.index("QueueD3D11VertexOverlay();", xray_wire)
    assert no_depth < xray_wire < xray_vertices
    assert "_xRayWireNoDepthDrawCount++" in overlay
    assert "_xRayVertexNoDepthPassCount++" in overlay
    assert '["xray_wire_no_depth_draws"]' in metrics
    assert '["xray_vertex_no_depth_passes"]' in metrics
    assert "SelectionGeometry.RequiresVisibleDepth(ShowXRay)" in selection
    assert "ApplyXRayOverlayProof" in headless
    assert 'gates["xray_overlay_draws_wire_and_vertices_without_depth"]' in headless
    assert 'gates["configurable_wire_width_and_vertex_size"]' in headless
    assert '["automatic_palette_active"]' in headless
    assert '["configured_sizing_active"]' in headless
