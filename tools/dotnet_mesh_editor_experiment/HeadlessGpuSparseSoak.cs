using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Numerics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static partial class HeadlessGpuSparseSoak
{
    private const string Schema = "cdmw_dotnet_gpu_sparse_soak_v1";
    private const double FrameBudgetMs = 16.7;
    private const double MaximumWorkingSetGrowthRatio = 0.10;

    public static bool IsRequested(string[] args)
    {
        return args.Any(arg => string.Equals(arg, "--headless-gpu-sparse-soak", StringComparison.OrdinalIgnoreCase));
    }

    public static int Run(string[] args)
    {
        var reportPath = HeadlessGpuSparseSoakOptions.ReportPathFrom(args);
        try
        {
            var options = HeadlessGpuSparseSoakOptions.Parse(args);
            var (report, ok) = Execute(options);
            WriteReport(options.ReportPath, report);
            return ok ? 0 : 2;
        }
        catch (Exception ex)
        {
            var report = new Dictionary<string, object?>
            {
                ["schema"] = Schema,
                ["ok"] = false,
                ["generated_at_utc"] = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture),
                ["error"] = new Dictionary<string, object?>
                {
                    ["type"] = ex.GetType().FullName,
                    ["message"] = ex.Message,
                },
            };
            WriteReport(reportPath, report);
            return 1;
        }
    }

    private static (Dictionary<string, object?> Report, bool Ok) Execute(HeadlessGpuSparseSoakOptions options)
    {
        var originalVsync = Environment.GetEnvironmentVariable("CDMW_MESH_DOTNET_D3D11_NO_VSYNC");
        Environment.SetEnvironmentVariable("CDMW_MESH_DOTNET_D3D11_NO_VSYNC", "1");
        try
        {
            return ExecuteWithNoVsync(options);
        }
        finally
        {
            Environment.SetEnvironmentVariable("CDMW_MESH_DOTNET_D3D11_NO_VSYNC", originalVsync);
        }
    }

    private static (Dictionary<string, object?> Report, bool Ok) ExecuteWithNoVsync(HeadlessGpuSparseSoakOptions options)
    {
        var process = Process.GetCurrentProcess();
        var workingSetBeforeDocument = WorkingSet(process);
        var document = BuildSyntheticDocument(options.VertexCount);
        var submesh = document.Submeshes[0];
        var renderVertexCount = submesh.Faces.Count * 3;
        var materials = NetMaterialSet.Empty;
        using var textures = NetTextureSet.Load(materials);
        using var host = CreateHiddenHost();
        using var viewport = new D3D11MaterialViewport(document, materials, textures, NetSceneState.Load(string.Empty, document.Submeshes.Count))
        {
            Dock = DockStyle.Fill,
        };
        host.Controls.Add(viewport);
        host.CreateControl();
        _ = host.Handle;
        viewport.CreateControl();
        _ = viewport.Handle;
        if (!viewport.TryInitialize(out var initializeError))
        {
            throw new InvalidOperationException($"Hidden D3D11 viewport initialization failed: {initializeError}");
        }
        var camera = CameraFor(document, host.ClientSize);
        viewport.UpdateCamera(camera);
        ConfigureSmokeViewport(viewport, camera, host.ClientSize, options.Smoke);
        if (!viewport.TryRunHeadlessFrame(out var firstFrameMs, out _, out var firstFrameError))
        {
            throw new InvalidOperationException($"Hidden D3D11 first frame failed: {firstFrameError}");
        }
        var xrayOverlayProof = ApplyXRayOverlayProof(
            viewport,
            document,
            camera,
            host.ClientSize,
            options.Smoke);
        var untexturedReadabilityProof = D3D11UntexturedReadabilityProof.Run();
        var texturedMetalReadabilityProof = D3D11TexturedMetalReadabilityProof.Run();

        var dirtyIndex = new[] { 0 };
        var changed = new Dictionary<int, MeshVertexChannelChanges>
        {
            [0] = new MeshVertexChannelChanges(dirtyIndex, dirtyIndex, dirtyIndex),
        };
        for (var warmup = 0; warmup < options.WarmupUpdates; warmup++)
        {
            _ = ApplySparseUpdate(viewport, submesh, renderVertexCount, warmup, dirtyIndex, changed);
        }
        var partialTopologyProof = ApplyPartialTopologyProof(viewport, submesh);
        ForceCollection();
        var resourcesBefore = viewport.ResourceMetricsPayload();
        var workingSetBaseline = WorkingSet(process);
        var peakWorkingSet = workingSetBaseline;
        var durations = new double[options.UpdateCount];
        var cadence = Stopwatch.StartNew();
        for (var update = 0; update < options.UpdateCount; update++)
        {
            durations[update] = ApplySparseUpdate(
                viewport,
                submesh,
                renderVertexCount,
                options.WarmupUpdates + update,
                dirtyIndex,
                changed);
            if ((update & 15) == 0)
            {
                peakWorkingSet = Math.Max(peakWorkingSet, WorkingSet(process));
            }
            if (options.EnforceCadence)
            {
                WaitForCadence(cadence, update + 1, options.TargetUpdatesPerSecond);
            }
        }
        cadence.Stop();
        var materialParameterProof = ApplyMaterialParameterProof(materials, viewport);
        if (!viewport.TryRunHeadlessFrame(out var finalFrameMs, out _, out var finalFrameError))
        {
            throw new InvalidOperationException($"Hidden D3D11 final sparse frame failed: {finalFrameError}");
        }
        var frameDurations = new[] { firstFrameMs, finalFrameMs };
        ForceCollection();
        var workingSetFinal = WorkingSet(process);
        peakWorkingSet = Math.Max(peakWorkingSet, workingSetFinal);
        var resourcesAfter = viewport.ResourceMetricsPayload();
        var boundsProof = SparseBoundsProof();
        var placementProof = ResidentPlacementProof();
        var presentationModeProof = PresentationModeProof();
        var cameraZoomProof = CameraZoomProof();
        var fitRelativeOverlayProof = FitRelativeOverlayProof();
        var topologyPacketProof = ResidentTopologyPacketProof();
        var gates = EvaluateGates(options, durations, cadence.Elapsed.TotalSeconds, workingSetBaseline, workingSetFinal, resourcesBefore, resourcesAfter, boundsProof);
        gates["production_d3d11_backend"] = viewport.IsInitialized
            && string.Equals(viewport.BackendName, "d3d11_vortice_shader", StringComparison.Ordinal);
        gates["untextured_faces_readable_front_back_and_oblique"] =
            untexturedReadabilityProof.GetValueOrDefault("ok") is true;
        gates["textured_metal_readable_front_back_and_oblique"] =
            texturedMetalReadabilityProof.GetValueOrDefault("ok") is true;
        gates["native_windows_remained_hidden"] = host.IsHandleCreated
            && viewport.IsHandleCreated
            && !host.Visible
            && !IsWindowVisible(host.Handle)
            && !IsWindowVisible(viewport.Handle)
            && !host.ShowInTaskbar;
        gates["synthetic_mesh_matches_profile"] = document.Submeshes.Sum(item => item.Vertices.Count) == options.VertexCount
            && renderVertexCount > 0;
        gates["full_scale_parameters_or_explicit_smoke"] = options.Smoke
            || (options.VertexCount >= 1_000_000 && options.UpdateCount >= 1_000 && options.EnforceCadence);
        gates["material_parameter_state_exact"] = (bool)materialParameterProof["state_exact"]!;
        gates["material_parameter_no_resource_churn"] = (bool)materialParameterProof["no_resource_churn"]!;
        gates["material_parameter_apply_counted"] = (bool)materialParameterProof["apply_counted"]!;
        gates["partial_topology_rebuild_only"] = (bool)partialTopologyProof["ok"]!;
        gates["resident_topology_add_remove_packets"] = (bool)topologyPacketProof["ok"]!;
        gates["resident_gizmo_moves_only_editable_role"] = (bool)placementProof["ok"]!;
        gates["all_presentation_modes_have_exact_role_visibility_and_pane_layout"] =
            (bool)presentationModeProof["ok"]!;
        gates["placement_and_mesh_edit_wheel_zoom_reversible"] =
            (bool)cameraZoomProof["ok"]!;
        gates["archive_browser_zoom_step_parity"] =
            cameraZoomProof.GetValueOrDefault("archive_browser_step_table_exact") is true;
        gates["wheel_zoom_panned_anchor_stable"] =
            cameraZoomProof.GetValueOrDefault("panned_anchor_proof") is Dictionary<string, object?> pannedAnchorProof
            && pannedAnchorProof.GetValueOrDefault("ok") is true;
        gates["side_by_side_wheel_zoom_target_isolated"] =
            cameraZoomProof.GetValueOrDefault("pane_isolation_proof") is Dictionary<string, object?> paneIsolationProof
            && paneIsolationProof.GetValueOrDefault("ok") is true;
        gates["programmatic_zoom_clamped_fit_relative"] =
            cameraZoomProof.GetValueOrDefault("programmatic_clamp_exact") is true;
        gates["fit_relative_vertex_markers_and_wire"] =
            fitRelativeOverlayProof.GetValueOrDefault("ok") is true;
        gates["xray_overlay_draws_wire_and_vertices_without_depth"] =
            xrayOverlayProof.GetValueOrDefault("ok") is true;
        var ok = gates.Values.All(value => value);
        var report = BuildReport(
            options,
            document,
            renderVertexCount,
            durations,
            frameDurations,
            cadence.Elapsed.TotalSeconds,
            workingSetBeforeDocument,
            workingSetBaseline,
            workingSetFinal,
            peakWorkingSet,
            resourcesBefore,
            resourcesAfter,
            boundsProof,
            gates,
            ok,
            host,
            viewport);
        report["material_parameter_proof"] = materialParameterProof;
        report["partial_topology_proof"] = partialTopologyProof;
        report["resident_topology_packet_proof"] = topologyPacketProof;
        report["resident_placement_proof"] = placementProof;
        report["presentation_mode_proof"] = presentationModeProof;
        report["camera_zoom_proof"] = cameraZoomProof;
        report["fit_relative_overlay_proof"] = fitRelativeOverlayProof;
        report["xray_overlay_proof"] = xrayOverlayProof;
        report["untextured_readability_proof"] = untexturedReadabilityProof;
        report["textured_metal_readability_proof"] = texturedMetalReadabilityProof;
        return (report, ok);
    }

    private static void ConfigureSmokeViewport(
        D3D11MaterialViewport viewport,
        NetViewportCamera camera,
        Size clientSize,
        bool smoke)
    {
        if (!smoke)
        {
            return;
        }

        viewport.UpdateRenderPanes(new[]
        {
            new D3D11RenderPane(
                new Rectangle(Point.Empty, clientSize),
                camera,
                "editable",
                "vertices",
                0,
                false,
                true,
                false,
                false,
                true),
        });
        viewport.UpdateOverlay(
            NetEdgeTopology.Empty,
            new HashSet<int>(),
            -1,
            null,
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<int>>(),
            new HashSet<int>(),
            -1,
            showWire: false,
            showVertices: true,
            showXRay: false,
            brushCursor: null,
            brushRadius: 24.0f);
    }

    private static Dictionary<string, object?> ApplyXRayOverlayProof(
        D3D11MaterialViewport viewport,
        ObjDocument document,
        NetViewportCamera camera,
        Size clientSize,
        bool smoke)
    {
        if (!smoke)
        {
            return new Dictionary<string, object?>
            {
                ["ok"] = true,
                ["exercised"] = false,
                ["reason"] = "The dedicated X-Ray draw proof runs in smoke mode.",
            };
        }

        var configuredColors = new MeshOverlayColors(
            System.Drawing.Color.FromArgb(12, 34, 56),
            System.Drawing.Color.FromArgb(78, 90, 123));
        viewport.SetOverlayColors(configuredColors);
        var before = viewport.ResourceMetricsPayload();
        viewport.UpdateRenderPanes(new[]
        {
            new D3D11RenderPane(
                new Rectangle(Point.Empty, clientSize),
                camera,
                "editable",
                "wire_vertices",
                0,
                false,
                true,
                false,
                true,
                true),
        });
        viewport.UpdateOverlay(
            NetEdgeTopology.Build(document),
            new HashSet<int>(),
            -1,
            null,
            new Dictionary<int, HashSet<int>>(),
            new Dictionary<int, HashSet<int>>(),
            new HashSet<int>(),
            -1,
            showWire: true,
            showVertices: true,
            showXRay: true,
            brushCursor: null,
            brushRadius: 24.0f);
        if (!viewport.TryRunHeadlessFrame(out var frameMs, out _, out var error))
        {
            throw new InvalidOperationException($"Hidden D3D11 X-Ray overlay proof failed: {error}");
        }
        var after = viewport.ResourceMetricsPayload();
        var normalColorsRetained =
            string.Equals(after.GetValueOrDefault("wire_overlay_color") as string, "#0C2238", StringComparison.Ordinal)
            && string.Equals(after.GetValueOrDefault("vertex_overlay_color") as string, "#4E5A7B", StringComparison.Ordinal);
        var automaticPaletteActive =
            after.GetValueOrDefault("xray_overlay_active") is true
            && string.Equals(after.GetValueOrDefault("xray_wire_overlay_color") as string, "#F5F8FC", StringComparison.Ordinal)
            && string.Equals(after.GetValueOrDefault("xray_vertex_overlay_color") as string, "#FF58D6", StringComparison.Ordinal);
        var wireNoDepthAdvanced =
            Metric(after, "xray_wire_no_depth_draws") > Metric(before, "xray_wire_no_depth_draws");
        var vertexNoDepthAdvanced =
            Metric(after, "xray_vertex_no_depth_passes") > Metric(before, "xray_vertex_no_depth_passes");

        viewport.SetOverlayColors(MeshOverlayColors.Default);
        ConfigureSmokeViewport(viewport, camera, clientSize, smoke: true);
        if (!viewport.TryRunHeadlessFrame(out _, out _, out var restoreError))
        {
            throw new InvalidOperationException($"Hidden D3D11 X-Ray overlay proof restore failed: {restoreError}");
        }

        return new Dictionary<string, object?>
        {
            ["ok"] = normalColorsRetained
                && automaticPaletteActive
                && wireNoDepthAdvanced
                && vertexNoDepthAdvanced,
            ["exercised"] = true,
            ["frame_ms"] = frameMs,
            ["normal_colors_retained"] = normalColorsRetained,
            ["automatic_palette_active"] = automaticPaletteActive,
            ["wire_no_depth_draw_advanced"] = wireNoDepthAdvanced,
            ["vertex_no_depth_pass_advanced"] = vertexNoDepthAdvanced,
            ["configured_wire_color"] = after.GetValueOrDefault("wire_overlay_color"),
            ["configured_vertex_color"] = after.GetValueOrDefault("vertex_overlay_color"),
            ["xray_wire_color"] = after.GetValueOrDefault("xray_wire_overlay_color"),
            ["xray_vertex_color"] = after.GetValueOrDefault("xray_vertex_overlay_color"),
            ["wire_no_depth_draws_before"] = Metric(before, "xray_wire_no_depth_draws"),
            ["wire_no_depth_draws_after"] = Metric(after, "xray_wire_no_depth_draws"),
            ["vertex_no_depth_passes_before"] = Metric(before, "xray_vertex_no_depth_passes"),
            ["vertex_no_depth_passes_after"] = Metric(after, "xray_vertex_no_depth_passes"),
        };
    }

    private static Dictionary<string, object?> ApplyPartialTopologyProof(
        D3D11MaterialViewport viewport,
        ObjSubmesh submesh)
    {
        if (submesh.Faces.Count == 0)
        {
            throw new InvalidOperationException("Hidden D3D11 partial topology proof requires one face.");
        }
        var before = viewport.ResourceMetricsPayload();
        var face = submesh.Faces[0];
        submesh.Faces[0] = new ObjFace(new[] { face.Corners[1], face.Corners[2], face.Corners[0] });
        viewport.RefreshTopologyGeometry(new[] { 0 }, new Dictionary<int, int> { [0] = 0 }, replaceAll: false);
        if (!viewport.TryApplyHeadlessPendingUpdate(out var error))
        {
            throw new InvalidOperationException($"Hidden D3D11 partial topology update failed: {error}");
        }
        var after = viewport.ResourceMetricsPayload();
        var ok = Metric(after, "partial_topology_rebuilds") == Metric(before, "partial_topology_rebuilds") + 1
            && Metric(after, "topology_batches_rebuilt") == Metric(before, "topology_batches_rebuilt") + 1
            && Metric(after, "full_geometry_rebuilds") == Metric(before, "full_geometry_rebuilds")
            && Metric(after, "vertex_buffer_creates") == Metric(before, "vertex_buffer_creates") + 1
            && Metric(after, "index_buffer_creates") == Metric(before, "index_buffer_creates") + 1;
        return new Dictionary<string, object?>
        {
            ["ok"] = ok,
            ["resources_before"] = before,
            ["resources_after"] = after,
        };
    }

    private static Dictionary<string, object?> ResidentTopologyPacketProof()
    {
        var topologyMaterials = NetMaterialSet.Empty;
        using var parameterDocument = JsonDocument.Parse("""
            {
              "schema": "cdmw_mesh_material_parameters_v1",
              "version": 1,
              "session_id": "resident-topology-proof",
              "edit_revision": 1,
              "parameter_generation": 1,
              "groups": [
                {"source_submesh_indices":[0],"editor_role":"replacement_preview","tint_color":[1,1,1]},
                {"source_submesh_indices":[1],"editor_role":"replacement_preview","tint_color":[1,0,0]},
                {"source_submesh_indices":[2],"editor_role":"replacement_preview","tint_color":[0,1,0]}
              ]
            }
            """);
        topologyMaterials.ApplyParameterUpdate(NetMaterialSet.ParseParameterUpdate(parameterDocument.RootElement));
        topologyMaterials.RemapTopologyState(new Dictionary<int, int> { [3] = 0 }, 4);
        topologyMaterials.RemapTopologyState(new Dictionary<int, int> { [1] = 2, [2] = 3 }, 3);
        var topologyMaterialLineageRemapped =
            topologyMaterials.ParametersForSubmesh(1).TintColor == new System.Numerics.Vector3(0, 1, 0)
            && topologyMaterials.ParametersForSubmesh(2).TintColor == System.Numerics.Vector3.One
            && topologyMaterials.ParametersForSubmesh(3).IsEmpty;

        var document = new ObjDocument();
        document.Submeshes.Add(new ObjSubmesh("old_a", 0, 0, 0));
        document.Submeshes.Add(new ObjSubmesh("old_b", 0, 0, 0));
        using var replaceDocument = JsonDocument.Parse("""
            {
              "replace_all_triangles": true,
              "final_submesh_count": 1,
              "triangle_groups": [{
                "source_submesh_index": 0,
                "material_source_submesh_index": 1,
                "material_name": "survivor",
                "positions": [0,0,0, 1,0,0, 0,1,0],
                "normals": [0,0,1, 0,0,1, 0,0,1],
                "uvs": [0,0, 1,0, 0,1],
                "indices": [0,1,2]
              }]
            }
            """);
        var replaceRoot = replaceDocument.RootElement;
        var replaced = ExperimentForm.TryApplyPreviewTriangleGroups(
            document,
            replaceRoot,
            replaceRoot.GetProperty("triangle_groups"),
            out var replaceChanges,
            out _,
            out var replaceMaterials,
            out var replaceAll);
        using var orderedVertexDocument = JsonDocument.Parse("""{"vertex_groups":[{"source_submesh_index":1,"positions":[0,0,0,-1,0,0,0,-1,0]}]}""");
        var orderedVertexGroups = orderedVertexDocument.RootElement.GetProperty("vertex_groups");
        var orderedVertexDecoded = ExperimentForm.TryParsePreviewVertexGroups(
            orderedVertexGroups,
            out var orderedVertexPlan);
        var orderedVertexRejectedBeforeTopology = orderedVertexDecoded
            && !ExperimentForm.ValidatePreviewVertexGroups(document, orderedVertexPlan);
        using var addDocument = JsonDocument.Parse("""
            {
              "triangle_groups": [{
                "source_submesh_index": 1,
                "material_source_submesh_index": 0,
                "material_name": "duplicate",
                "positions": [0,0,0, -1,0,0, 0,-1,0],
                "normals": [0,0,1, 0,0,1, 0,0,1],
                "uvs": [0,0, 1,0, 0,1],
                "indices": [0,1,2]
              }]
            }
            """);
        var addRoot = addDocument.RootElement;
        var added = ExperimentForm.TryApplyPreviewTriangleGroups(
            document,
            addRoot,
            addRoot.GetProperty("triangle_groups"),
            out var addChanges,
            out _,
            out var addMaterials,
            out var addReplaceAll);
        var orderedVertexAcceptedAfterTopology = orderedVertexDecoded
            && ExperimentForm.ValidatePreviewVertexGroups(document, orderedVertexPlan);
        using var shrinkDocument = JsonDocument.Parse("""{"final_submesh_count":1,"triangle_source_submesh_indices":[1],"triangle_groups":[{"source_submesh_index":1,"positions":[],"indices":[]}]}""");
        var shrinkRoot = shrinkDocument.RootElement;
        var shrunk = ExperimentForm.TryApplyPreviewTriangleGroups(document, shrinkRoot, shrinkRoot.GetProperty("triangle_groups"), out var shrinkChanges, out var shrinkAffected, out _, out var shrinkReplaceAll);
        using var incompleteDocument = JsonDocument.Parse("""{"replace_all_triangles":true,"final_submesh_count":2,"triangle_groups":[]}""");
        var incompleteRoot = incompleteDocument.RootElement;
        var incompleteRejected = !ExperimentForm.TryApplyPreviewTriangleGroups(
            document, incompleteRoot, incompleteRoot.GetProperty("triangle_groups"), out _, out _, out _, out _);
        var missingChannels = new ObjSubmesh("missing_channels", 0, 0, 0);
        missingChannels.Vertices.AddRange(new[] { new Vec3(0, 0, 0), new Vec3(1, 0, 0), new Vec3(0, 1, 0) });
        missingChannels.Faces.Add(new ObjFace(new[] { new ObjCorner(0, -1, -1), new ObjCorner(1, -1, -1), new ObjCorner(2, -1, -1) }));
        ExperimentForm.EnsureVertexAlignedNormals(missingChannels);
        ExperimentForm.EnsureVertexAlignedUvs(missingChannels);
        var missingChannelsInitialized = missingChannels.Normals.Count == 3 && missingChannels.Uvs.Count == 3
            && missingChannels.Faces[0].Corners.All(corner => corner.NormalIndex == corner.VertexIndex && corner.UvIndex == corner.VertexIndex);
        var misaligned = new ObjSubmesh("misaligned", 0, 0, 0);
        misaligned.Vertices.AddRange(missingChannels.Vertices);
        misaligned.Normals.AddRange(new[] { new Vec3(1, 0, 0), new Vec3(0, 1, 0), new Vec3(0, 0, 1) });
        misaligned.Uvs.AddRange(new[] { new Vec2(0, 0), new Vec2(1, 0), new Vec2(0, 1) });
        misaligned.Faces.Add(new ObjFace(new[] { new ObjCorner(0, 2, 2), new ObjCorner(1, 0, 0), new ObjCorner(2, 1, 1) }));
        ExperimentForm.EnsureVertexAlignedNormals(misaligned);
        ExperimentForm.EnsureVertexAlignedUvs(misaligned);
        var equalCountChannelsRemapped = misaligned.Faces[0].Corners.All(corner => corner.NormalIndex == corner.VertexIndex && corner.UvIndex == corner.VertexIndex)
            && misaligned.Normals[0] == new Vec3(0, 0, 1) && misaligned.Uvs[0] == new Vec2(0, 1);
        using var malformedVertexDocument = JsonDocument.Parse("""{"vertex_groups":[{"source_submesh_index":0,"source_vertex_indices":[0],"positions":[0,0,0],"normals":[0,1]}]}""");
        var malformedVertexRejected = !ExperimentForm.TryParsePreviewVertexGroups(
            document, malformedVertexDocument.RootElement.GetProperty("vertex_groups"), out _);
        var combinedSceneDocument = new ObjDocument();
        combinedSceneDocument.Submeshes.Add(new ObjSubmesh("editable_a", 0, 0, 0));
        combinedSceneDocument.Submeshes.Add(new ObjSubmesh("editable_b", 0, 0, 0));
        combinedSceneDocument.Submeshes.Add(new ObjSubmesh("reference_a", 0, 0, 0));
        combinedSceneDocument.Submeshes.Add(new ObjSubmesh("reference_b", 0, 0, 0));
        using var combinedShrinkDocument = JsonDocument.Parse("""{"final_submesh_count":1,"triangle_source_submesh_indices":[0,1],"triangle_groups":[{"source_submesh_index":0,"positions":[],"indices":[]}]}""");
        var combinedShrinkRoot = combinedShrinkDocument.RootElement;
        var combinedShrinkApplied = ExperimentForm.TryApplyPreviewTriangleGroups(
            combinedSceneDocument,
            combinedShrinkRoot,
            combinedShrinkRoot.GetProperty("triangle_groups"),
            2,
            out _,
            out _,
            out var combinedShrinkMaterials,
            out var combinedShrinkSources,
            out _);
        var combinedReferencesPreservedAfterDelete = combinedShrinkApplied
            && combinedSceneDocument.Submeshes.Select(submesh => submesh.Name).SequenceEqual(
                new[] { "editable_b", "reference_a", "reference_b" })
            && combinedShrinkMaterials.GetValueOrDefault(0) == 1
            && combinedShrinkMaterials.GetValueOrDefault(1) == 2
            && combinedShrinkMaterials.GetValueOrDefault(2) == 3
            && combinedShrinkSources.GetValueOrDefault(0, -1) == 1
            && combinedShrinkSources.GetValueOrDefault(1, -1) == 2
            && combinedShrinkSources.GetValueOrDefault(2, -1) == 3;
        using var combinedAddDocument = JsonDocument.Parse("""
            {
              "triangle_groups": [{
                "source_submesh_index": 1,
                "material_source_submesh_index": 0,
                "part_name": "editable_duplicate",
                "positions": [0,0,0, 1,0,0, 0,1,0],
                "indices": [0,1,2]
              }]
            }
            """);
        var combinedAddRoot = combinedAddDocument.RootElement;
        var combinedAddApplied = ExperimentForm.TryApplyPreviewTriangleGroups(
            combinedSceneDocument,
            combinedAddRoot,
            combinedAddRoot.GetProperty("triangle_groups"),
            1,
            out _,
            out _,
            out var combinedAddMaterials,
            out var combinedAddSources,
            out _);
        var combinedReferencesPreservedAfterAdd = combinedAddApplied
            && combinedSceneDocument.Submeshes.Select(submesh => submesh.Name).SequenceEqual(
                new[] { "editable_b", "editable_duplicate", "reference_a", "reference_b" })
            && combinedAddMaterials.GetValueOrDefault(1) == 0
            && combinedAddMaterials.GetValueOrDefault(2) == 1
            && combinedAddMaterials.GetValueOrDefault(3) == 2
            && combinedAddSources.GetValueOrDefault(0, -1) == 0
            && combinedAddSources.GetValueOrDefault(1, 0) == -1
            && combinedAddSources.GetValueOrDefault(2, -1) == 1
            && combinedAddSources.GetValueOrDefault(3, -1) == 2;
        var ok = replaced && replaceAll && replaceChanges == 1
            && added && !addReplaceAll && addChanges == 1
            && shrunk && !shrinkReplaceAll && shrinkChanges == 1 && shrinkAffected.SequenceEqual(new[] { 1 })
            && incompleteRejected && missingChannelsInitialized && equalCountChannelsRemapped && malformedVertexRejected
            && orderedVertexRejectedBeforeTopology && orderedVertexAcceptedAfterTopology
            && topologyMaterialLineageRemapped
            && combinedReferencesPreservedAfterDelete && combinedReferencesPreservedAfterAdd
            && document.Submeshes.Count == 1
            && document.Submeshes[0].Material == "survivor"
            && replaceMaterials.GetValueOrDefault(0) == 1
            && addMaterials.GetValueOrDefault(1) == 0;
        return new Dictionary<string, object?>
        {
            ["ok"] = ok,
            ["replace_all_applied"] = replaced,
            ["partial_add_applied"] = added,
            ["partial_tail_shrink_applied"] = shrunk,
            ["incomplete_replace_all_rejected"] = incompleteRejected,
            ["missing_vertex_channels_initialized"] = missingChannelsInitialized,
            ["equal_count_channels_remapped"] = equalCountChannelsRemapped,
            ["malformed_vertex_channel_rejected"] = malformedVertexRejected,
            ["combined_scene_references_preserved_after_delete"] = combinedReferencesPreservedAfterDelete,
            ["combined_scene_references_preserved_after_add"] = combinedReferencesPreservedAfterAdd,
            ["ordered_vertex_plan_revalidated_after_topology"] = orderedVertexRejectedBeforeTopology
                && orderedVertexAcceptedAfterTopology,
            ["material_parameter_lineage_remapped"] = topologyMaterialLineageRemapped,
            ["final_submesh_count"] = document.Submeshes.Count,
            ["survivor_material_source"] = replaceMaterials.GetValueOrDefault(0),
            ["added_material_source"] = addMaterials.GetValueOrDefault(1),
        };
    }

    private static Dictionary<string, object?> ApplyMaterialParameterProof(
        NetMaterialSet materials,
        D3D11MaterialViewport viewport)
    {
        var before = viewport.ResourceMetricsPayload();
        using var document = JsonDocument.Parse("""
            {
              "schema": "cdmw_mesh_material_parameters_v1",
              "version": 1,
              "session_id": "headless-gpu-soak",
              "edit_revision": 7,
              "parameter_generation": 1,
              "groups": [{
                "source_submesh_indices": [],
                "editor_role": "replacement_preview",
                "texture_brightness": 1.25,
                "post_contrast_brightness": 1.05,
                "base_color_lift": 0,
                "value_max": 222,
                "auto_balance": 100,
                "shadow_lift": 25,
                "metalness": 0.0,
                "specular": null,
                "roughness_inverted": true,
                "metalness_inverted": false,
                "roughness_scale": 0.0,
                "roughness_min": 24,
                "roughness_max": 230,
                "metalness_scale": 1.5,
                "metalness_min": 0,
                "metalness_max": 255,
                "roughness_blend_target": 0.25,
                "roughness_blend_strength": 0.5,
                "metalness_blend_target": 0.0,
                "metalness_blend_strength": null,
                "tint_color": [0.8, 0.9, 1.0],
                "material_role": "glow"
              }]
            }
            """);
        var update = NetMaterialSet.ParseParameterUpdate(document.RootElement).ExpandAllSubmeshes(new[] { 0 });
        materials.ApplyParameterUpdate(update);
        if (!viewport.TryApplyMaterialParameters(update.AffectedSubmeshes, out var error))
        {
            throw new InvalidOperationException($"Hidden D3D11 material parameter update failed: {error}");
        }
        var after = viewport.ResourceMetricsPayload();
        var state = materials.ParametersForSubmesh(0);
        var noResourceChurn = Metric(before, "geometry_buffer_identity") == Metric(after, "geometry_buffer_identity")
            && Metric(before, "material_binding_array_identity") == Metric(after, "material_binding_array_identity")
            && Metric(before, "texture_srv_creates") == Metric(after, "texture_srv_creates")
            && Metric(before, "texture_srv_disposals") == Metric(after, "texture_srv_disposals")
            && Metric(before, "material_binding_array_creates") == Metric(after, "material_binding_array_creates");
        return new Dictionary<string, object?>
        {
            ["state_exact"] = state.TextureBrightness == 1.25f
                && state.PostContrastBrightness == 1.05f
                && state.BaseColorLift == 0
                && state.ValueMax == 222
                && state.AutoBalance == 100
                && state.ShadowLift == 25
                && state.Metalness == 0.0f
                && state.Specular is null
                && state.RoughnessInverted == true
                && state.MetalnessInverted == false
                && state.RoughnessScale == 0.0f
                && state.RoughnessMin == 24
                && state.RoughnessMax == 230
                && state.MetalnessScale == 1.5f
                && state.MetalnessMin == 0
                && state.MetalnessMax == 255
                && state.RoughnessBlendTarget == 0.25f
                && state.RoughnessBlendStrength == 0.5f
                && state.MetalnessBlendTarget == 0.0f
                && state.MetalnessBlendStrength is null
                && state.TintColor == new System.Numerics.Vector3(0.8f, 0.9f, 1.0f)
                && state.MaterialRole == "glow",
            ["no_resource_churn"] = noResourceChurn,
            ["apply_counted"] = Metric(after, "material_parameter_apply_count") == Metric(before, "material_parameter_apply_count") + 1
                && Metric(after, "affected_material_parameter_batches") == Metric(before, "affected_material_parameter_batches") + 1,
            ["resources_before"] = before,
            ["resources_after"] = after,
        };
    }

    private static Form CreateHiddenHost()
    {
        return new Form
        {
            Text = "CDMW hidden D3D11 sparse soak",
            ClientSize = new Size(64, 64),
            StartPosition = FormStartPosition.Manual,
            Location = new Point(-32000, -32000),
            FormBorderStyle = FormBorderStyle.None,
            ShowInTaskbar = false,
            Visible = false,
        };
    }

    private static double ApplySparseUpdate(
        D3D11MaterialViewport viewport,
        ObjSubmesh submesh,
        int renderVertexCount,
        int sequence,
        int[] dirtyIndex,
        IReadOnlyDictionary<int, MeshVertexChannelChanges> changed)
    {
        var started = Stopwatch.GetTimestamp();
        var vertexIndex = sequence % renderVertexCount;
        var vertex = submesh.Vertices[vertexIndex];
        var delta = (sequence & 1) == 0 ? 0.0001f : -0.0001f;
        submesh.Vertices[vertexIndex] = vertex with { Z = vertex.Z + delta };
        submesh.Normals[vertexIndex] = new Vec3(delta, 0, 1);
        submesh.Uvs[vertexIndex] = new Vec2((vertexIndex % 1024) / 1024.0f, (sequence & 255) / 255.0f);
        dirtyIndex[0] = vertexIndex;
        viewport.RefreshVertexGeometry(changed);
        if (!viewport.TryApplyHeadlessPendingUpdate(out var updateError))
        {
            throw new InvalidOperationException($"Hidden D3D11 sparse upload {sequence} failed: {updateError}");
        }
        return ElapsedMilliseconds(started);
    }

    internal static ObjDocument BuildSyntheticDocument(int vertexCount)
    {
        var document = new ObjDocument();
        var submesh = new ObjSubmesh("gpu_sparse_soak", 0, 0, 0);
        document.Submeshes.Add(submesh);
        submesh.Vertices.Capacity = vertexCount;
        submesh.Normals.Capacity = vertexCount;
        submesh.Uvs.Capacity = vertexCount;
        var triangleCount = vertexCount / 3;
        submesh.Faces.Capacity = triangleCount;
        for (var triangle = 0; triangle < triangleCount; triangle++)
        {
            var vertexStart = triangle * 3;
            var x = triangle % 1024;
            var y = triangle / 1024;
            var z = (triangle % 17) * 0.001f;
            submesh.Vertices.Add(new Vec3(x, y, z));
            submesh.Vertices.Add(new Vec3(x + 0.4f, y, z));
            submesh.Vertices.Add(new Vec3(x, y + 0.4f, z));
            submesh.Normals.Add(new Vec3(0, 0, 1));
            submesh.Normals.Add(new Vec3(0, 0, 1));
            submesh.Normals.Add(new Vec3(0, 0, 1));
            submesh.Uvs.Add(new Vec2(0, 0));
            submesh.Uvs.Add(new Vec2(1, 0));
            submesh.Uvs.Add(new Vec2(0, 1));
            submesh.Faces.Add(new ObjFace(new[]
            {
                new ObjCorner(vertexStart, vertexStart, vertexStart),
                new ObjCorner(vertexStart + 1, vertexStart + 1, vertexStart + 1),
                new ObjCorner(vertexStart + 2, vertexStart + 2, vertexStart + 2),
            }));
        }
        while (submesh.Vertices.Count < vertexCount)
        {
            submesh.Vertices.Add(new Vec3(0, 0, 0));
            submesh.Normals.Add(new Vec3(0, 0, 1));
            submesh.Uvs.Add(new Vec2(0, 0));
        }
        return document;
    }

    internal static NetViewportCamera CameraFor(ObjDocument document, Size size)
    {
        var bounds = document.Bounds();
        var center = new Vec3(
            (bounds.Min.X + bounds.Max.X) * 0.5f,
            (bounds.Min.Y + bounds.Max.Y) * 0.5f,
            (bounds.Min.Z + bounds.Max.Z) * 0.5f);
        var sceneSize = Math.Max(bounds.Max.X - bounds.Min.X, Math.Max(bounds.Max.Y - bounds.Min.Y, bounds.Max.Z - bounds.Min.Z));
        var zoom = sceneSize > 0.0001f ? 380.0f / sceneSize : 220.0f;
        return NetViewportCamera.Create(center, bounds, -0.35f, 0.25f, zoom, 0, 0, size.Width, size.Height);
    }

    private static Dictionary<string, bool> EvaluateGates(
        HeadlessGpuSparseSoakOptions options,
        double[] durations,
        double cadenceSeconds,
        long workingSetBaseline,
        long workingSetFinal,
        Dictionary<string, object?> before,
        Dictionary<string, object?> after,
        Dictionary<string, object?> boundsProof)
    {
        var workingSetGrowth = GrowthRatio(workingSetBaseline, workingSetFinal);
        var effectiveHz = cadenceSeconds > 0 ? options.UpdateCount / cadenceSeconds : double.PositiveInfinity;
        return new Dictionary<string, bool>
        {
            ["update_handler_p95_below_16_7_ms"] = Percentile(durations, 0.95) < FrameBudgetMs,
            ["configured_update_count_completed"] = Metric(after, "sparse_vertex_updates") - Metric(before, "sparse_vertex_updates") == options.UpdateCount,
            ["sparse_upload_ranges_advanced"] = Metric(after, "vertex_patch_ranges") - Metric(before, "vertex_patch_ranges") >= options.UpdateCount,
            ["sparse_source_vertices_patched"] = Metric(after, "source_vertices_patched") - Metric(before, "source_vertices_patched") == options.UpdateCount,
            ["sparse_render_vertices_uploaded"] = Metric(after, "render_vertices_uploaded") - Metric(before, "render_vertices_uploaded") >= options.UpdateCount * 3L,
            ["topology_generation_retained"] = Metric(after, "topology_generation") == Metric(before, "topology_generation"),
            ["geometry_buffers_retained"] = Metric(after, "geometry_buffer_identity") == Metric(before, "geometry_buffer_identity")
                && Metric(after, "vertex_buffer_creates") == Metric(before, "vertex_buffer_creates")
                && Metric(after, "index_buffer_creates") == Metric(before, "index_buffer_creates")
                && Metric(after, "geometry_buffer_disposals") == Metric(before, "geometry_buffer_disposals"),
            ["no_full_rebuild_per_sparse_update"] = Metric(after, "full_geometry_rebuilds") == Metric(before, "full_geometry_rebuilds"),
            ["cached_srv_binding_arrays_retained"] = Metric(after, "material_binding_array_creates") == Metric(before, "material_binding_array_creates")
                && Metric(after, "material_binding_array_identity") == Metric(before, "material_binding_array_identity")
                && Metric(after, "cached_material_binding_arrays") == Metric(before, "cached_material_binding_arrays"),
            ["overlay_vertex_buffer_reused_across_frames"] = Metric(before, "overlay_vertex_buffer_creates") > 0
                && Metric(after, "overlay_vertex_buffer_creates") == Metric(before, "overlay_vertex_buffer_creates")
                && Metric(after, "overlay_vertex_buffer_maps") > Metric(before, "overlay_vertex_buffer_maps")
                && Metric(after, "overlay_batch_flushes") > Metric(before, "overlay_batch_flushes")
                && Metric(after, "overlay_batched_draws") > Metric(after, "overlay_batch_flushes"),
            ["vertex_markers_rendered_in_smoke"] = !options.Smoke
                || (Metric(after, "vertex_overlay_batch_draws") > 0
                    && Metric(after, "vertex_marker_size_pixels") >= 7),
            ["resident_vram_estimate_stable"] = Metric(after, "resident_vram_bytes_estimate") == Metric(before, "resident_vram_bytes_estimate"),
            ["post_warmup_working_set_growth_below_10_percent"] = workingSetGrowth < MaximumWorkingSetGrowthRatio,
            ["cadence_60hz_equivalent"] = !options.EnforceCadence || (effectiveHz >= 55.0 && effectiveHz <= 61.0),
            ["sparse_bounds_and_center_exact"] = boundsProof.TryGetValue("ok", out var boundsOk) && boundsOk is true,
        };
    }

    private static Dictionary<string, object?> BuildReport(
        HeadlessGpuSparseSoakOptions options,
        ObjDocument document,
        int renderVertexCount,
        double[] durations,
        double[] frameDurations,
        double cadenceSeconds,
        long workingSetBeforeDocument,
        long workingSetBaseline,
        long workingSetFinal,
        long peakWorkingSet,
        Dictionary<string, object?> resourcesBefore,
        Dictionary<string, object?> resourcesAfter,
        Dictionary<string, object?> boundsProof,
        Dictionary<string, bool> gates,
        bool ok,
        Form host,
        D3D11MaterialViewport viewport)
    {
        var releaseEligible = !options.Smoke && options.VertexCount >= 1_000_000 && options.UpdateCount >= 1_000 && options.EnforceCadence;
        return new Dictionary<string, object?>
        {
            ["schema"] = Schema,
            ["ok"] = ok,
            ["release_gate_eligible"] = releaseEligible,
            ["full_scale_gate_ok"] = releaseEligible && ok,
            ["generated_at_utc"] = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture),
            ["configuration"] = new Dictionary<string, object?>
            {
                ["profile"] = options.Smoke ? "smoke" : "full_scale",
                ["source_vertex_count"] = options.VertexCount,
                ["sparse_update_count"] = options.UpdateCount,
                ["warmup_update_count"] = options.WarmupUpdates,
                ["target_updates_per_second"] = options.TargetUpdatesPerSecond,
                ["cadence_enforced"] = options.EnforceCadence,
                ["handler_budget_ms"] = FrameBudgetMs,
                ["working_set_growth_budget_ratio"] = MaximumWorkingSetGrowthRatio,
            },
            ["synthetic_mesh"] = new Dictionary<string, object?>
            {
                ["generated_in_memory"] = true,
                ["checked_in_asset_used"] = false,
                ["source_vertices"] = document.Submeshes.Sum(item => item.Vertices.Count),
                ["triangles"] = document.Submeshes.Sum(item => item.Faces.Count),
                ["render_vertices"] = renderVertexCount,
            },
            ["backend_proof"] = new Dictionary<string, object?>
            {
                ["backend"] = viewport.BackendName,
                ["gpu_backed"] = true,
                ["swap_chain_initialized"] = viewport.IsInitialized,
                ["hwnd_required"] = true,
                ["host_hwnd_created"] = host.IsHandleCreated,
                ["viewport_hwnd_created"] = viewport.IsHandleCreated,
                ["host_visible"] = host.Visible,
                ["host_is_window_visible"] = host.IsHandleCreated && IsWindowVisible(host.Handle),
                ["viewport_is_window_visible"] = viewport.IsHandleCreated && IsWindowVisible(viewport.Handle),
                ["show_called"] = false,
                ["application_run_called"] = false,
                ["show_in_taskbar"] = host.ShowInTaskbar,
            },
            ["timings"] = new Dictionary<string, object?>
            {
                ["handler_ms_min"] = durations.Min(),
                ["handler_ms_average"] = durations.Average(),
                ["handler_ms_median"] = Percentile(durations, 0.5),
                ["handler_ms_p95"] = Percentile(durations, 0.95),
                ["handler_ms_max"] = durations.Max(),
                ["frame_ms_average"] = frameDurations.Average(),
                ["frame_ms_p95"] = Percentile(frameDurations, 0.95),
                ["frame_ms_max"] = frameDurations.Max(),
                ["frame_sample_count"] = frameDurations.Length,
                ["cadence_elapsed_seconds"] = cadenceSeconds,
                ["effective_updates_per_second"] = cadenceSeconds > 0 ? options.UpdateCount / cadenceSeconds : 0,
            },
            ["working_set"] = new Dictionary<string, object?>
            {
                ["before_document_bytes"] = workingSetBeforeDocument,
                ["post_warmup_baseline_bytes"] = workingSetBaseline,
                ["final_bytes"] = workingSetFinal,
                ["peak_sampled_bytes"] = peakWorkingSet,
                ["post_warmup_growth_ratio"] = GrowthRatio(workingSetBaseline, workingSetFinal),
            },
            ["resources_before"] = resourcesBefore,
            ["resources_after"] = resourcesAfter,
            ["sparse_bounds_proof"] = boundsProof,
            ["gates"] = gates,
        };
    }

    private static void WaitForCadence(Stopwatch cadence, int completedUpdates, double updatesPerSecond)
    {
        var targetSeconds = completedUpdates / updatesPerSecond;
        while (true)
        {
            var remainingMs = (targetSeconds - cadence.Elapsed.TotalSeconds) * 1000.0;
            if (remainingMs <= 0)
            {
                return;
            }
            if (remainingMs > 2.0)
            {
                Thread.Sleep(Math.Max(1, (int)remainingMs - 1));
            }
            else
            {
                Thread.SpinWait(128);
            }
        }
    }

    private static double Percentile(double[] values, double percentile)
    {
        var sorted = values.OrderBy(value => value).ToArray();
        var index = Math.Clamp((int)Math.Ceiling(sorted.Length * percentile) - 1, 0, sorted.Length - 1);
        return sorted[index];
    }

    private static long Metric(IReadOnlyDictionary<string, object?> payload, string key)
    {
        return payload.TryGetValue(key, out var value) && value is not null
            ? Convert.ToInt64(value, CultureInfo.InvariantCulture)
            : 0;
    }

    private static long WorkingSet(Process process)
    {
        process.Refresh();
        return process.WorkingSet64;
    }

    private static double GrowthRatio(long baseline, long current)
    {
        return Math.Max(0.0, current - baseline) / Math.Max(1.0, baseline);
    }

    private static double ElapsedMilliseconds(long started)
    {
        return (Stopwatch.GetTimestamp() - started) * 1000.0 / Stopwatch.Frequency;
    }

    private static bool NearlyEqual(float left, float right)
    {
        return Math.Abs(left - right) <= 0.00001f;
    }

    private static void ForceCollection()
    {
        GC.Collect();
        GC.WaitForPendingFinalizers();
        GC.Collect();
    }

    private static void WriteReport(string path, Dictionary<string, object?> report)
    {
        var fullPath = Path.GetFullPath(path);
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath) ?? Environment.CurrentDirectory);
        var json = JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true });
        var staging = $"{fullPath}.{Guid.NewGuid():N}.tmp";
        try
        {
            File.WriteAllText(staging, json + Environment.NewLine, new UTF8Encoding(false));
            File.Move(staging, fullPath, overwrite: true);
        }
        finally
        {
            if (File.Exists(staging))
            {
                File.Delete(staging);
            }
        }
        Console.WriteLine(json);
    }

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsWindowVisible(IntPtr hWnd);
}
