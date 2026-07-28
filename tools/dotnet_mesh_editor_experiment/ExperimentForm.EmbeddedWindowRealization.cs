using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// Keeps layout switches from being the first realisation of a hidden subtree
/// while this form is embedded in the host's window, and keeps the window
/// itself off screen until there is something finished to show.
/// </summary>
internal sealed partial class ExperimentForm
{
    private const int WsChild = 0x40000000;
    private const int WsCaption = 0x00C00000;
    private const int WsVisible = 0x10000000;
    private const int WsPopup = unchecked((int)0x80000000);

    private bool _startupRealizationQueued;
    private bool _embeddedWindowRevealed;

    /// <summary>
    /// True when this window can be created directly inside the host's window
    /// instead of being reparented into it after the fact.
    /// </summary>
    private bool EmbedsAtBirth => _options is { Embedded: true, ParentHwnd: > 0 };

    /// <summary>
    /// Creates the embedded window as a child of the host from the outset.
    /// </summary>
    /// <remarks>
    /// Reparenting after creation means the window first exists as a real
    /// top-level window of this process — borderless, at screen (0, 0), and
    /// visible — for as long as startup takes, which is what the user saw as a
    /// flash in the corner of the monitor with the editor assembling inside it.
    /// Born as a child, it has no life outside the host's window to be seen in,
    /// and <see cref="NativeWindowHost.Embed"/> becomes a verification rather
    /// than a reparent, which is also one fewer cross-process SetParent to fail.
    /// WS_VISIBLE is withheld until the reveal and forced on afterwards, rather
    /// than left to the base class. This handle is recreated during startup and
    /// again while the deferred tool panels are attached, and the base style is
    /// read off the outgoing window — which the panel builder's redraw batch
    /// has by then stripped WS_VISIBLE from, since WM_SETREDRAW(FALSE) clears
    /// it. Inheriting that brought the editor back invisible with WinForms
    /// believing it was already shown, so nothing ever showed it again.
    /// </remarks>
    protected override CreateParams CreateParams
    {
        get
        {
            var parameters = base.CreateParams;
            if (!EmbedsAtBirth)
            {
                return parameters;
            }
            parameters.Style |= WsChild;
            parameters.Style &= ~(WsPopup | WsCaption);
            if (_embeddedWindowRevealed)
            {
                parameters.Style |= WsVisible;
            }
            else
            {
                parameters.Style &= ~WsVisible;
            }
            parameters.Parent = new IntPtr(_options.ParentHwnd);
            return parameters;
        }
    }

    /// <summary>
    /// Swallows the show that starting the message loop performs, so the
    /// embedded window stays hidden until its control tree is realised and it
    /// is verified inside the host.
    /// </summary>
    /// <remarks>
    /// <c>Application.Run</c> makes its main form visible as soon as the loop
    /// starts, which is before the constructor's work has been laid out and
    /// before <see cref="RealizeClassicToolFlanks"/> has created the tool
    /// subtree — so the host pane showed WinForms building the editor a panel
    /// at a time. Hiding until <see cref="RevealEmbeddedWindow"/> leaves the
    /// workbench's own "starting" panel up for that whole stretch, and the
    /// editor arrives in one piece. Hide/Show across activation cycles already
    /// works on this form, so the deactivated state is unaffected.
    /// </remarks>
    protected override void SetVisibleCore(bool value)
    {
        // Strictly one-shot. A host that deactivates and reactivates the helper
        // mid-startup drives Hide/Show through here too, and swallowing one of
        // those would leave the editor hidden with nothing left to reveal it.
        if (value && EmbedsAtBirth && !_startupRealizationQueued)
        {
            try
            {
                BeginInvoke(new Action(RunStartupRealization));
            }
            catch (InvalidOperationException)
            {
                // Nothing to post to, so there is no deferred reveal to wait
                // for; show now rather than never.
                base.SetVisibleCore(value);
                return;
            }
            _startupRealizationQueued = true;
            base.SetVisibleCore(false);
            return;
        }
        base.SetVisibleCore(value);
    }

