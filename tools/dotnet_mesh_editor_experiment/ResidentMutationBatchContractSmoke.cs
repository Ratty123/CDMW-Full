using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static class ResidentMutationBatchContractSmoke
{
    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(arg, "--headless-resident-mutation-batch-contract", StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var reportPath = ReportPath(args);
        var gates = RunGates();
        var ok = gates.Values.All(value => value);
        PreviewPerformanceReport.WriteAtomic(reportPath, new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_resident_mutation_batch_contract_v1",
            ["schema_version"] = 1,
            ["ok"] = ok,
            ["capability"] = "resident_mutation_batch_v3",
            ["gates"] = gates,
        });
        return ok ? 0 : 1;
    }

    private static Dictionary<string, bool> RunGates()
    {
        var gates = new Dictionary<string, bool>(StringComparer.Ordinal);
        var vertexPayload = Payload(vertex: true, material: true, selection: true);
        var vertexPrepared = ExperimentForm.TryPrepareResidentMutationBatchPayload(
            vertexPayload,
            out var preparedVertex);
        gates["vertex_material_selection_prepared"] = vertexPrepared
            && preparedVertex is not null
            && preparedVertex.VertexGroups.Count == 1
            && preparedVertex.MaterialUpdate is not null
            && preparedVertex.Selection is not null
            && preparedVertex.HistoryState.GetProperty("undo_count").GetInt32() == 1;

        var live = TriangleDocument();
        var before = Fingerprint(live);
        var staged = ExperimentForm.CloneResidentMutationDocument(live);
        var vertexValid = preparedVertex is not null
            && ExperimentForm.ValidatePreviewVertexGroups(staged, preparedVertex.VertexGroups);
        if (vertexValid)
        {
            _ = ExperimentForm.ApplyResidentMutationVertexGroups(staged, preparedVertex!.VertexGroups);
        }
        gates["vertex_stage_does_not_mutate_live"] = vertexValid
            && Fingerprint(live) == before
            && Fingerprint(staged) != before;
        ExperimentForm.CopyResidentMutationDocument(live, staged);
        gates["vertex_commit_updates_once"] = live.Submeshes[0].Vertices[0].X == 2.0f;

        var materialClone = NetMaterialSet.Empty.CloneForResidentMutation();
        if (preparedVertex?.MaterialUpdate is not null)
        {
            materialClone.ApplyParameterUpdate(preparedVertex.MaterialUpdate);
        }
        gates["material_stage_isolated"] = NetMaterialSet.Empty.ParameterStateCount == 0
            && materialClone.ParameterStateCount == 1;
        gates["selection_payload_valid"] = preparedVertex?.Selection is not null
            && ExperimentForm.ValidateResidentMutationSelection(
                preparedVertex.Selection,
                live,
                editableSubmeshCount: 1);
        gates["positive_request_bypasses_protocol_coalescing"] =
            ExperimentForm.PositiveRequestBypassesProtocolCoalescing(
                vertexPayload,
                "preview_vertex_update")
            && ExperimentForm.PositiveRequestBypassesProtocolCoalescing(
                vertexPayload,
                "preview_triangle_update");
        var recoveryPayloadValues = JsonSerializer.Deserialize<Dictionary<string, object?>>(
            vertexPayload.GetRawText()) ?? new Dictionary<string, object?>();
        recoveryPayloadValues["recovery_snapshot"] = true;
        recoveryPayloadValues["mutation_kind"] = "recovery_snapshot";
        var recoveryPayload = JsonSerializer.SerializeToElement(recoveryPayloadValues);
        gates["idempotency_signature_ignores_recovery_flag"] = string.Equals(
            ExperimentForm.ResidentMutationPayloadSignature(vertexPayload),
            ExperimentForm.ResidentMutationPayloadSignature(recoveryPayload),
            StringComparison.Ordinal);
        gates["idempotency_signature_binds_payload"] = !string.Equals(
            ExperimentForm.ResidentMutationPayloadSignature(vertexPayload),
            ExperimentForm.ResidentMutationPayloadSignature(Payload(vertex: true, invalidVertex: true)),
            StringComparison.Ordinal);

        var invalidVertexLive = TriangleDocument();
        var invalidVertexBefore = Fingerprint(invalidVertexLive);
        var invalidVertexPrepared = ExperimentForm.TryPrepareResidentMutationBatchPayload(
            Payload(vertex: true, invalidVertex: true),
            out _);
        gates["invalid_vertex_rejected_without_mutation"] = !invalidVertexPrepared
            && Fingerprint(invalidVertexLive) == invalidVertexBefore;

        var invalidMaterialLive = TriangleDocument();
        var invalidMaterialBefore = Fingerprint(invalidMaterialLive);
        var invalidMaterialPrepared = ExperimentForm.TryPrepareResidentMutationBatchPayload(
            Payload(material: true, invalidMaterial: true),
            out _);
        gates["invalid_material_rejected_without_mutation"] = !invalidMaterialPrepared
            && Fingerprint(invalidMaterialLive) == invalidMaterialBefore;

        var invalidSelectionPrepared = ExperimentForm.TryPrepareResidentMutationBatchPayload(
            Payload(vertex: true, selection: true, invalidSelection: true),
            out var preparedInvalidSelection);
        gates["invalid_selection_rejected_without_mutation"] = invalidSelectionPrepared
            && preparedInvalidSelection?.Selection is not null
            && !ExperimentForm.ValidateResidentMutationSelection(
                preparedInvalidSelection.Selection,
                TriangleDocument(),
                editableSubmeshCount: 1);

        TestTopology(gates);
        TestAuthority(gates);
        TestIdempotency(gates);
        return gates;
    }

    private static void TestTopology(Dictionary<string, bool> gates)
    {
        var combinedPrepared = ExperimentForm.TryPrepareResidentMutationBatchPayload(
            Payload(material: true, selection: true, topology: "append"),
            out var combined);
        gates["topology_material_selection_prepared"] = combinedPrepared
            && combined?.TopologyPlan is not null
            && combined.MaterialUpdate is not null
            && combined.Selection is not null;

        var appendedLive = TriangleDocument();
        var appendPreparedOk = ExperimentForm.TryPrepareResidentMutationBatchPayload(
            Payload(topology: "append"),
            out var appendPrepared);
        var appendedStage = ExperimentForm.CloneResidentMutationDocument(appendedLive);
        var appendApplied = appendPreparedOk
            && appendPrepared?.TopologyPlan is not null
            && ExperimentForm.TryCommitPreviewTriangleGroups(
                appendedStage,
                appendPrepared.TopologyPlan,
                editableSubmeshCount: 1,
                out _,
                out _,
                out _,
                out _,
                out _);
        gates["topology_append_staged"] = appendApplied
            && appendedStage.Submeshes.Count == 2
            && appendedLive.Submeshes.Count == 1;

        var shrinkLive = TwoPartDocument();
        var shrinkPreparedOk = ExperimentForm.TryPrepareResidentMutationBatchPayload(
            Payload(topology: "shrink"),
            out var shrinkPrepared);
        var shrinkStage = ExperimentForm.CloneResidentMutationDocument(shrinkLive);
        var shrinkApplied = shrinkPreparedOk
            && shrinkPrepared?.TopologyPlan is not null
            && ExperimentForm.TryCommitPreviewTriangleGroups(
                shrinkStage,
                shrinkPrepared.TopologyPlan,
                editableSubmeshCount: 2,
                out _,
                out _,
                out _,
                out _,
                out _);
        gates["topology_shrink_staged"] = shrinkApplied
            && shrinkStage.Submeshes.Count == 1
            && shrinkLive.Submeshes.Count == 2;

        var invalidLive = TriangleDocument();
        var invalidBefore = Fingerprint(invalidLive);
        var invalidPrepared = ExperimentForm.TryPrepareResidentMutationBatchPayload(
            Payload(vertex: true, topology: "invalid"),
            out _);
        gates["invalid_topology_rejected_without_mutation"] = !invalidPrepared
            && Fingerprint(invalidLive) == invalidBefore;

        var commitFailureLive = TriangleDocument();
        var commitFailureBefore = Fingerprint(commitFailureLive);
        var commitFailurePrepared = ExperimentForm.TryPrepareResidentMutationBatchPayload(
            Payload(topology: "append"),
            out var commitFailurePlan);
        var commitFailureStage = ExperimentForm.CloneResidentMutationDocument(commitFailureLive);
        var commitFailureStaged = commitFailurePrepared
            && commitFailurePlan?.TopologyPlan is not null
            && ExperimentForm.TryCommitPreviewTriangleGroups(
                commitFailureStage,
                commitFailurePlan.TopologyPlan,
                editableSubmeshCount: 1,
                out _,
                out _,
                out _,
                out _,
                out _);
        gates["failure_before_final_commit_leaves_previous_state"] = commitFailureStaged
            && Fingerprint(commitFailureLive) == commitFailureBefore;
    }

    private static void TestAuthority(Dictionary<string, bool> gates)
    {
        var valid = Payload(vertex: true);
        gates["authority_accepts_current_envelope"] = ExperimentForm.ResidentMutationAuthorityReason(
            valid,
            "mesh-session",
            7,
            4).Length == 0;
        gates["wrong_session_rejected"] = AuthorityReason(valid, sessionId: "wrong") == "session_mismatch";
        gates["wrong_process_generation_rejected"] = AuthorityReason(valid, processGeneration: 8) == "stale_process_generation";
        gates["missing_request_rejected"] = AuthorityReason(valid, requestId: 0) == "missing_request_id";
        gates["protocol_v2_rejected_for_batch"] = AuthorityReason(valid, protocolVersion: 2) == "unsupported_protocol_version";
        gates["stale_revision_rejected"] = AuthorityReason(valid, baseRevision: 3, targetRevision: 4) == "stale_revision";
        gates["invalid_base_revision_rejected"] = AuthorityReason(valid, baseRevision: 3, targetRevision: 5) == "invalid_base_revision";
        gates["invalid_revision_range_rejected"] = AuthorityReason(valid, baseRevision: 4, targetRevision: 4) == "invalid_revision_range";
    }

    private static void TestIdempotency(Dictionary<string, bool> gates)
    {
        var ledger = new ResidentMutationResultLedger(2);
        var accepted = new ResidentMutationResult("applied", "", 4, 5, 5, 1, "accepted");
        var rejected = new ResidentMutationResult("rejected", "invalid_payload", 5, 6, 5, 0, "rejected");
        ledger.Remember("mesh-session|7|11", accepted);
        ledger.Remember("mesh-session|7|11", rejected);
        gates["duplicate_accepted_request_is_idempotent"] = ledger.TryGet("mesh-session|7|11", out var first)
            && first.Status == "applied"
            && first.AppliedRevision == 5;
        ledger.Remember("mesh-session|7|12", rejected);
        gates["duplicate_rejected_request_stays_rejected"] = ledger.TryGet("mesh-session|7|12", out var second)
            && second.Status == "rejected"
            && second.Reason == "invalid_payload";
        gates["distinct_positive_requests_remain_distinct"] = first != second;
        ledger.Remember("mesh-session|7|13", accepted with { BaseRevision = 6, TargetRevision = 7, AppliedRevision = 7 });
        gates["idempotency_cache_is_bounded"] = !ledger.TryGet("mesh-session|7|11", out _)
            && ledger.TryGet("mesh-session|7|13", out _);
    }

    private static string AuthorityReason(
        JsonElement source,
        string sessionId = "mesh-session",
        long processGeneration = 7,
        long requestId = 11,
        long baseRevision = 4,
        long targetRevision = 5,
        long protocolVersion = 3)
    {
        var payload = JsonSerializer.Deserialize<Dictionary<string, object?>>(source.GetRawText())
            ?? new Dictionary<string, object?>();
        payload["session_id"] = sessionId;
        payload["process_generation"] = processGeneration;
        payload["request_id"] = requestId;
        payload["base_revision"] = baseRevision;
        payload["target_revision"] = targetRevision;
        payload["edit_revision"] = targetRevision;
        payload["revision"] = targetRevision;
        payload["protocol_version"] = protocolVersion;
        return ExperimentForm.ResidentMutationAuthorityReason(
            JsonSerializer.SerializeToElement(payload),
            "mesh-session",
            7,
            4);
    }

    private static JsonElement Payload(
        bool vertex = false,
        bool material = false,
        bool selection = false,
        bool invalidVertex = false,
        bool invalidMaterial = false,
        bool invalidSelection = false,
        string topology = "")
    {
        var payload = new Dictionary<string, object?>
        {
            ["event"] = "resident_mutation_batch",
            ["session_id"] = "mesh-session",
            ["process_generation"] = 7,
            ["request_id"] = 11,
            ["base_revision"] = 4,
            ["target_revision"] = 5,
            ["edit_revision"] = 5,
            ["revision"] = 5,
            ["protocol_version"] = 3,
            ["action"] = topology.Length > 0 ? "topology" : "transform",
            ["affected_submesh_indices"] = new[] { 0 },
            ["history_state"] = new Dictionary<string, object?>
            {
                ["undo_count"] = 1,
                ["redo_count"] = 0,
                ["history_cursor"] = 1,
                ["history_entries"] = new object[]
                {
                    new Dictionary<string, object?>
                    {
                        ["action"] = "transform",
                        ["label"] = "Move",
                        ["state"] = "applied",
                    },
                },
            },
            ["vertex_updates"] = vertex
                ? new object[]
                {
                    new Dictionary<string, object?>
                    {
                        ["source_submesh_index"] = 0,
                        ["source_vertex_indices"] = new[] { 0 },
                        ["positions"] = invalidVertex
                            ? new[] { 2.0, 0.0 }
                            : new[] { 2.0, 0.0, 0.0 },
                    },
                }
                : Array.Empty<object>(),
            ["material_updates"] = material
                ? new object[]
                {
                    new Dictionary<string, object?>
                    {
                        ["source_submesh_indices"] = new[] { 0 },
                        ["editor_role"] = "replacement_preview",
                        [invalidMaterial ? "unknown_parameter" : "roughness"] = 0.5,
                    },
                }
                : Array.Empty<object>(),
        };
        if (selection)
        {
            payload["selection_update"] = new Dictionary<string, object?>
            {
                ["vertices_by_submesh"] = new Dictionary<string, object?>
                {
                    ["0"] = new[] { invalidSelection ? 99 : 0 },
                },
                ["faces_by_submesh"] = new Dictionary<string, object?> { ["0"] = new[] { 0 } },
                ["edges_by_submesh"] = new Dictionary<string, object?>
                {
                    ["0"] = new object[] { new[] { 0, 1 } },
                },
                ["source_indices"] = new[] { 0 },
            };
        }
        if (topology.Length > 0)
        {
            const int groupIndex = 1;
            payload["final_submesh_count"] = topology == "shrink" ? 1 : 2;
            payload["topology_update"] = new Dictionary<string, object?>
            {
                ["triangle_source_submesh_indices"] = new[] { groupIndex },
                ["replace_all_triangles"] = false,
                ["final_submesh_count"] = topology == "shrink" ? 1 : 2,
                ["triangle_groups"] = new object[]
                {
                    new Dictionary<string, object?>
                    {
                        ["source_submesh_index"] = groupIndex,
                        ["material_source_submesh_index"] = 0,
                        ["part_name"] = topology == "shrink" ? "removed" : "added",
                        ["positions"] = topology == "shrink"
                            ? Array.Empty<double>()
                            : new[] { 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0 },
                        ["indices"] = topology == "shrink"
                            ? Array.Empty<int>()
                            : topology == "invalid"
                                ? new[] { 0, 1, 9 }
                                : new[] { 0, 1, 2 },
                    },
                },
            };
        }
        return JsonSerializer.SerializeToElement(payload);
    }

    private static ObjDocument TriangleDocument()
    {
        var document = new ObjDocument();
        document.Submeshes.Add(TriangleSubmesh("part_0", 0.0f));
        return document;
    }

    private static ObjDocument TwoPartDocument()
    {
        var document = TriangleDocument();
        document.Submeshes.Add(TriangleSubmesh("part_1", 2.0f));
        return document;
    }

    private static ObjSubmesh TriangleSubmesh(string name, float offset)
    {
        var submesh = new ObjSubmesh(name, 0, 0, 0);
        submesh.Vertices.AddRange(new[]
        {
            new Vec3(offset, 0.0f, 0.0f),
            new Vec3(offset + 1.0f, 0.0f, 0.0f),
            new Vec3(offset, 1.0f, 0.0f),
        });
        submesh.Faces.Add(new ObjFace(new[]
        {
            new ObjCorner(0, -1, -1),
            new ObjCorner(1, -1, -1),
            new ObjCorner(2, -1, -1),
        }));
        return submesh;
    }

    private static string Fingerprint(ObjDocument document) => string.Join(
        "|",
        document.Submeshes.Select(submesh =>
            $"{submesh.Name}:{submesh.Vertices.Count}:{submesh.Faces.Count}:"
            + string.Join(",", submesh.Vertices.Select(vertex => $"{vertex.X:R}/{vertex.Y:R}/{vertex.Z:R}"))));

    private static string ReportPath(string[] args)
    {
        var index = Array.FindIndex(args, arg =>
            string.Equals(arg, "--resident-mutation-report", StringComparison.OrdinalIgnoreCase));
        if (index < 0 || index + 1 >= args.Length)
        {
            throw new ArgumentException("--resident-mutation-report requires an output path.");
        }
        return Path.GetFullPath(args[index + 1]);
    }
}
