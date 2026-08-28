using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private static void ConfigureNumeric(NumericUpDown control, int decimalPlaces, decimal minimum, decimal maximum, decimal value, decimal increment)
    {
        control.DecimalPlaces = decimalPlaces;
        control.Minimum = minimum;
        control.Maximum = maximum;
        control.Value = value;
        control.Increment = increment;
        control.AutoSize = true;
        control.MinimumSize = new Size(0, SingleLineControlHeight(control));
        control.BorderStyle = BorderStyle.FixedSingle;
        ApplyCommonControlStyle(control);
    }

    private static void ConfigureCombo(ComboBox combo, object[] values, int selectedIndex)
    {
        combo.Items.Clear();
        combo.Items.AddRange(values);
        combo.SelectedIndex = combo.Items.Count == 0
            ? -1
            : Math.Clamp(selectedIndex, 0, combo.Items.Count - 1);
        combo.DropDownStyle = ComboBoxStyle.DropDownList;
        combo.FlatStyle = FlatStyle.Flat;
        combo.ItemHeight = Math.Max(combo.ItemHeight, combo.Font.Height + 4);
        combo.MinimumSize = new Size(0, SingleLineControlHeight(combo));
        // A flat DropDownList only invalidates the newly exposed strip when it
        // grows, so the previous themed paint and drop arrow stay on screen and
        // the widened remainder keeps the unthemed system background. Repaint
        // the whole client whenever the layout resizes it.
        combo.Resize += (_, _) => combo.Invalidate();
        ApplyCommonControlStyle(combo);
    }

    private static void ConfigureCheckBox(CheckBox checkBox, string text, bool isChecked)
    {
        checkBox.Text = text;
        checkBox.Checked = isChecked;
        checkBox.AutoSize = true;
        checkBox.MinimumSize = new Size(0, SingleLineControlHeight(checkBox));
        checkBox.ForeColor = ThemeText;
        checkBox.BackColor = ThemeSectionBackground;
        checkBox.FlatStyle = FlatStyle.Flat;
        checkBox.Padding = new Padding(2, 0, 0, 0);
    }

    private static CheckBox ToolCheckBox(string text, bool isChecked)
    {
        var checkBox = new CheckBox();
        ConfigureCheckBox(checkBox, text, isChecked);
        return checkBox;
    }

    private static void ApplyCommonControlStyle(Control control)
    {
        control.ForeColor = ThemeText;
        control.BackColor = ThemeInputBackground;
        control.Margin = new Padding(0, 0, 0, 4);
    }

    private static int SingleLineControlHeight(Control control, int minimum = 24)
    {
        return Math.Max(minimum, TextRenderer.MeasureText("Ag", control.Font).Height + 6);
    }

    private static Button StyledButton(string text, int height = 26)
    {
        var buttonHeight = Math.Max(height, TextRenderer.MeasureText(text, SystemFonts.MessageBoxFont).Height + 6);
        var button = new MeshEditorFlatButton
        {
            Text = text,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Height = buttonHeight,
            MinimumSize = new Size(0, buttonHeight),
            Padding = new Padding(5, 1, 5, 1),
            FlatStyle = FlatStyle.Flat,
            ForeColor = ThemeText,
            BackColor = ThemeButtonBackground,
            Margin = new Padding(0, 0, 0, 3),
            // Tool captions are data, not accelerators: "Morph & Refit" has to
            // render its ampersand instead of losing it to a mnemonic prefix.
            UseMnemonic = false,
            UseVisualStyleBackColor = false
        };
        button.FlatAppearance.BorderSize = 0;
        button.FlatAppearance.MouseOverBackColor = ThemeButtonHover;
        button.FlatAppearance.MouseDownBackColor = ThemeButtonPressed;
        return button;
    }

    private static Button StyledActionButton(string text, Action action)
    {
        var button = StyledButton(text);
        button.Click += (_, _) => action();
        return button;
    }

    private Button CameraButton(string text, string preset)
    {
        return StyledActionButton(text, () =>
        {
            _viewport.SetCameraPreset(preset);
            _statusLabel.Text = $"Camera: {text}.";
        });
    }

    private Control PreviewModeControl()
    {
        return LabeledControl("Preview mode", _previewMode);
    }

    /// <summary>
    /// Populates and wires the preview-mode combo. This is display state the
    /// resident viewport protocol reads and writes, not decoration: the preview
    /// profile builds no tool panels but still routes every
    /// viewport_display_update through <see cref="SyncPreviewModeSelection"/>,
    /// which assigns SelectedIndex. An unpopulated combo throws there.
    /// </summary>
    private void ConfigurePreviewModeCombo()
    {
        var modes = new[]
        {
            "textured",
            "untextured_faces",
            "untextured_wire",
            "wire",
            "vertices",
            "wire_vertices",
            "xray",
        };
        ConfigureCombo(
            _previewMode,
            new object[]
            {
                "Solid (Textured)",
                "Faces (No Textures)",
                "Faces + Wire",
                "Wire",
                "Vertices",
                "Wire + Vertices",
                "X-Ray",
            },
            selectedIndex: Array.IndexOf(
                modes,
                _viewport.InitialResidentDisplayMode(HasResidentTextureResources())));
        _ = _viewport.TrySetSynchronizedDisplayMode(
            _viewport.InitialResidentDisplayMode(HasResidentTextureResources()),
            out _);
        _previewMode.SelectedIndexChanged += (_, _) =>
        {
            if (_syncingPreviewModeSelection)
            {
                return;
            }
            var index = Math.Clamp(_previewMode.SelectedIndex, 0, modes.Length - 1);
            var mode = modes[index];
            if (string.Equals(mode, "textured", StringComparison.OrdinalIgnoreCase)
                && _options.Embedded)
            {
                // Only the host knows whether every role required by this scene
                // is resident. A global "any texture exists" check accepted
                // Solid after Imported loaded while Original was still absent,
                // then the role-aware host sent Faces back one frame later.
                RequestResidentViewportDisplay(mode);
                return;
            }
            if (_viewport.TrySetSynchronizedDisplayMode(mode, out var error))
            {
                if (!_meshEditInteractionActive)
                {
                    _placementPreviewMode = mode;
                }
                _xray.Checked = _viewport.ShowXRay;
                _statusLabel.Text = $"Preview mode: {_previewMode.SelectedItem}.";
                // Tell the host every time, not only when textures still have to
                // be resolved. The host republishes a presentation snapshot after
                // every accepted scene frame, so a pick it never heard about is
                // overwritten by the next frame that happens to land.
                RequestResidentViewportDisplay(mode);
            }
            else
            {
                _statusLabel.Text = error;
            }
        };
    }

    private bool HasResidentTextureResources()
    {
        return _viewport.HasTexturedMaterialResources;
    }

    private void RequestResidentViewportDisplay(string mode)
    {
        if (string.IsNullOrWhiteSpace(_residentMaterialSessionId)
            || _residentProcessGeneration <= 0)
        {
            // Too early: there is no session to address the request to yet.
            // Remember the wish instead of dropping it — the host replays it
            // the moment a session is observed. Dropping it here is what made
            // an early "Solid (Textured)" pick do nothing until the user
            // happened to pick another textured mode later.
            _pendingResidentDisplayMode = mode;
            SyncPreviewModeSelection(mode);
            _statusLabel.Text = "Textures will load as soon as the resident preview is ready...";
            return;
        }
        _pendingResidentDisplayMode = string.Empty;
        WriteProtocolEvent("viewport_display_request", new Dictionary<string, object?>
        {
            ["session_id"] = _residentMaterialSessionId,
            ["request_id"] = ++_outgoingMutationRequestSequence,
            ["process_generation"] = _residentProcessGeneration,
            ["protocol_version"] = 2,
            ["mode"] = mode,
        });
        _statusLabel.Text = "Loading textures in the resident viewport...";
    }

    /// <summary>
    /// A textured display mode chosen before any resident session existed.
    /// Replayed by <see cref="ReplayPendingResidentDisplayRequest"/> when one
    /// arrives; empty when nothing is owed.
    /// </summary>
    private string _pendingResidentDisplayMode = string.Empty;

    private void ReplayPendingResidentDisplayRequest()
    {
        if (_pendingResidentDisplayMode.Length == 0
            || string.IsNullOrWhiteSpace(_residentMaterialSessionId)
            || _residentProcessGeneration <= 0)
        {
            return;
        }
        var mode = _pendingResidentDisplayMode;
        _pendingResidentDisplayMode = string.Empty;
        RequestResidentViewportDisplay(mode);
    }

    private void SyncPreviewModeSelection(string mode)
    {
        var normalized = mode.Trim().ToLowerInvariant();
        if (string.Equals(normalized, "textured_wire", StringComparison.OrdinalIgnoreCase))
        {
            normalized = "textured";
        }
        var index = normalized switch
        {
            "textured" => 0,
            "untextured_faces" => 1,
            "untextured_wire" => 2,
            "wire" => 3,
            "vertices" => 4,
            "wire_vertices" => 5,
            "xray" => 6,
            _ => -1,
        };
        if (index < 0)
        {
            return;
        }
        if (!_meshEditInteractionActive)
        {
            _placementPreviewMode = normalized;
        }
        if (_previewMode.SelectedIndex == index)
        {
            return;
        }
        _syncingPreviewModeSelection = true;
        try
        {
            _previewMode.SelectedIndex = index;
        }
        finally
        {
            _syncingPreviewModeSelection = false;
        }
    }

    private static Control StackControls(params Control[] controls)
    {
        var panel = new TableLayoutPanel
        {
            ColumnCount = 1,
            RowCount = 0,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0),
            Padding = new Padding(0),
        };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        foreach (var control in controls)
        {
            AddStackRow(panel, control);
        }
        return panel;
    }

    private static Control LabeledControl(string label, Control control)
    {
        var panel = new TableLayoutPanel
        {
            ColumnCount = 2,
            RowCount = 1,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0, 0, 0, 4),
            Padding = new Padding(0)
        };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        var text = new Label
        {
            Text = label,
            AutoSize = true,
            UseMnemonic = false,
            MinimumSize = new Size(0, 18),
            ForeColor = ThemeMutedText,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0, 0, 8, 0),
            Anchor = AnchorStyles.Left
        };
        control.Margin = new Padding(0);
        control.Dock = DockStyle.Fill;
        panel.Controls.Add(text, 0, 0);
        panel.Controls.Add(control, 1, 0);
        return panel;
    }

    private static Control ButtonRow(params Control[] controls)
    {
        var panel = new MeshEditorButtonRow(controls);
        var cellWidths = new int[controls.Length];
        var widestCellWidth = 0;
        for (var index = 0; index < controls.Length; index++)
        {
            var control = controls[index];
            control.Margin = new Padding(index == 0 ? 0 : 2, 0, index == controls.Length - 1 ? 0 : 2, 0);
            var preferredWidth = Math.Max(56, control.GetPreferredSize(Size.Empty).Width);
            control.MinimumSize = new Size(
                Math.Max(control.MinimumSize.Width, preferredWidth),
                control.MinimumSize.Height);
            cellWidths[index] = control.MinimumSize.Width;
            widestCellWidth = Math.Max(widestCellWidth, control.MinimumSize.Width);
            control.Dock = DockStyle.Fill;
        }
        // Only the widest single button is a hard floor. Claiming the whole row
        // as the minimum instead would hold the row wider than a narrow tool
        // column can ever be, so it could never reflow and would overlap.
        panel.Configure(cellWidths);
        panel.MinimumSize = new Size(widestCellWidth, 0);
        return panel;
    }

    private static GroupBox AddSection(TableLayoutPanel stack, string title, params Control[] controls)
    {
        var group = new MeshEditorSectionBox
        {
            Text = title,
            ForeColor = ThemeText,
            BackColor = ThemeSectionBackground,
            Padding = new Padding(8, 20, 8, 7),
            Margin = new Padding(0, 0, 0, 6),
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink
        };
        group.FitCaptionHeight();
        var body = new TableLayoutPanel
        {
            ColumnCount = 1,
            RowCount = 0,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Dock = DockStyle.Top,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0),
            Padding = new Padding(0)
        };
        body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        // Rows are appended one at a time and both the body and the group are
        // AutoSize, so without this every append re-laid out everything added
        // so far. The section is measured once, when its stack lays out.
        group.SuspendLayout();
        body.SuspendLayout();
        try
        {
            foreach (var control in controls)
            {
                AddStackRow(body, control);
            }
            group.Controls.Add(body);
        }
        finally
        {
            body.ResumeLayout(performLayout: false);
            group.ResumeLayout(performLayout: false);
        }
        AddStackRow(stack, group);
        return group;
    }

    private GroupBox AddHelpSection(
        TableLayoutPanel stack,
        string title,
        string helpText,
        out Control helpMarker,
        params Control[] controls)
    {
        // No "?" badge: pinned into the caption row, it made every section
        // reserve that row's height even blanked. Help moves onto the section.
        var group = AddSection(stack, title, controls);
        group.AccessibleName = title;
        SetHelpText(group, helpText);
        helpMarker = group;
        return group;
    }

    private void SetHelpText(Control? marker, string helpText)
    {
        if (marker is null)
        {
            return;
        }
        marker.AccessibleDescription = helpText;
        _helpToolTip.SetToolTip(marker, helpText);
    }

    private static SplitContainer CreateToolPanelSplit(string name, FixedPanel fixedPanel)
    {
        var split = new MeshEditorBufferedSplitContainer
        {
            Name = name,
            AccessibleName = name.Contains("Left", StringComparison.Ordinal)
                ? "Resize left Edit Mesh tools"
                : "Resize right Edit Mesh tools",
            Dock = DockStyle.Fill,
            Orientation = Orientation.Vertical,
            FixedPanel = fixedPanel,
            IsSplitterFixed = false,
            SplitterIncrement = 8,
            SplitterWidth = ToolPanelSplitterWidth,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemeBorder,
            TabStop = false,
        };
        split.Panel1.BackColor = ThemeWindowBackground;
        split.Panel2.BackColor = ThemeWindowBackground;
        return split;
    }

    private void ConfigureToolPanelSplitters()
    {
        if (_leftToolSplit is null || _rightToolSplit is null)
        {
            return;
        }
        // CaptureToolPanelLayout is a no-op while the tool rail is active, so
        // dragging a rail splitter never overwrites the classic widths.
        _leftToolSplit.SplitterMoved += (_, _) => CaptureToolPanelLayout(persist: true);
        _rightToolSplit.SplitterMoved += (_, _) => CaptureToolPanelLayout(persist: true);
    }

    private void ApplySavedToolPanelLayout()
    {
        if (_leftToolSplit is null || _rightToolSplit is null)
        {
            return;
        }
        if (_leftToolSplit.Panel1Collapsed || _rightToolSplit.Panel2Collapsed)
        {
            return;
        }
        var wasApplying = _applyingToolPanelLayout;
        _applyingToolPanelLayout = true;
        try
        {
            var normalized = _toolPanelLayout.Normalized();
            var splitterWidth = ScaleToolPanelWidth(ToolPanelSplitterWidth);
            _leftToolSplit.SplitterWidth = splitterWidth;
            _rightToolSplit.SplitterWidth = splitterWidth;
            ApplySplitterDistance(
                _leftToolSplit,
                ScaleToolPanelWidth(normalized.LeftWidth),
                ScaleToolPanelWidth(MeshToolPanelLayout.MinimumLeftWidth),
                ScaleToolPanelWidth(MinimumViewportWidth + MeshToolPanelLayout.MinimumRightWidth)
                    + splitterWidth,
                prioritizePanelOne: true);
            _leftToolSplit.PerformLayout();
            var rightPanelWidth = ScaleToolPanelWidth(normalized.RightWidth);
            var rightAvailable = Math.Max(
                0,
                _rightToolSplit.ClientSize.Width - _rightToolSplit.SplitterWidth);
            ApplySplitterDistance(
                _rightToolSplit,
                Math.Max(0, rightAvailable - rightPanelWidth),
                ScaleToolPanelWidth(MinimumViewportWidth),
                ScaleToolPanelWidth(MeshToolPanelLayout.MinimumRightWidth),
                prioritizePanelOne: false);
        }
        finally
        {
            _applyingToolPanelLayout = wasApplying;
        }
    }

    private static void ApplySplitterDistance(
        SplitContainer split,
        int desiredDistance,
        int requestedPanelOneMinimum,
        int requestedPanelTwoMinimum,
        bool prioritizePanelOne)
    {
        var available = Math.Max(0, split.ClientSize.Width - split.SplitterWidth);
        if (available <= 0)
        {
            return;
        }
        split.Panel1MinSize = 0;
        split.Panel2MinSize = 0;
        int panelOneMinimum;
        int panelTwoMinimum;
        if (prioritizePanelOne)
        {
            panelOneMinimum = Math.Min(requestedPanelOneMinimum, available);
            panelTwoMinimum = Math.Min(requestedPanelTwoMinimum, available - panelOneMinimum);
        }
        else
        {
            panelTwoMinimum = Math.Min(requestedPanelTwoMinimum, available);
            panelOneMinimum = Math.Min(requestedPanelOneMinimum, available - panelTwoMinimum);
        }
        var maximumDistance = Math.Max(panelOneMinimum, available - panelTwoMinimum);
        split.SplitterDistance = Math.Clamp(desiredDistance, panelOneMinimum, maximumDistance);
        split.Panel1MinSize = panelOneMinimum;
        split.Panel2MinSize = panelTwoMinimum;
    }

    private int ScaleToolPanelWidth(int logicalWidth)
    {
        return Math.Max(1, (int)Math.Round(logicalWidth * DeviceDpi / 96.0));
    }

    private int LogicalToolPanelWidth(int deviceWidth)
    {
        return Math.Max(1, (int)Math.Round(deviceWidth * 96.0 / Math.Max(1, DeviceDpi)));
    }

    private void CaptureToolPanelLayout(bool persist)
    {
        if (_applyingToolPanelLayout
            || IsToolRailActive
            || _leftToolSplit is null
            || _rightToolSplit is null
            || _leftToolSplit.Panel1Collapsed
            || _rightToolSplit.Panel2Collapsed)
        {
            return;
        }
        var rightWidth = Math.Max(
            0,
            _rightToolSplit.ClientSize.Width
                - _rightToolSplit.SplitterWidth
                - _rightToolSplit.SplitterDistance);
        _toolPanelLayout = new MeshToolPanelLayout(
            LogicalToolPanelWidth(_leftToolSplit.SplitterDistance),
            LogicalToolPanelWidth(rightWidth)).Normalized();
        if (persist)
        {
            _ = MeshToolPanelLayoutPreferences.TrySave(_toolPanelLayout, out _);
        }
    }

    private void SaveToolPanelLayout()
    {
        if (!IsToolRailActive)
        {
            CaptureToolPanelLayout(persist: false);
        }
        _ = MeshToolPanelLayoutPreferences.TrySave(_toolPanelLayout, out _);
    }

    private void SuspendToolPanelLayout()
    {
        _leftToolPanel?.SuspendLayout();
        _rightToolPanel?.SuspendLayout();
        _leftToolStack?.SuspendLayout();
        _rightToolStack?.SuspendLayout();
    }

    private void ResumeToolPanelLayout()
    {
        _rightToolStack?.ResumeLayout(performLayout: false);
        _leftToolStack?.ResumeLayout(performLayout: false);
        _rightToolPanel?.ResumeLayout(performLayout: true);
        _leftToolPanel?.ResumeLayout(performLayout: true);
    }

    private static void AddStackRow(TableLayoutPanel stack, Control control)
    {
        var row = stack.RowCount;
        stack.RowCount = row + 1;
        stack.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        control.Dock = DockStyle.Top;
        stack.Controls.Add(control, 0, row);
    }

    private Button ToolButton(string text, string tool)
    {
        var button = StyledButton(text);
        _toolButtons[tool] = button;
        button.Click += (_, _) => ActivateTool(tool, text, announce: true);
        return button;
    }

    /// <summary>
    /// Arms a tool. <paramref name="announce"/> is true when a reader chose it
    /// here, which is the only case the host has to be told about: it keeps its
    /// own notion of the tool and re-publishes it on every control refresh, so
    /// without this the next refresh replaces the reader's choice with Select.
    /// </summary>
    private void ActivateTool(string tool, string text, bool announce = false)
    {
        SetActiveTool(tool);
        if (tool == "move" && !_viewport.HasEditableSelection)
        {
            _statusLabel.Text = "Move requires a selection. Use Select in the viewport or choose a part under PARTS.";
        }
        else
        {
            _statusLabel.Text = tool is "grab" or "smooth" or "inflate" or "pinch"
                ? $"{text} active: left-drag inside the brush circle."
                : $"Tool: {text}";
        }
        UpdateViewportControlsHint();
        if (announce)
        {
            // Sent even when the tool did not change here: that is exactly the
            // case where the host is the one holding a stale value.
            WriteProtocolEvent("tool_changed", new Dictionary<string, object?>
            {
                ["tool"] = (tool ?? string.Empty).Trim().ToLowerInvariant(),
                ["target_mode"] = _viewport.CurrentTargetMode(),
            });
        }
    }

    private void SetActiveTool(string tool)
    {
        _viewport.ActiveTool = tool;
        RefreshToolButtonStates();
        SyncToolRailPageToActiveTool();
    }

    private void RefreshToolButtonStates()
    {
        foreach (var pair in _toolButtons)
        {
            SetButtonAccent(
                pair.Value,
                string.Equals(pair.Key, _viewport.ActiveTool, StringComparison.OrdinalIgnoreCase));
        }
        // The rail's tool buttons accent by the armed tool the same way,
        // however the tool was chosen.
        foreach (var pair in _toolRailToolButtons)
        {
            SetButtonAccent(
                pair.Value,
                string.Equals(pair.Key, _viewport.ActiveTool, StringComparison.OrdinalIgnoreCase));
        }
    }

    private void RefreshGizmoButtonStates()
    {
        foreach (var pair in _gizmoButtons)
        {
            SetButtonAccent(
                pair.Value,
                string.Equals(pair.Key, _scene.GizmoTool, StringComparison.OrdinalIgnoreCase));
        }
    }

    private static void SetButtonAccent(Button button, bool accent)
    {
        if (button is MeshEditorFlatButton flatButton)
        {
            flatButton.SetAccent(accent);
            return;
        }
        button.BackColor = accent ? ThemeAccent : ThemeButtonBackground;
        button.ForeColor = accent ? Color.White : ThemeText;
    }

    private Button CommandButton(string text, string command)
    {
        var button = StyledButton(text);
        button.Click += (_, _) =>
        {
            WriteCommandRequest(command);
        };
        return button;
    }

    private void UpdateViewportControlsHint()
    {
        string hint;
        var meshEdit = string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase);
        var tool = (_viewport.ActiveTool ?? string.Empty).Trim().ToLowerInvariant();
        var selectionTarget = Convert.ToString(_selectionTarget.SelectedItem) ?? "Vertices";
        var primary = "Orbit: LMB drag";
        // Written from the live bindings: the pan/orbit modifiers and the
        // middle/right drags are rebindable, so a baked-in "Shift+LMB / MMB /
        // RMB" would lie the moment one of them moved.
        var orbitBinding = CameraGestureBadgeText(
            _viewport.CameraOrbitModifier,
            middleDrag: string.Equals(
                _viewport.CameraMiddleDrag, CameraModifierBindings.DragOrbit, StringComparison.Ordinal),
            rightDrag: string.Equals(
                _viewport.CameraRightDrag, CameraModifierBindings.DragOrbit, StringComparison.Ordinal));
        var panBinding = CameraGestureBadgeText(
            _viewport.CameraPanModifier,
            middleDrag: string.Equals(
                _viewport.CameraMiddleDrag, CameraModifierBindings.DragPan, StringComparison.Ordinal),
            rightDrag: string.Equals(
                _viewport.CameraRightDrag, CameraModifierBindings.DragPan, StringComparison.Ordinal));
        if (!meshEdit)
        {
            hint = $"Orbit: LMB drag  |  Pan: {panBinding}  |  Zoom: Wheel";
        }
        else
        {
            primary = tool switch
            {
                "select" => $"Select {selectionTarget}: LMB click/drag",
                "orbit" => "Orbit: LMB drag",
                "move" => "Move selection: LMB drag",
                "grab" => "Grab: LMB drag",
                "smooth" => "Smooth: LMB drag",
                "inflate" => "Inflate: LMB drag",
                "pinch" => "Pinch: LMB drag",
                _ => "Apply tool: LMB drag",
            };
            hint = $"{primary}  |  Orbit override: {orbitBinding}  |  Pan: {panBinding}  |  Zoom: Wheel  |  Undo: Ctrl+Z  |  Redo: Ctrl+Y / Ctrl+Shift+Z";
        }
        _controlsHintLabel.Text = hint;
        // The strip under the viewport names the active tool and the modifiers
        // that move the camera around it. The modifiers are highlighted exactly
        // when they are the only way to move the camera: while an edit tool owns
        // the left button.
        UpdateViewportNavigationStrip(
            primary,
            modifiersOwnTheCamera: meshEdit
                && !string.Equals(tool, "orbit", StringComparison.OrdinalIgnoreCase));
        SetHelpText(
            _viewportHelpMarker,
            $"{hint}\r\n\r\nChoose the preview mode, topology appearance, viewport background and grid colors, or a camera preset. Colors and sizes are saved; X-Ray uses white wire and magenta vertices while preserving those sizes.");
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (_meshEditInteractionActive && (keyData & Keys.Control) == Keys.Control)
        {
            var keyCode = keyData & Keys.KeyCode;
            if (keyCode == Keys.C)
            {
                if (_viewport.HasEditableSelection)
                {
                    WriteCommandRequest("copy");
                }
                return true;
            }
            if (keyCode == Keys.V)
            {
                if (_layerPasteButton?.Enabled == true)
                {
                    WriteCommandRequest("paste");
                }
                return true;
            }
            var redo = keyCode == Keys.Y
                || (keyCode == Keys.Z && (keyData & Keys.Shift) == Keys.Shift);
            if (redo)
            {
                if (_redoButton?.Enabled == true)
                {
                    WriteCommandRequest("redo");
                }
                return true;
            }
            if (keyCode == Keys.Z)
            {
                if (_undoButton?.Enabled == true)
                {
                    WriteCommandRequest("undo");
                }
                return true;
            }
        }
        return base.ProcessCmdKey(ref msg, keyData);
    }

    private void ApplyInteractionModeControls()
    {
        var meshEdit = string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase);
        if (meshEdit)
        {
            // Hidden startup normally owns this build. Keep the entry point as
            // an idempotent backstop for nonstandard construction paths before
            // anything below walks the section lists.
            EnsureAuthoringToolPanelsReady();
            StartupTiming.Mark("interaction_mode_panels_ready");
        }
        var enteringMeshEdit = meshEdit && !_meshEditInteractionActive;
        var leavingMeshEdit = !meshEdit && _meshEditInteractionActive;
        _meshEditInteractionActive = meshEdit;
        if (!meshEdit)
        {
            RestorePlacementLayoutForNonMeshMode();
        }
        SuspendToolPanelLayout();
        try
        {
            if (!meshEdit)
            {
                ApplyEmbeddedToolPanelVisibility(meshEdit: false);
            }
            foreach (var section in _meshEditOnlySections)
            {
                section.Visible = meshEdit;
                section.Enabled = meshEdit;
            }
            foreach (var section in _placementOnlySections)
            {
                section.Visible = !meshEdit;
                section.Enabled = !meshEdit;
            }
            StartupTiming.Mark("interaction_mode_sections_toggled");
            if (meshEdit)
            {
                // The tool-rail activation below owns the final split state.
                // Expanding both placement flanks first only lays them out so
                // the same sections can immediately be hidden and re-parented.
                ApplyToolRailEditMeshLayout();
                StartupTiming.Mark("tool_rail_edit_mesh_layout_applied");
            }
        }
        finally
        {
            ResumeToolPanelLayout();
        }
        StartupTiming.Mark("interaction_mode_layout_resumed");
        if (meshEdit)
        {
            _viewport.ActivatePresentationView("editable");
            if (enteringMeshEdit)
            {
                _viewport.SuppressPlacementGizmoInteraction();
                // Wire + Vertices is only the untouched opening default. A
                // textured/material settle can put the renderer in the user's
                // requested mode before the separate host-authority marker is
                // observed, so authority alone cannot decide whether a real
                // choice exists. Preserve every non-default placement mode.
                if (!_meshEditDisplayInitialized
                    && !_viewport.HostDisplayModeAuthoritative
                    && string.Equals(
                        _viewport.DisplayMode,
                        "untextured_wire",
                        StringComparison.OrdinalIgnoreCase))
                {
                    SyncPreviewModeSelection("wire_vertices");
                    _ = _viewport.TrySetSynchronizedDisplayMode("wire_vertices", out _);
                }
            }
            _meshEditDisplayInitialized = true;
        }
        else if (leavingMeshEdit)
        {
            var mode = _placementPreviewMode;
            if (!HasResidentTextureResources())
            {
                mode = mode switch
                {
                    "textured" => "untextured_faces",
                    "textured_wire" => "untextured_faces",
                    _ => mode,
                };
            }
            SyncPreviewModeSelection(mode);
            if (_viewport.TrySetSynchronizedDisplayMode(mode, out var error))
            {
                _xray.Checked = _viewport.ShowXRay;
                _statusLabel.Text = $"Preview mode: {_previewMode.SelectedItem}.";
            }
            else
            {
                _statusLabel.Text = error;
            }
        }
        UpdatePresentationViewButtons();
        if (!meshEdit && !string.Equals(_viewport.ActiveTool, "orbit", StringComparison.OrdinalIgnoreCase))
        {
            _viewport.ActiveTool = "orbit";
        }
        RefreshToolButtonStates();
        RefreshGizmoButtonStates();
        UpdateViewportControlsHint();
    }

    private void ApplyEmbeddedToolPanelVisibility(bool meshEdit)
    {
        if (!_options.Embedded || _leftToolSplit is null || _rightToolSplit is null)
        {
            return;
        }
        if (!meshEdit)
        {
            CaptureToolPanelLayout(persist: false);
            var wasApplying = _applyingToolPanelLayout;
            _applyingToolPanelLayout = true;
            try
            {
                // Preview hosts can be much narrower than the authoring form's
                // startup width. SplitContainer keeps its previous panel
                // minimums even after collapse, which otherwise leaves the
                // D3D viewport at 1180 px and clips its centered model.
                _leftToolSplit.Panel1MinSize = 0;
                _leftToolSplit.Panel2MinSize = 0;
                _rightToolSplit.Panel1MinSize = 0;
                _rightToolSplit.Panel2MinSize = 0;
                _rightToolSplit.Panel2Collapsed = true;
                _leftToolSplit.Panel1Collapsed = true;
                _rightToolSplit.PerformLayout();
                _leftToolSplit.PerformLayout();
            }
            finally
            {
                _applyingToolPanelLayout = wasApplying;
            }
            SaveToolPanelLayout();
            return;
        }
        var applyingBeforeExpand = _applyingToolPanelLayout;
        _applyingToolPanelLayout = true;
        try
        {
            _leftToolSplit.Panel1Collapsed = false;
            _rightToolSplit.Panel2Collapsed = false;
            // The saved widths describe the classic side panels. Re-entering
            // mesh edit while the tool rail owns the flanks has to restore the
            // rail's own dock width instead, or every entry after the first
            // leaves the property column at the classic minimum and its tool
            // pages overlap.
            if (IsToolRailActive)
            {
                ApplyToolRailSplitterLayout();
            }
            else
            {
                ApplySavedToolPanelLayout();
            }
        }
        finally
        {
            _applyingToolPanelLayout = applyingBeforeExpand;
        }
    }

    private Control SceneComparisonControl()
    {
        var combo = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList };
        combo.Items.AddRange(new object[] { "Two panes", "Overlay", "Focus Imported / Modify", "Focus Original" });
        combo.SelectedIndex = _scene.ComparisonMode switch
        {
            "side_by_side" => 0,
            "overlay" => 1,
            "original_only" => 3,
            _ => 2,
        };
        combo.SelectedIndexChanged += (_, _) =>
        {
            if (combo.SelectedIndex == 1)
            {
                _viewport.ActivatePresentationView("overlay", "overlay");
            }
            else if (combo.SelectedIndex == 3)
            {
                _viewport.ActivatePresentationView("reference");
            }
            else if (combo.SelectedIndex == 2)
            {
                _viewport.ActivatePresentationView("editable");
            }
            else
            {
                _viewport.ActivatePresentationView("comparison", "side_by_side");
            }
            UpdatePresentationViewButtons();
            _statusLabel.Text = $"View layout: {combo.SelectedItem}.";
        };
        return LabeledControl("Comparison", combo);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            DisposeDetachedCompactMorphCards();
            _helpToolTip.Dispose();
        }
        base.Dispose(disposing);
    }

    private sealed class MeshEditorBufferedPanel : Panel
    {
        public MeshEditorBufferedPanel()
        {
            DoubleBuffered = true;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
        }
    }

    /// <summary>
    /// A panel whose whole descendant tree is composed off screen and blitted
    /// once, rather than painting one child window at a time.
    /// </summary>
    /// <remarks>
    /// This is the difference that <see cref="Control.DoubleBuffered"/> cannot
    /// make. Double buffering buffers a control's own painting into its own
    /// window; it does nothing about the fact that every WinForms container,
    /// button and list is a separate HWND that paints itself. Any layout change
    /// moves, resizes, shows or hides those windows individually, each one
    /// painting as it goes and the parent's background showing through the gaps
    /// between them, which is what is seen as the panel flickering whenever a
    /// row, a button or a list is touched. WS_EX_COMPOSITED makes Windows
    /// compose the entire subtree bottom-up into an off-screen surface and
    /// present it in one go, so a layout change becomes a single frame.
    ///
    /// It is deliberately scoped to the tool flanks rather than set on the form.
    /// The viewport presents through a DXGI flip-model swap chain, and flip
    /// model is not compatible with a composited ancestor: putting this on the
    /// form (or on anything above the viewport) is what would cost the renderer
    /// its presentation path. Nothing in either flank is an ancestor of the
    /// viewport, so the chrome composes and the swap chain is left alone.
    /// </remarks>
    private sealed class MeshEditorCompositedPanel : Panel
    {
        private const int WsExComposited = 0x02000000;

        public MeshEditorCompositedPanel()
        {
            DoubleBuffered = true;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
        }

        protected override CreateParams CreateParams
        {
            get
            {
                var parameters = base.CreateParams;
                parameters.ExStyle |= WsExComposited;
                return parameters;
            }
        }
    }

    private sealed class MeshEditorBufferedTableLayoutPanel : TableLayoutPanel
    {
        public MeshEditorBufferedTableLayoutPanel()
        {
            DoubleBuffered = true;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            var started = System.Diagnostics.Stopwatch.GetTimestamp();
            base.OnLayout(levent);
            StartupTiming.Account("buffered_table_layout", System.Diagnostics.Stopwatch.GetTimestamp() - started);
        }
    }

    private sealed class MeshEditorBufferedSplitContainer : SplitContainer
    {
        public MeshEditorBufferedSplitContainer()
        {
            DoubleBuffered = true;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
        }
    }

    private sealed class MeshEditorSectionBox : GroupBox
    {
        public MeshEditorSectionBox()
        {
            ResizeRedraw = true;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
        }

        protected override void OnLayout(LayoutEventArgs levent)
        {
            var started = System.Diagnostics.Stopwatch.GetTimestamp();
            base.OnLayout(levent);
            StartupTiming.Account("section_box_layout", System.Diagnostics.Stopwatch.GetTimestamp() - started);
        }

        [System.Diagnostics.CodeAnalysis.AllowNull]
        public override string Text
        {
            get => base.Text;
            set
            {
                base.Text = value;
                FitCaptionHeight();
            }
        }

        protected override void OnFontChanged(EventArgs e)
        {
            base.OnFontChanged(e);
            FitCaptionHeight();
        }

        /// <summary>
        /// Reserve the caption row only when there is a caption: a section named
        /// by the tool-list row above it has its own caption blanked.
        /// </summary>
        public void FitCaptionHeight()
        {
            var top = string.IsNullOrEmpty(base.Text) ? 8 : Math.Max(24, Font.Height + 9);
            if (Padding.Top != top)
            {
                Padding = new Padding(Padding.Left, top, Padding.Right, Padding.Bottom);
            }
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.Clear(BackColor);
            if (Width < 4 || Height < 4)
            {
                return;
            }
            g.SmoothingMode = SmoothingMode.AntiAlias;
            using (var path = MeshEditorFlatButton.RoundedPath(
                new Rectangle(0, 0, Width - 1, Height - 1), 5))
            using (var pen = new Pen(ThemeBorder))
            {
                g.DrawPath(pen, path);
            }
            g.SmoothingMode = SmoothingMode.Default;
            if (string.IsNullOrEmpty(Text))
            {
                return;
            }
            TextRenderer.DrawText(
                g,
                Text.ToUpperInvariant(),
                Font,
                new Rectangle(12, 7, Math.Max(0, Width - 24), Font.Height + 2),
                ThemeMutedText,
                TextFormatFlags.Left | TextFormatFlags.NoPrefix | TextFormatFlags.EndEllipsis);
        }
    }


    private void ConfigureSimplePreviewOverlay()
    {
        _overlaySettings = new MeshOverlaySettings(
            new MeshOverlayColors(
                Color.FromArgb(48, 60, 74),
                MeshOverlayColors.Default.Vertex,
                MeshOverlayColors.Default.Selection,
                MeshOverlayColors.Default.LiveSelection),
            new MeshOverlaySizing(1.0f, MeshOverlaySizing.Default.VertexMarkerSizePixels));
        _ = _viewport.TrySetSynchronizedDisplayMode(
            _viewport.InitialResidentDisplayMode(HasResidentTextureResources()),
            out _);
    }

    private void ConfigureXRayToggle()
    {
        _xray.CheckedChanged += (_, _) =>
        {
            if (!_xray.Checked && _previewMode.SelectedIndex == 6)
            {
                _previewMode.SelectedIndex = 4;
                return;
            }
            _viewport.SetXRayEnabled(_xray.Checked);
            _statusLabel.Text = _xray.Checked
                ? "X-Ray enabled: visible and occluded topology is drawn without depth rejection; wire and vertex colors switch automatically."
                : "Visible-only selection enabled; picking uses the front surface.";
        };
    }
}