    /// <summary>
    /// The single moment the embedded editor becomes visible, once it is fully
    /// built and sized to the host.
    /// </summary>
    private void RevealEmbeddedWindow()
    {
        _embeddedWindowRevealed = true;
        Visible = true;
        NativeWindowHost.ResizeToParent(
            this,
            new IntPtr(_options.ParentHwnd),
            forceFrameRefresh: true,
            show: true);
        Focus();
        _viewport.Focus();
        WriteProtocolEvent("embedded_window_revealed", new Dictionary<string, object?>
        {
            ["form_visible"] = Visible,
            ["window_visible"] = NativeWindowHost.IsWindowVisibleStyle(Handle),
            ["form_hwnd"] = Handle.ToInt64(),
            ["form_parent_hwnd"] = NativeWindowHost.ParentOf(Handle),
            ["embedded_parent_hwnd"] = _options.ParentHwnd,
            ["client_width"] = ClientSize.Width,
            ["client_height"] = ClientSize.Height,
        });
    }

    /// <summary>
    /// Creates the layout-switched panels' window handles while this form is
    /// still a plain top-level window of this process.
    /// </summary>
    /// <remarks>
    /// Booting straight into mesh edit — which the host does whenever it
    /// launches the helper with Edit Mesh already on — leaves both flanks hidden
    /// and unrealised, because the tool rail claims the sections before the
    /// classic layout ever runs. Realising that subtree later, after the form
    /// has been SetParent-ed into the host's window, makes WinForms create the
    /// controls on its own parking window and then re-parent them, and that
    /// SetParent fails with Win32 5023. Neither condition alone does it: a
    /// standalone helper survives the same reveal, and a placement boot builds
    /// its panels into an already-visible flank. Creating the handles here
    /// leaves the reveal on the way out of mesh edit with nothing to create.
    /// </remarks>
    private void RealizeClassicToolFlanks()
    {
        if (_options.SimplePreview)
        {
            // The read-only preview profile builds no tool panels at all.
            return;
        }
        // Every control whose Visible is flipped when the layout switches, so
        // that no switch is ever the first realisation of its subtree. The rail
        // dock is here for the same reason the flanks are: RevealToolRailPage
        // catches the identical Win32 5023 on a rail button click.
        RealizeControlTree(_leftToolPanel);
        RealizeControlTree(_rightToolPanel);
        RealizeControlTree(_toolDock);
        RealizeControlTree(_sceneInspectorColumn?.Parent?.Parent);
    }

    /// <summary>
    /// Top-down, so each child is created with its real parent already in its
    /// CreateParams. Walking bottom-up would park them exactly like the failure
    /// this exists to prevent.
    /// </summary>
    private static void RealizeControlTree(Control? control)
    {
        if (control is null || control.IsDisposed)
        {
            return;
        }
        _ = control.Handle;
        foreach (Control child in control.Controls)
        {
            RealizeControlTree(child);
        }
    }

    /// <summary>
    /// The classic flanks hit the same deferred-reparent failure as
    /// <see cref="RevealToolRailPage"/>, from the opposite direction: leaving
    /// mesh edit reveals a flank whose subtree the tool rail never realised.
    /// An exception escaping here reaches the UI guard, which exits the process,
    /// so the whole editor vanishes mid-session rather than one panel staying
    /// blank. <see cref="RealizeClassicToolFlanks"/> is what prevents the
    /// failure; this is the backstop that keeps it survivable.
    /// </summary>
    private void RevealToolFlank(Control flank)
    {
        try
        {
            flank.Visible = true;
        }
        catch (System.ComponentModel.Win32Exception ex)
        {
            WriteProtocolEvent("tool_flank_reveal_failed", new Dictionary<string, object?>
            {
                ["flank"] = flank.Name,
                ["native_error"] = ex.NativeErrorCode,
                ["message"] = ex.Message,
                ["embedded"] = _options.Embedded,
                ["embedded_parent_hwnd"] = _options.ParentHwnd,
                ["flank_handle_created"] = flank.IsHandleCreated,
                ["flank_hwnd"] = flank.IsHandleCreated ? flank.Handle.ToInt64() : 0L,
                ["flank_parent_hwnd"] = ToolRailWindowParent(flank),
                ["form_handle_created"] = IsHandleCreated,
                ["form_hwnd"] = IsHandleCreated ? Handle.ToInt64() : 0L,
                ["form_parent_hwnd"] = ToolRailWindowParent(this),
                ["children"] = ToolRailChildDiagnostics(flank),
            });
            _statusLabel.Text =
                $"The {flank.Name} tool panel could not be shown (Win32 {ex.NativeErrorCode}).";
        }
    }
}
