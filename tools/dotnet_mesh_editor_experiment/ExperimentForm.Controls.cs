using System.Drawing;
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
        control.Height = 24;
        control.BorderStyle = BorderStyle.FixedSingle;
        ApplyCommonControlStyle(control);
    }

    private static void ConfigureCombo(ComboBox combo, object[] values, int selectedIndex)
    {
        combo.Items.Clear();
        combo.Items.AddRange(values);
        combo.SelectedIndex = Math.Clamp(selectedIndex, 0, Math.Max(0, combo.Items.Count - 1));
        combo.DropDownStyle = ComboBoxStyle.DropDownList;
        combo.FlatStyle = FlatStyle.Flat;
        combo.Height = 24;
        ApplyCommonControlStyle(combo);
    }

    private static void ConfigureCheckBox(CheckBox checkBox, string text, bool isChecked)
    {
        checkBox.Text = text;
        checkBox.Checked = isChecked;
        checkBox.AutoSize = false;
        checkBox.Height = 24;
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

    private static Button StyledButton(string text, int height = 26)
    {
        var button = new MeshEditorDepthButton
        {
            Text = text,
            Height = height,
            MinimumSize = new Size(0, height),
            FlatStyle = FlatStyle.Flat,
            ForeColor = ThemeText,
            BackColor = ThemeButtonBackground,
            Margin = new Padding(0, 0, 0, 6),
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
        var modes = new[]
        {
            "textured",
            "untextured_faces",
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
                "Solid + Wire",
                "Wire",
                "Vertices",
                "Wire + Vertices",
                "X-Ray",
            },
            selectedIndex: 0);
        _previewMode.SelectedIndexChanged += (_, _) =>
        {
            var index = Math.Clamp(_previewMode.SelectedIndex, 0, modes.Length - 1);
            if (_viewport.TrySetDisplayMode(modes[index], out var error))
            {
                _xray.Checked = _viewport.ShowXRay;
                _statusLabel.Text = $"Preview mode: {_previewMode.SelectedItem}.";
            }
            else
            {
                _statusLabel.Text = error;
            }
        };
        return LabeledControl("Preview mode", _previewMode);
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
        var note = new Label
        {
            Name = "OverlayAppearanceXRayHint",
            Text = "Colors and sizes are saved. X-Ray uses white wire and magenta vertices while keeping your chosen sizes.",
            AutoSize = true,
            MaximumSize = new Size(248, 0),
            ForeColor = ThemeMutedText,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0, 0, 0, 6),
        };
        return LabeledControl(
            "Topology appearance",
            StackControls(
                ButtonRow(_wireColorButton, _vertexColorButton, reset),
                ButtonRow(
                    LabeledControl("Wire width (px)", _wireOverlayWidth),
                    LabeledControl("Vertex size (px)", _vertexMarkerSize)),
                note));
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
            ColumnCount = 1,
            RowCount = 2,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0, 0, 0, 6),
            Padding = new Padding(0)
        };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        var text = new Label
        {
            Text = label,
            AutoSize = false,
            Height = 18,
            ForeColor = ThemeMutedText,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0, 0, 0, 2)
        };
        control.Margin = new Padding(0);
        panel.Controls.Add(text, 0, 0);
        panel.Controls.Add(control, 0, 1);
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
        for (var index = 0; index < controls.Length; index++)
        {
            panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100.0f / controls.Length));
            var control = controls[index];
            control.Margin = new Padding(index == 0 ? 0 : 3, 0, index == controls.Length - 1 ? 0 : 3, 0);
            control.Dock = DockStyle.Fill;
            panel.Controls.Add(control, index, 0);
        }
        return panel;
    }

    private static GroupBox AddSection(TableLayoutPanel stack, string title, params Control[] controls)
    {
        var group = new GroupBox
        {
            Text = title,
            ForeColor = ThemeText,
            BackColor = ThemeSectionBackground,
            Padding = new Padding(8, 18, 8, 8),
            Margin = new Padding(0, 0, 0, 8),
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink
        };
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

    private static void AddStackRow(TableLayoutPanel stack, Control control)
    {
        var row = stack.RowCount;
        stack.RowCount = row + 1;
        stack.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        control.Dock = DockStyle.Top;
        stack.Controls.Add(control, 0, row);
    }

    private static void ResizeToolStack(ScrollableControl scroll, TableLayoutPanel stack)
    {
        var width = Math.Max(180, scroll.ClientSize.Width - scroll.Padding.Horizontal - SystemInformation.VerticalScrollBarWidth - 2);
        stack.Width = width;
        foreach (Control control in stack.Controls)
        {
            control.Width = width;
            foreach (Control child in control.Controls)
            {
                child.Width = Math.Max(120, width - 20);
            }
        }
    }

    private Button ToolButton(string text, string tool)
    {
        var button = StyledButton(text);
        _toolButtons[tool] = button;
        button.Click += (_, _) => ToggleTool(tool, text);
        return button;
    }

    private void ToggleTool(string tool, string text)
    {
        if (!string.Equals(tool, "orbit", StringComparison.OrdinalIgnoreCase)
            && string.Equals(_viewport.ActiveTool, tool, StringComparison.OrdinalIgnoreCase))
        {
            ActivateTool("orbit", "Orbit");
            return;
        }
        ActivateTool(tool, text);
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
    }

    private void RefreshToolButtonStates()
    {
        foreach (var pair in _toolButtons)
        {
            SetButtonLatched(
                pair.Value,
                string.Equals(pair.Key, _viewport.ActiveTool, StringComparison.OrdinalIgnoreCase));
        }
    }

    private void RefreshGizmoButtonStates()
    {
        foreach (var pair in _gizmoButtons)
        {
            SetButtonLatched(
                pair.Value,
                string.Equals(pair.Key, _scene.GizmoTool, StringComparison.OrdinalIgnoreCase));
        }
    }

    private static void SetButtonLatched(Button button, bool latched)
    {
        if (button is MeshEditorDepthButton depthButton)
        {
            depthButton.SetLatched(latched);
            return;
        }
        button.BackColor = latched ? ThemeAccent : ThemeButtonBackground;
        button.ForeColor = latched ? Color.Black : ThemeText;
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
        if (!string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase))
        {
            _controlsHintLabel.Text = "Orbit: LMB drag  |  Pan: Shift+LMB / MMB / RMB  |  Zoom: Wheel";
            return;
        }
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
        _controlsHintLabel.Text = $"{primary}  |  Orbit override: Ctrl+LMB drag  |  Pan: Shift+LMB / MMB / RMB  |  Zoom: Wheel  |  Undo: Ctrl+Z  |  Redo: Ctrl+Y / Ctrl+Shift+Z";
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
        var enteringMeshEdit = meshEdit && !_meshEditInteractionActive;
        var leavingMeshEdit = !meshEdit && _meshEditInteractionActive;
        _meshEditInteractionActive = meshEdit;
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
        ApplyEmbeddedToolPanelVisibility(meshEdit);
        if (meshEdit)
        {
            _viewport.ActivatePresentationView("editable");
            if (enteringMeshEdit)
            {
                if (_previewMode.SelectedIndex != 5)
                {
                    _previewMode.SelectedIndex = 5;
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
            if (_previewMode.SelectedIndex != 0)
            {
                _previewMode.SelectedIndex = 0;
            }
            if (_viewport.TrySetSynchronizedDisplayMode("textured", out var error))
            {
                _xray.Checked = false;
                _statusLabel.Text = "Preview mode: Solid (Textured).";
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
        if (!_options.Embedded || _toolPanel is null || _editorLayout is null)
        {
            return;
        }
        _editorLayout.ColumnStyles[0].Width = meshEdit ? ToolPanelWidth : 0;
        _toolPanel.Visible = meshEdit;
        _editorLayout.PerformLayout();
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

    private sealed class MeshEditorDepthButton : Button
    {
        private bool _latched;
        private bool _mousePressed;
        private bool _keyboardPressed;

        public MeshEditorDepthButton()
        {
            ResizeRedraw = true;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
        }

        public void SetLatched(bool latched)
        {
            _latched = latched;
            BackColor = latched ? ThemeAccent : ThemeButtonBackground;
            ForeColor = latched ? Color.Black : ThemeText;
            FlatAppearance.MouseOverBackColor = latched ? ThemeAccentHover : ThemeButtonHover;
            FlatAppearance.MouseDownBackColor = latched ? ThemeAccentPressed : ThemeButtonPressed;
            Invalidate();
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            _mousePressed = e.Button == MouseButtons.Left;
            base.OnMouseDown(e);
            Invalidate();
        }

        protected override void OnMouseUp(MouseEventArgs e)
        {
            _mousePressed = false;
            base.OnMouseUp(e);
            Invalidate();
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);
            if (_mousePressed)
            {
                Invalidate();
            }
        }

        protected override void OnMouseEnter(EventArgs e)
        {
            base.OnMouseEnter(e);
            Invalidate();
        }

        protected override void OnMouseLeave(EventArgs e)
        {
            base.OnMouseLeave(e);
            Invalidate();
        }

        protected override void OnMouseCaptureChanged(EventArgs e)
        {
            if (!Capture)
            {
                _mousePressed = false;
            }
            base.OnMouseCaptureChanged(e);
            Invalidate();
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.Space)
            {
                _keyboardPressed = true;
            }
            base.OnKeyDown(e);
            Invalidate();
        }

        protected override void OnKeyUp(KeyEventArgs e)
        {
            if (e.KeyCode == Keys.Space)
            {
                _keyboardPressed = false;
            }
            base.OnKeyUp(e);
            Invalidate();
        }

        protected override void OnLostFocus(EventArgs e)
        {
            _keyboardPressed = false;
            base.OnLostFocus(e);
            Invalidate();
        }

        protected override void OnEnabledChanged(EventArgs e)
        {
            base.OnEnabledChanged(e);
            Invalidate();
        }

        protected override void OnPaint(PaintEventArgs pevent)
        {
            base.OnPaint(pevent);
            if (ClientSize.Width < 4 || ClientSize.Height < 4)
            {
                return;
            }
            var pointerInside = ClientRectangle.Contains(PointToClient(Cursor.Position));
            var sunken = _latched || _keyboardPressed || (_mousePressed && pointerInside);
            var topLeft = Enabled
                ? (sunken ? ThemeButtonShadow : ThemeButtonHighlight)
                : ThemeBorder;
            var bottomRight = Enabled
                ? (sunken ? ThemeButtonHighlight : ThemeButtonShadow)
                : ThemeBorder;
            ControlPaint.DrawBorder(
                pevent.Graphics,
                ClientRectangle,
                topLeft,
                2,
                ButtonBorderStyle.Solid,
                topLeft,
                2,
                ButtonBorderStyle.Solid,
                bottomRight,
                2,
                ButtonBorderStyle.Solid,
                bottomRight,
                2,
                ButtonBorderStyle.Solid);
        }
    }
}
