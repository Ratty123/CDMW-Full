from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def test_alignment_gizmo_visuals_keep_generous_vortice_hit_targets() -> None:
    appearance = (DOTNET_ROOT / "GizmoAppearance.cs").read_text(encoding="utf-8")
    draw = (DOTNET_ROOT / "D3D11MaterialViewport.Gizmo.cs").read_text(encoding="utf-8")
    hit = (DOTNET_ROOT / "MeshViewport.Gizmo.cs").read_text(encoding="utf-8")

    assert "MinimumLineThicknessPixels = 1.0f" in appearance
    assert "MaximumLineThicknessPixels = 6.0f" in appearance
    assert draw.count("lineWidthPixels: _gizmoAppearance.LineThicknessPixels") == 5
    for unchanged_hit_rule in (
        "Math.Max(9.0, _gizmoAppearance.LineThicknessPixels + 4.0)",
        "Math.Max(8.0, (_gizmoAppearance.HandleSizePixels * 0.5f) + 4.0f)",
        "var left = -(handleHalfSize + 3.0f);",
        "var right = handleHalfSize + 4.0f + labelWidth + 8.0f;",
    ):
        assert unchanged_hit_rule in hit
