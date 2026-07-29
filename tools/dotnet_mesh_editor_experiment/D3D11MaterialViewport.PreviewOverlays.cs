using System.Diagnostics;
using System.Numerics;
using System.Runtime.CompilerServices;
using Vortice.Direct3D;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    // Chosen so a deflected vertex returns over a few tenths of a second: stiff
    // enough that the garment holds its authored silhouette, soft enough that
    // gravity and wind still visibly move it.
    private const float ClothRestStiffness = 34.0f;
    private const float ClothVelocityDamping = 0.90f;

    private readonly List<Vector3> _clothOverlayPositions = new();
    private readonly List<Vector3> _clothOverlayVelocities = new();
    private readonly List<Vector3> _clothOverlayRestPositions = new();
    private readonly List<float> _clothOverlayRestLengths = new();
    private int _clothOverlaySceneIdentity;
    private long _clothOverlayResetGeneration = -1;
    private long _clothOverlayLastTimestamp;

    public void ResetPreviewOverlaySimulationIfRequested()
    {
        var overlays = _scene.PreviewOverlays;
        if (_clothOverlayResetGeneration != overlays.ClothResetGeneration)
        {
            ResetClothOverlaySimulation(overlays);
        }
        Invalidate();
    }

    private void DrawPreviewSceneOverlays()
    {
        var overlays = _scene.PreviewOverlays;
        if (overlays.SkeletonVisible && overlays.SkeletonBones.Count > 0)
        {
            DrawSkeletonPreviewOverlay(overlays);
        }
        if (overlays.ClothEnabled && overlays.ClothParticles.Count > 0)
        {
            DrawClothPreviewOverlay(overlays);
        }
    }

    private void DrawSkeletonPreviewOverlay(NetPreviewOverlayState overlays)
    {
        var regular = ResetScratchA();
        var selected = ResetScratchB();
        var extent = Math.Max(0.01f, _scene.SceneExtent);
        var markerRadius = extent * 0.006f;
        foreach (var bone in overlays.SkeletonBones)
        {
            var target = bone.Index == overlays.SelectedBoneIndex ? selected : regular;
            if (bone.HasParentPosition)
            {
                target.Add(bone.ParentPosition);
                target.Add(bone.Position);
            }
            AddWorldCross(bone.Position, markerRadius, target);
        }
        var matrix = ActivePaneModelMatrix(0) * _camera.WorldViewProjection;
        DrawOverlayPrimitive(PrimitiveTopology.LineList, regular, OverlayColor(92, 207, 255, 220), matrix);
        DrawOverlayPrimitive(PrimitiveTopology.LineList, selected, OverlayColor(255, 210, 76, 255), matrix);
    }

    /// <summary>
    /// Push the solved particle positions into the submeshes they came from, so
    /// the textured mesh is what moves. Without this the solver only fed a line
    /// overlay and the model stayed rigid underneath it.
    /// </summary>
    private void ApplyClothSimulationToMesh(NetPreviewOverlayState overlays)
    {
        if (_document is null || overlays.ClothBatchRanges.Count == 0)
        {
            return;
        }
        foreach (var range in overlays.ClothBatchRanges)
        {
            if (range.SubmeshIndex < 0 || range.SubmeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[range.SubmeshIndex];
            // A topology edit between package load and now would make the range
            // describe a mesh that no longer exists; leave that frame alone.
            if (submesh.Vertices.Count != range.Count)
            {
                continue;
            }
            var batch = _batches.FirstOrDefault(candidate => candidate.SubmeshIndex == range.SubmeshIndex);
            if (batch is null
                || batch.TopologyGeneration != _topologyGeneration
                || batch.SourceVertexToRenderCorners.SourceVertexCount != submesh.Vertices.Count)
            {
                continue;
            }
            for (var index = 0; index < range.Count; index++)
            {
                var position = _clothOverlayPositions[range.Offset + index];
                submesh.Vertices[index] = new Vec3(position.X, position.Y, position.Z);
            }
            // Every vertex moved, so range coalescing would rebuild the whole
            // batch anyway; upload it in one call and let WriteFaceVertices
            // recompute the normals and tangent frames from the new positions.
            UploadFaceRange(batch, submesh, 0, batch.RenderFaces.Length - 1);
        }
    }

    private void DrawClothPreviewOverlay(NetPreviewOverlayState overlays)
    {
        EnsureClothOverlaySimulation(overlays);
        StepClothOverlaySimulation(overlays);
        ApplyClothSimulationToMesh(overlays);
        // The constraint lines were the only way to see the simulation when it
        // could not move the mesh. Now that it can, they are debug output and
        // ride with the other debug overlays rather than being the whole show.
        if (!overlays.ClothShowPins && !overlays.ClothShowColliders)
        {
            return;
        }
        var constraints = ResetScratchA();
        foreach (var constraint in overlays.ClothConstraints)
        {
            if (constraint.A < 0
                || constraint.B < 0
                || constraint.A >= _clothOverlayPositions.Count
                || constraint.B >= _clothOverlayPositions.Count)
            {
                continue;
            }
            constraints.Add(_clothOverlayPositions[constraint.A]);
            constraints.Add(_clothOverlayPositions[constraint.B]);
        }
        var matrix = ActivePaneModelMatrix(0) * _camera.WorldViewProjection;
        DrawOverlayPrimitive(
            PrimitiveTopology.LineList,
            constraints,
            OverlayColor(255, 128, 74, 180),
            matrix);

        if (overlays.ClothShowPins)
        {
            var pins = ResetScratchB();
            var radius = Math.Max(0.001f, _scene.SceneExtent * 0.008f);
            for (var index = 0; index < _clothOverlayPositions.Count; index++)
            {
                if (index < overlays.ClothPinWeights.Count && overlays.ClothPinWeights[index] >= 0.5f)
                {
                    AddWorldCross(_clothOverlayPositions[index], radius, pins);
                }
            }
            DrawOverlayPrimitive(PrimitiveTopology.LineList, pins, OverlayColor(255, 226, 82, 255), matrix);
        }
        if (overlays.ClothShowColliders)
        {
            var colliderLines = ResetScratchB();
            foreach (var collider in overlays.ClothColliders)
            {
                AddColliderLines(collider, colliderLines);
            }
            DrawOverlayPrimitive(
                PrimitiveTopology.LineList,
                colliderLines,
                OverlayColor(112, 235, 170, 235),
                matrix);
        }
    }

    private void EnsureClothOverlaySimulation(NetPreviewOverlayState overlays)
    {
        var identity = RuntimeHelpers.GetHashCode(overlays);
        if (_clothOverlaySceneIdentity != identity
            || _clothOverlayPositions.Count != overlays.ClothParticles.Count
            || _clothOverlayResetGeneration != overlays.ClothResetGeneration)
        {
            ResetClothOverlaySimulation(overlays);
        }
    }

    private void ResetClothOverlaySimulation(NetPreviewOverlayState overlays)
    {
        _clothOverlaySceneIdentity = RuntimeHelpers.GetHashCode(overlays);
        _clothOverlayResetGeneration = overlays.ClothResetGeneration;
        _clothOverlayLastTimestamp = 0;
        _clothOverlayPositions.Clear();
        _clothOverlayPositions.AddRange(overlays.ClothParticles);
        _clothOverlayRestPositions.Clear();
        _clothOverlayRestPositions.AddRange(overlays.ClothParticles);
        _clothOverlayVelocities.Clear();
        _clothOverlayVelocities.AddRange(Enumerable.Repeat(Vector3.Zero, overlays.ClothParticles.Count));
        _clothOverlayRestLengths.Clear();
        foreach (var constraint in overlays.ClothConstraints)
        {
            var length = constraint.A >= 0
                && constraint.B >= 0
                && constraint.A < overlays.ClothParticles.Count
                && constraint.B < overlays.ClothParticles.Count
                    ? Vector3.Distance(overlays.ClothParticles[constraint.A], overlays.ClothParticles[constraint.B])
                    : 0.0f;
            _clothOverlayRestLengths.Add(length);
        }
    }

    private void StepClothOverlaySimulation(NetPreviewOverlayState overlays)
    {
        var now = Stopwatch.GetTimestamp();
        var deltaSeconds = _clothOverlayLastTimestamp <= 0
            ? 1.0f / 60.0f
            : (float)Math.Clamp(
                (now - _clothOverlayLastTimestamp) / (double)Stopwatch.Frequency,
                1.0 / 240.0,
                1.0 / 30.0);
        _clothOverlayLastTimestamp = now;
        if (overlays.ClothPaused)
        {
            return;
        }
        var windRadians = overlays.ClothWindDirectionDegrees * MathF.PI / 180.0f;
        var acceleration = new Vector3(
            MathF.Cos(windRadians) * overlays.ClothWindStrength * 0.8f,
            -0.55f,
            MathF.Sin(windRadians) * overlays.ClothWindStrength * 0.8f);
        for (var index = 0; index < _clothOverlayPositions.Count; index++)
        {
            var pinWeight = index < overlays.ClothPinWeights.Count ? overlays.ClothPinWeights[index] : 0.0f;
            if (pinWeight >= 0.999f)
            {
                _clothOverlayPositions[index] = _clothOverlayRestPositions[index];
                _clothOverlayVelocities[index] = Vector3.Zero;
                continue;
            }
            // The authored shape is the equilibrium, not the floor. Distance
            // constraints alone do not oppose a constant pull, so a garment with
            // few pins sagged until it collapsed into a heap -- correct for a
            // flag, wrong for trousers already hanging where they belong. A
            // spring back to the rest pose makes gravity a deflection the cloth
            // recovers from rather than a direction it keeps travelling in.
            var toRest = _clothOverlayRestPositions[index] - _clothOverlayPositions[index];
            var restoring = toRest * ClothRestStiffness;
            var velocity = (_clothOverlayVelocities[index] + (acceleration + restoring) * deltaSeconds)
                * ClothVelocityDamping;
            _clothOverlayVelocities[index] = velocity;
            _clothOverlayPositions[index] += velocity * deltaSeconds * (1.0f - pinWeight);
        }
        for (var iteration = 0; iteration < 3; iteration++)
        {
            for (var index = 0; index < overlays.ClothConstraints.Count; index++)
            {
                var constraint = overlays.ClothConstraints[index];
                if (constraint.A < 0
                    || constraint.B < 0
                    || constraint.A >= _clothOverlayPositions.Count
                    || constraint.B >= _clothOverlayPositions.Count)
                {
                    continue;
                }
                var delta = _clothOverlayPositions[constraint.B] - _clothOverlayPositions[constraint.A];
                var length = delta.Length();
                var restLength = index < _clothOverlayRestLengths.Count ? _clothOverlayRestLengths[index] : length;
                if (length <= 0.000001f || restLength <= 0.0f)
                {
                    continue;
                }
                var correction = delta * ((length - restLength) / length * 0.5f);
                var pinA = constraint.A < overlays.ClothPinWeights.Count ? overlays.ClothPinWeights[constraint.A] : 0.0f;
                var pinB = constraint.B < overlays.ClothPinWeights.Count ? overlays.ClothPinWeights[constraint.B] : 0.0f;
                if (pinA < 0.999f)
                {
                    _clothOverlayPositions[constraint.A] += correction * (1.0f - pinA);
                }
                if (pinB < 0.999f)
                {
                    _clothOverlayPositions[constraint.B] -= correction * (1.0f - pinB);
                }
            }
            ResolveClothOverlayColliders(overlays);
        }
    }

    private void ResolveClothOverlayColliders(NetPreviewOverlayState overlays)
    {
        for (var particleIndex = 0; particleIndex < _clothOverlayPositions.Count; particleIndex++)
        {
            var pinWeight = particleIndex < overlays.ClothPinWeights.Count
                ? overlays.ClothPinWeights[particleIndex]
                : 0.0f;
            if (pinWeight >= 0.999f)
            {
                continue;
            }
            var position = _clothOverlayPositions[particleIndex];
            foreach (var collider in overlays.ClothColliders)
            {
                if (collider.Kind == "sphere")
                {
                    position = PushOutsideSphere(position, collider.A, collider.Radius);
                }
                else if (collider.Kind == "capsule")
                {
                    var segment = collider.B - collider.A;
                    var denominator = segment.LengthSquared();
                    var t = denominator <= 0.000001f
                        ? 0.0f
                        : Math.Clamp(Vector3.Dot(position - collider.A, segment) / denominator, 0.0f, 1.0f);
                    position = PushOutsideSphere(position, collider.A + segment * t, collider.Radius);
                }
                else if (collider.Kind == "aabb")
                {
                    var minimum = Vector3.Min(collider.A, collider.B);
                    var maximum = Vector3.Max(collider.A, collider.B);
                    if (position.X >= minimum.X && position.X <= maximum.X
                        && position.Y >= minimum.Y && position.Y <= maximum.Y
                        && position.Z >= minimum.Z && position.Z <= maximum.Z)
                    {
                        var distances = new[]
                        {
                            (position.X - minimum.X, 0, minimum.X),
                            (maximum.X - position.X, 0, maximum.X),
                            (position.Y - minimum.Y, 1, minimum.Y),
                            (maximum.Y - position.Y, 1, maximum.Y),
                            (position.Z - minimum.Z, 2, minimum.Z),
                            (maximum.Z - position.Z, 2, maximum.Z),
                        };
                        var closest = distances.MinBy(item => item.Item1);
                        if (closest.Item2 == 0) position.X = closest.Item3;
                        else if (closest.Item2 == 1) position.Y = closest.Item3;
                        else position.Z = closest.Item3;
                    }
                }
            }
            _clothOverlayPositions[particleIndex] = position;
        }
    }

    private static Vector3 PushOutsideSphere(Vector3 position, Vector3 center, float radius)
    {
        if (radius <= 0.0f)
        {
            return position;
        }
        var delta = position - center;
        var length = delta.Length();
        if (length >= radius)
        {
            return position;
        }
        return center + (length <= 0.000001f ? Vector3.UnitY : delta / length) * radius;
    }

    private static void AddWorldCross(Vector3 center, float radius, List<Vector3> lines)
    {
        lines.Add(center - Vector3.UnitX * radius);
        lines.Add(center + Vector3.UnitX * radius);
        lines.Add(center - Vector3.UnitY * radius);
        lines.Add(center + Vector3.UnitY * radius);
        lines.Add(center - Vector3.UnitZ * radius);
        lines.Add(center + Vector3.UnitZ * radius);
    }

    private static void AddColliderLines(NetClothOverlayCollider collider, List<Vector3> lines)
    {
        if (collider.Kind == "aabb")
        {
            AddBoxLines(Vector3.Min(collider.A, collider.B), Vector3.Max(collider.A, collider.B), lines);
            return;
        }
        AddCircleLines(collider.A, collider.Radius, lines);
        if (collider.Kind == "capsule")
        {
            AddCircleLines(collider.B, collider.Radius, lines);
            lines.Add(collider.A + Vector3.UnitX * collider.Radius);
            lines.Add(collider.B + Vector3.UnitX * collider.Radius);
            lines.Add(collider.A - Vector3.UnitX * collider.Radius);
            lines.Add(collider.B - Vector3.UnitX * collider.Radius);
        }
    }

    private static void AddCircleLines(Vector3 center, float radius, List<Vector3> lines)
    {
        const int segments = 20;
        for (var axis = 0; axis < 3; axis++)
        {
            for (var segment = 0; segment < segments; segment++)
            {
                var a = segment * MathF.Tau / segments;
                var b = (segment + 1) * MathF.Tau / segments;
                Vector3 Point(float angle) => axis switch
                {
                    0 => center + new Vector3(0, MathF.Cos(angle), MathF.Sin(angle)) * radius,
                    1 => center + new Vector3(MathF.Cos(angle), 0, MathF.Sin(angle)) * radius,
                    _ => center + new Vector3(MathF.Cos(angle), MathF.Sin(angle), 0) * radius,
                };
                lines.Add(Point(a));
                lines.Add(Point(b));
            }
        }
    }

    private static void AddBoxLines(Vector3 minimum, Vector3 maximum, List<Vector3> lines)
    {
        var corners = new[]
        {
            new Vector3(minimum.X, minimum.Y, minimum.Z),
            new Vector3(maximum.X, minimum.Y, minimum.Z),
            new Vector3(maximum.X, maximum.Y, minimum.Z),
            new Vector3(minimum.X, maximum.Y, minimum.Z),
            new Vector3(minimum.X, minimum.Y, maximum.Z),
            new Vector3(maximum.X, minimum.Y, maximum.Z),
            new Vector3(maximum.X, maximum.Y, maximum.Z),
            new Vector3(minimum.X, maximum.Y, maximum.Z),
        };
        foreach (var (a, b) in new[]
        {
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        })
        {
            lines.Add(corners[a]);
            lines.Add(corners[b]);
        }
    }
}
