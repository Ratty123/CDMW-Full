using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

// The hidden startup of an embedded editor: from a built form to the first
// frame the host is allowed to see. Split from Program.cs to keep that file
// inside the owned-file line cap; same partial class.
internal sealed partial class ExperimentForm
{
    private void QueueReadyAfterFirstFrame(string textureState, string textureError)
    {
        _pendingTextureState = textureState;
        _pendingTextureError = textureError;
        _readyPendingFirstFrame = true;
        StartupTiming.Mark("ready_queued_for_first_frame");
        _statusLabel.Text = "Textures ready; drawing the first .NET/Vortice frame...";
        _viewport.ApplySceneState();
        // The reveal cannot wait for the frame itself — the frame is produced by
        // a paint, and a hidden window never gets one. This is as late as it can
        // go: geometry, materials and textures are all bound, so the first paint
        // draws the finished model rather than an empty viewport.
        //
        // A prewarm launch is the exception and must stay hidden. Its scene is a
        // procedural placeholder nobody asked to see; revealing it painted that
        // placeholder into the host pane and then hid it again the moment the
        // host answered `ready` with `deactivate_request` — a flash of the wrong
        // model at dialog-open time. The host does not need `ready` from a
        // prewarm (it warms the GPU with an offscreen capture instead), and
        // without a reveal there is no paint, so `ready` correctly stays pending
        // until `activate_request` reveals the window over a real package.
        if (!_options.PrewarmLaunch)
        {
            EnsureEmbeddedWindowRevealed();
        }
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        if (_startupRealizationQueued)
        {
            // An embedded window runs its startup while still hidden; this
            // OnShown is that startup's own reveal, not a second entry.
            return;
        }
        RunStartupRealization();
    }

    /// <summary>
    /// Everything between a built form and a window the user should be looking
    /// at. Embedded, this runs hidden (see <see cref="SetVisibleCore"/>) and the
    /// reveal is deferred to the texture load's completion; standalone, it runs
    /// from OnShown as before.
    /// </summary>
    /// <remarks>
    /// The reveal used to sit here, before <see cref="StartTextureLoad"/>, which
    /// meant the host pane showed a fully built but untextured editor for the
    /// whole texture decode — the chrome arriving seconds before the model, read
    /// as the editor loading in stages. It sat here because it had to: the D3D11
    /// device was created by the first paint, a hidden window never paints, and
    /// <c>TryApplyMaterialState</c> fails outright without a device. Initialising
    /// the renderer explicitly breaks that dependency, so the window can stay
    /// hidden until there is a finished picture to show.
    /// </remarks>
    private void RunStartupRealization()
    {
        _startupRealizationQueued = true;
        StartupTiming.Mark("startup_realization_begin");
        // Build the expensive authoring tree while the Qt host still shows its
        // loading surface. Besides moving the cost off the Edit Mesh click,
        // this ensures the first visible WinForms frame contains one settled
        // layout instead of controls being attached and repainted in stages.
        if (DeferAuthoringToolPanels && !_options.SimplePreview)
        {
            EnsureAuthoringToolPanelsReady();
        }
        StartupTiming.Mark("authoring_tool_panels_ready");
        bool rendererInitialized;
        using (SuspendLayoutTree(_leftToolSplit))
        {
            // Handle creation and the embed both re-lay out the flanks, and the
            // window is still hidden; one pass when this closes is enough.
            //
            // Must precede the reveal: no layout switch may be the first
            // realisation of its subtree, and none of that realisation should be
            // something the user watches happen.
            RealizeClassicToolFlanks();
            StartupTiming.Mark("classic_tool_flanks_realized");
            if (_options.Embedded && !TryEmbedOrFail("startup"))
            {
                return;
            }
            StartupTiming.Mark("embedded_in_host");
            ApplySavedToolPanelLayout();
            StartupTiming.Mark("embedded_and_layout_applied");
            // EnsureRendererInitialized needs the viewport's handle, and nothing has
            // forced it while the form is hidden.
            RealizeControlTree(_viewport);
            StartupTiming.Mark("viewport_handles_realized");
            rendererInitialized = _viewport.EnsureRendererInitialized();
            StartupTiming.Mark("renderer_ensured");
        }
        StartupTiming.Mark("startup_realization_layout_settled");
        if (!rendererInitialized)
        {
            // Not fatal, and not worth blocking the reveal over: the first paint
            // still creates the device the way it always did, and a renderer that
            // genuinely cannot start reports through the texture/ready path.
            WriteProtocolEvent("renderer_prewarm_skipped", new Dictionary<string, object?>
            {
                ["reason"] = _viewport.RendererBlocked ? _viewport.RendererBlockReason : "device not ready before reveal",
                ["embedded"] = _options.Embedded,
                ["prewarm_launch"] = _options.PrewarmLaunch,
            });
            if (!_options.PrewarmLaunch)
            {
                EnsureEmbeddedWindowRevealed();
            }
        }
        StartTextureLoad();
    }

