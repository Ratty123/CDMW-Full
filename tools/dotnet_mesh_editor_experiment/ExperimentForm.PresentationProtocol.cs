using System.Text.Json;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private readonly Dictionary<string, Button> _presentationViewButtons =
        new(StringComparer.OrdinalIgnoreCase);
    private readonly List<Label> _navigationChipBadges = new();
    private TableLayoutPanel? _presentationViewSelector;
    private Label? _viewportNavigationPrimary;
    private Label? _orbitChipBadge;
    private Label? _panChipBadge;
    private bool _presentationHeaderDividerDragging;

    private Control BuildPresentationViewportRegion()
    {
        var simplePreview = _options.SimplePreview;
        var region = new TableLayoutPanel
        {
            Name = "ResidentRoleViewRegion",
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = simplePreview ? 2 : 3,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemeWindowBackground,
        };
        region.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        if (simplePreview)
        {
            region.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            region.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
        }
        else
        {
            region.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
            region.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            region.RowStyles.Add(new RowStyle(SizeType.Absolute, Math.Max(32, _statusLabel.Height + 6)));
        }
        var selector = new TableLayoutPanel
        {
            Name = "ResidentRoleViewSelector",
            Dock = DockStyle.Fill,
            ColumnCount = 3,
            RowCount = 1,
            Padding = new Padding(0),
            Margin = new Padding(0),
            BackColor = ThemePanelBackground,
        };
        selector.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 1));
        selector.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 8));
        selector.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 1));
        selector.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _presentationViewSelector = simplePreview ? null : selector;
        if (!simplePreview)
        {
            AddPresentationViewButton(selector, "Original (focus)", "reference", 0);
            AddPresentationViewButton(selector, "Imported / Modify (focus)", "editable", 2);
        }
        var divider = new Panel
        {
            Name = "ResidentRoleViewHeaderDivider",
            Dock = DockStyle.Fill,
            Margin = new Padding(0),
            BackColor = Color.FromArgb(190, 198, 207),
            Cursor = Cursors.VSplit,
        };
        divider.MouseDown += (_, e) =>
        {
            if (e.Button != MouseButtons.Left) return;
            _presentationHeaderDividerDragging = true;
            divider.Capture = true;
        };
        divider.MouseMove += (_, e) =>
        {
            if (!_presentationHeaderDividerDragging) return;
            var point = selector.PointToClient(divider.PointToScreen(e.Location));
            _viewport.SetPaneSplitRatio((float)point.X / Math.Max(1, selector.ClientSize.Width));
        };
        divider.MouseUp += (_, e) =>
        {
            if (!_presentationHeaderDividerDragging) return;
            _presentationHeaderDividerDragging = false;
            divider.Capture = false;
            var point = selector.PointToClient(divider.PointToScreen(e.Location));
            _viewport.SetPaneSplitRatio(
                (float)point.X / Math.Max(1, selector.ClientSize.Width),
                notifyHost: true);
        };
        if (!simplePreview)
        {
            selector.Controls.Add(divider, 1, 0);
            selector.Resize += (_, _) => UpdatePresentationHeaderSplit();
            _viewport.PaneSplitRatioChanged += _ => UpdatePresentationHeaderSplit();
            _viewport.ActivePresentationPaneChanged += _ => UpdatePresentationViewButtons();
            region.Controls.Add(selector, 0, 0);
        }
        region.Controls.Add(_viewport, 0, simplePreview ? 0 : 1);
        _controlsHintLabel.Name = "ResidentViewportControlsHint";
        _controlsHintLabel.Dock = DockStyle.Fill;
        _controlsHintLabel.Margin = new Padding(0);
        _controlsHintLabel.Padding = new Padding(10, 0, 10, 0);
        _controlsHintLabel.BackColor = ThemeStatusBackground;
        _controlsHintLabel.ForeColor = ThemeMutedText;
        _controlsHintLabel.TextAlign = ContentAlignment.MiddleLeft;
        _controlsHintLabel.AutoEllipsis = true;
        if (simplePreview)
        {
            region.Controls.Add(_controlsHintLabel, 0, 1);
        }
        else
        {
            region.Controls.Add(BuildAuthoringStatusFooter(), 0, 2);
        }
        UpdateViewportControlsHint();
        if (!simplePreview)
        {
            UpdatePresentationHeaderSplit();
        }
        UpdatePresentationViewButtons();
        return region;
    }

    /// <summary>
    /// The permanent camera legend along the bottom of the editor: the active
    /// tool on the left, then the modifier bindings that orbit, pan and zoom. It
    /// is always on screen because the bindings only matter once an edit tool
    /// has taken the left button, which is exactly when there is nothing left to
    /// discover them from.
    /// </summary>
    /// <remarks>
    /// It spans the whole window rather than sitting inside the viewport region.
    /// Both tool flanks are open in Edit Mesh, which leaves the viewport column
    /// around 380 px: a third of what these bindings need to read, and
    /// <see cref="FlowLayoutPanel"/> clips rather than wraps them.
    /// </remarks>
    private Control BuildViewportNavigationStrip()
    {
        var strip = new FlowLayoutPanel
        {
            Name = "ResidentViewportNavigationStrip",
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            AutoScroll = false,
            Margin = new Padding(0),
            Padding = new Padding(10, 3, 10, 3),
            BackColor = ThemeStatusBackground,
        };
        _viewportNavigationPrimary = new Label
        {
            Name = "ResidentViewportNavigationTool",
            AutoSize = true,
            UseMnemonic = false,
            TextAlign = ContentAlignment.MiddleLeft,
            Margin = new Padding(0, 4, 16, 0),
            BackColor = ThemeStatusBackground,
            ForeColor = ThemeStrongText,
            Font = new Font(Font, FontStyle.Bold),
        };
        strip.Controls.Add(_viewportNavigationPrimary);
        strip.Controls.Add(NavigationChip("Orbit", out _orbitChipBadge));
        strip.Controls.Add(NavigationChip("Pan", out _panChipBadge));
        strip.Controls.Add(NavigationChip("Zoom", out var zoomBadge));
        zoomBadge.Text = "Wheel";
        return strip;
    }

    /// <summary>
    /// One binding on the navigation strip: the keys in a badge, the camera
    /// move they perform beside it. The badge is written by
    /// <see cref="UpdateViewportNavigationStrip"/> because orbit and pan are
    /// rebindable and the strip has to name whatever they are bound to now.
    /// </summary>
    private Control NavigationChip(string action, out Label badge)
    {
        var chip = new FlowLayoutPanel
        {
            Name = $"ResidentViewportNavigationChip{action}",
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            Margin = new Padding(0, 0, 14, 0),
            Padding = new Padding(0),
            BackColor = ThemeStatusBackground,
        };
        badge = new Label
        {
            AutoSize = true,
            UseMnemonic = false,
            TextAlign = ContentAlignment.MiddleCenter,
            Margin = new Padding(0, 1, 6, 1),
            Padding = new Padding(6, 2, 6, 2),
            BackColor = ThemeButtonBackground,
            ForeColor = ThemeStrongText,
        };
        var label = new Label
        {
            Text = action,
            AutoSize = true,
            UseMnemonic = false,
            TextAlign = ContentAlignment.MiddleLeft,
            Margin = new Padding(0, 4, 0, 0),
            BackColor = ThemeStatusBackground,
            ForeColor = ThemeMutedText,
        };
        chip.Controls.Add(badge);
        chip.Controls.Add(label);
        _navigationChipBadges.Add(badge);
        return chip;
    }

    private void UpdateViewportNavigationStrip(string activeTool, bool modifiersOwnTheCamera)
    {
        if (_viewportNavigationPrimary is not null)
        {
            _viewportNavigationPrimary.Text = activeTool;
        }
        // Written from the live bindings rather than baked in, because the
        // modifiers and the middle/right drags are all rebindable from Model
        // Preview Settings > Controls. Each combination is a whole literal so
        // it stays one translatable phrase per binding.
        if (_orbitChipBadge is not null)
        {
            _orbitChipBadge.Text = CameraGestureBadgeText(
                _viewport.CameraOrbitModifier,
                middleDrag: string.Equals(
                    _viewport.CameraMiddleDrag, CameraModifierBindings.DragOrbit, StringComparison.Ordinal),
                rightDrag: string.Equals(
                    _viewport.CameraRightDrag, CameraModifierBindings.DragOrbit, StringComparison.Ordinal));
        }
        if (_panChipBadge is not null)
        {
            _panChipBadge.Text = CameraGestureBadgeText(
                _viewport.CameraPanModifier,
                middleDrag: string.Equals(
                    _viewport.CameraMiddleDrag, CameraModifierBindings.DragPan, StringComparison.Ordinal),
                rightDrag: string.Equals(
                    _viewport.CameraRightDrag, CameraModifierBindings.DragPan, StringComparison.Ordinal));
        }
        foreach (var badge in _navigationChipBadges)
        {
            badge.BackColor = modifiersOwnTheCamera ? ThemeAccent : ThemeButtonBackground;
            badge.ForeColor = modifiersOwnTheCamera ? Color.White : ThemeStrongText;
        }
    }

    /// <summary>
    /// The gestures that perform one camera move, as one whole translatable
    /// phrase: the bound modifier plus whichever of the middle and right drags
    /// are bound to the same move. Sixteen combinations, each its own literal,
    /// because a phrase assembled from fragments cannot be translated as one.
    /// </summary>
    private static string CameraGestureBadgeText(string modifier, bool middleDrag, bool rightDrag)
    {
        return (modifier, middleDrag, rightDrag) switch
        {
            (CameraModifierBindings.Alt, true, true) => "Alt + left-drag, or middle / right-drag",
            (CameraModifierBindings.Alt, true, false) => "Alt + left-drag, or middle-drag",
            (CameraModifierBindings.Alt, false, true) => "Alt + left-drag, or right-drag",
            (CameraModifierBindings.Alt, false, false) => "Alt + left-drag",
            (CameraModifierBindings.Ctrl, true, true) => "Ctrl + left-drag, or middle / right-drag",
            (CameraModifierBindings.Ctrl, true, false) => "Ctrl + left-drag, or middle-drag",
            (CameraModifierBindings.Ctrl, false, true) => "Ctrl + left-drag, or right-drag",
            (CameraModifierBindings.Ctrl, false, false) => "Ctrl + left-drag",
            (CameraModifierBindings.Shift, true, true) => "Shift + left-drag, or middle / right-drag",
            (CameraModifierBindings.Shift, true, false) => "Shift + left-drag, or middle-drag",
            (CameraModifierBindings.Shift, false, true) => "Shift + left-drag, or right-drag",
            (CameraModifierBindings.Shift, false, false) => "Shift + left-drag",
            (_, true, true) => "Alt or Ctrl + left-drag, or middle / right-drag",
            (_, true, false) => "Alt or Ctrl + left-drag, or middle-drag",
            (_, false, true) => "Alt or Ctrl + left-drag, or right-drag",
            _ => "Alt or Ctrl + left-drag",
        };
    }

    private Control BuildAuthoringStatusFooter()
    {
        var footer = new TableLayoutPanel
        {
            Name = "ResidentViewportStatusFooter",
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            Margin = new Padding(0),
            Padding = new Padding(10, 2, 10, 2),
            BackColor = ThemeStatusBackground,
        };
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        footer.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        footer.Controls.Add(_statusLabel, 0, 0);
        footer.Controls.Add(_fpsLabel, 1, 0);
        return footer;
    }

    private void AddPresentationViewButton(TableLayoutPanel selector, string text, string view, int column)
    {
        var button = StyledButton(text, 26);
        button.Name = view == "reference" ? "OriginalResidentViewButton" : "EditableResidentViewButton";
        button.Dock = DockStyle.Fill;
        button.AutoSize = false;
        button.Margin = new Padding(4, 3, 4, 3);
        button.AccessibleDescription = view == "reference"
            ? "Focus the Original pane's independent camera. Both side-by-side panes remain visible."
            : "Focus the Imported / Modify pane's independent camera. Both side-by-side panes remain visible.";
        button.Click += (_, _) =>
        {
            _viewport.FocusPresentationPane(view);
            UpdatePresentationViewButtons();
            _statusLabel.Text = view == "reference"
                ? "Original pane focused. Both previews remain visible; its camera is independent."
                : "Imported / Modify pane focused. Both previews remain visible; its camera is independent.";
        };
        _presentationViewButtons[view] = button;
        if (_options.Embedded && string.Equals(view, "editable", StringComparison.OrdinalIgnoreCase))
        {
            _fpsLabel.Dock = DockStyle.Right;
            _fpsLabel.Width = 248;
            _fpsLabel.Height = 26;
            _fpsLabel.Padding = new Padding(8, 0, 8, 0);
            _fpsLabel.Margin = new Padding(0);
            _fpsLabel.BackColor = ThemeStatusBackground;
            _fpsLabel.ForeColor = ThemeMutedText;
            _fpsLabel.Cursor = Cursors.Hand;
            _fpsLabel.Click += (_, _) =>
            {
                _viewport.FocusPresentationPane("editable");
                UpdatePresentationViewButtons();
            };
            button.Padding = new Padding(0, 0, _fpsLabel.Width, 0);
            button.Controls.Add(_fpsLabel);
            _fpsLabel.BringToFront();
        }
        selector.Controls.Add(button, column, 0);
    }

    private void UpdatePresentationHeaderSplit()
    {
        var selector = _presentationViewSelector;
        if (selector is null || selector.ClientSize.Width <= 0 || selector.ColumnStyles.Count < 3)
        {
            return;
        }
        const int dividerWidth = 8;
        var width = Math.Max(1, selector.ClientSize.Width);
        var splitX = width <= dividerWidth * 2
            ? Math.Max(1, width / 2)
            : Math.Clamp((int)MathF.Round(width * _viewport.PaneSplitRatio), dividerWidth, width - dividerWidth);
        var referenceWidth = Math.Max(1, splitX - dividerWidth / 2);
        var editableWidth = Math.Max(1, width - splitX - dividerWidth / 2);
        selector.ColumnStyles[0].Width = referenceWidth;
        selector.ColumnStyles[1].Width = dividerWidth;
        selector.ColumnStyles[2].Width = editableWidth;
    }

    private void UpdatePresentationViewButtons()
    {
        var meshEdit = string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase);
        foreach (var (view, button) in _presentationViewButtons)
        {
            button.Enabled = !meshEdit
                || string.Equals(view, "editable", StringComparison.OrdinalIgnoreCase);
            var active = string.Equals(_viewport.ActivePresentationPane, view, StringComparison.OrdinalIgnoreCase);
            SetButtonAccent(button, active);
        }
    }

    private void HandlePresentationStateUpdate(JsonElement root)
    {
        var sessionId = JsonString(root, "session_id").Trim();
        var requestId = JsonLongValue(root, "request_id");
        var processGeneration = JsonLongValue(root, "process_generation");
        var sessionMatches = AcceptMaterialSession(sessionId, out var sessionError);
        var applied = false;
        var reason = string.Empty;
        if (requestId <= 0)
        {
            reason = "missing_request_id";
        }
        else if (processGeneration <= 0 || processGeneration != _residentProcessGeneration)
        {
            reason = "stale_process_generation";
        }
        else if (!sessionMatches)
        {
            reason = string.IsNullOrWhiteSpace(sessionError) ? "stale_session" : sessionError;
        }
        else
        {
            applied = _viewport.TryApplyPresentationState(root, out reason);
        }
        if (applied)
        {
            SyncPreviewModeSelection(_viewport.DisplayMode);
            UpdatePresentationViewButtons();
            // The camera modifiers arrive in this payload, and the strip is the
            // only thing that tells the user what they are now bound to.
            UpdateViewportControlsHint();
            _statusLabel.Text = $"Resident presentation updated: {_viewport.ActivePresentationView}.";
        }
        var payload = new Dictionary<string, object?>
        {
            ["status"] = applied ? "applied" : "rejected",
            ["reason"] = applied ? string.Empty : reason,
            ["presentation"] = _viewport.PresentationStatusPayload(),
            ["renderer"] = RendererStatusWithLifecycle(),
            ["capabilities"] = new[]
            {
                "resident_presentation_state_v1",
                "resident_role_views_v1",
                "resident_simultaneous_role_panes_v2",
                "resizable_role_panes_v1",
            },
        };
        CopyMutationEnvelope(root, payload);
        WriteProtocolEvent("presentation_state_update_ack", payload);
    }
}
