namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private IReadOnlyList<NativeMeshSubmeshData> ResidentNativeSubmeshes()
    {
        var values = new List<NativeMeshSubmeshData>(_document.Submeshes.Count);
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            var submesh = _document.Submeshes[submeshIndex];
            var positions = new double[submesh.Vertices.Count * 3];
            for (var index = 0; index < submesh.Vertices.Count; index++)
            {
                positions[index * 3] = submesh.Vertices[index].X;
                positions[index * 3 + 1] = submesh.Vertices[index].Y;
                positions[index * 3 + 2] = submesh.Vertices[index].Z;
            }
            double[]? normals = null;
            if (submesh.NormalsVertexAligned && submesh.Normals.Count == submesh.Vertices.Count)
            {
                normals = new double[submesh.Normals.Count * 3];
                for (var index = 0; index < submesh.Normals.Count; index++)
                {
                    normals[index * 3] = submesh.Normals[index].X;
                    normals[index * 3 + 1] = submesh.Normals[index].Y;
                    normals[index * 3 + 2] = submesh.Normals[index].Z;
                }
            }
            values.Add(new NativeMeshSubmeshData(
                submeshIndex,
                positions,
                normals,
                ResidentNativeTriangleIndices(submesh)));
        }
        return values;
    }

    private static uint[] ResidentNativeTriangleIndices(ObjSubmesh submesh)
    {
        var triangles = new List<uint>(submesh.Faces.Count * 3);
        foreach (var face in submesh.Faces)
        {
            if (face.Corners.Length < 3)
            {
                continue;
            }
            var first = face.Corners[0].VertexIndex;
            for (var corner = 1; corner + 1 < face.Corners.Length; corner++)
            {
                var second = face.Corners[corner].VertexIndex;
                var third = face.Corners[corner + 1].VertexIndex;
                if (first >= 0 && second >= 0 && third >= 0)
                {
                    triangles.Add(checked((uint)first));
                    triangles.Add(checked((uint)second));
                    triangles.Add(checked((uint)third));
                }
            }
        }
        return triangles.ToArray();
    }

    private IReadOnlyList<NativeMeshSelectionData> ResidentNativeSelections(bool expandSelectedParts)
    {
        var values = new List<NativeMeshSelectionData>();
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            var vertices = _selectedVertices.TryGetValue(submeshIndex, out var selectedVertices)
                ? new HashSet<int>(selectedVertices)
                : new HashSet<int>();
            if (expandSelectedParts && _selectedSources.Contains(submeshIndex))
            {
                vertices.UnionWith(Enumerable.Range(0, _document.Submeshes[submeshIndex].Vertices.Count));
            }
            var faces = _selectedFaces.TryGetValue(submeshIndex, out var selectedFaces)
                ? selectedFaces.Order().Select(checkedIndex => checked((uint)checkedIndex)).ToArray()
                : [];
            var edgePairs = _selectedEdges
                .Select(edgeId => _edgeTopology.EdgeById(edgeId))
                .Where(edge => edge is not null && edge.SubmeshIndex == submeshIndex)
                .SelectMany(edge => new[] { checked((uint)edge!.VertexA), checked((uint)edge.VertexB) })
                .ToArray();
            if (vertices.Count == 0 && faces.Length == 0 && edgePairs.Length == 0)
            {
                continue;
            }
            values.Add(new NativeMeshSelectionData(
                submeshIndex,
                vertices.Order().Select(index => checked((uint)index)).ToArray(),
                faces,
                edgePairs));
        }
        return values;
    }

    private NativeMeshProjectionData[] ResidentNativeProjections(NetViewportCamera camera) =>
        VisibleEditableSubmeshIndices()
            .Select(submeshIndex => new NativeMeshProjectionData(
                submeshIndex,
                MatrixRowMajorArray(
                    ActiveSceneModelMatrix(submeshIndex) * camera.WorldViewProjection)))
            .ToArray();

    private static bool ResidentNativeProjectionsEqual(
        IReadOnlyList<NativeMeshProjectionData> left,
        IReadOnlyList<NativeMeshProjectionData> right)
    {
        if (left.Count != right.Count)
        {
            return false;
        }
        for (var index = 0; index < left.Count; ++index)
        {
            if (left[index].SubmeshIndex != right[index].SubmeshIndex
                || !left[index].WorldViewProjection.SequenceEqual(
                    right[index].WorldViewProjection))
            {
                return false;
            }
        }
        return true;
    }
}
