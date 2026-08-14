using System.Numerics;
using System.Runtime.InteropServices;
using Vortice.Direct3D;
using Vortice.Direct3D11;

namespace Cdmw.MeshEditorExperiment;

// The selection overlays: committed faces, edges, vertices and sources, plus
// the provisional ones a stroke paints before it commits. Split from
// D3D11MaterialViewport.Overlay to keep that file inside the owned-file line
// cap; same partial class, so nothing about how these are called changes.
internal sealed partial class D3D11MaterialViewport
{
    private void DrawSelectedSourcesOverlay()
    {
        var triangles = ResetScratchA();
        var lines = ResetScratchB();
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
        DrawOverlayPrimitive(PrimitiveTopology.TriangleList, triangles, OverlayColor(_overlaySettings.Colors.Selection, _overlayShowXRay ? 64 : 42), _camera.WorldViewProjection);
        DrawOverlayPrimitive(PrimitiveTopology.LineList, lines, OverlayColor(_overlaySettings.Colors.Selection, _overlayShowXRay ? 230 : 185), _camera.WorldViewProjection);
    }

    private void DrawSelectedFacesOverlay()
    {
        if (_overlayProvisionalFaces is { Count: 0 }
            && _provisionalFaceOverlayCache.Valid)
        {
            if (IndexSelectionsEqual(
                _provisionalFaceOverlayCache.SelectedFaces,
                _overlaySelectedFaces))
            {
                var supersededCommittedCache = _selectedFaceOverlayCache;
                _selectedFaceOverlayCache = _provisionalFaceOverlayCache;
                _provisionalFaceOverlayCache = supersededCommittedCache;
            }
            // Terminal authority either consumed this exact GPU cache or
            // rejected part of its visible-depth echo. In both cases the old
            // provisional set is finished; retaining a mismatch would compare
            // every selected index again on every subsequent frame.
            DisposeFaceOverlayCache(_provisionalFaceOverlayCache);
        }
        DrawFaceSelectionOverlay(
            _selectedFaceOverlayCache,
            _overlaySelectedFaces,
            OverlayColor(_overlaySettings.Colors.Selection, _overlayShowXRay ? 88 : 58),
            OverlayColor(_overlaySettings.Colors.Selection, 235));
    }

    private void DrawFaceSelectionOverlay(
        D3D11FaceOverlayCache cache,
        IReadOnlyDictionary<int, HashSet<int>> selectedFaces,
        Vector4 triangleColor,
        Vector4 lineColor)
    {
        UpdateFaceSelectionOverlay(cache, selectedFaces);
        DrawRetainedOverlayPrimitive(
            PrimitiveTopology.TriangleList,
            cache.TriangleBuffer,
            cache.Triangles.Count,
            triangleColor,
            _camera.WorldViewProjection);
        DrawRetainedOverlayPrimitive(
            PrimitiveTopology.LineList,
            cache.LineBuffer,
            cache.Lines.Count,
            lineColor,
            _camera.WorldViewProjection);
    }

