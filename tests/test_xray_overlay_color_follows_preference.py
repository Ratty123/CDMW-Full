"""X-Ray must draw the wire colour the reader chose.

X-Ray draws topology through the surface, so the default black wire is
unreadable there and falls back to a high-contrast automatic colour. That
fallback was unconditional: a wire colour set in Preview Settings was discarded
the moment the display mode became X-Ray, which reads as the setting being
ignored.

The rule is now "automatic only while untouched". These pin both directions,
because a fix that simply deleted the fallback would leave an untouched
preference drawing black-on-dark and nothing would have caught it.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = REPO_ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET_ROOT / name).read_text(encoding="utf-8")


def test_active_wire_keeps_the_automatic_colour_only_while_untouched() -> None:
    colors = _source("MeshOverlayColors.cs")

    assert (
        "xray && Wire.ToArgb() == Default.Wire.ToArgb() ? AutomaticXRayWire : Wire"
        in colors
    ), "X-Ray no longer honours a chosen wire colour, or no longer falls back"
    assert (
        "xray && Vertex.ToArgb() == Default.Vertex.ToArgb() ? AutomaticXRayVertex : Vertex"
        in colors
    )
    # Compared by ARGB rather than Color equality: a parsed colour and a
    # FromArgb constant differ in their known-colour state even when the pixels
    # are identical, and that would silently disable the fallback.
    assert "xray ? AutomaticXRayWire : Wire" not in colors
    assert "xray ? AutomaticXRayVertex : Vertex" not in colors


def test_the_d3d11_viewport_derives_its_xray_colours_from_the_settings() -> None:
    overlay = _source("D3D11MaterialViewport.Overlay.cs")

    # The renderer used its own fixed constants, a second copy of the decision
    # that MeshOverlayColors already owns.
    assert "XRayWireOverlayColor = OverlayColor(245, 248, 252, 240)" not in overlay
    assert "XRayVertexOverlayColor = OverlayColor(255, 88, 214, 255)" not in overlay
    assert "_xrayWireOverlayColor = XRayOverlayColor(colors.ActiveWire(true), 240);" in overlay
    assert "_xrayVertexOverlayColor = XRayOverlayColor(colors.ActiveVertex(true), 255);" in overlay
    # Both draw sites must read the derived field, not a constant.
    assert "_overlayShowXRay ? _xrayWireOverlayColor : _wireOverlayColor," in overlay
    assert "Color = _overlayShowXRay ? _xrayVertexOverlayColor : _vertexOverlayColor," in overlay


def test_metrics_report_the_colour_xray_would_actually_draw() -> None:
    metrics = _source("D3D11MaterialViewport.Metrics.cs")

    assert "_overlaySettings.Colors.ActiveWire(true)" in metrics
    assert "_overlaySettings.Colors.ActiveVertex(true)" in metrics
    # Reporting the constant is what let the evidence agree with itself while
    # the viewport drew something else.
    assert "MeshOverlayColors.Hex(MeshOverlayColors.AutomaticXRayWire)" not in metrics
    assert "MeshOverlayColors.Hex(MeshOverlayColors.AutomaticXRayVertex)" not in metrics


def test_the_gdi_and_wpf_paths_share_the_same_decision() -> None:
    """Three renderers draw this overlay; none may keep its own rule."""
    painting = _source("MeshViewport.Painting.cs")
    wpf = _source("WpfGpuMeshViewport.cs")

    assert "_overlaySettings.Colors.ActiveWire(ShowXRay)" in painting
    assert "_overlaySettings.Colors.ActiveWire(showXRay)" in wpf
    for source in (painting, wpf):
        assert "AutomaticXRayWire" not in source
        assert "AutomaticXRayVertex" not in source
