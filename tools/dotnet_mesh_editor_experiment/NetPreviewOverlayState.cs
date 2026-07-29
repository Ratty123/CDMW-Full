using System.Numerics;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed record NetSkeletonOverlayBone(
    int Index,
    int ParentIndex,
    Vector3 Position,
    Vector3 ParentPosition,
    bool HasParentPosition);

internal sealed record NetClothOverlayConstraint(int A, int B);

internal sealed record NetClothOverlayCollider(
    string Kind,
    Vector3 A,
    Vector3 B,
    float Radius);

internal sealed class NetPreviewOverlayState
{
    public bool SkeletonVisible { get; private set; }
    public bool SkeletonPoseVisible { get; private set; }
    public int SelectedBoneIndex { get; private set; } = -1;
    public List<NetSkeletonOverlayBone> SkeletonBones { get; } = new();
    public bool ClothEnabled { get; private set; }
    public bool ClothPaused { get; private set; }
    public bool ClothShowPins { get; private set; }
    public bool ClothShowColliders { get; private set; }
    public float ClothWindStrength { get; private set; }
    public float ClothWindDirectionDegrees { get; private set; } = 35.0f;
    public long ClothResetGeneration { get; private set; }
    public List<Vector3> ClothParticles { get; } = new();
    public List<float> ClothPinWeights { get; } = new();
    public List<NetClothOverlayConstraint> ClothConstraints { get; } = new();
    public List<NetClothOverlayCollider> ClothColliders { get; } = new();

    public void ApplySceneMetadata(JsonElement root)
    {
        var overlays = Object(root, "overlays");
        var skeleton = Object(root, "skeleton_overlay") ?? (overlays is JsonElement overlayRoot ? Object(overlayRoot, "skeleton") : null);
        if (skeleton is JsonElement skeletonRoot)
        {
            SkeletonBones.Clear();
            SkeletonVisible = Bool(skeletonRoot, "enabled", false);
            SkeletonPoseVisible = Bool(skeletonRoot, "pose_enabled", false);
            SelectedBoneIndex = Int(skeletonRoot, "selected_bone_index", -1);
            var positions = new Dictionary<int, Vector3>();
            if (skeletonRoot.TryGetProperty("bones", out var bones) && bones.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in bones.EnumerateArray().Take(4096))
                {
                    if (item.ValueKind != JsonValueKind.Object)
                    {
                        continue;
                    }
                    var index = Int(item, "index", -1);
                    if (index < 0 || Vector(item, "position") is not Vector3 position)
                    {
                        continue;
                    }
                    positions[index] = position;
                    var parent = Vector(item, "parent_position");
                    SkeletonBones.Add(new NetSkeletonOverlayBone(
                        index,
                        Int(item, "parent_index", -1),
                        position,
                        parent ?? default,
                        parent.HasValue));
                }
            }
            for (var index = 0; index < SkeletonBones.Count; index++)
            {
                var bone = SkeletonBones[index];
                if (!bone.HasParentPosition
                    && bone.ParentIndex >= 0
                    && positions.TryGetValue(bone.ParentIndex, out var parent))
                {
                    SkeletonBones[index] = bone with { ParentPosition = parent, HasParentPosition = true };
                }
            }
            SkeletonVisible &= SkeletonBones.Count > 0;
        }