    private void UpdateFaceSelectionOverlay(
        D3D11FaceOverlayCache cache,
        IReadOnlyDictionary<int, HashSet<int>> selectedFaces)
    {
        var generation = OverlayGeometryGenerationKey();
        var rebuild = !cache.Valid
            || cache.Generation != generation
            || FaceSelectionRemoved(cache.SelectedFaces, selectedFaces);
        var previousTriangleCount = cache.Triangles.Count;
        var previousLineCount = cache.Lines.Count;
        if (rebuild)
        {
            cache.SelectedFaces.Clear();
            cache.Triangles.Clear();
            cache.Lines.Clear();
            previousTriangleCount = 0;
            previousLineCount = 0;
        }
        foreach (var pair in selectedFaces)
        {
            if (!cache.SelectedFaces.TryGetValue(pair.Key, out var cachedFaces))
            {
                cachedFaces = new HashSet<int>();
                cache.SelectedFaces[pair.Key] = cachedFaces;
            }
            foreach (var faceIndex in pair.Value)
            {
                if (!cachedFaces.Add(faceIndex)
                    || pair.Key < 0
                    || pair.Key >= _document.Submeshes.Count
                    || !ActivePaneIncludes(pair.Key)
                    || _materials.ParametersForSubmesh(pair.Key).Visible is false)
                {
                    continue;
                }
                var submesh = _document.Submeshes[pair.Key];
                if (faceIndex < 0 || faceIndex >= submesh.Faces.Count)
                {
                    continue;
                }
                AddFaceVertices(
                    pair.Key,
                    submesh,
                    submesh.Faces[faceIndex],
                    cache.Triangles,
                    cache.Lines);
            }
        }
        var trianglesChanged = rebuild || cache.Triangles.Count != previousTriangleCount;
        var linesChanged = rebuild || cache.Lines.Count != previousLineCount;
        if (trianglesChanged)
        {
            UpdateRetainedOverlayBuffer(
                ref cache.TriangleBuffer,
                ref cache.TriangleCapacity,
                cache.Triangles,
                previousTriangleCount,
                rebuild);
        }
        if (linesChanged)
        {
            UpdateRetainedOverlayBuffer(
                ref cache.LineBuffer,
                ref cache.LineCapacity,
                cache.Lines,
                previousLineCount,
                rebuild);
        }
        cache.Generation = generation;
        cache.Valid = true;
        if (rebuild)
        {
            _retainedOverlayRebuildCount++;
        }
        else
        {
            _retainedOverlayCacheHitCount++;
        }
    }

    private static bool FaceSelectionRemoved(
        IReadOnlyDictionary<int, HashSet<int>> cached,
        IReadOnlyDictionary<int, HashSet<int>> current)
    {
        foreach (var pair in cached)
        {
            if (!current.TryGetValue(pair.Key, out var currentFaces)
                || pair.Value.Any(faceIndex => !currentFaces.Contains(faceIndex)))
            {
                return true;
            }
        }
        return false;
    }

    private static bool IndexSelectionsEqual(
        IReadOnlyDictionary<int, HashSet<int>> left,
        IReadOnlyDictionary<int, HashSet<int>> right) =>
        left.Count == right.Count
        && left.All(pair => right.TryGetValue(pair.Key, out var faces)
            && pair.Value.SetEquals(faces));

    private unsafe void UpdateRetainedOverlayBuffer(
        ref ID3D11Buffer? buffer,
        ref int capacity,
        IReadOnlyList<Vector3> vertices,
        int previousCount,
        bool rewrite)
    {
        if (vertices.Count == 0)
        {
            if (buffer is not null)
            {
                buffer.Dispose();
                buffer = null;
                _retainedOverlayBufferDisposeCount++;
            }
            capacity = 0;
            return;
        }
        if (_device is null || _context is null)
        {
            return;
        }
        if (buffer is null || capacity < vertices.Count)
        {
            var nextCapacity = Math.Max(InitialOverlayVertexCapacity, capacity);
            var wantedHeadroom = checked(vertices.Count * 4L);
            while (nextCapacity < vertices.Count)
            {
                nextCapacity = checked(nextCapacity * 2);
            }
            while (nextCapacity < wantedHeadroom && nextCapacity <= int.MaxValue / 2)
            {
                nextCapacity = checked(nextCapacity * 2);
            }
            var replacement = _device.CreateBuffer(new BufferDescription(
                checked((uint)(nextCapacity * (long)OverlayVertexStride)),
                BindFlags.VertexBuffer,
                ResourceUsage.Dynamic,
                CpuAccessFlags.Write,
                ResourceOptionFlags.None,
                0));
            if (buffer is not null)
            {
                buffer.Dispose();
                _retainedOverlayBufferDisposeCount++;
            }
            buffer = replacement;
            capacity = nextCapacity;
            previousCount = 0;
            rewrite = true;
            _retainedOverlayBufferCreateCount++;
        }
        var firstVertex = rewrite ? 0 : previousCount;
        if (firstVertex >= vertices.Count)
        {
            return;
        }
        var mapped = _context.Map(
            buffer,
            rewrite ? MapMode.WriteDiscard : MapMode.WriteNoOverwrite,
            MapFlags.None);
        _retainedOverlayBufferMapCount++;
        if (!rewrite)
        {
            _retainedOverlayBufferNoOverwriteMapCount++;
        }
        try
        {
            var destination = (D3D11OverlayVertex*)mapped.DataPointer;
            for (var index = firstVertex; index < vertices.Count; index++)
            {
                destination[index] = new D3D11OverlayVertex(vertices[index]);
            }
        }
        finally
        {
            _context.Unmap(buffer, 0);
        }
        _overlayVerticesUploaded += vertices.Count - firstVertex;
    }

