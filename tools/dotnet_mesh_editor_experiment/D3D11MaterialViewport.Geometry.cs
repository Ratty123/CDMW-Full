using System.Buffers;
using System.Diagnostics;
using System.Numerics;
using System.Runtime.InteropServices;
using Vortice.Direct3D11;
using Vortice.Mathematics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private readonly Dictionary<int, HashSet<int>> _dirtyVerticesBySubmesh = new();
    private readonly Dictionary<int, HashSet<int>> _dirtyNormalsBySubmesh = new();
    private readonly Dictionary<int, HashSet<int>> _dirtyUvsBySubmesh = new();
    private readonly HashSet<int> _dirtyTopologySubmeshes = new();
    private readonly Dictionary<int, int> _materialSourceBySubmesh = new();
    private bool _vertexDataDirty;
    private long _topologyGeneration;
    private long _fullGeometryRebuildCount;
    private long _partialTopologyRebuildCount;
    private long _topologyBatchesRebuilt;
    private long _sparseVertexUpdateCount;
    private long _vertexPatchRangeCount;
    private long _sourceVerticesPatched;
    private long _renderVerticesUploaded;
    private long _vertexBufferCreateCount;
    private long _indexBufferCreateCount;
    private long _bufferDisposeCount;
    private long _residentGeometryBytes;
    private long _peakResidentGeometryBytes;
    private long _peakGeometryRebuildBytesEstimate;
    private double _maxDisposedGeometryResourceLifetimeMs;

    public void RefreshGeometry()
    {
        DiscardPendingVertexUpdates();
        _dirtyTopologySubmeshes.Clear();
        _geometryDirty = true;
        Invalidate();
    }

    public void RefreshVertexGeometry(IReadOnlyDictionary<int, IReadOnlyCollection<int>> changedVertices)
    {
        RefreshVertexGeometry(changedVertices.ToDictionary(
            pair => pair.Key,
            pair => MeshVertexChannelChanges.PositionsOnly(pair.Value)));
    }

    public void RefreshVertexGeometry(IReadOnlyDictionary<int, MeshVertexChannelChanges> changedChannels)
    {
        if (_geometryDirty)
        {
            Invalidate();
            return;
        }
        foreach (var (submeshIndex, channels) in changedChannels)
        {
            if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            MergeDirtyChannel(_dirtyVerticesBySubmesh, submeshIndex, channels.Positions, submesh.Vertices.Count);
            MergeDirtyChannel(_dirtyNormalsBySubmesh, submeshIndex, channels.Normals, submesh.Normals.Count);
            MergeDirtyChannel(_dirtyUvsBySubmesh, submeshIndex, channels.Uvs, submesh.Uvs.Count);
        }
        _vertexDataDirty = _dirtyVerticesBySubmesh.Count > 0 || _dirtyNormalsBySubmesh.Count > 0 || _dirtyUvsBySubmesh.Count > 0;
        if (_vertexDataDirty)
        {
            Invalidate();
        }
    }

    public void RefreshTopologyGeometry(
        IReadOnlyCollection<int> affectedSubmeshes,
        IReadOnlyDictionary<int, int> materialSources,
        bool replaceAll)
    {
        var resolvedMaterialSources = materialSources
            .Where(pair => pair.Key >= 0 && pair.Key < _document.Submeshes.Count && pair.Value >= 0)
            .ToDictionary(pair => pair.Key, pair => MaterialSourceFor(pair.Value));
        if (replaceAll)
        {
            _materialSourceBySubmesh.Clear();
        }
        else
        {
            foreach (var staleIndex in _materialSourceBySubmesh.Keys.Where(index => index >= _document.Submeshes.Count).ToArray())
            {
                _materialSourceBySubmesh.Remove(staleIndex);
            }
        }
        foreach (var (submeshIndex, materialSource) in resolvedMaterialSources)
        {
            _materialSourceBySubmesh[submeshIndex] = materialSource;
        }
        if (replaceAll)
        {
            RefreshGeometry();
            return;
        }
        foreach (var submeshIndex in affectedSubmeshes.Where(index => index >= 0))
        {
            _dirtyTopologySubmeshes.Add(submeshIndex);
            DiscardPendingVertexUpdates(submeshIndex);
        }
        if (_dirtyTopologySubmeshes.Count > 0)
        {
            Invalidate();
        }
    }

    private static void MergeDirtyChannel(
        Dictionary<int, HashSet<int>> target,
        int submeshIndex,
        IReadOnlyCollection<int> indices,
        int sourceCount)
    {
        var valid = indices.Where(index => index >= 0 && index < sourceCount).ToArray();
        if (valid.Length == 0)
        {
            return;
        }
        if (!target.TryGetValue(submeshIndex, out var dirty))
        {
            dirty = new HashSet<int>();
            target[submeshIndex] = dirty;
        }
        dirty.UnionWith(valid);
    }

    private void DiscardPendingVertexUpdates()
    {
        _dirtyVerticesBySubmesh.Clear();
        _dirtyNormalsBySubmesh.Clear();
        _dirtyUvsBySubmesh.Clear();
        _vertexDataDirty = false;
    }

    private void DiscardPendingVertexUpdates(int submeshIndex)
    {
        _dirtyVerticesBySubmesh.Remove(submeshIndex);
        _dirtyNormalsBySubmesh.Remove(submeshIndex);
        _dirtyUvsBySubmesh.Remove(submeshIndex);
        _vertexDataDirty = _dirtyVerticesBySubmesh.Count > 0 || _dirtyNormalsBySubmesh.Count > 0 || _dirtyUvsBySubmesh.Count > 0;
    }

    private void RebuildGeometry()
    {
        if (_device is null)
        {
            return;
        }
        if (_materialResourcesDirty)
        {
            BeginTextureResourceRefresh();
        }
        var nextGeneration = _topologyGeneration + 1;
        var nextBatches = new List<D3D11SubmeshBatch>(_document.Submeshes.Count);
        try
        {
            for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
            {
                var batch = BuildBatch(
                    submeshIndex,
                    _document.Submeshes[submeshIndex],
                    nextGeneration,
                    MaterialSourceFor(submeshIndex));
                if (batch is not null)
                {
                    nextBatches.Add(batch);
                }
            }
        }
        catch
        {
            foreach (var batch in nextBatches)
            {
                DisposeBatch(batch);
            }
            PruneTextureCacheToActiveBindings();
            throw;
        }

        var nextBytes = nextBatches.Sum(batch => batch.GeometryBytes);
        _peakGeometryRebuildBytesEstimate = Math.Max(_peakGeometryRebuildBytesEstimate, _residentGeometryBytes + nextBytes);
        DisposeBatches();
        _batches.AddRange(nextBatches);
        PruneTextureCacheToActiveBindings();
        _residentGeometryBytes = nextBytes;
        _peakResidentGeometryBytes = Math.Max(_peakResidentGeometryBytes, nextBytes);
        _topologyGeneration = nextGeneration;
        _fullGeometryRebuildCount++;
        DiscardPendingVertexUpdates();
        _dirtyTopologySubmeshes.Clear();
        _geometryDirty = false;
        EndTextureResourceRefresh();
    }

    private void ApplyPendingTopologyUpdates()
    {
        if (_dirtyTopologySubmeshes.Count == 0 || _device is null)
        {
            return;
        }
        var requested = _dirtyTopologySubmeshes
            .Where(index => index >= 0)
            .Order()
            .ToArray();
        if (requested.Length == 0)
        {
            _dirtyTopologySubmeshes.Clear();
            return;
        }
        var affected = requested
            .Where(index => index >= 0 && index < _document.Submeshes.Count)
            .ToArray();
        var nextGeneration = _topologyGeneration + 1;
        var replacements = new List<D3D11SubmeshBatch>(affected.Length);
        try
        {
            foreach (var submeshIndex in affected)
            {
                var batch = BuildBatch(
                    submeshIndex,
                    _document.Submeshes[submeshIndex],
                    nextGeneration,
                    MaterialSourceFor(submeshIndex));
                if (batch is not null)
                {
                    replacements.Add(batch);
                }
            }
        }
        catch
        {
            foreach (var batch in replacements)
            {
                DisposeBatch(batch);
            }
            PruneTextureCacheToActiveBindings();
            throw;
        }
        var replaced = requested.ToHashSet();
        var oldBatches = _batches.Where(batch =>
            replaced.Contains(batch.SubmeshIndex) || batch.SubmeshIndex >= _document.Submeshes.Count).ToArray();
        _peakGeometryRebuildBytesEstimate = Math.Max(
            _peakGeometryRebuildBytesEstimate,
            _residentGeometryBytes + replacements.Sum(batch => batch.GeometryBytes));
        UnbindGeometryResources();
        foreach (var batch in oldBatches)
        {
            _batches.Remove(batch);
            DisposeBatch(batch);
        }
        _batches.AddRange(replacements);
        _batches.Sort((left, right) => left.SubmeshIndex.CompareTo(right.SubmeshIndex));
        foreach (var batch in _batches)
        {
            batch.AdvanceTopologyGeneration(nextGeneration);
        }
        _residentGeometryBytes = _batches.Sum(batch => batch.GeometryBytes);
        _peakResidentGeometryBytes = Math.Max(_peakResidentGeometryBytes, _residentGeometryBytes);
        _topologyGeneration = nextGeneration;
        _partialTopologyRebuildCount++;
        _topologyBatchesRebuilt += affected.Length;
        _dirtyTopologySubmeshes.Clear();
        PruneTextureCacheToActiveBindings();
    }

    private int MaterialSourceFor(int submeshIndex)
    {
        return _materialSourceBySubmesh.TryGetValue(submeshIndex, out var source) ? source : submeshIndex;
    }

    private unsafe D3D11SubmeshBatch? BuildBatch(
        int submeshIndex,
        ObjSubmesh submesh,
        long topologyGeneration,
        int materialSubmeshIndex)
    {
        if (_device is null)
        {
            return null;
        }
        var renderFaces = submesh.Faces.Where(face => IsRenderableTriangle(submesh, face)).ToArray();
        if (renderFaces.Length == 0)
        {
            return null;
        }
        var renderVertexCount = checked(renderFaces.Length * 3);
        var vertices = new D3D11MaterialVertex[renderVertexCount];
        var indices = new int[renderVertexCount];
        for (var faceIndex = 0; faceIndex < renderFaces.Length; faceIndex++)
        {
            var renderStart = faceIndex * 3;
            var face = renderFaces[faceIndex];
            WriteFaceVertices(submesh, face, vertices.AsSpan(renderStart, 3));
            for (var cornerIndex = 0; cornerIndex < 3; cornerIndex++)
            {
                var renderCorner = renderStart + cornerIndex;
                indices[renderCorner] = renderCorner;
            }
        }
        var sourceVertexToRenderCorners = D3D11SourceVertexToRenderCorners.Build(
            submesh.Vertices.Count,
            renderFaces);
        ID3D11Buffer? vertexBuffer = null;
        ID3D11Buffer? indexBuffer = null;
        try
        {
            fixed (D3D11MaterialVertex* vertexPtr = vertices)
            fixed (int* indexPtr = indices)
            {
                vertexBuffer = _device.CreateBuffer(
                    new BufferDescription(checked((uint)(vertices.Length * D3D11SubmeshBatch.VertexStride)), BindFlags.VertexBuffer),
                    new SubresourceData((IntPtr)vertexPtr));
                _vertexBufferCreateCount++;
                indexBuffer = _device.CreateBuffer(
                    new BufferDescription(checked((uint)(indices.Length * sizeof(int))), BindFlags.IndexBuffer),
                    new SubresourceData((IntPtr)indexPtr));
                _indexBufferCreateCount++;
            }
            return new D3D11SubmeshBatch(
                submeshIndex,
                materialSubmeshIndex,
                topologyGeneration,
                vertexBuffer,
                indexBuffer,
                indices.Length,
                renderFaces,
                sourceVertexToRenderCorners,
                CreateMaterialResources(materialSubmeshIndex));
        }
        catch
        {
            indexBuffer?.Dispose();
            vertexBuffer?.Dispose();
            _bufferDisposeCount += (indexBuffer is null ? 0 : 1) + (vertexBuffer is null ? 0 : 1);
            throw;
        }
    }

    private void ApplyPendingVertexUpdates()
    {
        if (!_vertexDataDirty || _context is null)
        {
            return;
        }
        long uploaded = 0;
        long patchedSources = 0;
        var dirtySubmeshes = _dirtyVerticesBySubmesh.Keys
            .Concat(_dirtyNormalsBySubmesh.Keys)
            .Concat(_dirtyUvsBySubmesh.Keys)
            .Distinct()
            .ToArray();
        foreach (var submeshIndex in dirtySubmeshes)
        {
            var batch = _batches.FirstOrDefault(candidate => candidate.SubmeshIndex == submeshIndex);
            if (batch is null)
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            if (batch.TopologyGeneration != _topologyGeneration
                || batch.SourceVertexToRenderCorners.SourceVertexCount != submesh.Vertices.Count)
            {
                _geometryDirty = true;
                break;
            }
            var dirtyVertices = _dirtyVerticesBySubmesh.GetValueOrDefault(submeshIndex) ?? [];
            var dirtyNormals = _dirtyNormalsBySubmesh.GetValueOrDefault(submeshIndex) ?? [];
            var dirtyUvs = _dirtyUvsBySubmesh.GetValueOrDefault(submeshIndex) ?? [];
            patchedSources += dirtyVertices.Concat(dirtyNormals).Concat(dirtyUvs).Distinct().Count();
            uploaded += PatchBatchVertexRanges(batch, submesh, dirtyVertices, dirtyNormals, dirtyUvs);
        }
        DiscardPendingVertexUpdates();
        if (_geometryDirty)
        {
            RebuildGeometry();
            return;
        }
        if (patchedSources > 0)
        {
            _sparseVertexUpdateCount++;
            _sourceVerticesPatched += patchedSources;
            _renderVerticesUploaded += uploaded;
        }
    }

    private int PatchBatchVertexRanges(
        D3D11SubmeshBatch batch,
        ObjSubmesh submesh,
        IEnumerable<int> dirtyVertices,
        IEnumerable<int> dirtyNormals,
        IEnumerable<int> dirtyUvs)
    {
        var dirtyFaces = new SortedSet<int>();
        AddDirtyFaces(dirtyFaces, batch.SourceVertexToRenderCorners, dirtyVertices);
        AddDirtyFaces(dirtyFaces, batch.SourceVertexToRenderCorners, dirtyNormals);
        AddDirtyFaces(dirtyFaces, batch.SourceVertexToRenderCorners, dirtyUvs);
        var uploaded = 0;
        using var enumerator = dirtyFaces.GetEnumerator();
        if (!enumerator.MoveNext())
        {
            return uploaded;
        }
        var rangeStart = enumerator.Current;
        var rangeEnd = rangeStart;
        while (enumerator.MoveNext())
        {
            if (enumerator.Current == rangeEnd + 1)
            {
                rangeEnd = enumerator.Current;
                continue;
            }
            uploaded += UploadFaceRange(batch, submesh, rangeStart, rangeEnd);
            rangeStart = rangeEnd = enumerator.Current;
        }
        return uploaded + UploadFaceRange(batch, submesh, rangeStart, rangeEnd);
    }

    private static void AddDirtyFaces(
        ISet<int> dirtyFaces,
        D3D11SourceVertexToRenderCorners mapping,
        IEnumerable<int> dirtySources)
    {
        foreach (var sourceIndex in dirtySources)
        {
            foreach (var renderCorner in mapping.CornersFor(sourceIndex))
            {
                dirtyFaces.Add(renderCorner / 3);
            }
        }
    }

    private void DisposeBatch(D3D11SubmeshBatch batch)
    {
        _bufferDisposeCount += 2;
        _maxDisposedGeometryResourceLifetimeMs = Math.Max(
            _maxDisposedGeometryResourceLifetimeMs,
            ElapsedMilliseconds(batch.CreatedTimestamp));
        batch.Dispose();
    }

    private static bool IsRenderableTriangle(ObjSubmesh submesh, ObjFace face)
    {
        return face.Corners.Length == 3
            && face.Corners.All(corner => corner.VertexIndex >= 0 && corner.VertexIndex < submesh.Vertices.Count);
    }

    private static void WriteFaceVertices(ObjSubmesh submesh, ObjFace face, Span<D3D11MaterialVertex> destination)
    {
        var normal = FaceNormal(submesh, face);
        var tangentSpace = FaceTangentSpace(submesh, face, normal);
        for (var cornerIndex = 0; cornerIndex < 3; cornerIndex++)
        {
            var corner = face.Corners[cornerIndex];
            var position = submesh.Vertices[corner.VertexIndex];
            var cornerNormal = NormalForCorner(submesh, corner, normal);
            var uv = corner.UvIndex >= 0 && corner.UvIndex < submesh.Uvs.Count ? submesh.Uvs[corner.UvIndex] : new Vec2(0, 0);
            destination[cornerIndex] = new D3D11MaterialVertex(
                new Vector3(position.X, position.Y, position.Z),
                new Vector3((float)cornerNormal.X, (float)cornerNormal.Y, (float)cornerNormal.Z),
                new Vector3((float)tangentSpace.Tangent.X, (float)tangentSpace.Tangent.Y, (float)tangentSpace.Tangent.Z),
                new Vector3((float)tangentSpace.Bitangent.X, (float)tangentSpace.Bitangent.Y, (float)tangentSpace.Bitangent.Z),
                new Vector2(uv.U, 1.0f - uv.V));
        }
    }

    private int UploadFaceRange(D3D11SubmeshBatch batch, ObjSubmesh submesh, int firstFace, int lastFace)
    {
        if (_context is null)
        {
            return 0;
        }
        var firstRenderVertex = checked(firstFace * 3);
        var renderVertexCount = checked((lastFace - firstFace + 1) * 3);
        var rented = ArrayPool<D3D11MaterialVertex>.Shared.Rent(renderVertexCount);
        try
        {
            var destination = rented.AsSpan(0, renderVertexCount);
            for (var faceIndex = firstFace; faceIndex <= lastFace; faceIndex++)
            {
                WriteFaceVertices(submesh, batch.RenderFaces[faceIndex], destination.Slice((faceIndex - firstFace) * 3, 3));
            }
            var byteStart = checked(firstRenderVertex * (int)D3D11SubmeshBatch.VertexStride);
            var byteEnd = checked(byteStart + renderVertexCount * (int)D3D11SubmeshBatch.VertexStride);
            _context.UpdateSubresource(
                destination,
                batch.VertexBuffer,
                0,
                0,
                0,
                new Box(byteStart, 0, 0, byteEnd, 1, 1));
            _vertexPatchRangeCount++;
            return renderVertexCount;
        }
        finally
        {
            ArrayPool<D3D11MaterialVertex>.Shared.Return(rented);
        }
    }

    private static System.Windows.Media.Media3D.Vector3D NormalForCorner(ObjSubmesh submesh, ObjCorner corner, System.Windows.Media.Media3D.Vector3D fallback)
    {
        if (corner.NormalIndex >= 0 && corner.NormalIndex < submesh.Normals.Count)
        {
            var normal = submesh.Normals[corner.NormalIndex];
            var vector = new System.Windows.Media.Media3D.Vector3D(normal.X, normal.Y, normal.Z);
            if (vector.LengthSquared > 0.0001)
            {
                vector.Normalize();
                return vector;
            }
        }
        return fallback;
    }

    private static (System.Windows.Media.Media3D.Vector3D Tangent, System.Windows.Media.Media3D.Vector3D Bitangent) FaceTangentSpace(ObjSubmesh submesh, ObjFace face, System.Windows.Media.Media3D.Vector3D normal)
    {
        if (face.Corners.Any(corner => corner.UvIndex < 0 || corner.UvIndex >= submesh.Uvs.Count))
        {
            return FallbackTangentSpace(normal);
        }
        var p0 = submesh.Vertices[face.Corners[0].VertexIndex];
        var p1 = submesh.Vertices[face.Corners[1].VertexIndex];
        var p2 = submesh.Vertices[face.Corners[2].VertexIndex];
        var uv0 = submesh.Uvs[face.Corners[0].UvIndex];
        var uv1 = submesh.Uvs[face.Corners[1].UvIndex];
        var uv2 = submesh.Uvs[face.Corners[2].UvIndex];
        var edge1 = new System.Windows.Media.Media3D.Vector3D(p1.X - p0.X, p1.Y - p0.Y, p1.Z - p0.Z);
        var edge2 = new System.Windows.Media.Media3D.Vector3D(p2.X - p0.X, p2.Y - p0.Y, p2.Z - p0.Z);
        var du1 = uv1.U - uv0.U;
        var dv1 = uv1.V - uv0.V;
        var du2 = uv2.U - uv0.U;
        var dv2 = uv2.V - uv0.V;
        var determinant = (du1 * dv2) - (du2 * dv1);
        if (Math.Abs(determinant) < 0.000001)
        {
            return FallbackTangentSpace(normal);
        }
        var scale = 1.0 / determinant;
        var tangent = (edge1 * dv2 - edge2 * dv1) * scale;
        var bitangent = (edge2 * du1 - edge1 * du2) * scale;
        tangent.Normalize();
        bitangent.Normalize();
        return (tangent, bitangent);
    }

    private static (System.Windows.Media.Media3D.Vector3D Tangent, System.Windows.Media.Media3D.Vector3D Bitangent) FallbackTangentSpace(System.Windows.Media.Media3D.Vector3D normal)
    {
        var tangent = System.Windows.Media.Media3D.Vector3D.CrossProduct(normal, Math.Abs(normal.Y) < 0.95 ? new System.Windows.Media.Media3D.Vector3D(0, 1, 0) : new System.Windows.Media.Media3D.Vector3D(1, 0, 0));
        if (tangent.LengthSquared < 0.0001)
        {
            tangent = new System.Windows.Media.Media3D.Vector3D(1, 0, 0);
        }
        tangent.Normalize();
        var bitangent = System.Windows.Media.Media3D.Vector3D.CrossProduct(normal, tangent);
        bitangent.Normalize();
        return (tangent, bitangent);
    }

    private static System.Windows.Media.Media3D.Vector3D FaceNormal(ObjSubmesh submesh, ObjFace face)
    {
        var a = submesh.Vertices[face.Corners[0].VertexIndex];
        var b = submesh.Vertices[face.Corners[1].VertexIndex];
        var c = submesh.Vertices[face.Corners[2].VertexIndex];
        var ab = new System.Windows.Media.Media3D.Vector3D(b.X - a.X, b.Y - a.Y, b.Z - a.Z);
        var ac = new System.Windows.Media.Media3D.Vector3D(c.X - a.X, c.Y - a.Y, c.Z - a.Z);
        var normal = System.Windows.Media.Media3D.Vector3D.CrossProduct(ab, ac);
        if (normal.LengthSquared < 0.0001)
        {
            return new System.Windows.Media.Media3D.Vector3D(0, 1, 0);
        }
        normal.Normalize();
        return normal;
    }

    private static double ElapsedMilliseconds(long startedTimestamp)
    {
        return Math.Max(0.0, (Stopwatch.GetTimestamp() - startedTimestamp) * 1000.0 / Stopwatch.Frequency);
    }
}

