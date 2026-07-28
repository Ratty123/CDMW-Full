using System.Numerics;
using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class NetSceneState
{
    private const float DefaultArchivePreviewFitRelativeZoom = 0.9f;

    private sealed record PlacementSnapshot(
        Vector3 Translation,
        Vector3 RotationDegrees,
        Vector3 Scale,
        Matrix4x4 EditableModelMatrix,
        Vector3 PlacementPivot,
        Vector3 SourceAnchor);

    private readonly HashSet<int> _presentationHiddenSubmeshes = new();
    private readonly Dictionary<int, Matrix4x4> _presentationPartMatrices = new();
    private readonly Dictionary<int, string> _presentationPartRoles = new();
    private PlacementSnapshot? _acknowledgedPlacement;
    private long _provisionalPlacementRequestId;
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
    public Vector3 PlacementPivot { get; private set; }
    public Vector3 AlignmentSourceAnchor { get; private set; }
    public bool HasAlignmentSourceAnchor { get; private set; }
    public Vector3? SelectionPivot { get; private set; }
    public string HoveredGizmoHandle { get; private set; } = string.Empty;
    public string ActiveGizmoHandle { get; private set; } = string.Empty;
    public float SceneExtent { get; private set; } = 2.0f;
    public string SessionId { get; private set; } = string.Empty;
    public string SourceIdentity { get; private set; } = string.Empty;
    public string ArchivePreviewSourcePath { get; private set; } = string.Empty;
    public bool ArchivePreviewTexturesEnabled { get; private set; }
    public bool HasArchivePreviewCamera { get; private set; }
    public float ArchivePreviewYawDegrees { get; private set; }
    public float ArchivePreviewPitchDegrees { get; private set; }
    public bool ArchivePreviewFitToView { get; private set; }
    public float ArchivePreviewFitRelativeZoom { get; private set; } = DefaultArchivePreviewFitRelativeZoom;
    public long SceneGeneration { get; private set; }
    public long PresentationGeneration { get; private set; }
    public long LastRequestId { get; private set; }
    public Matrix4x4 EditableModelMatrix { get; private set; } = Matrix4x4.Identity;
    public Matrix4x4 ReferenceModelMatrix { get; private set; } = Matrix4x4.Identity;
    public Vector3 EditableBoundsMinimum { get; private set; } = -Vector3.One;
    public Vector3 EditableBoundsMaximum { get; private set; } = Vector3.One;
    public Vector3 ReferenceBoundsMinimum { get; private set; } = -Vector3.One;
    public Vector3 ReferenceBoundsMaximum { get; private set; } = Vector3.One;
    public Vector3 FramingBoundsMinimum { get; private set; } = -Vector3.One;
    public Vector3 FramingBoundsMaximum { get; private set; } = Vector3.One;
    public Vector3 GroundOrigin { get; private set; }
    public Vector3 GroundNormal { get; private set; } = Vector3.UnitY;
    public bool HasAuthoritativeFrame { get; private set; }
    public bool HasProvisionalPlacement => _acknowledgedPlacement is not null;
    public NetPreviewOverlayState PreviewOverlays { get; private set; } = new();

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
        SessionId = JsonText(root, "session_id", SessionId).Trim();
        SourceIdentity = JsonText(root, "source_identity", SourceIdentity).Trim();
        if (root.TryGetProperty("archive_preview", out var archivePreview)
            && archivePreview.ValueKind == JsonValueKind.Object)
        {
            ArchivePreviewSourcePath = JsonText(archivePreview, "source_path", ArchivePreviewSourcePath).Trim();
            ArchivePreviewTexturesEnabled = JsonBool(
                archivePreview,
                "textures_enabled",
                ArchivePreviewTexturesEnabled);
            if (archivePreview.TryGetProperty("camera", out var camera)
                && camera.ValueKind == JsonValueKind.Object)
            {
                ArchivePreviewYawDegrees = Math.Clamp(
                    JsonFloat(camera, "yaw_degrees", ArchivePreviewYawDegrees),
                    -360.0f,
                    360.0f);
                ArchivePreviewPitchDegrees = Math.Clamp(
                    JsonFloat(camera, "pitch_degrees", ArchivePreviewPitchDegrees),
                    -89.0f,
                    89.0f);
                ArchivePreviewFitToView = JsonBool(camera, "fit_to_view", true);
                ArchivePreviewFitRelativeZoom = Math.Clamp(
                    JsonFloat(camera, "fit_relative_zoom", ArchivePreviewFitRelativeZoom),
                    0.1f,
                    64.0f);
                HasArchivePreviewCamera = true;
            }
        }
        SceneGeneration = Math.Max(SceneGeneration, JsonLong(root, "scene_generation", SceneGeneration));
        EditableSubmeshCount = Math.Clamp(JsonInt(root, "editable_submesh_count", EditableSubmeshCount), 0, documentSubmeshCount);
        ReferenceSubmeshCount = Math.Clamp(JsonInt(root, "reference_submesh_count", documentSubmeshCount - EditableSubmeshCount), 0, documentSubmeshCount - EditableSubmeshCount);
        InteractionMode = NormalizeInteraction(JsonText(root, "interaction_mode", InteractionMode));
        ComparisonMode = EffectiveComparisonMode(
            JsonText(root, "comparison_mode", ComparisonMode),
            InteractionMode);
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
        if (root.TryGetProperty("automatic_alignment", out var alignment)
            && alignment.ValueKind == JsonValueKind.Object
            && JsonOptionalVector(alignment, "source_anchor") is Vector3 sourceAnchor)
        {
            AlignmentSourceAnchor = sourceAnchor;
            HasAlignmentSourceAnchor = true;
        }
        PlacementPivot = JsonVector(root, "placement_pivot", PlacementPivot);
        SelectionPivot = JsonOptionalVector(root, "selection_pivot");
        if (root.TryGetProperty("ground_plane", out var ground) && ground.ValueKind == JsonValueKind.Object)
        {
            GroundOrigin = JsonVector(ground, "origin", GroundOrigin);
            GroundNormal = JsonVector(ground, "normal", GroundNormal);
        }
        if (root.TryGetProperty("roles", out var roles) && roles.ValueKind == JsonValueKind.Object)
        {
            if (roles.TryGetProperty("editable", out var editable) && editable.ValueKind == JsonValueKind.Object)
            {
                EditableModelMatrix = JsonMatrix(editable, "model_matrix", EditableModelMatrix);
                (EditableBoundsMinimum, EditableBoundsMaximum) = JsonWorldBounds(
                    editable, EditableBoundsMinimum, EditableBoundsMaximum);
                HasAuthoritativeFrame = true;
            }
            if (roles.TryGetProperty("reference", out var reference) && reference.ValueKind == JsonValueKind.Object)
            {
                ReferenceModelMatrix = JsonMatrix(reference, "model_matrix", ReferenceModelMatrix);
                (ReferenceBoundsMinimum, ReferenceBoundsMaximum) = JsonWorldBounds(
                    reference, ReferenceBoundsMinimum, ReferenceBoundsMaximum);
            }
        }
        if (root.TryGetProperty("bounds", out var bounds) && bounds.ValueKind == JsonValueKind.Object)
        {
            var min = JsonVector(bounds, "min", -Vector3.One);
            var max = JsonVector(bounds, "max", Vector3.One);
            FramingBoundsMinimum = min;
            FramingBoundsMaximum = max;
            SceneExtent = Math.Max(0.01f, Math.Max(max.X - min.X, Math.Max(max.Y - min.Y, max.Z - min.Z)));
        }
        PreviewOverlays.ApplySceneMetadata(root);
    }

    public bool TryApplyResidentUpdate(JsonElement root, int documentSubmeshCount, out string rejectionReason)
    {
        rejectionReason = string.Empty;
        var sessionId = JsonText(root, "session_id", string.Empty).Trim();
        var sourceIdentity = JsonText(root, "source_identity", string.Empty).Trim();
        var requestId = JsonLong(root, "request_id", 0);
        var generation = JsonLong(root, "scene_generation", 0);
        if (sessionId.Length == 0 || sourceIdentity.Length == 0 || requestId <= 0 || generation <= 0)
        {
            rejectionReason = "missing_scene_correlation";
            return false;
        }
        if (SessionId.Length > 0 && !string.Equals(SessionId, sessionId, StringComparison.Ordinal))
        {
            rejectionReason = "stale_session";
            return false;
        }
        if (SourceIdentity.Length > 0 && !string.Equals(SourceIdentity, sourceIdentity, StringComparison.Ordinal))
        {
            rejectionReason = "stale_source_identity";
            return false;
        }
        if (generation <= SceneGeneration || requestId <= LastRequestId)
        {
            rejectionReason = "stale_scene_generation";
            return false;
        }
        if (!HasValidAuthoritativeRoles(root))
        {
            rejectionReason = "invalid_scene_frame";
            return false;
        }
        var preserveResidentWorldFrame = HasAuthoritativeFrame
            && string.Equals(SourceIdentity, sourceIdentity, StringComparison.Ordinal);
        var residentGridOrigin = GridOrigin;
        var residentGridSpacing = GridSpacing;
        var provisionalTranslation = Translation;
        var provisionalRotation = RotationDegrees;
        var provisionalScale = Scale;
        var hadProvisionalPlacement = _acknowledgedPlacement is not null;
        var candidate = Clone();
        candidate.Apply(root, documentSubmeshCount);
        candidate.LastRequestId = requestId;
        CopyFrom(candidate);
        if (preserveResidentWorldFrame)
        {
            GridOrigin = residentGridOrigin;
            GridSpacing = residentGridSpacing;
        }
        if (hadProvisionalPlacement)
        {
            _acknowledgedPlacement = new PlacementSnapshot(
                candidate.Translation,
                candidate.RotationDegrees,
                candidate.Scale,
                candidate.EditableModelMatrix,
                candidate.PlacementPivot,
                candidate.ResolvedAlignmentSourceAnchor());
            Translation = provisionalTranslation;
            RotationDegrees = provisionalRotation;
            Scale = provisionalScale;
        }
        return true;
    }

    public bool IsEditable(int submeshIndex) => submeshIndex >= 0 && submeshIndex < EditableSubmeshCount;
    public bool IsReference(int submeshIndex) => submeshIndex >= EditableSubmeshCount && submeshIndex < EditableSubmeshCount + ReferenceSubmeshCount;
    public bool IsPresentationVisible(int submeshIndex) => !_presentationHiddenSubmeshes.Contains(submeshIndex);

    /// <summary>
    /// Whether the caller has explicitly hidden this submesh. Separate from
    /// <see cref="IsVisible"/> because that also folds in the comparison mode,
    /// and a pane showing one side of a comparison must still honour an explicit
    /// hide.
    /// </summary>
    public bool IsHiddenByPresentation(int submeshIndex) =>
        _presentationHiddenSubmeshes.Contains(submeshIndex);

    public bool IsVisible(int submeshIndex)
    {
        if (!IsPresentationVisible(submeshIndex))
        {
            return false;
        }
        return ComparisonMode switch
        {
            "original_only" => IsReference(submeshIndex),
            "replacement_only" => IsEditable(submeshIndex),
            _ => IsEditable(submeshIndex) || IsReference(submeshIndex),
        };
    }

    public void SetComparisonMode(string value)
    {
        var next = EffectiveComparisonMode(value, InteractionMode);
        if (string.Equals(next, ComparisonMode, StringComparison.Ordinal))
        {
            return;
        }
        ComparisonMode = next;
        PresentationGeneration++;
    }

    public void SetInteractionMode(string value)
    {
        var next = NormalizeInteraction(value);
        if (string.Equals(next, InteractionMode, StringComparison.Ordinal))
        {
            return;
        }
        InteractionMode = next;
        ComparisonMode = EffectiveComparisonMode(ComparisonMode, InteractionMode);
        PresentationGeneration++;
    }
    public void SetPresentationOverlayVisibility(bool gridVisible, bool gizmoVisible)
    {
        if (GridVisible == gridVisible && GizmoVisible == gizmoVisible)
        {
            return;
        }
        GridVisible = gridVisible;
        GizmoVisible = gizmoVisible;
        PresentationGeneration++;
    }
    public void SetPresentationHiddenSubmeshes(IEnumerable<int> indices)
    {
        _presentationHiddenSubmeshes.Clear();
        foreach (var index in indices.Where(index => index >= 0))
        {
            _presentationHiddenSubmeshes.Add(index);
        }
        PresentationGeneration++;
    }
    public void SetPresentationPartMatrices(
        IReadOnlyDictionary<int, Matrix4x4> matrices,
        IReadOnlyDictionary<int, string> roles)
    {
        _presentationPartMatrices.Clear();
        foreach (var pair in matrices.Where(pair => pair.Key >= 0 && IsEditable(pair.Key)))
        {
            _presentationPartMatrices[pair.Key] = pair.Value;
        }
        _presentationPartRoles.Clear();
        foreach (var pair in roles.Where(pair => pair.Key >= 0 && IsEditable(pair.Key)))
        {
            _presentationPartRoles[pair.Key] = pair.Value;
        }
        PresentationGeneration++;
    }

    public void RemapTopologyState(
        IReadOnlyDictionary<int, int> topologySources,
        int editableSubmeshCount,
        int documentSubmeshCount)
    {
        var previousHidden = new HashSet<int>(_presentationHiddenSubmeshes);
        var previousMatrices = new Dictionary<int, Matrix4x4>(_presentationPartMatrices);
        var previousRoles = new Dictionary<int, string>(_presentationPartRoles);
        var totalCount = Math.Max(0, documentSubmeshCount);
        var nextEditableCount = Math.Clamp(editableSubmeshCount, 0, totalCount);

        _presentationHiddenSubmeshes.Clear();
        _presentationPartMatrices.Clear();
        _presentationPartRoles.Clear();
        for (var targetIndex = 0; targetIndex < totalCount; targetIndex++)
        {
            var sourceIndex = topologySources.TryGetValue(targetIndex, out var source)
                ? source
                : targetIndex;
            if (sourceIndex < 0)
            {
                continue;
            }
            if (previousHidden.Contains(sourceIndex))
            {
                _presentationHiddenSubmeshes.Add(targetIndex);
            }
            if (targetIndex >= nextEditableCount)
            {
                continue;
            }
            if (previousMatrices.TryGetValue(sourceIndex, out var matrix))
            {
                _presentationPartMatrices[targetIndex] = matrix;
            }
            if (previousRoles.TryGetValue(sourceIndex, out var role))
            {
                _presentationPartRoles[targetIndex] = role;
            }
        }
        EditableSubmeshCount = nextEditableCount;
        ReferenceSubmeshCount = totalCount - nextEditableCount;
        PresentationGeneration++;
    }

    public void SetGizmoTool(string value) => GizmoTool = NormalizeGizmo(value);
    public void SetHoveredGizmoHandle(string value) => HoveredGizmoHandle = NormalizeGizmoHandle(value);
    public void SetActiveGizmoHandle(string value) => ActiveGizmoHandle = NormalizeGizmoHandle(value);

    public Vector3 EffectiveGizmoPivot()
    {
        return EffectiveGizmoPivot(includeSideBySideOffset: true);
    }

    public Vector3 RoleViewGizmoPivot()
    {
        return EffectiveGizmoPivot(includeSideBySideOffset: false);
    }

    private Vector3 EffectiveGizmoPivot(bool includeSideBySideOffset)
    {
        if (HasAuthoritativeFrame)
        {
            var authoritative = InteractionMode == "mesh_edit"
                ? SelectionPivot ?? ((EditableBoundsMinimum + EditableBoundsMaximum) * 0.5f)
                : ProvisionalPlacementPivot();
            return Vector3.Transform(authoritative, EditablePresentationMatrix(includeSideBySideOffset));
        }
        var legacyPivot = InteractionMode == "mesh_edit" && SelectionPivot is Vector3 selection
            ? selection
            : PlacementPivot;
        return Vector3.Transform(legacyPivot, EditableAuthorityMatrix());
    }

    public void ApplyConstrainedTranslation(Vector3 start, Vector3 delta) => Translation = start + delta;

    public void ApplyConstrainedRotation(Vector3 start, int axis, float degrees)
    {
        var value = start;
        if (axis == 0) value.X += degrees;
        else if (axis == 1) value.Y += degrees;
        else value.Z += degrees;
        RotationDegrees = value;
    }

    public void ApplyConstrainedScale(Vector3 start, int axis, float factor)
    {
        var value = start;
        var safeFactor = Math.Clamp(factor, 0.001f, 1000.0f);
        if (axis < 0)
        {
            value *= safeFactor;
        }
        else if (axis == 0) value.X *= safeFactor;
        else if (axis == 1) value.Y *= safeFactor;
        else value.Z *= safeFactor;
        Scale = ClampScale(value);
    }

    public void BeginProvisionalPlacement()
    {
        _acknowledgedPlacement ??= new PlacementSnapshot(
            Translation,
            RotationDegrees,
            Scale,
            EditableModelMatrix,
            PlacementPivot,
            ResolvedAlignmentSourceAnchor());
    }

    public void TrackProvisionalPlacementRequest(long requestId)
    {
        if (requestId <= 0 || requestId < _provisionalPlacementRequestId)
        {
            return;
        }
        BeginProvisionalPlacement();
        _provisionalPlacementRequestId = requestId;
    }

    public bool RejectProvisionalPlacement(long requestId)
    {
        if (requestId <= 0 || requestId != _provisionalPlacementRequestId || _acknowledgedPlacement is null)
        {
            return false;
        }
        Translation = _acknowledgedPlacement.Translation;
        RotationDegrees = _acknowledgedPlacement.RotationDegrees;
        Scale = _acknowledgedPlacement.Scale;
        ClearProvisionalPlacement();
        return true;
    }

    public bool AcceptAuthoritativePlacementFrame()
    {
        if (_acknowledgedPlacement is null)
        {
            return true;
        }
        if (!NearlyEqual(Translation, _acknowledgedPlacement.Translation)
            || !NearlyEqual(RotationDegrees, _acknowledgedPlacement.RotationDegrees)
            || !NearlyEqual(Scale, _acknowledgedPlacement.Scale))
        {
            return false;
        }
        ClearProvisionalPlacement();
        return true;
    }

    public void ForceAcceptAuthoritativePlacementFrame()
    {
        if (_acknowledgedPlacement is not null)
        {
            Translation = _acknowledgedPlacement.Translation;
            RotationDegrees = _acknowledgedPlacement.RotationDegrees;
            Scale = _acknowledgedPlacement.Scale;
        }
        ClearProvisionalPlacement();
    }

    public void ResetProvisionalPlacement()
    {
        if (_acknowledgedPlacement is not null)
        {
            Translation = _acknowledgedPlacement.Translation;
            RotationDegrees = _acknowledgedPlacement.RotationDegrees;
            Scale = _acknowledgedPlacement.Scale;
        }
        ClearProvisionalPlacement();
    }

    private void ClearProvisionalPlacement()
    {
        _acknowledgedPlacement = null;
        _provisionalPlacementRequestId = 0;
    }

    public Dictionary<string, object?> PlacementPayload() => new()
    {
        ["translation"] = new[] { Translation.X, Translation.Y, Translation.Z },
        ["rotation_degrees"] = new[] { RotationDegrees.X, RotationDegrees.Y, RotationDegrees.Z },
        ["scale"] = new[] { Scale.X, Scale.Y, Scale.Z },
    };

    public Matrix4x4 ModelMatrix(int submeshIndex) => ModelMatrix(submeshIndex, includeSideBySideOffset: true);

    public Matrix4x4 RoleViewModelMatrix(int submeshIndex) => ModelMatrix(submeshIndex, includeSideBySideOffset: false);

    private Matrix4x4 ModelMatrix(int submeshIndex, bool includeSideBySideOffset)
    {
        if (IsReference(submeshIndex))
        {
            var authority = HasAuthoritativeFrame ? ReferenceModelMatrix : Matrix4x4.Identity;
            return includeSideBySideOffset && ComparisonMode == "side_by_side"
                ? authority * Matrix4x4.CreateTranslation(-SceneExtent * 0.6f, 0.0f, 0.0f)
                : authority;
        }
        if (!IsEditable(submeshIndex)) return Matrix4x4.Identity;
        if (HasAuthoritativeFrame)
        {
            var part = _presentationPartMatrices.GetValueOrDefault(submeshIndex, Matrix4x4.Identity);
            return part * ProvisionalEditableModelMatrix() * EditablePresentationMatrix(includeSideBySideOffset);
        }
        var rotation = RotationDegrees * (MathF.PI / 180.0f);
        var placement = Matrix4x4.CreateScale(Scale)
            * Matrix4x4.CreateFromYawPitchRoll(rotation.Y, rotation.X, rotation.Z)
            * Matrix4x4.CreateTranslation(Translation);
        var partPlacement = _presentationPartMatrices.GetValueOrDefault(submeshIndex, Matrix4x4.Identity);
        return includeSideBySideOffset && ComparisonMode == "side_by_side"
            ? partPlacement * placement * Matrix4x4.CreateTranslation(SceneExtent * 0.6f, 0.0f, 0.0f)
            : partPlacement * placement;
    }

    private Matrix4x4 EditableAuthorityMatrix()
    {
        var rotation = RotationDegrees * (MathF.PI / 180.0f);
        return Matrix4x4.CreateScale(Scale)
            * Matrix4x4.CreateFromYawPitchRoll(rotation.Y, rotation.X, rotation.Z)
            * Matrix4x4.CreateTranslation(Translation);
    }

    private Vector3 ProvisionalPlacementPivot() => _acknowledgedPlacement is null
        ? PlacementPivot
        : _acknowledgedPlacement.PlacementPivot
            + Translation
            - _acknowledgedPlacement.Translation;

    private Matrix4x4 ProvisionalEditableModelMatrix()
    {
        if (_acknowledgedPlacement is null)
        {
            return EditableModelMatrix;
        }
        var acknowledgedManual = ManualLinearMatrix(
            _acknowledgedPlacement.RotationDegrees,
            _acknowledgedPlacement.Scale);
        var acknowledgedLinear = LinearOnly(_acknowledgedPlacement.EditableModelMatrix);
        if (!Matrix4x4.Invert(acknowledgedManual, out var inverseAcknowledgedManual))
        {
            return EditableModelMatrix;
        }
        // Scene matrices use row vectors: automatic alignment is followed by
        // manual S/X/Y/Z rotation, while the source anchor must stay at the
        // placement pivot. Rebuild only that manual suffix for live dragging.
        var automaticLinear = acknowledgedLinear * inverseAcknowledgedManual;
        var provisionalLinear = automaticLinear * ManualLinearMatrix(RotationDegrees, Scale);
        var provisionalPivot = _acknowledgedPlacement.PlacementPivot
            - _acknowledgedPlacement.Translation
            + Translation;
        var provisionalTranslation = provisionalPivot
            - Vector3.TransformNormal(_acknowledgedPlacement.SourceAnchor, provisionalLinear);
        return WithTranslation(provisionalLinear, provisionalTranslation);
    }

    private Vector3 ResolvedAlignmentSourceAnchor()
    {
        if (HasAlignmentSourceAnchor)
        {
            return AlignmentSourceAnchor;
        }
        var editableLinear = LinearOnly(EditableModelMatrix);
        return Matrix4x4.Invert(editableLinear, out var inverseEditableLinear)
            ? Vector3.TransformNormal(
                PlacementPivot - EditableModelMatrix.Translation,
                inverseEditableLinear)
            : Vector3.Zero;
    }

    private static Matrix4x4 ManualLinearMatrix(Vector3 rotationDegrees, Vector3 scale)
    {
        var rotation = rotationDegrees * (MathF.PI / 180.0f);
        return Matrix4x4.CreateScale(scale)
            * Matrix4x4.CreateRotationX(rotation.X)
            * Matrix4x4.CreateRotationY(rotation.Y)
            * Matrix4x4.CreateRotationZ(rotation.Z);
    }

    private static Matrix4x4 LinearOnly(Matrix4x4 matrix) => new(
        matrix.M11, matrix.M12, matrix.M13, 0.0f,
        matrix.M21, matrix.M22, matrix.M23, 0.0f,
        matrix.M31, matrix.M32, matrix.M33, 0.0f,
        0.0f, 0.0f, 0.0f, 1.0f);

    private static Matrix4x4 WithTranslation(Matrix4x4 linear, Vector3 translation) => new(
        linear.M11, linear.M12, linear.M13, 0.0f,
        linear.M21, linear.M22, linear.M23, 0.0f,
        linear.M31, linear.M32, linear.M33, 0.0f,
        translation.X, translation.Y, translation.Z, 1.0f);

    private Matrix4x4 EditablePresentationMatrix(bool includeSideBySideOffset) =>
        includeSideBySideOffset && ComparisonMode == "side_by_side"
        ? Matrix4x4.CreateTranslation(SceneExtent * 0.6f, 0.0f, 0.0f)
        : Matrix4x4.Identity;

    private NetSceneState Clone()
    {
        var clone = new NetSceneState();
        clone.CopyFrom(this);
        return clone;
    }

    private void CopyFrom(NetSceneState other)
    {
        EditableSubmeshCount = other.EditableSubmeshCount;
        ReferenceSubmeshCount = other.ReferenceSubmeshCount;
        ComparisonMode = other.ComparisonMode;
        InteractionMode = other.InteractionMode;
        GridVisible = other.GridVisible;
        GridOrigin = other.GridOrigin;
        GridSpacing = other.GridSpacing;
        GizmoTool = other.GizmoTool;
        GizmoVisible = other.GizmoVisible;
        Translation = other.Translation;
        RotationDegrees = other.RotationDegrees;
        Scale = other.Scale;
        PlacementPivot = other.PlacementPivot;
        AlignmentSourceAnchor = other.AlignmentSourceAnchor;
        HasAlignmentSourceAnchor = other.HasAlignmentSourceAnchor;
        SelectionPivot = other.SelectionPivot;
        HoveredGizmoHandle = other.HoveredGizmoHandle;
        ActiveGizmoHandle = other.ActiveGizmoHandle;
        SceneExtent = other.SceneExtent;
        SessionId = other.SessionId;
        SourceIdentity = other.SourceIdentity;
        ArchivePreviewSourcePath = other.ArchivePreviewSourcePath;
        ArchivePreviewTexturesEnabled = other.ArchivePreviewTexturesEnabled;
        HasArchivePreviewCamera = other.HasArchivePreviewCamera;
        ArchivePreviewYawDegrees = other.ArchivePreviewYawDegrees;
        ArchivePreviewPitchDegrees = other.ArchivePreviewPitchDegrees;
        ArchivePreviewFitToView = other.ArchivePreviewFitToView;
        ArchivePreviewFitRelativeZoom = other.ArchivePreviewFitRelativeZoom;
        SceneGeneration = other.SceneGeneration;
        PresentationGeneration = other.PresentationGeneration;
        LastRequestId = other.LastRequestId;
        EditableModelMatrix = other.EditableModelMatrix;
        ReferenceModelMatrix = other.ReferenceModelMatrix;
        EditableBoundsMinimum = other.EditableBoundsMinimum;
        EditableBoundsMaximum = other.EditableBoundsMaximum;
        ReferenceBoundsMinimum = other.ReferenceBoundsMinimum;
        ReferenceBoundsMaximum = other.ReferenceBoundsMaximum;
        FramingBoundsMinimum = other.FramingBoundsMinimum;
        FramingBoundsMaximum = other.FramingBoundsMaximum;
        GroundOrigin = other.GroundOrigin;
        GroundNormal = other.GroundNormal;
        HasAuthoritativeFrame = other.HasAuthoritativeFrame;
        PreviewOverlays = other.PreviewOverlays.Clone();
        _presentationHiddenSubmeshes.Clear();
        _presentationHiddenSubmeshes.UnionWith(other._presentationHiddenSubmeshes);
        _presentationPartMatrices.Clear();
        foreach (var pair in other._presentationPartMatrices)
        {
            _presentationPartMatrices[pair.Key] = pair.Value;
        }
        _presentationPartRoles.Clear();
        foreach (var pair in other._presentationPartRoles)
        {
            _presentationPartRoles[pair.Key] = pair.Value;
        }
    }

    private static bool HasValidAuthoritativeRoles(JsonElement root)
    {
        if (!root.TryGetProperty("roles", out var roles) || roles.ValueKind != JsonValueKind.Object)
        {
            return false;
        }
        foreach (var roleName in new[] { "editable", "reference" })
        {
            if (!roles.TryGetProperty(roleName, out var role) || role.ValueKind != JsonValueKind.Object)
            {
                return false;
            }
            if (!TryJsonMatrix(role, "model_matrix", out _))
            {
                return false;
            }
            if (!role.TryGetProperty("world_bounds", out var bounds)
                || bounds.ValueKind != JsonValueKind.Object
                || JsonOptionalVector(bounds, "min") is not Vector3 minimum
                || JsonOptionalVector(bounds, "max") is not Vector3 maximum
                || minimum.X > maximum.X
                || minimum.Y > maximum.Y
                || minimum.Z > maximum.Z)
            {
                return false;
            }
        }
        return true;
    }

    private static (Vector3 Minimum, Vector3 Maximum) JsonWorldBounds(
        JsonElement role,
        Vector3 fallbackMinimum,
        Vector3 fallbackMaximum)
    {
        if (!role.TryGetProperty("world_bounds", out var bounds) || bounds.ValueKind != JsonValueKind.Object)
        {
            return (fallbackMinimum, fallbackMaximum);
        }
        return (
            JsonVector(bounds, "min", fallbackMinimum),
            JsonVector(bounds, "max", fallbackMaximum));
    }

    private static Matrix4x4 JsonMatrix(JsonElement root, string name, Matrix4x4 fallback) =>
        TryJsonMatrix(root, name, out var matrix) ? matrix : fallback;

    private static bool TryJsonMatrix(JsonElement root, string name, out Matrix4x4 matrix)
    {
        matrix = Matrix4x4.Identity;
        if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return false;
        }
        var values = value.EnumerateArray()
            .Select(item => item.TryGetSingle(out var number) && float.IsFinite(number) ? number : float.NaN)
            .ToArray();
        if (values.Length != 16 || values.Any(number => !float.IsFinite(number)))
        {
            return false;
        }
        matrix = new Matrix4x4(
            values[0], values[1], values[2], values[3],
            values[4], values[5], values[6], values[7],
            values[8], values[9], values[10], values[11],
            values[12], values[13], values[14], values[15]);
        return true;
    }

    private static string NormalizeComparison(string value) => value.Trim().ToLowerInvariant() switch
    {
        "side_by_side" => "side_by_side",
        "overlay" or "ghost" => "overlay",
        "original_only" or "source" => "original_only",
        _ => "replacement_only",
    };
    internal static string EffectiveComparisonMode(string value, string interactionMode) =>
        NormalizeInteraction(interactionMode) switch
        {
            "mesh_edit" => "replacement_only",
            _ => NormalizeComparison(value),
        };
    private static string NormalizeInteraction(string value) => value.Trim().ToLowerInvariant() == "mesh_edit" ? "mesh_edit" : "placement";
    private static string NormalizeGizmo(string value) => value.Trim().ToLowerInvariant() switch { "rotate" => "rotate", "scale" => "scale", _ => "move" };
    private static string NormalizeGizmoHandle(string value) => value.Trim().ToLowerInvariant() switch
    {
        "x" or "y" or "z" or "xy" or "xz" or "yz" or "center" => value.Trim().ToLowerInvariant(),
        _ => string.Empty,
    };
    private static bool NearlyEqual(Vector3 left, Vector3 right) =>
        NearlyEqual(left.X, right.X)
        && NearlyEqual(left.Y, right.Y)
        && NearlyEqual(left.Z, right.Z);
    private static bool NearlyEqual(float left, float right) =>
        Math.Abs(left - right) <= 0.0001f * Math.Max(1.0f, Math.Max(Math.Abs(left), Math.Abs(right)));
    private static Vector3 ClampScale(Vector3 value) => new(Math.Clamp(value.X, 0.001f, 100.0f), Math.Clamp(value.Y, 0.001f, 100.0f), Math.Clamp(value.Z, 0.001f, 100.0f));
    private static int JsonInt(JsonElement root, string name, int fallback) => root.TryGetProperty(name, out var value) && value.TryGetInt32(out var result) ? result : fallback;
    private static long JsonLong(JsonElement root, string name, long fallback) => root.TryGetProperty(name, out var value) && value.TryGetInt64(out var result) ? result : fallback;
    private static float JsonFloat(JsonElement root, string name, float fallback) => root.TryGetProperty(name, out var value) && value.TryGetSingle(out var result) && float.IsFinite(result) ? result : fallback;
    private static bool JsonBool(JsonElement root, string name, bool fallback) => root.TryGetProperty(name, out var value) && value.ValueKind is JsonValueKind.True or JsonValueKind.False ? value.GetBoolean() : fallback;
    private static string JsonText(JsonElement root, string name, string fallback) => root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? fallback : fallback;
    private static Vector3 JsonVector(JsonElement root, string name, Vector3 fallback)
    {
        if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array) return fallback;
        var values = value.EnumerateArray().Take(3).Select(item => item.TryGetSingle(out var number) && float.IsFinite(number) ? number : 0.0f).ToArray();
        return values.Length == 3 ? new Vector3(values[0], values[1], values[2]) : fallback;
    }
    private static Vector3? JsonOptionalVector(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array) return null;
        var values = value.EnumerateArray().Take(3).Select(item => item.TryGetSingle(out var number) && float.IsFinite(number) ? number : float.NaN).ToArray();
        return values.Length == 3 && values.All(float.IsFinite)
            ? new Vector3(values[0], values[1], values[2])
            : null;
    }
}
