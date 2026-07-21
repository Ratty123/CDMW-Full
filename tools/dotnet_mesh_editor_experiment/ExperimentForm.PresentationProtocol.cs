using System.Text.Json;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private readonly Dictionary<string, Button> _presentationViewButtons =
        new(StringComparer.OrdinalIgnoreCase);
    private TableLayoutPanel? _presentationViewSelector;
    private bool _presentationHeaderDividerDragging;

    private Control BuildPresentationViewportRegion()
    {
        var simplePreview = _options.SimplePreview;
        var region = new TableLayoutPanel
        {
            Name = "ResidentRoleViewRegion",
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
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
        UpdateViewportControlsHint();
        if (!simplePreview)
        {
            UpdatePresentationHeaderSplit();
        }
        UpdatePresentationViewButtons();
        return region;
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
            SetButtonLatched(button, active);
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
            UpdatePresentationViewButtons();
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
