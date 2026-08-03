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
        public required PointF[] Projected { get; init; }
        public required bool[] FrontFacing { get; init; }
        public required Vector3[] Normals { get; init; }
        public required Vec3[] SmoothTargets { get; init; }
        public required float[] Exposure { get; init; }
        public required float[] GrabWeights { get; init; }
        public required int[] GrabIndices { get; init; }
        public required int[][] SpatialBuckets { get; init; }
        public required int[] VisitMarks { get; init; }
        public required int[] DirtyIndices { get; init; }
        public required Matrix4x4 WorldViewProjection { get; init; }
        public required Vector3 Center { get; init; }
        public required Vector3 BrushCenter { get; set; }
        public required float UnitsPerPixel { get; init; }
        public required int GridColumns { get; init; }
        public required int GridRows { get; init; }
        public int VisitGeneration { get; set; }
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
        public Point Previous { get; set; }
        public long LatestRequestId { get; set; }
        public long TerminalRequestId { get; set; }
        public long LastAcceptedRequestId { get; set; }
        public long LastAcceptedRevision { get; set; }
        public long TerminalAcceptedRevision { get; set; }
        public bool AwaitingTerminalGeometry { get; set; }
        public bool Ended { get; set; }
        public bool Cancelled { get; set; }
    }

    private ProvisionalStrokeState? _provisionalStroke;
    private long _authoritativeEditRevision;

    internal bool HasProvisionalStroke => _provisionalStroke is not null;

    internal IReadOnlyList<int> ProvisionalStrokeSourceIndices =>
        _provisionalStroke?.SourceIndices ?? Array.Empty<int>();

    internal void SetAuthoritativeEditRevision(long revision)
    {
        _authoritativeEditRevision = Math.Max(_authoritativeEditRevision, Math.Max(0, revision));
    }

    private bool BeginProvisionalEditorStroke(Point location, string tool, int strokeId)
    {
        ClearProvisionalEditorStroke();
        var normalizedTool = (tool ?? string.Empty).Trim().ToLowerInvariant();
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
            return false;
        }
        SetProvisionalViewportSize();
        var camera = CurrentCamera();
        var radius = (float)Math.Clamp(
            NumberOption(ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>(), "radius", 24.0),
            2.0,
            256.0);
        var candidates = new ProvisionalStrokeSubmesh[scope.Length];
        for (var index = 0; index < scope.Length; index++)
        {
            candidates[index] = BuildProvisionalStrokeSubmesh(scope[index], camera, location, radius);
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
        };
        if (normalizedTool == "move")
        {
            _d3d11Viewport?.BeginProvisionalPartTransforms(scope);
        }
        else
        {
            _d3d11Viewport?.BeginProvisionalVertexGeometry(scope);
        }
        UpdateProvisionalEditorStroke(location, initial: true);
        return true;
    }

    private int[] SelectedEditableStrokeSources()
    {
        var values = new List<int>(_selectedSources.Count);
        foreach (var sourceIndex in _selectedSources)
        {
            if (sourceIndex >= 0
                && sourceIndex < _scene.EditableSubmeshCount
                && sourceIndex < _document.Submeshes.Count
                && IsSubmeshVisibleForViewportSelection(sourceIndex))
            {
                values.Add(sourceIndex);
            }
        }
        values.Sort();
        return values.ToArray();
    }

    private ProvisionalStrokeSubmesh BuildProvisionalStrokeSubmesh(
        int submeshIndex,
        NetViewportCamera camera,
        Point origin,
        float radius)
    {
        var submesh = _document.Submeshes[submeshIndex];
        var count = submesh.Vertices.Count;
        var baseline = submesh.Vertices.ToArray();
        var working = baseline.ToArray();
        var projected = new PointF[count];
        var frontFacing = new bool[count];
        var normals = BuildProvisionalVertexNormals(submesh, baseline);
        var center = Vector3.Zero;
        for (var vertexIndex = 0; vertexIndex < count; vertexIndex++)
        {
            var vertex = baseline[vertexIndex];
            center += new Vector3(vertex.X, vertex.Y, vertex.Z);
            projected[vertexIndex] = SceneProjectedPoint(camera, submeshIndex, vertex);
        }
        center /= Math.Max(1, count);
        MarkFrontFacingVertices(submesh, projected, frontFacing);
        var matrix = ActiveSceneModelMatrix(submeshIndex) * camera.WorldViewProjection;
        var unitsPerPixel = ScreenUnitsPerPixel(matrix, center, origin);
        var weights = new float[count];
        var grabIndices = new int[count];
        var grabCount = 0;
        var weightedCenter = Vector3.Zero;
        var weightTotal = 0.0f;
        for (var vertexIndex = 0; vertexIndex < count; vertexIndex++)
        {
            var dx = projected[vertexIndex].X - origin.X;
            var dy = projected[vertexIndex].Y - origin.Y;
            var distance = MathF.Sqrt(dx * dx + dy * dy);
            if (distance > radius || (!ShowXRay && !frontFacing[vertexIndex]))
            {
                continue;
            }
            var weight = BrushFalloffWeight(distance / Math.Max(radius, 0.001f), "smooth");
            weights[vertexIndex] = weight;
            grabIndices[grabCount++] = vertexIndex;
            weightedCenter += new Vector3(
                baseline[vertexIndex].X,
                baseline[vertexIndex].Y,
                baseline[vertexIndex].Z) * weight;
            weightTotal += weight;
        }
        Array.Resize(ref grabIndices, grabCount);
        var spatialIndex = BuildProvisionalSpatialIndex(projected);
        return new ProvisionalStrokeSubmesh
        {
            SubmeshIndex = submeshIndex,
            Baseline = baseline,
            Working = working,
            Projected = projected,
            FrontFacing = frontFacing,
            Normals = normals,
            SmoothTargets = BuildSmoothTargets(submesh, baseline),
            Exposure = new float[count],
            GrabWeights = weights,
            GrabIndices = grabIndices,
            SpatialBuckets = spatialIndex.Buckets,
            VisitMarks = new int[count],
            DirtyIndices = new int[count],
            WorldViewProjection = matrix,
            Center = center,
            BrushCenter = weightTotal > 0.0001f ? weightedCenter / weightTotal : center,
            UnitsPerPixel = unitsPerPixel,
            GridColumns = spatialIndex.Columns,
            GridRows = spatialIndex.Rows,
        };
    }

    private const int ProvisionalSpatialCellPixels = 32;

    private (int Columns, int Rows, int[][] Buckets) BuildProvisionalSpatialIndex(PointF[] projected)
    {
        var viewport = ActivePaneBounds();
        var columns = Math.Max(1, (viewport.Width + ProvisionalSpatialCellPixels - 1) / ProvisionalSpatialCellPixels);
        var rows = Math.Max(1, (viewport.Height + ProvisionalSpatialCellPixels - 1) / ProvisionalSpatialCellPixels);
        var pending = new List<int>?[columns * rows];
        for (var vertexIndex = 0; vertexIndex < projected.Length; vertexIndex++)
        {
            var point = projected[vertexIndex];
            var column = (int)MathF.Floor(point.X / ProvisionalSpatialCellPixels);
            var row = (int)MathF.Floor(point.Y / ProvisionalSpatialCellPixels);
            if (column < 0 || column >= columns || row < 0 || row >= rows)
            {
                continue;
            }
            var bucketIndex = row * columns + column;
            (pending[bucketIndex] ??= new List<int>()).Add(vertexIndex);
        }
        var buckets = new int[pending.Length][];
        for (var bucketIndex = 0; bucketIndex < pending.Length; bucketIndex++)
        {
            buckets[bucketIndex] = pending[bucketIndex]?.ToArray() ?? Array.Empty<int>();
        }
        return (columns, rows, buckets);
    }

    private static Vector3[] BuildProvisionalVertexNormals(ObjSubmesh submesh, IReadOnlyList<Vec3> vertices)
    {
        var normals = new Vector3[vertices.Count];
        if (submesh.Normals.Count == vertices.Count)
        {
            for (var index = 0; index < normals.Length; index++)
            {
                var normal = submesh.Normals[index];
                normals[index] = NormalizeOr(new Vector3(normal.X, normal.Y, normal.Z), Vector3.UnitY);
            }
            return normals;
        }
        foreach (var face in submesh.Faces)
        {
            if (face.Corners.Length != 3)
            {
                continue;
            }
            var a = face.Corners[0].VertexIndex;
            var b = face.Corners[1].VertexIndex;
            var c = face.Corners[2].VertexIndex;
            if (a < 0 || b < 0 || c < 0 || a >= vertices.Count || b >= vertices.Count || c >= vertices.Count)
            {
                continue;
            }
            var va = ToVector3(vertices[a]);
            var normal = Vector3.Cross(ToVector3(vertices[b]) - va, ToVector3(vertices[c]) - va);
            normals[a] += normal;
            normals[b] += normal;
            normals[c] += normal;
        }
        for (var index = 0; index < normals.Length; index++)
        {
            normals[index] = NormalizeOr(normals[index], Vector3.UnitY);
        }
        return normals;
    }

    private static Vec3[] BuildSmoothTargets(ObjSubmesh submesh, IReadOnlyList<Vec3> vertices)
    {
        var sums = new Vector3[vertices.Count];
        var counts = new int[vertices.Count];
        foreach (var face in submesh.Faces)
        {
            if (face.Corners.Length != 3)
            {
                continue;
            }
            var a = face.Corners[0].VertexIndex;
            var b = face.Corners[1].VertexIndex;
            var c = face.Corners[2].VertexIndex;
            if (a < 0 || b < 0 || c < 0 || a >= vertices.Count || b >= vertices.Count || c >= vertices.Count)
            {
                continue;
            }
            AddSmoothNeighbor(sums, counts, a, vertices[b]);
            AddSmoothNeighbor(sums, counts, a, vertices[c]);
            AddSmoothNeighbor(sums, counts, b, vertices[a]);
            AddSmoothNeighbor(sums, counts, b, vertices[c]);
            AddSmoothNeighbor(sums, counts, c, vertices[a]);
            AddSmoothNeighbor(sums, counts, c, vertices[b]);
        }
        var targets = new Vec3[vertices.Count];
        for (var index = 0; index < targets.Length; index++)
        {
            targets[index] = counts[index] > 0
                ? FromVector3(sums[index] / counts[index])
                : vertices[index];
        }
        return targets;
    }

    private static void AddSmoothNeighbor(Vector3[] sums, int[] counts, int target, Vec3 neighbor)
    {
        sums[target] += ToVector3(neighbor);
        counts[target]++;
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
            var area = ((projected[b].X - projected[a].X) * (projected[c].Y - projected[a].Y))
                - ((projected[b].Y - projected[a].Y) * (projected[c].X - projected[a].X));
            if (area >= -0.01f)
            {
                continue;
            }
            frontFacing[a] = true;
            frontFacing[b] = true;
            frontFacing[c] = true;
        }
    }

    private void UpdateProvisionalEditorStroke(Point point, bool initial = false)
    {
        var state = _provisionalStroke;
        if (state is null || state.Ended)
        {
            return;
        }
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        var radius = (float)Math.Clamp(NumberOption(options, "radius", 24.0), 2.0, 256.0);
        var strength = (float)Math.Clamp(NumberOption(options, "strength", 0.5), 0.0, 1.0);
        var falloff = Convert.ToString(options.GetValueOrDefault("falloff"), CultureInfo.InvariantCulture)?.Trim().ToLowerInvariant() ?? "smooth";
        var invert = options.TryGetValue("invert", out var rawInvert) && Convert.ToBoolean(rawInvert, CultureInfo.InvariantCulture);
        if (state.Tool == "move")
        {
            foreach (var candidate in state.Submeshes)
            {
                var delta = UnprojectScreenDelta(
                    candidate.WorldViewProjection,
                    candidate.Center,
                    state.Origin,
                    point);
                candidate.LastTranslation = delta;
                _d3d11Viewport?.UpdateProvisionalPartTranslation(candidate.SubmeshIndex, delta);
            }
        }
        else if (state.Tool == "grab")
        {
            UpdateProvisionalGrab(state, point, strength);
        }
        else
        {
            UpdateProvisionalBrush(state, state.Previous, point, radius, strength, falloff, invert, initial);
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
            foreach (var vertexIndex in candidate.GrabIndices)
            {
                var weight = candidate.GrabWeights[vertexIndex];
                candidate.Working[vertexIndex] = FromVector3(
                    ToVector3(candidate.Baseline[vertexIndex]) + delta * (weight * strength));
                candidate.DirtyIndices[candidate.DirtyCount++] = vertexIndex;
            }
            _d3d11Viewport?.UpdateProvisionalVertexPositions(
                candidate.SubmeshIndex,
                candidate.Working,
                candidate.DirtyIndices,
                candidate.DirtyCount);
        }
    }

    private void UpdateProvisionalBrush(
        ProvisionalStrokeState state,
        Point start,
        Point end,
        float radius,
        float strength,
        string falloff,
        bool invert,
        bool initial)
    {
        var segmentLength = MathF.Sqrt((end.X - start.X) * (end.X - start.X) + (end.Y - start.Y) * (end.Y - start.Y));
        var exposureStep = Math.Max(initial ? 0.2f : 0.08f, segmentLength / Math.Max(radius * 0.5f, 1.0f));
        foreach (var candidate in state.Submeshes)
        {
            candidate.DirtyCount = 0;
            candidate.VisitGeneration = candidate.VisitGeneration == int.MaxValue
                ? 1
                : candidate.VisitGeneration + 1;
            if (candidate.VisitGeneration == 1)
            {
                Array.Clear(candidate.VisitMarks);
            }
            var cursorCenter = UnprojectScreenPoint(
                candidate.WorldViewProjection,
                candidate.Center,
                end);
            var radiusUnits = Math.Max(candidate.UnitsPerPixel * radius, 0.000001f);
            var amount = radiusUnits * 0.08f * strength * (invert ? -1.0f : 1.0f);
            var left = Math.Clamp((int)MathF.Floor((Math.Min(start.X, end.X) - radius) / ProvisionalSpatialCellPixels), 0, candidate.GridColumns - 1);
            var right = Math.Clamp((int)MathF.Floor((Math.Max(start.X, end.X) + radius) / ProvisionalSpatialCellPixels), 0, candidate.GridColumns - 1);
            var top = Math.Clamp((int)MathF.Floor((Math.Min(start.Y, end.Y) - radius) / ProvisionalSpatialCellPixels), 0, candidate.GridRows - 1);
            var bottom = Math.Clamp((int)MathF.Floor((Math.Max(start.Y, end.Y) + radius) / ProvisionalSpatialCellPixels), 0, candidate.GridRows - 1);
            for (var row = top; row <= bottom; row++)
            {
                for (var column = left; column <= right; column++)
                {
                    foreach (var vertexIndex in candidate.SpatialBuckets[row * candidate.GridColumns + column])
                    {
                        if (candidate.VisitMarks[vertexIndex] == candidate.VisitGeneration)
                        {
                            continue;
                        }
                        candidate.VisitMarks[vertexIndex] = candidate.VisitGeneration;
                        if (!ShowXRay && !candidate.FrontFacing[vertexIndex])
                        {
                            continue;
                        }
                        var distance = DistanceToSegment(candidate.Projected[vertexIndex], start, end);
                        if (distance > radius)
                        {
                            continue;
                        }
                        var weight = BrushFalloffWeight(distance / Math.Max(radius, 0.001f), falloff);
                        candidate.Exposure[vertexIndex] = Math.Min(4.0f, candidate.Exposure[vertexIndex] + weight * exposureStep);
                        var exposure = candidate.Exposure[vertexIndex];
                        var baseline = ToVector3(candidate.Baseline[vertexIndex]);
                        Vector3 next;
                        if (state.Tool == "smooth")
                        {
                            var target = ToVector3(candidate.SmoothTargets[vertexIndex]);
                            next = Vector3.Lerp(baseline, target, Math.Clamp(exposure * strength, 0.0f, 1.0f));
                        }
                        else if (state.Tool == "pinch")
                        {
                            var direction = NormalizeOr(cursorCenter - baseline, Vector3.Zero);
                            next = baseline + direction * (Math.Abs(amount) * exposure * (invert ? -1.0f : 1.0f));
                        }
                        else
                        {
                            next = baseline + candidate.Normals[vertexIndex] * (amount * exposure);
                        }
                        candidate.Working[vertexIndex] = FromVector3(next);
                        candidate.DirtyIndices[candidate.DirtyCount++] = vertexIndex;
                    }
                }
            }
            _d3d11Viewport?.UpdateProvisionalVertexPositions(
                candidate.SubmeshIndex,
                candidate.Working,
                candidate.DirtyIndices,
                candidate.DirtyCount);
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
        if (!cancelled)
        {
            return;
        }
        if (state.Tool == "move")
        {
            foreach (var candidate in state.Submeshes)
            {
                _d3d11Viewport?.UpdateProvisionalPartTranslation(candidate.SubmeshIndex, Vector3.Zero);
            }
            return;
        }
        foreach (var candidate in state.Submeshes)
        {
            candidate.DirtyCount = candidate.Baseline.Length;
            for (var index = 0; index < candidate.Baseline.Length; index++)
            {
                candidate.Working[index] = candidate.Baseline[index];
                candidate.DirtyIndices[index] = index;
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
                ClearProvisionalEditorStroke();
            }
            return;
        }
        if (!accepted && requestId >= state.LatestRequestId)
        {
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
        ClearProvisionalEditorStroke();
    }

    private float ScreenUnitsPerPixel(Matrix4x4 matrix, Vector3 center, Point point)
    {
        var start = UnprojectScreenPoint(matrix, center, point);
        var end = UnprojectScreenPoint(matrix, center, new Point(point.X + 1, point.Y));
        var units = Vector3.Distance(start, end);
        return float.IsFinite(units) && units > 0.0000001f ? units : 0.001f;
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

    private static float DistanceToSegment(PointF point, Point start, Point end)
    {
        var dx = end.X - start.X;
        var dy = end.Y - start.Y;
        var lengthSquared = dx * dx + dy * dy;
        if (lengthSquared <= 0.0001f)
        {
            return MathF.Sqrt((point.X - start.X) * (point.X - start.X) + (point.Y - start.Y) * (point.Y - start.Y));
        }
        var t = Math.Clamp(((point.X - start.X) * dx + (point.Y - start.Y) * dy) / lengthSquared, 0.0f, 1.0f);
        var nearestX = start.X + t * dx;
        var nearestY = start.Y + t * dy;
        return MathF.Sqrt((point.X - nearestX) * (point.X - nearestX) + (point.Y - nearestY) * (point.Y - nearestY));
    }

    private static float BrushFalloffWeight(float normalizedDistance, string falloff)
    {
        var weight = Math.Clamp(1.0f - normalizedDistance, 0.0f, 1.0f);
        return falloff switch
        {
            "sharp" => weight * weight,
            "linear" => weight,
            "constant" => weight > 0.0f ? 1.0f : 0.0f,
            _ => weight * weight * (3.0f - 2.0f * weight),
        };
    }

    private static Vector3 NormalizeOr(Vector3 value, Vector3 fallback) =>
        value.LengthSquared() > 0.0000001f ? Vector3.Normalize(value) : fallback;

    private static Vector3 ToVector3(Vec3 value) => new(value.X, value.Y, value.Z);
    private static Vec3 FromVector3(Vector3 value) => new(value.X, value.Y, value.Z);
}
