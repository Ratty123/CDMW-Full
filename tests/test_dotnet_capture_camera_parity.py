"""An icon captured from the resident viewport shows the view on screen.

`D3D11MaterialViewport.CameraForCaptureViewport` re-aims the visible camera at the
capture's size. From 2026-07-17 it built that camera from `NetViewportCamera.World`
and a fresh projection. The interactive `NetViewportCamera.Create` writes `World` and
`WorldViewProjection` as two hand-built matrices that do not encode the same rotation
(and fold the pan in at different points), so the capture agreed with the screen only
at yaw 0 -- the overhead framing a weapon loads with -- and a view the user had orbited
captured at another angle: New Item Studio's *Take the icon from this view* and the
Model Library's icon capture both went through it.

The helper's GPU-free proof runs the real method over the real camera constructors at
several yaws, pitches and pans and compares where the same points land. It starts no
renderer and no window, and reads no licensed asset.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = REPO_ROOT / "tools" / "dotnet_mesh_editor_experiment"
DOTNET_PROJECT = DOTNET_ROOT / "Cdmw.MeshEditorExperiment.csproj"
DOTNET_HELPER = DOTNET_ROOT / "bin" / "Release" / "net10.0-windows" / "cdmw-mesh-dotnet-editor.dll"


def _build_helper() -> Path:
    completed = subprocess.run(
        [
            "dotnet",
            "build",
            str(DOTNET_PROJECT),
            "--configuration",
            "Release",
            "--nologo",
            "--verbosity:quiet",
        ],
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout
    assert DOTNET_HELPER.is_file(), completed.stdout
    return DOTNET_HELPER


def _run_proof() -> dict:
    with tempfile.TemporaryDirectory(prefix="cdmw-capture-camera-") as temp_dir:
        helper = _build_helper()
        report_path = Path(temp_dir) / "capture-camera.json"
        completed = subprocess.run(
            [
                "dotnet",
                str(helper),
                "--headless-capture-camera-parity",
                "--capture-camera-report",
                str(report_path),
            ],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
        assert report_path.is_file(), (
            f"capture camera parity proof exited {completed.returncode} without a report: {completed.stderr}"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "error" not in report, json.dumps(report, indent=2)
    report["_returncode"] = completed.returncode
    return report


def test_the_capture_camera_is_the_screen_camera_at_every_view() -> None:
    report = _run_proof()
    assert report["schema"] == "cdmw_capture_camera_parity_v1"
    assert report["renderer_started"] is False
    assert report["visible_window_started"] is False

    gates = report["gates"]
    same_size = {entry["view"]: entry for entry in report["same_size"]}
    # The defect itself: a capture at the viewport's own size, from a view orbited
    # away from yaw 0, landed its points somewhere else than the screen did.
    for view in ("three_quarter", "orbited", "behind_high", "side_panned"):
        assert same_size[view]["ok"] is True, json.dumps(same_size[view], indent=2)
        assert same_size[view]["max_error_px"] <= report["pixel_tolerance"]
    # A vertical pan at the overhead pitch was nearly dropped from the capture.
    assert same_size["overhead_panned"]["ok"] is True, json.dumps(same_size["overhead_panned"], indent=2)
    assert gates["interactive_capture_matches_screen"] is True, json.dumps(report["same_size"], indent=2)

    # A smaller square icon is the same camera re-made at the scaled zoom and pan,
    # which is what `capture_replacement_icon` documents.
    assert gates["interactive_icon_capture_is_the_camera_rescaled"] is True, json.dumps(report["rescaled"], indent=2)

    # The visual audit's camera keeps the archive object-rotation basis its baselines
    # were measured against.
    assert gates["archive_audit_capture_keeps_object_rotation_basis"] is True, json.dumps(report["archive_audit"], indent=2)

    assert report["ok"] is True
    assert report["_returncode"] == 0


def test_the_world_matrix_is_the_view_frame_the_projection_draws_in() -> None:
    """Lighting (`World`, `NormalWorld`) and the transparent sort read the camera's World
    matrix, and the geometry is drawn through its WorldViewProjection. Until 2026-08-22
    the interactive camera built them as two hand-written matrices with different
    rotations (and the pan folded in at different points), so the lit side agreed with
    the surface at yaw 0 and drifted against it as the view turned. The proof checks, at
    the same views, that World times the projection lands the same points in the same
    pixels as WorldViewProjection, that the camera's right, up and forward land on the
    frame's axes, that the rotation is proper, and that at yaw 0 with no pan the matrix
    is still the one the lighting was tuned on."""
    report = _run_proof()
    view_frame = {entry["view"]: entry for entry in report["view_frame"]}
    for view in ("three_quarter", "orbited", "behind_high", "side_panned", "overhead_panned"):
        assert view_frame[view]["ok"] is True, json.dumps(view_frame[view], indent=2)
        assert view_frame[view]["max_error_px"] <= report["pixel_tolerance"]
        assert abs(view_frame[view]["rotation_determinant"] - 1.0) <= 1e-4
    # The frame every baseline was rendered in: unchanged where they were taken.
    for view in ("front", "weapon_overhead"):
        assert view_frame[view]["yaw_zero_unchanged"] is True, json.dumps(view_frame[view], indent=2)
    assert report["gates"]["interactive_world_is_the_view_frame_of_the_projection"] is True
    assert report["gates"]["interactive_world_unchanged_at_yaw_zero"] is True


def test_a_plain_left_drag_turns_the_near_side_with_the_pointer() -> None:
    """Every resident viewport (Mesh Editor, Archive Browser preview, the New Item Studio
    placement and icon viewports) shares the helper's camera, and until 2026-08-22 its
    horizontal orbit ran against the pointer while the vertical orbit and both pan axes
    ran with it: drag right and the side of the model facing you slid left. The proof
    drives the viewport's own move handler on a synthetic mesh and reads where the vertex
    drawn nearest the reader lands, by the renderer's depth: right for a drag to the
    right, down for a drag downward."""
    report = _run_proof()
    orbit = report["orbit"]
    assert orbit["near_side_follows_drag_right"] is True, json.dumps(orbit, indent=2)
    assert orbit["near_side_follows_drag_down"] is True, json.dumps(orbit, indent=2)
    assert report["gates"]["orbit_follows_pointer"] is True, json.dumps(orbit, indent=2)
