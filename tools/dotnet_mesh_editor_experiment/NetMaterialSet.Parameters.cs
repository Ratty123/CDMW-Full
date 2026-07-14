using System.Globalization;
using System.IO;
using System.Numerics;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class NetMaterialSet
{
    private IReadOnlyDictionary<int, NetMaterialParameters> ParameterStates { get; set; }
        = new Dictionary<int, NetMaterialParameters>();

    public NetMaterialParameters ParametersForSubmesh(int submeshIndex)
    {
        return ParameterStates.TryGetValue(submeshIndex, out var parameters)
            ? parameters
            : NetMaterialParameters.Empty;
    }

    public int ParameterStateCount => ParameterStates.Count;

    public IReadOnlyDictionary<string, string> ParameterRoles => ParameterStates
        .Where(pair => !string.IsNullOrWhiteSpace(pair.Value.MaterialRole))
        .ToDictionary(
            pair => pair.Key.ToString(CultureInfo.InvariantCulture),
            pair => pair.Value.MaterialRole!,
            StringComparer.Ordinal);

    public IReadOnlyDictionary<int, NetMaterialParameters> CaptureParameterState()
    {
        return ParameterStates;
    }

    public void ReplaceParameterState(IReadOnlyDictionary<int, NetMaterialParameters> state)
    {
        ParameterStates = state;
    }

    private void LoadInitialParameterStates(JsonElement root)
    {
        if (!root.TryGetProperty("submeshes", out var submeshes) || submeshes.ValueKind != JsonValueKind.Array)
        {
            return;
        }
        var states = new Dictionary<int, NetMaterialParameters>();
        foreach (var item in submeshes.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object
                || !item.TryGetProperty("parameters", out var parameters)
                || parameters.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var state = NetMaterialParameters.Empty.Apply(ParseParameterDelta(parameters));
            if (!state.IsEmpty)
            {
                states[JsonInt(item, "submesh_index", states.Count)] = state;
            }
        }
        ParameterStates = states;
    }

    public void ApplyParameterUpdate(NetMaterialParameterUpdate update)
    {
        var next = new Dictionary<int, NetMaterialParameters>(ParameterStates);
        foreach (var group in update.Groups)
        {
            foreach (var submeshIndex in group.SubmeshIndices)
            {
                var current = next.TryGetValue(submeshIndex, out var existing)
                    ? existing
                    : NetMaterialParameters.Empty;
                var updated = current.Apply(group.Parameters);
                if (updated.IsEmpty)
                {
                    next.Remove(submeshIndex);
                }
                else
                {
                    next[submeshIndex] = updated;
                }
            }
        }
        ParameterStates = next;
    }

    public static NetMaterialParameterUpdate ParseParameterUpdate(JsonElement root)
    {
        const string expectedSchema = "cdmw_mesh_material_parameters_v1";
        var schema = JsonText(root, "schema");
        var version = RequiredParameterLong(root, "version");
        if (!string.Equals(schema, expectedSchema, StringComparison.Ordinal))
        {
            throw new InvalidDataException($"Unsupported material parameter schema: {schema}");
        }
        if (version != 1)
        {
            throw new InvalidDataException($"Unsupported material parameter version: {version}");
        }
        var editRevision = RequiredParameterLong(root, "edit_revision");
        var parameterGeneration = RequiredParameterLong(root, "parameter_generation");
        if (!TryGetParameterGroups(root, out var groupArray))
        {
            throw new InvalidDataException("Material parameter update requires a non-empty groups array.");
        }

        var groups = new List<NetMaterialParameterGroup>();
        var affected = new HashSet<int>();
        foreach (var item in groupArray.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidDataException("Material parameter groups must be objects.");
            }
            ValidateParameterGroupFields(item);
            if (!string.Equals(JsonText(item, "editor_role"), "replacement_preview", StringComparison.Ordinal))
            {
                throw new InvalidDataException("Material parameter groups require editor_role replacement_preview.");
            }
            var indices = ParameterGroupIndices(item);
            var appliesToAll = indices.Count == 0;
            if (!appliesToAll && indices.Any(index => !affected.Add(index)))
            {
                throw new InvalidDataException("A submesh may appear in only one material parameter group.");
            }
            var parameters = ParseParameterDelta(item);
            if (!parameters.HasChanges)
            {
                throw new InvalidDataException("Material parameter groups require at least one parameter change.");
            }
            groups.Add(new NetMaterialParameterGroup(indices, appliesToAll, parameters));
        }
        if (groups.Any(group => group.AppliesToAll) && groups.Count != 1)
        {
            throw new InvalidDataException("An all-submesh material parameter group must be the only group.");
        }
        return new NetMaterialParameterUpdate(
            JsonText(root, "session_id"), editRevision, parameterGeneration, groups, affected.Order().ToArray());
    }

    private static long RequiredParameterLong(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var value)
            || value.ValueKind != JsonValueKind.Number
            || !value.TryGetInt64(out var number))
        {
            throw new InvalidDataException($"Material parameter update requires integer {name}.");
        }
        return number;
    }

    private static bool TryGetParameterGroups(JsonElement root, out JsonElement groups)
    {
        foreach (var name in new[] { "groups", "material_override_groups" })
        {
            if (root.TryGetProperty(name, out groups)
                && groups.ValueKind == JsonValueKind.Array
                && groups.GetArrayLength() > 0)
            {
                return true;
            }
        }
        groups = default;
        return false;
    }

    private static IReadOnlyList<int> ParameterGroupIndices(JsonElement group)
    {
        var present = new[] { "source_submesh_indices", "submesh_indices", "affected_submeshes" }
            .Where(name => group.TryGetProperty(name, out _))
            .ToArray();
        if (present.Length > 1)
        {
            throw new InvalidDataException("Material parameter group has conflicting submesh fields.");
        }
        if (present.Length == 0)
        {
            throw new InvalidDataException("Material parameter groups require a submesh field; an empty array means all submeshes.");
        }
        if (!group.TryGetProperty(present[0], out var value) || value.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidDataException("Material parameter submesh fields must be arrays.");
        }
        var result = new List<int>();
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Number
                || !item.TryGetInt32(out var index)
                || index < 0
                || result.Contains(index))
            {
                throw new InvalidDataException("Material parameter submesh indices must be unique non-negative integers.");
            }
            result.Add(index);
        }
        return result;
    }

    private static NetMaterialParameterDelta ParseParameterDelta(JsonElement group)
    {
        return new NetMaterialParameterDelta
        {
            TextureBrightness = OptionalFloat(group, "texture_brightness", 0.1f, 3.0f, "brightness"),
            Contrast = OptionalFloat(group, "contrast", 0.25f, 2.5f),
            PostContrastBrightness = OptionalFloat(group, "post_contrast_brightness", 0.0f, 4.0f),
            Saturation = OptionalFloat(group, "saturation", 0.0f, 4.0f),
            Gamma = OptionalFloat(group, "gamma", 0.25f, 4.0f),
            TintColor = OptionalColor(group, "tint_color", 0.0f, 4.0f, "tint"),
            BaseColorLift = OptionalInteger(group, "base_color_lift", 0, 254),
            ValueMax = OptionalInteger(group, "value_max", 0, 255),
            AutoBalance = OptionalInteger(group, "auto_balance", 0, 100),
            ShadowLift = OptionalInteger(group, "shadow_lift", 0, 100),
            Roughness = OptionalFloat(group, "roughness", 0.0f, 1.0f),
            Metalness = OptionalFloat(group, "metalness", 0.0f, 1.0f, "metallic"),
            Specular = OptionalFloat(group, "specular", 0.0f, 1.0f),
            RoughnessInverted = OptionalBoolean(group, "roughness_inverted", "roughness_invert"),
            MetalnessInverted = OptionalBoolean(group, "metalness_inverted", "metallic_inverted", "metalness_invert", "metallic_invert"),
            RoughnessScale = OptionalFloat(group, "roughness_scale", 0.0f, 4.0f),
            RoughnessMin = OptionalInteger(group, "roughness_min", 0, 255),
            RoughnessMax = OptionalInteger(group, "roughness_max", 0, 255),
            MetalnessScale = OptionalFloat(group, "metalness_scale", 0.0f, 4.0f, "metallic_scale"),
            MetalnessMin = OptionalInteger(group, "metalness_min", 0, 255, "metallic_min"),
            MetalnessMax = OptionalInteger(group, "metalness_max", 0, 255, "metallic_max"),
            RoughnessBlendTarget = OptionalFloat(group, "roughness_blend_target", 0.0f, 1.0f),
            RoughnessBlendStrength = OptionalFloat(group, "roughness_blend_strength", 0.0f, 1.0f),
            MetalnessBlendTarget = OptionalFloat(group, "metalness_blend_target", 0.0f, 1.0f, "metallic_blend_target"),
            MetalnessBlendStrength = OptionalFloat(group, "metalness_blend_strength", 0.0f, 1.0f, "metallic_blend_strength"),
            HeightScale = OptionalFloat(group, "height_scale", 0.0f, 1.0f, "height"),
            EmissiveIntensity = OptionalFloat(group, "emissive_intensity", 0.0f, 32.0f),
            EmissiveColor = OptionalColor(group, "emissive_color", 0.0f, 2.0f),
            EmissiveScalarMask = OptionalBoolean(group, "emissive_scalar_mask"),
            MaterialRole = OptionalMaterialRole(group),
            Visible = OptionalBoolean(group, "visible"),
        };
    }

    private static NetOptionalTextParameter OptionalMaterialRole(JsonElement group)
    {
        if (!group.TryGetProperty("material_role", out var value))
        {
            return default;
        }
        if (value.ValueKind == JsonValueKind.Null)
        {
            return new NetOptionalTextParameter(true, null);
        }
        if (value.ValueKind != JsonValueKind.String)
        {
            throw new InvalidDataException("Material parameter material_role must be a string or null.");
        }
        var role = (value.GetString() ?? string.Empty).Trim().ToLowerInvariant();
        if (role.Length is 0 or > 64
            || role.Any(character => !(char.IsLetterOrDigit(character) || character is '_' or '-')))
        {
            throw new InvalidDataException("Material parameter material_role must be 1-64 letters, digits, underscores, or hyphens.");
        }
        return new NetOptionalTextParameter(true, role);
    }

    private static NetOptionalParameter<float> OptionalFloat(
        JsonElement group,
        string name,
        float minimum,
        float maximum,
        params string[] aliases)
    {
        var propertyName = OptionalPropertyName(group, name, aliases);
        if (propertyName.Length == 0)
        {
            return default;
        }
        var value = group.GetProperty(propertyName);
        if (value.ValueKind == JsonValueKind.Null)
        {
            return new NetOptionalParameter<float>(true, null);
        }
        if (value.ValueKind != JsonValueKind.Number
            || !value.TryGetDouble(out var number)
            || !double.IsFinite(number)
            || number < minimum
            || number > maximum)
        {
            throw new InvalidDataException($"Material parameter {propertyName} must be finite and between {minimum} and {maximum}.");
        }
        return new NetOptionalParameter<float>(true, (float)number);
    }

    private static NetOptionalParameter<int> OptionalInteger(
        JsonElement group,
        string name,
        int minimum,
        int maximum,
        params string[] aliases)
    {
        var propertyName = OptionalPropertyName(group, name, aliases);
        if (propertyName.Length == 0)
        {
            return default;
        }
        var value = group.GetProperty(propertyName);
        if (value.ValueKind == JsonValueKind.Null)
        {
            return new NetOptionalParameter<int>(true, null);
        }
        if (value.ValueKind != JsonValueKind.Number
            || !value.TryGetInt32(out var number)
            || number < minimum
            || number > maximum)
        {
            throw new InvalidDataException($"Material parameter {propertyName} must be an integer between {minimum} and {maximum}.");
        }
        return new NetOptionalParameter<int>(true, number);
    }

    private static NetOptionalParameter<bool> OptionalBoolean(
        JsonElement group,
        string name,
        params string[] aliases)
    {
        var propertyName = OptionalPropertyName(group, name, aliases);
        if (propertyName.Length == 0)
        {
            return default;
        }
        var value = group.GetProperty(propertyName);
        if (value.ValueKind == JsonValueKind.Null)
        {
            return new NetOptionalParameter<bool>(true, null);
        }
        if (value.ValueKind is not JsonValueKind.True and not JsonValueKind.False)
        {
            throw new InvalidDataException($"Material parameter {propertyName} must be a boolean or null.");
        }
        return new NetOptionalParameter<bool>(true, value.GetBoolean());
    }

    private static NetOptionalParameter<Vector3> OptionalColor(
        JsonElement group,
        string name,
        float minimum,
        float maximum,
        params string[] aliases)
    {
        var propertyName = OptionalPropertyName(group, name, aliases);
        if (propertyName.Length == 0)
        {
            return default;
        }
        var value = group.GetProperty(propertyName);
        if (value.ValueKind == JsonValueKind.Null)
        {
            return new NetOptionalParameter<Vector3>(true, null);
        }
        if (value.ValueKind != JsonValueKind.Array || value.GetArrayLength() != 3)
        {
            throw new InvalidDataException($"Material parameter {propertyName} must contain exactly three numbers.");
        }
        var components = value.EnumerateArray().Select(component =>
        {
            if (component.ValueKind != JsonValueKind.Number
                || !component.TryGetDouble(out var number)
                || !double.IsFinite(number)
                || number < minimum
                || number > maximum)
            {
                throw new InvalidDataException($"Material parameter {propertyName} components must be finite and between {minimum} and {maximum}.");
            }
            return (float)number;
        }).ToArray();
        return new NetOptionalParameter<Vector3>(true, new Vector3(components[0], components[1], components[2]));
    }

    private static string OptionalPropertyName(JsonElement group, string name, params string[] aliases)
    {
        var present = aliases.Prepend(name).Where(property => group.TryGetProperty(property, out _)).ToArray();
        if (present.Length > 1)
        {
            throw new InvalidDataException($"Material parameter aliases cannot both be present: {string.Join(", ", present)}.");
        }
        return present.FirstOrDefault() ?? string.Empty;
    }

    private static void ValidateParameterGroupFields(JsonElement group)
    {
        var allowed = new HashSet<string>(StringComparer.Ordinal)
        {
            "source_submesh_indices", "submesh_indices", "affected_submeshes",
            "editor_role", "material_name", "texture_name",
            "texture_brightness", "brightness", "contrast", "post_contrast_brightness", "saturation", "gamma",
            "tint_color", "tint", "base_color_lift", "value_max", "auto_balance", "shadow_lift",
            "roughness", "metalness", "metallic", "specular",
            "roughness_inverted", "roughness_invert", "metalness_inverted", "metallic_inverted", "metalness_invert", "metallic_invert",
            "roughness_scale", "roughness_min", "roughness_max",
            "metalness_scale", "metallic_scale", "metalness_min", "metallic_min", "metalness_max", "metallic_max",
            "roughness_blend_target", "roughness_blend_strength",
            "metalness_blend_target", "metallic_blend_target", "metalness_blend_strength", "metallic_blend_strength",
            "height_scale", "height", "emissive_intensity", "emissive_color", "emissive_scalar_mask", "material_role", "visible",
        };
        var unsupported = group.EnumerateObject()
            .Select(property => property.Name)
            .FirstOrDefault(name => !allowed.Contains(name));
        if (!string.IsNullOrWhiteSpace(unsupported))
        {
            throw new InvalidDataException($"Unsupported material parameter field: {unsupported}");
        }
    }
}

