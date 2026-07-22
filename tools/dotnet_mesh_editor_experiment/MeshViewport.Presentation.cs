using System.Runtime.CompilerServices;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed class NetViewPresentationContext
{
    public required string Id { get; init; }
    public required string RoleFilter { get; init; }
    public float Yaw { get; set; }
    public float Pitch { get; set; }
    public float Zoom { get; set; }
    public float PanX { get; set; }
    public float PanY { get; set; }
    public Vec3 CameraMinimum { get; set; }
    public Vec3 CameraMaximum { get; set; }
    public long LastCameraCommandGeneration { get; set; }
    public string DisplayMode { get; set; } = "textured";
    public bool XRay { get; set; }
    public int MaterialDebugMode { get; set; }
    public bool TexturesEnabled { get; set; } = true;
    public bool GridVisible { get; set; } = true;
    public bool GizmoVisible { get; set; } = true;
    public bool PartPickEnabled { get; set; }

    public Dictionary<string, object?> StatusPayload()
    {
        var sceneSize = Math.Max(
            CameraMaximum.X - CameraMinimum.X,
            Math.Max(CameraMaximum.Y - CameraMinimum.Y, CameraMaximum.Z - CameraMinimum.Z));
        var fitZoom = CameraZoomPolicy.FitZoomForSceneSize(sceneSize);
        return new Dictionary<string, object?>
        {
            ["id"] = Id,
            ["role_filter"] = RoleFilter,
            ["camera"] = new Dictionary<string, object?>
            {
                ["yaw_degrees"] = Yaw * 180.0f / MathF.PI,
                ["pitch_degrees"] = Pitch * 180.0f / MathF.PI,
                ["zoom"] = Zoom,
                ["fit_relative_zoom"] = CameraZoomPolicy.FitRelativeRatio(Zoom, fitZoom),
                ["fit_mode"] = "manual",
                ["pan"] = new[] { PanX, PanY },
                ["bounds_minimum"] = new[] { CameraMinimum.X, CameraMinimum.Y, CameraMinimum.Z },
                ["bounds_maximum"] = new[] { CameraMaximum.X, CameraMaximum.Y, CameraMaximum.Z },
                ["last_command_generation"] = LastCameraCommandGeneration,
            },
            ["display_mode"] = DisplayMode,
            ["xray"] = XRay,
            ["material_debug_mode"] = MaterialDebugMode,
            ["textures_enabled"] = TexturesEnabled,
            ["grid_visible"] = GridVisible,
            ["gizmo_visible"] = GizmoVisible,
            ["part_pick_enabled"] = PartPickEnabled,
            ["interaction_allowed"] = string.Equals(RoleFilter, "editable", StringComparison.OrdinalIgnoreCase),
        };
    }
}

internal sealed partial class MeshViewport
{
    private readonly Dictionary<string, NetViewPresentationContext> _presentationContexts =
        new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<int> _presentationHighlightedSources = new();
    private readonly HashSet<int> _presentationHiddenSubmeshes = new();
    private string _activePresentationView = "editable";
    private string _activeCameraContextId = "editable";
    private bool _comparisonCameraLinked;
    private bool _presentationGridVisible = true;
    private bool _presentationGizmoVisible = true;
    private int _presentationHoveredSource = -1;
    private string _presentationStateFingerprint = string.Empty;
    private long _presentationGeneration;

    public string ActivePresentationView => _activePresentationView;
    public bool PresentationInteractionAllowed =>
        !string.Equals(_activeCameraContextId, "reference", StringComparison.OrdinalIgnoreCase);

    private void InitializePresentationContexts()
    {
        if (_presentationContexts.Count > 0)
        {
            return;
        }
        _presentationContexts["editable"] = NewPresentationContext("editable", "editable");
        _presentationContexts["reference"] = NewPresentationContext("reference", "reference");
        _presentationContexts["editable"].Zoom = FitZoomForBounds(CameraBoundsForContext("editable"));
        _presentationContexts["reference"].Zoom = FitZoomForBounds(CameraBoundsForContext("reference"));
    }

