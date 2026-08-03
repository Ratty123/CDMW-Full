using System.Numerics;
using Vortice.Mathematics;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// Renderer-local geometry used only while a pointer stroke is in progress.
/// MeshService remains authoritative: the resident document and its revision
/// are never changed here, and ending the provisional state uploads the latest
/// authoritative resident vertices back into every touched range.
/// </summary>
internal sealed partial class D3D11MaterialViewport
{
    private readonly Dictionary<int, Vector3> _provisionalPartTranslations = new();

    public void BeginProvisionalPartTransforms(IEnumerable<int> submeshIndices)
    {
        var requested = submeshIndices.ToArray();
        _provisionalPartTranslations.Clear();
        foreach (var submeshIndex in requested)
        {
            if (submeshIndex >= 0 && submeshIndex < _scene.EditableSubmeshCount)
            {
                _provisionalPartTranslations[submeshIndex] = Vector3.Zero;
            }
        }
        // Freeze the resident vertex buffer at the stroke baseline while
        // authoritative updates land in the document behind it. Otherwise the
        // transient transform would be applied on top of already-moved
        // vertices and visibly double every acknowledged delta.
        BeginProvisionalVertexGeometry(requested);
        Invalidate();
    }

    public void UpdateProvisionalPartTranslation(int submeshIndex, Vector3 translation)
    {
        if (!_provisionalPartTranslations.ContainsKey(submeshIndex))
        {
            return;
        }
        _provisionalPartTranslations[submeshIndex] = translation;
        Invalidate();
    }

    public void BeginProvisionalVertexGeometry(IEnumerable<int> submeshIndices)
    {
        var requested = submeshIndices.ToHashSet();
        foreach (var batch in _batches)
        {
            if (requested.Contains(batch.SubmeshIndex)
                && batch.SubmeshIndex < _scene.EditableSubmeshCount)
            {
                batch.ProvisionalGeometry = new D3D11ProvisionalBatchGeometry(
                    batch.ResidentVertices,
                    batch.RenderFaces.Length);
            }
        }
    }

    public void UpdateProvisionalVertexPositions(
        int submeshIndex,
        IReadOnlyList<Vec3> positions,
        int[] changedSourceIndices,
        int changedCount)
    {
        if (_context is null || changedCount <= 0)
        {
            return;
        }
        D3D11SubmeshBatch? batch = null;
        foreach (var candidate in _batches)
        {
            if (candidate.SubmeshIndex == submeshIndex)
            {
                batch = candidate;
                break;
            }
        }
        var state = batch?.ProvisionalGeometry;
        if (batch is null || state is null)
        {
            return;
        }
        state.BeginFrame();
        var limit = Math.Min(changedCount, changedSourceIndices.Length);
        for (var itemIndex = 0; itemIndex < limit; itemIndex++)
        {
            var sourceIndex = changedSourceIndices[itemIndex];
            if (sourceIndex < 0 || sourceIndex >= positions.Count)
            {
                continue;
            }
            var position = positions[sourceIndex];
            foreach (var renderCorner in batch.SourceVertexToRenderCorners.CornersFor(sourceIndex))
            {
                state.Vertices[renderCorner] = state.Vertices[renderCorner] with
                {
                    Position = new Vector3(position.X, position.Y, position.Z),
                };
                state.MarkFace(renderCorner / 3);
            }
        }
        UploadProvisionalFrame(batch, state);
        Invalidate();
    }

    public void ClearProvisionalGeometry(bool uploadAuthoritative = true)
    {
        _provisionalPartTranslations.Clear();
        foreach (var batch in _batches)
        {
            var state = batch.ProvisionalGeometry;
            if (state is null)
            {
                continue;
            }
            if (uploadAuthoritative && _context is not null)
            {
                UploadTouchedAuthoritativeFaces(batch, state);
            }
            batch.ProvisionalGeometry = null;
        }
        Invalidate();
    }

