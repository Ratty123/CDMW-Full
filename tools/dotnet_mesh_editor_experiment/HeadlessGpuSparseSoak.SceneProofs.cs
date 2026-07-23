using System.Numerics;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static partial class HeadlessGpuSparseSoak
{
    private static Dictionary<string, object?> SparseBoundsProof()
    {
        var document = new ObjDocument();
        var submesh = new ObjSubmesh("bounds", 0, 0, 0);
        document.Submeshes.Add(submesh);
        submesh.Vertices.AddRange(new[] { new Vec3(-1, -2, -3), new Vec3(1, 2, 3), new Vec3(0, 0, 0) });
        var tracker = new SparseMeshBoundsTracker(document);
        tracker.Rebase();
        var changed = new Dictionary<int, IReadOnlyCollection<int>> { [0] = new[] { 2 } };
        submesh.Vertices[2] = new Vec3(4, 0, 0);
        var outwardRebased = tracker.Update(changed);
        var outwardExact = NearlyEqual(tracker.Bounds.Max.X, 4) && NearlyEqual(tracker.Center.X, 1.5f);
        submesh.Vertices[2] = new Vec3(0.5f, 0, 0);
        var inwardRebased = tracker.Update(changed);
        var inwardExact = NearlyEqual(tracker.Bounds.Max.X, 1) && NearlyEqual(tracker.Center.X, 0);
        var ok = !outwardRebased && inwardRebased && outwardExact && inwardExact;
        return new Dictionary<string, object?>
        {
            ["ok"] = ok,
            ["outward_interior_update_was_sparse"] = !outwardRebased,
            ["outward_bounds_and_center_exact"] = outwardExact,
            ["inward_extremum_update_rebased"] = inwardRebased,
            ["inward_bounds_and_center_exact"] = inwardExact,
            ["exact_rebases"] = tracker.ExactRebaseCount,
            ["sparse_updates"] = tracker.SparseUpdateCount,
            ["boundary_triggered_rebases"] = tracker.BoundaryTriggeredRebaseCount,
        };
    }

    private static Dictionary<string, object?> ResidentPlacementProof()
    {
        var state = new NetSceneState();
        var translation0 = new Vector3(1.0f, 2.0f, 3.0f);
        var rotation0 = new Vector3(10.0f, -20.0f, 5.0f);
        var scale0 = new Vector3(1.2f, 0.8f, 1.5f);
        var basePivot = new Vector3(7.0f, 11.0f, -3.0f);
        var sourceAnchor = new Vector3(3.0f, -2.0f, 4.0f);
        var automaticLinear = Matrix4x4.CreateScale(2.0f, 0.5f, 1.4f)
            * Matrix4x4.CreateRotationY(0.3f);
        var referenceMatrix = Matrix4x4.CreateTranslation(-4.0f, 0.0f, 2.0f);
        var gridOrigin = new Vector3(2.0f, -1.0f, 5.0f);
        var matrix0 = PlacementProofMatrix(
            automaticLinear,
            rotation0,
            scale0,
            basePivot + translation0,
            sourceAnchor);
        ApplyPlacementProofFrame(
            state,
            requestId: 0,
            generation: 1,
            translation0,
            rotation0,
            scale0,
            matrix0,
            referenceMatrix,
            gridOrigin,
            out _);

        state.BeginProvisionalPlacement();
        var translation1 = translation0 + new Vector3(4.0f, -1.0f, 2.0f);
        var rotation1 = rotation0 + new Vector3(0.0f, 12.0f, 0.0f);
        var scale1 = scale0 * 1.25f;
        state.ApplyConstrainedTranslation(translation0, translation1 - translation0);
        state.ApplyConstrainedRotation(rotation0, axis: 1, degrees: 12.0f);
        state.ApplyConstrainedScale(scale0, axis: -1, factor: 1.25f);
        var expectedProvisional = PlacementProofMatrix(
            automaticLinear,
            rotation1,
            scale1,
            basePivot + translation1,
            sourceAnchor);
        var editableMovedImmediately = MatrixNearlyEqual(
                state.RoleViewModelMatrix(0),
                expectedProvisional)
            && !MatrixNearlyEqual(state.RoleViewModelMatrix(0), matrix0);
        var referenceUnchanged = MatrixNearlyEqual(state.RoleViewModelMatrix(1), referenceMatrix);
        var pivotMovedWithTranslation = VectorNearlyEqual(
            state.RoleViewGizmoPivot(),
            basePivot + translation1);
        var nonzeroSourceAnchorStayedAtPivot = VectorNearlyEqual(
            Vector3.Transform(sourceAnchor, state.RoleViewModelMatrix(0)),
            state.RoleViewGizmoPivot());

        var translation2 = translation0 + Vector3.UnitX;
        var matrix2 = PlacementProofMatrix(
            automaticLinear,
            rotation0,
            scale0,
            basePivot + translation2,
            sourceAnchor);
        var staleApplied = ApplyPlacementProofFrame(
            state,
            requestId: 1,
            generation: 2,
            translation2,
            rotation0,
            scale0,
            matrix2,
            referenceMatrix,
            gridOrigin + new Vector3(100.0f, 0.0f, 100.0f),
            out var staleRejection);
        var staleAuthorityRetainedProvisional = staleApplied
            && staleRejection.Length == 0
            && !state.AcceptAuthoritativePlacementFrame()
            && state.HasProvisionalPlacement
            && MatrixNearlyEqual(state.RoleViewModelMatrix(0), expectedProvisional);
        var residentGridStayedFixed = VectorNearlyEqual(state.GridOrigin, gridOrigin);

        var acceptedApplied = ApplyPlacementProofFrame(
            state,
            requestId: 2,
            generation: 3,
            translation1,
            rotation1,
            scale1,
            expectedProvisional,
            referenceMatrix,
            gridOrigin + new Vector3(200.0f, 0.0f, 200.0f),
            out var acceptedRejection);
        var matchingAuthorityAccepted = acceptedApplied
            && acceptedRejection.Length == 0
            && state.AcceptAuthoritativePlacementFrame()
            && !state.HasProvisionalPlacement
            && MatrixNearlyEqual(state.RoleViewModelMatrix(0), expectedProvisional);
        var ok = editableMovedImmediately
            && referenceUnchanged
            && pivotMovedWithTranslation
            && nonzeroSourceAnchorStayedAtPivot
            && staleAuthorityRetainedProvisional
            && residentGridStayedFixed
            && matchingAuthorityAccepted;
        return new Dictionary<string, object?>
        {
            ["ok"] = ok,
            ["editable_matrix_changed_at_input_cadence"] = editableMovedImmediately,
            ["reference_matrix_unchanged"] = referenceUnchanged,
            ["gizmo_pivot_followed_translation"] = pivotMovedWithTranslation,
            ["nonzero_source_anchor_stayed_at_gizmo_pivot"] = nonzeroSourceAnchorStayedAtPivot,
            ["stale_authority_retained_newer_provisional_drag"] = staleAuthorityRetainedProvisional,
            ["resident_world_grid_stayed_fixed"] = residentGridStayedFixed,
            ["matching_authority_completed_provisional_drag"] = matchingAuthorityAccepted,
        };
    }

    private static Dictionary<string, object?> PresentationModeProof()
    {
        var scene = new NetSceneState();
        _ = ApplyPlacementProofFrame(
            scene,
            requestId: 0,
            generation: 1,
            Vector3.Zero,
            Vector3.Zero,
            Vector3.One,
            Matrix4x4.Identity,
            Matrix4x4.Identity,
            Vector3.Zero,
            out _);
        var expectations = new[]
        {
            (Mode: "side_by_side", Roles: new[] { "reference", "editable" }, EditableVisible: true, ReferenceVisible: true),
            (Mode: "overlay", Roles: new[] { "comparison" }, EditableVisible: true, ReferenceVisible: true),
            (Mode: "replacement_only", Roles: new[] { "editable" }, EditableVisible: true, ReferenceVisible: false),
            (Mode: "original_only", Roles: new[] { "reference" }, EditableVisible: false, ReferenceVisible: true),
        };
        var rows = new List<Dictionary<string, object?>>();
        foreach (var expected in expectations)
        {
            scene.SetComparisonMode(expected.Mode);
            var simultaneous = MeshViewport.UsesSimultaneousRolePanes(
                scene.ComparisonMode,
                scene.EditableSubmeshCount,
                scene.ReferenceSubmeshCount);
            var roles = simultaneous
                ? new[] { "reference", "editable" }
                : new[] { MeshViewport.SinglePaneRoleForMode(scene.ComparisonMode) };
            var editableVisible = scene.IsVisible(0);
            var referenceVisible = scene.IsVisible(1);
            rows.Add(new Dictionary<string, object?>
            {
                ["mode"] = expected.Mode,
                ["roles"] = roles,
                ["editable_visible"] = editableVisible,
                ["reference_visible"] = referenceVisible,
                ["ok"] = roles.SequenceEqual(expected.Roles)
                    && editableVisible == expected.EditableVisible
                    && referenceVisible == expected.ReferenceVisible,
            });
        }
        var ownerSize = new System.Drawing.Size(1412, 620);
        var deferredRenderSurfaceSize = new System.Drawing.Size(1180, 614);
        var effectiveDeferredSize = MeshViewport.EffectivePaneSurfaceSize(
            ownerSize,
            deferredRenderSurfaceSize,
            renderSurfaceAvailable: true);
        var fallbackOwnerSize = MeshViewport.EffectivePaneSurfaceSize(
            ownerSize,
            System.Drawing.Size.Empty,
            renderSurfaceAvailable: false);
        var paneGeometryTracksRenderSurface =
            effectiveDeferredSize == deferredRenderSurfaceSize
            && fallbackOwnerSize == ownerSize;
        return new Dictionary<string, object?>
        {
            ["ok"] = rows.All(row => (bool)row["ok"]!)
                && paneGeometryTracksRenderSurface
                && NetSceneState.EffectiveComparisonMode("side_by_side", "mesh_edit") == "replacement_only"
                && NetSceneState.EffectiveComparisonMode("original_only", "mesh_edit") == "replacement_only",
            ["modes"] = rows,
            ["pane_geometry_tracks_current_render_surface"] = paneGeometryTracksRenderSurface,
            ["deferred_render_surface_size"] = new[]
            {
                effectiveDeferredSize.Width,
                effectiveDeferredSize.Height,
            },
            ["fallback_owner_size"] = new[]
            {
                fallbackOwnerSize.Width,
                fallbackOwnerSize.Height,
            },
            ["mesh_edit_side_by_side_resolved"] = NetSceneState.EffectiveComparisonMode("side_by_side", "mesh_edit"),
            ["mesh_edit_original_only_resolved"] = NetSceneState.EffectiveComparisonMode("original_only", "mesh_edit"),
        };
    }

    private static Dictionary<string, object?> CameraZoomProof()
    {
        const float fitZoom = 0.19f;
        var expectedSteps = new[]
        {
            0.1f, 0.25f, 0.5f, 0.75f, 1.0f, 1.5f, 2.0f, 3.0f, 4.0f,
            6.0f, 8.0f, 12.0f, 16.0f, 24.0f, 32.0f, 48.0f, 64.0f,
        };
        var actualSteps = CameraZoomPolicy.FitRelativeSteps.ToArray();
        var stepRows = new List<Dictionary<string, object?>>();
        for (var index = 0; index < expectedSteps.Length - 1; index++)
        {
            var current = fitZoom * expectedSteps[index];
            var next = CameraZoomPolicy.ApplyWheelDelta(current, fitZoom, 120);
            var previous = CameraZoomPolicy.ApplyWheelDelta(next, fitZoom, -120);
            stepRows.Add(new Dictionary<string, object?>
            {
                ["from_ratio"] = expectedSteps[index],
                ["to_ratio"] = next / fitZoom,
                ["restored_ratio"] = previous / fitZoom,
                ["ok"] = NearlyEqual(next, fitZoom * expectedSteps[index + 1])
                    && NearlyEqual(previous, current),
            });
        }
        var fitScaleRows = new[] { 0.0005f, fitZoom, 226.707f }
            .Select(candidateFit => new Dictionary<string, object?>
            {
                ["fit_zoom"] = candidateFit,
                ["minimum"] = CameraZoomPolicy.MinimumZoom(candidateFit),
                ["maximum"] = CameraZoomPolicy.MaximumZoom(candidateFit),
                ["ok"] = NearlyEqual(CameraZoomPolicy.MinimumZoom(candidateFit), candidateFit * 0.1f)
                    && NearlyEqual(CameraZoomPolicy.MaximumZoom(candidateFit), candidateFit * 64.0f),
            })
            .ToArray();
        var zoomedIn = CameraZoomPolicy.ApplyWheelDelta(fitZoom, fitZoom, 120);
        var restored = CameraZoomPolicy.ApplyWheelDelta(zoomedIn, fitZoom, -120);
        var zoomedOut = CameraZoomPolicy.ApplyWheelDelta(fitZoom, fitZoom, -120);
        var minimum = CameraZoomPolicy.MinimumZoom(fitZoom);
        var maximum = CameraZoomPolicy.MaximumZoom(fitZoom);
        var reciprocalError = Math.Abs(restored - fitZoom);
        var boundariesExact = NearlyEqual(
                CameraZoomPolicy.ApplyWheelDelta(minimum, fitZoom, -120),
                minimum)
            && NearlyEqual(
                CameraZoomPolicy.ApplyWheelDelta(maximum, fitZoom, 120),
                maximum);
        var highResolutionDeltaSingleStep = NearlyEqual(
                CameraZoomPolicy.ApplyWheelDelta(fitZoom, fitZoom, 1),
                zoomedIn)
            && NearlyEqual(
                CameraZoomPolicy.ApplyWheelDelta(fitZoom, fitZoom, 1200),
                zoomedIn)
            && NearlyEqual(
                CameraZoomPolicy.ApplyWheelDelta(fitZoom, fitZoom, -1),
                zoomedOut)
            && NearlyEqual(
                CameraZoomPolicy.ApplyWheelDelta(fitZoom, fitZoom, -1200),
                zoomedOut);
        var invalidValuesSafe = NearlyEqual(
                CameraZoomPolicy.ApplyZoomFactor(float.NaN, fitZoom, float.NaN),
                fitZoom)
            && NearlyEqual(CameraZoomPolicy.MinimumZoom(float.NaN), 0.1f)
            && NearlyEqual(CameraZoomPolicy.MaximumZoom(float.PositiveInfinity), 64.0f);
        var programmaticClampExact = NearlyEqual(
                CameraZoomPolicy.ApplyZoomFactor(fitZoom, fitZoom, 0.0001f),
                minimum)
            && NearlyEqual(
                CameraZoomPolicy.ApplyZoomFactor(fitZoom, fitZoom, 1000.0f),
                maximum);
        var pannedAnchorProof = PannedZoomAnchorProof(expectedSteps);
        var paneIsolationProof = PaneZoomIsolationProof();
        var stepTableExact = actualSteps.SequenceEqual(expectedSteps);
        var stepTransitionsExact = stepRows.All(row => row.GetValueOrDefault("ok") is true);
        var fitRelativeBoundsExact = fitScaleRows.All(row => row.GetValueOrDefault("ok") is true);
        return new Dictionary<string, object?>
        {
            ["ok"] = stepTableExact
                && stepTransitionsExact
                && fitRelativeBoundsExact
                && boundariesExact
                && highResolutionDeltaSingleStep
                && invalidValuesSafe
                && programmaticClampExact
                && pannedAnchorProof.GetValueOrDefault("ok") is true
                && paneIsolationProof.GetValueOrDefault("ok") is true
                && reciprocalError <= 0.00001f
                && zoomedOut < fitZoom
                && minimum < fitZoom,
            ["archive_browser_step_table_exact"] = stepTableExact,
            ["step_transitions"] = stepRows,
            ["fit_scale_bounds"] = fitScaleRows,
            ["boundaries_exact"] = boundariesExact,
            ["high_resolution_delta_single_step"] = highResolutionDeltaSingleStep,
            ["invalid_values_safe"] = invalidValuesSafe,
            ["programmatic_clamp_exact"] = programmaticClampExact,
            ["panned_anchor_proof"] = pannedAnchorProof,
            ["pane_isolation_proof"] = paneIsolationProof,
            ["fit_zoom"] = fitZoom,
            ["zoomed_in"] = zoomedIn,
            ["restored"] = restored,
            ["zoomed_out"] = zoomedOut,
            ["minimum"] = minimum,
            ["maximum"] = maximum,
            ["reciprocal_error"] = reciprocalError,
            ["shared_interaction_modes"] = new[] { "placement", "mesh_edit" },
        };
    }

    private static Dictionary<string, object?> FitRelativeOverlayProof()
    {
        const float fitZoom = 0.19f;
        var expected = new (float Ratio, float MarkerSize, float WireOpacity)[]
        {
            (0.1f, 2.0f, 0.2f),
            (0.25f, 2.0f, 0.25f),
            (0.5f, 3.5f, 0.5f),
            (0.75f, 5.25f, 0.75f),
            (1.0f, 7.0f, 1.0f),
            (1.5f, 7.0f, 1.0f),
            (64.0f, 7.0f, 1.0f),
        };
        var rows = expected
            .Select(item =>
            {
                var style = FitRelativeOverlayPolicy.ForZoom(fitZoom * item.Ratio, fitZoom);
                return new Dictionary<string, object?>
                {
                    ["zoom_ratio"] = item.Ratio,
                    ["vertex_marker_size_pixels"] = style.VertexMarkerSizePixels,
                    ["wire_opacity_scale"] = style.WireOpacityScale,
                    ["ok"] = NearlyEqual(style.ZoomRatio, item.Ratio)
                        && NearlyEqual(style.VertexMarkerSizePixels, item.MarkerSize)
                        && NearlyEqual(style.WireOpacityScale, item.WireOpacity),
                };
            })
            .ToArray();
        var fitScaleRows = new[] { 0.0005f, fitZoom, 226.707f }
            .Select(candidateFit =>
            {
                var style = FitRelativeOverlayPolicy.ForZoom(candidateFit * 0.5f, candidateFit);
                return new Dictionary<string, object?>
                {
                    ["fit_zoom"] = candidateFit,
                    ["vertex_marker_size_pixels"] = style.VertexMarkerSizePixels,
                    ["wire_opacity_scale"] = style.WireOpacityScale,
                    ["ok"] = NearlyEqual(style.ZoomRatio, 0.5f)
                        && NearlyEqual(style.VertexMarkerSizePixels, 3.5f)
                        && NearlyEqual(style.WireOpacityScale, 0.5f),
                };
            })
            .ToArray();
        var bounds = (Min: new Vec3(-1.0f, -1.0f, -1.0f), Max: new Vec3(1.0f, 1.0f, 1.0f));
        var camera = NetViewportCamera.Create(
            new Vec3(0.0f, 0.0f, 0.0f),
            bounds,
            0.0f,
            0.0f,
            CameraZoomPolicy.FitZoomForSceneSize(2.0f) * 0.5f,
            0.0f,
            0.0f,
            1280,
            720);
        var cameraStyle = FitRelativeOverlayPolicy.ForCamera(camera);
        var invalidStyle = FitRelativeOverlayPolicy.ForZoom(float.NaN, float.NaN);
        var expectedRowsExact = rows.All(row => row.GetValueOrDefault("ok") is true);
        var fitScaleIndependent = fitScaleRows.All(row => row.GetValueOrDefault("ok") is true);
        var cameraUsesSceneFit = NearlyEqual(cameraStyle.ZoomRatio, 0.5f)
            && NearlyEqual(cameraStyle.VertexMarkerSizePixels, 3.5f)
            && NearlyEqual(cameraStyle.WireOpacityScale, 0.5f);
        var invalidValuesSafe = NearlyEqual(invalidStyle.ZoomRatio, 1.0f)
            && NearlyEqual(invalidStyle.VertexMarkerSizePixels, 7.0f)
            && NearlyEqual(invalidStyle.WireOpacityScale, 1.0f);
        return new Dictionary<string, object?>
        {
            ["ok"] = expectedRowsExact
                && fitScaleIndependent
                && cameraUsesSceneFit
                && invalidValuesSafe,
            ["zoom_steps"] = rows,
            ["fit_scale_rows"] = fitScaleRows,
            ["expected_rows_exact"] = expectedRowsExact,
            ["fit_scale_independent"] = fitScaleIndependent,
            ["camera_uses_scene_fit"] = cameraUsesSceneFit,
            ["invalid_values_safe"] = invalidValuesSafe,
            ["minimum_vertex_marker_size_pixels"] = FitRelativeOverlayPolicy.MinimumVertexMarkerSizePixels,
            ["minimum_wire_opacity_scale"] = FitRelativeOverlayPolicy.MinimumWireOpacityScale,
        };
    }

    private static Dictionary<string, object?> PannedZoomAnchorProof(IReadOnlyList<float> zoomSteps)
    {
        var bounds = (Min: new Vec3(-4.0f, -2.0f, 3.0f), Max: new Vec3(8.0f, 10.0f, 15.0f));
        var center = new Vec3(2.0f, 4.0f, 9.0f);
        const float fitZoom = 31.666666f;
        var angles = new (string Name, float Yaw, float Pitch)[]
        {
            ("front", 0.0f, 0.0f),
            ("back", MathF.PI, 0.0f),
            ("top", 0.0f, -89.0f * MathF.PI / 180.0f),
            ("side", MathF.PI * 0.5f, 0.0f),
            ("oblique", -35.0f * MathF.PI / 180.0f, 20.0f * MathF.PI / 180.0f),
        };
        var pans = new (string Name, float X, float Y)[]
        {
            ("centered", 0.0f, 0.0f),
            ("panned", 47.0f, -31.0f),
        };
        var rows = new List<Dictionary<string, object?>>();
        foreach (var angle in angles)
        {
            foreach (var pan in pans)
            {
                var context = new NetViewPresentationContext
                {
                    Id = "editable",
                    RoleFilter = "editable",
                    Yaw = angle.Yaw,
                    Pitch = angle.Pitch,
                    Zoom = fitZoom,
                    PanX = pan.X,
                    PanY = pan.Y,
                    CameraMinimum = bounds.Min,
                    CameraMaximum = bounds.Max,
                };
                var baselineCamera = NetViewportCamera.Create(
                    center,
                    bounds,
                    context.Yaw,
                    context.Pitch,
                    context.Zoom,
                    context.PanX,
                    context.PanY,
                    1280,
                    720);
                var anchor = UnprojectFramingCenter(baselineCamera);
                var baseline = baselineCamera.Project(anchor);
                var maximumDelta = 0.0;
                var maximumWorldPanError = 0.0;
                var initialWorldPanX = context.PanX / context.Zoom;
                var initialWorldPanY = context.PanY / context.Zoom;
                foreach (var step in zoomSteps)
                {
                    MeshViewport.ApplyZoomToContext(context, fitZoom * step);
                    var projected = NetViewportCamera.Create(
                        center,
                        bounds,
                        context.Yaw,
                        context.Pitch,
                        context.Zoom,
                        context.PanX,
                        context.PanY,
                        1280,
                        720).Project(anchor);
                    maximumDelta = Math.Max(
                        maximumDelta,
                        Math.Sqrt(
                            Math.Pow(projected.X - baseline.X, 2.0)
                            + Math.Pow(projected.Y - baseline.Y, 2.0)));
                    maximumWorldPanError = Math.Max(
                        maximumWorldPanError,
                        Math.Max(
                            Math.Abs((context.PanX / context.Zoom) - initialWorldPanX),
                            Math.Abs((context.PanY / context.Zoom) - initialWorldPanY)));
                }
                rows.Add(new Dictionary<string, object?>
                {
                    ["angle"] = angle.Name,
                    ["pan"] = pan.Name,
                    ["anchor"] = new[] { anchor.X, anchor.Y, anchor.Z },
                    ["baseline"] = new[] { baseline.X, baseline.Y },
                    ["maximum_pixel_delta"] = maximumDelta,
                    ["maximum_world_pan_error"] = maximumWorldPanError,
                    ["ok"] = maximumDelta <= 0.005 && maximumWorldPanError <= 0.00001,
                });
            }
        }
        return new Dictionary<string, object?>
        {
            ["ok"] = rows.All(row => row.GetValueOrDefault("ok") is true),
            ["angles"] = rows,
            ["panned_anchor_tolerance_pixels"] = 0.005,
            ["world_pan_tolerance"] = 0.00001,
        };
    }

    private static Vec3 UnprojectFramingCenter(NetViewportCamera camera)
    {
        if (!Matrix4x4.Invert(camera.WorldViewProjection, out var inverse))
        {
            return camera.Center;
        }
        var world = Vector4.Transform(new Vector4(0.0f, 0.0f, 0.5f, 1.0f), inverse);
        if (Math.Abs(world.W) <= 0.000001f)
        {
            return camera.Center;
        }
        return new Vec3(world.X / world.W, world.Y / world.W, world.Z / world.W);
    }

    private static Dictionary<string, object?> PaneZoomIsolationProof()
    {
        var editable = new NetViewPresentationContext
        {
            Id = "editable",
            RoleFilter = "editable",
            Yaw = 0.25f,
            Pitch = -0.35f,
            Zoom = 19.0f,
            PanX = 13.0f,
            PanY = -7.0f,
            CameraMinimum = new Vec3(-10.0f, -4.0f, -2.0f),
            CameraMaximum = new Vec3(10.0f, 6.0f, 8.0f),
        };
        var reference = new NetViewPresentationContext
        {
            Id = "reference",
            RoleFilter = "reference",
            Yaw = -0.8f,
            Pitch = 0.45f,
            Zoom = 38.0f,
            PanX = -21.0f,
            PanY = 11.0f,
            CameraMinimum = new Vec3(-3.0f, -5.0f, -4.0f),
            CameraMaximum = new Vec3(7.0f, 5.0f, 6.0f),
        };
        const string activeContext = "editable";
        var editableBefore = CameraFixedValues(editable);
        var referenceBefore = CameraFixedValues(reference);
        var editableWorldPanBefore = CameraWorldPan(editable);
        var referenceWorldPanBefore = CameraWorldPan(reference);
        var editableZoomBefore = editable.Zoom;
        var referenceZoomBefore = reference.Zoom;
        var editableProjectedPanBefore = new[] { editable.PanX, editable.PanY };
        var referenceProjectedPanBefore = new[] { reference.PanX, reference.PanY };

        MeshViewport.ApplyWheelZoomToContext(reference, 120);
        var referenceChangedOnlyZoom = CameraFixedValues(reference).SequenceEqual(referenceBefore)
            && CameraWorldPan(reference).Zip(referenceWorldPanBefore).All(pair => NearlyEqual(pair.First, pair.Second))
            && NearlyEqual(reference.Zoom, referenceZoomBefore * 1.5f)
            && NearlyEqual(reference.PanX, referenceProjectedPanBefore[0] * 1.5f)
            && NearlyEqual(reference.PanY, referenceProjectedPanBefore[1] * 1.5f);
        var editableUntouched = CameraFixedValues(editable).SequenceEqual(editableBefore)
            && CameraWorldPan(editable).Zip(editableWorldPanBefore).All(pair => NearlyEqual(pair.First, pair.Second))
            && NearlyEqual(editable.Zoom, editableZoomBefore);
        MeshViewport.ApplyWheelZoomToContext(reference, -120);
        var referenceRestored = NearlyEqual(reference.Zoom, referenceZoomBefore)
            && NearlyEqual(reference.PanX, referenceProjectedPanBefore[0])
            && NearlyEqual(reference.PanY, referenceProjectedPanBefore[1]);

        MeshViewport.ApplyWheelZoomToContext(editable, -120);
        var editableChangedOnlyZoom = CameraFixedValues(editable).SequenceEqual(editableBefore)
            && CameraWorldPan(editable).Zip(editableWorldPanBefore).All(pair => NearlyEqual(pair.First, pair.Second))
            && NearlyEqual(editable.Zoom, editableZoomBefore * 0.75f)
            && NearlyEqual(editable.PanX, editableProjectedPanBefore[0] * 0.75f)
            && NearlyEqual(editable.PanY, editableProjectedPanBefore[1] * 0.75f);
        var referenceUntouched = CameraFixedValues(reference).SequenceEqual(referenceBefore)
            && CameraWorldPan(reference).Zip(referenceWorldPanBefore).All(pair => NearlyEqual(pair.First, pair.Second))
            && NearlyEqual(reference.Zoom, referenceZoomBefore);
        MeshViewport.ApplyWheelZoomToContext(editable, 120);
        var editableRestored = NearlyEqual(editable.Zoom, editableZoomBefore)
            && NearlyEqual(editable.PanX, editableProjectedPanBefore[0])
            && NearlyEqual(editable.PanY, editableProjectedPanBefore[1]);
        var activeContextUnchanged = activeContext == "editable";

        return new Dictionary<string, object?>
        {
            ["ok"] = referenceChangedOnlyZoom
                && editableUntouched
                && referenceRestored
                && editableChangedOnlyZoom
                && referenceUntouched
                && editableRestored
                && activeContextUnchanged,
            ["reference_changed_only_zoom"] = referenceChangedOnlyZoom,
            ["reference_world_pan_preserved"] =
                CameraWorldPan(reference).Zip(referenceWorldPanBefore).All(pair => NearlyEqual(pair.First, pair.Second)),
            ["editable_untouched_when_reference_targeted"] = editableUntouched,
            ["reference_inverse_restored"] = referenceRestored,
            ["editable_changed_only_zoom"] = editableChangedOnlyZoom,
            ["editable_world_pan_preserved"] =
                CameraWorldPan(editable).Zip(editableWorldPanBefore).All(pair => NearlyEqual(pair.First, pair.Second)),
            ["reference_untouched_when_editable_targeted"] = referenceUntouched,
            ["editable_inverse_restored"] = editableRestored,
            ["active_context_unchanged"] = activeContextUnchanged,
        };
    }

    private static float[] CameraFixedValues(NetViewPresentationContext context) => new[]
    {
        context.Yaw,
        context.Pitch,
        context.CameraMinimum.X,
        context.CameraMinimum.Y,
        context.CameraMinimum.Z,
        context.CameraMaximum.X,
        context.CameraMaximum.Y,
        context.CameraMaximum.Z,
    };

    private static float[] CameraWorldPan(NetViewPresentationContext context) => new[]
    {
        context.PanX / context.Zoom,
        context.PanY / context.Zoom,
    };

    private static bool ApplyPlacementProofFrame(
        NetSceneState state,
        long requestId,
        long generation,
        Vector3 translation,
        Vector3 rotation,
        Vector3 scale,
        Matrix4x4 editableMatrix,
        Matrix4x4 referenceMatrix,
        Vector3 gridOrigin,
        out string rejectionReason)
    {
        var payload = new Dictionary<string, object?>
        {
            ["session_id"] = "resident-placement-proof",
            ["source_identity"] = "resident-placement-source",
            ["request_id"] = requestId,
            ["scene_generation"] = generation,
            ["editable_submesh_count"] = 1,
            ["reference_submesh_count"] = 1,
            ["comparison_mode"] = "side_by_side",
            ["interaction_mode"] = "placement",
            ["placement"] = new Dictionary<string, object?>
            {
                ["translation"] = VectorValues(translation),
                ["rotation_degrees"] = VectorValues(rotation),
                ["scale"] = VectorValues(scale),
            },
            ["placement_pivot"] = VectorValues(new Vector3(7.0f, 11.0f, -3.0f) + translation),
            ["automatic_alignment"] = new Dictionary<string, object?>
            {
                ["source_anchor"] = new[] { 3.0f, -2.0f, 4.0f },
            },
            ["grid"] = new Dictionary<string, object?>
            {
                ["visible"] = true,
                ["origin"] = VectorValues(gridOrigin),
                ["spacing"] = 2.0f,
            },
            ["roles"] = new Dictionary<string, object?>
            {
                ["editable"] = PlacementProofRole(editableMatrix),
                ["reference"] = PlacementProofRole(referenceMatrix),
            },
            ["bounds"] = new Dictionary<string, object?>
            {
                ["min"] = new[] { -20.0f, -20.0f, -20.0f },
                ["max"] = new[] { 20.0f, 20.0f, 20.0f },
            },
        };
        using var document = JsonDocument.Parse(JsonSerializer.Serialize(payload));
        if (requestId <= 0)
        {
            state.Apply(document.RootElement, documentSubmeshCount: 2);
            rejectionReason = string.Empty;
            return true;
        }
        return state.TryApplyResidentUpdate(
            document.RootElement,
            documentSubmeshCount: 2,
            out rejectionReason);
    }

    private static Dictionary<string, object?> PlacementProofRole(Matrix4x4 matrix) => new()
    {
        ["model_matrix"] = MatrixValues(matrix),
        ["world_bounds"] = new Dictionary<string, object?>
        {
            ["min"] = new[] { -10.0f, -10.0f, -10.0f },
            ["max"] = new[] { 10.0f, 10.0f, 10.0f },
        },
    };

    private static Matrix4x4 PlacementProofMatrix(
        Matrix4x4 automaticLinear,
        Vector3 rotationDegrees,
        Vector3 scale,
        Vector3 placementPivot,
        Vector3 sourceAnchor)
    {
        var rotation = rotationDegrees * (MathF.PI / 180.0f);
        var linear = automaticLinear
            * Matrix4x4.CreateScale(scale)
            * Matrix4x4.CreateRotationX(rotation.X)
            * Matrix4x4.CreateRotationY(rotation.Y)
            * Matrix4x4.CreateRotationZ(rotation.Z);
        var matrixTranslation = placementPivot - Vector3.TransformNormal(sourceAnchor, linear);
        linear.M41 = matrixTranslation.X;
        linear.M42 = matrixTranslation.Y;
        linear.M43 = matrixTranslation.Z;
        linear.M44 = 1.0f;
        return linear;
    }

    private static float[] MatrixValues(Matrix4x4 matrix) => new[]
    {
        matrix.M11, matrix.M12, matrix.M13, matrix.M14,
        matrix.M21, matrix.M22, matrix.M23, matrix.M24,
        matrix.M31, matrix.M32, matrix.M33, matrix.M34,
        matrix.M41, matrix.M42, matrix.M43, matrix.M44,
    };

    private static float[] VectorValues(Vector3 value) => new[] { value.X, value.Y, value.Z };

    private static bool MatrixNearlyEqual(Matrix4x4 left, Matrix4x4 right) =>
        MatrixValues(left).Zip(MatrixValues(right)).All(pair => NearlyEqual(pair.First, pair.Second));

    private static bool VectorNearlyEqual(Vector3 left, Vector3 right) =>
        NearlyEqual(left.X, right.X)
        && NearlyEqual(left.Y, right.Y)
        && NearlyEqual(left.Z, right.Z);
}