    private void PublishReady(string textureState, string textureError)
    {
        if (_readyPublished)
        {
            return;
        }
        _readyPublished = true;
        // Every terminal texture failure publishes ready directly, without ever
        // reaching QueueReadyAfterFirstFrame. Without this the editor would stay
        // hidden behind the host's spinner with the error only in a status line
        // nobody can see. A failed prewarm still stays hidden: nobody asked to
        // see it, and the host simply launches again for the real package.
        if (!_options.PrewarmLaunch)
        {
            EnsureEmbeddedWindowRevealed();
        }
        var rendererStatus = RendererStatusWithLifecycle();
        WriteStatus(
            _options,
            _viewport.RendererBlocked ? "blocked_renderer_unavailable" : "loaded",
            _viewport.RendererBlocked ? _viewport.RendererBlockReason : "Mesh loaded in .NET editor experiment.",
            _viewport.Metrics,
            rendererStatus: rendererStatus);
        StartupTiming.Mark("ready_published");
        WriteProtocolEvent("startup_timing", StartupTiming.Payload(this));
        StartupTiming.Seal();
        WriteProtocolEvent("ready", new Dictionary<string, object?>
        {
            ["capabilities"] = _viewport.ActiveCapabilities(),
            ["profile"] = _options.Profile,
            ["selection_depth_mode"] = "visible",
            ["tool_enabled"] = !string.Equals(_viewport.ActiveTool, "orbit", StringComparison.OrdinalIgnoreCase),
            ["tool"] = _viewport.ActiveTool,
            ["target_mode"] = _viewport.CurrentTargetMode(),
            ["selection_mode"] = SelectionText(_selectionShape, "brush"),
            ["selection_operation"] = SelectionOperation(),
            ["material_signature"] = _materials.Signature,
            ["material_generation"] = _materials.Generation,
            ["texture_state"] = textureState,
            ["texture_error"] = textureError,
            ["renderer"] = rendererStatus,
            ["lifecycle_counts"] = LifecycleCountsPayload(),
            ["local_selection"] = _viewport.SelectionSnapshotPayload(),
            ["selected_part_index"] = _viewport.SelectedSubmeshIndex,
            ["parts_list_selected_index"] = _submeshList.SelectedIndex,
            ["parts_list_selected_indices"] = _submeshList.SelectedIndices.Cast<int>().ToArray(),
        });
    }

    private bool TryEmbedOrFail(string phase)
    {
        // Before the first reveal this only verifies and sizes the window the
        // constructor already created inside the host; forcing it on screen
        // here is what RevealEmbeddedWindow is for.
        if (NativeWindowHost.Embed(this, new IntPtr(_options.ParentHwnd), reveal: _embeddedWindowRevealed))
        {
            _statusLabel.Text = "Embedded .NET mesh editor ready.";
            if (_embeddedWindowRevealed)
            {
                Focus();
                _viewport.Focus();
            }
            return true;
        }
        _embeddedViewportActive = false;
        _embeddedHostFailed = true;
        var message = $"Embedded host unavailable during {phase}; returning to the native mesh editor.";
        _statusLabel.Text = message;
        WriteStatus(_options, "error", message, _viewport.Metrics, rendererStatus: RendererStatusWithLifecycle());
        WriteProtocolEvent("error", new Dictionary<string, object?>
        {
            ["code"] = "embedded_host_unavailable",
            ["phase"] = phase,
            ["message"] = message
        });
        Close();
        return false;
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        SaveToolPanelLayout();
        CancelResidentPackageLoad();
        CancelPerformanceCaptureForShutdown();
        FlushPendingPlacementTransform(force: true);
        if (!_saved && !_embeddedHostFailed && _options.Embedded && _editedSubmeshes.Count > 0 && !_externalTopologyDirty)
        {
            SaveAndReport();
        }
        if (!_saved && !_embeddedHostFailed)
        {
            WriteStatus(
                _options,
                "closed",
                "Mesh .NET editor experiment closed without saving.",
                _viewport.Metrics,
                rendererStatus: RendererStatusWithLifecycle());
        }
        _textureSet.Dispose();
        base.OnFormClosing(e);
    }


    /// <summary>
    /// Take the host's size now, before a single child exists.
    /// </summary>
    /// <remarks>
    /// The startup realisation embeds and sizes this window again later, and
    /// when that changed the size from the constructor's default it re-laid out
    /// the whole finished tool tree at a new width: the most expensive resize
    /// the editor ever does, spent on a window nobody could see yet. Taking the
    /// final size first makes that later resize a no-op. A host that has no
    /// usable size yet keeps the default; the realisation corrects it.
    /// </remarks>
    private void TakeHostSizeBeforeChildren(LaunchOptions options)
    {
        if (EmbedsAtBirth
            && NativeWindowHost.TryGetClientSize(new IntPtr(options.ParentHwnd), out var hostClientSize)
            && hostClientSize.Width >= 200
            && hostClientSize.Height >= 200)
        {
            NativeWindowHost.ResizeToParent(this, new IntPtr(options.ParentHwnd), forceFrameRefresh: false, show: false);
        }
    }

    /// <summary>
    /// From here on every startup mark is also a protocol event, so the host can
    /// tell a helper that is still building from one that hung. A headless smoke
    /// has no host and no protocol stream to report to.
    /// </summary>
    private void StartStartupProgressReporting(LaunchOptions options)
    {
        StartupTiming.Reporter = options.HeadlessSmoke
            ? null
            : (phase, atMs) => WriteProtocolEvent("startup_progress", new Dictionary<string, object?>
            {
                ["phase"] = phase,
                ["at_ms"] = Math.Round(atMs, 1),
            });
    }

    /// <summary>
    /// Booting into mesh edit moves every rail section into its page; one
    /// closing layout pass covers all of those moves.
    /// </summary>
    private void ApplyInteractionModeControlsUnderOneLayout()
    {
        using (SuspendLayoutTree(_leftToolSplit))
        {
            ApplyInteractionModeControls();
        }
    }
}