    private NetViewPresentationContext NewPresentationContext(string id, string roleFilter)
    {
        var cameraBounds = SceneBoundsForContext(id);
        return new NetViewPresentationContext
        {
            Id = id,
            RoleFilter = roleFilter,
            Yaw = _yaw,
            Pitch = _pitch,
            Zoom = _zoom,
            PanX = _panX,
            PanY = _panY,
            CameraMinimum = cameraBounds.Min,
            CameraMaximum = cameraBounds.Max,
            DisplayMode = DisplayMode,
            XRay = ShowXRay,
            MaterialDebugMode = MaterialDebugMode,
            TexturesEnabled = this.TexturesEnabled,
            GridVisible = _presentationGridVisible,
            GizmoVisible = _presentationGizmoVisible,
            PartPickEnabled = PartPickEnabled,
        };
    }

    private void SaveActivePresentationContext()
    {
        InitializePresentationContexts();
        if (!_presentationContexts.TryGetValue(_activeCameraContextId, out var context))
        {
            return;
        }
        context.Yaw = _yaw;
        context.Pitch = _pitch;
        context.Zoom = _zoom;
        context.PanX = _panX;
        context.PanY = _panY;
        context.DisplayMode = DisplayMode;
        context.XRay = ShowXRay;
        context.MaterialDebugMode = MaterialDebugMode;
        context.TexturesEnabled = TexturesEnabled;
        context.GridVisible = _presentationGridVisible;
        context.GizmoVisible = _presentationGizmoVisible;
        context.PartPickEnabled = PartPickEnabled;
    }

    private void LoadPresentationContext(string contextId)
    {
        InitializePresentationContexts();
        if (!_presentationContexts.TryGetValue(contextId, out var context))
        {
            context = _presentationContexts["editable"];
            contextId = "editable";
        }
        _activeCameraContextId = contextId;
        _yaw = context.Yaw;
        _pitch = context.Pitch;
        _zoom = context.Zoom;
        _panX = context.PanX;
        _panY = context.PanY;
        MaterialDebugMode = context.MaterialDebugMode;
        _presentationGridVisible = context.GridVisible;
        _presentationGizmoVisible = context.GizmoVisible;
        PartPickEnabled = context.PartPickEnabled;
        _scene.SetPresentationOverlayVisibility(
            _presentationGridVisible,
            _presentationGizmoVisible);
        var xray = context.XRay;
        _ = TrySetDisplayMode(context.DisplayMode, out _);
        SetXRayEnabled(xray);
        TexturesEnabled = context.TexturesEnabled;
    }