internal sealed class D3D11SourceVertexToRenderCorners
{
    private readonly int[] _offsets;
    private readonly int[] _renderCorners;

    private D3D11SourceVertexToRenderCorners(int[] offsets, int[] renderCorners)
    {
        _offsets = offsets;
        _renderCorners = renderCorners;
    }

    public int SourceVertexCount => _offsets.Length - 1;
    public long EstimatedBytes => checked((long)(_offsets.Length + _renderCorners.Length) * sizeof(int));

    public ReadOnlySpan<int> CornersFor(int sourceVertex)
    {
        return _renderCorners.AsSpan(
            _offsets[sourceVertex],
            _offsets[sourceVertex + 1] - _offsets[sourceVertex]);
    }

    public static D3D11SourceVertexToRenderCorners Build(int sourceVertexCount, IReadOnlyList<ObjFace> renderFaces)
    {
        var offsets = new int[checked(sourceVertexCount + 1)];
        foreach (var face in renderFaces)
        {
            foreach (var corner in face.Corners)
            {
                offsets[corner.VertexIndex + 1] = checked(offsets[corner.VertexIndex + 1] + 1);
            }
        }
        for (var sourceVertex = 1; sourceVertex < offsets.Length; sourceVertex++)
        {
            offsets[sourceVertex] = checked(offsets[sourceVertex] + offsets[sourceVertex - 1]);
        }
        var next = offsets.AsSpan(0, sourceVertexCount).ToArray();
        var renderCorners = new int[checked(renderFaces.Count * 3)];
        for (var faceIndex = 0; faceIndex < renderFaces.Count; faceIndex++)
        {
            for (var cornerIndex = 0; cornerIndex < 3; cornerIndex++)
            {
                var sourceVertex = renderFaces[faceIndex].Corners[cornerIndex].VertexIndex;
                renderCorners[next[sourceVertex]++] = checked(faceIndex * 3 + cornerIndex);
            }
        }
        return new D3D11SourceVertexToRenderCorners(offsets, renderCorners);
    }
}

