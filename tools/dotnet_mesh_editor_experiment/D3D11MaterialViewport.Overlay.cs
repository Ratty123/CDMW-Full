using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private void DrawD3D11Overlay(Graphics graphics)
    {
        graphics.SmoothingMode = SmoothingMode.AntiAlias;
        graphics.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
        if (_overlayShowWire || _overlayShowXRay)
        {
            DrawD3D11WireOverlay(graphics);
        }
        DrawSelectedSourcesOverlay(graphics);
        DrawSelectedFacesOverlay(graphics);
        DrawSelectedEdgesOverlay(graphics);
        DrawSelectedVerticesOverlay(graphics);
        DrawSelectionRectangleOverlay(graphics);
        if (_overlayShowXRay)
        {
            DrawXRayOverlayLabel(graphics);
        }
    }

    private void DrawD3D11WireOverlay(Graphics graphics)
    {
        var alpha = _overlayShowXRay ? 125 : 95;
        using var wirePen = new Pen(System.Drawing.Color.FromArgb(alpha, 120, 170, 220), _overlayShowXRay ? 0.9f : 0.75f);
        foreach (var edge in _overlayTopology.Edges)
        {
            if (!TryProjectOverlayEdge(edge, out var a, out var b))
            {
                continue;
            }
            graphics.DrawLine(wirePen, a, b);
        }
    }

    private void DrawSelectedSourcesOverlay(Graphics graphics)
    {
        using var sourceFill = new SolidBrush(System.Drawing.Color.FromArgb(_overlayShowXRay ? 64 : 42, 70, 155, 255));
        using var sourcePen = new Pen(System.Drawing.Color.FromArgb(_overlayShowXRay ? 230 : 185, 70, 155, 255), 1.5f);
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            if (!_overlaySelectedSources.Contains(submeshIndex) && submeshIndex != _overlaySelectedSubmeshIndex)
            {
                continue;
            }
            DrawSubmeshFacesOverlay(graphics, submeshIndex, sourceFill, sourcePen);
        }
    }

    private void DrawSelectedFacesOverlay(Graphics graphics)
    {
        using var faceFill = new SolidBrush(System.Drawing.Color.FromArgb(_overlayShowXRay ? 88 : 58, 255, 224, 92));
        using var facePen = new Pen(System.Drawing.Color.FromArgb(235, 255, 224, 92), 1.8f);
        foreach (var pair in _overlaySelectedFaces)
        {
            if (pair.Key < 0 || pair.Key >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[pair.Key];
            foreach (var faceIndex in pair.Value)
            {
                if (faceIndex < 0 || faceIndex >= submesh.Faces.Count)
                {
                    continue;
                }
                if (TryProjectOverlayFace(submesh, submesh.Faces[faceIndex], out var points))
                {
                    graphics.FillPolygon(faceFill, points);
                    graphics.DrawPolygon(facePen, points);
                }
            }
        }
    }

    private void DrawSelectedEdgesOverlay(Graphics graphics)
    {
        using var selectedPen = new Pen(System.Drawing.Color.FromArgb(245, 226, 196, 72), 2.0f);
        using var hoverPen = new Pen(System.Drawing.Color.FromArgb(245, 96, 202, 255), 2.2f);
        foreach (var edge in _overlayTopology.Edges)
        {
            var selected = _overlaySelectedEdges.Contains(edge.Id);
            var hovered = edge.Id == _overlayHoverEdgeId;
            if (!selected && !hovered)
            {
                continue;
            }
            if (!TryProjectOverlayEdge(edge, out var a, out var b))
            {
                continue;
            }
            graphics.DrawLine(hovered ? hoverPen : selectedPen, a, b);
        }
    }

    private void DrawSelectedVerticesOverlay(Graphics graphics)
    {
        using var vertexBrush = new SolidBrush(System.Drawing.Color.FromArgb(235, 255, 230, 88));
        using var vertexPen = new Pen(System.Drawing.Color.FromArgb(245, 42, 26, 8), 1.0f);
        foreach (var pair in _overlaySelectedVertices)
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
                var point = ProjectOverlayVertex(submesh.Vertices[vertexIndex]);
                var rect = new RectangleF(point.X - 3.5f, point.Y - 3.5f, 7.0f, 7.0f);
                graphics.FillEllipse(vertexBrush, rect);
                graphics.DrawEllipse(vertexPen, rect);
            }
        }
    }

    private void DrawSelectionRectangleOverlay(Graphics graphics)
    {
        if (!_overlaySelectionRectangle.HasValue)
        {
            return;
        }
        using var rectanglePen = new Pen(System.Drawing.Color.FromArgb(210, 96, 202, 255), 1.0f) { DashStyle = DashStyle.Dash };
        using var rectangleBrush = new SolidBrush(System.Drawing.Color.FromArgb(36, 96, 202, 255));
        graphics.FillRectangle(rectangleBrush, _overlaySelectionRectangle.Value);
        graphics.DrawRectangle(rectanglePen, _overlaySelectionRectangle.Value);
    }

    private void DrawXRayOverlayLabel(Graphics graphics)
    {
        using var font = new Font(FontFamily.GenericSansSerif, 8.0f, FontStyle.Bold);
        using var brush = new SolidBrush(System.Drawing.Color.FromArgb(235, 165, 215, 255));
        graphics.DrawString("X-Ray", font, brush, new PointF(8.0f, 8.0f));
    }

    private void DrawSubmeshFacesOverlay(Graphics graphics, int submeshIndex, Brush fill, Pen outline)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return;
        }
        var submesh = _document.Submeshes[submeshIndex];
        foreach (var face in submesh.Faces)
        {
            if (TryProjectOverlayFace(submesh, face, out var points))
            {
                graphics.FillPolygon(fill, points);
                graphics.DrawPolygon(outline, points);
            }
        }
    }

    private bool TryProjectOverlayEdge(NetEdge edge, out PointF a, out PointF b)
    {
        a = default;
        b = default;
        if (edge.SubmeshIndex < 0 || edge.SubmeshIndex >= _document.Submeshes.Count)
        {
            return false;
        }
        var submesh = _document.Submeshes[edge.SubmeshIndex];
        if (edge.VertexA < 0 || edge.VertexA >= submesh.Vertices.Count || edge.VertexB < 0 || edge.VertexB >= submesh.Vertices.Count)
        {
            return false;
        }
        a = ProjectOverlayVertex(submesh.Vertices[edge.VertexA]);
        b = ProjectOverlayVertex(submesh.Vertices[edge.VertexB]);
        return true;
    }

    private bool TryProjectOverlayFace(ObjSubmesh submesh, ObjFace face, out PointF[] points)
    {
        points = Array.Empty<PointF>();
        if (face.Corners.Length != 3)
        {
            return false;
        }
        var projected = new PointF[3];
        for (var index = 0; index < 3; index++)
        {
            var vertexIndex = face.Corners[index].VertexIndex;
            if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
            {
                return false;
            }
            projected[index] = ProjectOverlayVertex(submesh.Vertices[vertexIndex]);
        }
        points = projected;
        return true;
    }

    private PointF ProjectOverlayVertex(Vec3 vertex)
    {
        var matrices = BuildCameraMatrices();
        var clip = Vector4.Transform(new Vector4(vertex.X, vertex.Y, vertex.Z, 1.0f), matrices.WorldViewProjection);
        if (Math.Abs(clip.W) > 0.000001f)
        {
            clip /= clip.W;
        }
        var width = Math.Max(1.0f, _renderWidth > 0 ? _renderWidth : Width);
        var height = Math.Max(1.0f, _renderHeight > 0 ? _renderHeight : Height);
        return new PointF((clip.X * 0.5f + 0.5f) * width, (0.5f - clip.Y * 0.5f) * height);
    }
}
