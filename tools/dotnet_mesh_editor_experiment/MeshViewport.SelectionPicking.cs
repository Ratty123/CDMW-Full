using System.Drawing;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private const double SelectionClickRadiusPixels = 14.0;
    private const int SelectionRegionTolerancePixels = 6;

    private (int SubmeshIndex, int ItemIndex)? PickVertexAt(Point point)
    {
        var camera = CurrentCamera();
        var bestDistance = SelectionClickRadiusPixels;
        (int SubmeshIndex, int ItemIndex)? best = null;
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount; submeshIndex++)
        {
            if (!IsSubmeshVisibleForViewportSelection(submeshIndex))
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            for (var vertexIndex = 0; vertexIndex < submesh.Vertices.Count; vertexIndex++)
            {
                if (!ShowXRay && !IsVertexFrontFacing(submeshIndex, vertexIndex, camera))
                {
                    continue;
                }
                var projected = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
                var dx = point.X - projected.X;
                var dy = point.Y - projected.Y;
                var distance = Math.Sqrt((dx * dx) + (dy * dy));
                if (distance < bestDistance
                    && (ShowXRay
                        || !IsWorldPointOccluded(
                            point,
                            SceneWorldPoint(submeshIndex, submesh.Vertices[vertexIndex]))))
                {
                    bestDistance = distance;
                    best = (submeshIndex, vertexIndex);
                }
            }
        }
        return best;
    }

    private (int SubmeshIndex, int ItemIndex)? PickFaceAt(Point point)
    {
        if (!ShowXRay)
        {
            return TryNearestVisibleSurface(point, out _, out var visibleSubmesh, out var visibleFace)
                ? (visibleSubmesh, visibleFace)
                : null;
        }
        var camera = CurrentCamera();
        var bestScore = double.MaxValue;
        (int SubmeshIndex, int ItemIndex)? best = null;
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount; submeshIndex++)
        {
            if (!IsSubmeshVisibleForViewportSelection(submeshIndex))
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                if (!ShowXRay && !IsFaceFrontFacing(submeshIndex, faceIndex, camera))
                {
                    continue;
                }
                var face = submesh.Faces[faceIndex];
                if (face.Corners.Length != 3)
                {
                    continue;
                }
                var points = new PointF[3];
                var valid = true;
                for (var cornerIndex = 0; cornerIndex < 3; cornerIndex++)
                {
                    var vertexIndex = face.Corners[cornerIndex].VertexIndex;
                    if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
                    {
                        valid = false;
                        break;
                    }
                    points[cornerIndex] = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
                }
                if (!valid || !PointInTriangle(point, points[0], points[1], points[2]))
                {
                    continue;
                }
                var centerX = (points[0].X + points[1].X + points[2].X) / 3.0;
                var centerY = (points[0].Y + points[1].Y + points[2].Y) / 3.0;
                var score = Math.Pow(point.X - centerX, 2.0) + Math.Pow(point.Y - centerY, 2.0);
                if (score < bestScore)
                {
                    bestScore = score;
                    best = (submeshIndex, faceIndex);
                }
            }
        }
        return best;
    }

    private bool IsVertexFrontFacing(int submeshIndex, int vertexIndex, NetViewportCamera camera)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count || vertexIndex < 0)
        {
            return false;
        }
        var submesh = _document.Submeshes[submeshIndex];
        if (vertexIndex >= submesh.Vertices.Count)
        {
            return false;
        }
        for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
        {
            var face = submesh.Faces[faceIndex];
            if (face.Corners.Any(corner => corner.VertexIndex == vertexIndex)
                && IsFaceFrontFacing(submeshIndex, faceIndex, camera))
            {
                return true;
            }
        }
        return false;
    }

    private void BeginEdgeDrag(Point point)
    {
        BeginSelectionDrag(point, "edge");
    }

    private void FinishEdgeDrag(Point point)
    {
        _edgeDragCurrent = point;
        var rectangle = EdgeDragRectangle();
        var targetMode = _selectionDragTargetMode;
        _edgeDragActive = false;
        var payload = new Dictionary<string, object?>
        {
            ["operation"] = CurrentSelectionOperation(),
            ["target_mode"] = targetMode,
            ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
        };
        if (_options.SimplePreview && targetMode is "source" or "part")
        {
            int[] sourceIndices;
            if (rectangle.Width < 4 && rectangle.Height < 4)
            {
                var sourceIndex = PickPartAt(point);
                sourceIndices = sourceIndex >= 0 ? new[] { sourceIndex } : Array.Empty<int>();
            }
            else
            {
                sourceIndices = PartIdsInRectangle(rectangle);
            }
            payload["source_indices"] = sourceIndices;
            payload["sources"] = sourceIndices;
            payload["active_pane"] = ActivePresentationPane;
            payload["hit"] = sourceIndices.Length > 0;
            EditorEventRequested?.Invoke("part_pick_result", payload);
            StatusRequested?.Invoke(sourceIndices.Length > 0
                ? $"Preview part pick: {string.Join(", ", sourceIndices)}"
                : "Preview part pick: no hit.");
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        if (rectangle.Width < 4 && rectangle.Height < 4)
        {
            payload["screen_brush"] = ScreenPayload(point, SelectionClickRadiusPixels);
            EditorEventRequested?.Invoke("select_request", payload);
            StatusRequested?.Invoke($"{targetMode} selection awaiting authoritative depth-resolved result.");
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        payload["screen_region"] = ScreenDragPayload(_edgeDragStart, point);
        EditorEventRequested?.Invoke("select_request", payload);
        StatusRequested?.Invoke($"{targetMode} region selection awaiting authoritative depth-resolved result.");
        _hoverEdgeId = -1;
        UpdateGpuViewport();
        Invalidate();
    }

    private Rectangle EdgeDragRectangle()
    {
        var left = Math.Min(_edgeDragStart.X, _edgeDragCurrent.X);
        var top = Math.Min(_edgeDragStart.Y, _edgeDragCurrent.Y);
        var right = Math.Max(_edgeDragStart.X, _edgeDragCurrent.X);
        var bottom = Math.Max(_edgeDragStart.Y, _edgeDragCurrent.Y);
        return Rectangle.FromLTRB(left, top, right, bottom);
    }

    private (int SubmeshIndex, int ItemIndex)[] VertexIdsInRectangle(Rectangle rectangle)
    {
        var camera = CurrentCamera();
        var expanded = Rectangle.Inflate(rectangle, SelectionRegionTolerancePixels, SelectionRegionTolerancePixels);
        var result = new List<(int SubmeshIndex, int ItemIndex)>();
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount; submeshIndex++)
        {
            if (!IsSubmeshVisibleForViewportSelection(submeshIndex))
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            for (var vertexIndex = 0; vertexIndex < submesh.Vertices.Count; vertexIndex++)
            {
                if (!ShowXRay && !IsVertexFrontFacing(submeshIndex, vertexIndex, camera))
                {
                    continue;
                }
                var point = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
                if (expanded.Contains(Point.Round(point)))
                {
                    result.Add((submeshIndex, vertexIndex));
                }
            }
        }
        return result.OrderBy(hit => hit.SubmeshIndex).ThenBy(hit => hit.ItemIndex).ToArray();
    }

    private (int SubmeshIndex, int ItemIndex)[] FaceIdsInRectangle(Rectangle rectangle)
    {
        var camera = CurrentCamera();
        var expanded = Rectangle.Inflate(rectangle, SelectionRegionTolerancePixels, SelectionRegionTolerancePixels);
        var result = new List<(int SubmeshIndex, int ItemIndex)>();
        for (var submeshIndex = 0; submeshIndex < _scene.EditableSubmeshCount; submeshIndex++)
        {
            if (!IsSubmeshVisibleForViewportSelection(submeshIndex))
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                if (!ShowXRay && !IsFaceFrontFacing(submeshIndex, faceIndex, camera))
                {
                    continue;
                }
                if (FaceIntersectsRectangle(submeshIndex, submesh, submesh.Faces[faceIndex], expanded, camera))
                {
                    result.Add((submeshIndex, faceIndex));
                }
            }
        }
        return result.OrderBy(hit => hit.SubmeshIndex).ThenBy(hit => hit.ItemIndex).ToArray();
    }

    private int[] PartIdsInRectangle(Rectangle rectangle)
    {
        return FaceIdsInRectangle(rectangle)
            .Select(hit => hit.SubmeshIndex)
            .Distinct()
            .OrderBy(index => index)
            .ToArray();
    }

    private bool FaceIntersectsRectangle(int submeshIndex, ObjSubmesh submesh, ObjFace face, Rectangle rectangle, NetViewportCamera camera)
    {
        if (face.Corners.Length != 3)
        {
            return false;
        }
        var points = new PointF[3];
        for (var i = 0; i < 3; i++)
        {
            var vertexIndex = face.Corners[i].VertexIndex;
            if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
            {
                return false;
            }
            points[i] = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
        }
        var center = new PointF((points[0].X + points[1].X + points[2].X) / 3.0f, (points[0].Y + points[1].Y + points[2].Y) / 3.0f);
        return rectangle.Contains(Point.Round(points[0]))
            || rectangle.Contains(Point.Round(points[1]))
            || rectangle.Contains(Point.Round(points[2]))
            || rectangle.Contains(Point.Round(center))
            || SegmentIntersectsRectangle(points[0], points[1], rectangle)
            || SegmentIntersectsRectangle(points[1], points[2], rectangle)
            || SegmentIntersectsRectangle(points[2], points[0], rectangle);
    }

    private int[] EdgeIdsInRectangle(Rectangle rectangle)
    {
        var camera = CurrentCamera();
        var expanded = Rectangle.Inflate(rectangle, SelectionRegionTolerancePixels, SelectionRegionTolerancePixels);
        var result = new List<int>();
        foreach (var edge in _edgeTopology.Edges)
        {
            if (!IsSubmeshVisibleForViewportSelection(edge.SubmeshIndex))
            {
                continue;
            }
            if (!ShowXRay && !IsEdgeFrontFacing(edge, camera))
            {
                continue;
            }
            if (edge.SubmeshIndex < 0 || edge.SubmeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[edge.SubmeshIndex];
            if (edge.VertexA < 0 || edge.VertexA >= submesh.Vertices.Count || edge.VertexB < 0 || edge.VertexB >= submesh.Vertices.Count)
            {
                continue;
            }
            var a = SceneProjectedPoint(camera, edge.SubmeshIndex, submesh.Vertices[edge.VertexA]);
            var b = SceneProjectedPoint(camera, edge.SubmeshIndex, submesh.Vertices[edge.VertexB]);
            var midpoint = new PointF((a.X + b.X) * 0.5f, (a.Y + b.Y) * 0.5f);
            if (expanded.Contains(Point.Round(a)) || expanded.Contains(Point.Round(b)) || expanded.Contains(Point.Round(midpoint)) || SegmentIntersectsRectangle(a, b, expanded))
            {
                result.Add(edge.Id);
            }
        }
        return result.OrderBy(edgeId => edgeId).ToArray();
    }

    private void SelectEdgeAt(Point point)
    {
        var edgeId = PickEdgeAt(point);
        if (edgeId < 0)
        {
            if (string.Equals(CurrentSelectionOperation(), "replace", StringComparison.OrdinalIgnoreCase))
            {
                _selectedEdges.Clear();
            }
            _hoverEdgeId = -1;
            StatusRequested?.Invoke($"Edge mode: selected={_selectedEdges.Count} hover=0 xray={(ShowXRay ? "on" : "off")}");
            NotifyLocalSelectionChanged();
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        ApplyEdgeSelectionOperation(edgeId, CurrentSelectionOperation());
        _hoverEdgeId = edgeId;
        StatusRequested?.Invoke($"Edge mode: selected={_selectedEdges.Count} hover=1 xray={(ShowXRay ? "on" : "off")}");
        NotifyLocalSelectionChanged();
        UpdateGpuViewport();
        Invalidate();
    }

    private void UpdateHoverEdge(Point point)
    {
        var edgeId = PickEdgeAt(point);
        if (edgeId == _hoverEdgeId)
        {
            return;
        }
        _hoverEdgeId = edgeId;
        StatusRequested?.Invoke($"Edge mode: selected={_selectedEdges.Count} hover={(edgeId >= 0 ? 1 : 0)} xray={(ShowXRay ? "on" : "off")}");
        UpdateGpuViewport();
        Invalidate();
    }

    private void ApplyEdgeSelectionOperation(IEnumerable<int> edgeIds, string operation)
    {
        var ids = edgeIds.Where(_edgeTopology.Contains).Distinct().ToArray();
        var normalized = (operation ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized == "add")
        {
            foreach (var edgeId in ids)
            {
                _selectedEdges.Add(edgeId);
            }
        }
        else if (normalized == "subtract")
        {
            foreach (var edgeId in ids)
            {
                _selectedEdges.Remove(edgeId);
            }
        }
        else if (normalized == "toggle")
        {
            foreach (var edgeId in ids)
            {
                if (!_selectedEdges.Remove(edgeId))
                {
                    _selectedEdges.Add(edgeId);
                }
            }
        }
        else
        {
            _selectedEdges.Clear();
            foreach (var edgeId in ids)
            {
                _selectedEdges.Add(edgeId);
            }
        }
    }

    private void ApplyEdgeSelectionOperation(int edgeId, string operation)
    {
        var normalized = (operation ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized == "add")
        {
            _selectedEdges.Add(edgeId);
        }
        else if (normalized == "subtract")
        {
            _selectedEdges.Remove(edgeId);
        }
        else if (normalized == "toggle")
        {
            if (!_selectedEdges.Remove(edgeId))
            {
                _selectedEdges.Add(edgeId);
            }
        }
        else
        {
            _selectedEdges.Clear();
            _selectedEdges.Add(edgeId);
        }
    }

    private int PickEdgeAt(Point point)
    {
        var camera = CurrentCamera();
        var bestEdgeId = -1;
        var bestDistance = SelectionClickRadiusPixels;
        foreach (var edge in _edgeTopology.Edges)
        {
            if (!IsSubmeshVisibleForViewportSelection(edge.SubmeshIndex))
            {
                continue;
            }
            if (!ShowXRay && !IsEdgeFrontFacing(edge, camera))
            {
                continue;
            }
            if (edge.SubmeshIndex < 0 || edge.SubmeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[edge.SubmeshIndex];
            if (edge.VertexA < 0 || edge.VertexA >= submesh.Vertices.Count || edge.VertexB < 0 || edge.VertexB >= submesh.Vertices.Count)
            {
                continue;
            }
            var a = SceneProjectedPoint(camera, edge.SubmeshIndex, submesh.Vertices[edge.VertexA]);
            var b = SceneProjectedPoint(camera, edge.SubmeshIndex, submesh.Vertices[edge.VertexB]);
            var distance = DistanceToSegment(point, a, b);
            var edgePoint = Vector3.Lerp(
                SceneWorldPoint(edge.SubmeshIndex, submesh.Vertices[edge.VertexA]),
                SceneWorldPoint(edge.SubmeshIndex, submesh.Vertices[edge.VertexB]),
                ScreenSegmentParameter(point, a, b));
            if (distance < bestDistance && (ShowXRay || !IsWorldPointOccluded(point, edgePoint)))
            {
                bestDistance = distance;
                bestEdgeId = edge.Id;
            }
        }
        return bestEdgeId;
    }

    private bool IsSubmeshVisibleForViewportSelection(int submeshIndex)
    {
        return submeshIndex >= 0
            && submeshIndex < _document.Submeshes.Count
            && ActivePaneIncludesForPicking(submeshIndex)
            && _materials.ParametersForSubmesh(submeshIndex).Visible is not false;
    }

    private bool IsEdgeFrontFacing(NetEdge edge, NetViewportCamera camera)
    {
        if (edge.AdjacentFaces.Count == 0)
        {
            return true;
        }
        foreach (var faceIndex in edge.AdjacentFaces)
        {
            if (IsFaceFrontFacing(edge.SubmeshIndex, faceIndex, camera))
            {
                return true;
            }
        }
        return false;
    }

    private bool IsFaceFrontFacing(int submeshIndex, int faceIndex, NetViewportCamera camera)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return false;
        }
        var submesh = _document.Submeshes[submeshIndex];
        if (faceIndex < 0 || faceIndex >= submesh.Faces.Count)
        {
            return false;
        }
        var face = submesh.Faces[faceIndex];
        if (face.Corners.Length != 3)
        {
            return false;
        }
        var points = new PointF[3];
        for (var i = 0; i < 3; i++)
        {
            var vertexIndex = face.Corners[i].VertexIndex;
            if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
            {
                return false;
            }
            points[i] = SceneProjectedPoint(camera, submeshIndex, submesh.Vertices[vertexIndex]);
        }
        var area = ((points[1].X - points[0].X) * (points[2].Y - points[0].Y)) - ((points[1].Y - points[0].Y) * (points[2].X - points[0].X));
        return area < -0.01f;
    }

    internal string CurrentTargetMode()
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        return options.TryGetValue("target_mode", out var value)
            ? (value?.ToString() ?? "vertex").Trim().ToLowerInvariant()
            : "vertex";
    }

    private string CurrentSelectionOperation()
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        return options.TryGetValue("operation", out var value)
            ? (value?.ToString() ?? "replace").Trim().ToLowerInvariant()
            : "replace";
    }
}