    private long RetainedOverlayBufferBytesEstimate()
    {
        long vertexCapacity = _comparisonWireOverlayCache.VertexBuffer is null
            ? 0
            : _comparisonWireOverlayCache.Lines.Count;
        vertexCapacity += _referenceWireOverlayCache.VertexBuffer is null
            ? 0
            : _referenceWireOverlayCache.Lines.Count;
        vertexCapacity += _editableWireOverlayCache.VertexBuffer is null
            ? 0
            : _editableWireOverlayCache.Lines.Count;
        vertexCapacity += _selectedFaceOverlayCache.TriangleCapacity;
        vertexCapacity += _selectedFaceOverlayCache.LineCapacity;
        vertexCapacity += _provisionalFaceOverlayCache.TriangleCapacity;
        vertexCapacity += _provisionalFaceOverlayCache.LineCapacity;
        vertexCapacity += _selectedVertexOverlayCache.Submeshes.Values.Sum(
            cache => (long)cache.VertexCapacity);
        vertexCapacity += _provisionalVertexOverlayCache.Submeshes.Values.Sum(
            cache => (long)cache.VertexCapacity);
        return vertexCapacity * OverlayVertexStride;
    }

    private void DrawSelectedEdgesOverlay()
    {
        var selected = ResetScratchA();
        var hovered = ResetScratchB();
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
            if (edge.Id == _overlayHoverEdgeId)
            {
                AddEdgeLineVertices(edge, hovered);
            }
            else if (_overlaySelectedEdges.Contains(edge.Id))
            {
                AddEdgeLineVertices(edge, selected);
            }
        }
        DrawOverlayPrimitive(PrimitiveTopology.LineList, selected, _selectionOverlayColor, _camera.WorldViewProjection);
        DrawOverlayPrimitive(PrimitiveTopology.LineList, hovered, _liveSelectionOverlayColor, _camera.WorldViewProjection);
    }

    private void DrawSelectedVerticesOverlay()
    {
        if (_overlayProvisionalVertices is { Count: 0 }
            && _provisionalVertexOverlayCache.Valid)
        {
            if (IndexSelectionsEqual(
                VertexOverlaySelections(_provisionalVertexOverlayCache),
                _overlaySelectedVertices))
            {
                var supersededCommittedCache = _selectedVertexOverlayCache;
                _selectedVertexOverlayCache = _provisionalVertexOverlayCache;
                _provisionalVertexOverlayCache = supersededCommittedCache;
            }
            DisposeVertexOverlayCache(_provisionalVertexOverlayCache);
        }
        DrawVertexSelectionOverlay(
            _selectedVertexOverlayCache,
            _overlaySelectedVertices,
            _selectionOverlayColor);
    }

    private static Dictionary<int, HashSet<int>> VertexOverlaySelections(D3D11VertexOverlayCache cache) =>
        cache.Submeshes.ToDictionary(
            pair => pair.Key,
            pair => pair.Value.SelectedVertices);

    private void DrawVertexSelectionOverlay(
        D3D11VertexOverlayCache cache,
        IReadOnlyDictionary<int, HashSet<int>> selectedVertices,
        Vector4 color)
    {
        UpdateVertexSelectionOverlay(cache, selectedVertices);
        foreach (var pair in cache.Submeshes)
        {
            DrawRetainedOverlayPrimitive(
                PrimitiveTopology.PointList,
                pair.Value.VertexBuffer,
                pair.Value.Points.Count,
                color,
                ActivePaneModelMatrix(pair.Key) * _camera.WorldViewProjection,
                SelectedVertexMarkerRadiusPixels);
        }
    }

    private void UpdateVertexSelectionOverlay(
        D3D11VertexOverlayCache cache,
        IReadOnlyDictionary<int, HashSet<int>> selectedVertices)
    {
        var generation = OverlayGeometryGenerationKey();
        var generationChanged = !cache.Valid || cache.Generation != generation;
        if (generationChanged)
        {
            DisposeVertexOverlayCache(cache);
        }
        foreach (var submeshIndex in cache.Submeshes.Keys
            .Where(submeshIndex => !selectedVertices.ContainsKey(submeshIndex))
            .ToArray())
        {
            DisposeVertexOverlaySubmesh(cache.Submeshes[submeshIndex]);
            cache.Submeshes.Remove(submeshIndex);
        }
        foreach (var pair in selectedVertices)
        {
            if (pair.Key < 0
                || pair.Key >= _document.Submeshes.Count
                || !ActivePaneIncludes(pair.Key)
                || _materials.ParametersForSubmesh(pair.Key).Visible is false)
            {
                continue;
            }
            if (!cache.Submeshes.TryGetValue(pair.Key, out var submeshCache))
            {
                submeshCache = new D3D11VertexOverlaySubmeshCache();
                cache.Submeshes[pair.Key] = submeshCache;
            }
            var rebuild = submeshCache.SelectedVertices.Any(
                vertexIndex => !pair.Value.Contains(vertexIndex));
            var previousPointCount = submeshCache.Points.Count;
            if (rebuild)
            {
                submeshCache.SelectedVertices.Clear();
                submeshCache.Points.Clear();
                previousPointCount = 0;
            }
            var submesh = _document.Submeshes[pair.Key];
            foreach (var vertexIndex in pair.Value)
            {
                if (vertexIndex < 0
                    || vertexIndex >= submesh.Vertices.Count
                    || !submeshCache.SelectedVertices.Add(vertexIndex))
                {
                    continue;
                }
                var vertex = submesh.Vertices[vertexIndex];
                submeshCache.Points.Add(new Vector3(vertex.X, vertex.Y, vertex.Z));
            }
            if (rebuild || submeshCache.Points.Count != previousPointCount)
            {
                UpdateRetainedOverlayBuffer(
                    ref submeshCache.VertexBuffer,
                    ref submeshCache.VertexCapacity,
                    submeshCache.Points,
                    previousPointCount,
                    rebuild);
            }
        }
        cache.Generation = generation;
        cache.Valid = true;
        if (generationChanged)
        {
            _retainedOverlayRebuildCount++;
        }
        else
        {
            _retainedOverlayCacheHitCount++;
        }
    }

    private void DisposeVertexOverlaySubmesh(D3D11VertexOverlaySubmeshCache cache)
    {
        if (cache.VertexBuffer is not null)
        {
            cache.VertexBuffer.Dispose();
            cache.VertexBuffer = null;
            _retainedOverlayBufferDisposeCount++;
        }
    }

    /// <summary>
    /// The instant local echo of a paint or click selection, tinted cooler
    /// and fainter than the authoritative gold so the two states read apart;
    /// the authoritative result replaces it one round trip later.
    /// </summary>
    private void DrawProvisionalVerticesOverlay()
    {
        var provisional = _overlayProvisionalVertices;
        if (provisional is null || provisional.Count == 0)
        {
            return;
        }
        DrawVertexSelectionOverlay(
            _provisionalVertexOverlayCache,
            provisional,
            OverlayColor(_overlaySettings.Colors.LiveSelection, 180));
    }

    private void DrawProvisionalFacesOverlay()
    {
        var provisional = _overlayProvisionalFaces;
        if (provisional is null || provisional.Count == 0)
        {
            return;
        }
        DrawFaceSelectionOverlay(
            _provisionalFaceOverlayCache,
            provisional,
            OverlayColor(_overlaySettings.Colors.LiveSelection, _overlayShowXRay ? 80 : 52),
            OverlayColor(_overlaySettings.Colors.LiveSelection, 220));
    }

    private void DrawProvisionalEdgesOverlay()
    {
        var provisional = _overlayProvisionalEdges;
        if (provisional is null || provisional.Count == 0)
        {
            return;
        }
        var lines = ResetScratchA();
        foreach (var edge in _overlayTopology.Edges)
        {
            if (!provisional.Contains(edge.Id)
                || edge.SubmeshIndex < 0
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
            OverlayColor(_overlaySettings.Colors.LiveSelection, 220),
            _camera.WorldViewProjection);
    }
}
