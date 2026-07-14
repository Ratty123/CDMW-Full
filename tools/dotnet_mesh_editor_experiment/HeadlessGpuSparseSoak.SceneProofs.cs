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
        return new Dictionary<string, object?>
        {
            ["ok"] = rows.All(row => (bool)row["ok"]!)
                && NetSceneState.EffectiveComparisonMode("side_by_side", "mesh_edit") == "replacement_only"
                && NetSceneState.EffectiveComparisonMode("original_only", "mesh_edit") == "replacement_only",
            ["modes"] = rows,
            ["mesh_edit_side_by_side_resolved"] = NetSceneState.EffectiveComparisonMode("side_by_side", "mesh_edit"),
            ["mesh_edit_original_only_resolved"] = NetSceneState.EffectiveComparisonMode("original_only", "mesh_edit"),
        };
    }

    private static Dictionary<string, object?> CameraZoomProof()
    {
        const float fitZoom = 0.19f;
        var zoomedIn = CameraZoomPolicy.ApplyWheelDelta(fitZoom, fitZoom, 120);
        var restored = CameraZoomPolicy.ApplyWheelDelta(zoomedIn, fitZoom, -120);
        var zoomedOut = CameraZoomPolicy.ApplyWheelDelta(fitZoom, fitZoom, -120);
        var minimum = CameraZoomPolicy.MinimumZoom(fitZoom);
        var reciprocalError = Math.Abs(restored - fitZoom);
        return new Dictionary<string, object?>
        {
            ["ok"] = reciprocalError <= 0.00001f
                && zoomedOut < fitZoom
                && minimum < fitZoom,
            ["fit_zoom"] = fitZoom,
            ["zoomed_in"] = zoomedIn,
            ["restored"] = restored,
            ["zoomed_out"] = zoomedOut,
            ["minimum"] = minimum,
            ["reciprocal_error"] = reciprocalError,
            ["shared_interaction_modes"] = new[] { "placement", "mesh_edit" },
        };
    }

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
