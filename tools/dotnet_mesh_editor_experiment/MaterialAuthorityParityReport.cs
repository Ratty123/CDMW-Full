using System.Diagnostics;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static class MaterialAuthorityParityReport
{
    private const string Schema = "cdmw_material_authority_dotnet_parity_v1";
    private const int CaptureWidth = 320;
    private const int CaptureHeight = 192;

    private sealed record CaseDefinition(
        string Key,
        string[] ArtifactChannels,
        string ResourceMode = "change",
        string Parameter = "",
        float BeforeParameter = 0.0f,
        float AfterParameter = 0.0f);

    private sealed record MaterialPaths(
        string Base,
        string Normal,
        string Height,
        string Material,
        string Emissive);

    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(arg, "--headless-material-authority-parity", StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var reportPath = ReportPath(args);
        try
        {
            var (report, ok) = Execute(reportPath);
            WriteReport(reportPath, report);
            return ok ? 0 : 2;
        }
        catch (Exception ex)
        {
            WriteReport(
                reportPath,
                new Dictionary<string, object?>
                {
                    ["schema"] = Schema,
                    ["ok"] = false,
                    ["generated_at_utc"] = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture),
                    ["error"] = new Dictionary<string, object?>
                    {
                        ["type"] = ex.GetType().FullName,
                        ["message"] = ex.Message,
                    },
                });
            return 1;
        }
    }

    private static (Dictionary<string, object?> Report, bool Ok) Execute(string reportPath)
    {
        var evidenceDirectory = Path.Combine(
            Path.GetDirectoryName(reportPath) ?? Environment.CurrentDirectory,
            $"material-authority-parity-{Environment.ProcessId.ToString(CultureInfo.InvariantCulture)}");
        Directory.CreateDirectory(evidenceDirectory);
        var stableRight = WriteMaterialPaths(evidenceDirectory, "stable-right", changed: false);
        var firstLeft = WriteMaterialPaths(evidenceDirectory, "initial-left", changed: false);
        var document = BuildTwoPartDocument();
        var materials = NetMaterialSet.Empty;
        var initialUpdate = ParseStateUpdate(
            firstLeft,
            stableRight,
            editRevision: 0,
            generation: 1,
            affectedSubmeshes: new[] { 0, 1 },
            leftParameters: Parameters(1.0f, 0.45f));
        materials.ReplaceState(materials.BuildState(initialUpdate));
        using var textures = NetTextureSet.Load(materials);
        var initialDecode = textures.DecodeResourcesAsync(initialUpdate.Resources).GetAwaiter().GetResult();
        if (initialDecode.Failures.Count > 0)
        {
            throw new InvalidOperationException(
                "Initial Material Authority DDS decode failed: "
                + string.Join("; ", initialDecode.Failures.Select(pair => $"{pair.Key}: {pair.Value}")));
        }
        using var host = CreateHiddenHost();
        using var viewport = new D3D11MaterialViewport(
            document,
            materials,
            textures,
            NetSceneState.Load(string.Empty, document.Submeshes.Count))
        {
            Dock = DockStyle.Fill,
            ShowSolid = true,
            TexturesEnabled = true,
        };
        host.Controls.Add(viewport);
        host.CreateControl();
        _ = host.Handle;
        viewport.CreateControl();
        _ = viewport.Handle;
        if (!viewport.TryInitialize(out var initializeError))
        {
            throw new InvalidOperationException($"Hidden Material Authority viewport initialization failed: {initializeError}");
        }
        viewport.ApplyPresentationSettings(new D3D11PresentationSettings
        {
            CullBackFaces = false,
            DisableLighting = false,
            LightAzimuthDegrees = -28.0f,
            LightElevationDegrees = 22.0f,
            AmbientStrength = 0.72f,
            DiffuseLightScale = 0.78f,
            EnvironmentStrength = 0.64f,
            SpecularBase = 0.06f,
            SpecularMax = 0.72f,
            ToneExposure = 1.0f,
            ToneContrast = 1.04f,
            ToneGamma = 1.0f,
        });
        var camera = NetViewportCamera.Create(
            new Vec3(0.0f, 0.0f, 0.0f),
            document.Bounds(),
            0.0f,
            0.0f,
            52.0f,
            0.0f,
            0.0f,
            CaptureWidth,
            CaptureHeight);
        viewport.UpdateCamera(camera);
        if (!viewport.TryRunHeadlessFrame(out _, out _, out var firstFrameError))
        {
            throw new InvalidOperationException($"Hidden Material Authority first frame failed: {firstFrameError}");
        }

        var processId = Environment.ProcessId;
        var geometryUploadsBefore = viewport.GeometryUploadCount;
        var renderSurfaceBefore = viewport.RenderSurfaceIdentity;
        var deviceResetsBefore = viewport.DeviceResetCount;
        var rows = new List<Dictionary<string, object?>>();
        long generation = 2;
        var revision = 0;
        foreach (var definition in Cases())
        {
            revision++;
            var baselinePaths = WriteMaterialPaths(evidenceDirectory, $"{revision:00}-{definition.Key}-before", changed: false);
            var changedPaths = WriteMaterialPaths(evidenceDirectory, $"{revision:00}-{definition.Key}-after", changed: true);
            var beforePaths = ApplyResourceMode(definition, baselinePaths, changedPaths, before: true);
            var afterPaths = ApplyResourceMode(definition, baselinePaths, changedPaths, before: false);
            var beforeParameters = ParametersForCase(definition, before: true);
            var afterParameters = ParametersForCase(definition, before: false);
            var beforeUpdate = ParseStateUpdate(
                beforePaths,
                stableRight,
                revision,
                generation++,
                new[] { 0 },
                beforeParameters);
            ApplyState(materials, textures, viewport, beforeUpdate);
            var beforeCapture = Path.Combine(evidenceDirectory, $"{revision:00}-{definition.Key}-before.png");
            var beforeCaptured = viewport.TryCaptureReplacementPng(
                beforeCapture,
                CaptureWidth,
                CaptureHeight,
                out var beforeFrameHash,
                out var beforeCaptureError);
            var metricsBefore = viewport.ResourceMetricsPayload();
            var afterUpdate = ParseStateUpdate(
                afterPaths,
                stableRight,
                revision,
                generation++,
                new[] { 0 },
                afterParameters);
            ApplyState(materials, textures, viewport, afterUpdate);
            var afterCapture = Path.Combine(evidenceDirectory, $"{revision:00}-{definition.Key}-after.png");
            var afterCaptured = viewport.TryCaptureReplacementPng(
                afterCapture,
                CaptureWidth,
                CaptureHeight,
                out var afterFrameHash,
                out var afterCaptureError);
            var metricsAfter = viewport.ResourceMetricsPayload();
            var deltas = beforeCaptured && afterCaptured
                ? PixelDeltas(beforeCapture, afterCapture)
                : new Dictionary<string, object?>
                {
                    ["full_delta_pixels"] = 0L,
                    ["affected_left_delta_pixels"] = 0L,
                    ["unaffected_right_delta_pixels"] = long.MaxValue,
                    ["max_channel_delta"] = 0,
                };
            var parameterState = materials.ParametersForSubmesh(0);
            var parameterExact = ParameterStateMatches(definition, parameterState);
            var beforeHashes = ResourceHashes(beforePaths);
            var afterHashes = ResourceHashes(afterPaths);
            var fingerprint = Fingerprint(definition.Key, revision, afterHashes, afterParameters);
            var affectedDelta = Convert.ToInt64(deltas["affected_left_delta_pixels"], CultureInfo.InvariantCulture);
            var unaffectedDelta = Convert.ToInt64(deltas["unaffected_right_delta_pixels"], CultureInfo.InvariantCulture);
            var noGeometryReload = Metric(metricsBefore, "geometry_buffer_identity") == Metric(metricsAfter, "geometry_buffer_identity")
                && viewport.GeometryUploadCount == geometryUploadsBefore;
            var stableRenderer = viewport.RenderSurfaceIdentity == renderSurfaceBefore
                && viewport.DeviceResetCount == deviceResetsBefore
                && string.IsNullOrWhiteSpace(viewport.DeviceRemovedReason);
            var ok = beforeCaptured
                && afterCaptured
                && affectedDelta > 0
                && unaffectedDelta == 0
                && parameterExact
                && noGeometryReload
                && stableRenderer;
            rows.Add(new Dictionary<string, object?>
            {
                ["control_key"] = definition.Key,
                ["revision"] = revision,
                ["fingerprint"] = fingerprint,
                ["artifact_channels"] = definition.ArtifactChannels,
                ["parameter"] = definition.Parameter,
                ["before_capture"] = beforeCapture,
                ["after_capture"] = afterCapture,
                ["before_frame_sha256"] = beforeFrameHash,
                ["after_frame_sha256"] = afterFrameHash,
                ["before_capture_error"] = beforeCaptureError,
                ["after_capture_error"] = afterCaptureError,
                ["pixel_deltas"] = deltas,
                ["resource_hashes_before"] = beforeHashes,
                ["resource_hashes_after"] = afterHashes,
                ["parameter_state"] = ParameterPayload(parameterState),
                ["parameter_state_exact"] = parameterExact,
                ["affected_part_changed"] = affectedDelta > 0,
                ["unaffected_part_isolated"] = unaffectedDelta == 0,
                ["no_geometry_reload"] = noGeometryReload,
                ["render_surface_stable"] = viewport.RenderSurfaceIdentity == renderSurfaceBefore,
                ["device_stable"] = stableRenderer,
                ["process_id"] = processId,
                ["resources_before"] = metricsBefore,
                ["resources_after"] = metricsAfter,
                ["ok"] = ok,
            });
        }

        var expectedControls = Cases().Select(item => item.Key).Order(StringComparer.Ordinal).ToArray();
        var uniqueControls = expectedControls.Distinct(StringComparer.Ordinal).ToArray();
        var controlsComplete = expectedControls.Length == 38 && uniqueControls.Length == 38;
        var allRowsPass = rows.Count == 38 && rows.All(row => row.GetValueOrDefault("ok") is true);
        var hidden = host.IsHandleCreated
            && viewport.IsHandleCreated
            && !host.Visible
            && !HeadlessGpuSparseSoak.IsWindowVisibleForProof(host.Handle)
            && !HeadlessGpuSparseSoak.IsWindowVisibleForProof(viewport.Handle)
            && !host.ShowInTaskbar;
        var overall = controlsComplete
            && allRowsPass
            && hidden
            && viewport.GeometryUploadCount == geometryUploadsBefore
            && viewport.RenderSurfaceIdentity == renderSurfaceBefore
            && viewport.DeviceResetCount == deviceResetsBefore
            && Environment.ProcessId == processId;
        return (
            new Dictionary<string, object?>
            {
                ["schema"] = Schema,
                ["evidence_class"] = "hidden_synthetic_production_renderer_regression",
                ["parity_scope"] = "Exact resident DDS resources and canonical parameter state used by the production .NET renderer; proprietary in-game shader graphs, lighting, and post-processing are excluded.",
                ["generated_at_utc"] = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture),
                ["backend"] = viewport.BackendName,
                ["process_id"] = processId,
                ["control_count"] = rows.Count,
                ["expected_control_keys"] = expectedControls,
                ["controls_classified_once"] = controlsComplete,
                ["native_windows_hidden"] = hidden,
                ["mesh_reload_count"] = viewport.GeometryUploadCount - geometryUploadsBefore,
                ["process_reload_count"] = Environment.ProcessId == processId ? 0 : 1,
                ["viewport_replacement_count"] = 0,
                ["camera_reset_count"] = 0,
                ["render_surface_identity_before"] = renderSurfaceBefore,
                ["render_surface_identity_after"] = viewport.RenderSurfaceIdentity,
                ["device_reset_count_before"] = deviceResetsBefore,
                ["device_reset_count_after"] = viewport.DeviceResetCount,
                ["cases"] = rows,
                ["ok"] = overall,
            },
            overall);
    }

    private static IReadOnlyList<CaseDefinition> Cases() => new CaseDefinition[]
    {
        new("global_gloss_reduction", new[] { "material" }),
        new("auto_brightness", new[] { "base" }),
        new("source_brightness", new[] { "base" }),
        new("tone_contrast", new[] { "base" }),
        new("edge_relief", new[] { "normal", "height", "material" }, "add"),
        new("edge_relief_source", new[] { "normal", "height", "material" }),
        new("accent_glow", Array.Empty<string>(), Parameter: "emissive_intensity", BeforeParameter: 1.0f, AfterParameter: 5.5f),
        new("part_glow_color", new[] { "emissive" }),
        new("part_glow_strength", Array.Empty<string>(), Parameter: "emissive_intensity", BeforeParameter: 1.0f, AfterParameter: 3.0f),
        new("base_binding_mode", new[] { "base" }, "remove"),
        new("mask_binding_mode", new[] { "material" }, "remove"),
        new("support_policy", new[] { "normal", "height", "material" }, "add"),
        new("emissive_mode", new[] { "emissive" }, "remove"),
        new("base_color_lift", new[] { "base" }),
        new("base_color_gamma", new[] { "base" }),
        new("base_color_saturation", new[] { "base" }),
        new("base_color_value_max", new[] { "base" }),
        new("base_color_scale", new[] { "base" }),
        new("emissive_color_scale", new[] { "emissive" }),
        new("emissive_color_saturation", new[] { "emissive" }),
        new("emissive_color_value_max", new[] { "emissive" }),
        new("roughness_default", new[] { "material" }),
        new("roughness_min", new[] { "material" }),
        new("roughness_scale", new[] { "material" }),
        new("roughness_max", new[] { "material" }),
        new("metallic_default", new[] { "material" }),
        new("metallic_min", new[] { "material" }),
        new("metallic_scale", new[] { "material" }),
        new("metallic_max", new[] { "material" }),
        new("displacement_scale_multiplier", Array.Empty<string>(), Parameter: "height_scale", BeforeParameter: 0.2f, AfterParameter: 0.8f),
        new("displacement_scale_max", Array.Empty<string>(), Parameter: "height_scale", BeforeParameter: 0.2f, AfterParameter: 0.8f),
        new("ao_default", new[] { "material" }),
        new("force_nonmetal", new[] { "material" }),
        new("roughness_inverted", new[] { "material" }),
        new("metallic_inverted", new[] { "material" }),
        new("allow_factor_only_authority", new[] { "base" }, "add"),
        new("factor_only_material_mask", new[] { "material" }, "add"),
        new("force_neutral_layer_support", new[] { "normal", "height", "material" }, "add"),
    };

    private static void ApplyState(
        NetMaterialSet materials,
        NetTextureSet textures,
        D3D11MaterialViewport viewport,
        NetMaterialStateUpdate update)
    {
        var affectedResources = update.ResourceIdsForAffectedSubmeshes();
        var decode = textures.DecodeResourcesAsync(
            update.Resources.Where(resource => affectedResources.Contains(resource.ResourceId))).GetAwaiter().GetResult();
        if (decode.Failures.Count > 0)
        {
            throw new InvalidOperationException(
                "Material Authority DDS decode failed: "
                + string.Join("; ", decode.Failures.Select(pair => $"{pair.Key}: {pair.Value}")));
        }
        var previous = materials.CaptureState();
        materials.ReplaceState(materials.BuildState(update));
        if (!viewport.TryApplyMaterialState(update.AffectedSubmeshes, out var error))
        {
            materials.ReplaceState(previous);
            throw new InvalidOperationException($"Material Authority state apply failed: {error}");
        }
        textures.PruneToResources(materials.TextureLoadResources());
    }

    private static NetMaterialStateUpdate ParseStateUpdate(
        MaterialPaths left,
        MaterialPaths right,
        long editRevision,
        long generation,
        int[] affectedSubmeshes,
        Dictionary<string, object?> leftParameters)
    {
        var resources = new List<Dictionary<string, object?>>();
        var submeshes = new List<Dictionary<string, object?>>();
        AddMaterialState(resources, submeshes, 0, "selected_part", left, leftParameters);
        AddMaterialState(resources, submeshes, 1, "unaffected_part", right, Parameters(1.0f, 0.45f));
        var payload = new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_mesh_material_state_v2",
            ["version"] = 2,
            ["session_id"] = "material-authority-parity",
            ["edit_revision"] = editRevision,
            ["generation"] = generation,
            ["material_signature"] = $"material-authority-parity-{editRevision}-{generation}",
            ["affected_submeshes"] = affectedSubmeshes,
            ["resources"] = resources,
            ["submeshes"] = submeshes,
        };
        using var json = JsonDocument.Parse(JsonSerializer.Serialize(payload));
        return NetMaterialSet.ParseStateUpdate(json.RootElement);
    }

    private static void AddMaterialState(
        List<Dictionary<string, object?>> resources,
        List<Dictionary<string, object?>> submeshes,
        int index,
        string material,
        MaterialPaths paths,
        Dictionary<string, object?> parameters)
    {
        var channels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var colorSpaces = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        void AddResource(string channel, string path, bool srgb)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                return;
            }
            var id = $"ma-parity:{index}:{channel}:{Sha256(path)[..12]}";
            resources.Add(new Dictionary<string, object?>
            {
                ["resource_id"] = id,
                ["path"] = path,
                ["fingerprint"] = Sha256(path),
                ["role"] = "replacement",
                ["submesh_index"] = index,
                ["material_channel"] = channel,
                ["semantic"] = channel,
                ["color_space"] = srgb ? "srgb" : "linear",
                ["semantic_authority"] = "material_authority_exact",
                ["profile"] = "material_authority_parity",
                ["required"] = true,
                ["fallback_policy"] = "reject",
            });
            channels[channel] = id;
            colorSpaces[channel] = srgb ? "srgb" : "linear";
        }
        AddResource("base", paths.Base, srgb: true);
        AddResource("normal", paths.Normal, srgb: false);
        AddResource("height", paths.Height, srgb: false);
        AddResource("emissive", paths.Emissive, srgb: true);
        if (!string.IsNullOrWhiteSpace(paths.Material))
        {
            var id = $"ma-parity:{index}:material:{Sha256(paths.Material)[..12]}";
            resources.Add(new Dictionary<string, object?>
            {
                ["resource_id"] = id,
                ["path"] = paths.Material,
                ["fingerprint"] = Sha256(paths.Material),
                ["role"] = "replacement",
                ["submesh_index"] = index,
                ["material_channel"] = "material",
                ["semantic"] = "material",
                ["color_space"] = "linear",
                ["semantic_authority"] = "material_authority_exact",
                ["profile"] = "material_authority_parity",
                ["required"] = true,
                ["fallback_policy"] = "reject",
            });
            foreach (var semantic in new[] { "ao", "roughness", "metallic" })
            {
                channels[semantic] = id;
                colorSpaces[semantic] = "linear";
            }
        }
        submeshes.Add(new Dictionary<string, object?>
        {
            ["submesh_index"] = index,
            ["material_slot_index"] = index,
            ["material"] = material,
            ["channels"] = channels,
            ["channel_components"] = new Dictionary<string, string>
            {
                ["ao"] = "r",
                ["roughness"] = "g",
                ["metallic"] = "b",
            },
            ["channel_color_spaces"] = colorSpaces,
            ["alpha_mode"] = "opaque",
            ["double_sided"] = true,
            ["material_category"] = "metal",
            ["material_category_confidence"] = 1.0,
            ["material_response_promoted"] = true,
            ["parameters"] = parameters,
        });
    }

    private static Dictionary<string, object?> Parameters(float emissiveIntensity, float heightScale) => new()
    {
        ["texture_brightness"] = 1.0,
        ["contrast"] = 1.0,
        ["post_contrast_brightness"] = 1.0,
        ["saturation"] = 1.0,
        ["gamma"] = 1.0,
        ["tint_color"] = new[] { 1.0, 1.0, 1.0 },
        ["emissive_intensity"] = emissiveIntensity,
        ["emissive_color"] = new[] { 1.0, 1.0, 1.0 },
        ["height_scale"] = heightScale,
        ["material_role"] = "emissive",
    };

    private static Dictionary<string, object?> ParametersForCase(CaseDefinition definition, bool before)
    {
        var emissive = 1.0f;
        var height = 0.45f;
        var value = before ? definition.BeforeParameter : definition.AfterParameter;
        if (string.Equals(definition.Parameter, "emissive_intensity", StringComparison.Ordinal))
        {
            emissive = value;
        }
        else if (string.Equals(definition.Parameter, "height_scale", StringComparison.Ordinal))
        {
            height = value;
        }
        return Parameters(emissive, height);
    }

    private static bool ParameterStateMatches(CaseDefinition definition, NetMaterialParameters state)
    {
        if (string.Equals(definition.Parameter, "emissive_intensity", StringComparison.Ordinal))
        {
            return state.EmissiveIntensity == definition.AfterParameter;
        }
        if (string.Equals(definition.Parameter, "height_scale", StringComparison.Ordinal))
        {
            return state.HeightScale == definition.AfterParameter;
        }
        return state.EmissiveIntensity == 1.0f && state.HeightScale == 0.45f;
    }

    private static Dictionary<string, object?> ParameterPayload(NetMaterialParameters state) => new()
    {
        ["texture_brightness"] = state.TextureBrightness,
        ["contrast"] = state.Contrast,
        ["post_contrast_brightness"] = state.PostContrastBrightness,
        ["saturation"] = state.Saturation,
        ["gamma"] = state.Gamma,
        ["emissive_intensity"] = state.EmissiveIntensity,
        ["emissive_color"] = state.EmissiveColor is { } color ? new[] { color.X, color.Y, color.Z } : null,
        ["height_scale"] = state.HeightScale,
        ["material_role"] = state.MaterialRole,
    };

    private static MaterialPaths ApplyResourceMode(
        CaseDefinition definition,
        MaterialPaths baseline,
        MaterialPaths changed,
        bool before)
    {
        var selected = before ? baseline : changed;
        if (string.Equals(definition.ResourceMode, "remove", StringComparison.Ordinal))
        {
            selected = before ? baseline : ClearChannels(baseline, definition.ArtifactChannels);
        }
        else if (string.Equals(definition.ResourceMode, "add", StringComparison.Ordinal))
        {
            selected = before
                ? ClearChannels(baseline, definition.ArtifactChannels)
                : CopyChangedChannels(baseline, changed, definition.ArtifactChannels);
        }
        else if (!before)
        {
            selected = CopyChangedChannels(baseline, changed, definition.ArtifactChannels);
        }
        return selected;
    }

    private static MaterialPaths ClearChannels(MaterialPaths source, IEnumerable<string> channels)
    {
        var set = channels.ToHashSet(StringComparer.OrdinalIgnoreCase);
        return source with
        {
            Base = set.Contains("base") ? string.Empty : source.Base,
            Normal = set.Contains("normal") ? string.Empty : source.Normal,
            Height = set.Contains("height") ? string.Empty : source.Height,
            Material = set.Contains("material") ? string.Empty : source.Material,
            Emissive = set.Contains("emissive") ? string.Empty : source.Emissive,
        };
    }

    private static MaterialPaths CopyChangedChannels(
        MaterialPaths baseline,
        MaterialPaths changed,
        IEnumerable<string> channels)
    {
        var set = channels.ToHashSet(StringComparer.OrdinalIgnoreCase);
        return baseline with
        {
            Base = set.Contains("base") ? changed.Base : baseline.Base,
            Normal = set.Contains("normal") ? changed.Normal : baseline.Normal,
            Height = set.Contains("height") ? changed.Height : baseline.Height,
            Material = set.Contains("material") ? changed.Material : baseline.Material,
            Emissive = set.Contains("emissive") ? changed.Emissive : baseline.Emissive,
        };
    }

    private static MaterialPaths WriteMaterialPaths(string root, string prefix, bool changed)
    {
        var basePath = Path.Combine(root, $"{prefix}-base.dds");
        var normalPath = Path.Combine(root, $"{prefix}-normal.dds");
        var heightPath = Path.Combine(root, $"{prefix}-height.dds");
        var materialPath = Path.Combine(root, $"{prefix}-material.dds");
        var emissivePath = Path.Combine(root, $"{prefix}-emissive.dds");
        WriteDds(basePath, changed ? Color.FromArgb(255, 30, 88, 220) : Color.FromArgb(255, 190, 118, 42), srgb: true);
        WriteDds(normalPath, changed ? Color.FromArgb(255, 215, 74, 205) : Color.FromArgb(255, 128, 128, 255), srgb: false);
        WriteDds(heightPath, changed ? Color.White : Color.FromArgb(255, 36, 36, 36), srgb: false);
        WriteDds(materialPath, changed ? Color.FromArgb(255, 255, 24, 245) : Color.FromArgb(255, 255, 225, 8), srgb: false);
        WriteDds(emissivePath, changed ? Color.FromArgb(255, 240, 20, 12) : Color.FromArgb(255, 12, 5, 3), srgb: true);
        return new MaterialPaths(basePath, normalPath, heightPath, materialPath, emissivePath);
    }

    private static void WriteDds(string path, Color color, bool srgb)
    {
        const int width = 16;
        const int height = 16;
        using var stream = File.Create(path);
        using var writer = new BinaryWriter(stream, Encoding.ASCII, leaveOpen: false);
        writer.Write(Encoding.ASCII.GetBytes("DDS "));
        writer.Write(124u);
        writer.Write(0x0000100Fu);
        writer.Write((uint)height);
        writer.Write((uint)width);
        writer.Write((uint)(width * 4));
        writer.Write(0u);
        writer.Write(1u);
        for (var index = 0; index < 11; index++) writer.Write(0u);
        writer.Write(32u);
        writer.Write(0x00000004u);
        writer.Write(Encoding.ASCII.GetBytes("DX10"));
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(0x00001000u);
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(0u);
        writer.Write(srgb ? 91 : 87);
        writer.Write(3);
        writer.Write(0u);
        writer.Write(1);
        writer.Write(0u);
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var checker = ((x / 4) + (y / 4)) % 2 == 0 ? 1.0f : 0.72f;
                writer.Write((byte)Math.Clamp((int)Math.Round(color.B * checker), 0, 255));
                writer.Write((byte)Math.Clamp((int)Math.Round(color.G * checker), 0, 255));
                writer.Write((byte)Math.Clamp((int)Math.Round(color.R * checker), 0, 255));
                writer.Write(color.A);
            }
        }
    }

    private static ObjDocument BuildTwoPartDocument()
    {
        var document = new ObjDocument();
        AddQuad(document, "selected_part", -1.65f, -0.15f);
        AddQuad(document, "unaffected_part", 0.15f, 1.65f);
        return document;
    }

    private static void AddQuad(ObjDocument document, string name, float left, float right)
    {
        var submesh = new ObjSubmesh(name, 0, 0, 0);
        document.Submeshes.Add(submesh);
        submesh.Vertices.AddRange(new[]
        {
            new Vec3(left, -0.85f, 0.0f),
            new Vec3(right, -0.85f, 0.0f),
            new Vec3(right, 0.85f, 0.0f),
            new Vec3(left, 0.85f, 0.0f),
        });
        submesh.Normals.AddRange(Enumerable.Repeat(new Vec3(0.0f, 0.0f, 1.0f), 4));
        submesh.Uvs.AddRange(new[]
        {
            new Vec2(0.0f, 1.0f),
            new Vec2(1.0f, 1.0f),
            new Vec2(1.0f, 0.0f),
            new Vec2(0.0f, 0.0f),
        });
        submesh.Faces.Add(new ObjFace(new[]
        {
            new ObjCorner(0, 0, 0), new ObjCorner(1, 1, 1), new ObjCorner(2, 2, 2),
        }));
        submesh.Faces.Add(new ObjFace(new[]
        {
            new ObjCorner(0, 0, 0), new ObjCorner(2, 2, 2), new ObjCorner(3, 3, 3),
        }));
    }

    private static Dictionary<string, object?> PixelDeltas(string beforePath, string afterPath)
    {
        using var before = new Bitmap(beforePath);
        using var after = new Bitmap(afterPath);
        long full = 0;
        long left = 0;
        long right = 0;
        var maxDelta = 0;
        for (var y = 0; y < before.Height; y++)
        {
            for (var x = 0; x < before.Width; x++)
            {
                var a = before.GetPixel(x, y);
                var b = after.GetPixel(x, y);
                var delta = Math.Max(Math.Abs(a.R - b.R), Math.Max(Math.Abs(a.G - b.G), Math.Abs(a.B - b.B)));
                maxDelta = Math.Max(maxDelta, delta);
                if (delta <= 1) continue;
                full++;
                if (x < before.Width / 2) left++; else right++;
            }
        }
        return new Dictionary<string, object?>
        {
            ["full_delta_pixels"] = full,
            ["affected_left_delta_pixels"] = left,
            ["unaffected_right_delta_pixels"] = right,
            ["max_channel_delta"] = maxDelta,
        };
    }

    private static Dictionary<string, string> ResourceHashes(MaterialPaths paths)
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (channel, path) in new[]
        {
            ("base", paths.Base), ("normal", paths.Normal), ("height", paths.Height),
            ("material", paths.Material), ("emissive", paths.Emissive),
        })
        {
            result[channel] = string.IsNullOrWhiteSpace(path) ? "removed" : Sha256(path);
        }
        return result;
    }

    private static string Fingerprint(
        string key,
        int revision,
        IReadOnlyDictionary<string, string> hashes,
        IReadOnlyDictionary<string, object?> parameters)
    {
        var payload = JsonSerializer.Serialize(new { key, revision, hashes, parameters });
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(payload))).ToLowerInvariant();
    }

    private static string Sha256(string path) =>
        Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();

    private static long Metric(IReadOnlyDictionary<string, object?> payload, string key) =>
        Convert.ToInt64(payload.GetValueOrDefault(key) ?? 0L, CultureInfo.InvariantCulture);

    private static Form CreateHiddenHost() => new()
    {
        Text = "CDMW hidden Material Authority parity",
        ClientSize = new Size(CaptureWidth, CaptureHeight),
        StartPosition = FormStartPosition.Manual,
        Location = new Point(-32000, -32000),
        FormBorderStyle = FormBorderStyle.None,
        ShowInTaskbar = false,
        Visible = false,
    };

    private static string ReportPath(string[] args)
    {
        var index = Array.FindIndex(args, arg =>
            string.Equals(arg, "--material-authority-parity-report", StringComparison.OrdinalIgnoreCase));
        if (index >= 0 && index + 1 < args.Length && !args[index + 1].StartsWith("--", StringComparison.Ordinal))
        {
            return Path.GetFullPath(args[index + 1]);
        }
        return Path.Combine(Environment.CurrentDirectory, "dotnet-material-authority-parity.json");
    }

    private static void WriteReport(string path, IReadOnlyDictionary<string, object?> report)
    {
        var fullPath = Path.GetFullPath(path);
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath) ?? throw new InvalidOperationException("Report path has no parent directory."));
        File.WriteAllText(fullPath, JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
    }
}
