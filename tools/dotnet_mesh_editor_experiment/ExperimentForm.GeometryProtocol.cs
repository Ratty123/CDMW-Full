using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private sealed record PreviewTriangleGroup(int SubmeshIndex, int MaterialSource, ObjSubmesh Submesh);
    internal sealed record PreviewVertexGroup(
        int SubmeshIndex,
        IReadOnlyList<int> Indices,
        IReadOnlyList<double> Positions,
        IReadOnlyList<double> Normals,
        IReadOnlyList<double> Uvs);

    internal static bool TryParsePreviewVertexGroups(
        ObjDocument document,
        JsonElement groups,
        out IReadOnlyList<PreviewVertexGroup> parsed)
    {
        var result = new List<PreviewVertexGroup>();
        foreach (var group in groups.EnumerateArray())
        {
            if (group.ValueKind != JsonValueKind.Object)
            {
                parsed = Array.Empty<PreviewVertexGroup>();
                return false;
            }
            var submeshIndex = JsonInt(group, "source_submesh_index", JsonInt(group, "index", -1));
            if (submeshIndex < 0 || submeshIndex >= document.Submeshes.Count)
            {
                parsed = Array.Empty<PreviewVertexGroup>();
                return false;
            }
            var submesh = document.Submeshes[submeshIndex];
            var positions = JsonOrBinaryDoubles(group, "positions", "positions_binary");
            if (positions.Count == 0 || positions.Count % 3 != 0)
            {
                parsed = Array.Empty<PreviewVertexGroup>();
                return false;
            }
            var indexPayloadDeclared = ChannelPayloadDeclaresValues(
                group,
                "source_vertex_indices",
                "source_vertex_indices_binary");
            var indices = JsonOrBinaryInts(group, "source_vertex_indices", "source_vertex_indices_binary");
            if (indices.Count == 0)
            {
                if (indexPayloadDeclared)
                {
                    parsed = Array.Empty<PreviewVertexGroup>();
                    return false;
                }
                var start = JsonInt(group, "source_vertex_start", -1);
                var count = JsonInt(group, "source_vertex_count", 0);
                if (start >= 0 && count > 0)
                {
                    indices = Enumerable.Range(start, count).ToList();
                }
                else if (positions.Count / 3 == submesh.Vertices.Count)
                {
                    indices = Enumerable.Range(0, submesh.Vertices.Count).ToList();
                }
            }
            var normals = JsonOrBinaryDoubles(group, "normals", "normals_binary");
            var uvs = JsonOrBinaryDoubles(group, "uvs", "uvs_binary");
            var countMatches = indices.Count == positions.Count / 3;
            if (!countMatches
                || indices.Any(index => index < 0 || index >= submesh.Vertices.Count)
                || (ChannelPayloadDeclaresValues(group, "normals", "normals_binary") && normals.Count != indices.Count * 3)
                || (ChannelPayloadDeclaresValues(group, "uvs", "uvs_binary") && uvs.Count != indices.Count * 2))
            {
                parsed = Array.Empty<PreviewVertexGroup>();
                return false;
            }
            result.Add(new PreviewVertexGroup(submeshIndex, indices, positions, normals, uvs));
        }
        parsed = result;
        return true;
    }

    private static bool ChannelPayloadDeclaresValues(JsonElement group, string jsonName, string binaryName)
    {
        if (group.TryGetProperty(jsonName, out var values) && values.ValueKind == JsonValueKind.Array)
        {
            return values.GetArrayLength() > 0;
        }
        return group.TryGetProperty(binaryName, out var descriptor)
            && descriptor.ValueKind == JsonValueKind.Object
            && JsonInt(descriptor, "count", 0) > 0;
    }

    private static bool TryParsePreviewTriangleGroup(JsonElement group, out PreviewTriangleGroup? parsed)
    {
        parsed = null;
        var submeshIndex = JsonInt(group, "source_submesh_index", JsonInt(group, "index", -1));
        if (submeshIndex < 0)
        {
            return false;
        }
        var positions = JsonOrBinaryDoubles(group, "positions", "positions_binary");
        var normals = JsonOrBinaryDoubles(group, "normals", "normals_binary");
        var uvs = JsonOrBinaryDoubles(group, "uvs", "uvs_binary");
        var indices = JsonOrBinaryInts(group, "indices", "indices_binary");
        if (positions.Count % 3 != 0 || indices.Count % 3 != 0 || (positions.Count == 0) != (indices.Count == 0))
        {
            return false;
        }
        var vertexCount = positions.Count / 3;
        if ((normals.Count != 0 && normals.Count != vertexCount * 3)
            || (uvs.Count != 0 && uvs.Count != vertexCount * 2)
            || indices.Any(index => index < 0 || index >= vertexCount))
        {
            return false;
        }
        var materialName = JsonString(group, "material_name");
        var partName = JsonString(group, "part_name");
        var submesh = new ObjSubmesh(
            partName.Length > 0 ? partName : (materialName.Length > 0 ? materialName : $"submesh_{submeshIndex}"),
            0,
            0,
            0)
        {
            Material = materialName,
        };
        for (var offset = 0; offset < positions.Count; offset += 3)
        {
            submesh.Vertices.Add(new Vec3((float)positions[offset], (float)positions[offset + 1], (float)positions[offset + 2]));
        }
        for (var offset = 0; offset < normals.Count; offset += 3)
        {
            submesh.Normals.Add(new Vec3((float)normals[offset], (float)normals[offset + 1], (float)normals[offset + 2]));
        }
        for (var offset = 0; offset < uvs.Count; offset += 2)
        {
            submesh.Uvs.Add(new Vec2((float)uvs[offset], (float)uvs[offset + 1]));
        }
        var hasNormals = submesh.Normals.Count == vertexCount;
        var hasUvs = submesh.Uvs.Count == vertexCount;
        for (var offset = 0; offset < indices.Count; offset += 3)
        {
            submesh.Faces.Add(new ObjFace(new[]
            {
                PreviewCorner(indices[offset], hasUvs, hasNormals),
                PreviewCorner(indices[offset + 1], hasUvs, hasNormals),
                PreviewCorner(indices[offset + 2], hasUvs, hasNormals),
            }));
        }
        submesh.NormalsVertexAligned = hasNormals;
        submesh.UvsVertexAligned = hasUvs;
        parsed = new PreviewTriangleGroup(
            submeshIndex,
            JsonInt(group, "material_source_submesh_index", submeshIndex),
            submesh);
        return true;
    }

    private static ObjCorner PreviewCorner(int index, bool hasUvs, bool hasNormals)
    {
        return new ObjCorner(index, hasUvs ? index : -1, hasNormals ? index : -1);
    }

    private static List<double> JsonOrBinaryDoubles(JsonElement group, string jsonName, string binaryName)
    {
        var values = JsonDoubleValues(group, jsonName);
        return values.Count == 0 && group.TryGetProperty(binaryName, out var descriptor)
            ? ReadDoubleBinary(descriptor)
            : values;
    }

    private static List<int> JsonOrBinaryInts(JsonElement group, string jsonName, string binaryName)
    {
        var values = JsonIntValues(group, jsonName);
        return values.Count == 0 && group.TryGetProperty(binaryName, out var descriptor)
            ? ReadIntBinary(descriptor)
            : values;
    }

    internal static void EnsureVertexAlignedNormals(ObjSubmesh submesh)
    {
        if (submesh.NormalsVertexAligned && submesh.Normals.Count == submesh.Vertices.Count)
        {
            return;
        }
        if (submesh.Normals.Count == submesh.Vertices.Count
            && submesh.Faces.All(face => face.Corners.All(corner =>
                corner.VertexIndex < 0 || corner.VertexIndex >= submesh.Vertices.Count || corner.NormalIndex == corner.VertexIndex)))
        {
            submesh.NormalsVertexAligned = true;
            return;
        }
        var previous = submesh.Normals.ToArray();
        var aligned = Enumerable.Repeat(new Vec3(0, 0, 1), submesh.Vertices.Count).ToArray();
        var assigned = new bool[submesh.Vertices.Count];
        foreach (var face in submesh.Faces)
        {
            for (var cornerIndex = 0; cornerIndex < face.Corners.Length; cornerIndex++)
            {
                var corner = face.Corners[cornerIndex];
                if (corner.VertexIndex < 0 || corner.VertexIndex >= aligned.Length)
                {
                    continue;
                }
                if (!assigned[corner.VertexIndex] && corner.NormalIndex >= 0 && corner.NormalIndex < previous.Length)
                {
                    aligned[corner.VertexIndex] = previous[corner.NormalIndex];
                    assigned[corner.VertexIndex] = true;
                }
                face.Corners[cornerIndex] = corner with { NormalIndex = corner.VertexIndex };
            }
        }
        submesh.Normals.Clear();
        submesh.Normals.AddRange(aligned);
        submesh.NormalsVertexAligned = true;
    }

    internal static void EnsureVertexAlignedUvs(ObjSubmesh submesh)
    {
        if (submesh.UvsVertexAligned && submesh.Uvs.Count == submesh.Vertices.Count)
        {
            return;
        }
        if (submesh.Uvs.Count == submesh.Vertices.Count
            && submesh.Faces.All(face => face.Corners.All(corner =>
                corner.VertexIndex < 0 || corner.VertexIndex >= submesh.Vertices.Count || corner.UvIndex == corner.VertexIndex)))
        {
            submesh.UvsVertexAligned = true;
            return;
        }
        var previous = submesh.Uvs.ToArray();
        var aligned = new Vec2[submesh.Vertices.Count];
        var assigned = new bool[submesh.Vertices.Count];
        foreach (var face in submesh.Faces)
        {
            for (var cornerIndex = 0; cornerIndex < face.Corners.Length; cornerIndex++)
            {
                var corner = face.Corners[cornerIndex];
                if (corner.VertexIndex < 0 || corner.VertexIndex >= aligned.Length)
                {
                    continue;
                }
                if (!assigned[corner.VertexIndex] && corner.UvIndex >= 0 && corner.UvIndex < previous.Length)
                {
                    aligned[corner.VertexIndex] = previous[corner.UvIndex];
                    assigned[corner.VertexIndex] = true;
                }
                face.Corners[cornerIndex] = corner with { UvIndex = corner.VertexIndex };
            }
        }
        submesh.Uvs.Clear();
        submesh.Uvs.AddRange(aligned);
        submesh.UvsVertexAligned = true;
    }

    internal static bool TryApplyPreviewTriangleGroups(
        ObjDocument document,
        JsonElement root,
        JsonElement groups,
        out int changedCount,
        out int[] affectedSubmeshes,
        out Dictionary<int, int> materialSources,
        out bool replaceAll)
    {
        changedCount = 0;
        affectedSubmeshes = Array.Empty<int>();
        materialSources = new Dictionary<int, int>();
        replaceAll = root.TryGetProperty("replace_all_triangles", out var replaceValue)
            && replaceValue.ValueKind == JsonValueKind.True;
        var parsed = new Dictionary<int, PreviewTriangleGroup>();
        foreach (var group in groups.EnumerateArray())
        {
            if (group.ValueKind != JsonValueKind.Object || !TryParsePreviewTriangleGroup(group, out var item) || item is null)
            {
                return false;
            }
            if (!parsed.TryAdd(item.SubmeshIndex, item))
            {
                return false;
            }
        }
        var requested = JsonIntValues(root, "triangle_source_submesh_indices");
        if (requested.Any(index => index < 0 || (index >= document.Submeshes.Count && !parsed.ContainsKey(index))))
        {
            return false;
        }
        var affected = parsed.Keys.Concat(requested).ToHashSet();
        var hasExplicitFinalCount = root.TryGetProperty("final_submesh_count", out var finalCountValue)
            && finalCountValue.ValueKind is not JsonValueKind.Null and not JsonValueKind.Undefined;
        var finalCount = JsonInt(root, "final_submesh_count", -1);
        if (replaceAll)
        {
            if (!hasExplicitFinalCount)
            {
                finalCount = parsed.Count == 0 ? document.Submeshes.Count : parsed.Keys.Max() + 1;
            }
            if (finalCount < 0
                || parsed.Keys.Any(index => index >= finalCount)
                || (hasExplicitFinalCount && Enumerable.Range(0, finalCount).Any(index => !parsed.ContainsKey(index))))
            {
                return false;
            }
            var next = new List<ObjSubmesh>(finalCount);
            for (var index = 0; index < finalCount; index++)
            {
                if (parsed.TryGetValue(index, out var item))
                {
                    next.Add(item.Submesh);
                    materialSources[index] = Math.Max(0, item.MaterialSource);
                }
                else if (!hasExplicitFinalCount && index < document.Submeshes.Count)
                {
                    next.Add(document.Submeshes[index]);
                    materialSources[index] = index;
                }
                else
                {
                    return false;
                }
            }
            affected.UnionWith(Enumerable.Range(0, Math.Max(finalCount, document.Submeshes.Count)));
            document.Submeshes.Clear();
            document.Submeshes.AddRange(next);
        }
        else
        {
            var previousCount = document.Submeshes.Count;
            if (hasExplicitFinalCount
                && (finalCount < 0
                    || parsed.Values.Any(item => item.SubmeshIndex >= finalCount
                        && (item.SubmeshIndex >= previousCount
                            || item.Submesh.Vertices.Count != 0
                            || item.Submesh.Faces.Count != 0))
                    || (finalCount > previousCount
                        && Enumerable.Range(previousCount, finalCount - previousCount).Any(index => !parsed.ContainsKey(index)))))
            {
                return false;
            }
            var sourceIndices = Enumerable.Range(0, previousCount).ToList();
            if (hasExplicitFinalCount && finalCount < previousCount)
            {
                var removedCount = previousCount - finalCount;
                var removalMarkers = parsed.Values
                    .Where(item => item.SubmeshIndex < previousCount
                        && item.Submesh.Vertices.Count == 0
                        && item.Submesh.Faces.Count == 0)
                    .Select(item => item.SubmeshIndex)
                    .OrderDescending()
                    .ToArray();
                if (removalMarkers.Length > removedCount)
                {
                    return false;
                }
                foreach (var removedIndex in removalMarkers)
                {
                    document.Submeshes.RemoveAt(removedIndex);
                    sourceIndices.RemoveAt(removedIndex);
                    parsed.Remove(removedIndex);
                }
                if (document.Submeshes.Count > finalCount)
                {
                    affected.UnionWith(sourceIndices.Skip(finalCount));
                    document.Submeshes.RemoveRange(finalCount, document.Submeshes.Count - finalCount);
                    sourceIndices.RemoveRange(finalCount, sourceIndices.Count - finalCount);
                }
                for (var submeshIndex = 0; submeshIndex < sourceIndices.Count; submeshIndex++)
                {
                    var oldIndex = sourceIndices[submeshIndex];
                    if (oldIndex == submeshIndex)
                    {
                        continue;
                    }
                    affected.Add(submeshIndex);
                    affected.Add(oldIndex);
                    materialSources[submeshIndex] = oldIndex;
                }
            }
            foreach (var item in parsed.Values.OrderBy(item => item.SubmeshIndex))
            {
                while (document.Submeshes.Count <= item.SubmeshIndex)
                {
                    document.Submeshes.Add(new ObjSubmesh($"submesh_{document.Submeshes.Count}", 0, 0, 0));
                }
                document.Submeshes[item.SubmeshIndex] = item.Submesh;
                materialSources[item.SubmeshIndex] = Math.Max(0, item.MaterialSource);
            }
        }
        changedCount = replaceAll ? Math.Max(1, parsed.Count) : affected.Count;
        affectedSubmeshes = affected.Order().ToArray();
        return true;
    }
}
