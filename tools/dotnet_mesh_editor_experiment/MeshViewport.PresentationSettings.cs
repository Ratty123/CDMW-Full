using System.Numerics;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private D3D11PresentationSettings _residentPresentationSettings = new();
    private readonly HashSet<int> _presentationHighlightedOriginals = new();
    private readonly Dictionary<int, string> _presentationPartRoles = new();
    private readonly HashSet<int> _presentedSources = new();

    private void ApplyPresentationQualityAndUv(JsonElement display, JsonElement root)
    {
        var quality = display.TryGetProperty("quality", out var value)
            && value.ValueKind == JsonValueKind.Object
                ? value
                : display;
        var uv = root.TryGetProperty("uv", out var uvValue)
            && uvValue.ValueKind == JsonValueKind.Object
                ? uvValue
                : display;
        var defaults = new D3D11PresentationSettings();
        var texturesEnabled = JsonBool(quality, "use_textures_by_default", TexturesEnabled);
        var viewMode = JsonText(quality, "d3d11_view_mode", defaults.ViewMode).ToLowerInvariant();
        TexturesEnabled = texturesEnabled;
        _residentPresentationSettings = new D3D11PresentationSettings
        {
            HighQuality = JsonBool(quality, "high_quality_by_default", defaults.HighQuality),
            ViewMode = viewMode,
            GameOutdoorApprox = string.Equals(viewMode, "game_outdoor", StringComparison.Ordinal),
            ForceNearestSampling = JsonBool(quality, "force_nearest_no_mipmaps", defaults.ForceNearestSampling),
            CullBackFaces = JsonBool(quality, "d3d11_cull_back_faces", defaults.CullBackFaces),
            DisableLighting = JsonBool(quality, "disable_lighting", defaults.DisableLighting),
            DisableDepthTest = JsonBool(quality, "disable_depth_test", defaults.DisableDepthTest),
            DisableTint = JsonBool(quality, "disable_tint", defaults.DisableTint),
            DisableBrightness = JsonBool(quality, "disable_brightness", defaults.DisableBrightness),
            DisableUvScale = JsonBool(quality, "disable_uv_scale", defaults.DisableUvScale),
            DisableNormalMap = JsonBool(quality, "disable_normal_map", defaults.DisableNormalMap),
            DisableMaterialMap = JsonBool(quality, "disable_material_map", defaults.DisableMaterialMap),
            DisableHeightMap = JsonBool(quality, "disable_height_map", defaults.DisableHeightMap),
            DisableAllSupportMaps = JsonBool(quality, "disable_all_support_maps", defaults.DisableAllSupportMaps),
            FlipTextureV = JsonBool(quality, "flip_texture_v", defaults.FlipTextureV),
            LightAzimuthDegrees = JsonFloat(quality, "d3d11_light_azimuth_degrees", defaults.LightAzimuthDegrees),
            LightElevationDegrees = JsonFloat(quality, "d3d11_light_elevation_degrees", defaults.LightElevationDegrees),
            AoStrength = Math.Clamp(JsonFloat(quality, "d3d11_ao_strength", defaults.AoStrength), 0.0f, 2.0f),
            RoughnessBias = Math.Clamp(JsonFloat(quality, "d3d11_roughness_bias", defaults.RoughnessBias), -0.5f, 0.5f),
            MetalnessScale = Math.Clamp(JsonFloat(quality, "d3d11_metalness_scale", defaults.MetalnessScale), 0.0f, 2.0f),
            EnvironmentStrength = Math.Clamp(JsonFloat(quality, "d3d11_environment_strength", defaults.EnvironmentStrength), 0.0f, 2.0f),
            EmissiveGain = Math.Clamp(JsonFloat(quality, "d3d11_emissive_gain", defaults.EmissiveGain), 0.0f, 4.0f),
            ToneExposure = Math.Clamp(JsonFloat(quality, "d3d11_tone_exposure", defaults.ToneExposure), 0.25f, 2.0f),
            ToneContrast = Math.Clamp(JsonFloat(quality, "d3d11_tone_contrast", defaults.ToneContrast), 0.5f, 1.75f),
            ToneGamma = Math.Clamp(JsonFloat(quality, "d3d11_tone_gamma", defaults.ToneGamma), 0.5f, 2.2f),
            MaxAnisotropy = Math.Clamp(JsonInt(quality, "max_anisotropy", defaults.MaxAnisotropy), 1, 16),
            MipLodBias = Math.Clamp(JsonFloat(quality, "d3d11_mip_lod_bias", defaults.MipLodBias), -2.0f, 1.0f),
            TextureAddressMode = JsonText(quality, "d3d11_texture_address_mode", defaults.TextureAddressMode).ToLowerInvariant(),
            NormalYMode = JsonText(quality, "d3d11_normal_y_mode", defaults.NormalYMode).ToLowerInvariant(),
            AmbientStrength = Math.Clamp(JsonFloat(quality, "ambient_strength", defaults.AmbientStrength), 0.35f, 1.0f),
            DiffuseWrapBias = Math.Clamp(JsonFloat(quality, "diffuse_wrap_bias", defaults.DiffuseWrapBias), 0.2f, 1.0f),
            DiffuseLightScale = Math.Clamp(JsonFloat(quality, "diffuse_light_scale", defaults.DiffuseLightScale), 0.05f, 1.5f),
            NormalStrengthCap = Math.Clamp(JsonFloat(quality, "normal_strength_cap", defaults.NormalStrengthCap), 0.0f, 1.0f),
            HeightEffectMax = Math.Clamp(JsonFloat(quality, "height_effect_max", defaults.HeightEffectMax), 0.0f, 1.0f),
            SpecularBase = Math.Clamp(JsonFloat(quality, "specular_base", defaults.SpecularBase), 0.0f, 0.5f),
            SpecularMax = Math.Clamp(JsonFloat(quality, "specular_max", defaults.SpecularMax), 0.0f, 1.0f),
            ShininessMax = Math.Clamp(JsonFloat(quality, "shininess_max", defaults.ShininessMax), 1.0f, 256.0f),
            OrbitSensitivity = Math.Clamp(JsonFloat(quality, "orbit_sensitivity", defaults.OrbitSensitivity), 0.05f, 1.0f),
            PanSensitivity = Math.Clamp(JsonFloat(quality, "pan_sensitivity", defaults.PanSensitivity), 0.05f, 3.0f),
            InvertOrbitX = JsonBool(quality, "invert_orbit_x", defaults.InvertOrbitX),
            InvertOrbitY = JsonBool(quality, "invert_orbit_y", defaults.InvertOrbitY),
            InvertPanX = JsonBool(quality, "invert_pan_x", defaults.InvertPanX),
            InvertPanY = JsonBool(quality, "invert_pan_y", defaults.InvertPanY),
            UvScale = new Vector2(
                SafeNonZero(JsonFloat(uv, "scale_u", defaults.UvScale.X)),
                SafeNonZero(JsonFloat(uv, "scale_v", defaults.UvScale.Y))),
            UvOffset = new Vector2(
                JsonFloat(uv, "offset_u", defaults.UvOffset.X),
                JsonFloat(uv, "offset_v", defaults.UvOffset.Y)),
            UvRotationDegrees = JsonFloat(uv, "rotate_degrees", defaults.UvRotationDegrees),
            FlipU = JsonBool(uv, "flip_u", defaults.FlipU),
            FlipV = JsonBool(uv, "flip_v", defaults.FlipV),
        };
        ApplyGizmoAppearanceFromPresentation(quality);
        _d3d11Viewport?.ApplyPresentationSettings(_residentPresentationSettings);
    }

    private void SynchronizePresentationDisplaySettings()
    {
        InitializePresentationContexts();
        foreach (var context in _presentationContexts.Values)
        {
            context.DisplayMode = DisplayMode;
            context.MaterialDebugMode = MaterialDebugMode;
            context.TexturesEnabled = TexturesEnabled;
        }
    }

    public bool TrySetSynchronizedDisplayMode(string mode, out string error)
    {
        if (!TrySetDisplayMode(mode, out error))
        {
            return false;
        }
        SynchronizePresentationDisplaySettings();
        return true;
    }

    private void ApplyPresentationPartStates(JsonElement root)
    {
        var matrices = new Dictionary<int, Matrix4x4>();
        _presentationPartRoles.Clear();
        if (root.TryGetProperty("part_transforms", out var transforms)
            && transforms.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in transforms.EnumerateObject())
            {
                if (property.Value.ValueKind != JsonValueKind.Object
                    || !TryPartIndex(property, out var sourceIndex)
                    || sourceIndex < 0
                    || sourceIndex >= _scene.EditableSubmeshCount)
                {
                    continue;
                }
                matrices[sourceIndex] = PresentationPartMatrix(sourceIndex, property.Value);
                _presentationPartRoles[sourceIndex] = JsonText(property.Value, "material_role", string.Empty);
            }
        }
        _scene.SetPresentationPartMatrices(matrices, _presentationPartRoles);
    }

    private Matrix4x4 PresentationPartMatrix(int sourceIndex, JsonElement state)
    {
        var submesh = _document.Submeshes[sourceIndex];
        var pivot = submesh.Vertices.Count == 0
            ? Vector3.Zero
            : (new Vector3(
                submesh.Vertices.Min(vertex => vertex.X),
                submesh.Vertices.Min(vertex => vertex.Y),
                submesh.Vertices.Min(vertex => vertex.Z))
              + new Vector3(
                submesh.Vertices.Max(vertex => vertex.X),
                submesh.Vertices.Max(vertex => vertex.Y),
                submesh.Vertices.Max(vertex => vertex.Z))) * 0.5f;
        var scale = JsonVector3(state, "scale_xyz", Vector3.One)
            * Math.Clamp(JsonFloat(state, "uniform_scale", 1.0f), 0.001f, 1000.0f);
        var rotation = JsonVector3(state, "rotate_xyz_degrees", Vector3.Zero) * MathF.PI / 180.0f;
        var offset = JsonVector3(state, "offset_xyz", Vector3.Zero);
        return Matrix4x4.CreateTranslation(-pivot)
            * Matrix4x4.CreateScale(scale)
            * Matrix4x4.CreateRotationX(rotation.X)
            * Matrix4x4.CreateRotationY(rotation.Y)
            * Matrix4x4.CreateRotationZ(rotation.Z)
            * Matrix4x4.CreateTranslation(pivot + offset);
    }

    private static bool TryPartIndex(JsonProperty property, out int index)
    {
        if (int.TryParse(property.Name, out index))
        {
            return true;
        }
        index = JsonInt(property.Value, "source_submesh_index", -1);
        return index >= 0;
    }

    private static Vector3 JsonVector3(JsonElement root, string name, Vector3 fallback)
    {
        if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return fallback;
        }
        var values = value.EnumerateArray().Take(3)
            .Select(item => item.TryGetSingle(out var number) && float.IsFinite(number) ? number : float.NaN)
            .ToArray();
        return values.Length == 3 && values.All(float.IsFinite)
            ? new Vector3(values[0], values[1], values[2])
            : fallback;
    }

    private static float SafeNonZero(float value) => Math.Abs(value) > 0.000001f ? value : 1.0f;

    private static string JsonText(JsonElement root, string name, string fallback) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? (value.GetString() ?? fallback).Trim()
            : fallback;
}
