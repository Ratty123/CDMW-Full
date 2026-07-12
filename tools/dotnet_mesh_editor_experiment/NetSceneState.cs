using System.Numerics;
using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed class NetSceneState
{
    public int EditableSubmeshCount { get; private set; }
    public int ReferenceSubmeshCount { get; private set; }
    public string ComparisonMode { get; private set; } = "replacement_only";
    public string InteractionMode { get; private set; } = "placement";
    public bool GridVisible { get; private set; } = true;
    public Vector3 GridOrigin { get; private set; }
    public float GridSpacing { get; private set; } = 1.0f;
    public string GizmoTool { get; private set; } = "move";
    public bool GizmoVisible { get; private set; } = true;
    public Vector3 Translation { get; private set; }
    public Vector3 RotationDegrees { get; private set; }
    public Vector3 Scale { get; private set; } = Vector3.One;
    public float SceneExtent { get; private set; } = 2.0f;

    public static NetSceneState Load(string path, int documentSubmeshCount)
    {
        var state = new NetSceneState { EditableSubmeshCount = documentSubmeshCount };
        if (!File.Exists(path)) return state;
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        state.Apply(document.RootElement, documentSubmeshCount);
        return state;
    }

    public void Apply(JsonElement root, int documentSubmeshCount)
    {
        EditableSubmeshCount = Math.Clamp(JsonInt(root, "editable_submesh_count", EditableSubmeshCount), 0, documentSubmeshCount);
        ReferenceSubmeshCount = Math.Clamp(JsonInt(root, "reference_submesh_count", documentSubmeshCount - EditableSubmeshCount), 0, documentSubmeshCount - EditableSubmeshCount);
        ComparisonMode = NormalizeComparison(JsonText(root, "comparison_mode", ComparisonMode));
        InteractionMode = NormalizeInteraction(JsonText(root, "interaction_mode", InteractionMode));
        if (root.TryGetProperty("grid", out var grid) && grid.ValueKind == JsonValueKind.Object)
        {
            GridVisible = JsonBool(grid, "visible", GridVisible);
            GridOrigin = JsonVector(grid, "origin", GridOrigin);
            GridSpacing = Math.Clamp(JsonFloat(grid, "spacing", GridSpacing), 0.0001f, 100000.0f);
        }
        if (root.TryGetProperty("gizmo", out var gizmo) && gizmo.ValueKind == JsonValueKind.Object)
        {
            GizmoVisible = JsonBool(gizmo, "visible", GizmoVisible);
            GizmoTool = NormalizeGizmo(JsonText(gizmo, "tool", GizmoTool));
        }
        if (root.TryGetProperty("placement", out var placement) && placement.ValueKind == JsonValueKind.Object)
        {
            Translation = JsonVector(placement, "translation", Translation);
            RotationDegrees = JsonVector(placement, "rotation_degrees", RotationDegrees);
            Scale = ClampScale(JsonVector(placement, "scale", Scale));
        }
        if (root.TryGetProperty("bounds", out var bounds) && bounds.ValueKind == JsonValueKind.Object)
        {
            var min = JsonVector(bounds, "min", -Vector3.One);
            var max = JsonVector(bounds, "max", Vector3.One);
            SceneExtent = Math.Max(0.01f, Math.Max(max.X - min.X, Math.Max(max.Y - min.Y, max.Z - min.Z)));
        }
    }

    public bool IsEditable(int submeshIndex) => submeshIndex >= 0 && submeshIndex < EditableSubmeshCount;
    public bool IsReference(int submeshIndex) => submeshIndex >= EditableSubmeshCount && submeshIndex < EditableSubmeshCount + ReferenceSubmeshCount;

    public bool IsVisible(int submeshIndex) => ComparisonMode switch
    {
        "original_only" => IsReference(submeshIndex),
        "replacement_only" => IsEditable(submeshIndex),
        _ => IsEditable(submeshIndex) || IsReference(submeshIndex),
    };

    public void SetComparisonMode(string value) => ComparisonMode = NormalizeComparison(value);
    public void SetGizmoTool(string value) => GizmoTool = NormalizeGizmo(value);

    public void ApplyGizmoDrag(Vector3 startTranslation, Vector3 startRotation, Vector3 startScale, float dx, float dy)
    {
        if (GizmoTool == "rotate")
        {
            RotationDegrees = startRotation + new Vector3(-dy * 0.35f, dx * 0.35f, 0.0f);
            return;
        }
        if (GizmoTool == "scale")
        {
            var factor = MathF.Exp(-dy * 0.01f);
            Scale = ClampScale(startScale * factor);
            return;
        }
        var unitsPerPixel = SceneExtent / 500.0f;
        Translation = startTranslation + new Vector3(dx * unitsPerPixel, -dy * unitsPerPixel, 0.0f);
    }

    public Dictionary<string, object?> PlacementPayload() => new()
    {
        ["translation"] = new[] { Translation.X, Translation.Y, Translation.Z },
        ["rotation_degrees"] = new[] { RotationDegrees.X, RotationDegrees.Y, RotationDegrees.Z },
        ["scale"] = new[] { Scale.X, Scale.Y, Scale.Z },
    };

    public Matrix4x4 ModelMatrix(int submeshIndex)
    {
        if (IsReference(submeshIndex))
        {
            return ComparisonMode == "side_by_side"
                ? Matrix4x4.CreateTranslation(-SceneExtent * 0.6f, 0.0f, 0.0f)
                : Matrix4x4.Identity;
        }
        if (!IsEditable(submeshIndex)) return Matrix4x4.Identity;
        var rotation = RotationDegrees * (MathF.PI / 180.0f);
        var placement = Matrix4x4.CreateScale(Scale)
            * Matrix4x4.CreateFromYawPitchRoll(rotation.Y, rotation.X, rotation.Z)
            * Matrix4x4.CreateTranslation(Translation);
        return ComparisonMode == "side_by_side"
            ? placement * Matrix4x4.CreateTranslation(SceneExtent * 0.6f, 0.0f, 0.0f)
            : placement;
    }

    private static string NormalizeComparison(string value) => value.Trim().ToLowerInvariant() switch
    {
        "side_by_side" => "side_by_side",
        "overlay" or "ghost" => "overlay",
        "original_only" or "source" => "original_only",
        _ => "replacement_only",
    };
    private static string NormalizeInteraction(string value) => value.Trim().ToLowerInvariant() == "mesh_edit" ? "mesh_edit" : "placement";
    private static string NormalizeGizmo(string value) => value.Trim().ToLowerInvariant() switch { "rotate" => "rotate", "scale" => "scale", _ => "move" };
    private static Vector3 ClampScale(Vector3 value) => new(Math.Clamp(value.X, 0.001f, 100.0f), Math.Clamp(value.Y, 0.001f, 100.0f), Math.Clamp(value.Z, 0.001f, 100.0f));
    private static int JsonInt(JsonElement root, string name, int fallback) => root.TryGetProperty(name, out var value) && value.TryGetInt32(out var result) ? result : fallback;
    private static float JsonFloat(JsonElement root, string name, float fallback) => root.TryGetProperty(name, out var value) && value.TryGetSingle(out var result) && float.IsFinite(result) ? result : fallback;
    private static bool JsonBool(JsonElement root, string name, bool fallback) => root.TryGetProperty(name, out var value) && value.ValueKind is JsonValueKind.True or JsonValueKind.False ? value.GetBoolean() : fallback;
    private static string JsonText(JsonElement root, string name, string fallback) => root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? fallback : fallback;
    private static Vector3 JsonVector(JsonElement root, string name, Vector3 fallback)
    {
        if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array) return fallback;
        var values = value.EnumerateArray().Take(3).Select(item => item.TryGetSingle(out var number) && float.IsFinite(number) ? number : 0.0f).ToArray();
        return values.Length == 3 ? new Vector3(values[0], values[1], values[2]) : fallback;
    }
}