    private void UploadProvisionalFrame(
        D3D11SubmeshBatch batch,
        D3D11ProvisionalBatchGeometry state)
    {
        if (_context is null || state.FrameFaceCount <= 0)
        {
            return;
        }
        Array.Sort(state.FrameFaces, 0, state.FrameFaceCount);
        var rangeStart = state.FrameFaces[0];
        var rangeEnd = rangeStart;
        for (var index = 1; index < state.FrameFaceCount; index++)
        {
            var face = state.FrameFaces[index];
            if (face == rangeEnd + 1)
            {
                rangeEnd = face;
                continue;
            }
            UploadProvisionalFaceRange(batch, state.Vertices, rangeStart, rangeEnd);
            rangeStart = rangeEnd = face;
        }
        UploadProvisionalFaceRange(batch, state.Vertices, rangeStart, rangeEnd);
    }

    private void UploadTouchedAuthoritativeFaces(
        D3D11SubmeshBatch batch,
        D3D11ProvisionalBatchGeometry state)
    {
        var rangeStart = -1;
        for (var face = 0; face <= state.TouchedFaces.Length; face++)
        {
            var touched = face < state.TouchedFaces.Length && state.TouchedFaces[face];
            if (touched && rangeStart < 0)
            {
                rangeStart = face;
                continue;
            }
            if (touched || rangeStart < 0)
            {
                continue;
            }
            UploadProvisionalFaceRange(batch, batch.ResidentVertices, rangeStart, face - 1);
            rangeStart = -1;
        }
    }

    private void UploadProvisionalFaceRange(
        D3D11SubmeshBatch batch,
        D3D11MaterialVertex[] vertices,
        int firstFace,
        int lastFace)
    {
        if (_context is null || firstFace < 0 || lastFace < firstFace)
        {
            return;
        }
        var firstRenderVertex = checked(firstFace * 3);
        var renderVertexCount = checked((lastFace - firstFace + 1) * 3);
        var byteStart = checked(firstRenderVertex * (int)D3D11SubmeshBatch.VertexStride);
        var byteEnd = checked(byteStart + renderVertexCount * (int)D3D11SubmeshBatch.VertexStride);
        _context.UpdateSubresource(
            vertices.AsSpan(firstRenderVertex, renderVertexCount),
            batch.VertexBuffer,
            0,
            0,
            0,
            new Box(byteStart, 0, 0, byteEnd, 1, 1));
        _vertexPatchRangeCount++;
    }

    private Matrix4x4 ApplyProvisionalPartTranslation(int submeshIndex, Matrix4x4 model)
    {
        if (submeshIndex >= _scene.EditableSubmeshCount
            || !_provisionalPartTranslations.TryGetValue(submeshIndex, out var translation))
        {
            return model;
        }
        return Matrix4x4.CreateTranslation(translation) * model;
    }
}

internal sealed class D3D11ProvisionalBatchGeometry
{
    private int _frameGeneration;
    private readonly int[] _frameMarks;

    public D3D11ProvisionalBatchGeometry(
        IReadOnlyCollection<D3D11MaterialVertex> residentVertices,
        int faceCount)
    {
        Vertices = residentVertices.ToArray();
        _frameMarks = new int[Math.Max(0, faceCount)];
        FrameFaces = new int[Math.Max(0, faceCount)];
        TouchedFaces = new bool[Math.Max(0, faceCount)];
    }

    public D3D11MaterialVertex[] Vertices { get; }
    public int[] FrameFaces { get; }
    public bool[] TouchedFaces { get; }
    public int FrameFaceCount { get; private set; }

    public void BeginFrame()
    {
        FrameFaceCount = 0;
        _frameGeneration++;
        if (_frameGeneration != int.MaxValue)
        {
            return;
        }
        Array.Clear(_frameMarks);
        _frameGeneration = 1;
    }

    public void MarkFace(int faceIndex)
    {
        if (faceIndex < 0 || faceIndex >= _frameMarks.Length)
        {
            return;
        }
        TouchedFaces[faceIndex] = true;
        if (_frameMarks[faceIndex] == _frameGeneration)
        {
            return;
        }
        _frameMarks[faceIndex] = _frameGeneration;
        FrameFaces[FrameFaceCount++] = faceIndex;
    }

    public void MarkAuthoritativeRange(int firstFace, int lastFace)
    {
        var start = Math.Max(0, firstFace);
        var end = Math.Min(TouchedFaces.Length - 1, lastFace);
        for (var face = start; face <= end; face++)
        {
            TouchedFaces[face] = true;
        }
    }
}
