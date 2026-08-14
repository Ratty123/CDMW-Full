using System.Numerics;
using System.Runtime.InteropServices;
using Vortice.Direct3D;
using Vortice.Direct3D11;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private const int InitialOverlayVertexCapacity = 4096;
    private const float SelectedVertexMarkerRadiusPixels = 7.0f;
    private MeshOverlaySettings _overlaySettings = MeshOverlaySettings.Default;
    private Vector4 _wireOverlayColor = OverlayColor(0, 0, 0, 225);
    private Vector4 _vertexOverlayColor = OverlayColor(255, 174, 40, 255);
    private Vector4 _selectionOverlayColor = OverlayColor(255, 224, 92, 245);
    private Vector4 _liveSelectionOverlayColor = OverlayColor(96, 202, 255, 245);
    // Derived from the overlay settings rather than fixed, so a chosen wire or
    // vertex colour survives X-Ray. MeshOverlayColors decides when the automatic
    // high-contrast colour still applies; this must not make that call again.
    private Vector4 _xrayWireOverlayColor = XRayOverlayColor(
        MeshOverlaySettings.Default.Colors.ActiveWire(true),
        240);
    private Vector4 _xrayVertexOverlayColor = XRayOverlayColor(
        MeshOverlaySettings.Default.Colors.ActiveVertex(true),
        255);

    private static Vector4 XRayOverlayColor(System.Drawing.Color color, int alpha) =>
        OverlayColor(color.R, color.G, color.B, alpha);
    private static readonly uint OverlayVertexStride = (uint)Marshal.SizeOf<D3D11OverlayVertex>();
    private ID3D11Buffer? _overlayVertexBuffer;
    private int _overlayVertexCapacity;
    private int _overlayVertexWriteOffset;
    private long _overlayVertexBufferCreateCount;
    private long _overlayVertexBufferMapCount;
    private long _overlayVerticesUploaded;
    private long _overlayBatchFlushCount;
    private long _overlayBatchedDrawCount;
    private long _xRayWireNoDepthDrawCount;
    private long _xRayVertexNoDepthPassCount;
    private long _committedSelectionOverlayPrimitiveCount;
    private long _liveSelectionOverlayPrimitiveCount;
    private System.Drawing.Color _lastCommittedSelectionPrimitiveColor = System.Drawing.Color.Empty;
    private System.Drawing.Color _lastLiveSelectionPrimitiveColor = System.Drawing.Color.Empty;
    private readonly List<Vector3> _overlayScratchA = new(InitialOverlayVertexCapacity);
    private readonly List<Vector3> _overlayScratchB = new(InitialOverlayVertexCapacity);
    private readonly List<Vector3> _overlayFrameVertices = new(InitialOverlayVertexCapacity);
    private readonly List<D3D11OverlayDrawCommand> _overlayDrawCommands = new(64);
    private readonly List<Vector3> _gridMinorVertices = new(80);
    private readonly List<Vector3> _gridMajorVertices = new(24);
    private readonly List<Vector3> _referenceOverlayVertices = new(InitialOverlayVertexCapacity);
    private readonly D3D11WireOverlayCache _comparisonWireOverlayCache = new();
    private readonly D3D11WireOverlayCache _referenceWireOverlayCache = new();
    private readonly D3D11WireOverlayCache _editableWireOverlayCache = new();
    private D3D11FaceOverlayCache _selectedFaceOverlayCache = new();
    private D3D11FaceOverlayCache _provisionalFaceOverlayCache = new();
    private D3D11VertexOverlayCache _selectedVertexOverlayCache = new();
    private D3D11VertexOverlayCache _provisionalVertexOverlayCache = new();
    private Vector3 _cachedGridOrigin;
    private float _cachedGridSpacing;
    private int _cachedGridLineCount;
    private bool _gridGeometryValid;
    private D3D11OverlayGeometryGenerationKey _referenceOverlayGeneration;
    private bool _referenceOverlayValid;
    private long _retainedOverlayCacheHitCount;
    private long _retainedOverlayRebuildCount;
    private long _retainedOverlayBufferCreateCount;
    private long _retainedOverlayBufferDisposeCount;
    private long _retainedWireOverlayBufferCreateCount;
    private long _retainedWireOverlayBufferDisposeCount;
    private long _retainedOverlayBufferMapCount;
    private long _retainedOverlayBufferNoOverwriteMapCount;
    private byte _overlayCommandDepthMode;

    private void BeginOverlayFrame()
    {
        _overlayVertexWriteOffset = 0;
        _overlayFrameVertices.Clear();
        _overlayDrawCommands.Clear();
        _overlayCommandDepthMode = 0;
    }

    public void SetOverlaySettings(MeshOverlaySettings settings)
    {
        _overlaySettings = settings.Normalized();
        var colors = _overlaySettings.Colors;
        _wireOverlayColor = OverlayColor(
            colors.Wire.R,
            colors.Wire.G,
            colors.Wire.B,
            225);
        _vertexOverlayColor = OverlayColor(
            colors.Vertex.R,
            colors.Vertex.G,
            colors.Vertex.B,
            255);
        _xrayWireOverlayColor = XRayOverlayColor(colors.ActiveWire(true), 240);
        _xrayVertexOverlayColor = XRayOverlayColor(colors.ActiveVertex(true), 255);
        _selectionOverlayColor = OverlayColor(
            colors.Selection.R,
            colors.Selection.G,
            colors.Selection.B,
            245);
        _liveSelectionOverlayColor = OverlayColor(
            colors.LiveSelection.R,
            colors.LiveSelection.G,
            colors.LiveSelection.B,
            245);
    }

    private void DisposeOverlayDynamicResources()
    {
        _overlayVertexBuffer?.Dispose();
        _overlayVertexBuffer = null;
        _overlayVertexCapacity = 0;
        _overlayVertexWriteOffset = 0;
        DisposeRetainedWireOverlayBuffers();
        DisposeFaceOverlayCache(_selectedFaceOverlayCache);
        DisposeFaceOverlayCache(_provisionalFaceOverlayCache);
        DisposeVertexOverlayCache(_selectedVertexOverlayCache);
        DisposeVertexOverlayCache(_provisionalVertexOverlayCache);
    }

    private void DisposeRetainedWireOverlayBuffers()
    {
        foreach (var cache in new[]
        {
            _comparisonWireOverlayCache,
            _referenceWireOverlayCache,
            _editableWireOverlayCache,
        })
        {
            if (cache.VertexBuffer is not null)
            {
                cache.VertexBuffer.Dispose();
                cache.VertexBuffer = null;
                _retainedOverlayBufferDisposeCount++;
                _retainedWireOverlayBufferDisposeCount++;
            }
            cache.Valid = false;
        }
    }

    private unsafe ID3D11Buffer? CreateRetainedOverlayBuffer(IReadOnlyList<Vector3> positions)
    {
        if (_device is null || positions.Count == 0)
        {
            return null;
        }
        var vertices = positions.ToArray();
        fixed (Vector3* vertexPointer = vertices)
        {
            var buffer = _device.CreateBuffer(
                new BufferDescription(
                    checked((uint)(vertices.Length * (long)OverlayVertexStride)),
                    BindFlags.VertexBuffer),
                new SubresourceData((IntPtr)vertexPointer));
            _retainedOverlayBufferCreateCount++;
            _retainedWireOverlayBufferCreateCount++;
            return buffer;
        }
    }

    private void DisposeFaceOverlayCache(D3D11FaceOverlayCache cache)
    {
        foreach (var buffer in new[] { cache.TriangleBuffer, cache.LineBuffer })
        {
            if (buffer is not null)
            {
                buffer.Dispose();
                _retainedOverlayBufferDisposeCount++;
            }
        }
        cache.TriangleBuffer = null;
        cache.LineBuffer = null;
        cache.TriangleCapacity = 0;
        cache.LineCapacity = 0;
        cache.Valid = false;
        cache.SelectedFaces.Clear();
        cache.Triangles.Clear();
        cache.Lines.Clear();
    }

    private void DisposeVertexOverlayCache(D3D11VertexOverlayCache cache)
    {
        foreach (var submeshCache in cache.Submeshes.Values)
        {
            if (submeshCache.VertexBuffer is not null)
            {
                submeshCache.VertexBuffer.Dispose();
                _retainedOverlayBufferDisposeCount++;
            }
        }
        cache.Submeshes.Clear();
        cache.Valid = false;
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
            || _wireGeometryShader is null
            || _vertexMarkerGeometryShader is null
            || _overlayPixelShader is null
            || _overlayCameraBuffer is null)
        {
            return;
        }
        _context.OMSetBlendState(_overlayBlendState);
        _context.OMSetDepthStencilState(_overlayDepthState);
        _overlayCommandDepthMode = 0;
        _context.IASetInputLayout(_overlayInputLayout);
        _context.VSSetShader(_overlayVertexShader);
        _context.GSSetShader(null);
        _context.PSSetShader(_overlayPixelShader);
        _context.OMSetDepthStencilState(_overlayDepthState);
        DrawSceneGrid();
        if (!_overlayShowXRay)
        {
            if (_overlayShowWire)
            {
                DrawD3D11WireOverlay();
            }
            if (_overlayShowVertices)
            {
                QueueD3D11VertexOverlay();
            }
            DrawSelectedSourcesOverlay();
            DrawSelectedFacesOverlay();
            DrawSelectedEdgesOverlay();
            DrawSelectedVerticesOverlay();
            DrawProvisionalFacesOverlay();
            DrawProvisionalEdgesOverlay();
            DrawProvisionalVerticesOverlay();
        }

        _context.OMSetDepthStencilState(_overlayNoDepthState);
        _overlayCommandDepthMode = 1;
        if (_overlayShowXRay)
        {
            DrawD3D11WireOverlay();
            if (_overlayShowVertices)
            {
                QueueD3D11VertexOverlay();
            }
            DrawSelectedSourcesOverlay();
            DrawSelectedFacesOverlay();
            DrawSelectedEdgesOverlay();
            DrawSelectedVerticesOverlay();
            DrawProvisionalFacesOverlay();
            DrawProvisionalEdgesOverlay();
            DrawProvisionalVerticesOverlay();
        }
        if (ActivePaneInteractionAllowed)
        {
            DrawSelectionRectangleOverlay();
            DrawSelectionLassoOverlay();
            DrawBrushCursorOverlay();
        }
        if (_overlayShowXRay)
        {
            DrawXRayOverlayMarker();
        }
        DrawPreviewSceneOverlays();

        _context.OMSetDepthStencilState(_gizmoDepthState);
        _overlayCommandDepthMode = 2;
        DrawSceneGizmo();
        FlushOverlayPrimitives();
        _context.OMSetBlendState(_blendState);
        _context.OMSetDepthStencilState(_depthState);
    }

    private void QueueD3D11VertexOverlay()
    {
        _overlayDrawCommands.Add(new D3D11OverlayDrawCommand(
            PrimitiveTopology.Undefined,
            0,
            0,
            default,
            default,
            _overlayCommandDepthMode,
            DrawSceneVertices: true));
    }

    private void DrawSceneGrid()
    {
        if (ActivePaneGridVisible)
        {
            var spacing = Math.Max(
                0.0001f,
                _scene.GridSpacing * _presentationSettings.GridSpacingScale);
            if (!_gridGeometryValid
                || _cachedGridOrigin != _scene.GridOrigin
                || _cachedGridSpacing != spacing
                || _cachedGridLineCount != _presentationSettings.GridLineCount)
            {
                RebuildGridGeometry(spacing);
            }
            else
            {
                _retainedOverlayCacheHitCount++;
            }
            // Minor lines draw the configured colour; major lines a lightened
            // variant of it, the same +35 step the fixed palette used.
            var gridColor = _presentationSettings.GridColor;
            var minorR = (byte)Math.Clamp((int)MathF.Round(gridColor.X * 255f), 0, 255);
            var minorG = (byte)Math.Clamp((int)MathF.Round(gridColor.Y * 255f), 0, 255);
            var minorB = (byte)Math.Clamp((int)MathF.Round(gridColor.Z * 255f), 0, 255);
            DrawOverlayPrimitive(PrimitiveTopology.LineList, _gridMinorVertices, OverlayColor(minorR, minorG, minorB, 75), _camera.WorldViewProjection);
            DrawOverlayPrimitive(
                PrimitiveTopology.LineList,
                _gridMajorVertices,
                OverlayColor(
                    (byte)Math.Min(255, minorR + 35),
                    (byte)Math.Min(255, minorG + 35),
                    (byte)Math.Min(255, minorB + 35),
                    115),
                _camera.WorldViewProjection);
        }
        if (_scene.ComparisonMode == "overlay")
        {
            var generation = OverlayGeometryGenerationKey();
            if (!_referenceOverlayValid || _referenceOverlayGeneration != generation)
            {
                RebuildReferenceOverlay(generation);
            }
            else
            {
                _retainedOverlayCacheHitCount++;
            }
            DrawOverlayPrimitive(PrimitiveTopology.LineList, _referenceOverlayVertices, OverlayColor(90, 205, 255, 190), _camera.WorldViewProjection);
        }
    }

    private void RebuildGridGeometry(float spacing)
    {
        _gridMinorVertices.Clear();
        _gridMajorVertices.Clear();
        var halfLines = Math.Clamp(_presentationSettings.GridLineCount, 4, 40);
        for (var line = -halfLines; line <= halfLines; line++)
        {
            var target = line % 5 == 0 ? _gridMajorVertices : _gridMinorVertices;
            var offset = line * spacing;
            target.Add(_scene.GridOrigin + new Vector3(-halfLines * spacing, 0, offset));
            target.Add(_scene.GridOrigin + new Vector3(halfLines * spacing, 0, offset));
            target.Add(_scene.GridOrigin + new Vector3(offset, 0, -halfLines * spacing));
            target.Add(_scene.GridOrigin + new Vector3(offset, 0, halfLines * spacing));
        }
        _cachedGridOrigin = _scene.GridOrigin;
        _cachedGridSpacing = spacing;
        _cachedGridLineCount = halfLines;
        _gridGeometryValid = true;
        _retainedOverlayRebuildCount++;
    }

    private void RebuildReferenceOverlay(D3D11OverlayGeometryGenerationKey generation)
    {
        _referenceOverlayVertices.Clear();
        for (var submeshIndex = _scene.EditableSubmeshCount; submeshIndex < _scene.EditableSubmeshCount + _scene.ReferenceSubmeshCount; submeshIndex++)
        {
            if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            AddSubmeshFaceLineVertices(submeshIndex, _referenceOverlayVertices);
        }
        _referenceOverlayGeneration = generation;
        _referenceOverlayValid = true;
        _retainedOverlayRebuildCount++;
    }

    private void DrawD3D11WireOverlay()
    {
        var overlayStyle = FitRelativeOverlayPolicy.ForCamera(_camera, _overlaySettings.Sizing);
        var cache = WireOverlayCacheForActivePane();
        var generation = OverlayGeometryGenerationKey();
        if (!cache.Valid || cache.Generation != generation)
        {
            if (cache.VertexBuffer is not null)
            {
                cache.VertexBuffer.Dispose();
                cache.VertexBuffer = null;
                _retainedOverlayBufferDisposeCount++;
                _retainedWireOverlayBufferDisposeCount++;
            }
            cache.Lines.Clear();
            var edges = _overlayTopology.Edges;
            for (var edgeIndex = 0; edgeIndex < edges.Count; edgeIndex++)
            {
                var edge = edges[edgeIndex];
                if (edge.SubmeshIndex < 0
                    || edge.SubmeshIndex >= _document.Submeshes.Count
                    || !ActivePaneIncludes(edge.SubmeshIndex)
                    || _materials.ParametersForSubmesh(edge.SubmeshIndex).Visible is false)
                {
                    continue;
                }
                AddEdgeLineVertices(edge, cache.Lines);
            }
            cache.VertexBuffer = CreateRetainedOverlayBuffer(cache.Lines);
            cache.Generation = generation;
            cache.Valid = true;
            _retainedOverlayRebuildCount++;
        }
        else
        {
            _retainedOverlayCacheHitCount++;
        }
        DrawRetainedOverlayPrimitive(
            PrimitiveTopology.LineList,
            cache.VertexBuffer,
            cache.Lines.Count,
            ScaleOverlayAlpha(
                _overlayShowXRay ? _xrayWireOverlayColor : _wireOverlayColor,
                overlayStyle.WireOpacityScale),
            _camera.WorldViewProjection,
            lineWidthPixels: _overlaySettings.Sizing.WireWidthPixels);
        if (cache.Lines.Count > 0)
        {
            _wireOverlayDrawCount++;
        }
    }

    private D3D11WireOverlayCache WireOverlayCacheForActivePane() => (_activeRenderPane?.Role ?? "comparison") switch
    {
        "reference" => _referenceWireOverlayCache,
        "editable" => _editableWireOverlayCache,
        _ => _comparisonWireOverlayCache,
    };

    private D3D11OverlayGeometryGenerationKey OverlayGeometryGenerationKey() => new(
        _topologyGeneration,
        _sparseVertexUpdateCount,
        _scene.SceneGeneration,
        _scene.PresentationGeneration,
        _materials.Generation,
        _materialParameterApplyCount,
        _scene.Translation,
        _scene.RotationDegrees,
        _scene.Scale,
        (_activeRenderPane?.Role ?? "comparison") switch
        {
            "reference" => 1,
            "editable" => 2,
            _ => 0,
        });

    private void DrawD3D11VertexOverlay()
    {
        if (_context is null || _overlayCameraBuffer is null)
        {
            return;
        }
        var overlayStyle = FitRelativeOverlayPolicy.ForCamera(_camera, _overlaySettings.Sizing);
        var constants = new D3D11OverlayConstants
        {
            WorldViewProjection = _camera.WorldViewProjection,
            Color = _overlayShowXRay ? _xrayVertexOverlayColor : _vertexOverlayColor,
            MarkerSettings = new Vector4(
                Math.Max(1.0f, _camera.ViewportWidth),
                Math.Max(1.0f, _camera.ViewportHeight),
                overlayStyle.VertexMarkerSizePixels,
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
            _context.IASetVertexBuffer(0u, ActiveVertexBuffer(batch), D3D11SubmeshBatch.VertexStride);
            _context.IASetIndexBuffer(batch.IndexBuffer, Vortice.DXGI.Format.R32_UInt, 0);
            _context.DrawIndexed((uint)batch.IndexCount, 0, 0);
            _vertexOverlayBatchDrawCount++;
        }
        _context.GSSetShader(null);
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

    private void AddSubmeshFaceLineVertices(int submeshIndex, List<Vector3> lines)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return;
        }
        var submesh = _document.Submeshes[submeshIndex];
        var model = ActivePaneModelMatrix(submeshIndex);
        foreach (var face in submesh.Faces)
        {
            if (face.Corners.Length != 3)
            {
                continue;
            }
            var firstIndex = face.Corners[0].VertexIndex;
            var secondIndex = face.Corners[1].VertexIndex;
            var thirdIndex = face.Corners[2].VertexIndex;
            if (firstIndex < 0 || firstIndex >= submesh.Vertices.Count
                || secondIndex < 0 || secondIndex >= submesh.Vertices.Count
                || thirdIndex < 0 || thirdIndex >= submesh.Vertices.Count)
            {
                continue;
            }
            var first = TransformVertex(submesh.Vertices[firstIndex], model);
            var second = TransformVertex(submesh.Vertices[secondIndex], model);
            var third = TransformVertex(submesh.Vertices[thirdIndex], model);
            lines.Add(first);
            lines.Add(second);
            lines.Add(second);
            lines.Add(third);
            lines.Add(third);
            lines.Add(first);
        }
    }

    private void AddFaceVertices(int submeshIndex, ObjSubmesh submesh, ObjFace face, List<Vector3> triangles, List<Vector3> lines)
    {
        if (face.Corners.Length != 3)
        {
            return;
        }
        var firstIndex = face.Corners[0].VertexIndex;
        var secondIndex = face.Corners[1].VertexIndex;
        var thirdIndex = face.Corners[2].VertexIndex;
        if (firstIndex < 0 || firstIndex >= submesh.Vertices.Count
            || secondIndex < 0 || secondIndex >= submesh.Vertices.Count
            || thirdIndex < 0 || thirdIndex >= submesh.Vertices.Count)
        {
            return;
        }
        var model = ActivePaneModelMatrix(submeshIndex);
        var first = TransformVertex(submesh.Vertices[firstIndex], model);
        var second = TransformVertex(submesh.Vertices[secondIndex], model);
        var third = TransformVertex(submesh.Vertices[thirdIndex], model);
        triangles.Add(first);
        triangles.Add(second);
        triangles.Add(third);
        lines.Add(first);
        lines.Add(second);
        lines.Add(second);
        lines.Add(third);
        lines.Add(third);
        lines.Add(first);
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

    private List<Vector3> ResetScratchA()
    {
        _overlayScratchA.Clear();
        return _overlayScratchA;
    }

    private List<Vector3> ResetScratchB()
    {
        _overlayScratchB.Clear();
        return _overlayScratchB;
    }

    private static Vector3 GizmoCirclePoint(Vector3 origin, float radius, int normalAxis, float angle) => normalAxis switch
    {
        0 => origin + new Vector3(0, MathF.Cos(angle) * radius, MathF.Sin(angle) * radius),
        1 => origin + new Vector3(MathF.Cos(angle) * radius, 0, MathF.Sin(angle) * radius),
        _ => origin + new Vector3(MathF.Cos(angle) * radius, MathF.Sin(angle) * radius, 0),
    };

    private static Vector3 TransformVertex(Vec3 vertex, Matrix4x4 model) =>
        Vector3.Transform(new Vector3(vertex.X, vertex.Y, vertex.Z), model);

    private unsafe void DrawOverlayPrimitive(
        PrimitiveTopology topology,
        IReadOnlyList<Vector3> positions,
        Vector4 color,
        Matrix4x4 worldViewProjection,
        float lineWidthPixels = 0.0f)
    {
        if (positions.Count == 0 || _device is null || _context is null || _overlayCameraBuffer is null)
        {
            return;
        }
        if (OverlayRgbMatches(color, _overlaySettings.Colors.Selection))
        {
            _committedSelectionOverlayPrimitiveCount++;
            _lastCommittedSelectionPrimitiveColor = _overlaySettings.Colors.Selection;
        }
        else if (OverlayRgbMatches(color, _overlaySettings.Colors.LiveSelection))
        {
            _liveSelectionOverlayPrimitiveCount++;
            _lastLiveSelectionPrimitiveColor = _overlaySettings.Colors.LiveSelection;
        }
        var startVertex = _overlayFrameVertices.Count;
        for (var index = 0; index < positions.Count; index++)
        {
            _overlayFrameVertices.Add(positions[index]);
        }
        _overlayDrawCommands.Add(new D3D11OverlayDrawCommand(
            topology,
            startVertex,
            positions.Count,
            color,
            worldViewProjection,
            _overlayCommandDepthMode,
            lineWidthPixels));
    }

    private void DrawRetainedOverlayPrimitive(
        PrimitiveTopology topology,
        ID3D11Buffer? vertexBuffer,
        int vertexCount,
        Vector4 color,
        Matrix4x4 worldViewProjection,
        float lineWidthPixels = 0.0f)
    {
        if (vertexBuffer is null || vertexCount <= 0 || _context is null || _overlayCameraBuffer is null)
        {
            return;
        }
        if (OverlayRgbMatches(color, _overlaySettings.Colors.Selection))
        {
            _committedSelectionOverlayPrimitiveCount++;
            _lastCommittedSelectionPrimitiveColor = _overlaySettings.Colors.Selection;
        }
        else if (OverlayRgbMatches(color, _overlaySettings.Colors.LiveSelection))
        {
            _liveSelectionOverlayPrimitiveCount++;
            _lastLiveSelectionPrimitiveColor = _overlaySettings.Colors.LiveSelection;
        }
        _overlayDrawCommands.Add(new D3D11OverlayDrawCommand(
            topology,
            0,
            vertexCount,
            color,
            worldViewProjection,
            _overlayCommandDepthMode,
            lineWidthPixels,
            VertexBuffer: vertexBuffer));
    }

    private static bool OverlayRgbMatches(Vector4 color, System.Drawing.Color expected) =>
        MathF.Abs(color.X - (expected.R / 255.0f)) < 0.0001f
        && MathF.Abs(color.Y - (expected.G / 255.0f)) < 0.0001f
        && MathF.Abs(color.Z - (expected.B / 255.0f)) < 0.0001f;

    private unsafe void FlushOverlayPrimitives()
    {
        if (_overlayDrawCommands.Count == 0
            || _device is null
            || _context is null
            || _overlayCameraBuffer is null)
        {
            _overlayFrameVertices.Clear();
            _overlayDrawCommands.Clear();
            return;
        }
        ID3D11Buffer? vertexBuffer = null;
        if (_overlayFrameVertices.Count > 0)
        {
            EnsureOverlayVertexCapacity(_overlayFrameVertices.Count);
            vertexBuffer = _overlayVertexBuffer;
            if (vertexBuffer is null)
            {
                _overlayFrameVertices.Clear();
                _overlayDrawCommands.Clear();
                return;
            }
            var mapped = _context.Map(vertexBuffer, MapMode.WriteDiscard, MapFlags.None);
            try
            {
                var destination = (D3D11OverlayVertex*)mapped.DataPointer;
                for (var index = 0; index < _overlayFrameVertices.Count; index++)
                {
                    destination[index] = new D3D11OverlayVertex(_overlayFrameVertices[index]);
                }
            }
            finally
            {
                _context.Unmap(vertexBuffer, 0);
            }
            _overlayVertexWriteOffset = _overlayFrameVertices.Count;
            _overlayVertexBufferMapCount++;
            _overlayVerticesUploaded += _overlayFrameVertices.Count;
        }
        _overlayBatchFlushCount++;
        _context.OMSetBlendState(_overlayBlendState);
        _context.IASetInputLayout(_overlayInputLayout);
        _context.VSSetShader(_overlayVertexShader);
        _context.GSSetShader(null);
        _context.PSSetShader(_overlayPixelShader);
        _context.VSSetConstantBuffer(1u, _overlayCameraBuffer);
        _context.GSSetConstantBuffer(1u, _overlayCameraBuffer);
        _context.PSSetConstantBuffer(1u, _overlayCameraBuffer);
        ID3D11Buffer? boundVertexBuffer = null;
        foreach (var command in _overlayDrawCommands)
        {
            _context.OMSetDepthStencilState(command.DepthMode switch
            {
                1 => _overlayNoDepthState,
                2 => _gizmoDepthState,
                _ => _overlayDepthState,
            });
            if (command.DrawSceneVertices)
            {
                DrawD3D11VertexOverlay();
                if (command.DepthMode == 1)
                {
                    _xRayVertexNoDepthPassCount++;
                }
                _context.IASetInputLayout(_overlayInputLayout);
                _context.VSSetShader(_overlayVertexShader);
                _context.GSSetShader(null);
                _context.PSSetShader(_overlayPixelShader);
                _context.VSSetConstantBuffer(1u, _overlayCameraBuffer);
                _context.PSSetConstantBuffer(1u, _overlayCameraBuffer);
                if (vertexBuffer is not null)
                {
                    _context.IASetVertexBuffer(0u, vertexBuffer, OverlayVertexStride);
                    boundVertexBuffer = vertexBuffer;
                }
                else
                {
                    boundVertexBuffer = null;
                }
                continue;
            }
            var commandVertexBuffer = command.VertexBuffer ?? vertexBuffer;
            if (commandVertexBuffer is null)
            {
                continue;
            }
            if (!ReferenceEquals(boundVertexBuffer, commandVertexBuffer))
            {
                _context.IASetVertexBuffer(0u, commandVertexBuffer, OverlayVertexStride);
                boundVertexBuffer = commandVertexBuffer;
            }
            var constants = new D3D11OverlayConstants
            {
                WorldViewProjection = command.WorldViewProjection,
                Color = command.Color,
                MarkerSettings = new Vector4(
                    Math.Max(1.0f, _camera.ViewportWidth),
                    Math.Max(1.0f, _camera.ViewportHeight),
                    command.LineWidthPixels,
                    0.0f),
            };
            _context.UpdateSubresource(in constants, _overlayCameraBuffer);
            _context.GSSetShader(command.Topology switch
            {
                PrimitiveTopology.PointList when command.LineWidthPixels > 0.0f => _vertexMarkerGeometryShader,
                PrimitiveTopology.LineList when command.LineWidthPixels > 1.0f => _wireGeometryShader,
                _ => null,
            });
            _context.IASetPrimitiveTopology(command.Topology);
            _context.Draw((uint)command.VertexCount, (uint)command.StartVertex);
            if (command.DepthMode == 1 && command.LineWidthPixels > 1.0f)
            {
                _xRayWireNoDepthDrawCount++;
            }
            _overlayBatchedDrawCount++;
        }
        _context.GSSetShader(null);
        _overlayFrameVertices.Clear();
        _overlayDrawCommands.Clear();
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

    private static Vector4 OverlayColor(System.Drawing.Color color, int alpha) =>
        OverlayColor(color.R, color.G, color.B, alpha);

    private static Vector4 ScaleOverlayAlpha(Vector4 color, float opacityScale) =>
        new(color.X, color.Y, color.Z, Math.Clamp(color.W * opacityScale, 0.0f, 1.0f));
}

[StructLayout(LayoutKind.Sequential)]
internal readonly record struct D3D11OverlayVertex(Vector3 Position);

internal readonly record struct D3D11OverlayDrawCommand(
    PrimitiveTopology Topology,
    int StartVertex,
    int VertexCount,
    Vector4 Color,
    Matrix4x4 WorldViewProjection,
    byte DepthMode,
    float LineWidthPixels = 0.0f,
    bool DrawSceneVertices = false,
    ID3D11Buffer? VertexBuffer = null);

internal readonly record struct D3D11OverlayGeometryGenerationKey(
    long TopologyGeneration,
    long SparseVertexUpdateCount,
    long SceneGeneration,
    long PresentationGeneration,
    long MaterialGeneration,
    long MaterialParameterApplyCount,
    Vector3 Translation,
    Vector3 RotationDegrees,
    Vector3 Scale,
    int PaneRole);

internal sealed class D3D11WireOverlayCache
{
    public List<Vector3> Lines { get; } = new(4096);
    public ID3D11Buffer? VertexBuffer { get; set; }
    public D3D11OverlayGeometryGenerationKey Generation { get; set; }
    public bool Valid { get; set; }
}

internal sealed class D3D11FaceOverlayCache
{
    public Dictionary<int, HashSet<int>> SelectedFaces { get; } = new();
    public List<Vector3> Triangles { get; } = new(4096);
    public List<Vector3> Lines { get; } = new(8192);
    public ID3D11Buffer? TriangleBuffer;
    public ID3D11Buffer? LineBuffer;
    public int TriangleCapacity;
    public int LineCapacity;
    public D3D11OverlayGeometryGenerationKey Generation { get; set; }
    public bool Valid { get; set; }
}

internal sealed class D3D11VertexOverlayCache
{
    public Dictionary<int, D3D11VertexOverlaySubmeshCache> Submeshes { get; } = new();
    public D3D11OverlayGeometryGenerationKey Generation { get; set; }
    public bool Valid { get; set; }
}

internal sealed class D3D11VertexOverlaySubmeshCache
{
    public HashSet<int> SelectedVertices { get; } = new();
    public List<Vector3> Points { get; } = new(4096);
    public ID3D11Buffer? VertexBuffer;
    public int VertexCapacity;
}

[StructLayout(LayoutKind.Sequential)]
internal struct D3D11OverlayConstants
{
    public Matrix4x4 WorldViewProjection;
    public Vector4 Color;
    public Vector4 MarkerSettings;
}
