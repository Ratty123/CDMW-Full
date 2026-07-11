using System.Numerics;
using System.Runtime.InteropServices;
using Vortice.Direct3D;
using Vortice.Direct3D11;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private void DrawD3D11Overlay()
    {
        if (_context is null
            || _device is null
            || _overlayInputLayout is null
            || _overlayVertexShader is null
            || _overlayPixelShader is null
            || _overlayCameraBuffer is null)
        {
            return;
        }
        _context.OMSetBlendState(_overlayBlendState);
        _context.OMSetDepthStencilState(_overlayDepthState);
        _context.IASetInputLayout(_overlayInputLayout);
        _context.VSSetShader(_overlayVertexShader);
        _context.PSSetShader(_overlayPixelShader);
        if (_overlayShowWire || _overlayShowXRay)
        {
            DrawD3D11WireOverlay();
        }
        if (_overlayShowVertices)
        {
            DrawD3D11VertexOverlay();
        }
        DrawSelectedSourcesOverlay();
        DrawSelectedFacesOverlay();
        DrawSelectedEdgesOverlay();
        DrawSelectedVerticesOverlay();
        DrawSelectionRectangleOverlay();
        if (_overlayShowXRay)
        {
            DrawXRayOverlayMarker();
        }
        _context.OMSetBlendState(_blendState);
        _context.OMSetDepthStencilState(_depthState);
    }

    private void DrawD3D11WireOverlay()
    {
        var lines = new List<Vector3>();
        foreach (var edge in _overlayTopology.Edges)
        {
            AddEdgeLineVertices(edge, lines);
        }
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, OverlayColor(120, 170, 220, _overlayShowXRay ? 125 : 95), _camera.WorldViewProjection);
        if (lines.Count > 0)
        {
            _wireOverlayDrawCount++;
        }
    }

    private void DrawD3D11VertexOverlay()
    {
        if (_context is null || _overlayCameraBuffer is null)
        {
            return;
        }
        var constants = new D3D11OverlayConstants
        {
            WorldViewProjection = _camera.WorldViewProjection,
            Color = OverlayColor(110, 215, 255, 235),
        };
        _context.UpdateSubresource(in constants, _overlayCameraBuffer);
        _context.VSSetConstantBuffer(1u, _overlayCameraBuffer);
        _context.PSSetConstantBuffer(1u, _overlayCameraBuffer);
        _context.IASetPrimitiveTopology(PrimitiveTopology.PointList);
        foreach (var batch in _batches)
        {
            if (_materials.ParametersForSubmesh(batch.SubmeshIndex).Visible is false)
            {
                continue;
            }
            _context.IASetVertexBuffer(0u, batch.VertexBuffer, D3D11SubmeshBatch.VertexStride);
            _context.IASetIndexBuffer(batch.IndexBuffer, Vortice.DXGI.Format.R32_UInt, 0);
            _context.DrawIndexed((uint)batch.IndexCount, 0, 0);
            _vertexOverlayBatchDrawCount++;
        }
    }

    private void DrawSelectedSourcesOverlay()
    {
        var triangles = new List<Vector3>();
        var lines = new List<Vector3>();
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            if (!_overlaySelectedSources.Contains(submeshIndex) && submeshIndex != _overlaySelectedSubmeshIndex)
            {
                continue;
            }
            AddSubmeshFaceVertices(submeshIndex, triangles, lines);
        }
        DrawOverlayPrimitive(PrimitiveTopology.TriangleList, triangles, OverlayColor(70, 155, 255, _overlayShowXRay ? 64 : 42), _camera.WorldViewProjection);
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, OverlayColor(70, 155, 255, _overlayShowXRay ? 230 : 185), _camera.WorldViewProjection);
    }

    private void DrawSelectedFacesOverlay()
    {
        var triangles = new List<Vector3>();
        var lines = new List<Vector3>();
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
                AddFaceVertices(submesh, submesh.Faces[faceIndex], triangles, lines);
            }
        }
        DrawOverlayPrimitive(PrimitiveTopology.TriangleList, triangles, OverlayColor(255, 224, 92, _overlayShowXRay ? 88 : 58), _camera.WorldViewProjection);
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, OverlayColor(255, 224, 92, 235), _camera.WorldViewProjection);
    }

    private void DrawSelectedEdgesOverlay()
    {
        var selected = new List<Vector3>();
        var hovered = new List<Vector3>();
        foreach (var edge in _overlayTopology.Edges)
        {
            if (edge.Id == _overlayHoverEdgeId)
            {
                AddEdgeLineVertices(edge, hovered);
            }
            else if (_overlaySelectedEdges.Contains(edge.Id))
            {
                AddEdgeLineVertices(edge, selected);
            }
        }
        DrawOverlayPrimitive(PrimitiveTopology.LineList, selected, OverlayColor(226, 196, 72, 245), _camera.WorldViewProjection);
        DrawOverlayPrimitive(PrimitiveTopology.LineList, hovered, OverlayColor(96, 202, 255, 245), _camera.WorldViewProjection);
    }

    private void DrawSelectedVerticesOverlay()
    {
        var lines = new List<Vector3>();
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
                AddScreenCross(_camera.Project(submesh.Vertices[vertexIndex]), 4.0f, lines);
            }
        }
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, OverlayColor(255, 230, 88, 245), Matrix4x4.Identity);
    }

    private void DrawSelectionRectangleOverlay()
    {
        if (!_overlaySelectionRectangle.HasValue)
        {
            return;
        }
        var rect = _overlaySelectionRectangle.Value;
        var triangles = new List<Vector3>();
        AddScreenQuad(rect.Left, rect.Top, rect.Right, rect.Bottom, triangles);
        DrawOverlayPrimitive(PrimitiveTopology.TriangleList, triangles, OverlayColor(96, 202, 255, 36), Matrix4x4.Identity);
        var lines = new List<Vector3>();
        AddScreenRectangle(rect.Left, rect.Top, rect.Right, rect.Bottom, lines);
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, OverlayColor(96, 202, 255, 210), Matrix4x4.Identity);
    }

    private void DrawXRayOverlayMarker()
    {
        var lines = new List<Vector3>();
        AddScreenLine(8.0f, 8.0f, 32.0f, 24.0f, lines);
        AddScreenLine(32.0f, 8.0f, 8.0f, 24.0f, lines);
        AddScreenLine(40.0f, 8.0f, 58.0f, 24.0f, lines);
        AddScreenLine(58.0f, 8.0f, 40.0f, 24.0f, lines);
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, OverlayColor(165, 215, 255, 235), Matrix4x4.Identity);
    }

    private void AddSubmeshFaceVertices(int submeshIndex, List<Vector3> triangles, List<Vector3> lines)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return;
        }
        var submesh = _document.Submeshes[submeshIndex];
        foreach (var face in submesh.Faces)
        {
            AddFaceVertices(submesh, face, triangles, lines);
        }
    }

    private static void AddFaceVertices(ObjSubmesh submesh, ObjFace face, List<Vector3> triangles, List<Vector3> lines)
    {
        if (face.Corners.Length != 3)
        {
            return;
        }
        var vertices = new Vector3[3];
        for (var index = 0; index < 3; index++)
        {
            var vertexIndex = face.Corners[index].VertexIndex;
            if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
            {
                return;
            }
            var vertex = submesh.Vertices[vertexIndex];
            vertices[index] = new Vector3(vertex.X, vertex.Y, vertex.Z);
        }
        triangles.AddRange(vertices);
        lines.Add(vertices[0]);
        lines.Add(vertices[1]);
        lines.Add(vertices[1]);
        lines.Add(vertices[2]);
        lines.Add(vertices[2]);
        lines.Add(vertices[0]);
    }

    private void AddEdgeLineVertices(NetEdge edge, List<Vector3> lines)
    {
        if (edge.SubmeshIndex < 0 || edge.SubmeshIndex >= _document.Submeshes.Count)
        {
            return;
        }
        var submesh = _document.Submeshes[edge.SubmeshIndex];
        if (edge.VertexA < 0 || edge.VertexA >= submesh.Vertices.Count || edge.VertexB < 0 || edge.VertexB >= submesh.Vertices.Count)
        {
            return;
        }
        var a = submesh.Vertices[edge.VertexA];
        var b = submesh.Vertices[edge.VertexB];
        lines.Add(new Vector3(a.X, a.Y, a.Z));
        lines.Add(new Vector3(b.X, b.Y, b.Z));
    }

    private void AddScreenCross(PointF point, float radius, List<Vector3> lines)
    {
        AddScreenLine(point.X - radius, point.Y, point.X + radius, point.Y, lines);
        AddScreenLine(point.X, point.Y - radius, point.X, point.Y + radius, lines);
    }

    private void AddScreenRectangle(float left, float top, float right, float bottom, List<Vector3> lines)
    {
        AddScreenLine(left, top, right, top, lines);
        AddScreenLine(right, top, right, bottom, lines);
        AddScreenLine(right, bottom, left, bottom, lines);
        AddScreenLine(left, bottom, left, top, lines);
    }

    private void AddScreenQuad(float left, float top, float right, float bottom, List<Vector3> triangles)
    {
        var a = ClipFromScreen(left, top);
        var b = ClipFromScreen(right, top);
        var c = ClipFromScreen(right, bottom);
        var d = ClipFromScreen(left, bottom);
        triangles.Add(a);
        triangles.Add(b);
        triangles.Add(c);
        triangles.Add(a);
        triangles.Add(c);
        triangles.Add(d);
    }

    private void AddScreenLine(float x1, float y1, float x2, float y2, List<Vector3> lines)
    {
        lines.Add(ClipFromScreen(x1, y1));
        lines.Add(ClipFromScreen(x2, y2));
    }

    private Vector3 ClipFromScreen(float x, float y)
    {
        var width = Math.Max(1.0f, _camera.ViewportWidth);
        var height = Math.Max(1.0f, _camera.ViewportHeight);
        return new Vector3((2.0f * x / width) - 1.0f, 1.0f - (2.0f * y / height), 0.0f);
    }

    private unsafe void DrawOverlayPrimitive(PrimitiveTopology topology, IReadOnlyList<Vector3> positions, Vector4 color, Matrix4x4 worldViewProjection)
    {
        if (positions.Count == 0 || _device is null || _context is null || _overlayCameraBuffer is null)
        {
            return;
        }
        var vertices = positions.Select(position => new D3D11OverlayVertex(position)).ToArray();
        fixed (D3D11OverlayVertex* vertexPtr = vertices)
        {
            using var vertexBuffer = _device.CreateBuffer(
                new BufferDescription((uint)(vertices.Length * Marshal.SizeOf<D3D11OverlayVertex>()), BindFlags.VertexBuffer),
                new SubresourceData((IntPtr)vertexPtr));
            var constants = new D3D11OverlayConstants
            {
                WorldViewProjection = worldViewProjection,
                Color = color,
            };
            _context.UpdateSubresource(in constants, _overlayCameraBuffer);
            _context.VSSetConstantBuffer(1u, _overlayCameraBuffer);
            _context.PSSetConstantBuffer(1u, _overlayCameraBuffer);
            _context.IASetPrimitiveTopology(topology);
            _context.IASetVertexBuffer(0u, vertexBuffer, (uint)Marshal.SizeOf<D3D11OverlayVertex>());
            _context.Draw((uint)vertices.Length, 0);
        }
    }

    private static Vector4 OverlayColor(int red, int green, int blue, int alpha)
    {
        const float scale = 1.0f / 255.0f;
        return new Vector4(
            Math.Clamp(red, 0, 255) * scale,
            Math.Clamp(green, 0, 255) * scale,
            Math.Clamp(blue, 0, 255) * scale,
            Math.Clamp(alpha, 0, 255) * scale);
    }
}

[StructLayout(LayoutKind.Sequential)]
internal readonly record struct D3D11OverlayVertex(Vector3 Position);

[StructLayout(LayoutKind.Sequential)]
internal struct D3D11OverlayConstants
{
    public Matrix4x4 WorldViewProjection;
    public Vector4 Color;
}
