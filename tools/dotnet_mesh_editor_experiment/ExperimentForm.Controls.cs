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
        var button = new Button
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
        button.FlatAppearance.BorderColor = ThemeBorder;
        button.FlatAppearance.MouseOverBackColor = ThemeButtonHover;
        button.FlatAppearance.MouseDownBackColor = ThemeAccent;
        return button;
    }

    private static Button DisabledButton(string text, string reason)
    {
        var button = StyledButton(text);
        button.Enabled = false;
        button.Text = text;
        button.Tag = reason;
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
        var combo = new ComboBox();
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
            combo,
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
        combo.SelectedIndexChanged += (_, _) =>
        {
            var index = Math.Clamp(combo.SelectedIndex, 0, modes.Length - 1);
            if (_viewport.TrySetDisplayMode(modes[index], out var error))
            {
                _xray.Checked = _viewport.ShowXRay;
                _statusLabel.Text = $"Preview mode: {combo.SelectedItem}.";
            }
            else
            {
                _statusLabel.Text = error;
            }
        };
        return LabeledControl("Preview mode", combo);
    }

    private Control MaterialDebugModeControl()
    {
        var combo = new ComboBox();
        ConfigureCombo(combo, new object[] { "Final", "Base", "Normal", "Roughness", "Metallic", "Emissive", "Specular" }, selectedIndex: 0);
        combo.SelectedIndexChanged += (_, _) =>
        {
            _viewport.MaterialDebugMode = combo.SelectedIndex;
            _viewport.Invalidate();
            _statusLabel.Text = $"Material debug: {combo.SelectedItem}.";
        };
        return LabeledControl("Material debug", combo);
    }

    private static string MaterialDebugModeName(int mode)
    {
        return Math.Clamp(mode, 0, 6) switch
        {
            1 => "base",
            2 => "normal",
            3 => "roughness",
            4 => "metallic",
            5 => "emissive",
            6 => "specular",
            _ => "final",
        };
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

    private static void AddSection(TableLayoutPanel stack, string title, params Control[] controls)
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
        button.Click += (_, _) =>
        {
            _viewport.ActiveTool = tool;
            _statusLabel.Text = $"Tool: {text}";
        };
        return button;
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
}