internal sealed class D3D11SubmeshBatch : IDisposable
{
    public static readonly uint VertexStride = (uint)Marshal.SizeOf<D3D11MaterialVertex>();

    public D3D11SubmeshBatch(
        int submeshIndex,
        int materialSubmeshIndex,
        long topologyGeneration,
        ID3D11Buffer vertexBuffer,
        ID3D11Buffer indexBuffer,
        int indexCount,
        ObjFace[] renderFaces,
        D3D11SourceVertexToRenderCorners sourceVertexToRenderCorners,
        D3D11MaterialResources materials)
    {
        SubmeshIndex = submeshIndex;
        MaterialSubmeshIndex = materialSubmeshIndex;
        TopologyGeneration = topologyGeneration;
        VertexBuffer = vertexBuffer;
        IndexBuffer = indexBuffer;
        IndexCount = indexCount;
        RenderFaces = renderFaces;
        SourceVertexToRenderCorners = sourceVertexToRenderCorners;
        Materials = materials;
        CreatedTimestamp = Stopwatch.GetTimestamp();
        GeometryBytes = checked((long)indexCount * (VertexStride + sizeof(int)));
    }

    public int SubmeshIndex { get; }
    public int MaterialSubmeshIndex { get; }
    public long TopologyGeneration { get; private set; }
    public ID3D11Buffer VertexBuffer { get; }
    public ID3D11Buffer IndexBuffer { get; }
    public int IndexCount { get; }
    public ObjFace[] RenderFaces { get; }
    public D3D11SourceVertexToRenderCorners SourceVertexToRenderCorners { get; }
    public D3D11MaterialResources Materials { get; set; }
    public long CreatedTimestamp { get; }
    public long GeometryBytes { get; }

    public void AdvanceTopologyGeneration(long generation)
    {
        TopologyGeneration = generation;
    }

    public void Dispose()
    {
        Materials.Dispose();
        IndexBuffer.Dispose();
        VertexBuffer.Dispose();
    }
}
