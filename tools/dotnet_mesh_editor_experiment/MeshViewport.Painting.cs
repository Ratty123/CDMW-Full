using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private long _gdiFallbackFrameCount;

    protected override void OnPaint(PaintEventArgs e)
    {
        var started = _clock.ElapsedTicks;
        if (_d3d11Viewport is not null)
        {
            // The child HWND owns production presentation. Painting the CPU/GDI
            // fallback underneath it duplicates every face on the UI thread.
            base.OnPaint(e);
            return;
        }
        if (_gpuViewport is not null)
        {
            RecordRenderedFrame((_clock.ElapsedTicks - started) * 1000.0 / Stopwatch.Frequency, 0.0, string.Empty);
            base.OnPaint(e);
            return;
        }
        _gdiFallbackFrameCount++;
        e.Graphics.Clear(BackColor);
        e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.None;
        var normalAlpha = ShowXRay ? 70 : 150;
        var activeWireColor = _overlaySettings.Colors.ActiveWire(ShowXRay);
        using var normalPen = new Pen(
            Color.FromArgb(ShowXRay ? 240 : 225, activeWireColor),
            _overlaySettings.Sizing.WireWidthPixels);
        using var selectedPen = new Pen(GdiSelectionColor(_overlaySettings, live: false, 245), 1.6f);
        using var liveSelectionPen = new Pen(GdiSelectionColor(_overlaySettings, live: true, 245), 1.6f);
        using var normalBrush = new SolidBrush(Color.FromArgb(normalAlpha, 79, 112, 152));
        using var selectedBrush = new SolidBrush(GdiSelectionColor(_overlaySettings, live: false, 190));
        using var liveSelectionBrush = new SolidBrush(GdiSelectionColor(_overlaySettings, live: true, 170));
        var points = new PointF[3];
        var camera = CurrentCamera();

        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount; submeshIndex++)
        {
            var submesh = _document.Submeshes[submeshIndex];
            var partSelected = IsPartSelected(submeshIndex);
            var pen = partSelected ? selectedPen : normalPen;
            var brush = partSelected ? selectedBrush : normalBrush;
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                var face = submesh.Faces[faceIndex];
                if (face.Corners.Length != 3)
                {
                    continue;
                }
                var valid = true;
                for (var i = 0; i < 3; i++)
                {
                    var vertexIndex = face.Corners[i].VertexIndex;
                    if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
                    {
                        valid = false;
                        break;
                    }
                    points[i] = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
                }
                if (valid)
                {
                    var faceSelected = IsFaceSelected(submeshIndex, faceIndex);
                    var faceLive = _provisionalSelectedFaces.TryGetValue(submeshIndex, out var liveFaces)
                        && liveFaces.Contains(faceIndex);
                    var faceBrush = faceLive ? liveSelectionBrush : faceSelected ? selectedBrush : brush;
                    var facePen = faceLive ? liveSelectionPen : faceSelected ? selectedPen : pen;
                    var textured = ShowSolid && !faceSelected && !faceLive
                        && TryDrawTexturedFace(e.Graphics, submeshIndex, submesh, face, points);
                    if ((ShowSolid || faceSelected || faceLive) && !textured)
                    {
                        e.Graphics.FillPolygon(faceBrush, points);
                    }
                    if (ShowWire || ShowXRay || faceSelected || faceLive)
                    {
                        e.Graphics.DrawPolygon(facePen, points);
                    }
                }
            }
        }

        DrawSelectedEdges(e.Graphics, camera);
        DrawSelectedVertices(e.Graphics, camera);
        DrawProvisionalVertices(e.Graphics, camera);
        DrawEdgeSelectionRectangle(e.Graphics);
        if (_pointerInside && ActiveTool is "grab" or "smooth" or "inflate" or "pinch")
        {
            var radius = (float)NumberOption(ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>(), "radius", 24.0);
            using var brushPen = new Pen(Color.FromArgb(245, 255, 224, 92), 1.5f);
            e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            e.Graphics.DrawEllipse(brushPen, _pointerLocation.X - radius, _pointerLocation.Y - radius, radius * 2, radius * 2);
        }

        var frameTicks = _clock.ElapsedTicks - started;
        RecordRenderedFrame(frameTicks * 1000.0 / Stopwatch.Frequency, 0.0, string.Empty);
        base.OnPaint(e);
    }

    private bool TryDrawTexturedFace(Graphics graphics, int submeshIndex, ObjSubmesh submesh, ObjFace face, PointF[] destination)
    {
        var texturePath = _materials.BaseTexturePathForSubmesh(submeshIndex);
        var bitmap = _textureSet.BitmapForPath(texturePath);
        if (bitmap is null || face.Corners.Length != 3)
        {
            return false;
        }
        var source = new PointF[3];
        for (var i = 0; i < 3; i++)
        {
            var uvIndex = face.Corners[i].UvIndex;
            if (uvIndex < 0 || uvIndex >= submesh.Uvs.Count)
            {
                return false;
            }
            var uv = submesh.Uvs[uvIndex];
            source[i] = new PointF(uv.U * bitmap.Width, (1.0f - uv.V) * bitmap.Height);
        }
        return DrawAffineTexturedTriangle(graphics, bitmap, source, destination);
    }

    private static bool DrawAffineTexturedTriangle(Graphics graphics, Bitmap bitmap, PointF[] source, PointF[] destination)
    {
        var denominator = source[0].X * (source[1].Y - source[2].Y)
            + source[1].X * (source[2].Y - source[0].Y)
            + source[2].X * (source[0].Y - source[1].Y);
        if (Math.Abs(denominator) < 0.001f)
        {
            return false;
        }
        var m11 = (destination[0].X * (source[1].Y - source[2].Y)
            + destination[1].X * (source[2].Y - source[0].Y)
            + destination[2].X * (source[0].Y - source[1].Y)) / denominator;
        var m12 = (destination[0].Y * (source[1].Y - source[2].Y)
            + destination[1].Y * (source[2].Y - source[0].Y)
            + destination[2].Y * (source[0].Y - source[1].Y)) / denominator;
        var m21 = (destination[0].X * (source[2].X - source[1].X)
            + destination[1].X * (source[0].X - source[2].X)
            + destination[2].X * (source[1].X - source[0].X)) / denominator;
        var m22 = (destination[0].Y * (source[2].X - source[1].X)
            + destination[1].Y * (source[0].X - source[2].X)
            + destination[2].Y * (source[1].X - source[0].X)) / denominator;
        var dx = (destination[0].X * ((source[1].X * source[2].Y) - (source[2].X * source[1].Y))
            + destination[1].X * ((source[2].X * source[0].Y) - (source[0].X * source[2].Y))
            + destination[2].X * ((source[0].X * source[1].Y) - (source[1].X * source[0].Y))) / denominator;
        var dy = (destination[0].Y * ((source[1].X * source[2].Y) - (source[2].X * source[1].Y))
            + destination[1].Y * ((source[2].X * source[0].Y) - (source[0].X * source[2].Y))
            + destination[2].Y * ((source[0].X * source[1].Y) - (source[1].X * source[0].Y))) / denominator;
        var state = graphics.Save();
        try
        {
            using var clipPath = new System.Drawing.Drawing2D.GraphicsPath();
            clipPath.AddPolygon(destination);
            graphics.SetClip(clipPath);
            using var matrix = new System.Drawing.Drawing2D.Matrix(m11, m12, m21, m22, dx, dy);
            graphics.Transform = matrix;
            graphics.DrawImage(bitmap, 0, 0, bitmap.Width, bitmap.Height);
        }
        finally
        {
            graphics.Restore(state);
        }
        return true;
    }

    private bool IsPartSelected(int submeshIndex)
    {
        if (_provisionalPartSelectionActive)
        {
            return _provisionalSelectedSources.Contains(submeshIndex);
        }
        return submeshIndex == SelectedSubmeshIndex || _selectedSources.Contains(submeshIndex);
    }

    private bool IsFaceSelected(int submeshIndex, int faceIndex)
    {
        return _selectedFaces.TryGetValue(submeshIndex, out var faces) && faces.Contains(faceIndex);
    }

    private void DrawEdgeSelectionRectangle(Graphics graphics)
    {
        if (!_edgeDragActive)
        {
            return;
        }
        var rectangle = EdgeDragRectangle();
        using var pen = new Pen(GdiSelectionColor(_overlaySettings, live: true, 190), 1.0f) { DashStyle = System.Drawing.Drawing2D.DashStyle.Dash };
        using var brush = new SolidBrush(GdiSelectionColor(_overlaySettings, live: true, 36));
        graphics.FillRectangle(brush, rectangle);
        graphics.DrawRectangle(pen, rectangle);
    }

    private void DrawSelectedEdges(Graphics graphics, NetViewportCamera camera)
    {
        using var selectedPen = new Pen(GdiSelectionColor(_overlaySettings, live: false, 245), 2.2f);
        using var hoverPen = new Pen(GdiSelectionColor(_overlaySettings, live: true, 245), 2.0f);
        foreach (var edge in _edgeTopology.Edges)
        {
            var selected = _selectedEdges.Contains(edge.Id);
            var hovered = edge.Id == _hoverEdgeId;
            var live = _provisionalSelectedEdges.Contains(edge.Id);
            if (!selected && !hovered && !live)
            {
                continue;
            }
            if (edge.SubmeshIndex < 0 || edge.SubmeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[edge.SubmeshIndex];
            if (edge.VertexA < 0 || edge.VertexA >= submesh.Vertices.Count || edge.VertexB < 0 || edge.VertexB >= submesh.Vertices.Count)
            {
                continue;
            }
            var a = SceneProjectedPoint(camera, edge.SubmeshIndex, submesh.Vertices[edge.VertexA]);
            var b = SceneProjectedPoint(camera, edge.SubmeshIndex, submesh.Vertices[edge.VertexB]);
            graphics.DrawLine(hovered || live ? hoverPen : selectedPen, a, b);
        }
    }

    private void DrawSelectedVertices(Graphics graphics, NetViewportCamera camera)
    {
        using var brush = new SolidBrush(GdiSelectionColor(_overlaySettings, live: false, 235));
        using var pen = new Pen(Color.FromArgb(255, 44, 25, 10), 1.0f);
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount; submeshIndex++)
        {
            var submesh = _document.Submeshes[submeshIndex];
            foreach (var vertexIndex in SelectionVerticesForSubmesh(submeshIndex))
            {
                if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
                {
                    continue;
                }
                var point = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
                var rect = new RectangleF(point.X - 3.0f, point.Y - 3.0f, 6.0f, 6.0f);
                graphics.FillEllipse(brush, rect);
                graphics.DrawEllipse(pen, rect);
            }
        }
    }

    private void DrawProvisionalVertices(Graphics graphics, NetViewportCamera camera)
    {
        using var brush = new SolidBrush(GdiSelectionColor(_overlaySettings, live: true, 220));
        using var pen = new Pen(Color.FromArgb(255, 20, 35, 45), 1.0f);
        foreach (var pair in _provisionalSelectedVertices)
        {
            if (pair.Key < 0 || pair.Key >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[pair.Key];
            foreach (var vertexIndex in pair.Value)
            {
                if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
                {
                    continue;
                }
                var point = SceneProjectedPoint(camera, pair.Key, submesh.Vertices[vertexIndex]);
                var rect = new RectangleF(point.X - 3.0f, point.Y - 3.0f, 6.0f, 6.0f);
                graphics.FillEllipse(brush, rect);
                graphics.DrawEllipse(pen, rect);
            }
        }
    }

    internal static Dictionary<string, object?> GdiSelectionOverlayColorProofPayload(
        MeshOverlaySettings settings)
    {
        var normalized = settings.Normalized();
        using var committedFace = new SolidBrush(GdiSelectionColor(normalized, live: false, 190));
        using var liveFace = new SolidBrush(GdiSelectionColor(normalized, live: true, 170));
        using var committedWire = new Pen(GdiSelectionColor(normalized, live: false, 245), 2.2f);
        using var liveWire = new Pen(GdiSelectionColor(normalized, live: true, 245), 2.0f);
        using var committedVertex = new SolidBrush(GdiSelectionColor(normalized, live: false, 235));
        using var liveVertex = new SolidBrush(GdiSelectionColor(normalized, live: true, 220));
        return new Dictionary<string, object?>
        {
            ["committed_faces"] = SameRgb(committedFace.Color, normalized.Colors.Selection),
            ["committed_wires"] = SameRgb(committedWire.Color, normalized.Colors.Selection),
            ["committed_vertices"] = SameRgb(committedVertex.Color, normalized.Colors.Selection),
            ["live_faces"] = SameRgb(liveFace.Color, normalized.Colors.LiveSelection),
            ["live_wires"] = SameRgb(liveWire.Color, normalized.Colors.LiveSelection),
            ["live_vertices"] = SameRgb(liveVertex.Color, normalized.Colors.LiveSelection),
            ["committed_color"] = MeshOverlayColors.Hex(Color.FromArgb(
                normalized.Colors.Selection.R,
                normalized.Colors.Selection.G,
                normalized.Colors.Selection.B)),
            ["live_color"] = MeshOverlayColors.Hex(Color.FromArgb(
                normalized.Colors.LiveSelection.R,
                normalized.Colors.LiveSelection.G,
                normalized.Colors.LiveSelection.B)),
        };
    }

    private static Color GdiSelectionColor(MeshOverlaySettings settings, bool live, int alpha) =>
        Color.FromArgb(alpha, live ? settings.Colors.LiveSelection : settings.Colors.Selection);

    private static bool SameRgb(Color actual, Color expected) =>
        actual.R == expected.R && actual.G == expected.G && actual.B == expected.B;
}
