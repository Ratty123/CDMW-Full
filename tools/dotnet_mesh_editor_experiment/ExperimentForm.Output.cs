using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private readonly ProtocolOutputWriter _protocolOutput = new();

    private void WriteProtocolEvent(string eventName, Dictionary<string, object?>? payload = null)
    {
        var message = payload is null
            ? new Dictionary<string, object?>()
            : new Dictionary<string, object?>(payload);
        message["event"] = eventName;
        if (IsMutatingProtocolRequest(eventName))
        {
            message["session_id"] = _residentMaterialSessionId;
            message["request_id"] = ++_outgoingMutationRequestSequence;
            message["base_revision"] = Math.Max(_lastAppliedEditRevision, _lastObservedSessionRevision);
            message["revision"] = Math.Max(_lastAppliedEditRevision, _lastObservedSessionRevision);
            message["edit_revision"] = Math.Max(_lastAppliedEditRevision, _lastObservedSessionRevision);
            message["process_generation"] = _residentProcessGeneration;
            message["protocol_version"] = 2;
            if (string.Equals(eventName, "save_request", StringComparison.OrdinalIgnoreCase))
            {
                // Finish is itself the renderer's last authoritative view of the
                // scene. Carry that identity so the host can still issue the
                // placement transition if its cached Python frame was released
                // while the resident package stayed alive.
                message["source_identity"] = _scene.SourceIdentity;
            }
            RegisterOutgoingMutation(eventName, message);
        }
        _diagnosticProtocolObserver?.Invoke(eventName, message);
        if (string.Equals(eventName, "metrics", StringComparison.OrdinalIgnoreCase))
        {
            _protocolOutput.EnqueueLatestTelemetry(message);
        }
        else
        {
            _protocolOutput.EnqueueCritical(message);
        }
    }

    public bool DrainProtocolOutput(TimeSpan grace) => _protocolOutput.WaitForDrain(grace);

    private void WritePreparedProtocolEventThreadSafe(
        string eventName,
        IReadOnlyDictionary<string, object?> payload)
    {
        var message = new Dictionary<string, object?>(payload)
        {
            ["event"] = eventName,
        };
        _protocolOutput.EnqueueCritical(message);
    }

    private static bool IsMutatingProtocolRequest(string eventName) => eventName.Trim().ToLowerInvariant() switch
    {
        "select_request" or
        "selection_request" or
        "stroke_begin" or
        "stroke_update" or
        "stroke_end" or
        "stroke_cancel" or
        "command_request" or
        "placement_transform_request" or
        "capture_request" or
        "save_request" => true,
        _ => false,
    };

    private void SaveAndReport()
    {
        SaveOutput(_options, _document, _editedSubmeshes, _viewport.Metrics, RendererStatusWithLifecycle());
        _saved = true;
        _statusLabel.Text = $"Saved edited package: {_options.OutputDir}";
    }

    public static void SaveOutput(
        LaunchOptions options,
        ObjDocument document,
        IEnumerable<int> editedSubmeshIndices,
        RenderMetrics metrics,
        Dictionary<string, object?>? rendererStatus = null)
    {
        Directory.CreateDirectory(options.OutputDir);
        var outputObj = Path.Combine(options.OutputDir, "mesh.obj");
        var scene = NetSceneState.Load(options.ScenePath, document.Submeshes.Count);
        document.Save(outputObj, options.MeshPath, scene.EditableSubmeshCount);
        var outputSidecar = outputObj + ".meta.json";
        if (File.Exists(options.MetadataPath))
        {
            File.Copy(options.MetadataPath, outputSidecar, overwrite: true);
        }
        WriteEditOperations(options, document, editedSubmeshIndices);
        WriteStatus(
            options,
            "saved",
            "Mesh .NET editor experiment saved edited package.",
            metrics,
            outputObj,
            rendererStatus);
    }

    public static void WriteStatus(
        LaunchOptions options,
        string eventName,
        string message,
        RenderMetrics? metrics,
        string? editedMeshPath = null,
        Dictionary<string, object?>? rendererStatus = null)
    {
        var payload = new Dictionary<string, object?>
        {
            ["event"] = eventName,
            ["message"] = message,
            ["edited_package"] = options.OutputDir,
            ["edited_mesh"] = editedMeshPath ?? Path.Combine(options.OutputDir, "mesh.obj"),
            ["edit_operations"] = options.EditOperationsPath,
            ["authority_contract"] = "dotnet_viewport_python_cpp_validation",
            ["parser_authority"] = "cdmw_python_cpp",
            ["rebuild_authority"] = "cdmw_python_cpp",
            ["archive_write_authority"] = "cdmw_python_cpp",
            ["renderer"] = rendererStatus ?? new Dictionary<string, object?>
            {
                ["backend"] = "not_reported",
            },
            ["metrics"] = new Dictionary<string, object?>
            {
                ["average_fps"] = metrics?.AverageFps,
                ["frame_time_ms"] = metrics?.AverageFrameMs,
                ["render_time_ms"] = metrics?.AverageRenderMs,
                ["frame_interval_ms"] = metrics?.AverageFrameIntervalMs,
                ["frame_interval_p95_ms"] = metrics?.FrameIntervalP95Ms,
                ["frame_interval_max_ms"] = metrics?.FrameIntervalMaxMs,
                ["frame_pacing_jitter_ms"] = metrics?.FramePacingJitterMs,
                ["present_time_ms"] = metrics?.AveragePresentMs,
                ["dirty_to_present_ms"] = metrics?.AverageDirtyToPresentMs,
                ["dropped_frames"] = metrics?.DroppedFrames,
                ["responsiveness_ms"] = metrics?.AverageResponsivenessMs,
                ["memory_mb"] = Process.GetCurrentProcess().WorkingSet64 / (1024.0 * 1024.0),
                ["packaging_complexity"] = "external .NET WinForms process; parser/rebuilder stay in Python/C++",
                ["maintenance_complexity"] = "UI-only prototype bridge",
                ["crash_behavior"] = eventName == "error" ? "error" : "no crash reported"
            }
        };
        var statusPath = Path.GetFullPath(options.StatusPath);
        Directory.CreateDirectory(Path.GetDirectoryName(statusPath) ?? Environment.CurrentDirectory);
        var stagingPath = $"{statusPath}.{Guid.NewGuid():N}.tmp";
        var backupPath = $"{statusPath}.{Guid.NewGuid():N}.bak";
        var statusKey = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(statusPath.ToUpperInvariant())));
        using var statusMutex = new Mutex(false, $@"Local\CDMW.MeshEditorExperiment.Status.{statusKey}");
        var ownsStatusMutex = false;
        try
        {
            File.WriteAllText(
                stagingPath,
                JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }),
                Utf8NoBom);
            try
            {
                ownsStatusMutex = statusMutex.WaitOne(TimeSpan.FromSeconds(1));
            }
            catch (AbandonedMutexException)
            {
                ownsStatusMutex = true;
            }
            if (!ownsStatusMutex)
            {
                throw new IOException($"Timed out waiting to publish Mesh Editor status '{statusPath}'.");
            }
            if (File.Exists(statusPath))
            {
                File.Replace(stagingPath, statusPath, backupPath);
            }
            else
            {
                File.Move(stagingPath, statusPath);
            }
        }
        finally
        {
            if (ownsStatusMutex)
            {
                statusMutex.ReleaseMutex();
            }
            if (File.Exists(stagingPath))
            {
                File.Delete(stagingPath);
            }
            if (File.Exists(backupPath))
            {
                File.Delete(backupPath);
            }
        }
    }

    public static int[] ApplyHeadlessSmokeEdit(ObjDocument document)
    {
        if (document.Submeshes.Count == 0 || document.Submeshes[0].Vertices.Count == 0)
        {
            return Array.Empty<int>();
        }
        var submesh = document.Submeshes[0];
        for (var i = 0; i < submesh.Vertices.Count; i++)
        {
            var vertex = submesh.Vertices[i];
            submesh.Vertices[i] = vertex with { X = vertex.X + 0.001f };
        }
        return new[] { 0 };
    }

    private static void WriteEditOperations(
        LaunchOptions options,
        ObjDocument document,
        IEnumerable<int> editedSubmeshIndices)
    {
        var editableSubmeshCount = NetSceneState.Load(options.ScenePath, document.Submeshes.Count).EditableSubmeshCount;
        var operations = editedSubmeshIndices
            .Where(index => index >= 0 && index < editableSubmeshCount)
            .OrderBy(index => index)
            .Select(index => new Dictionary<string, object?>
            {
                ["operation"] = "replace_positions_same_count",
                ["lod_index"] = 0,
                ["submesh_index"] = index,
                ["vertex_count"] = document.Submeshes[index].Vertices.Count,
                ["source"] = "mesh.obj",
                ["created_by"] = "CDMW .NET Mesh Editor Experiment",
                ["metadata"] = new Dictionary<string, object?>
                {
                    ["authority_contract"] = "dotnet_viewport_python_cpp_validation",
                    ["viewport_authority"] = "dotnet_local_interaction_state",
                    ["validation_authority"] = "cdmw_python_cpp",
                    ["native_authoritative_operation_required"] = true
                }
            })
            .ToArray();
        var payload = new Dictionary<string, object?> { ["operations"] = operations };
        File.WriteAllText(
            options.EditOperationsPath,
            JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }),
            Utf8NoBom);
    }
}
