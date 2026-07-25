using System.Drawing;
using System.Drawing.Drawing2D;
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
        control.Margin = new Padding(0, 0, 0, 6);
    }

    private static int SingleLineControlHeight(Control control, int minimum = 28)
    {
        return Math.Max(minimum, TextRenderer.MeasureText("Ag", control.Font).Height + 10);
    }

    private static Button StyledButton(string text, int height = 30)
    {
        var buttonHeight = Math.Max(height, TextRenderer.MeasureText(text, SystemFonts.MessageBoxFont).Height + 10);
        var button = new MeshEditorFlatButton
        {
            Text = text,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Height = buttonHeight,
            MinimumSize = new Size(0, buttonHeight),
            Padding = new Padding(6, 3, 6, 3),
            FlatStyle = FlatStyle.Flat,
            ForeColor = ThemeText,
            BackColor = ThemeButtonBackground,
            Margin = new Padding(0, 0, 0, 6),
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
            "textured_wire",
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
                "Solid + Wire",
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
            if ((string.Equals(mode, "textured", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(mode, "textured_wire", StringComparison.OrdinalIgnoreCase))
                && _options.Embedded
                && !HasResidentTextureResources())
            {
                var fallbackMode = string.Equals(mode, "textured_wire", StringComparison.OrdinalIgnoreCase)
                    ? "untextured_wire"
                    : "untextured_faces";
                _ = _viewport.TrySetDisplayMode(fallbackMode, out _);
                RequestResidentViewportDisplay(mode);
                return;
            }
            if (_viewport.TrySetDisplayMode(mode, out var error))
            {
                if (!_meshEditInteractionActive)
                {
                    _placementPreviewMode = mode;
                }
                _xray.Checked = _viewport.ShowXRay;
                _statusLabel.Text = $"Preview mode: {_previewMode.SelectedItem}.";
            }
            else
            {
                _statusLabel.Text = error;
            }
        };
    }

    private bool HasResidentTextureResources()
    {
        return _materials.TextureLoadResources().Any()
            || _textureSet.DecodedCount > 0
            || _textureSet.NativeDdsResourceCount > 0;
    }

    private void RequestResidentViewportDisplay(string mode)
    {
        if (string.IsNullOrWhiteSpace(_residentMaterialSessionId)
            || _residentProcessGeneration <= 0)
        {
            SyncPreviewModeSelection(
                string.Equals(mode, "textured_wire", StringComparison.OrdinalIgnoreCase)
                    ? "untextured_wire"
                    : "untextured_faces");
            _statusLabel.Text = "Resident preview is not ready to load textures yet.";
            return;
        }
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

    private void SyncPreviewModeSelection(string mode)
    {
        var normalized = mode.Trim().ToLowerInvariant();
        var index = normalized switch
        {
            "textured" => 0,
            "untextured_faces" => 1,
            "untextured_wire" => 2,
            "textured_wire" => 3,
            "wire" => 4,
            "vertices" => 5,
            "wire_vertices" => 6,
            "xray" => 7,
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

    private Control OverlayAppearanceControls()
    {
        _wireColorButton = OverlayColorButton("Wire", wire: true);
        _vertexColorButton = OverlayColorButton("Vertices", wire: false);
        ConfigureNumeric(
            _wireOverlayWidth,
            decimalPlaces: 2,
            minimum: (decimal)MeshOverlaySizing.MinimumWireWidthPixels,
            maximum: (decimal)MeshOverlaySizing.MaximumWireWidthPixels,
            value: (decimal)_overlaySettings.Sizing.WireWidthPixels,
            increment: 0.05M);
        ConfigureNumeric(
            _vertexMarkerSize,
            decimalPlaces: 1,
            minimum: (decimal)MeshOverlaySizing.MinimumVertexMarkerSizePixels,
            maximum: (decimal)MeshOverlaySizing.MaximumVertexMarkerSizePixels,
            value: (decimal)_overlaySettings.Sizing.VertexMarkerSizePixels,
            increment: 0.5M);
        _wireOverlayWidth.Name = "WireOverlayWidthControl";
        _wireOverlayWidth.AccessibleName = "Wire width in pixels";
        _vertexMarkerSize.Name = "VertexMarkerSizeControl";
        _vertexMarkerSize.AccessibleName = "Vertex size in pixels";
        _wireOverlayWidth.ValueChanged += (_, _) => ApplyOverlaySizing(
            $"Wire width set to {_wireOverlayWidth.Value:0.##} px.");
        _vertexMarkerSize.ValueChanged += (_, _) => ApplyOverlaySizing(
            $"Vertex size set to {_vertexMarkerSize.Value:0.#} px.");
        var reset = StyledActionButton("Reset", ResetOverlayAppearance);
        // Each of these rows owns the section's full width. Nesting them under a
        // shared "Topology appearance" label pushed the sizing row past the
        // inspector edge, which clipped the vertex-size control out of reach.
        return StackControls(
            ButtonRow(_wireColorButton, _vertexColorButton, reset),
            LabeledControl("Wire width (px)", _wireOverlayWidth),
            LabeledControl("Vertex size (px)", _vertexMarkerSize));
    }

    private Button OverlayColorButton(string label, bool wire)
    {
        var button = StyledButton(label);
        button.Click += (_, _) => ChooseOverlayColor(label, wire);
        ApplyOverlayColorButtonStyle(
            button,
            label,
            wire ? _overlaySettings.Colors.Wire : _overlaySettings.Colors.Vertex);
        return button;
    }

    private void ChooseOverlayColor(string label, bool wire)
    {
        var current = wire ? _overlaySettings.Colors.Wire : _overlaySettings.Colors.Vertex;
        using var dialog = new ColorDialog
        {
            Color = current,
            AllowFullOpen = true,
            AnyColor = true,
            FullOpen = true,
            SolidColorOnly = true,
        };
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }
        var colors = wire
            ? _overlaySettings.Colors with { Wire = dialog.Color }
            : _overlaySettings.Colors with { Vertex = dialog.Color };
        _overlaySettings = _overlaySettings with { Colors = colors };
        ApplyOverlaySettings($"{label} color set to {MeshOverlayColors.Hex(dialog.Color)}.");
    }

    private void ApplyOverlaySizing(string status)
    {
        if (_syncingOverlayAppearanceControls)
        {
            return;
        }
        _overlaySettings = _overlaySettings with
        {
            Sizing = new MeshOverlaySizing(
                (float)_wireOverlayWidth.Value,
                (float)_vertexMarkerSize.Value),
        };
        ApplyOverlaySettings(status);
    }

    private void ResetOverlayAppearance()
    {
        _overlaySettings = MeshOverlaySettings.Default;
        ApplyOverlaySettings("Topology appearance reset to black wire, amber vertices, 1.35 px wire, and 7 px vertices.");
    }

    private void ApplyOverlaySettings(string status)
    {
        _overlaySettings = _overlaySettings.Normalized();
        _viewport.SetOverlaySettings(_overlaySettings);
        if (_wireColorButton is not null)
        {
            ApplyOverlayColorButtonStyle(_wireColorButton, "Wire", _overlaySettings.Colors.Wire);
        }
        if (_vertexColorButton is not null)
        {
            ApplyOverlayColorButtonStyle(_vertexColorButton, "Vertices", _overlaySettings.Colors.Vertex);
        }
        _syncingOverlayAppearanceControls = true;
        try
        {
            _wireOverlayWidth.Value = (decimal)_overlaySettings.Sizing.WireWidthPixels;
            _vertexMarkerSize.Value = (decimal)_overlaySettings.Sizing.VertexMarkerSizePixels;
        }
        finally
        {
            _syncingOverlayAppearanceControls = false;
        }
        _statusLabel.Text = MeshOverlayPreferences.TrySave(_overlaySettings, out var error)
            ? status
            : $"{status} Preference save failed: {error}";
    }

    private static void ApplyOverlayColorButtonStyle(Button button, string label, Color color)
    {
        var normalized = Color.FromArgb(color.R, color.G, color.B);
        var lightText = RelativeLuminance(normalized) < 0.44;
        button.Text = $"{label}\n{MeshOverlayColors.Hex(normalized)}";
        button.BackColor = normalized;
        button.ForeColor = lightText ? Color.White : Color.Black;
        button.FlatAppearance.MouseOverBackColor = BlendColor(normalized, Color.White, 0.16f);
        button.FlatAppearance.MouseDownBackColor = BlendColor(normalized, Color.Black, 0.16f);
        button.Height = 42;
        button.MinimumSize = new Size(0, 42);
        button.Invalidate();
    }

    private static double RelativeLuminance(Color color)
    {
        static double Channel(byte value)
        {
            var normalized = value / 255.0;
            return normalized <= 0.04045
                ? normalized / 12.92
                : Math.Pow((normalized + 0.055) / 1.055, 2.4);
        }
        return (0.2126 * Channel(color.R)) + (0.7152 * Channel(color.G)) + (0.0722 * Channel(color.B));
    }

    private static Color BlendColor(Color from, Color to, float amount)
    {
        var weight = Math.Clamp(amount, 0.0f, 1.0f);
        return Color.FromArgb(
            (int)MathF.Round(from.R + ((to.R - from.R) * weight)),
            (int)MathF.Round(from.G + ((to.G - from.G) * weight)),
            (int)MathF.Round(from.B + ((to.B - from.B) * weight)));
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
            Margin = new Padding(0, 0, 0, 6),
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
            MinimumSize = new Size(0, 20),
            ForeColor = ThemeMutedText,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0, 0, 10, 0),
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
        var panel = new TableLayoutPanel
        {
            ColumnCount = Math.Max(1, controls.Length),
            RowCount = 1,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0, 0, 0, 6),
            Padding = new Padding(0)
        };
        var minimumRowWidth = 0;
        for (var index = 0; index < controls.Length; index++)
        {
            panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100.0f / controls.Length));
            var control = controls[index];
            control.Margin = new Padding(index == 0 ? 0 : 3, 0, index == controls.Length - 1 ? 0 : 3, 0);
            var preferredWidth = Math.Max(64, control.GetPreferredSize(Size.Empty).Width);
            control.MinimumSize = new Size(
                Math.Max(control.MinimumSize.Width, preferredWidth),
                control.MinimumSize.Height);
            minimumRowWidth += control.MinimumSize.Width + control.Margin.Horizontal;
            control.Dock = DockStyle.Fill;
            panel.Controls.Add(control, index, 0);
        }
        panel.MinimumSize = new Size(minimumRowWidth, 0);
        return panel;
    }

    private Control BuildToolNavigator(params (string Label, Control Target)[] items)
    {
        var buttons = items.Select(item =>
        {
            var button = StyledButton(item.Label, height: 26);
            button.AccessibleName = $"Go to {item.Label} tools";
            button.Click += (_, _) =>
            {
                if (item.Target.Parent?.Parent is ScrollableControl scrollPanel)
                {
                    scrollPanel.ScrollControlIntoView(item.Target);
                    scrollPanel.Focus();
                }
            };
            return (Control)button;
        }).ToArray();
        var navigator = ButtonRow(buttons);
        navigator.Name = "DotNetMeshEditorLeftToolNavigator";
        navigator.Dock = DockStyle.Top;
        navigator.Margin = new Padding(0);
        navigator.Padding = new Padding(10, 8, 10, 8);
        navigator.BackColor = ThemePanelBackground;
        return navigator;
    }

    private static GroupBox AddSection(TableLayoutPanel stack, string title, params Control[] controls)
    {
        var group = new MeshEditorSectionBox
        {
            Text = title,
            ForeColor = ThemeText,
            BackColor = ThemeSectionBackground,
            Padding = new Padding(10, 24, 10, 10),
            Margin = new Padding(0, 0, 0, 10),
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink
        };
        void FitTitleHeight() => group.Padding = new Padding(
            group.Padding.Left,
            Math.Max(24, group.Font.Height + 9),
            group.Padding.Right,
            group.Padding.Bottom);
        group.FontChanged += (_, _) => FitTitleHeight();
        FitTitleHeight();
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
        foreach (var control in controls)
        {
            AddStackRow(body, control);
        }
        group.Controls.Add(body);
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
        var group = AddSection(stack, title, controls);
        var marker = new Label
        {
            Name = $"DotNetMeshEditor{title.Replace(" ", string.Empty)}Help",
            Text = "?",
            AutoSize = true,
            ForeColor = ThemeAccent,
            BackColor = ThemeSectionBackground,
            Cursor = Cursors.Help,
            TabStop = false,
            TextAlign = ContentAlignment.MiddleCenter,
            AccessibleName = $"{title} help",
            AccessibleDescription = helpText,
            Margin = new Padding(0),
            Padding = new Padding(3, 0, 3, 0),
        };
        _helpToolTip.SetToolTip(marker, helpText);
        marker.Click += (_, _) => _helpToolTip.Show(
            marker.AccessibleDescription ?? helpText,
            marker,
            0,
            marker.Height,
            12000);
        group.Controls.Add(marker);
        marker.BringToFront();
        void PlaceMarker() => marker.Location = new Point(
            Math.Max(group.Padding.Left, group.ClientSize.Width - group.Padding.Right - marker.Width),
            1);
        group.SizeChanged += (_, _) => PlaceMarker();
        marker.SizeChanged += (_, _) => PlaceMarker();
        PlaceMarker();
        helpMarker = marker;
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
        button.Click += (_, _) => ActivateTool(tool, text);
        return button;
    }

    private void ActivateTool(string tool, string text)
    {
        SetActiveTool(tool);
        _statusLabel.Text = tool is "grab" or "smooth" or "inflate" or "pinch"
            ? $"{text} active: left-drag inside the brush circle."
            : $"Tool: {text}";
        UpdateViewportControlsHint();
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
        if (!string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase))
        {
            hint = "Orbit: LMB drag  |  Pan: Shift+LMB / MMB / RMB  |  Zoom: Wheel";
        }
        else
        {
            var tool = (_viewport.ActiveTool ?? string.Empty).Trim().ToLowerInvariant();
            var primary = tool switch
            {
                "select" => $"Select {_selectionTarget.SelectedItem ?? "mesh"}: LMB click/drag",
                "orbit" => "Orbit: LMB drag",
                "move" => "Move selection: LMB drag",
                "grab" => "Grab: LMB drag",
                "smooth" => "Smooth: LMB drag",
                "inflate" => "Inflate: LMB drag",
                "pinch" => "Pinch: LMB drag",
                _ => "Apply tool: LMB drag",
            };
            hint = $"{primary}  |  Orbit override: Ctrl+LMB drag  |  Pan: Shift+LMB / MMB / RMB  |  Zoom: Wheel  |  Undo: Ctrl+Z  |  Redo: Ctrl+Y / Ctrl+Shift+Z";
        }
        _controlsHintLabel.Text = hint;
        SetHelpText(
            _viewportHelpMarker,
            $"{hint}\r\n\r\nChoose the preview mode, topology appearance, or a camera preset. Colors and sizes are saved; X-Ray uses white wire and magenta vertices while preserving those sizes.");
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (_meshEditInteractionActive && (keyData & Keys.Control) == Keys.Control)
        {
            var keyCode = keyData & Keys.KeyCode;
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
            // The first moment the flanks uncollapse is the first moment the
            // panels must exist. Everything below walks the section lists,
            // which stay empty until they are built.
            EnsureAuthoringToolPanelsReady();
        }
        var enteringMeshEdit = meshEdit && !_meshEditInteractionActive;
        var leavingMeshEdit = !meshEdit && _meshEditInteractionActive;
        _meshEditInteractionActive = meshEdit;
        if (!meshEdit)
        {
            RestoreClassicLayoutForNonMeshMode();
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
            if (meshEdit)
            {
                ApplyEmbeddedToolPanelVisibility(meshEdit: true);
                ApplyRequestedEditMeshLayout();
            }
        }
        finally
        {
            ResumeToolPanelLayout();
        }
        if (meshEdit)
        {
            _viewport.ActivatePresentationView("editable");
            if (enteringMeshEdit)
            {
                _viewport.SuppressPlacementGizmoInteraction();
                if (_previewMode.SelectedIndex != 6)
                {
                    _previewMode.SelectedIndex = 6;
                }
                else if (_viewport.TrySetDisplayMode("wire_vertices", out var error))
                {
                    _xray.Checked = _viewport.ShowXRay;
                    _statusLabel.Text = $"Preview mode: {_previewMode.SelectedItem}.";
                }
                else
                {
                    _statusLabel.Text = error;
                }
            }
        }
        else if (leavingMeshEdit)
        {
            var mode = _placementPreviewMode;
            if (!HasResidentTextureResources())
            {
                mode = mode switch
                {
                    "textured" => "untextured_faces",
                    "textured_wire" => "untextured_wire",
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
            ApplySavedToolPanelLayout();
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

    private sealed class MeshEditorBufferedTableLayoutPanel : TableLayoutPanel
    {
        public MeshEditorBufferedTableLayoutPanel()
        {
            DoubleBuffered = true;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
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

    /// <summary>
    /// Flat, rounded, accent-driven button. Replaces the beveled highlight and
    /// shadow border, which is the single strongest "old Windows" cue in the
    /// editor and does not exist anywhere in the Qt shell.
    /// </summary>
    private sealed class MeshEditorFlatButton : Button
    {
        private const int CornerRadius = 4;
        private bool _accent;

        public MeshEditorFlatButton()
        {
            ResizeRedraw = true;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
        }

        public void SetAccent(bool accent)
        {
            _accent = accent;
            BackColor = accent ? ThemeAccent : ThemeButtonBackground;
            ForeColor = accent ? Color.White : ThemeText;
            FlatAppearance.MouseOverBackColor = accent ? ThemeAccentHover : ThemeButtonHover;
            FlatAppearance.MouseDownBackColor = accent ? ThemeAccentPressed : ThemeButtonPressed;
            Invalidate();
        }

        internal static GraphicsPath RoundedPath(Rectangle bounds, int radius)
        {
            var path = new GraphicsPath();
            var d = Math.Max(1, radius * 2);
            if (bounds.Width <= d || bounds.Height <= d)
            {
                path.AddRectangle(bounds);
                return path;
            }
            path.AddArc(bounds.X, bounds.Y, d, d, 180, 90);
            path.AddArc(bounds.Right - d, bounds.Y, d, d, 270, 90);
            path.AddArc(bounds.Right - d, bounds.Bottom - d, d, d, 0, 90);
            path.AddArc(bounds.X, bounds.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            ApplyRoundedRegion();
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            ApplyRoundedRegion();
        }

        private void ApplyRoundedRegion()
        {
            if (Width < 4 || Height < 4)
            {
                return;
            }
            using var path = RoundedPath(new Rectangle(0, 0, Width, Height), CornerRadius);
            var previous = Region;
            Region = new Region(path);
            previous?.Dispose();
        }

        protected override void OnPaint(PaintEventArgs pevent)
        {
            base.OnPaint(pevent);
            if (Width < 4 || Height < 4)
            {
                return;
            }
            pevent.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using var path = RoundedPath(new Rectangle(0, 0, Width - 1, Height - 1), CornerRadius);
            using var pen = new Pen(
                !Enabled ? ThemeBorder : _accent ? ThemeAccent : ThemeButtonBorder);
            pevent.Graphics.DrawPath(pen, path);
        }
    }

    /// <summary>
    /// A flat card instead of the Win32 etched group frame: hairline rounded
    /// border, uppercase caption, no notch.
    /// </summary>
    private sealed class MeshEditorSectionBox : GroupBox
    {
        public MeshEditorSectionBox()
        {
            ResizeRedraw = true;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
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
}
