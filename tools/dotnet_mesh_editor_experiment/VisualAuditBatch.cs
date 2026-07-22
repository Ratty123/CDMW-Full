using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal static class VisualAuditBatch
{
    private const string ManifestArgument = "--visual-audit-batch";
    private const string ReportArgument = "--visual-audit-report";
    private const int MaximumAssets = 128;
    private const int MaximumViewsPerAsset = 12;
    private const int MaximumMaterialRegionsPerAsset = 512;

    public static bool IsRequested(string[] args) => ArgumentValue(args, ManifestArgument) is not null;

    public static int Run(string[] args)
    {
        var manifestPath = RequiredArgument(args, ManifestArgument);
        var reportPath = RequiredArgument(args, ReportArgument);
        var started = Stopwatch.StartNew();
        var rows = new List<Dictionary<string, object?>>();
        var fatalError = string.Empty;
        var outputRoot = string.Empty;
        var runId = string.Empty;
        var requestedAssetCount = 0;
        var sessionSummary = new Dictionary<string, object?>();
        try
        {
            using var manifest = JsonDocument.Parse(File.ReadAllText(manifestPath));
            var root = manifest.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidDataException("Visual-audit manifest must be a JSON object.");
            }
            var schema = JsonRequiredString(root, "schema");
            if (!string.Equals(schema, "cdmw_mesh_visual_audit_dotnet_batch_v1", StringComparison.Ordinal)
                && !string.Equals(schema, "cdmw_mesh_visual_audit_dotnet_batch_v2", StringComparison.Ordinal))
            {
                throw new InvalidDataException($"Unsupported visual-audit manifest schema: {schema}");
            }
            runId = SafeName(JsonRequiredString(root, "run_id"));
            outputRoot = Path.GetFullPath(JsonRequiredString(root, "output_root"));
            Directory.CreateDirectory(outputRoot);
            var width = Math.Clamp(JsonInt(root, "width", 768), 64, 2048);
            var height = Math.Clamp(JsonInt(root, "height", 768), 64, 2048);
            if (!root.TryGetProperty("assets", out var assets) || assets.ValueKind != JsonValueKind.Array)
            {
                throw new InvalidDataException("Visual-audit manifest has no assets array.");
            }
            requestedAssetCount = assets.GetArrayLength();
            if (requestedAssetCount <= 0 || requestedAssetCount > MaximumAssets)
            {
                throw new InvalidDataException($"Visual-audit asset count must be between 1 and {MaximumAssets}.");
            }
            using var session = new ResidentVisualAuditSession(width, height);
            foreach (var asset in assets.EnumerateArray())
            {
                rows.Add(CaptureAsset(asset, outputRoot, width, height, session));
                Application.DoEvents();
            }
            sessionSummary = session.SummaryPayload();
        }
        catch (Exception ex)
        {
            fatalError = $"{ex.GetType().Name}: {ex.Message}";
        }

        var ok = fatalError.Length == 0
            && rows.Count == requestedAssetCount
            && rows.All(row => row.TryGetValue("ok", out var value) && value is true);
        var residentMaterialUpdates = rows
            .Select(row => row.GetValueOrDefault("resident_material_update"))
            .OfType<Dictionary<string, object?>>()
            .Where(row => row.GetValueOrDefault("requested") is true)
            .ToArray();
        var report = new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_mesh_visual_audit_dotnet_batch_v2",
            ["compatible_reader_schemas"] = new[] { "cdmw_mesh_visual_audit_dotnet_batch_v1" },
            ["run_id"] = runId,
            ["ok"] = ok,
            ["process_id"] = Environment.ProcessId,
            ["process_start_count"] = 1,
            ["process_restart_count"] = 0,
            ["requested_asset_count"] = requestedAssetCount,
            ["completed_asset_count"] = rows.Count,
            ["resident_material_update_count"] = residentMaterialUpdates.Count(row =>
                row.GetValueOrDefault("ok") is true),
            ["resident_material_update_failure_count"] = residentMaterialUpdates.Count(row =>
                row.GetValueOrDefault("ok") is not true),
            ["total_ms"] = started.Elapsed.TotalMilliseconds,
            ["output_root"] = outputRoot,
            ["fatal_error"] = fatalError,
            ["renderer_session"] = sessionSummary,
            ["assets"] = rows,
        };
        AtomicWriteJson(reportPath, report);
        return ok ? 0 : 1;
    }

    private static Dictionary<string, object?> CaptureAsset(
        JsonElement asset,
        string outputRoot,
        int width,
        int height,
        ResidentVisualAuditSession session)
    {
        var assetStarted = Stopwatch.StartNew();
        var assetId = JsonRequiredString(asset, "id");
        var packageDir = Path.GetFullPath(JsonRequiredString(asset, "package_dir"));
        var assetOutput = OwnedOutputDirectory(outputRoot, assetId);
        Directory.CreateDirectory(assetOutput);
        var captures = new List<Dictionary<string, object?>>();
        var materialRegions = new List<Dictionary<string, object?>>();
        var rendererStatus = new Dictionary<string, object?>();
        var residentMaterialUpdate = new Dictionary<string, object?>
        {
            ["requested"] = false,
            ["ok"] = false,
            ["reason"] = "resident material state was not supplied",
        };
        var error = string.Empty;
        var sourceSubmeshCount = 0;
        var parseMs = 0.0;
        var textureReadyMs = 0.0;
        var rendererStartMs = 0.0;
        NetTextureSet? textures = null;
        var rendererAdoptedTextures = false;
        try
        {
            var scenePath = Path.Combine(packageDir, "scene.obj");
            var materialsPath = Path.Combine(packageDir, "net_materials.json");
            var sceneStatePath = Path.Combine(packageDir, "dotnet_scene.json");
            RequirePackageFile(packageDir, scenePath);
            RequirePackageFile(packageDir, materialsPath);
            RequirePackageFile(packageDir, sceneStatePath);

            var phase = Stopwatch.StartNew();
            var document = ObjDocument.Load(scenePath);
            sourceSubmeshCount = document.Submeshes.Count;
            var materials = NetMaterialSet.Load(materialsPath);
            var scene = NetSceneState.Load(sceneStatePath, document.Submeshes.Count);
            scene.SetPresentationOverlayVisibility(gridVisible: false, gizmoVisible: false);
            parseMs = phase.Elapsed.TotalMilliseconds;

            textures = NetTextureSet.Load(materials);
            phase.Restart();
            textures.LoadAsync(materials).GetAwaiter().GetResult();
            textureReadyMs = phase.Elapsed.TotalMilliseconds;
            var requiredFailures = materials.FailedRequiredResources(textures.TextureLoadFailures);
            if (requiredFailures.Count > 0)
            {
                throw new InvalidDataException(
                    "Required production texture resources failed: "
                    + string.Join("; ", requiredFailures.Select(resource =>
                        $"{resource.Role}[{resource.SubmeshIndex}].{resource.MaterialChannel}: {resource.Path}")));
            }

            phase.Restart();
            session.LoadScene(document, materials, textures, scene);
            rendererAdoptedTextures = true;
            rendererStartMs = phase.Elapsed.TotalMilliseconds;
            residentMaterialUpdate = ApplyResidentMaterialStateIfRequested(
                asset,
                assetId,
                assetOutput,
                document,
                materials,
                textures,
                session,
                width,
                height);
            if (residentMaterialUpdate.GetValueOrDefault("requested") is not true)
            {
                throw new InvalidDataException(
                    "Visual-audit v2 requires a canonical resident material state payload.");
            }
            if (residentMaterialUpdate.GetValueOrDefault("ok") is not true)
            {
                throw new InvalidDataException(
                    "Resident material state proof failed: "
                    + Convert.ToString(residentMaterialUpdate.GetValueOrDefault("reason")));
            }
            rendererStatus = session.StatusPayload();
            foreach (var view in AssetViews(asset))
            {
                var name = SafeName(JsonRequiredString(view, "name"));
                var yaw = JsonFloat(view, "yaw", 0.0f);
                var pitch = JsonFloat(view, "pitch", 0.0f);
                var rendererYaw = yaw;
                var rendererPitch = pitch;
                session.SetArchiveCamera(document, rendererYaw, rendererPitch);
                Application.DoEvents();
                var capturePath = Path.Combine(assetOutput, name + ".png");
                File.Delete(capturePath);
                phase.Restart();
                var captured = session.TryCapture(
                    capturePath,
                    width,
                    height,
                    out var sha256,
                    out var captureError,
                    out var renderedCamera);
                captures.Add(new Dictionary<string, object?>
                {
                    ["name"] = name,
                    ["yaw"] = yaw,
                    ["pitch"] = pitch,
                    ["renderer_yaw"] = rendererYaw,
                    ["renderer_pitch"] = rendererPitch,
                    ["camera_mapping"] = "archive_object_rotation_basis_orthographic_v1",
                    ["ok"] = captured,
                    ["path"] = capturePath,
                    ["bytes"] = captured ? new FileInfo(capturePath).Length : 0L,
                    ["sha256"] = sha256,
                    ["capture_ms"] = phase.Elapsed.TotalMilliseconds,
                    ["rendered_camera"] = new Dictionary<string, object?>
                    {
                        ["role"] = renderedCamera.Role,
                        ["yaw_degrees"] = renderedCamera.YawDegrees,
                        ["pitch_degrees"] = renderedCamera.PitchDegrees,
                        ["viewport_width"] = renderedCamera.ViewportWidth,
                        ["viewport_height"] = renderedCamera.ViewportHeight,
                        ["world_view_projection"] = renderedCamera.WorldViewProjection,
                        ["solid_draw_count"] = renderedCamera.SolidDrawCount,
                        ["sample_count"] = renderedCamera.SampleCount,
                        ["sample_quality"] = renderedCamera.SampleQuality,
                        ["multisample_resolved"] = renderedCamera.MultisampleResolved,
                    },
                    ["error"] = captureError,
                });
                if (!captured)
                {
                    throw new IOException($"Capture {name} failed: {captureError}");
                }
            }
            foreach (var region in AssetMaterialRegions(asset))
            {
                var submeshIndex = JsonInt(region, "source_submesh_index", -1);
                if (submeshIndex < 0 || submeshIndex >= document.Submeshes.Count)
                {
                    throw new InvalidDataException(
                        $"Visual-audit material region submesh index is out of range: {submeshIndex}");
                }
                var hidden = Enumerable.Range(0, document.Submeshes.Count)
                    .Where(index => index != submeshIndex)
                    .ToArray();
                scene.SetPresentationHiddenSubmeshes(hidden);
                session.SetMaterialDebugMode("final");
                var regionCaptures = new List<Dictionary<string, object?>>();
                foreach (var angle in RegionAngles(region))
                {
                    var angleName = SafeName(JsonRequiredString(angle, "name"));
                    var yaw = JsonFloat(angle, "yaw", 0.0f);
                    var pitch = JsonFloat(angle, "pitch", 0.0f);
                    session.SetMaterialRegionCamera(document, submeshIndex, yaw, pitch);
                    Application.DoEvents();
                    regionCaptures.Add(CaptureMaterialRegionFrame(
                        session,
                        assetOutput,
                        width,
                        height,
                        submeshIndex,
                        angleName,
                        "final",
                        yaw,
                        pitch));
                    if (!string.Equals(angleName, "oblique", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }
                    foreach (var debugMode in RegionDebugModes(region))
                    {
                        session.SetMaterialDebugMode(debugMode);
                        Application.DoEvents();
                        regionCaptures.Add(CaptureMaterialRegionFrame(
                            session,
                            assetOutput,
                            width,
                            height,
                            submeshIndex,
                            angleName,
                            debugMode,
                            yaw,
                            pitch));
                    }
                    session.SetMaterialDebugMode("final");
                }
                materialRegions.Add(new Dictionary<string, object?>
                {
                    ["source_submesh_index"] = submeshIndex,
                    ["submesh_name"] = document.Submeshes[submeshIndex].Name,
                    ["hidden_submesh_indices"] = hidden,
                    ["captures"] = regionCaptures,
                    ["ok"] = regionCaptures.Count > 0 && regionCaptures.All(row => row["ok"] is true),
                });
            }
            scene.SetPresentationHiddenSubmeshes(Array.Empty<int>());
            session.SetMaterialDebugMode("final");
            rendererStatus = session.StatusPayload();
        }
        catch (Exception ex)
        {
            error = $"{ex.GetType().Name}: {ex.Message}";
        }
        finally
        {
            if (!rendererAdoptedTextures)
            {
                textures?.Dispose();
            }
        }
        return new Dictionary<string, object?>
        {
            ["id"] = assetId,
            ["ok"] = error.Length == 0
                && captures.Count > 0
                && captures.All(row => row["ok"] is true)
                && materialRegions.All(row => row["ok"] is true),
            ["package_dir"] = packageDir,
            ["source_submesh_count"] = sourceSubmeshCount,
            ["backend"] = rendererStatus.GetValueOrDefault("backend") ?? "",
            ["source_parse_ms"] = parseMs,
            ["texture_ready_ms"] = textureReadyMs,
            ["renderer_start_ms"] = rendererStartMs,
            ["total_ms"] = assetStarted.Elapsed.TotalMilliseconds,
            ["renderer_status"] = rendererStatus,
            ["captures"] = captures,
            ["material_regions"] = materialRegions,
            ["resident_material_update"] = residentMaterialUpdate,
            ["error"] = error,
        };
    }

    private static Dictionary<string, object?> ApplyResidentMaterialStateIfRequested(
        JsonElement asset,
        string assetId,
        string assetOutput,
        ObjDocument document,
        NetMaterialSet materials,
        NetTextureSet textures,
        ResidentVisualAuditSession session,
        int width,
        int height)
    {
        if (!asset.TryGetProperty("resident_material_state_path", out var pathValue)
            || pathValue.ValueKind != JsonValueKind.String
            || string.IsNullOrWhiteSpace(pathValue.GetString()))
        {
            return new Dictionary<string, object?>
            {
                ["requested"] = false,
                ["ok"] = false,
                ["reason"] = "resident material state path is empty",
            };
        }

        var statePath = Path.GetFullPath(pathValue.GetString()!);
        var evidence = new Dictionary<string, object?>
        {
            ["requested"] = true,
            ["ok"] = false,
            ["state_path"] = statePath,
        };
        try
        {
            if (!File.Exists(statePath))
            {
                throw new FileNotFoundException("Resident material state payload is missing.", statePath);
            }
            using var stateDocument = JsonDocument.Parse(File.ReadAllText(statePath));
            var stateRoot = stateDocument.RootElement;
            var schema = stateRoot.TryGetProperty("schema", out var schemaValue)
                && schemaValue.ValueKind == JsonValueKind.String
                ? schemaValue.GetString() ?? string.Empty
                : string.Empty;
            if (!string.Equals(schema, "cdmw_mesh_material_state_v3", StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    $"Visual-audit resident material state must use v3, found {schema}.");
            }
            var update = materials.NormalizeStateUpdate(NetMaterialSet.ParseStateUpdate(stateRoot));
            if (!string.Equals(update.SessionId, assetId, StringComparison.Ordinal))
            {
                throw new InvalidDataException("Resident material state session does not match the audit asset.");
            }
            var expectedSubmeshes = Enumerable.Range(0, document.Submeshes.Count).ToArray();
            if (!update.AffectedSubmeshes.SequenceEqual(expectedSubmeshes))
            {
                throw new InvalidDataException(
                    "Resident material state must affect every visible source submesh in order.");
            }

            session.SetArchiveCamera(document, 0.0f, 0.0f);
            Application.DoEvents();
            var beforePath = Path.Combine(assetOutput, "resident-material-before.png");
            var afterPath = Path.Combine(assetOutput, "resident-material-after.png");
            File.Delete(beforePath);
            File.Delete(afterPath);
            var beforeCaptured = session.TryCapture(
                beforePath,
                width,
                height,
                out var beforeHash,
                out var beforeError,
                out var beforeCamera);
            var before = session.MaterialStabilitySnapshot();

            var affectedResources = update.ResourceIdsForAffectedSubmeshes();
            var decode = textures.DecodeResourcesAsync(
                update.Resources.Where(resource => affectedResources.Contains(resource.ResourceId)))
                .GetAwaiter().GetResult();
            var resourcesById = update.Resources.ToDictionary(
                resource => resource.ResourceId,
                StringComparer.Ordinal);
            var requiredFailures = decode.Failures
                .Where(pair => resourcesById.TryGetValue(pair.Key, out var resource) && resource.Required)
                .ToArray();
            if (requiredFailures.Length > 0)
            {
                throw new InvalidDataException(
                    "Required resident material resource decode failed: "
                    + string.Join("; ", requiredFailures.Select(pair => $"{pair.Key}: {pair.Value}")));
            }
            var optionalFailures = decode.Failures
                .Where(pair => !resourcesById.TryGetValue(pair.Key, out var resource) || !resource.Required)
                .Select(pair => new Dictionary<string, object?>
                {
                    ["resource_id"] = pair.Key,
                    ["message"] = pair.Value,
                    ["fallback_policy"] = resourcesById.TryGetValue(pair.Key, out var resource)
                        ? resource.FallbackPolicy
                        : "diagnostic_only",
                })
                .ToArray();
            var previous = materials.CaptureState();
            materials.ReplaceState(materials.BuildState(update));
            if (!session.TryApplyMaterialState(update.AffectedSubmeshes, out var applyError))
            {
                materials.ReplaceState(previous);
                throw new InvalidDataException($"Resident material state apply failed: {applyError}");
            }
            textures.PruneToResources(materials.TextureLoadResources());
            Application.DoEvents();

            var afterCaptured = session.TryCapture(
                afterPath,
                width,
                height,
                out var afterHash,
                out var afterError,
                out var afterCamera);
            var after = session.MaterialStabilitySnapshot();
            var geometryStable = before.GeometryUploadCount == after.GeometryUploadCount;
            var renderSurfaceStable = before.RenderSurfaceIdentity == after.RenderSurfaceIdentity;
            var deviceStable = before.DeviceResetAttemptCount == after.DeviceResetAttemptCount
                && before.DeviceResetCount == after.DeviceResetCount;
            var cameraStable = beforeCamera.WorldViewProjection.SequenceEqual(afterCamera.WorldViewProjection);
            var visualEquivalent = beforeCaptured
                && afterCaptured
                && string.Equals(beforeHash, afterHash, StringComparison.OrdinalIgnoreCase);
            var ok = visualEquivalent && geometryStable && renderSurfaceStable && deviceStable && cameraStable;
            evidence["schema"] = schema;
            evidence["edit_revision"] = update.EditRevision;
            evidence["generation"] = update.Generation;
            evidence["affected_submeshes"] = update.AffectedSubmeshes;
            evidence["resource_count"] = update.Resources.Count;
            evidence["optional_resource_failures"] = optionalFailures;
            evidence["before_capture"] = beforePath;
            evidence["after_capture"] = afterPath;
            evidence["before_capture_error"] = beforeError;
            evidence["after_capture_error"] = afterError;
            evidence["before_frame_sha256"] = beforeHash;
            evidence["after_frame_sha256"] = afterHash;
            evidence["initial_resident_visual_equivalent"] = visualEquivalent;
            evidence["geometry_upload_count_before"] = before.GeometryUploadCount;
            evidence["geometry_upload_count_after"] = after.GeometryUploadCount;
            evidence["no_geometry_reload"] = geometryStable;
            evidence["render_surface_identity_before"] = before.RenderSurfaceIdentity;
            evidence["render_surface_identity_after"] = after.RenderSurfaceIdentity;
            evidence["render_surface_stable"] = renderSurfaceStable;
            evidence["device_reset_attempt_count_before"] = before.DeviceResetAttemptCount;
            evidence["device_reset_attempt_count_after"] = after.DeviceResetAttemptCount;
            evidence["device_reset_count_before"] = before.DeviceResetCount;
            evidence["device_reset_count_after"] = after.DeviceResetCount;
            evidence["device_stable"] = deviceStable;
            evidence["camera_stable"] = cameraStable;
            evidence["ok"] = ok;
            evidence["reason"] = ok
                ? "canonical v3 state applied in place with identical initial/resident pixels"
                : "resident state changed pixels, geometry, camera, render surface, or device";
        }
        catch (Exception ex)
        {
            evidence["reason"] = $"{ex.GetType().Name}: {ex.Message}";
        }
        return evidence;
    }

    private static Dictionary<string, object?> CaptureMaterialRegionFrame(
        ResidentVisualAuditSession session,
        string assetOutput,
        int width,
        int height,
        int submeshIndex,
        string angleName,
        string debugMode,
        float yaw,
        float pitch)
    {
        var safeMode = SafeName(debugMode.Replace('_', '-'));
        var name = $"region-{submeshIndex:000}-{angleName}-{safeMode}";
        var capturePath = Path.Combine(assetOutput, name + ".png");
        File.Delete(capturePath);
        var phase = Stopwatch.StartNew();
        var captured = session.TryCapture(
            capturePath,
            width,
            height,
            out var sha256,
            out var captureError,
            out var renderedCamera);
        var row = new Dictionary<string, object?>
        {
            ["name"] = name,
            ["capture_kind"] = "material_region",
            ["source_submesh_index"] = submeshIndex,
            ["angle"] = angleName,
            ["debug_mode"] = debugMode,
            ["yaw"] = yaw,
            ["pitch"] = pitch,
            ["renderer_yaw"] = yaw,
            ["renderer_pitch"] = pitch,
            ["camera_mapping"] = "archive_object_rotation_basis_orthographic_v1",
            ["ok"] = captured,
            ["path"] = capturePath,
            ["bytes"] = captured ? new FileInfo(capturePath).Length : 0L,
            ["sha256"] = sha256,
            ["capture_ms"] = phase.Elapsed.TotalMilliseconds,
            ["rendered_camera"] = new Dictionary<string, object?>
            {
                ["role"] = renderedCamera.Role,
                ["yaw_degrees"] = renderedCamera.YawDegrees,
                ["pitch_degrees"] = renderedCamera.PitchDegrees,
                ["viewport_width"] = renderedCamera.ViewportWidth,
                ["viewport_height"] = renderedCamera.ViewportHeight,
                ["world_view_projection"] = renderedCamera.WorldViewProjection,
                ["solid_draw_count"] = renderedCamera.SolidDrawCount,
                ["sample_count"] = renderedCamera.SampleCount,
                ["sample_quality"] = renderedCamera.SampleQuality,
                ["multisample_resolved"] = renderedCamera.MultisampleResolved,
            },
            ["error"] = captureError,
        };
        if (!captured)
        {
            throw new IOException($"Capture {name} failed: {captureError}");
        }
        return row;
    }

    private sealed class ResidentVisualAuditSession : IDisposable
    {
        private readonly Form _form;
        private D3D11MaterialViewport? _viewport;
        private NetTextureSet? _activeTextures;
        private int _viewportCreateCount;
        private int _deviceInitializationCount;

        public ResidentVisualAuditSession(int width, int height)
        {
            _form = new Form
            {
                ClientSize = new Size(width, height),
                FormBorderStyle = FormBorderStyle.None,
                Location = new Point(-20000, -20000),
                ShowInTaskbar = false,
                StartPosition = FormStartPosition.Manual,
                Text = "CDMW resident visual audit",
            };
        }

        public void LoadScene(
            ObjDocument document,
            NetMaterialSet materials,
            NetTextureSet textures,
            NetSceneState scene)
        {
            if (_viewport is null)
            {
                var viewport = new D3D11MaterialViewport(document, materials, textures, scene)
                {
                    Dock = DockStyle.Fill,
                };
                viewport.ApplyPresentationSettings(new D3D11PresentationSettings());
                _form.Controls.Add(viewport);
                try
                {
                    _form.CreateControl();
                    _ = _form.Handle;
                    viewport.CreateControl();
                    _ = viewport.Handle;
                    Application.DoEvents();
                    if (!viewport.IsInitialized && !viewport.TryInitialize(out var error))
                    {
                        throw new InvalidOperationException(error);
                    }
                    if (!string.Equals(viewport.BackendName, "d3d11_vortice_shader", StringComparison.Ordinal))
                    {
                        throw new InvalidOperationException($"Unexpected renderer backend: {viewport.BackendName}");
                    }
                    _viewport = viewport;
                    _activeTextures = textures;
                    _viewportCreateCount = 1;
                    _deviceInitializationCount = 1;
                    return;
                }
                catch
                {
                    _form.Controls.Remove(viewport);
                    viewport.Dispose();
                    throw;
                }
            }

            var previousTextures = _activeTextures;
            _viewport.ReplaceResidentScene(document, materials, textures, scene);
            _activeTextures = textures;
            previousTextures?.Dispose();
            Application.DoEvents();
        }

        public void SetArchiveCamera(ObjDocument document, float yawDegrees, float pitchDegrees)
        {
            var viewport = RequireViewport();
            var bounds = document.Bounds();
            SetArchiveCameraBounds(viewport, bounds, yawDegrees, pitchDegrees);
        }

        public void SetMaterialRegionCamera(
            ObjDocument document,
            int submeshIndex,
            float yawDegrees,
            float pitchDegrees)
        {
            if (submeshIndex < 0 || submeshIndex >= document.Submeshes.Count)
            {
                throw new ArgumentOutOfRangeException(nameof(submeshIndex));
            }
            var vertices = document.Submeshes[submeshIndex].Vertices;
            if (vertices.Count == 0)
            {
                throw new InvalidDataException($"Material region {submeshIndex} has no vertices.");
            }
            var bounds = (
                new Vec3(vertices.Min(vertex => vertex.X), vertices.Min(vertex => vertex.Y), vertices.Min(vertex => vertex.Z)),
                new Vec3(vertices.Max(vertex => vertex.X), vertices.Max(vertex => vertex.Y), vertices.Max(vertex => vertex.Z)));
            SetArchiveCameraBounds(RequireViewport(), bounds, yawDegrees, pitchDegrees);
        }

        public void SetMaterialDebugMode(string mode)
        {
            var viewport = RequireViewport();
            viewport.MaterialDebugMode = MaterialDebugModeForName(mode);
            viewport.Invalidate();
        }

        private void SetArchiveCameraBounds(
            D3D11MaterialViewport viewport,
            (Vec3 Min, Vec3 Max) bounds,
            float yawDegrees,
            float pitchDegrees)
        {
            var center = new Vec3(
                (bounds.Min.X + bounds.Max.X) * 0.5f,
                (bounds.Min.Y + bounds.Max.Y) * 0.5f,
                (bounds.Min.Z + bounds.Max.Z) * 0.5f);
            var size = Math.Max(
                bounds.Max.X - bounds.Min.X,
                Math.Max(bounds.Max.Y - bounds.Min.Y, bounds.Max.Z - bounds.Min.Z));
            var zoom = size > 0.0001f ? 500.0f / size : 220.0f;
            viewport.UpdateCamera(NetViewportCamera.CreateArchiveAudit(
                center,
                bounds,
                yawDegrees * MathF.PI / 180.0f,
                Math.Clamp(pitchDegrees, -89.0f, 89.0f) * MathF.PI / 180.0f,
                zoom,
                Math.Max(1, _form.ClientSize.Width),
                Math.Max(1, _form.ClientSize.Height)));
            viewport.Invalidate();
        }

        public bool TryCapture(
            string outputPath,
            int width,
            int height,
            out string sha256,
            out string error,
            out D3D11RenderedCameraEvidence renderedCamera) =>
            RequireViewport().TryCaptureReplacementPng(
                outputPath,
                width,
                height,
                out sha256,
                out error,
                out renderedCamera);

        public bool TryApplyMaterialState(
            IReadOnlyList<int> affectedSubmeshes,
            out string error) =>
            RequireViewport().TryApplyMaterialState(affectedSubmeshes, out error);

        public MaterialStabilityEvidence MaterialStabilitySnapshot()
        {
            var viewport = RequireViewport();
            return new MaterialStabilityEvidence(
                viewport.GeometryUploadCount,
                viewport.RenderSurfaceIdentity,
                viewport.DeviceResetAttemptCount,
                viewport.DeviceResetCount);
        }

        public Dictionary<string, object?> StatusPayload()
        {
            var viewport = RequireViewport();
            var nativeWindowsRemainedHidden = _form.IsHandleCreated
                && viewport.IsHandleCreated
                && !_form.Visible
                && !viewport.Visible
                && !IsWindowVisible(_form.Handle)
                && !IsWindowVisible(viewport.Handle)
                && !_form.ShowInTaskbar;
            return new Dictionary<string, object?>
            {
                ["backend"] = viewport.BackendName,
                ["initialized"] = viewport.IsInitialized,
                ["capture_mode"] = "hidden_hwnd_no_show",
                ["native_windows_remained_hidden"] = nativeWindowsRemainedHidden,
                ["host_hwnd_created"] = _form.IsHandleCreated,
                ["viewport_hwnd_created"] = viewport.IsHandleCreated,
                ["host_visible"] = _form.Visible,
                ["viewport_visible"] = viewport.Visible,
                ["host_is_window_visible"] = _form.IsHandleCreated && IsWindowVisible(_form.Handle),
                ["viewport_is_window_visible"] = viewport.IsHandleCreated && IsWindowVisible(viewport.Handle),
                ["show_called"] = false,
                ["show_in_taskbar"] = _form.ShowInTaskbar,
                ["resident_scene_load_count"] = viewport.ResidentSceneLoadCount,
                ["viewport_create_count"] = _viewportCreateCount,
                ["device_initialization_count"] = _deviceInitializationCount,
                ["device_reset_attempt_count"] = viewport.DeviceResetAttemptCount,
                ["device_reset_count"] = viewport.DeviceResetCount,
                ["last_error"] = viewport.LastError,
                ["presentation"] = viewport.PresentationEvidencePayload(),
                ["resources"] = viewport.ResourceMetricsPayload(),
            };
        }

        public Dictionary<string, object?> SummaryPayload() => StatusPayload();

        private D3D11MaterialViewport RequireViewport() =>
            _viewport ?? throw new InvalidOperationException("Resident Vortice renderer has not loaded a scene.");

        public void Dispose()
        {
            _form.Hide();
            _form.Dispose();
            _viewport = null;
            _activeTextures?.Dispose();
            _activeTextures = null;
        }

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool IsWindowVisible(IntPtr hWnd);
    }

    private sealed record MaterialStabilityEvidence(
        long GeometryUploadCount,
        int RenderSurfaceIdentity,
        long DeviceResetAttemptCount,
        long DeviceResetCount);

    private static IEnumerable<JsonElement> AssetViews(JsonElement asset)
    {
        if (!asset.TryGetProperty("views", out var views) || views.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidDataException("Visual-audit asset has no views array.");
        }
        var count = views.GetArrayLength();
        if (count <= 0 || count > MaximumViewsPerAsset)
        {
            throw new InvalidDataException($"Visual-audit view count must be between 1 and {MaximumViewsPerAsset}.");
        }
        return views.EnumerateArray().ToArray();
    }

    private static IEnumerable<JsonElement> AssetMaterialRegions(JsonElement asset)
    {
        if (!asset.TryGetProperty("material_regions", out var regions))
        {
            return Array.Empty<JsonElement>();
        }
        if (regions.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidDataException("Visual-audit material_regions must be an array.");
        }
        var count = regions.GetArrayLength();
        if (count > MaximumMaterialRegionsPerAsset)
        {
            throw new InvalidDataException(
                $"Visual-audit material region count cannot exceed {MaximumMaterialRegionsPerAsset}.");
        }
        return regions.EnumerateArray().ToArray();
    }

    private static IEnumerable<JsonElement> RegionAngles(JsonElement region)
    {
        if (!region.TryGetProperty("capture_angles", out var angles)
            || angles.ValueKind != JsonValueKind.Array
            || angles.GetArrayLength() != 2)
        {
            throw new InvalidDataException("Visual-audit material region requires exactly front and oblique angles.");
        }
        return angles.EnumerateArray().ToArray();
    }

    private static IEnumerable<string> RegionDebugModes(JsonElement region)
    {
        if (!region.TryGetProperty("debug_modes", out var modes) || modes.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidDataException("Visual-audit material region requires debug_modes.");
        }
        var values = modes.EnumerateArray().Select(value => value.GetString()?.Trim() ?? string.Empty).ToArray();
        var required = new[] { "base", "normal", "roughness", "metallic", "specular", "layer_mask" };
        if (!values.SequenceEqual(required, StringComparer.Ordinal))
        {
            throw new InvalidDataException(
                "Visual-audit material region debug_modes must be base, normal, roughness, metallic, specular, layer_mask.");
        }
        return values;
    }

    private static int MaterialDebugModeForName(string value) => value.Trim().ToLowerInvariant() switch
    {
        "final" => 0,
        "base" => 1,
        "normal" => 2,
        "roughness" => 3,
        "metallic" => 4,
        "specular" => 6,
        "layer_mask" => 12,
        _ => throw new InvalidDataException($"Unsupported material-region debug mode: {value}"),
    };

    private static string OwnedOutputDirectory(string outputRoot, string assetId)
    {
        var safeId = SafeName(assetId);
        var candidate = Path.GetFullPath(Path.Combine(outputRoot, safeId));
        var rootPrefix = Path.GetFullPath(outputRoot).TrimEnd(Path.DirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        if (!candidate.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Visual-audit asset output escaped its owned root.");
        }
        return candidate;
    }

    private static void RequirePackageFile(string packageDir, string path)
    {
        var rootPrefix = Path.GetFullPath(packageDir).TrimEnd(Path.DirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        var fullPath = Path.GetFullPath(path);
        if (!fullPath.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase) || !File.Exists(fullPath))
        {
            throw new FileNotFoundException("Visual-audit package input is missing or outside its package.", fullPath);
        }
    }

    private static string SafeName(string value)
    {
        var normalized = new string(value.Trim().Select(character =>
            char.IsLetterOrDigit(character) || character is '-' or '_' ? character : '-').ToArray());
        normalized = normalized.Trim('-');
        if (normalized.Length == 0 || normalized.Length > 120)
        {
            throw new InvalidDataException("Visual-audit identifier is empty or too long.");
        }
        return normalized;
    }

    private static string JsonRequiredString(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String)
        {
            throw new InvalidDataException($"Visual-audit field {name} must be a string.");
        }
        var text = value.GetString()?.Trim() ?? string.Empty;
        if (text.Length == 0)
        {
            throw new InvalidDataException($"Visual-audit field {name} is empty.");
        }
        return text;
    }

    private static int JsonInt(JsonElement root, string name, int fallback) =>
        root.TryGetProperty(name, out var value) && value.TryGetInt32(out var parsed) ? parsed : fallback;

    private static float JsonFloat(JsonElement root, string name, float fallback) =>
        root.TryGetProperty(name, out var value) && value.TryGetSingle(out var parsed) ? parsed : fallback;

    private static string RequiredArgument(string[] args, string name) =>
        ArgumentValue(args, name) ?? throw new ArgumentException($"{name} requires a path.");

    private static string? ArgumentValue(string[] args, string name)
    {
        var index = Array.FindIndex(args, value => string.Equals(value, name, StringComparison.OrdinalIgnoreCase));
        return index >= 0 && index + 1 < args.Length ? Path.GetFullPath(args[index + 1]) : null;
    }

    private static void AtomicWriteJson(string path, object payload)
    {
        var fullPath = Path.GetFullPath(path);
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath)
            ?? throw new InvalidOperationException("Visual-audit report has no parent directory."));
        var temporaryPath = fullPath + $".{Guid.NewGuid():N}.tmp";
        try
        {
            File.WriteAllText(
                temporaryPath,
                JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
            File.Move(temporaryPath, fullPath, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporaryPath))
            {
                File.Delete(temporaryPath);
            }
        }
    }
}
