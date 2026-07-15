using System.Numerics;
using System.Runtime.InteropServices;
using Vortice.Direct3D;
using Vortice.Direct3D11;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private const int InitialOverlayVertexCapacity = 4096;
    private const float VertexMarkerSizePixels = 7.0f;
    private const float SelectedVertexMarkerRadiusPixels = 7.0f;
    private static readonly Vector4 WireOverlayColor = OverlayColor(255, 112, 32, 210);
    private static readonly Vector4 XRayWireOverlayColor = OverlayColor(255, 112, 32, 230);
    private static readonly Vector4 VertexOverlayColor = OverlayColor(255, 174, 40, 255);
    private static readonly uint OverlayVertexStride = (uint)Marshal.SizeOf<D3D11OverlayVertex>();
    private ID3D11Buffer? _overlayVertexBuffer;
    private int _overlayVertexCapacity;
    private int _overlayVertexWriteOffset;
    private long _overlayVertexBufferCreateCount;
    private long _overlayVertexBufferMapCount;
    private long _overlayVertexBufferNoOverwriteCount;
    private long _overlayVerticesUploaded;

    private void BeginOverlayFrame()
    {
        _overlayVertexWriteOffset = 0;
    }

    private void DisposeOverlayDynamicResources()
    {
        _overlayVertexBuffer?.Dispose();
        _overlayVertexBuffer = null;
        _overlayVertexCapacity = 0;
        _overlayVertexWriteOffset = 0;
    }

    private void EnsureOverlayVertexCapacity(int requiredVertexCount)
    {
        if (_device is null
            || (_overlayVertexBuffer is not null && requiredVertexCount <= _overlayVertexCapacity))
        {
            return;
        }
        var capacity = Math.Max(InitialOverlayVertexCapacity, _overlayVertexCapacity);
        while (capacity < requiredVertexCount)
        {
            capacity = checked(capacity * 2);
        }
        var byteWidth = checked((uint)(capacity * (long)OverlayVertexStride));
        var replacement = _device.CreateBuffer(new BufferDescription(
            byteWidth,
            BindFlags.VertexBuffer,
            ResourceUsage.Dynamic,
            CpuAccessFlags.Write,
            ResourceOptionFlags.None,
            0));
        var previous = _overlayVertexBuffer;
        _overlayVertexBuffer = replacement;
        _overlayVertexCapacity = capacity;
        _overlayVertexWriteOffset = 0;
        _overlayVertexBufferCreateCount++;
        previous?.Dispose();
    }

    private void DrawD3D11Overlay()
    {
        if (_context is null
            || _device is null
            || _overlayInputLayout is null
            || _overlayVertexShader is null
            || _vertexMarkerGeometryShader is null
            || _overlayPixelShader is null
            || _overlayCameraBuffer is null)
        {
            return;
        }
        _context.OMSetBlendState(_overlayBlendState);
        _context.OMSetDepthStencilState(_overlayDepthState);
        _context.IASetInputLayout(_overlayInputLayout);
        _context.VSSetShader(_overlayVertexShader);
        _context.GSSetShader(null);
        _context.PSSetShader(_overlayPixelShader);
        _context.OMSetDepthStencilState(_overlayDepthState);
        DrawSceneGrid();
        if (_overlayShowWire)
        {
            DrawD3D11WireOverlay();
        }
        if (_overlayShowVertices)
        {
            DrawD3D11VertexOverlay();
        }
        if (!_overlayShowXRay)
        {
            DrawSelectedSourcesOverlay();
            DrawSelectedFacesOverlay();
            DrawSelectedEdgesOverlay();
            DrawSelectedVerticesOverlay();
        }

        _context.OMSetDepthStencilState(_overlayNoDepthState);
        if (_overlayShowXRay)
        {
            if (!_overlayShowWire)
            {
                DrawD3D11WireOverlay();
            }
            DrawSelectedSourcesOverlay();
            DrawSelectedFacesOverlay();
            DrawSelectedEdgesOverlay();
            DrawSelectedVerticesOverlay();
        }
        if (ActivePaneInteractionAllowed)
        {
            DrawSelectionRectangleOverlay();
            DrawBrushCursorOverlay();
        }
        if (_overlayShowXRay)
        {
            DrawXRayOverlayMarker();
        }

        _context.OMSetDepthStencilState(_gizmoDepthState);
        DrawSceneGizmo();
        _context.OMSetBlendState(_blendState);
        _context.OMSetDepthStencilState(_depthState);
    }

    private void DrawSceneGrid()
    {
        if (ActivePaneGridVisible)
        {
            var minor = new List<Vector3>();
            var major = new List<Vector3>();
            var spacing = Math.Max(0.0001f, _scene.GridSpacing);
            const int halfLines = 10;
            for (var line = -halfLines; line <= halfLines; line++)
            {
                var target = line % 5 == 0 ? major : minor;
                var offset = line * spacing;
                target.Add(_scene.GridOrigin + new Vector3(-halfLines * spacing, 0, offset));
                target.Add(_scene.GridOrigin + new Vector3(halfLines * spacing, 0, offset));
                target.Add(_scene.GridOrigin + new Vector3(offset, 0, -halfLines * spacing));
                target.Add(_scene.GridOrigin + new Vector3(offset, 0, halfLines * spacing));
            }
            DrawOverlayPrimitive(PrimitiveTopology.LineList, minor, OverlayColor(90, 105, 120, 75), _camera.WorldViewProjection);
            DrawOverlayPrimitive(PrimitiveTopology.LineList, major, OverlayColor(125, 140, 155, 115), _camera.WorldViewProjection);
        }
        if (_scene.ComparisonMode == "overlay")
        {
            var referenceLines = new List<Vector3>();
            for (var submeshIndex = _scene.EditableSubmeshCount; submeshIndex < _scene.EditableSubmeshCount + _scene.ReferenceSubmeshCount; submeshIndex++)
            {
                if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count) continue;
                var ignoredTriangles = new List<Vector3>();
                AddSubmeshFaceVertices(submeshIndex, ignoredTriangles, referenceLines);
            }
            DrawOverlayPrimitive(PrimitiveTopology.LineList, referenceLines, OverlayColor(90, 205, 255, 190), _camera.WorldViewProjection);
        }
    }

    private void DrawSceneGizmo()
    {
        if (!ActivePaneGizmoVisible || _scene.EditableSubmeshCount <= 0) return;
        var origin = string.Equals(_activeRenderPane?.Role, "editable", StringComparison.OrdinalIgnoreCase)
            ? _scene.RoleViewGizmoPivot()
            : _scene.EffectiveGizmoPivot();
        var length = Math.Max(_scene.SceneExtent * 0.18f, _scene.GridSpacing * 2.0f);
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
            DrawOverlayPrimitive(
                PrimitiveTopology.LineList,
                new List<Vector3>
                {
                    origin - new Vector3(size, 0, 0), origin + new Vector3(size, 0, 0),
                    origin - new Vector3(0, size, 0), origin + new Vector3(0, size, 0),
                    origin - new Vector3(0, 0, size), origin + new Vector3(0, 0, size),
                },
                OverlayColor(240, 240, 240, 245),
                _camera.WorldViewProjection);
        }
    }

    private Vector4 GizmoAxisColor(string handle)
    {
        if (string.Equals(_scene.ActiveGizmoHandle, handle, StringComparison.Ordinal)
            || string.Equals(_scene.HoveredGizmoHandle, handle, StringComparison.Ordinal))
        {
            return OverlayColor(255, 225, 95, 255);
        }
        return handle switch
        {
            "x" => OverlayColor(235, 75, 75, 255),
            "y" => OverlayColor(80, 220, 105, 255),
            _ => OverlayColor(75, 145, 255, 255),
        };
    }

    private void DrawGizmoAxis(Vector3 origin, Vector3 axis, string label, Vector4 color)
    {
        var lines = new List<Vector3> { origin, origin + axis };
        if (_scene.GizmoTool == "scale")
        {
            var tip = origin + axis;
            var size = Math.Max(axis.Length() * 0.08f, 0.001f);
            lines.Add(tip - new Vector3(size, 0, 0)); lines.Add(tip + new Vector3(size, 0, 0));
            lines.Add(tip - new Vector3(0, size, 0)); lines.Add(tip + new Vector3(0, size, 0));
            lines.Add(tip - new Vector3(0, 0, size)); lines.Add(tip + new Vector3(0, 0, size));
        }
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, color, _camera.WorldViewProjection);
        DrawGizmoHandleMarker(origin + axis, label, color);
    }

    private void DrawGizmoPlane(Vector3 origin, float length, Vector3 firstAxis, Vector3 secondAxis, Vector4 color)
    {
        var a = origin + (firstAxis * length * 0.22f);
        var b = origin + (firstAxis * length * 0.42f);
        var c = origin + (secondAxis * length * 0.42f);
        var d = origin + (secondAxis * length * 0.22f);
        DrawOverlayPrimitive(
            PrimitiveTopology.LineList,
            new List<Vector3> { a, b, b, c, c, d, d, a },
            color,
            _camera.WorldViewProjection);
    }

    private void DrawGizmoCircle(Vector3 origin, float radius, int normalAxis, string label, Vector4 color)
    {
        const int segments = 48;
        var lines = new List<Vector3>(segments * 2);
        for (var index = 0; index < segments; index++)
        {
            var a = index * MathF.Tau / segments;
            var b = (index + 1) * MathF.Tau / segments;
            Vector3 Point(float angle) => normalAxis switch
            {
                0 => origin + new Vector3(0, MathF.Cos(angle) * radius, MathF.Sin(angle) * radius),
                1 => origin + new Vector3(MathF.Cos(angle) * radius, 0, MathF.Sin(angle) * radius),
                _ => origin + new Vector3(MathF.Cos(angle) * radius, MathF.Sin(angle) * radius, 0),
            };
            lines.Add(Point(a)); lines.Add(Point(b));
        }
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, color, _camera.WorldViewProjection);
        var markerAngle = normalAxis == 1 ? MathF.PI * 0.5f : 0.0f;
        Vector3 MarkerPoint(float angle) => normalAxis switch
        {
            0 => origin + new Vector3(0, MathF.Cos(angle) * radius, MathF.Sin(angle) * radius),
            1 => origin + new Vector3(MathF.Cos(angle) * radius, 0, MathF.Sin(angle) * radius),
            _ => origin + new Vector3(MathF.Cos(angle) * radius, MathF.Sin(angle) * radius, 0),
        };
        DrawGizmoHandleMarker(MarkerPoint(markerAngle), label, color);
    }

    private void DrawGizmoHandleMarker(Vector3 worldPoint, string label, Vector4 color)
    {
        var point = _camera.Project(new Vec3(worldPoint.X, worldPoint.Y, worldPoint.Z));
        var marker = new List<Vector3>();
        AddScreenQuad(point.X - 4.0f, point.Y - 4.0f, point.X + 4.0f, point.Y + 4.0f, marker);
        DrawOverlayPrimitive(PrimitiveTopology.TriangleList, marker, color, Matrix4x4.Identity);

        var left = point.X + 8.0f;
        var top = point.Y - 6.0f;
        const float width = 7.0f;
        const float height = 12.0f;
        var glyph = new List<Vector3>();
        switch ((label ?? string.Empty).Trim().ToUpperInvariant())
        {
            case "X":
                AddScreenLine(left, top, left + width, top + height, glyph);
                AddScreenLine(left + width, top, left, top + height, glyph);
                break;
            case "Y":
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
            OverlayColor(245, 248, 252, 255),
            Matrix4x4.Identity);
    }

    private void DrawD3D11WireOverlay()
    {
        var lines = new List<Vector3>();
        foreach (var edge in _overlayTopology.Edges)
        {
            if (edge.SubmeshIndex < 0
                || edge.SubmeshIndex >= _document.Submeshes.Count
                || !ActivePaneIncludes(edge.SubmeshIndex)
                || _materials.ParametersForSubmesh(edge.SubmeshIndex).Visible is false)
            {
                continue;
            }
            AddEdgeLineVertices(edge, lines);
        }
        DrawOverlayPrimitive(
            PrimitiveTopology.LineList,
            lines,
            _overlayShowXRay ? XRayWireOverlayColor : WireOverlayColor,
            _camera.WorldViewProjection);
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
            Color = VertexOverlayColor,
            MarkerSettings = new Vector4(
                Math.Max(1.0f, _camera.ViewportWidth),
                Math.Max(1.0f, _camera.ViewportHeight),
                VertexMarkerSizePixels,
                0.0f),
        };
        _context.UpdateSubresource(in constants, _overlayCameraBuffer);
        _context.VSSetConstantBuffer(1u, _overlayCameraBuffer);
        _context.GSSetConstantBuffer(1u, _overlayCameraBuffer);
        _context.PSSetConstantBuffer(1u, _overlayCameraBuffer);
        _context.GSSetShader(_vertexMarkerGeometryShader);
        _context.IASetPrimitiveTopology(PrimitiveTopology.PointList);
        foreach (var batch in _batches)
        {
            if (!ActivePaneIncludes(batch.SubmeshIndex) || _materials.ParametersForSubmesh(batch.SubmeshIndex).Visible is false)
            {
                continue;
            }
            constants.WorldViewProjection = ActivePaneModelMatrix(batch.SubmeshIndex) * _camera.WorldViewProjection;
            _context.UpdateSubresource(in constants, _overlayCameraBuffer);
            _context.IASetVertexBuffer(0u, batch.VertexBuffer, D3D11SubmeshBatch.VertexStride);
            _context.IASetIndexBuffer(batch.IndexBuffer, Vortice.DXGI.Format.R32_UInt, 0);
            _context.DrawIndexed((uint)batch.IndexCount, 0, 0);
            _vertexOverlayBatchDrawCount++;
        }
        _context.GSSetShader(null);
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
            if (!ActivePaneIncludes(submeshIndex) || _materials.ParametersForSubmesh(submeshIndex).Visible is false)
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
            if (!ActivePaneIncludes(pair.Key) || _materials.ParametersForSubmesh(pair.Key).Visible is false)
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
                AddFaceVertices(pair.Key, submesh, submesh.Faces[faceIndex], triangles, lines);
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
            if (edge.SubmeshIndex < 0
                || edge.SubmeshIndex >= _document.Submeshes.Count
                || !ActivePaneIncludes(edge.SubmeshIndex)
                || _materials.ParametersForSubmesh(edge.SubmeshIndex).Visible is false)
            {
                continue;
            }
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
            if (!ActivePaneIncludes(pair.Key) || _materials.ParametersForSubmesh(pair.Key).Visible is false)
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
                var transformed = Vector3.Transform(new Vector3(submesh.Vertices[vertexIndex].X, submesh.Vertices[vertexIndex].Y, submesh.Vertices[vertexIndex].Z), ActivePaneModelMatrix(pair.Key));
                AddScreenCross(
                    _camera.Project(new Vec3(transformed.X, transformed.Y, transformed.Z)),
                    SelectedVertexMarkerRadiusPixels,
                    lines);
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

    private void DrawBrushCursorOverlay()
    {
        if (!_overlayBrushCursor.HasValue)
        {
            return;
        }
        const int segments = 48;
        var center = _overlayBrushCursor.Value;
        var lines = new List<Vector3>(segments * 2);
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

    private void AddSubmeshFaceVertices(int submeshIndex, List<Vector3> triangles, List<Vector3> lines)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return;
        }
        var submesh = _document.Submeshes[submeshIndex];
        foreach (var face in submesh.Faces)
        {
            AddFaceVertices(submeshIndex, submesh, face, triangles, lines);
        }
    }

    private void AddFaceVertices(int submeshIndex, ObjSubmesh submesh, ObjFace face, List<Vector3> triangles, List<Vector3> lines)
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
            vertices[index] = Vector3.Transform(new Vector3(vertex.X, vertex.Y, vertex.Z), ActivePaneModelMatrix(submeshIndex));
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
        var model = ActivePaneModelMatrix(edge.SubmeshIndex);
        lines.Add(Vector3.Transform(new Vector3(a.X, a.Y, a.Z), model));
        lines.Add(Vector3.Transform(new Vector3(b.X, b.Y, b.Z), model));
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
        EnsureOverlayVertexCapacity(checked(_overlayVertexWriteOffset + positions.Count));
        var vertexBuffer = _overlayVertexBuffer;
        if (vertexBuffer is null)
        {
            return;
        }
        var startVertex = _overlayVertexWriteOffset;
        var mapMode = startVertex == 0 ? MapMode.WriteDiscard : MapMode.WriteNoOverwrite;
        var mapped = _context.Map(vertexBuffer, mapMode, MapFlags.None);
        try
        {
            var destination = (D3D11OverlayVertex*)mapped.DataPointer + startVertex;
            for (var index = 0; index < positions.Count; index++)
            {
                destination[index] = new D3D11OverlayVertex(positions[index]);
            }
        }
        finally
        {
            _context.Unmap(vertexBuffer, 0);
        }
        _overlayVertexWriteOffset = checked(startVertex + positions.Count);
        _overlayVertexBufferMapCount++;
        if (mapMode == MapMode.WriteNoOverwrite)
        {
            _overlayVertexBufferNoOverwriteCount++;
        }
        _overlayVerticesUploaded += positions.Count;
        var constants = new D3D11OverlayConstants
        {
            WorldViewProjection = worldViewProjection,
            Color = color,
        };
        _context.UpdateSubresource(in constants, _overlayCameraBuffer);
        _context.VSSetConstantBuffer(1u, _overlayCameraBuffer);
        _context.PSSetConstantBuffer(1u, _overlayCameraBuffer);
        _context.IASetPrimitiveTopology(topology);
        _context.IASetVertexBuffer(0u, vertexBuffer, OverlayVertexStride);
        _context.Draw((uint)positions.Count, (uint)startVertex);
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
    public Vector4 MarkerSettings;
}
