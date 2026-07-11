namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private SparseMeshBoundsTracker? _sparseBounds;
    private SparseMeshBoundsTracker SparseBounds => _sparseBounds ??= new SparseMeshBoundsTracker(_document);

    private void ApplySparseBounds()
    {
        _bounds = SparseBounds.Bounds;
        _center = SparseBounds.Center;
    }
}

internal sealed class SparseMeshBoundsTracker
{
    private readonly ObjDocument _document;
    private readonly MeshVertexLocation?[] _extremaOwners = new MeshVertexLocation?[6];

    public SparseMeshBoundsTracker(ObjDocument document)
    {
        _document = document;
        Bounds = (new Vec3(-1, -1, -1), new Vec3(1, 1, 1));
        Center = new Vec3(0, 0, 0);
    }

    public (Vec3 Min, Vec3 Max) Bounds { get; private set; }
    public Vec3 Center { get; private set; }
    public long ExactRebaseCount { get; private set; }
    public long SparseUpdateCount { get; private set; }
    public long BoundaryTriggeredRebaseCount { get; private set; }

    public void Rebase()
    {
        Array.Clear(_extremaOwners);
        var found = false;
        var min = new Vec3(-1, -1, -1);
        var max = new Vec3(1, 1, 1);
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            var vertices = _document.Submeshes[submeshIndex].Vertices;
            for (var vertexIndex = 0; vertexIndex < vertices.Count; vertexIndex++)
            {
                var vertex = vertices[vertexIndex];
                var location = new MeshVertexLocation(submeshIndex, vertexIndex);
                if (!found)
                {
                    min = max = vertex;
                    for (var axis = 0; axis < _extremaOwners.Length; axis++)
                    {
                        _extremaOwners[axis] = location;
                    }
                    found = true;
                    continue;
                }
                Expand(ref min, ref max, vertex, location);
            }
        }
        Bounds = (min, max);
        Center = BoundsCenter(min, max);
        ExactRebaseCount++;
    }

    public bool Update(IReadOnlyDictionary<int, IReadOnlyCollection<int>> changedVertices)
    {
        SparseUpdateCount++;
        if (TouchesExtremumOwner(changedVertices))
        {
            BoundaryTriggeredRebaseCount++;
            Rebase();
            return true;
        }
        var min = Bounds.Min;
        var max = Bounds.Max;
        foreach (var (submeshIndex, indices) in changedVertices)
        {
            if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var vertices = _document.Submeshes[submeshIndex].Vertices;
            foreach (var vertexIndex in indices)
            {
                if (vertexIndex < 0 || vertexIndex >= vertices.Count)
                {
                    continue;
                }
                Expand(ref min, ref max, vertices[vertexIndex], new MeshVertexLocation(submeshIndex, vertexIndex));
            }
        }
        Bounds = (min, max);
        Center = BoundsCenter(min, max);
        return false;
    }

    private bool TouchesExtremumOwner(IReadOnlyDictionary<int, IReadOnlyCollection<int>> changedVertices)
    {
        foreach (var owner in _extremaOwners)
        {
            if (owner is { } location
                && changedVertices.TryGetValue(location.SubmeshIndex, out var changed)
                && changed.Contains(location.VertexIndex))
            {
                return true;
            }
        }
        return false;
    }

    private void Expand(ref Vec3 min, ref Vec3 max, Vec3 vertex, MeshVertexLocation owner)
    {
        if (vertex.X < min.X) { min = min with { X = vertex.X }; _extremaOwners[0] = owner; }
        if (vertex.Y < min.Y) { min = min with { Y = vertex.Y }; _extremaOwners[1] = owner; }
        if (vertex.Z < min.Z) { min = min with { Z = vertex.Z }; _extremaOwners[2] = owner; }
        if (vertex.X > max.X) { max = max with { X = vertex.X }; _extremaOwners[3] = owner; }
        if (vertex.Y > max.Y) { max = max with { Y = vertex.Y }; _extremaOwners[4] = owner; }
        if (vertex.Z > max.Z) { max = max with { Z = vertex.Z }; _extremaOwners[5] = owner; }
    }

    private static Vec3 BoundsCenter(Vec3 min, Vec3 max)
    {
        return new Vec3(
            (min.X + max.X) * 0.5f,
            (min.Y + max.Y) * 0.5f,
            (min.Z + max.Z) * 0.5f);
    }
}

internal readonly record struct MeshVertexLocation(int SubmeshIndex, int VertexIndex);
