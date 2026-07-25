using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private readonly long _sourceParseCount;
    private long _initialTextureLoadCount;
    private long _materialStateUpdateCount;
    private long _materialStateAppliedCount;
    private long _materialStateFailedCount;
    private long _lastRequestedMaterialGeneration;
    private long _lastAppliedMaterialGeneration;
    private long _materialParameterUpdateCount;
    private long _materialParameterAppliedCount;
    private long _materialParameterFailedCount;
    private long _lastRequestedMaterialParameterGeneration;
    private long _lastAppliedMaterialParameterGeneration;
    private string _residentMaterialSessionId = string.Empty;
    private bool _activateAfterMaterialSync;
    private RendererDiagnosticCacheKey _rendererDiagnosticCacheKey;
    private Dictionary<string, object?>? _rendererDiagnosticCache;
    private long _rendererDiagnosticCacheHitCount;
    private long _rendererDiagnosticRebuildCount;

    private Dictionary<string, object?> LifecycleCountsPayload()
    {
        return new Dictionary<string, object?>
        {
            // Whether the authoring tool panels are actually constructed. The
            // preview profile never builds them; authoring must always have
            // them by the time mesh edit is entered, and this is what makes
            // that observable from outside the process.
            ["authoring_tool_panels_present"] = _leftToolPanel is not null && _rightToolPanel is not null,
            ["source_parse_count"] = _sourceParseCount,
            ["geometry_upload_count"] = _viewport.GeometryUploadCount,
            ["device_reset_count"] = _viewport.DeviceResetCount,
            ["device_reset_attempt_count"] = _viewport.DeviceResetAttemptCount,
            ["initial_texture_load_count"] = _initialTextureLoadCount,
            ["material_state_update_count"] = _materialStateUpdateCount,
            ["material_state_applied_count"] = _materialStateAppliedCount,
            ["material_state_failed_count"] = _materialStateFailedCount,
            ["material_parameter_update_count"] = _materialParameterUpdateCount,
            ["material_parameter_applied_count"] = _materialParameterAppliedCount,
            ["material_parameter_failed_count"] = _materialParameterFailedCount,
            ["texture_region_update_count"] = _textureRegionUpdateCount,
            ["texture_region_applied_count"] = _textureRegionAppliedCount,
            ["texture_region_failed_count"] = _textureRegionFailedCount,
            ["texture_decode_singleflight_join_count"] = _textureSet.DecodeSingleflightJoinCount,
            ["decoded_bitmap_prune_count"] = _textureSet.DecodedBitmapPruneCount,
            ["renderer_diagnostic_cache_hits"] = _rendererDiagnosticCacheHitCount,
            ["renderer_diagnostic_rebuilds"] = _rendererDiagnosticRebuildCount,
            ["embedded_host_resize_deferred_count"] = _embeddedHostResizeDeferredCount,
            ["embedded_host_resize_coalesced_count"] = _embeddedHostResizeCoalescedCount,
            ["embedded_host_resize_commit_count"] = _embeddedHostResizeCommitCount,
        };
    }

    private Dictionary<string, object?> RendererStatusWithLifecycle()
    {
        var cacheKey = new RendererDiagnosticCacheKey(
            _viewport.RendererBackendName,
            _viewport.DisplayMode,
            _viewport.MaterialDebugMode,
            _viewport.ShowSolid,
            _viewport.ShowWire,
            _viewport.ShowVertices,
            _viewport.TexturesEnabled,
            _viewport.Width,
            _viewport.Height,
            _scene.SceneGeneration,
            _materials.Generation,
            _lastAppliedEditRevision,
            _lastAppliedMaterialGeneration,
            _lastAppliedMaterialParameterGeneration,
            _textureRegionAppliedCount,
            _textureSet.DecodedCount,
            _viewport.GeometryUploadCount,
            _viewport.DeviceResetCount);
        if (_rendererDiagnosticCache is null || _rendererDiagnosticCacheKey != cacheKey)
        {
            _rendererDiagnosticCache = _viewport.RendererStatusPayload();
            _rendererDiagnosticCache["provenance"] = HelperBuildProvenance.Payload(_viewport.ActiveCapabilities());
            _rendererDiagnosticCacheKey = cacheKey;
            _rendererDiagnosticRebuildCount++;
        }
        else
        {
            _rendererDiagnosticCacheHitCount++;
        }
        var renderer = new Dictionary<string, object?>(_rendererDiagnosticCache);
        renderer["live_metrics"] = _viewport.RendererLiveMetricsPayload();
        renderer["lifecycle_counts"] = LifecycleCountsPayload();
        renderer["material_generation"] = _materials.Generation;
        renderer["last_requested_material_generation"] = _lastRequestedMaterialGeneration;
        renderer["last_applied_material_generation"] = _lastAppliedMaterialGeneration;
        renderer["last_requested_material_parameter_generation"] = _lastRequestedMaterialParameterGeneration;
        renderer["last_applied_material_parameter_generation"] = _lastAppliedMaterialParameterGeneration;
        return renderer;
    }

    private Dictionary<string, object?> RendererCompactStatusWithLifecycle()
    {
        var renderer = _viewport.RendererCompactStatusPayload();
        renderer["lifecycle_counts"] = LifecycleCountsPayload();
        renderer["material_generation"] = _materials.Generation;
        renderer["last_requested_material_generation"] = _lastRequestedMaterialGeneration;
        renderer["last_applied_material_generation"] = _lastAppliedMaterialGeneration;
        renderer["last_requested_material_parameter_generation"] = _lastRequestedMaterialParameterGeneration;
        renderer["last_applied_material_parameter_generation"] = _lastAppliedMaterialParameterGeneration;
        return renderer;
    }

    private readonly record struct RendererDiagnosticCacheKey(
        string Backend,
        string DisplayMode,
        int MaterialDebugMode,
        bool ShowSolid,
        bool ShowWire,
        bool ShowVertices,
        bool TexturesEnabled,
        int Width,
        int Height,
        long SceneGeneration,
        long MaterialGeneration,
        long EditRevision,
        long AppliedMaterialGeneration,
        long AppliedMaterialParameterGeneration,
        long TextureRegionAppliedCount,
        int DecodedTextureCount,
        long GeometryUploadCount,
        long DeviceResetCount);

    private void RequestMaterialSync(string requestedMaterialSignature)
    {
        _activateAfterMaterialSync = true;
        WriteProtocolEvent("material_sync_required", new Dictionary<string, object?>
        {
            ["material_signature"] = _materials.Signature,
            ["requested_material_signature"] = requestedMaterialSignature,
            ["generation"] = _lastAppliedMaterialGeneration,
            ["capabilities"] = new[] { ResidentMaterialUpdatesCapability },
            ["lifecycle_counts"] = LifecycleCountsPayload(),
        });
    }

    private bool ActivateResidentViewport()
    {
        if (_options.Embedded && !TryEmbedOrFail("reactivation"))
        {
            return false;
        }
        _embeddedViewportActive = true;
        Show();
        Focus();
        _viewport.Focus();
        WriteProtocolEvent("activated", new Dictionary<string, object?>
        {
            ["material_signature"] = _materials.Signature,
            ["generation"] = _materials.Generation,
            ["renderer"] = RendererStatusWithLifecycle(),
            ["lifecycle_counts"] = LifecycleCountsPayload(),
        });
        return true;
    }

    private void HandleMaterialStateUpdate(JsonElement root)
    {
        _materialStateUpdateCount++;
        var request = root.Clone();
        NetMaterialStateUpdate update;
        try
        {
            update = _materials.NormalizeStateUpdate(NetMaterialSet.ParseStateUpdate(root));
        }
        catch (Exception ex) when (ex is InvalidDataException or IOException or ArgumentException or NotSupportedException or OverflowException)
        {
            WriteMaterialStateFailed(request, 0, string.Empty, "invalid_payload", ex.Message);
            return;
        }

        if (!ValidateMutationEnvelope(root, out var envelopeError))
        {
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, envelopeError, "Material state update requires a current mutation envelope.");
            return;
        }
        if (update.Generation <= 0)
        {
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, "invalid_generation", "Material generation must be positive.");
            return;
        }
        if (string.IsNullOrWhiteSpace(update.MaterialSignature))
        {
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, "invalid_signature", "Material state update requires material_signature.");
            return;
        }
        if (!AcceptMaterialSession(update.SessionId, out var sessionError))
        {
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, "session_mismatch", sessionError);
            return;
        }
        if (update.Generation <= _lastRequestedMaterialGeneration)
        {
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, "stale_or_out_of_order", "Material generation is not newer than the last request.");
            return;
        }
        if (!CanApplyMaterialEditRevision(update.EditRevision, out var revisionError))
        {
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, revisionError, "Material edit revision does not match the resident session revision.");
            return;
        }
        if (update.AffectedSubmeshes.Any(index => index < 0 || index >= _document.Submeshes.Count))
        {
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, "invalid_submesh", "Material update references an unknown submesh.");
            return;
        }

        _lastRequestedMaterialGeneration = update.Generation;
        var affectedResourceIds = update.ResourceIdsForAffectedSubmeshes();
        var resourcesToDecode = update.Resources.Where(resource => affectedResourceIds.Contains(resource.ResourceId)).ToArray();
        var started = new Dictionary<string, object?>
        {
            ["session_id"] = update.SessionId,
            ["generation"] = update.Generation,
            ["affected_submesh_count"] = update.AffectedSubmeshes.Count,
            ["resource_count"] = resourcesToDecode.Length,
        };
        CopyMutationEnvelope(request, started);
        WriteProtocolEvent("material_state_started", started);
        _ = _textureSet.DecodeResourcesAsync(resourcesToDecode).ContinueWith(task =>
        {
            if (IsDisposed || Disposing || !IsHandleCreated)
            {
                return;
            }
            try
            {
                BeginInvoke(new Action(() => CompleteMaterialStateUpdate(update, task, request)));
            }
            catch (InvalidOperationException)
            {
            }
        }, TaskScheduler.Default);
    }

    private bool AcceptMaterialSession(string sessionId, out string error)
    {
        error = string.Empty;
        if (string.IsNullOrWhiteSpace(sessionId))
        {
            error = "Material state update requires session_id.";
            return false;
        }
        if (string.IsNullOrWhiteSpace(_residentMaterialSessionId))
        {
            error = "Resident session is not established.";
            return false;
        }
        if (string.Equals(_residentMaterialSessionId, sessionId, StringComparison.Ordinal))
        {
            return true;
        }
        error = $"Material session {sessionId} does not match resident session {_residentMaterialSessionId}.";
        return false;
    }

    private void ObserveResidentSession(JsonElement root)
    {
        var sessionId = JsonString(root, "session_id").Trim();
        if (string.IsNullOrWhiteSpace(sessionId))
        {
            return;
        }
        var processGeneration = Math.Max(0, JsonLongValue(root, "process_generation"));
        if ((_residentProcessGeneration > 0 && processGeneration != _residentProcessGeneration)
            || (!string.IsNullOrWhiteSpace(_residentMaterialSessionId)
                && !string.Equals(_residentMaterialSessionId, sessionId, StringComparison.Ordinal)))
        {
            ResetPendingMutationAuthority();
        }
        _residentProcessGeneration = processGeneration;
        if (string.IsNullOrWhiteSpace(_residentMaterialSessionId))
        {
            _residentMaterialSessionId = sessionId;
            _lastObservedSessionRevision = ProtocolEditRevision(root);
            return;
        }
        if (!string.Equals(_residentMaterialSessionId, sessionId, StringComparison.Ordinal))
        {
            WriteProtocolEvent("error", new Dictionary<string, object?>
            {
                ["code"] = "session_mismatch",
                ["session_id"] = sessionId,
                ["resident_session_id"] = _residentMaterialSessionId,
            });
            return;
        }
        _lastObservedSessionRevision = Math.Max(_lastObservedSessionRevision, ProtocolEditRevision(root));
    }

    private bool CanApplyMaterialEditRevision(long revision, out string reason)
    {
        reason = string.Empty;
        if (revision < 0)
        {
            reason = "invalid_edit_revision";
            return false;
        }
        var residentRevision = Math.Max(_lastAppliedEditRevision, _lastObservedSessionRevision);
        if (revision < residentRevision)
        {
            reason = "stale_edit_revision";
            return false;
        }
        if (revision > residentRevision)
        {
            reason = "future_edit_revision";
            return false;
        }
        return true;
    }

    private void CompleteMaterialStateUpdate(NetMaterialStateUpdate update, Task<NetTextureDecodeResult> task, JsonElement request)
    {
        if (update.Generation != _lastRequestedMaterialGeneration)
        {
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, "superseded", "A newer material generation replaced this request.");
            return;
        }
        if (!CanApplyMaterialEditRevision(update.EditRevision, out var revisionError))
        {
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, revisionError, "Material edit revision changed while textures were decoding.");
            return;
        }
        if (task.IsCanceled || task.IsFaulted)
        {
            var message = task.Exception?.GetBaseException().Message ?? "Material texture decode was cancelled.";
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, "texture_decode_failed", message);
            return;
        }
        var decode = task.Result;
        var affectedResourceIds = update.ResourceIdsForAffectedSubmeshes();
        var requestedResources = update.Resources
            .Where(resource => affectedResourceIds.Contains(resource.ResourceId))
            .ToArray();
        var resourcesById = update.Resources.ToDictionary(resource => resource.ResourceId, StringComparer.Ordinal);
        var requiredFailures = decode.Failures
            .Where(pair => resourcesById.TryGetValue(pair.Key, out var resource) && resource.Required)
            .ToArray();
        if (requiredFailures.Length > 0)
        {
            var message = string.Join("; ", requiredFailures.Select(pair => $"{pair.Key}: {pair.Value}"));
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, "required_texture_decode_failed", message);
            return;
        }
        if (requestedResources.Length > 0
            && decode.Decoded == 0
            && decode.Reused == 0
            && decode.Failures.Count > 0)
        {
            var message = string.Join("; ", decode.Failures.Select(pair => $"{pair.Key}: {pair.Value}"));
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, "texture_decode_failed", message);
            return;
        }
        var optionalFailures = decode.Failures
            .Where(pair => !resourcesById.TryGetValue(pair.Key, out var resource) || !resource.Required)
            .ToArray();

        var previous = _materials.CaptureState();
        var next = _materials.BuildState(update);
        var missingResource = next.Submeshes
            .Where(binding => update.AffectedSubmeshes.Contains(binding.SubmeshIndex))
            .SelectMany(binding => binding.ResourceChannels.Values)
            .FirstOrDefault(resourceId => !next.Resources.ContainsKey(resourceId));
        if (!string.IsNullOrWhiteSpace(missingResource))
        {
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, "missing_resource", $"Material resource {missingResource} was not supplied.");
            return;
        }

        _materials.ReplaceState(next);
        if (!_viewport.TryApplyMaterialState(update.AffectedSubmeshes, out var bindError))
        {
            _materials.ReplaceState(previous);
            WriteMaterialStateFailed(request, update.Generation, update.SessionId, "d3d_binding_failed", bindError);
            return;
        }
        _textureSet.PruneToResources(_materials.TextureLoadResources());
        RefreshSubmeshList();

        _lastAppliedMaterialGeneration = update.Generation;
        _materialStateAppliedCount++;
        MarkEditRevisionApplied(update.EditRevision);
        var payload = new Dictionary<string, object?>
        {
            ["session_id"] = update.SessionId,
            ["edit_revision"] = update.EditRevision,
            ["generation"] = update.Generation,
            ["material_signature"] = _materials.Signature,
            ["material_authority_fingerprint"] = JsonString(request, "material_authority_fingerprint"),
            ["material_authority_revision"] = JsonLongValue(request, "material_authority_revision"),
            ["affected_submeshes"] = update.AffectedSubmeshes,
            ["decoded_resources"] = decode.Decoded,
            ["reused_resources"] = decode.Reused,
            ["optional_resource_failures"] = optionalFailures.Select(pair => new Dictionary<string, object?>
            {
                ["resource_id"] = pair.Key,
                ["message"] = pair.Value,
                ["fallback_policy"] = resourcesById.TryGetValue(pair.Key, out var resource)
                    ? resource.FallbackPolicy
                    : "diagnostic_only",
            }).ToArray(),
            ["renderer"] = RendererStatusWithLifecycle(),
            ["lifecycle_counts"] = LifecycleCountsPayload(),
            ["capabilities"] = new[] { ResidentMaterialUpdatesCapability },
        };
        CopyMutationEnvelope(request, payload);
        WriteProtocolEvent("material_state_applied", payload);
        if (_activateAfterMaterialSync)
        {
            _activateAfterMaterialSync = false;
            _ = ActivateResidentViewport();
        }
    }

    private void HandleMaterialParameterUpdate(JsonElement root)
    {
        _materialParameterUpdateCount++;
        NetMaterialParameterUpdate update;
        try
        {
            update = NetMaterialSet.ParseParameterUpdate(root).ExpandAllSubmeshes(
                Enumerable.Range(0, _document.Submeshes.Count).ToArray());
        }
        catch (Exception ex) when (ex is InvalidDataException or ArgumentException or OverflowException)
        {
            WriteMaterialParameterFailed(
                root,
                ProtocolParameterGeneration(root),
                JsonString(root, "session_id"),
                ProtocolEditRevision(root),
                "invalid_payload",
                ex.Message);
            return;
        }

        if (update.ParameterGeneration <= 0)
        {
            WriteMaterialParameterFailed(root, update.ParameterGeneration, update.SessionId, update.EditRevision, "invalid_generation", "Material parameter_generation must be positive.");
            return;
        }
        if (update.EditRevision < 0)
        {
            WriteMaterialParameterFailed(root, update.ParameterGeneration, update.SessionId, update.EditRevision, "invalid_revision", "Material edit_revision cannot be negative.");
            return;
        }
        if (!ValidateMutationEnvelope(root, out var envelopeError))
        {
            WriteMaterialParameterFailed(root, update.ParameterGeneration, update.SessionId, update.EditRevision, envelopeError, "Material parameter update requires a current mutation envelope.");
            return;
        }
        if (!AcceptMaterialSession(update.SessionId, out var sessionError))
        {
            WriteMaterialParameterFailed(root, update.ParameterGeneration, update.SessionId, update.EditRevision, "session_mismatch", sessionError);
            return;
        }
        if (update.ParameterGeneration <= _lastRequestedMaterialParameterGeneration)
        {
            WriteMaterialParameterFailed(root, update.ParameterGeneration, update.SessionId, update.EditRevision, "stale_or_out_of_order", "Material parameter_generation is not newer than the last request.");
            return;
        }
        if (update.EditRevision < _lastAppliedEditRevision)
        {
            WriteMaterialParameterFailed(root, update.ParameterGeneration, update.SessionId, update.EditRevision, "stale_edit_revision", "Material edit_revision is older than the resident edit revision.");
            return;
        }
        if (update.AffectedSubmeshes.Any(index => index < 0 || index >= _document.Submeshes.Count))
        {
            WriteMaterialParameterFailed(root, update.ParameterGeneration, update.SessionId, update.EditRevision, "invalid_submesh", "Material parameter update references an unknown submesh.");
            return;
        }

        _lastRequestedMaterialParameterGeneration = update.ParameterGeneration;
        var previous = _materials.CaptureParameterState();
        _materials.ApplyParameterUpdate(update);
        if (!_viewport.TryApplyMaterialParameters(update.AffectedSubmeshes, out var applyError))
        {
            _materials.ReplaceParameterState(previous);
            WriteMaterialParameterFailed(root, update.ParameterGeneration, update.SessionId, update.EditRevision, "renderer_rejected", applyError);
            return;
        }

        RefreshSubmeshList();
        _lastAppliedMaterialParameterGeneration = update.ParameterGeneration;
        _materialParameterAppliedCount++;
        var payload = new Dictionary<string, object?>
        {
            ["session_id"] = update.SessionId,
            ["edit_revision"] = update.EditRevision,
            ["parameter_generation"] = update.ParameterGeneration,
            ["affected_submeshes"] = update.AffectedSubmeshes,
            ["renderer"] = RendererStatusWithLifecycle(),
            ["lifecycle_counts"] = LifecycleCountsPayload(),
            ["capabilities"] = new[] { ResidentMaterialParameterUpdatesCapability },
        };
        CopyMutationEnvelope(root, payload);
        WriteProtocolEvent("material_parameter_applied", payload);
    }

    private static long ProtocolParameterGeneration(JsonElement root)
    {
        if (!root.TryGetProperty("parameter_generation", out var value))
        {
            return 0;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number))
        {
            return number;
        }
        return value.ValueKind == JsonValueKind.String && long.TryParse(value.GetString(), out number)
            ? number
            : 0;
    }

    private void WriteMaterialParameterFailed(JsonElement request, long generation, string sessionId, long editRevision, string reason, string message)
    {
        _materialParameterFailedCount++;
        var payload = new Dictionary<string, object?>
        {
            ["session_id"] = sessionId,
            ["edit_revision"] = editRevision,
            ["parameter_generation"] = generation,
            ["reason"] = reason,
            ["message"] = message,
            ["last_applied_edit_revision"] = _lastAppliedEditRevision,
            ["last_requested_parameter_generation"] = _lastRequestedMaterialParameterGeneration,
            ["last_applied_parameter_generation"] = _lastAppliedMaterialParameterGeneration,
            ["renderer"] = RendererStatusWithLifecycle(),
            ["lifecycle_counts"] = LifecycleCountsPayload(),
            ["capabilities"] = new[] { ResidentMaterialParameterUpdatesCapability },
        };
        CopyMutationEnvelope(request, payload);
        WriteProtocolEvent("material_parameter_failed", payload);
    }

    private void WriteMaterialStateFailed(JsonElement request, long generation, string sessionId, string reason, string message)
    {
        _materialStateFailedCount++;
        var payload = new Dictionary<string, object?>
        {
            ["session_id"] = sessionId,
            ["generation"] = generation,
            ["reason"] = reason,
            ["message"] = message,
            ["material_signature"] = _materials.Signature,
            ["last_applied_generation"] = _lastAppliedMaterialGeneration,
            ["last_applied_edit_revision"] = _lastAppliedEditRevision,
            ["last_observed_session_revision"] = _lastObservedSessionRevision,
            ["renderer"] = RendererStatusWithLifecycle(),
            ["lifecycle_counts"] = LifecycleCountsPayload(),
            ["capabilities"] = new[] { ResidentMaterialUpdatesCapability },
        };
        CopyMutationEnvelope(request, payload);
        WriteProtocolEvent("material_state_failed", payload);
        if (_activateAfterMaterialSync)
        {
            _activateAfterMaterialSync = false;
            _ = ActivateResidentViewport();
        }
    }
}