internal readonly record struct NetOptionalParameter<T>(bool IsSpecified, T? Value)
    where T : struct
{
    public T? Apply(T? current) => IsSpecified ? Value : current;
}

internal readonly record struct NetOptionalTextParameter(bool IsSpecified, string? Value)
{
    public string? Apply(string? current) => IsSpecified ? Value : current;
}

internal readonly record struct NetMaterialParameterDelta
{
    public NetOptionalParameter<float> TextureBrightness { get; init; }
    public NetOptionalParameter<float> Contrast { get; init; }
    public NetOptionalParameter<float> PostContrastBrightness { get; init; }
    public NetOptionalParameter<float> Saturation { get; init; }
    public NetOptionalParameter<float> Gamma { get; init; }
    public NetOptionalParameter<Vector3> TintColor { get; init; }
    public NetOptionalParameter<int> BaseColorLift { get; init; }
    public NetOptionalParameter<int> ValueMax { get; init; }
    public NetOptionalParameter<int> AutoBalance { get; init; }
    public NetOptionalParameter<int> ShadowLift { get; init; }
    public NetOptionalParameter<float> Roughness { get; init; }
    public NetOptionalParameter<float> Metalness { get; init; }
    public NetOptionalParameter<float> Specular { get; init; }
    public NetOptionalParameter<bool> RoughnessInverted { get; init; }
    public NetOptionalParameter<bool> MetalnessInverted { get; init; }
    public NetOptionalParameter<float> RoughnessScale { get; init; }
    public NetOptionalParameter<int> RoughnessMin { get; init; }
    public NetOptionalParameter<int> RoughnessMax { get; init; }
    public NetOptionalParameter<float> MetalnessScale { get; init; }
    public NetOptionalParameter<int> MetalnessMin { get; init; }
    public NetOptionalParameter<int> MetalnessMax { get; init; }
    public NetOptionalParameter<float> RoughnessBlendTarget { get; init; }
    public NetOptionalParameter<float> RoughnessBlendStrength { get; init; }
    public NetOptionalParameter<float> MetalnessBlendTarget { get; init; }
    public NetOptionalParameter<float> MetalnessBlendStrength { get; init; }
    public NetOptionalParameter<float> HeightScale { get; init; }
    public NetOptionalParameter<float> EmissiveIntensity { get; init; }
    public NetOptionalParameter<Vector3> EmissiveColor { get; init; }
    public NetOptionalParameter<bool> EmissiveScalarMask { get; init; }
    public NetOptionalTextParameter MaterialRole { get; init; }
    public NetOptionalParameter<bool> Visible { get; init; }

    public bool HasChanges =>
        TextureBrightness.IsSpecified || Contrast.IsSpecified || PostContrastBrightness.IsSpecified
        || Saturation.IsSpecified || Gamma.IsSpecified || TintColor.IsSpecified || BaseColorLift.IsSpecified
        || ValueMax.IsSpecified || AutoBalance.IsSpecified || ShadowLift.IsSpecified || Roughness.IsSpecified
        || Metalness.IsSpecified || Specular.IsSpecified || RoughnessInverted.IsSpecified || MetalnessInverted.IsSpecified
        || RoughnessScale.IsSpecified || RoughnessMin.IsSpecified || RoughnessMax.IsSpecified
        || MetalnessScale.IsSpecified || MetalnessMin.IsSpecified || MetalnessMax.IsSpecified
        || RoughnessBlendTarget.IsSpecified || RoughnessBlendStrength.IsSpecified
        || MetalnessBlendTarget.IsSpecified || MetalnessBlendStrength.IsSpecified
        || HeightScale.IsSpecified || EmissiveIntensity.IsSpecified || EmissiveColor.IsSpecified || EmissiveScalarMask.IsSpecified
        || MaterialRole.IsSpecified || Visible.IsSpecified;
}

