from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET_ROOT / name).read_text(encoding="utf-8")


def test_dotnet_wheel_zoom_is_reversible_and_uses_fit_relative_bounds() -> None:
    policy = _source("CameraZoomPolicy.cs")
    input_source = _source("MeshViewport.Input.cs")
    presentation_source = _source("MeshViewport.Presentation.cs")
    split_view_source = _source("MeshViewport.SplitView.cs")
    host_presentation_source = (
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_presentation.py"
    ).read_text(encoding="utf-8")

    assert "MathF.Pow(WheelZoomPerNotch, wheelNotches)" in policy
    assert "Math.Min(LegacyMinimumZoom, safeFitZoom * MinimumFitZoomRatio)" in policy
    assert "Math.Max(LegacyMaximumZoom, safeFitZoom * MaximumFitZoomRatio)" in policy
    assert "CameraZoomPolicy.ApplyWheelDelta(" in input_source
    assert "SaveActivePresentationContext();" in input_source
    assert "_zoom *= e.Delta > 0 ? 1.1f : 0.9f;" not in input_source
    assert "Math.Clamp(_zoom, 1.0f, 500000.0f)" not in input_source
    assert "CameraZoomPolicy.ApplyZoomFactor(" in presentation_source
    assert "Math.Clamp(_zoom * zoomFactor, 1.0f, 500000.0f)" not in presentation_source
    assert "CameraBoundsForContext" in split_view_source
    assert "context.CameraMinimum" in split_view_source
    assert 'stamped_camera["command_generation"] = generation' in host_presentation_source
    assert 'set(state or {}) == {"camera"}' in host_presentation_source

    wheel_handler = input_source.split(
        "protected override void OnMouseWheel", maxsplit=1
    )[1].split("private static bool IsPanGesture", maxsplit=1)[0]
    assert "InteractionMode" not in wheel_handler
    assert "CameraZoomPolicy.ApplyWheelDelta(" in wheel_handler


def test_hidden_runtime_proof_covers_shared_reversible_zoom_policy() -> None:
    soak = _source("HeadlessGpuSparseSoak.cs")

    assert "CameraZoomProof()" in soak
    assert 'gates["placement_and_mesh_edit_wheel_zoom_reversible"]' in soak
    assert '["reciprocal_error"]' in soak
