using System.Drawing;
using System.Globalization;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private sealed class ProvisionalStrokeSubmesh
    {
        public required int SubmeshIndex { get; init; }
        public required Vec3[] Baseline { get; init; }
        public required Vec3[] Working { get; init; }
        public required Vec3[] Scratch { get; init; }
        public required float[] BrushWeights { get; init; }
        public required int[] BrushIndices { get; init; }
        public required int[] EditableIndices { get; init; }
        public required int[] DirtyIndices { get; init; }
        public required PointF[] Projected { get; init; }
        public required bool[] FrontFacing { get; init; }
        public required int[][] Adjacency { get; init; }
        public required Vector3[] Normals { get; init; }
        public required Matrix4x4 WorldViewProjection { get; init; }
        public required Vector3 Center { get; init; }
        public required Vector3 BrushCenter { get; set; }
        public int BrushCount { get; set; }
        public int DirtyCount { get; set; }
        public Vector3 LastTranslation { get; set; }
    }

    private sealed class ProvisionalStrokeState
    {
        public required string StrokeId { get; init; }
        public required string Tool { get; init; }
        public required Point Origin { get; init; }
        public required int[] SourceIndices { get; init; }
        public required ProvisionalStrokeSubmesh[] Submeshes { get; init; }
        public required long BaseRevision { get; init; }
        public required bool LocalGeometryPreview { get; init; }
        public Point Previous { get; set; }
        public long LatestRequestId { get; set; }
        public long TerminalRequestId { get; set; }
        public long LastAcceptedRequestId { get; set; }
        public long LastAcceptedRevision { get; set; }
        public long TerminalAcceptedRevision { get; set; }
        public int SculptSampleCount { get; set; }
        public bool AwaitingTerminalGeometry { get; set; }
        public bool Ended { get; set; }
        public bool Cancelled { get; set; }
    }

    private ProvisionalStrokeState? _provisionalStroke;
    private long _authoritativeEditRevision;

    internal bool HasProvisionalStroke => _provisionalStroke is not null;

    internal IReadOnlyList<int> ProvisionalStrokeSourceIndices =>
        _provisionalStroke?.SourceIndices ?? Array.Empty<int>();

    internal long AuthoritativeEditRevision => _authoritativeEditRevision;

    internal void SetAuthoritativeEditRevision(long revision)
    {
        _authoritativeEditRevision = Math.Max(_authoritativeEditRevision, Math.Max(0, revision));
    }

    private bool BeginProvisionalEditorStroke(Point location, string tool, int strokeId)
    {
        ClearProvisionalEditorStroke();
        var normalizedTool = (tool ?? string.Empty).Trim().ToLowerInvariant();
        var hasExplicitSelection = HasEditableSelection;
        var scope = SelectedEditableStrokeSources();
        if (scope.Length == 0 && normalizedTool != "move")
        {
            var hitPart = PickPartAt(location);
            if (hitPart >= 0 && hitPart < _scene.EditableSubmeshCount)
            {
                scope = new[] { hitPart };
            }
        }
        if (scope.Length == 0)
        {
            if (normalizedTool == "move")
            {
                StatusRequested?.Invoke("Move requires a selection. Use Select in the viewport or choose a part under PARTS.");
            }
            return false;
        }
        SetProvisionalViewportSize();
        var camera = CurrentCamera();
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        var radius = (float)Math.Clamp(NumberOption(options, "radius", 24.0), 2.0, 256.0);
        var falloff = FalloffOption(options);
        var localGeometryPreview = normalizedTool is "move" or "grab" or "smooth" or "inflate" or "pinch";
        var candidates = new ProvisionalStrokeSubmesh[scope.Length];
        for (var index = 0; index < candidates.Length; index++)
        {
            candidates[index] = BuildProvisionalStrokeSubmesh(
                scope[index],
                camera,
                location,
                radius,
                hasExplicitSelection ? SelectionVerticesForSubmesh(scope[index]) : null,
                normalizedTool,
                falloff);
        }
        _provisionalStroke = new ProvisionalStrokeState
        {
            StrokeId = strokeId.ToString(CultureInfo.InvariantCulture),
            Tool = normalizedTool,
            Origin = location,
            Previous = location,
            SourceIndices = scope,
            Submeshes = candidates,
            BaseRevision = _authoritativeEditRevision,
            LastAcceptedRevision = _authoritativeEditRevision,
            // Every brush has a local formula kept in parity with the native
            // edit kernel. Python stays outside the pointer-feedback loop;
            // the native transaction still owns the committed result.
            LocalGeometryPreview = localGeometryPreview,
        };
        if (_provisionalStroke.LocalGeometryPreview)
        {
            _d3d11Viewport?.BeginProvisionalVertexGeometry(scope);
        }
        UpdateProvisionalEditorStroke(location);
        return true;
    }

    private int[] SelectedEditableStrokeSources()
    {
        var selected = new HashSet<int>(_selectedSources);
        foreach (var pair in _selectedVertices)
        {
            if (pair.Value.Count > 0) selected.Add(pair.Key);
        }
        foreach (var pair in _selectedFaces)
        {
            if (pair.Value.Count > 0) selected.Add(pair.Key);
        }
        foreach (var edgeId in _selectedEdges)
        {
            if (_edgeTopology.EdgeById(edgeId) is { } edge) selected.Add(edge.SubmeshIndex);
        }
        var editableCount = Math.Min(_scene.EditableSubmeshCount, _document.Submeshes.Count);
        return selected
            .Where(sourceIndex => sourceIndex >= 0
                && sourceIndex < editableCount
                && IsSubmeshVisibleForViewportSelection(sourceIndex))
            .OrderBy(sourceIndex => sourceIndex)
            .ToArray();
    }

    private ProvisionalStrokeSubmesh BuildProvisionalStrokeSubmesh(
        int submeshIndex,
        NetViewportCamera camera,
        Point origin,
        float radius,
        IReadOnlySet<int>? editableSelection,
        string tool,
        string falloff)
    {
        var submesh = _document.Submeshes[submeshIndex];
        var count = submesh.Vertices.Count;
        var baseline = submesh.Vertices.ToArray();
        var working = baseline.ToArray();
        var editableIndices = editableSelection is null
            ? Enumerable.Range(0, count).ToArray()
            : editableSelection.Where(index => index >= 0 && index < count).Distinct().OrderBy(index => index).ToArray();
        var center = Vector3.Zero;
        foreach (var vertexIndex in editableIndices)
        {
            var vertex = baseline[vertexIndex];
            center += new Vector3(vertex.X, vertex.Y, vertex.Z);
        }
        center /= Math.Max(1, editableIndices.Length);
        var matrix = ActiveSceneModelMatrix(submeshIndex) * camera.WorldViewProjection;
        var weights = new float[count];
        var brushIndices = new int[Math.Max(1, editableIndices.Length)];
        var projected = tool == "move" ? Array.Empty<PointF>() : new PointF[count];
        var frontFacing = tool == "move" ? Array.Empty<bool>() : new bool[count];
        if (tool != "move")
        {
            for (var vertexIndex = 0; vertexIndex < count; vertexIndex++)
            {
                projected[vertexIndex] = SceneProjectedPoint(camera, submeshIndex, baseline[vertexIndex]);
            }
            MarkFrontFacingVertices(submesh, projected, frontFacing);
        }
        var weightedCenter = center;
        var brushCount = 0;
        if (tool == "grab")
        {
            weightedCenter = Vector3.Zero;
            var weightTotal = 0.0f;
            foreach (var vertexIndex in editableIndices)
            {
                var dx = projected[vertexIndex].X - origin.X;
                var dy = projected[vertexIndex].Y - origin.Y;
                var distance = MathF.Sqrt(dx * dx + dy * dy);
                if (distance > radius
                    || (SelectionGeometry.RequiresVisibleDepth(ShowXRay) && !frontFacing[vertexIndex]))
                {
                    continue;
                }
                // The active falloff option, through the same profile the falloff
                // preview draws. The echo hardcoding the smooth profile meant any
                // other falloff snapped to a different surface when the
                // authoritative result replaced the provisional one at stroke end.
                var weight = (float)BrushFalloffProfile.Weight(distance, Math.Max(radius, 0.001f), falloff);
                weights[vertexIndex] = weight;
                brushIndices[brushCount++] = vertexIndex;
                weightedCenter += new Vector3(
                    baseline[vertexIndex].X,
                    baseline[vertexIndex].Y,
                    baseline[vertexIndex].Z) * weight;
                weightTotal += weight;
            }
            weightedCenter = weightTotal > 0.0001f ? weightedCenter / weightTotal : center;
        }
        return new ProvisionalStrokeSubmesh
        {
            SubmeshIndex = submeshIndex,
            Baseline = baseline,
            Working = working,
            Scratch = new Vec3[count],
            BrushWeights = weights,
            BrushIndices = brushIndices,
            EditableIndices = editableIndices,
            DirtyIndices = new int[count],
            Projected = projected,
            FrontFacing = frontFacing,
            Adjacency = tool == "smooth" ? BuildProvisionalAdjacency(submesh, count) : Array.Empty<int[]>(),
            Normals = tool == "inflate" ? BuildProvisionalNormals(submesh, baseline) : Array.Empty<Vector3>(),
            WorldViewProjection = matrix,
            Center = center,
            BrushCenter = weightedCenter,
            BrushCount = brushCount,
        };
    }

    private static void MarkFrontFacingVertices(ObjSubmesh submesh, PointF[] projected, bool[] frontFacing)
    {
        foreach (var face in submesh.Faces)
        {
            if (face.Corners.Length != 3)
            {
                continue;
            }
            var a = face.Corners[0].VertexIndex;
            var b = face.Corners[1].VertexIndex;
            var c = face.Corners[2].VertexIndex;
            if (a < 0 || b < 0 || c < 0 || a >= projected.Length || b >= projected.Length || c >= projected.Length)
            {
                continue;
            }
            if (!SelectionGeometry.IsFrontFacingProjectedTriangle(
                projected[a],
                projected[b],
                projected[c]))
            {
                continue;
            }
            frontFacing[a] = true;
            frontFacing[b] = true;
            frontFacing[c] = true;
        }
    }

    private static int[][] BuildProvisionalAdjacency(ObjSubmesh submesh, int vertexCount)
    {
        var adjacency = Enumerable.Range(0, vertexCount)
            .Select(_ => new HashSet<int>())
            .ToArray();
        foreach (var face in submesh.Faces)
        {
            if (face.Corners.Length != 3)
            {
                continue;
            }
            var indices = face.Corners.Select(corner => corner.VertexIndex).ToArray();
            if (indices.Any(index => index < 0 || index >= vertexCount))
            {
                continue;
            }
            adjacency[indices[0]].Add(indices[1]);
            adjacency[indices[0]].Add(indices[2]);
            adjacency[indices[1]].Add(indices[0]);
            adjacency[indices[1]].Add(indices[2]);
            adjacency[indices[2]].Add(indices[0]);
            adjacency[indices[2]].Add(indices[1]);
        }
        return adjacency.Select(neighbors => neighbors.OrderBy(index => index).ToArray()).ToArray();
    }

    private static Vector3[] BuildProvisionalNormals(ObjSubmesh submesh, Vec3[] vertices)
    {
        if (submesh.NormalsVertexAligned && submesh.Normals.Count == vertices.Length)
        {
            return submesh.Normals
                .Select(normal => NormalizeOr(ToVector3(normal), Vector3.UnitY))
                .ToArray();
        }
        var normals = new Vector3[vertices.Length];
        foreach (var face in submesh.Faces)
        {
            if (face.Corners.Length != 3)
            {
                continue;
            }
            var a = face.Corners[0].VertexIndex;
            var b = face.Corners[1].VertexIndex;
            var c = face.Corners[2].VertexIndex;
            if (a < 0 || b < 0 || c < 0 || a >= vertices.Length || b >= vertices.Length || c >= vertices.Length)
            {
                continue;
            }
            var faceNormal = Vector3.Cross(
                ToVector3(vertices[b]) - ToVector3(vertices[a]),
                ToVector3(vertices[c]) - ToVector3(vertices[a]));
            normals[a] += faceNormal;
            normals[b] += faceNormal;
            normals[c] += faceNormal;
        }
        for (var index = 0; index < normals.Length; index++)
        {
            var fallback = NormalizeOr(ToVector3(vertices[index]), Vector3.UnitY);
            normals[index] = NormalizeOr(normals[index], fallback);
        }
        return normals;
    }

    private static Vector3 NormalizeOr(Vector3 value, Vector3 fallback) =>
        value.LengthSquared() > 0.000000000001f ? Vector3.Normalize(value) : fallback;

    private void UpdateProvisionalEditorStroke(Point point)
    {
        var state = _provisionalStroke;
        if (state is null || state.Ended)
        {
            return;
        }
        if (!state.LocalGeometryPreview)
        {
            state.Previous = point;
            return;
        }
        if (state.Tool == "move")
        {
            foreach (var candidate in state.Submeshes)
            {
                candidate.DirtyCount = 0;
                var delta = UnprojectScreenDelta(
                    candidate.WorldViewProjection,
                    candidate.Center,
                    state.Origin,
                    point);
                candidate.LastTranslation = delta;
                foreach (var vertexIndex in candidate.EditableIndices)
                {
                    candidate.Working[vertexIndex] = FromVector3(
                        ToVector3(candidate.Baseline[vertexIndex]) + delta);
                    candidate.DirtyIndices[candidate.DirtyCount++] = vertexIndex;
                }
                _d3d11Viewport?.UpdateProvisionalVertexPositions(
                    candidate.SubmeshIndex,
                    candidate.Working,
                    candidate.DirtyIndices,
                    candidate.DirtyCount,
                    stableChangedSet: true);
            }
        }
        else if (state.Tool == "grab")
        {
            var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
            var strength = (float)Math.Clamp(NumberOption(options, "strength", 0.5), 0.0, 1.0);
            UpdateProvisionalGrab(state, point, strength);
        }
        else if (state.Tool is "smooth" or "inflate" or "pinch")
        {
            var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
            UpdateProvisionalSculpt(state, point, options);
        }
        state.Previous = point;
        UpdateGpuViewport();
        Invalidate();
    }

    private void UpdateProvisionalGrab(ProvisionalStrokeState state, Point point, float strength)
    {
        foreach (var candidate in state.Submeshes)
        {
            candidate.DirtyCount = 0;
            var delta = UnprojectScreenDelta(
                candidate.WorldViewProjection,
                candidate.BrushCenter,
                state.Origin,
                point);
            for (var index = 0; index < candidate.BrushCount; index++)
            {
                var vertexIndex = candidate.BrushIndices[index];
                var weight = candidate.BrushWeights[vertexIndex];
                candidate.Working[vertexIndex] = FromVector3(
                    ToVector3(candidate.Baseline[vertexIndex]) + delta * (weight * strength));
                candidate.DirtyIndices[candidate.DirtyCount++] = vertexIndex;
            }
            _d3d11Viewport?.UpdateProvisionalVertexPositions(
                candidate.SubmeshIndex,
                candidate.Working,
                candidate.DirtyIndices,
                candidate.DirtyCount,
                stableChangedSet: true);
        }
    }

    private void UpdateProvisionalSculpt(
        ProvisionalStrokeState state,
        Point point,
        Dictionary<string, object?> options)
    {
        var radius = (float)Math.Clamp(NumberOption(options, "radius", 24.0), 2.0, 256.0);
        var strength = (float)Math.Clamp(NumberOption(options, "strength", 0.5), 0.0, 1.0);
        var falloff = FalloffOption(options);
        var invert = BoolOption(options, "invert", false);
        var iterations = Math.Clamp((int)Math.Round(NumberOption(options, "iterations", 1.0)), 1, 12);
        foreach (var candidate in state.Submeshes)
        {
            if (!PrepareProvisionalBrushSample(
                    candidate,
                    state.Previous,
                    point,
                    radius,
                    falloff,
                    begin: state.SculptSampleCount == 0))
            {
                continue;
            }
            if (state.Tool == "smooth")
            {
                ApplyProvisionalSmooth(candidate, strength, iterations);
            }
            else
            {
                ApplyProvisionalInflateOrPinch(candidate, state.Tool, point, radius, strength, invert);
            }
            _d3d11Viewport?.UpdateProvisionalVertexPositions(
                candidate.SubmeshIndex,
                candidate.Working,
                candidate.DirtyIndices,
                candidate.DirtyCount,
                stableChangedSet: false);
        }
        state.SculptSampleCount++;
    }

    private bool PrepareProvisionalBrushSample(
        ProvisionalStrokeSubmesh candidate,
        Point start,
        Point point,
        float radius,
        string falloff,
        bool begin)
    {
        for (var index = 0; index < candidate.BrushCount; index++)
        {
            candidate.BrushWeights[candidate.BrushIndices[index]] = 0.0f;
        }
        candidate.BrushCount = 0;
        var weightedCenter = Vector3.Zero;
        var weightTotal = 0.0f;
        var segmentLength = MathF.Sqrt(
            (point.X - start.X) * (point.X - start.X)
            + (point.Y - start.Y) * (point.Y - start.Y));
        var exposureStep = begin
            ? 0.2f
            : Math.Min(4.0f, Math.Max(0.08f, segmentLength / Math.Max(radius * 0.5f, 1.0f)));
        foreach (var vertexIndex in candidate.EditableIndices)
        {
            var distance = SegmentDistance(candidate.Projected[vertexIndex], start, point);
            if (distance > radius
                || (SelectionGeometry.RequiresVisibleDepth(ShowXRay)
                    && !candidate.FrontFacing[vertexIndex]))
            {
                continue;
            }
            var weight = Math.Min(
                4.0f,
                Math.Max(
                    distance <= 0.00000001f ? 1.0f : 0.0f,
                    (float)BrushFalloffProfile.Weight(
                        distance,
                        Math.Max(radius, 0.001f),
                        falloff))
                * exposureStep);
            if (weight <= 0.0f)
            {
                continue;
            }
            candidate.BrushWeights[vertexIndex] = weight;
            candidate.BrushIndices[candidate.BrushCount++] = vertexIndex;
            weightedCenter += ToVector3(candidate.Working[vertexIndex]) * weight;
            weightTotal += weight;
        }
        candidate.BrushCenter = weightTotal > 0.0001f
            ? weightedCenter / weightTotal
            : candidate.Center;
        return candidate.BrushCount > 0;
    }

    private static float SegmentDistance(PointF value, Point start, Point end)
    {
        var dx = end.X - start.X;
        var dy = end.Y - start.Y;
        var lengthSquared = dx * dx + dy * dy;
        if (lengthSquared <= 0.000000000001f)
        {
            return MathF.Sqrt(
                (value.X - start.X) * (value.X - start.X)
                + (value.Y - start.Y) * (value.Y - start.Y));
        }
        var t = Math.Clamp(
            ((value.X - start.X) * dx + (value.Y - start.Y) * dy) / lengthSquared,
            0.0f,
            1.0f);
        var nearestX = start.X + dx * t;
        var nearestY = start.Y + dy * t;
        return MathF.Sqrt(
            (value.X - nearestX) * (value.X - nearestX)
            + (value.Y - nearestY) * (value.Y - nearestY));
    }

    private static void ApplyProvisionalSmooth(
        ProvisionalStrokeSubmesh candidate,
        float strength,
        int iterations)
    {
        for (var iteration = 0; iteration < iterations; iteration++)
        {
            for (var offset = 0; offset < candidate.BrushCount; offset++)
            {
                var vertexIndex = candidate.BrushIndices[offset];
                var neighbors = candidate.Adjacency[vertexIndex];
                if (neighbors.Length == 0)
                {
                    candidate.Scratch[vertexIndex] = candidate.Working[vertexIndex];
                    continue;
                }
                var sum = Vector3.Zero;
                foreach (var neighbor in neighbors)
                {
                    sum += ToVector3(candidate.Working[neighbor]);
                }
                var vertex = ToVector3(candidate.Working[vertexIndex]);
                var average = sum / neighbors.Length;
                var blend = Math.Clamp(candidate.BrushWeights[vertexIndex] * strength, 0.0f, 1.0f);
                candidate.Scratch[vertexIndex] = FromVector3(vertex + (average - vertex) * blend);
            }
            for (var offset = 0; offset < candidate.BrushCount; offset++)
            {
                var vertexIndex = candidate.BrushIndices[offset];
                candidate.Working[vertexIndex] = candidate.Scratch[vertexIndex];
            }
        }
        candidate.DirtyCount = candidate.BrushCount;
        Array.Copy(candidate.BrushIndices, candidate.DirtyIndices, candidate.BrushCount);
    }

    private void ApplyProvisionalInflateOrPinch(
        ProvisionalStrokeSubmesh candidate,
        string tool,
        Point point,
        float radius,
        float strength,
        bool invert)
    {
        candidate.DirtyCount = 0;
        var radiusPixels = Math.Max(1, (int)Math.Round(radius));
        var rightRadius = UnprojectScreenDelta(
            candidate.WorldViewProjection,
            candidate.BrushCenter,
            point,
            new Point(point.X + radiusPixels, point.Y)).Length();
        var downRadius = UnprojectScreenDelta(
            candidate.WorldViewProjection,
            candidate.BrushCenter,
            point,
            new Point(point.X, point.Y + radiusPixels)).Length();
        var worldRadius = (rightRadius + downRadius) * 0.5f;
        var amount = worldRadius * 0.08f * strength * (invert ? -1.0f : 1.0f);
        for (var offset = 0; offset < candidate.BrushCount; offset++)
        {
            var vertexIndex = candidate.BrushIndices[offset];
            var vertex = ToVector3(candidate.Working[vertexIndex]);
            var direction = tool == "inflate"
                ? candidate.Normals[vertexIndex]
                : NormalizeOr(candidate.BrushCenter - vertex, Vector3.Zero);
            var next = vertex + direction * (amount * candidate.BrushWeights[vertexIndex]);
            if (Vector3.DistanceSquared(vertex, next) <= 0.000000000001f)
            {
                continue;
            }
            candidate.Working[vertexIndex] = FromVector3(next);
            candidate.DirtyIndices[candidate.DirtyCount++] = vertexIndex;
        }
    }

    private void MarkProvisionalEditorStrokeEnded(bool cancelled)
    {
        var state = _provisionalStroke;
        if (state is null)
        {
            return;
        }
        state.Ended = true;
        state.Cancelled = cancelled;
        if (!cancelled || !state.LocalGeometryPreview)
        {
            return;
        }
        if (state.Tool == "move")
        {
            foreach (var candidate in state.Submeshes)
            {
                candidate.DirtyCount = 0;
                foreach (var vertexIndex in candidate.EditableIndices)
                {
                    candidate.Working[vertexIndex] = candidate.Baseline[vertexIndex];
                    candidate.DirtyIndices[candidate.DirtyCount++] = vertexIndex;
                }
                _d3d11Viewport?.UpdateProvisionalVertexPositions(
                    candidate.SubmeshIndex,
                    candidate.Working,
                    candidate.DirtyIndices,
                    candidate.DirtyCount);
            }
            return;
        }
        foreach (var candidate in state.Submeshes)
        {
            candidate.DirtyCount = 0;
            foreach (var vertexIndex in candidate.EditableIndices)
            {
                candidate.Working[vertexIndex] = candidate.Baseline[vertexIndex];
                candidate.DirtyIndices[candidate.DirtyCount++] = vertexIndex;
            }
            _d3d11Viewport?.UpdateProvisionalVertexPositions(
                candidate.SubmeshIndex,
                candidate.Working,
                candidate.DirtyIndices,
                candidate.DirtyCount);
        }
    }

    private void ClearProvisionalEditorStroke()
    {
        _d3d11Viewport?.ClearProvisionalGeometry();
        _provisionalStroke = null;
    }

    internal void RegisterProvisionalStrokeRequest(
        long requestId,
        long baseRevision,
        string strokeId,
        string eventName)
    {
        var state = _provisionalStroke;
        if (state is null
            || requestId <= 0
            || !string.Equals(state.StrokeId, strokeId, StringComparison.Ordinal))
        {
            return;
        }
        state.LatestRequestId = Math.Max(state.LatestRequestId, requestId);
        state.LastAcceptedRevision = Math.Max(state.LastAcceptedRevision, Math.Max(0, baseRevision));
        if (eventName is "stroke_end" or "stroke_cancel")
        {
            state.TerminalRequestId = requestId;
        }
    }

    internal bool AcceptProvisionalStrokeUpdate(long requestId, string strokeId, long revision)
    {
        var state = _provisionalStroke;
        if (state is null)
        {
            return true;
        }
        if (requestId <= 0
            || !string.Equals(state.StrokeId, strokeId, StringComparison.Ordinal)
            || revision < state.BaseRevision)
        {
            return false;
        }
        state.LastAcceptedRequestId = Math.Max(state.LastAcceptedRequestId, requestId);
        state.LastAcceptedRevision = Math.Max(state.LastAcceptedRevision, revision);
        return true;
    }

    internal void CompleteProvisionalStrokeRequest(
        long requestId,
        string strokeId,
        string eventName,
        bool accepted,
        string status,
        bool authoritativeGeometryPending = false,
        long revision = 0)
    {
        var state = _provisionalStroke;
        if (state is null
            || !string.Equals(state.StrokeId, strokeId, StringComparison.Ordinal)
            || string.Equals(status, "coalesced", StringComparison.OrdinalIgnoreCase))
        {
            return;
        }
        var terminal = eventName is "stroke_end" or "stroke_cancel";
        if (terminal && requestId == state.TerminalRequestId)
        {
            state.TerminalAcceptedRevision = Math.Max(0, revision);
            state.AwaitingTerminalGeometry = accepted
                && authoritativeGeometryPending
                && (state.LastAcceptedRequestId < requestId
                    || state.LastAcceptedRevision < state.TerminalAcceptedRevision);
            if (!state.AwaitingTerminalGeometry)
            {
                if (accepted)
                {
                    if (_editOperators.ApplyAuthoritativeResult(strokeId))
                    {
                        _editOperators.CompleteRenderer(strokeId);
                    }
                }
                else
                {
                    _editOperators.Reject(
                        strokeId,
                        string.IsNullOrWhiteSpace(status) ? "stroke_rejected" : status,
                        "The authoritative stroke request was rejected.");
                }
                ClearProvisionalEditorStroke();
            }
            return;
        }
        if (!accepted && requestId >= state.LatestRequestId)
        {
            _editOperators.Reject(
                strokeId,
                string.IsNullOrWhiteSpace(status) ? "stroke_rejected" : status,
                "The authoritative stroke update was rejected.");
            ClearProvisionalEditorStroke();
        }
    }

    internal void CompleteProvisionalAuthoritativeUpdate(
        long requestId,
        string strokeId,
        long revision)
    {
        var state = _provisionalStroke;
        if (state is null
            || !state.AwaitingTerminalGeometry
            || requestId != state.TerminalRequestId
            || !string.Equals(state.StrokeId, strokeId, StringComparison.Ordinal)
            || revision < state.TerminalAcceptedRevision)
        {
            return;
        }
        if (_editOperators.ApplyAuthoritativeResult(strokeId))
        {
            _editOperators.CompleteRenderer(strokeId);
        }
        ClearProvisionalEditorStroke();
    }

    private Vector3 UnprojectScreenDelta(
        Matrix4x4 matrix,
        Vector3 center,
        Point start,
        Point end) =>
        UnprojectScreenPoint(matrix, center, end) - UnprojectScreenPoint(matrix, center, start);

    private Vector3 UnprojectScreenPoint(Matrix4x4 matrix, Vector3 center, Point point)
    {
        var clipCenter = Vector4.Transform(new Vector4(center, 1.0f), matrix);
        if (Math.Abs(clipCenter.W) < 0.0000001f || !Matrix4x4.Invert(matrix, out var inverse))
        {
            return center;
        }
        var viewport = _activeProvisionalViewportSize;
        var ndc = new Vector4(
            2.0f * point.X / viewport.X - 1.0f,
            1.0f - 2.0f * point.Y / viewport.Y,
            clipCenter.Z / clipCenter.W,
            1.0f);
        var local = Vector4.Transform(ndc, inverse);
        if (Math.Abs(local.W) < 0.0000001f)
        {
            return center;
        }
        return new Vector3(local.X, local.Y, local.Z) / local.W;
    }

    private Vector2 _activeProvisionalViewportSize = Vector2.One;

    private void SetProvisionalViewportSize()
    {
        var viewport = ActivePaneBounds();
        _activeProvisionalViewportSize = new Vector2(Math.Max(1, viewport.Width), Math.Max(1, viewport.Height));
    }

    // The weight math itself lives in BrushFalloffProfile, the guarded
    // line-for-line port of the native brush; a second local copy here is what
    // let the echo drift onto a hardcoded smooth profile.
    private static string FalloffOption(Dictionary<string, object?> options) =>
        options.TryGetValue("falloff", out var value) && value is string text && text.Length > 0
            ? text.Trim().ToLowerInvariant()
            : BrushFalloffProfile.Smooth;

    private static bool BoolOption(
        Dictionary<string, object?> options,
        string key,
        bool fallback) =>
        options.TryGetValue(key, out var value)
            ? value is bool flag
                ? flag
                : bool.TryParse(Convert.ToString(value, CultureInfo.InvariantCulture), out var parsed)
                    ? parsed
                    : fallback
            : fallback;

    private static Vector3 ToVector3(Vec3 value) => new(value.X, value.Y, value.Z);
    private static Vec3 FromVector3(Vector3 value) => new(value.X, value.Y, value.Z);
}