internal readonly record struct NetMaterialParameters
{
    public float? TextureBrightness { get; init; }
    public float? Contrast { get; init; }
    public float? PostContrastBrightness { get; init; }
    public float? Saturation { get; init; }
    public float? Gamma { get; init; }
    public Vector3? TintColor { get; init; }
    public int? BaseColorLift { get; init; }
    public int? ValueMax { get; init; }
    public int? AutoBalance { get; init; }
    public int? ShadowLift { get; init; }
    public float? Roughness { get; init; }
    public float? Metalness { get; init; }
    public float? Specular { get; init; }
    public bool? RoughnessInverted { get; init; }
    public bool? MetalnessInverted { get; init; }
    public float? RoughnessScale { get; init; }
    public int? RoughnessMin { get; init; }
    public int? RoughnessMax { get; init; }
    public float? MetalnessScale { get; init; }
    public int? MetalnessMin { get; init; }
    public int? MetalnessMax { get; init; }
    public float? RoughnessBlendTarget { get; init; }
    public float? RoughnessBlendStrength { get; init; }
    public float? MetalnessBlendTarget { get; init; }
    public float? MetalnessBlendStrength { get; init; }
    public float? HeightScale { get; init; }
    public float? EmissiveIntensity { get; init; }
    public Vector3? EmissiveColor { get; init; }
    public bool? EmissiveScalarMask { get; init; }
    public string? MaterialRole { get; init; }
    public bool? Visible { get; init; }

    public static NetMaterialParameters Empty => default;
    public bool IsEmpty => this == Empty;

    public NetMaterialParameters Apply(NetMaterialParameterDelta delta)
    {
        return new NetMaterialParameters
        {
            TextureBrightness = delta.TextureBrightness.Apply(TextureBrightness),
            Contrast = delta.Contrast.Apply(Contrast),
            PostContrastBrightness = delta.PostContrastBrightness.Apply(PostContrastBrightness),
            Saturation = delta.Saturation.Apply(Saturation),
            Gamma = delta.Gamma.Apply(Gamma),
            TintColor = delta.TintColor.Apply(TintColor),
            BaseColorLift = delta.BaseColorLift.Apply(BaseColorLift),
            ValueMax = delta.ValueMax.Apply(ValueMax),
            AutoBalance = delta.AutoBalance.Apply(AutoBalance),
            ShadowLift = delta.ShadowLift.Apply(ShadowLift),
            Roughness = delta.Roughness.Apply(Roughness),
            Metalness = delta.Metalness.Apply(Metalness),
            Specular = delta.Specular.Apply(Specular),
            RoughnessInverted = delta.RoughnessInverted.Apply(RoughnessInverted),
            MetalnessInverted = delta.MetalnessInverted.Apply(MetalnessInverted),
            RoughnessScale = delta.RoughnessScale.Apply(RoughnessScale),
            RoughnessMin = delta.RoughnessMin.Apply(RoughnessMin),
            RoughnessMax = delta.RoughnessMax.Apply(RoughnessMax),
            MetalnessScale = delta.MetalnessScale.Apply(MetalnessScale),
            MetalnessMin = delta.MetalnessMin.Apply(MetalnessMin),
            MetalnessMax = delta.MetalnessMax.Apply(MetalnessMax),
            RoughnessBlendTarget = delta.RoughnessBlendTarget.Apply(RoughnessBlendTarget),
            RoughnessBlendStrength = delta.RoughnessBlendStrength.Apply(RoughnessBlendStrength),
            MetalnessBlendTarget = delta.MetalnessBlendTarget.Apply(MetalnessBlendTarget),
            MetalnessBlendStrength = delta.MetalnessBlendStrength.Apply(MetalnessBlendStrength),
            HeightScale = delta.HeightScale.Apply(HeightScale),
            EmissiveIntensity = delta.EmissiveIntensity.Apply(EmissiveIntensity),
            EmissiveColor = delta.EmissiveColor.Apply(EmissiveColor),
            EmissiveScalarMask = delta.EmissiveScalarMask.Apply(EmissiveScalarMask),
            MaterialRole = delta.MaterialRole.Apply(MaterialRole),
            Visible = delta.Visible.Apply(Visible),
        };
    }
}

internal sealed record NetMaterialParameterGroup(
    IReadOnlyList<int> SubmeshIndices,
    bool AppliesToAll,
    NetMaterialParameterDelta Parameters);

internal sealed record NetMaterialParameterUpdate(
    string SessionId,
    long EditRevision,
    long ParameterGeneration,
    IReadOnlyList<NetMaterialParameterGroup> Groups,
    IReadOnlyList<int> AffectedSubmeshes)
{
    public NetMaterialParameterUpdate ExpandAllSubmeshes(IReadOnlyList<int> allSubmeshes)
    {
        if (!Groups.Any(group => group.AppliesToAll))
        {
            return this;
        }
        return this with
        {
            Groups = Groups.Select(group => group.AppliesToAll
                ? group with { SubmeshIndices = allSubmeshes, AppliesToAll = false }
                : group).ToArray(),
            AffectedSubmeshes = allSubmeshes,
        };
    }
}
