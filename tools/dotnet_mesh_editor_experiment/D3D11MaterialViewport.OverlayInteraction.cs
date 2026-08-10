using System.Numerics;
using Vortice.Direct3D;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private void DrawSelectionRectangleOverlay()
    {
        if (!_overlaySelectionRectangle.HasValue)
        {
            return;
        }
        var rect = _overlaySelectionRectangle.Value;
        var triangles = ResetScratchA();
        AddScreenQuad(rect.Left, rect.Top, rect.Right, rect.Bottom, triangles);
        DrawOverlayPrimitive(PrimitiveTopology.TriangleList, triangles, OverlayColor(_overlaySettings.Colors.LiveSelection, 36), Matrix4x4.Identity);
        var lines = ResetScratchA();
        AddScreenRectangle(rect.Left, rect.Top, rect.Right, rect.Bottom, lines);
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, OverlayColor(_overlaySettings.Colors.LiveSelection, 210), Matrix4x4.Identity);
    }

    /// <summary>
    /// The lasso drag draws the path actually swept -- the polygon the native
    /// side will test -- with a fainter closing segment back to the start,
    /// the way Blender previews an unclosed lasso.
    /// </summary>
    private void DrawSelectionLassoOverlay()
    {
        var path = _overlayLassoPath;
        if (path is null || path.Count < 2)
        {
            return;
        }
        var lines = ResetScratchA();
        for (var index = 1; index < path.Count; index++)
        {
            AddScreenLine(path[index - 1].X, path[index - 1].Y, path[index].X, path[index].Y, lines);
        }
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, OverlayColor(_overlaySettings.Colors.LiveSelection, 210), Matrix4x4.Identity);
        if (path.Count >= 3)
        {
            var closing = ResetScratchA();
            AddScreenLine(path[^1].X, path[^1].Y, path[0].X, path[0].Y, closing);
            DrawOverlayPrimitive(PrimitiveTopology.LineList, closing, OverlayColor(_overlaySettings.Colors.LiveSelection, 110), Matrix4x4.Identity);
        }
    }

    private void DrawXRayOverlayMarker()
    {
        var lines = ResetScratchA();
        AddScreenLine(8.0f, 8.0f, 32.0f, 24.0f, lines);
        AddScreenLine(32.0f, 8.0f, 8.0f, 24.0f, lines);
        AddScreenLine(40.0f, 8.0f, 58.0f, 24.0f, lines);
        AddScreenLine(58.0f, 8.0f, 40.0f, 24.0f, lines);
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, OverlayColor(165, 215, 255, 235), Matrix4x4.Identity);
    }

    private void DrawBrushCursorOverlay()
    {
        if (!_overlayBrushCursor.HasValue)
        {
            return;
        }
        const int segments = 48;
        var center = _overlayBrushCursor.Value;
        var lines = ResetScratchA();
        for (var index = 0; index < segments; index++)
        {
            var start = index * MathF.Tau / segments;
            var end = (index + 1) * MathF.Tau / segments;
            AddScreenLine(
                center.X + MathF.Cos(start) * _overlayBrushRadius,
                center.Y + MathF.Sin(start) * _overlayBrushRadius,
                center.X + MathF.Cos(end) * _overlayBrushRadius,
                center.Y + MathF.Sin(end) * _overlayBrushRadius,
                lines);
        }
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, OverlayColor(255, 224, 92, 245), Matrix4x4.Identity);
    }
}