        var cloth = Object(root, "cloth_overlay") ?? (overlays is JsonElement clothOverlayRoot ? Object(clothOverlayRoot, "cloth") : null);
        if (cloth is not JsonElement clothRoot)
        {
            return;
        }
        ClothParticles.Clear();
        ClothPinWeights.Clear();
        ClothConstraints.Clear();
        ClothColliders.Clear();
        ClothEnabled = Bool(clothRoot, "enabled", false);
        ClothPaused = Bool(clothRoot, "paused", false);
        ClothShowPins = Bool(clothRoot, "show_pins", false);
        ClothShowColliders = Bool(clothRoot, "show_colliders", false);
        ClothWindStrength = Math.Clamp(Float(clothRoot, "wind_strength", 0.0f), 0.0f, 2.0f);
        ClothWindDirectionDegrees = Math.Clamp(Float(clothRoot, "wind_direction_degrees", 35.0f), -180.0f, 180.0f);
        ClothResetGeneration = Math.Max(0, Long(clothRoot, "reset_generation", 0));
        if (clothRoot.TryGetProperty("particles", out var particles) && particles.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in particles.EnumerateArray().Take(2_000_000))
            {
                if (ArrayVector(item) is Vector3 particle)
                {
                    ClothParticles.Add(particle);
                }
            }
        }
        if (clothRoot.TryGetProperty("pin_weights", out var pins) && pins.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in pins.EnumerateArray().Take(ClothParticles.Count))
            {
                ClothPinWeights.Add(item.TryGetSingle(out var value) && float.IsFinite(value)
                    ? Math.Clamp(value, 0.0f, 1.0f)
                    : 0.0f);
            }
        }
        while (ClothPinWeights.Count < ClothParticles.Count)
        {
            ClothPinWeights.Add(0.0f);
        }
        if (clothRoot.TryGetProperty("constraints", out var constraints) && constraints.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in constraints.EnumerateArray().Take(4_000_000))
            {
                if (Constraint(item) is NetClothOverlayConstraint constraint
                    && constraint.A >= 0
                    && constraint.B >= 0
                    && constraint.A < ClothParticles.Count
                    && constraint.B < ClothParticles.Count
                    && constraint.A != constraint.B)
                {
                    ClothConstraints.Add(constraint);
                }
            }
        }
        if (clothRoot.TryGetProperty("colliders", out var colliders) && colliders.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in colliders.EnumerateArray().Take(4096))
            {
                if (Collider(item) is NetClothOverlayCollider collider)
                {
                    ClothColliders.Add(collider);
                }
            }
        }
        ClothEnabled &= ClothParticles.Count > 0;
    }

    public bool ApplyControlUpdate(JsonElement root, out string reason)
    {
        reason = string.Empty;
        var changed = false;
        if (Object(root, "skeleton") is JsonElement skeleton)
        {
            SkeletonVisible = Bool(skeleton, "visible", SkeletonVisible) && SkeletonBones.Count > 0;
            SkeletonPoseVisible = Bool(skeleton, "pose_visible", SkeletonPoseVisible);
            SelectedBoneIndex = Int(skeleton, "selected_bone_index", SelectedBoneIndex);
            changed = true;
        }
        if (Object(root, "cloth") is JsonElement cloth)
        {
            ClothEnabled = Bool(cloth, "enabled", ClothEnabled) && ClothParticles.Count > 0;
            ClothPaused = Bool(cloth, "paused", ClothPaused);
            ClothShowPins = Bool(cloth, "show_pins", ClothShowPins);
            ClothShowColliders = Bool(cloth, "show_colliders", ClothShowColliders);
            ClothWindStrength = Math.Clamp(Float(cloth, "wind_strength", ClothWindStrength), 0.0f, 2.0f);
            ClothWindDirectionDegrees = Math.Clamp(
                Float(cloth, "wind_direction_degrees", ClothWindDirectionDegrees),
                -180.0f,
                180.0f);
            ClothResetGeneration = Math.Max(
                ClothResetGeneration,
                Long(cloth, "reset_generation", ClothResetGeneration));
            changed = true;
        }
        if (!changed)
        {
            reason = "overlay_state_missing";
        }
        return changed;
    }

    public Dictionary<string, object?> StatusPayload() => new()
    {
        ["skeleton"] = new Dictionary<string, object?>
        {
            ["visible"] = SkeletonVisible,
            ["pose_visible"] = SkeletonPoseVisible,
            ["selected_bone_index"] = SelectedBoneIndex,
            ["bone_count"] = SkeletonBones.Count,
        },
        ["cloth"] = new Dictionary<string, object?>
        {
            ["enabled"] = ClothEnabled,
            ["paused"] = ClothPaused,
            ["show_pins"] = ClothShowPins,
            ["show_colliders"] = ClothShowColliders,
            ["wind_strength"] = ClothWindStrength,
            ["wind_direction_degrees"] = ClothWindDirectionDegrees,
            ["reset_generation"] = ClothResetGeneration,
            ["particle_count"] = ClothParticles.Count,
            ["constraint_count"] = ClothConstraints.Count,
            ["collider_count"] = ClothColliders.Count,
        },
    };

    public NetPreviewOverlayState Clone()
    {
        var clone = new NetPreviewOverlayState
        {
            SkeletonVisible = SkeletonVisible,
            SkeletonPoseVisible = SkeletonPoseVisible,
            SelectedBoneIndex = SelectedBoneIndex,
            ClothEnabled = ClothEnabled,
            ClothPaused = ClothPaused,
            ClothShowPins = ClothShowPins,
            ClothShowColliders = ClothShowColliders,
            ClothWindStrength = ClothWindStrength,
            ClothWindDirectionDegrees = ClothWindDirectionDegrees,
            ClothResetGeneration = ClothResetGeneration,
        };
        clone.SkeletonBones.AddRange(SkeletonBones);
        clone.ClothParticles.AddRange(ClothParticles);
        clone.ClothPinWeights.AddRange(ClothPinWeights);
        clone.ClothConstraints.AddRange(ClothConstraints);
        clone.ClothColliders.AddRange(ClothColliders);
        return clone;
    }

    private static JsonElement? Object(JsonElement root, string name) =>
        root.ValueKind == JsonValueKind.Object
        && root.TryGetProperty(name, out var value)
        && value.ValueKind == JsonValueKind.Object
            ? value
            : null;

    private static bool Bool(JsonElement root, string name, bool fallback) =>
        root.TryGetProperty(name, out var value)
        && value.ValueKind is JsonValueKind.True or JsonValueKind.False
            ? value.GetBoolean()
            : fallback;

    private static int Int(JsonElement root, string name, int fallback) =>
        root.TryGetProperty(name, out var value) && value.TryGetInt32(out var result) ? result : fallback;

    private static long Long(JsonElement root, string name, long fallback) =>
        root.TryGetProperty(name, out var value) && value.TryGetInt64(out var result) ? result : fallback;

    private static float Float(JsonElement root, string name, float fallback) =>
        root.TryGetProperty(name, out var value) && value.TryGetSingle(out var result) && float.IsFinite(result)
            ? result
            : fallback;

    private static Vector3? Vector(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) ? ArrayVector(value) : null;

    private static Vector3? ArrayVector(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.Array)
        {
            return null;
        }
        var values = value.EnumerateArray().Take(3)
            .Select(item => item.TryGetSingle(out var number) && float.IsFinite(number) ? number : float.NaN)
            .ToArray();
        return values.Length == 3 && values.All(float.IsFinite)
            ? new Vector3(values[0], values[1], values[2])
            : null;
    }

    private static NetClothOverlayConstraint? Constraint(JsonElement item)
    {
        if (item.ValueKind == JsonValueKind.Array)
        {
            var values = item.EnumerateArray().Take(2)
                .Select(value => value.TryGetInt32(out var number) ? number : -1)
                .ToArray();
            return values.Length == 2 ? new NetClothOverlayConstraint(values[0], values[1]) : null;
        }
        if (item.ValueKind == JsonValueKind.Object)
        {
            return new NetClothOverlayConstraint(Int(item, "a", -1), Int(item, "b", -1));
        }
        return null;
    }

    private static NetClothOverlayCollider? Collider(JsonElement item)
    {
        if (item.ValueKind != JsonValueKind.Object)
        {
            return null;
        }
        var kind = item.TryGetProperty("kind", out var kindValue) ? kindValue.GetString() ?? string.Empty : string.Empty;
        kind = kind.Trim().ToLowerInvariant();
        if (kind is not ("sphere" or "capsule" or "aabb"))
        {
            return null;
        }
        var a = Vector(item, "a") ?? Vector(item, "center") ?? Vector3.Zero;
        var b = Vector(item, "b") ?? Vector(item, "maximum") ?? a;
        return new NetClothOverlayCollider(kind, a, b, Math.Max(0.0f, Float(item, "radius", 0.0f)));
    }
}
