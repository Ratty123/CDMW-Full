from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OWNERS = ROOT / "native" / "cdmw_d3d11_preview" / "src" / "owners"


def test_alignment_gizmo_visuals_are_thinner_without_smaller_hit_targets() -> None:
    draw = (OWNERS / "renderer_geometry_overlays.cpp").read_text(encoding="utf-8")
    hit = (OWNERS / "renderer_render_alignment.cpp").read_text(encoding="utf-8")
    assert "constexpr float kAlignmentGizmoVisualScale = 0.65f;" in draw
    assert draw.count("width_pixels *= kAlignmentGizmoVisualScale;") == 2
    assert draw.count("radius *= kAlignmentGizmoVisualScale;") == 1
    for unchanged_hit_rule in (
        "float best_distance = 30.0f;",
        "center_distance > 12.0f",
        "center_distance <= 26.0f",
        "distance >= 34.0f && distance <= 58.0f",
        "distance >= 62.0f && distance <= 84.0f",
    ):
        assert unchanged_hit_rule in hit
