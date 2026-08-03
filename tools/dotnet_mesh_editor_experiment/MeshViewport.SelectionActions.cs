using System.Drawing;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private void AddSelectedVertices(int submeshIndex, HashSet<int> result)
    {
        var submesh = _document.Submeshes[submeshIndex];
        if (!_selectedVertices.TryGetValue(submeshIndex, out var selectedVertices))
        {
            return;
        }
        foreach (var vertexIndex in selectedVertices)
        {
            if (vertexIndex >= 0 && vertexIndex < submesh.Vertices.Count)
            {
                result.Add(vertexIndex);
            }
        }
    }

    private void AddSelectedFaceVertices(int submeshIndex, HashSet<int> result)
    {
        var submesh = _document.Submeshes[submeshIndex];
        if (!_selectedFaces.TryGetValue(submeshIndex, out var selectedFaces))
        {
            return;
        }
        foreach (var faceIndex in selectedFaces)
        {
            if (faceIndex < 0 || faceIndex >= submesh.Faces.Count)
            {
                continue;
            }
            foreach (var corner in submesh.Faces[faceIndex].Corners)
            {
                if (corner.VertexIndex >= 0 && corner.VertexIndex < submesh.Vertices.Count)
                {
                    result.Add(corner.VertexIndex);
                }
            }
        }
    }

    private HashSet<int> SelectionVerticesForSubmesh(int submeshIndex)
    {
        var result = new HashSet<int>();
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return result;
        }
        if (_selectedSources.Contains(submeshIndex))
        {
            result.UnionWith(Enumerable.Range(0, _document.Submeshes[submeshIndex].Vertices.Count));
            return result;
        }
        AddSelectedVertices(submeshIndex, result);
        AddSelectedFaceVertices(submeshIndex, result);
        foreach (var edgeId in _selectedEdges)
        {
            var edge = _edgeTopology.EdgeById(edgeId);
            if (edge is null || edge.SubmeshIndex != submeshIndex)
            {
                continue;
            }
            result.Add(edge.VertexA);
            result.Add(edge.VertexB);
        }
        return result;
    }

    public int[] EditableVertexIndicesForSubmesh(int submeshIndex)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return Array.Empty<int>();
        }
        return SelectionVerticesForSubmesh(submeshIndex).OrderBy(index => index).ToArray();
    }

    public void SelectPartFromList(int submeshIndex)
    {
        SelectPartsFromList(new[] { submeshIndex });
    }

    public void SelectPartsFromList(IEnumerable<int> submeshIndices)
    {
        var requestedSources = submeshIndices
            .Where(index => index >= 0 && index < _document.Submeshes.Count)
            .Distinct()
            .OrderBy(index => index)
            .ToArray();
        // The replace carries the current vertex/face/edge selection alongside
        // the requested parts. Sending empty maps here made a Parts-list click
        // an authoritative "replace with nothing" for the geometry channels,
        // which wiped whatever the reader had selected in the viewport.
        var selection = SelectionSnapshotPayload();
        selection["source_indices"] = requestedSources;
        selection["sources"] = requestedSources;
        EditorEventRequested?.Invoke("selection_request", new Dictionary<string, object?>
        {
            ["operation"] = "replace",
            ["target_mode"] = "source",
            ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
            ["local_selection"] = selection,
        });
        StatusRequested?.Invoke("Part selection awaiting authoritative acceptance.");
    }

    private void SyncSelectedPartFocus()
    {
        _selectedSources.RemoveWhere(index => index < 0 || index >= _document.Submeshes.Count);
        SubmeshSelectedRequested?.Invoke(SelectedSubmeshIndex);
    }

    private int PickPartAt(Point point)
    {
        var face = PickFaceAt(point);
        return face?.SubmeshIndex ?? -1;
    }

    // The local click-selection pickers (SelectVertexAt/SelectFaceAt/
    // SelectPartAt/SelectEdgeAt) and their Apply*Operation helpers are
    // gone: hit resolution lives in native screen selection, and the one
    // local fallback left is the SimplePreview part pick above. They had
    // no callers, but their selection_request echo was still being
    // misread by the host as an authoritative empty selection.
}
