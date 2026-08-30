using System.Drawing;
using Vortice.Direct3D;
using Vortice.Direct3D11.Debug;

namespace Cdmw.MeshEditorExperiment;

internal static class D3D11DebugLayerEvidence
{
    private static readonly string[] HeadlessD3D11GateArguments =
    {
        "--headless-gpu-interaction-soak",
    };

    public static bool RequiredForCurrentProcess()
    {
        var arguments = Environment.GetCommandLineArgs();
        return arguments.Any(argument => HeadlessD3D11GateArguments.Any(
            gate => string.Equals(argument, gate, StringComparison.OrdinalIgnoreCase)));
    }

    public static Dictionary<string, object?> CaptureWarpRenderer(
        ObjDocument document,
        NetMaterialSet materials,
        NetTextureSet textures)
    {
        try
        {
            var scene = NetSceneState.Load(string.Empty, document.Submeshes.Count);
            scene.SetInteractionMode("mesh_edit");
            using var host = new Form
            {
                Text = string.Empty,
                AutoScaleMode = AutoScaleMode.None,
                ClientSize = new Size(640, 480),
                StartPosition = FormStartPosition.Manual,
                Location = new Point(-32000, -32000),
                FormBorderStyle = FormBorderStyle.None,
                ShowInTaskbar = false,
                Visible = false,
            };
            using var viewport = new D3D11MaterialViewport(
                document,
                materials,
                textures,
                scene,
                DriverType.Warp,
                debugLayerRequested: true)
            {
                Dock = DockStyle.Fill,
            };
            host.Controls.Add(viewport);
            host.CreateControl();
            _ = host.Handle;
            NativeWindowHost.ResizeHidden(host, 640, 480);
            host.PerformLayout();
            viewport.CreateControl();
            _ = viewport.Handle;
            if (!viewport.EnsureRendererInitialized())
            {
                return Failure("warp", viewport.LastError);
            }

            viewport.BeginDebugLayerCapture();
            if (!viewport.TryRunHeadlessFrame(out _, out _, out var firstError))
            {
                return Failure("warp", firstError);
            }
            if (!viewport.TryRunHeadlessFrame(out _, out _, out var secondError))
            {
                return Failure("warp", secondError);
            }
            var result = viewport.DebugLayerEvidencePayload();
            result["renderer_frames"] = 2;
            result["host_visible"] = host.Visible;
            result["show_in_taskbar"] = host.ShowInTaskbar;
            result["ok"] = result.GetValueOrDefault("ok") is true
                && !host.Visible
                && !host.ShowInTaskbar;
            return result;
        }
        catch (Exception ex)
        {
            return Failure("warp", ex.Message);
        }
    }

    private static Dictionary<string, object?> Failure(string driverType, string error) => new()
    {
        ["ok"] = false,
        ["driver_type"] = driverType,
        ["debug_layer_requested"] = true,
        ["debug_layer_active"] = false,
        ["capture_started"] = false,
        ["stored_message_count"] = -1L,
        ["discarded_message_count"] = -1L,
        ["error"] = error,
    };
}

internal sealed partial class D3D11MaterialViewport
{
    private bool _debugLayerCaptureStarted;

    public void BeginDebugLayerCapture()
    {
        _debugLayerCaptureStarted = false;
        if (!_debugLayerRequested || _device is null)
        {
            return;
        }
        using var infoQueue = _device.QueryInterface<ID3D11InfoQueue>();
        infoQueue.ClearStorageFilter();
        infoQueue.AddStorageFilterEntries(new InfoQueueFilter
        {
            DenyList = new InfoQueueFilterDescription
            {
                Severities = new[] { MessageSeverity.Info, MessageSeverity.Message },
            },
        });
        infoQueue.ClearStoredMessages();
        _debugLayerCaptureStarted = true;
    }

    public Dictionary<string, object?> DebugLayerEvidencePayload()
    {
        var active = false;
        long storedMessageCount = -1;
        long discardedMessageCount = -1;
        var error = string.Empty;
        if (_debugLayerRequested && _device is not null)
        {
            try
            {
                using var infoQueue = _device.QueryInterface<ID3D11InfoQueue>();
                active = true;
                storedMessageCount = checked((long)infoQueue.NumStoredMessages);
                discardedMessageCount = checked((long)infoQueue.NumMessagesDiscardedByMessageCountLimit);
            }
            catch (Exception ex)
            {
                error = ex.Message;
            }
        }
        var adapterRecorded = !string.IsNullOrWhiteSpace(_adapterDescription);
        var clean = _debugLayerRequested
            && active
            && _debugLayerCaptureStarted
            && storedMessageCount == 0
            && discardedMessageCount == 0
            && adapterRecorded;
        return new Dictionary<string, object?>
        {
            ["ok"] = clean,
            ["driver_type"] = _driverType.ToString().ToLowerInvariant(),
            ["adapter_description"] = _adapterDescription,
            ["adapter_vendor_id"] = _adapterVendorId,
            ["adapter_device_id"] = _adapterDeviceId,
            ["feature_level"] = _featureLevelName,
            ["debug_layer_requested"] = _debugLayerRequested,
            ["debug_layer_active"] = active,
            ["capture_started"] = _debugLayerCaptureStarted,
            ["storage_filter"] = "warning_error_corruption",
            ["stored_message_count"] = storedMessageCount,
            ["discarded_message_count"] = discardedMessageCount,
            ["error"] = error,
        };
    }

    private void AppendD3D11Identity(Dictionary<string, object?> payload)
    {
        payload["driver_type"] = _driverType.ToString().ToLowerInvariant();
        payload["adapter_description"] = _adapterDescription;
        payload["adapter_vendor_id"] = _adapterVendorId;
        payload["adapter_device_id"] = _adapterDeviceId;
        payload["feature_level"] = _featureLevelName;
        payload["debug_layer_requested"] = _debugLayerRequested;
        payload["debug_layer_state"] = _debugLayerRequested
            ? (_device is null ? "unavailable" : "active")
            : "disabled";
    }
}
