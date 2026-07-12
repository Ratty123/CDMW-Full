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

    private Dictionary<string, object?> LifecycleCountsPayload()
    {
        return new Dictionary<string, object?>
        {
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
        };
    }

    private Dictionary<string, object?> RendererStatusWithLifecycle()
    {
        var renderer = _viewport.RendererStatusPayload();
        renderer["lifecycle_counts"] = LifecycleCountsPayload();
        renderer["material_generation"] = _materials.Generation;
        renderer["last_requested_material_generation"] = _lastRequestedMaterialGeneration;
        renderer["last_applied_material_generation"] = _lastAppliedMaterialGeneration;
        renderer["last_requested_material_parameter_generation"] = _lastRequestedMaterialParameterGeneration;
        renderer["last_applied_material_parameter_generation"] = _lastAppliedMaterialParameterGeneration;
        return renderer;
    }

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
        NetMaterialStateUpdate update;
        try
        {
            update = _materials.NormalizeStateUpdate(NetMaterialSet.ParseStateUpdate(root));
        }
        catch (Exception ex) when (ex is InvalidDataException or IOException or ArgumentException or NotSupportedException or OverflowException)
        {
            WriteMaterialStateFailed(0, string.Empty, "invalid_payload", ex.Message);
            return;
        }

        if (update.Generation <= 0)
        {
            WriteMaterialStateFailed(update.Generation, update.SessionId, "invalid_generation", "Material generation must be positive.");
            return;
        }
        if (string.IsNullOrWhiteSpace(update.MaterialSignature))
        {
            WriteMaterialStateFailed(update.Generation, update.SessionId, "invalid_signature", "Material state update requires material_signature.");
            return;
        }
        if (!AcceptMaterialSession(update.SessionId, out var sessionError))
        {
            WriteMaterialStateFailed(update.Generation, update.SessionId, "session_mismatch", sessionError);
            return;
        }
        if (update.Generation <= _lastRequestedMaterialGeneration)
        {
            WriteMaterialStateFailed(update.Generation, update.SessionId, "stale_or_out_of_order", "Material generation is not newer than the last request.");
            return;
        }
        if (!CanApplyMaterialEditRevision(update.EditRevision, out var revisionError))
        {
            WriteMaterialStateFailed(update.Generation, update.SessionId, revisionError, "Material edit revision does not match the resident session revision.");
            return;
        }
        if (update.AffectedSubmeshes.Any(index => index < 0 || index >= _document.Submeshes.Count))
        {
            WriteMaterialStateFailed(update.Generation, update.SessionId, "invalid_submesh", "Material update references an unknown submesh.");
            return;
        }

        _lastRequestedMaterialGeneration = update.Generation;
        var affectedResourceIds = update.ResourceIdsForAffectedSubmeshes();
        var resourcesToDecode = update.Resources.Where(resource => affectedResourceIds.Contains(resource.ResourceId)).ToArray();
        _ = _textureSet.DecodeResourcesAsync(resourcesToDecode).ContinueWith(task =>
        {
            if (IsDisposed || Disposing || !IsHandleCreated)
            {
                return;
            }
            try
            {
                BeginInvoke(new Action(() => CompleteMaterialStateUpdate(update, task)));
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

    private void CompleteMaterialStateUpdate(NetMaterialStateUpdate update, Task<NetTextureDecodeResult> task)
    {
        if (update.Generation != _lastRequestedMaterialGeneration)
        {
            WriteMaterialStateFailed(update.Generation, update.SessionId, "superseded", "A newer material generation replaced this request.");
            return;
        }
        if (!CanApplyMaterialEditRevision(update.EditRevision, out var revisionError))
        {
            WriteMaterialStateFailed(update.Generation, update.SessionId, revisionError, "Material edit revision changed while textures were decoding.");
            return;
        }
        if (task.IsCanceled || task.IsFaulted)
        {
            var message = task.Exception?.GetBaseException().Message ?? "Material texture decode was cancelled.";
            WriteMaterialStateFailed(update.Generation, update.SessionId, "texture_decode_failed", message);
            return;
        }
        var decode = task.Result;
        if (!decode.Ok)
        {
            var message = string.Join("; ", decode.Failures.Select(pair => $"{pair.Key}: {pair.Value}"));
            WriteMaterialStateFailed(update.Generation, update.SessionId, "texture_decode_failed", message);
            return;
        }

        var previous = _materials.CaptureState();
        var next = _materials.BuildState(update);
        var missingResource = next.Submeshes
            .Where(binding => update.AffectedSubmeshes.Contains(binding.SubmeshIndex))
            .SelectMany(binding => binding.ResourceChannels.Values)
            .FirstOrDefault(resourceId => !next.Resources.ContainsKey(resourceId));
        if (!string.IsNullOrWhiteSpace(missingResource))
        {
            WriteMaterialStateFailed(update.Generation, update.SessionId, "missing_resource", $"Material resource {missingResource} was not supplied.");
            return;
        }

        _materials.ReplaceState(next);
        if (!_viewport.TryApplyMaterialState(update.AffectedSubmeshes, out var bindError))
        {
            _materials.ReplaceState(previous);
            WriteMaterialStateFailed(update.Generation, update.SessionId, "d3d_binding_failed", bindError);
            return;
        }
        _textureSet.PruneToResources(_materials.TextureLoadResources());
        RefreshSubmeshList();

        _lastAppliedMaterialGeneration = update.Generation;
        _materialStateAppliedCount++;
        MarkEditRevisionApplied(update.EditRevision, "material_state_update");
        WriteProtocolEvent("material_state_applied", new Dictionary<string, object?>
        {
            ["session_id"] = update.SessionId,
            ["edit_revision"] = update.EditRevision,
            ["generation"] = update.Generation,
            ["material_signature"] = _materials.Signature,
            ["affected_submeshes"] = update.AffectedSubmeshes,
            ["decoded_resources"] = decode.Decoded,
            ["reused_resources"] = decode.Reused,
            ["renderer"] = RendererStatusWithLifecycle(),
            ["lifecycle_counts"] = LifecycleCountsPayload(),
            ["capabilities"] = new[] { ResidentMaterialUpdatesCapability },
        });
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
                ProtocolParameterGeneration(root),
                JsonString(root, "session_id"),
                ProtocolEditRevision(root),
                "invalid_payload",
                ex.Message);
            return;
        }

        if (update.ParameterGeneration <= 0)
        {
            WriteMaterialParameterFailed(update.ParameterGeneration, update.SessionId, update.EditRevision, "invalid_generation", "Material parameter_generation must be positive.");
            return;
        }
        if (update.EditRevision < 0)
        {
            WriteMaterialParameterFailed(update.ParameterGeneration, update.SessionId, update.EditRevision, "invalid_revision", "Material edit_revision cannot be negative.");
            return;
        }
        if (!AcceptMaterialSession(update.SessionId, out var sessionError))
        {
            WriteMaterialParameterFailed(update.ParameterGeneration, update.SessionId, update.EditRevision, "session_mismatch", sessionError);
            return;
        }
        if (update.ParameterGeneration <= _lastRequestedMaterialParameterGeneration)
        {
            WriteMaterialParameterFailed(update.ParameterGeneration, update.SessionId, update.EditRevision, "stale_or_out_of_order", "Material parameter_generation is not newer than the last request.");
            return;
        }
        if (update.EditRevision < _lastAppliedEditRevision)
        {
            WriteMaterialParameterFailed(update.ParameterGeneration, update.SessionId, update.EditRevision, "stale_edit_revision", "Material edit_revision is older than the resident edit revision.");
            return;
        }
        if (update.AffectedSubmeshes.Any(index => index < 0 || index >= _document.Submeshes.Count))
        {
            WriteMaterialParameterFailed(update.ParameterGeneration, update.SessionId, update.EditRevision, "invalid_submesh", "Material parameter update references an unknown submesh.");
            return;
        }

        _lastRequestedMaterialParameterGeneration = update.ParameterGeneration;
        var previous = _materials.CaptureParameterState();
        _materials.ApplyParameterUpdate(update);
        if (!_viewport.TryApplyMaterialParameters(update.AffectedSubmeshes, out var applyError))
        {
            _materials.ReplaceParameterState(previous);
            WriteMaterialParameterFailed(update.ParameterGeneration, update.SessionId, update.EditRevision, "renderer_rejected", applyError);
            return;
        }

        RefreshSubmeshList();
        _lastAppliedMaterialParameterGeneration = update.ParameterGeneration;
        _materialParameterAppliedCount++;
        WriteProtocolEvent("material_parameter_applied", new Dictionary<string, object?>
        {
            ["session_id"] = update.SessionId,
            ["edit_revision"] = update.EditRevision,
            ["parameter_generation"] = update.ParameterGeneration,
            ["affected_submeshes"] = update.AffectedSubmeshes,
            ["renderer"] = RendererStatusWithLifecycle(),
            ["lifecycle_counts"] = LifecycleCountsPayload(),
            ["capabilities"] = new[] { ResidentMaterialParameterUpdatesCapability },
        });
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

    private void WriteMaterialParameterFailed(long generation, string sessionId, long editRevision, string reason, string message)
    {
        _materialParameterFailedCount++;
        WriteProtocolEvent("material_parameter_failed", new Dictionary<string, object?>
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
        });
    }

    private void WriteMaterialStateFailed(long generation, string sessionId, string reason, string message)
    {
        _materialStateFailedCount++;
        WriteProtocolEvent("material_state_failed", new Dictionary<string, object?>
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
        });
        if (_activateAfterMaterialSync)
        {
            _activateAfterMaterialSync = false;
            _ = ActivateResidentViewport();
        }
    }
}