    public void ActivatePresentationView(string view, string? comparisonMode = null)
    {
        SaveActivePresentationContext();
        var normalized = (view ?? string.Empty).Trim().ToLowerInvariant().Replace('-', '_');
        if (string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase))
        {
            normalized = "editable";
        }
        if (normalized is "original" or "reference" or "original_only")
        {
            _activePresentationView = "reference";
            _comparisonCameraLinked = false;
            _scene.SetComparisonMode("original_only");
            LoadPresentationContext("reference");
        }
        else if (normalized is "comparison" or "overlay" or "side_by_side")
        {
            _activePresentationView = "comparison";
            var requestedMode = (comparisonMode ?? normalized).Trim().ToLowerInvariant();
            var overlay = requestedMode == "overlay";
            _comparisonCameraLinked = overlay;
            _scene.SetComparisonMode(overlay ? "overlay" : "side_by_side");
            // Overlay intentionally links to the editable comparison camera.
            // Normal split panes keep their own independently stored cameras.
            LoadPresentationContext(overlay ? "editable" : NormalizePaneId(_activeCameraContextId));
        }
        else
        {
            _activePresentationView = "editable";
            _comparisonCameraLinked = false;
            _scene.SetComparisonMode("replacement_only");
            LoadPresentationContext("editable");
        }
        ApplySceneState();
    }

    public bool TryApplyPresentationState(JsonElement root, out string error)
    {
        error = string.Empty;
        InitializePresentationContexts();
        var activeView = JsonString(root, "active_view", _activePresentationView);
        var comparisonMode = JsonString(root, "comparison_mode", _scene.ComparisonMode);
        if (activeView.Length > 0 || comparisonMode.Length > 0)
        {
            var inferredView = activeView;
            if (inferredView.Length == 0)
            {
                inferredView = comparisonMode switch
                {
                    "original_only" => "reference",
                    "overlay" or "side_by_side" => "comparison",
                    _ => "editable",
                };
            }
            ActivatePresentationView(inferredView, comparisonMode);
        }
        var splitRatio = JsonFloat(
            root,
            "side_by_side_split_ratio",
            JsonFloat(root, "split_ratio", PaneSplitRatio));
        SetPaneSplitRatio(splitRatio);

        if (root.TryGetProperty("camera", out var camera) && camera.ValueKind == JsonValueKind.Object)
        {
            ApplyPresentationCamera(camera);
        }
        if (root.TryGetProperty("display", out var display) && display.ValueKind == JsonValueKind.Object)
        {
            var mode = JsonString(display, "mode", DisplayMode);
            if (!TrySetDisplayMode(mode, out error))
            {
                return false;
            }
            MaterialDebugMode = Math.Clamp(JsonInt(display, "material_debug_mode", MaterialDebugMode), 0, 12);
            _presentationGridVisible = JsonBool(display, "grid_visible", _presentationGridVisible);
            _presentationGizmoVisible = JsonBool(display, "gizmo_visible", _presentationGizmoVisible);
            _scene.SetPresentationOverlayVisibility(_presentationGridVisible, _presentationGizmoVisible);
            PartPickEnabled = JsonBool(display, "part_pick_enabled", PartPickEnabled);
            ApplyPresentationQualityAndUv(display, root);
            SynchronizePresentationDisplaySettings();
        }
        if (root.TryGetProperty("highlights", out var highlights) && highlights.ValueKind == JsonValueKind.Object)
        {
            ReplaceIntSet(_presentationHighlightedSources, highlights, "source_indices");
            ReplaceIntSet(_presentationHighlightedOriginals, highlights, "original_indices");
            _presentationHoveredSource = JsonInt(highlights, "hovered_source_index", -1);
        }
        if (root.TryGetProperty("visibility", out var visibility) && visibility.ValueKind == JsonValueKind.Object)
        {
            ReplaceIntSet(_presentationHiddenSubmeshes, visibility, "hidden_submesh_indices");
            _scene.SetPresentationHiddenSubmeshes(_presentationHiddenSubmeshes);
        }
        ApplyPresentationPartStates(root);

        _presentationGeneration = Math.Max(
            _presentationGeneration + 1,
            JsonLong(root, "presentation_generation", _presentationGeneration + 1));
        _presentationStateFingerprint = Convert.ToHexString(
            System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(root.GetRawText())))
            .ToLowerInvariant();
        SaveActivePresentationContext();
        RequestFrame();
        UpdateGpuViewport();
        Invalidate();
        return true;
    }

    private void ApplyPresentationCamera(JsonElement camera)
    {
        InitializePresentationContexts();
        SaveActivePresentationContext();
        var role = JsonString(camera, "role", _activeCameraContextId).Trim().ToLowerInvariant();
        var contextId = role is "original" or "reference" or "original_only"
            ? "reference"
            : role is "replacement" or "imported" or "editable" or "modify"
                ? "editable"
                : NormalizePaneId(_activeCameraContextId);
        var context = _presentationContexts[contextId];
        var commandGeneration = JsonLong(camera, "command_generation", 0);
        if (commandGeneration > 0 && commandGeneration <= context.LastCameraCommandGeneration)
        {
            return;
        }
        var preset = JsonString(camera, "preset", string.Empty);
        if (preset.Length > 0)
        {
            ApplyCameraPreset(context, preset);
        }
        var fitMode = JsonString(camera, "fit_mode", string.Empty).Trim().ToLowerInvariant();
        if (fitMode == "fit" || JsonBool(camera, "fit", JsonBool(camera, "fit_to_view", false)))
        {
            var bounds = SceneBoundsForContext(contextId);
            context.CameraMinimum = bounds.Min;
            context.CameraMaximum = bounds.Max;
            context.Zoom = FitZoomForBounds(bounds);
            context.PanX = 0.0f;
            context.PanY = 0.0f;
        }
        if (camera.TryGetProperty("yaw", out var yaw) && yaw.TryGetSingle(out var yawDegrees))
        {
            context.Yaw = yawDegrees * MathF.PI / 180.0f;
        }
        if (camera.TryGetProperty("pitch", out var pitch) && pitch.TryGetSingle(out var pitchDegrees))
        {
            context.Pitch = Math.Clamp(pitchDegrees, -89.0f, 89.0f) * MathF.PI / 180.0f;
        }
        context.Yaw += JsonFloat(camera, "yaw_delta", 0.0f) * MathF.PI / 180.0f;
        context.Pitch = Math.Clamp(
            context.Pitch + JsonFloat(camera, "pitch_delta", 0.0f) * MathF.PI / 180.0f,
            -1.55f,
            1.55f);
        var fitZoom = FitZoomForBounds((context.CameraMinimum, context.CameraMaximum));
        if (camera.TryGetProperty("fit_relative_zoom", out var relativeZoom)
            && relativeZoom.TryGetSingle(out var fitRelativeZoom)
            && float.IsFinite(fitRelativeZoom))
        {
            ApplyZoomToContext(context, fitZoom * Math.Clamp(fitRelativeZoom, 0.1f, 64.0f));
        }
        else
        {
            var zoomFactor = Math.Clamp(JsonFloat(camera, "zoom_factor", 1.0f), 0.01f, 100.0f);
            var targetZoom = CameraZoomPolicy.ApplyZoomFactor(context.Zoom, fitZoom, zoomFactor);
            ApplyZoomToContext(context, targetZoom);
        }
        if (camera.TryGetProperty("pan", out var pan) && pan.ValueKind == JsonValueKind.Array)
        {
            var values = pan.EnumerateArray().Take(2)
                .Select(value => value.TryGetSingle(out var number) && float.IsFinite(number) ? number : 0.0f)
                .ToArray();
            if (values.Length == 2)
            {
                context.PanX = values[0];
                context.PanY = values[1];
            }
        }
        if (commandGeneration > 0)
        {
            context.LastCameraCommandGeneration = commandGeneration;
        }
        if (string.Equals(contextId, _activeCameraContextId, StringComparison.OrdinalIgnoreCase))
        {
            _yaw = context.Yaw;
            _pitch = context.Pitch;
            _zoom = context.Zoom;
            _panX = context.PanX;
            _panY = context.PanY;
        }
    }

    private static void ApplyCameraPreset(NetViewPresentationContext context, string preset)
    {
        context.PanX = 0.0f;
        context.PanY = 0.0f;
        switch ((preset ?? string.Empty).Trim().ToLowerInvariant())
        {
            case "front":
                context.Yaw = 0.0f;
                context.Pitch = 0.0f;
                break;
            case "back":
                context.Yaw = MathF.PI;
                context.Pitch = 0.0f;
                break;
            case "left":
                context.Yaw = -MathF.PI * 0.5f;
                context.Pitch = 0.0f;
                break;
            case "right":
                context.Yaw = MathF.PI * 0.5f;
                context.Pitch = 0.0f;
                break;
            case "top":
                context.Yaw = 0.0f;
                context.Pitch = -1.35f;
                break;
            case "bottom":
                context.Yaw = 0.0f;
                context.Pitch = 1.35f;
                break;
        }
    }

    public Dictionary<string, object?> PresentationStatusPayload()
    {
        InitializePresentationContexts();
        SaveActivePresentationContext();
        var sharedDocumentIdentity = RuntimeHelpers.GetHashCode(_document);
        return new Dictionary<string, object?>
        {
            ["active_view"] = _activePresentationView,
            ["active_camera_context"] = _activeCameraContextId,
            ["comparison_camera_linked"] = _comparisonCameraLinked,
            ["normal_cameras_independent"] = true,
            ["simultaneous_role_panes"] = HasSimultaneousRolePanes,
            ["active_pane"] = ActivePresentationPane,
            ["split_ratio"] = PaneSplitRatio,
            ["pane_rectangles"] = PaneRectangleStatusPayload(),
            ["view_contexts"] = _presentationContexts.Values
                .OrderBy(context => context.Id)
                .Select(context => context.StatusPayload())
                .ToArray(),
            ["shared_scene_resources"] = new Dictionary<string, object?>
            {
                ["document_identity"] = sharedDocumentIdentity,
                ["geometry_identity"] = sharedDocumentIdentity,
                ["material_identity"] = RuntimeHelpers.GetHashCode(_materials),
                ["texture_identity"] = RuntimeHelpers.GetHashCode(_textureSet),
            },
            ["presentation_generation"] = _presentationGeneration,
            ["presentation_fingerprint"] = _presentationStateFingerprint,
            ["grid_visible"] = _presentationGridVisible,
            ["gizmo_visible"] = _presentationGizmoVisible,
            ["hidden_submesh_indices"] = _presentationHiddenSubmeshes.OrderBy(index => index).ToArray(),
            ["highlighted_source_indices"] = _presentationHighlightedSources.OrderBy(index => index).ToArray(),
            ["highlighted_original_indices"] = _presentationHighlightedOriginals.OrderBy(index => index).ToArray(),
            ["part_roles"] = _presentationPartRoles.OrderBy(pair => pair.Key)
                .ToDictionary(pair => pair.Key.ToString(), pair => pair.Value),
            ["presentation_quality_applied"] = true,
            ["presentation_uv_applied"] = true,
            ["quality_state"] = new Dictionary<string, object?>
            {
                ["use_textures_by_default"] = TexturesEnabled,
                ["dotnet_view_mode"] = _residentPresentationSettings.ViewMode,
                ["d3d11_view_mode"] = _residentPresentationSettings.ViewMode,
                ["high_quality"] = _residentPresentationSettings.HighQuality,
                ["force_nearest_sampling"] = _residentPresentationSettings.ForceNearestSampling,
                ["cull_back_faces"] = _residentPresentationSettings.CullBackFaces,
                ["disable_lighting"] = _residentPresentationSettings.DisableLighting,
                ["disable_depth_test"] = _residentPresentationSettings.DisableDepthTest,
                ["disable_tint"] = _residentPresentationSettings.DisableTint,
                ["disable_brightness"] = _residentPresentationSettings.DisableBrightness,
                ["disable_uv_scale"] = _residentPresentationSettings.DisableUvScale,
                ["disable_normal_map"] = _residentPresentationSettings.DisableNormalMap,
                ["disable_material_map"] = _residentPresentationSettings.DisableMaterialMap,
                ["disable_height_map"] = _residentPresentationSettings.DisableHeightMap,
                ["disable_all_support_maps"] = _residentPresentationSettings.DisableAllSupportMaps,
                ["flip_texture_v"] = _residentPresentationSettings.FlipTextureV,
                ["normal_y_mode"] = _residentPresentationSettings.NormalYMode,
                ["texture_address_mode"] = _residentPresentationSettings.TextureAddressMode,
                ["max_anisotropy"] = _residentPresentationSettings.MaxAnisotropy,
                ["mip_lod_bias"] = _residentPresentationSettings.MipLodBias,
                ["light_azimuth_degrees"] = _residentPresentationSettings.LightAzimuthDegrees,
                ["light_elevation_degrees"] = _residentPresentationSettings.LightElevationDegrees,
                ["ao_strength"] = _residentPresentationSettings.AoStrength,
                ["roughness_bias"] = _residentPresentationSettings.RoughnessBias,
                ["metalness_scale"] = _residentPresentationSettings.MetalnessScale,
                ["environment_strength"] = _residentPresentationSettings.EnvironmentStrength,
                ["emissive_gain"] = _residentPresentationSettings.EmissiveGain,
                ["tone_exposure"] = _residentPresentationSettings.ToneExposure,
                ["tone_contrast"] = _residentPresentationSettings.ToneContrast,
                ["tone_gamma"] = _residentPresentationSettings.ToneGamma,
                ["ambient_strength"] = _residentPresentationSettings.AmbientStrength,
                ["diffuse_wrap_bias"] = _residentPresentationSettings.DiffuseWrapBias,
                ["diffuse_light_scale"] = _residentPresentationSettings.DiffuseLightScale,
                ["normal_strength_cap"] = _residentPresentationSettings.NormalStrengthCap,
                ["height_effect_max"] = _residentPresentationSettings.HeightEffectMax,
                ["specular_base"] = _residentPresentationSettings.SpecularBase,
                ["specular_max"] = _residentPresentationSettings.SpecularMax,
                ["shininess_max"] = _residentPresentationSettings.ShininessMax,
                ["orbit_sensitivity"] = _residentPresentationSettings.OrbitSensitivity,
                ["pan_sensitivity"] = _residentPresentationSettings.PanSensitivity,
                ["invert_orbit_x"] = _residentPresentationSettings.InvertOrbitX,
                ["invert_orbit_y"] = _residentPresentationSettings.InvertOrbitY,
                ["invert_pan_x"] = _residentPresentationSettings.InvertPanX,
                ["invert_pan_y"] = _residentPresentationSettings.InvertPanY,
            },
            ["uv_state"] = new Dictionary<string, object?>
            {
                ["scale"] = new[] { _residentPresentationSettings.UvScale.X, _residentPresentationSettings.UvScale.Y },
                ["offset"] = new[] { _residentPresentationSettings.UvOffset.X, _residentPresentationSettings.UvOffset.Y },
                ["rotation_degrees"] = _residentPresentationSettings.UvRotationDegrees,
                ["flip_u"] = _residentPresentationSettings.FlipU,
                ["flip_v"] = _residentPresentationSettings.FlipV ^ _residentPresentationSettings.FlipTextureV,
            },
            ["hovered_source_index"] = _presentationHoveredSource,
        };
    }

    private void NotifyViewStateChanged()
    {
        EditorEventRequested?.Invoke("view_state_changed", PresentationStatusPayload());
    }

    private static void ReplaceIntSet(HashSet<int> target, JsonElement root, string name)
    {
        target.Clear();
        if (!root.TryGetProperty(name, out var values) || values.ValueKind != JsonValueKind.Array)
        {
            return;
        }
        foreach (var value in values.EnumerateArray())
        {
            if (value.TryGetInt32(out var index) && index >= 0)
            {
                target.Add(index);
            }
        }
    }

    private static string JsonString(JsonElement root, string name, string fallback) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? (value.GetString() ?? fallback).Trim().ToLowerInvariant()
            : fallback;
    private static int JsonInt(JsonElement root, string name, int fallback) =>
        root.TryGetProperty(name, out var value) && value.TryGetInt32(out var result) ? result : fallback;
    private static long JsonLong(JsonElement root, string name, long fallback) =>
        root.TryGetProperty(name, out var value) && value.TryGetInt64(out var result) ? result : fallback;
    private static float JsonFloat(JsonElement root, string name, float fallback) =>
        root.TryGetProperty(name, out var value) && value.TryGetSingle(out var result) && float.IsFinite(result)
            ? result
            : fallback;
    private static bool JsonBool(JsonElement root, string name, bool fallback) =>
        root.TryGetProperty(name, out var value) && value.ValueKind is JsonValueKind.True or JsonValueKind.False
            ? value.GetBoolean()
            : fallback;
}
