using System.Drawing;
using System.Numerics;
using Vortice.Direct3D;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private GizmoAppearance _gizmoAppearance = GizmoAppearance.Default;
    private long _gizmoOverlayDrawCount;

    public void SetGizmoAppearance(GizmoAppearance appearance)
    {
        _gizmoAppearance = appearance.Normalized();
    }

    private void DrawSceneGizmo()
    {
        if (!ActivePaneGizmoVisible || _scene.EditableSubmeshCount <= 0) return;
        _gizmoOverlayDrawCount++;
        var origin = string.Equals(_activeRenderPane?.Role, "editable", StringComparison.OrdinalIgnoreCase)
            ? _scene.RoleViewGizmoPivot()
            : _scene.EffectiveGizmoPivot();
        var length = _gizmoAppearance.ScaleLength(
            Math.Max(_scene.SceneExtent * 0.18f, _scene.GridSpacing * 2.0f));
        if (_scene.GizmoTool == "rotate")
        {
            DrawGizmoCircle(origin, length, 0, "x", GizmoAxisColor("x"));
            DrawGizmoCircle(origin, length, 1, "y", GizmoAxisColor("y"));
            DrawGizmoCircle(origin, length, 2, "z", GizmoAxisColor("z"));
            return;
        }
        DrawGizmoAxis(origin, new Vector3(length, 0, 0), "x", GizmoAxisColor("x"));
        DrawGizmoAxis(origin, new Vector3(0, length, 0), "y", GizmoAxisColor("y"));
        DrawGizmoAxis(origin, new Vector3(0, 0, length), "z", GizmoAxisColor("z"));
        if (_scene.GizmoTool == "move")
        {
            DrawGizmoPlane(origin, length, Vector3.UnitX, Vector3.UnitY, OverlayColor(235, 215, 85, 210));
            DrawGizmoPlane(origin, length, Vector3.UnitX, Vector3.UnitZ, OverlayColor(215, 85, 235, 210));
            DrawGizmoPlane(origin, length, Vector3.UnitY, Vector3.UnitZ, OverlayColor(85, 220, 225, 210));
        }
        else if (_scene.GizmoTool == "scale")
        {
            var size = Math.Max(length * 0.055f, 0.001f);
            var lines = ResetScratchA();
            lines.Add(origin - new Vector3(size, 0, 0));
            lines.Add(origin + new Vector3(size, 0, 0));
            lines.Add(origin - new Vector3(0, size, 0));
            lines.Add(origin + new Vector3(0, size, 0));
            lines.Add(origin - new Vector3(0, 0, size));
            lines.Add(origin + new Vector3(0, 0, size));
            DrawOverlayPrimitive(
                PrimitiveTopology.LineList,
                lines,
                GizmoColor(_gizmoAppearance.Label, 245),
                _camera.WorldViewProjection,
                lineWidthPixels: _gizmoAppearance.LineThicknessPixels);
        }
    }

    private Vector4 GizmoAxisColor(string handle)
    {
        if (string.Equals(_scene.ActiveGizmoHandle, handle, StringComparison.Ordinal)
            || string.Equals(_scene.HoveredGizmoHandle, handle, StringComparison.Ordinal))
        {
            return GizmoColor(_gizmoAppearance.Highlight);
        }
        return GizmoColor(_gizmoAppearance.Axis(handle));
    }

    private void DrawGizmoAxis(Vector3 origin, Vector3 axis, string label, Vector4 color)
    {
        var lines = ResetScratchA();
        lines.Add(origin);
        lines.Add(origin + axis);
        if (_scene.GizmoTool == "scale")
        {
            var tip = origin + axis;
            var size = Math.Max(axis.Length() * 0.08f, 0.001f);
            lines.Add(tip - new Vector3(size, 0, 0)); lines.Add(tip + new Vector3(size, 0, 0));
            lines.Add(tip - new Vector3(0, size, 0)); lines.Add(tip + new Vector3(0, size, 0));
            lines.Add(tip - new Vector3(0, 0, size)); lines.Add(tip + new Vector3(0, 0, size));
        }
        DrawOverlayPrimitive(
            PrimitiveTopology.LineList,
            lines,
            color,
            _camera.WorldViewProjection,
            lineWidthPixels: _gizmoAppearance.LineThicknessPixels);
        DrawGizmoHandleMarker(origin + axis, label, color);
    }

    private void DrawGizmoPlane(Vector3 origin, float length, Vector3 firstAxis, Vector3 secondAxis, Vector4 color)
    {
        var a = origin + (firstAxis * length * 0.22f);
        var b = origin + (firstAxis * length * 0.42f);
        var c = origin + (secondAxis * length * 0.42f);
        var d = origin + (secondAxis * length * 0.22f);
        var lines = ResetScratchA();
        lines.Add(a); lines.Add(b);
        lines.Add(b); lines.Add(c);
        lines.Add(c); lines.Add(d);
        lines.Add(d); lines.Add(a);
        DrawOverlayPrimitive(
            PrimitiveTopology.LineList,
            lines,
            color,
            _camera.WorldViewProjection,
            lineWidthPixels: _gizmoAppearance.LineThicknessPixels);
    }

    private void DrawGizmoCircle(Vector3 origin, float radius, int normalAxis, string label, Vector4 color)
    {
        const int segments = 48;
        var lines = ResetScratchA();
        for (var index = 0; index < segments; index++)
        {
            var a = index * MathF.Tau / segments;
            var b = (index + 1) * MathF.Tau / segments;
            lines.Add(GizmoCirclePoint(origin, radius, normalAxis, a));
            lines.Add(GizmoCirclePoint(origin, radius, normalAxis, b));
        }
        DrawOverlayPrimitive(
            PrimitiveTopology.LineList,
            lines,
            color,
            _camera.WorldViewProjection,
            lineWidthPixels: _gizmoAppearance.LineThicknessPixels);
        var markerAngle = normalAxis == 1 ? MathF.PI * 0.5f : 0.0f;
        DrawGizmoHandleMarker(GizmoCirclePoint(origin, radius, normalAxis, markerAngle), label, color);
    }

    private void DrawGizmoHandleMarker(Vector3 worldPoint, string label, Vector4 color)
    {
        var point = _camera.Project(new Vec3(worldPoint.X, worldPoint.Y, worldPoint.Z));
        var handleHalfSize = _gizmoAppearance.HandleSizePixels * 0.5f;
        var marker = ResetScratchA();
        AddScreenQuad(
            point.X - handleHalfSize,
            point.Y - handleHalfSize,
            point.X + handleHalfSize,
            point.Y + handleHalfSize,
            marker);
        DrawOverlayPrimitive(PrimitiveTopology.TriangleList, marker, color, Matrix4x4.Identity);

        var height = _gizmoAppearance.LabelSizePixels;
        var width = height * (7.0f / 12.0f);
        var left = point.X + handleHalfSize + 4.0f;
        var top = point.Y - (height * 0.5f);
        var glyph = ResetScratchA();
        switch (label)
        {
            case "x":
                AddScreenLine(left, top, left + width, top + height, glyph);
                AddScreenLine(left + width, top, left, top + height, glyph);
                break;
            case "y":
                AddScreenLine(left, top, left + width * 0.5f, top + height * 0.5f, glyph);
                AddScreenLine(left + width, top, left + width * 0.5f, top + height * 0.5f, glyph);
                AddScreenLine(left + width * 0.5f, top + height * 0.5f, left + width * 0.5f, top + height, glyph);
                break;
            default:
                AddScreenLine(left, top, left + width, top, glyph);
                AddScreenLine(left + width, top, left, top + height, glyph);
                AddScreenLine(left, top + height, left + width, top + height, glyph);
                break;
        }
        DrawOverlayPrimitive(
            PrimitiveTopology.LineList,
            glyph,
            GizmoColor(_gizmoAppearance.Label),
            Matrix4x4.Identity,
            lineWidthPixels: _gizmoAppearance.LineThicknessPixels);
    }

    private static Vector4 GizmoColor(Color color, int alpha = 255) =>
        OverlayColor(color.R, color.G, color.B, alpha);
}
