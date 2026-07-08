namespace Cdmw.MeshEditorExperiment;

internal sealed class NetEdge
{
    public NetEdge(int id, int submeshIndex, int vertexA, int vertexB, int sourceVertexA, int sourceVertexB)
    {
        Id = id;
        SubmeshIndex = submeshIndex;
        VertexA = vertexA;
        VertexB = vertexB;
        SourceVertexA = Math.Min(sourceVertexA, sourceVertexB);
        SourceVertexB = Math.Max(sourceVertexA, sourceVertexB);
        StableKey = $"submesh:{submeshIndex}|source_vertices:{SourceVertexA}:{SourceVertexB}";
    }

    public int Id { get; }
    public int SubmeshIndex { get; }
    public int VertexA { get; }
    public int VertexB { get; }
    public int SourceVertexA { get; }
    public int SourceVertexB { get; }
    public string StableKey { get; }
    public List<int> AdjacentFaces { get; } = new();
    public bool IsBoundary => AdjacentFaces.Count <= 1;

    public Dictionary<string, object?> ToDescriptorPayload(int topologyGeneration)
    {
        return new Dictionary<string, object?>
        {
            ["id"] = Id,
            ["stable_key"] = StableKey,
            ["native_edge_identifier"] = StableKey,
            ["topology_generation"] = topologyGeneration,
            ["source_submesh_index"] = SubmeshIndex,
            ["submesh_index"] = SubmeshIndex,
            ["vertex_a"] = VertexA,
            ["vertex_b"] = VertexB,
            ["source_vertex_a"] = SourceVertexA,
            ["source_vertex_b"] = SourceVertexB,
            ["source_vertex_pair"] = new[] { SourceVertexA, SourceVertexB },
            ["adjacent_faces"] = AdjacentFaces.OrderBy(value => value).ToArray(),
            ["boundary"] = IsBoundary,
        };
    }
}

internal sealed class NetEdgeTopology
{
    public static NetEdgeTopology Empty { get; } = new(Array.Empty<NetEdge>(), 0);

    private readonly Dictionary<int, NetEdge> _edgesById;
    private readonly Dictionary<string, NetEdge> _edgesByStableKey;

    private NetEdgeTopology(IEnumerable<NetEdge> edges, int generation)
    {
        Edges = edges.ToArray();
        Generation = generation;
        _edgesById = Edges.ToDictionary(edge => edge.Id);
        _edgesByStableKey = Edges.ToDictionary(edge => edge.StableKey, StringComparer.OrdinalIgnoreCase);
    }

    public IReadOnlyList<NetEdge> Edges { get; }
    public int Generation { get; }

    public bool Contains(int edgeId)
    {
        return edgeId >= 0 && _edgesById.ContainsKey(edgeId);
    }

    public NetEdge? EdgeById(int edgeId)
    {
        return _edgesById.TryGetValue(edgeId, out var edge) ? edge : null;
    }

    public NetEdge? EdgeByStableKey(string stableKey)
    {
        return !string.IsNullOrWhiteSpace(stableKey) && _edgesByStableKey.TryGetValue(stableKey, out var edge) ? edge : null;
    }

    public NetEdge? EdgeByVertices(int submeshIndex, int vertexA, int vertexB)
    {
        var a = Math.Min(vertexA, vertexB);
        var b = Math.Max(vertexA, vertexB);
        return Edges.FirstOrDefault(edge => edge.SubmeshIndex == submeshIndex && edge.VertexA == a && edge.VertexB == b);
    }

    public static NetEdgeTopology Build(ObjDocument document, int generation = 1)
    {
        var edges = new List<NetEdge>();
        var lookup = new Dictionary<(int SubmeshIndex, int A, int B), NetEdge>();
        var nextId = 0;
        for (var submeshIndex = 0; submeshIndex < document.Submeshes.Count; submeshIndex++)
        {
            var submesh = document.Submeshes[submeshIndex];
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                var face = submesh.Faces[faceIndex];
                if (face.Corners.Length != 3)
                {
                    continue;
                }
                AddFaceEdge(submeshIndex, faceIndex, submesh.VertexStart, face.Corners[0].VertexIndex, face.Corners[1].VertexIndex, edges, lookup, ref nextId);
                AddFaceEdge(submeshIndex, faceIndex, submesh.VertexStart, face.Corners[1].VertexIndex, face.Corners[2].VertexIndex, edges, lookup, ref nextId);
                AddFaceEdge(submeshIndex, faceIndex, submesh.VertexStart, face.Corners[2].VertexIndex, face.Corners[0].VertexIndex, edges, lookup, ref nextId);
            }
        }
        return new NetEdgeTopology(edges, generation);
    }

    private static void AddFaceEdge(
        int submeshIndex,
        int faceIndex,
        int sourceVertexOffset,
        int vertexA,
        int vertexB,
        List<NetEdge> edges,
        Dictionary<(int SubmeshIndex, int A, int B), NetEdge> lookup,
        ref int nextId)
    {
        if (vertexA < 0 || vertexB < 0 || vertexA == vertexB)
        {
            return;
        }
        var a = Math.Min(vertexA, vertexB);
        var b = Math.Max(vertexA, vertexB);
        var key = (submeshIndex, a, b);
        if (!lookup.TryGetValue(key, out var edge))
        {
            edge = new NetEdge(nextId++, submeshIndex, a, b, sourceVertexA: sourceVertexOffset + a, sourceVertexB: sourceVertexOffset + b);
            lookup[key] = edge;
            edges.Add(edge);
        }
        edge.AdjacentFaces.Add(faceIndex);
    }
}
