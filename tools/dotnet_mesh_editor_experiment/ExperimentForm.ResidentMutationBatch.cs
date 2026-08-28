using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private const string ResidentMutationBatchCapability = "resident_mutation_batch_v3";
    private readonly ResidentMutationResultLedger _residentMutationLedger = new(256);

    internal sealed record ResidentMutationSelection(
        Dictionary<int, HashSet<int>> Vertices,
        Dictionary<int, HashSet<int>> Faces,
        Dictionary<int, HashSet<(int A, int B)>> Edges,
        HashSet<int> Sources);

    internal sealed record PreparedResidentMutationBatch(
        string Action,
        IReadOnlyList<PreviewVertexGroup> VertexGroups,
        PreviewTriangleUpdatePlan? TopologyPlan,
        NetMaterialParameterUpdate? MaterialUpdate,
        ResidentMutationSelection? Selection,
        IReadOnlyList<int> AffectedSubmeshes,
        int? FinalSubmeshCount);

    private sealed record StagedResidentMutationBatch(
        ObjDocument Document,
        NetMaterialSet Materials,
        NetSceneState Scene,
        ResidentMutationSelection? Selection,
        IReadOnlyDictionary<int, MeshVertexChannelChanges> VertexChanges,
        NetMaterialParameterUpdate? MaterialUpdate,
        int[] AffectedSubmeshes,
        Dictionary<int, int> MaterialSources,
        bool TopologyChanged,
        bool ReplaceAllTopology,
        int EditableSubmeshCount);

    internal static bool TryPrepareResidentMutationBatchPayload(
        JsonElement root,
        out PreparedResidentMutationBatch? prepared)
    {
        prepared = null;
        var action = JsonString(root, "action").Trim();
        if (action.Length == 0)
        {
            action = JsonString(root, "command").Trim();
        }
        if (action.Length == 0)
        {
            return false;
        }

        IReadOnlyList<PreviewVertexGroup> vertexGroups = Array.Empty<PreviewVertexGroup>();
        if (root.TryGetProperty("vertex_updates", out var vertexUpdates))
        {
            if (vertexUpdates.ValueKind != JsonValueKind.Array
                || !TryParsePreviewVertexGroups(vertexUpdates, out vertexGroups))
            {
                return false;
            }
        }

        PreviewTriangleUpdatePlan? topologyPlan = null;
        if (root.TryGetProperty("topology_update", out var topologyUpdate))
        {
            if (topologyUpdate.ValueKind != JsonValueKind.Object
                || !topologyUpdate.TryGetProperty("triangle_groups", out var triangleGroups)
                || triangleGroups.ValueKind != JsonValueKind.Array
                || !TryPreparePreviewTriangleGroups(topologyUpdate, triangleGroups, out topologyPlan)
                || topologyPlan is null)
            {
                return false;
            }
            if (root.TryGetProperty("final_submesh_count", out var finalCount)
                && finalCount.ValueKind == JsonValueKind.Number
                && finalCount.TryGetInt32(out var finalCountValue))
            {
                topologyPlan = topologyPlan with
                {
                    HasExplicitFinalCount = true,
                    FinalCount = finalCountValue,
                };
            }
        }

        NetMaterialParameterUpdate? materialUpdate = null;
        if (root.TryGetProperty("material_updates", out var materialUpdates))
        {
            if (materialUpdates.ValueKind != JsonValueKind.Array)
            {
                return false;
            }
            if (materialUpdates.GetArrayLength() > 0)
            {
                try
                {
                    materialUpdate = NetMaterialSet.ParseResidentMutationParameterUpdate(
                        materialUpdates,
                        JsonString(root, "session_id").Trim(),
                        Math.Max(0, JsonLongValue(root, "target_revision")),
                        Math.Max(0, JsonLongValue(root, "request_id")));
                }
                catch (InvalidDataException)
                {
                    return false;
                }
            }
        }

        ResidentMutationSelection? selection = null;
        if (root.TryGetProperty("selection_update", out var selectionUpdate))
        {
            if (selectionUpdate.ValueKind != JsonValueKind.Object)
            {
                return false;
            }
            var selectionRoot = selectionUpdate.TryGetProperty("selection", out var nestedSelection)
                ? nestedSelection
                : selectionUpdate;
            if (selectionRoot.ValueKind != JsonValueKind.Object)
            {
                return false;
            }
            var edges = JsonEdgeSelectionMap(selectionRoot, "edges_by_submesh");
            if (edges.Count == 0)
            {
                edges = JsonEdgeDescriptorSelectionMap(selectionRoot, "edge_descriptors");
            }
            selection = new ResidentMutationSelection(
                JsonSelectionMap(selectionRoot, "vertices_by_submesh"),
                JsonSelectionMap(selectionRoot, "faces_by_submesh"),
                edges,
                JsonIntSet(selectionRoot, "source_indices"));
        }

        var finalSubmeshCount = root.TryGetProperty("final_submesh_count", out var finalSubmeshValue)
            && finalSubmeshValue.ValueKind == JsonValueKind.Number
            && finalSubmeshValue.TryGetInt32(out var parsedFinalSubmeshCount)
                ? parsedFinalSubmeshCount
                : (int?)null;
        var affected = JsonIntValues(root, "affected_submesh_indices");
        if (vertexGroups.Count == 0
            && topologyPlan is null
            && materialUpdate is null
            && selection is null)
        {
            return false;
        }
        prepared = new PreparedResidentMutationBatch(
            action,
            vertexGroups,
            topologyPlan,
            materialUpdate,
            selection,
            affected,
            finalSubmeshCount);
        return true;
    }

    private void ApplyResidentMutationBatch(
        JsonElement root,
        PreparedResidentMutationBatch? prepared,
        bool payloadPrepared)
    {
        var cacheKey = ResidentMutationCacheKey(root);
        if (cacheKey.Length > 0 && _residentMutationLedger.TryGet(cacheKey, out var cached))
        {
            if (!string.Equals(
                    cached.PayloadSignature,
                    ResidentMutationPayloadSignature(root),
                    StringComparison.Ordinal))
            {
                WriteResidentMutationBatchAck(
                    root,
                    new ResidentMutationResult(
                        "rejected",
                        "request_id_payload_mismatch",
                        Math.Max(0, JsonLongValue(root, "base_revision")),
                        Math.Max(0, JsonLongValue(root, "target_revision")),
                        _lastAppliedEditRevision,
                        0,
                        ResidentMutationPayloadSignature(root)),
                    duplicate: false);
                return;
            }
            WriteResidentMutationBatchAck(root, cached, duplicate: true);
            return;
        }
        if (!TryValidateResidentMutationAuthority(root, out var authorityReason))
        {
            RejectResidentMutation(root, cacheKey, authorityReason);
            return;
        }
        if (!payloadPrepared)
        {
            payloadPrepared = TryPrepareResidentMutationBatchPayload(root, out prepared);
        }
        if (!payloadPrepared || prepared is null)
        {
            RejectResidentMutation(root, cacheKey, "invalid_payload");
            return;
        }
        if (!TryStageResidentMutationBatch(prepared, out var staged, out var stageReason)
            || staged is null)
        {
            RejectResidentMutation(root, cacheKey, stageReason);
            return;
        }
        CommitResidentMutationBatch(root, cacheKey, staged);
    }

    private bool TryValidateResidentMutationAuthority(JsonElement root, out string reason)
    {
        reason = ResidentMutationAuthorityReason(
            root,
            _residentMaterialSessionId,
            _residentProcessGeneration,
            _lastAppliedEditRevision);
        return reason.Length == 0;
    }

    internal static string ResidentMutationAuthorityReason(
        JsonElement root,
        string currentSessionId,
        long currentProcessGeneration,
        long currentRevision)
    {
        var sessionId = JsonString(root, "session_id").Trim();
        var processGeneration = JsonLongValue(root, "process_generation");
        var requestId = JsonLongValue(root, "request_id");
        var protocolVersion = JsonLongValue(root, "protocol_version");
        var baseRevision = JsonLongValue(root, "base_revision");
        var targetRevision = JsonLongValue(root, "target_revision");
        if (sessionId.Length == 0 || !string.Equals(sessionId, currentSessionId, StringComparison.Ordinal))
        {
            return "session_mismatch";
        }
        if (processGeneration <= 0 || processGeneration != currentProcessGeneration)
        {
            return "stale_process_generation";
        }
        if (requestId <= 0)
        {
            return "missing_request_id";
        }
        if (protocolVersion < 3)
        {
            return "unsupported_protocol_version";
        }
        if (baseRevision < 0 || targetRevision <= baseRevision)
        {
            return "invalid_revision_range";
        }
        if (targetRevision <= currentRevision)
        {
            return "stale_revision";
        }
        if (baseRevision != currentRevision)
        {
            return "invalid_base_revision";
        }
        return string.Empty;
    }

    private bool TryStageResidentMutationBatch(
        PreparedResidentMutationBatch prepared,
        out StagedResidentMutationBatch? staged,
        out string reason)
    {
        staged = null;
        reason = "invalid_payload";
        var document = CloneResidentMutationDocument(_document);
        var previousEditableCount = Math.Clamp(
            _scene.EditableSubmeshCount,
            0,
            document.Submeshes.Count);
        var referenceCount = document.Submeshes.Count - previousEditableCount;
        var affected = new HashSet<int>(prepared.AffectedSubmeshes);
        var materialSources = new Dictionary<int, int>();
        var topologySources = new Dictionary<int, int>();
        var topologyAffected = Array.Empty<int>();
        var replaceAll = false;
        var topologyChanged = prepared.TopologyPlan is not null;
        if (prepared.TopologyPlan is not null
            && !TryCommitPreviewTriangleGroups(
                document,
                prepared.TopologyPlan,
                previousEditableCount,
                out _,
                out topologyAffected,
                out materialSources,
                out topologySources,
                out replaceAll))
        {
            reason = "invalid_topology_payload";
            return false;
        }
        if (topologyChanged)
        {
            affected.UnionWith(topologyAffected);
        }
        var editableCount = document.Submeshes.Count - referenceCount;
        if (prepared.FinalSubmeshCount is not null
            && prepared.FinalSubmeshCount.Value != editableCount)
        {
            reason = "final_submesh_count_mismatch";
            return false;
        }
        if (!ValidatePreviewVertexGroups(document, prepared.VertexGroups))
        {
            reason = "invalid_vertex_payload";
            return false;
        }
        var vertexChanges = ApplyResidentMutationVertexGroups(document, prepared.VertexGroups);
        affected.UnionWith(vertexChanges.Keys);

        var materials = _materials.CloneForResidentMutation();
        var scene = _scene.CloneForResidentMutation();
        if (topologyChanged)
        {
            scene.RemapTopologyState(topologySources, editableCount, document.Submeshes.Count);
            _ = materials.RemapTopologyState(materialSources, document.Submeshes.Count);
        }
        var materialUpdate = prepared.MaterialUpdate?.ExpandAllSubmeshes(
            Enumerable.Range(0, editableCount).ToArray());
        if (materialUpdate is not null)
        {
            if (materialUpdate.AffectedSubmeshes.Any(index => index < 0 || index >= editableCount))
            {
                reason = "invalid_material_target";
                return false;
            }
            materials.ApplyParameterUpdate(materialUpdate);
            affected.UnionWith(materialUpdate.AffectedSubmeshes);
        }
        if (prepared.Selection is not null
            && !ValidateResidentMutationSelection(prepared.Selection, document, editableCount))
        {
            reason = "invalid_selection_payload";
            return false;
        }
        var largestValidAffectedIndex = Math.Max(
            _document.Submeshes.Count,
            document.Submeshes.Count);
        if (affected.Any(index => index < 0 || index >= largestValidAffectedIndex))
        {
            reason = "invalid_affected_submesh";
            return false;
        }
        staged = new StagedResidentMutationBatch(
            document,
            materials,
            scene,
            prepared.Selection,
            vertexChanges,
            materialUpdate,
            affected.Order().ToArray(),
            materialSources,
            topologyChanged,
            replaceAll,
            editableCount);
        reason = string.Empty;
        return true;
    }

    private void CommitResidentMutationBatch(
        JsonElement root,
        string cacheKey,
        StagedResidentMutationBatch staged)
    {
        var previousDocument = CloneResidentMutationDocument(_document);
        var previousMaterials = _materials.CaptureState();
        var previousScene = _scene.CloneForResidentMutation();
        var previousSelection = _viewport.CaptureResidentMutationSelection();
        var previousEdited = new HashSet<int>(_editedSubmeshes);
        var previousTopologyDirty = _externalTopologyDirty;
        var previousRevision = _lastAppliedEditRevision;
        var previousRequestedMaterialGeneration = _lastRequestedMaterialParameterGeneration;
        var previousAppliedMaterialGeneration = _lastAppliedMaterialParameterGeneration;
        var previousMaterialAppliedCount = _materialParameterAppliedCount;
        var targetRevision = JsonLongValue(root, "target_revision");
        var requestId = JsonLongValue(root, "request_id");
        try
        {
            CopyResidentMutationDocument(_document, staged.Document);
            _materials.ReplaceState(staged.Materials.CaptureState());
            _scene.ReplaceFromResidentMutation(staged.Scene);
            ApplyResidentMutationRendererCommit(root, staged, requestId, targetRevision);
            _lastAppliedEditRevision = targetRevision;
            _lastObservedSessionRevision = Math.Max(_lastObservedSessionRevision, targetRevision);
            _viewport.SetAuthoritativeEditRevision(targetRevision);
            RefreshSubmeshList();
            _viewport.Invalidate();
            var result = new ResidentMutationResult(
                "applied",
                string.Empty,
                JsonLongValue(root, "base_revision"),
                targetRevision,
                targetRevision,
                staged.AffectedSubmeshes.Length,
                ResidentMutationPayloadSignature(root));
            _residentMutationLedger.Remember(cacheKey, result);
            WriteResidentMutationBatchAck(root, result, duplicate: false);
        }
        catch (Exception)
        {
            var rollbackReason = "final_commit_failed";
            try
            {
                CopyResidentMutationDocument(_document, previousDocument);
                _materials.ReplaceState(previousMaterials);
                _scene.ReplaceFromResidentMutation(previousScene);
                _editedSubmeshes.Clear();
                _editedSubmeshes.UnionWith(previousEdited);
                _externalTopologyDirty = previousTopologyDirty;
                _lastAppliedEditRevision = previousRevision;
                _lastRequestedMaterialParameterGeneration = previousRequestedMaterialGeneration;
                _lastAppliedMaterialParameterGeneration = previousAppliedMaterialGeneration;
                _materialParameterAppliedCount = previousMaterialAppliedCount;
                _viewport.ReplaceResidentPackage(_document, _materials, _textureSet, _scene);
                _viewport.RestoreResidentMutationSelection(previousSelection);
                _viewport.SetAuthoritativeEditRevision(previousRevision);
            }
            catch (Exception)
            {
                rollbackReason = "rollback_failed";
            }
            RejectResidentMutation(root, cacheKey, rollbackReason);
        }
    }

    private void ApplyResidentMutationRendererCommit(
        JsonElement root,
        StagedResidentMutationBatch staged,
        long requestId,
        long targetRevision)
    {
        if (staged.TopologyChanged)
        {
            _externalTopologyDirty = true;
            _editedSubmeshes.UnionWith(
                staged.AffectedSubmeshes.Where(index => index >= 0 && index < staged.EditableSubmeshCount));
            _viewport.RefreshTopologyGeometry(
                staged.AffectedSubmeshes,
                staged.MaterialSources,
                staged.ReplaceAllTopology);
        }
        else if (staged.VertexChanges.Count > 0)
        {
            _editedSubmeshes.UnionWith(staged.VertexChanges.Keys);
            _viewport.RefreshVertexGeometry(staged.VertexChanges);
        }
        if (staged.MaterialUpdate is not null)
        {
            if (!_viewport.TryApplyMaterialParameters(
                    staged.MaterialUpdate.AffectedSubmeshes,
                    out var materialError))
            {
                throw new InvalidOperationException(materialError);
            }
            _lastRequestedMaterialParameterGeneration = Math.Max(
                _lastRequestedMaterialParameterGeneration,
                staged.MaterialUpdate.ParameterGeneration);
            _lastAppliedMaterialParameterGeneration = Math.Max(
                _lastAppliedMaterialParameterGeneration,
                staged.MaterialUpdate.ParameterGeneration);
            _materialParameterAppliedCount++;
        }
        if (staged.Selection is not null)
        {
            PendingMutationRequest? pending = null;
            var correlatedSelection = false;
            if (_pendingMutationRequests.TryGetValue(requestId, out var candidate)
                && MutationMayReturnSelection(candidate))
            {
                if (!TryPrepareCorrelatedSelectionUpdate(root, out pending, out _))
                {
                    throw new InvalidOperationException("selection_correlation_rejected");
                }
                correlatedSelection = true;
            }
            if (!_viewport.UpdateSelection(
                    staged.Selection.Vertices,
                    staged.Selection.Faces,
                    staged.Selection.Edges,
                    staged.Selection.Sources,
                    requestId,
                    targetRevision,
                    correlatedSelection ? pending?.StrokeId ?? string.Empty : string.Empty,
                    correlatedSelection ? pending?.StrokeSequence ?? -1 : -1,
                    correlatedSelection ? pending?.Phase ?? string.Empty : string.Empty))
            {
                throw new InvalidOperationException("selection_commit_rejected");
            }
            if (correlatedSelection && pending is not null)
            {
                CompleteCorrelatedSelectionUpdate(pending);
            }
            RefreshCreatePartFromSelectionButton();
        }
        if (staged.VertexChanges.Count > 0)
        {
            CompleteCorrelatedStrokeGeometry(root, targetRevision);
        }
    }

    private void RejectResidentMutation(JsonElement root, string cacheKey, string reason)
    {
        var result = new ResidentMutationResult(
            "rejected",
            string.IsNullOrWhiteSpace(reason) ? "invalid_payload" : reason,
            Math.Max(0, JsonLongValue(root, "base_revision")),
            Math.Max(0, JsonLongValue(root, "target_revision")),
            _lastAppliedEditRevision,
            0,
            ResidentMutationPayloadSignature(root));
        _residentMutationLedger.Remember(cacheKey, result);
        WriteResidentMutationBatchAck(root, result, duplicate: false);
    }

    private void WriteResidentMutationBatchAck(
        JsonElement request,
        ResidentMutationResult result,
        bool duplicate)
    {
        var status = duplicate && result.Status == "applied" ? "already_applied" : result.Status;
        var payload = new Dictionary<string, object?>
        {
            ["session_id"] = JsonString(request, "session_id").Trim(),
            ["process_generation"] = JsonLongValue(request, "process_generation"),
            ["request_id"] = JsonLongValue(request, "request_id"),
            ["base_revision"] = result.BaseRevision,
            ["target_revision"] = result.TargetRevision,
            ["edit_revision"] = result.TargetRevision,
            ["applied_renderer_revision"] = result.AppliedRevision,
            ["status"] = status,
            ["reason"] = result.Reason,
            ["changed_items"] = result.ChangedItems,
            ["protocol_version"] = 3,
            ["capabilities"] = new[]
            {
                MeshEditRevisionCapability,
                MutationEnvelopeCapability,
                ResidentMutationBatchCapability,
            },
        };
        WriteProtocolEvent("resident_mutation_batch_ack", payload);
    }

    private static string ResidentMutationCacheKey(JsonElement root)
    {
        var sessionId = JsonString(root, "session_id").Trim();
        var processGeneration = JsonLongValue(root, "process_generation");
        var requestId = JsonLongValue(root, "request_id");
        return sessionId.Length > 0 && processGeneration > 0 && requestId > 0
            ? $"{sessionId}|{processGeneration}|{requestId}"
            : string.Empty;
    }

    internal static string ResidentMutationPayloadSignature(JsonElement root)
    {
        var text = new StringBuilder();
        foreach (var name in new[]
        {
            "action",
            "command",
            "base_revision",
            "target_revision",
            "vertex_updates",
            "topology_update",
            "material_updates",
            "selection_update",
            "final_submesh_count",
            "affected_submesh_indices",
        })
        {
            text.Append(name).Append('=');
            if (root.TryGetProperty(name, out var value))
            {
                text.Append(value.GetRawText());
            }
            text.Append(';');
        }
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text.ToString())));
    }

    internal static ObjDocument CloneResidentMutationDocument(ObjDocument source)
    {
        var clone = new ObjDocument();
        clone.HeaderComments.AddRange(source.HeaderComments);
        clone.MaterialLibraries.AddRange(source.MaterialLibraries);
        foreach (var submesh in source.Submeshes)
        {
            var copy = new ObjSubmesh(
                submesh.Name,
                submesh.VertexStart,
                submesh.UvStart,
                submesh.NormalStart)
            {
                Material = submesh.Material,
                NormalsVertexAligned = submesh.NormalsVertexAligned,
                UvsVertexAligned = submesh.UvsVertexAligned,
            };
            copy.Vertices.AddRange(submesh.Vertices);
            copy.Uvs.AddRange(submesh.Uvs);
            copy.Normals.AddRange(submesh.Normals);
            copy.Faces.AddRange(submesh.Faces.Select(face =>
                new ObjFace(face.Corners.Select(corner =>
                    new ObjCorner(corner.VertexIndex, corner.UvIndex, corner.NormalIndex)).ToArray())));
            clone.Submeshes.Add(copy);
        }
        return clone;
    }

    internal static void CopyResidentMutationDocument(ObjDocument target, ObjDocument source)
    {
        var copy = CloneResidentMutationDocument(source);
        target.HeaderComments.Clear();
        target.HeaderComments.AddRange(copy.HeaderComments);
        target.MaterialLibraries.Clear();
        target.MaterialLibraries.AddRange(copy.MaterialLibraries);
        target.Submeshes.Clear();
        target.Submeshes.AddRange(copy.Submeshes);
    }

    internal static IReadOnlyDictionary<int, MeshVertexChannelChanges> ApplyResidentMutationVertexGroups(
        ObjDocument document,
        IReadOnlyList<PreviewVertexGroup> groups)
    {
        var positions = new Dictionary<int, HashSet<int>>();
        var normals = new Dictionary<int, HashSet<int>>();
        var uvs = new Dictionary<int, HashSet<int>>();
        foreach (var group in groups)
        {
            var submesh = document.Submeshes[group.SubmeshIndex];
            if (group.Normals.Count > 0)
            {
                EnsureVertexAlignedNormals(submesh);
            }
            if (group.Uvs.Count > 0)
            {
                EnsureVertexAlignedUvs(submesh);
            }
            for (var offset = 0; offset < group.Indices.Count; offset++)
            {
                var vertexIndex = group.Indices[offset];
                var positionOffset = offset * 3;
                submesh.Vertices[vertexIndex] = new Vec3(
                    (float)group.Positions[positionOffset],
                    (float)group.Positions[positionOffset + 1],
                    (float)group.Positions[positionOffset + 2]);
                AddChangedChannel(positions, group.SubmeshIndex, vertexIndex);
                if (group.Normals.Count > 0)
                {
                    submesh.Normals[vertexIndex] = new Vec3(
                        (float)group.Normals[positionOffset],
                        (float)group.Normals[positionOffset + 1],
                        (float)group.Normals[positionOffset + 2]);
                    AddChangedChannel(normals, group.SubmeshIndex, vertexIndex);
                }
                if (group.Uvs.Count > 0)
                {
                    var uvOffset = offset * 2;
                    submesh.Uvs[vertexIndex] = new Vec2(
                        (float)group.Uvs[uvOffset],
                        (float)group.Uvs[uvOffset + 1]);
                    AddChangedChannel(uvs, group.SubmeshIndex, vertexIndex);
                }
            }
        }
        return positions.Keys
            .Concat(normals.Keys)
            .Concat(uvs.Keys)
            .Distinct()
            .ToDictionary(
                submeshIndex => submeshIndex,
                submeshIndex => new MeshVertexChannelChanges(
                    ChangedChannel(positions, submeshIndex),
                    ChangedChannel(normals, submeshIndex),
                    ChangedChannel(uvs, submeshIndex)));
    }

    internal static bool ValidateResidentMutationSelection(
        ResidentMutationSelection selection,
        ObjDocument document,
        int editableSubmeshCount)
    {
        foreach (var (submeshIndex, indices) in selection.Vertices)
        {
            if (submeshIndex < 0
                || submeshIndex >= editableSubmeshCount
                || indices.Any(index => index < 0 || index >= document.Submeshes[submeshIndex].Vertices.Count))
            {
                return false;
            }
        }
        foreach (var (submeshIndex, indices) in selection.Faces)
        {
            if (submeshIndex < 0
                || submeshIndex >= editableSubmeshCount
                || indices.Any(index => index < 0 || index >= document.Submeshes[submeshIndex].Faces.Count))
            {
                return false;
            }
        }
        foreach (var (submeshIndex, edges) in selection.Edges)
        {
            if (submeshIndex < 0 || submeshIndex >= editableSubmeshCount)
            {
                return false;
            }
            var validEdges = DocumentEdges(document.Submeshes[submeshIndex]);
            if (edges.Any(edge => !validEdges.Contains(NormalizedEdge(edge.A, edge.B))))
            {
                return false;
            }
        }
        return selection.Sources.All(index => index >= 0 && index < editableSubmeshCount);
    }

    private static HashSet<(int A, int B)> DocumentEdges(ObjSubmesh submesh)
    {
        var edges = new HashSet<(int A, int B)>();
        foreach (var face in submesh.Faces)
        {
            for (var index = 0; index < face.Corners.Length; index++)
            {
                var first = face.Corners[index].VertexIndex;
                var second = face.Corners[(index + 1) % face.Corners.Length].VertexIndex;
                edges.Add(NormalizedEdge(first, second));
            }
        }
        return edges;
    }

    private static (int A, int B) NormalizedEdge(int first, int second) =>
        first <= second ? (first, second) : (second, first);

    internal static bool PositiveRequestBypassesProtocolCoalescing(JsonElement root, string eventName) =>
        ProtocolCoalescingKey(new ParsedProtocolMessage(root, eventName)) is null;
}

internal sealed record ResidentMutationResult(
    string Status,
    string Reason,
    long BaseRevision,
    long TargetRevision,
    long AppliedRevision,
    int ChangedItems,
    string PayloadSignature);

internal sealed class ResidentMutationResultLedger
{
    private readonly int _limit;
    private readonly Dictionary<string, ResidentMutationResult> _results = new(StringComparer.Ordinal);
    private readonly Queue<string> _order = new();

    public ResidentMutationResultLedger(int limit)
    {
        _limit = Math.Max(1, limit);
    }

    public bool TryGet(string key, out ResidentMutationResult result) =>
        _results.TryGetValue(key, out result!);

    public void Remember(string key, ResidentMutationResult result)
    {
        if (string.IsNullOrWhiteSpace(key) || _results.ContainsKey(key))
        {
            return;
        }
        _results[key] = result;
        _order.Enqueue(key);
        while (_order.Count > _limit)
        {
            _results.Remove(_order.Dequeue());
        }
    }
}
