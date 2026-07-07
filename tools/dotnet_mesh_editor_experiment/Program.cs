using System.Diagnostics;
using System.IO;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            var options = LaunchOptions.Parse(args);
            var document = ObjDocument.Load(options.MeshPath);
            Directory.CreateDirectory(options.OutputDir);
            if (options.HeadlessSmoke)
            {
                var editedSubmeshes = ExperimentForm.ApplyHeadlessSmokeEdit(document);
                ExperimentForm.SaveOutput(options, document, editedSubmeshes, HeadlessRenderer.Measure(document));
                return 0;
            }

            ApplicationConfiguration.Initialize();
            Application.Run(new ExperimentForm(options, document));
            return 0;
        }
        catch (Exception ex)
        {
            var options = LaunchOptions.TryParse(args);
            if (options is not null)
            {
                ExperimentForm.WriteStatus(options, "error", ex.Message, null);
            }
            var suppressDialog = Array.Exists(args, arg =>
                string.Equals(arg, "--embedded", StringComparison.OrdinalIgnoreCase)
                || string.Equals(arg, "--headless-smoke", StringComparison.OrdinalIgnoreCase));
            if (!suppressDialog)
            {
                MessageBox.Show(ex.Message, "CDMW .NET Mesh Editor Experiment", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            return 1;
        }
    }
}

internal sealed class ExperimentForm : Form
{
    private static readonly UTF8Encoding Utf8NoBom = new(false);
    private static readonly Color ThemeWindowBackground = Color.FromArgb(15, 20, 26);
    private static readonly Color ThemePanelBackground = Color.FromArgb(21, 27, 35);
    private static readonly Color ThemeSectionBackground = Color.FromArgb(25, 32, 41);
    private static readonly Color ThemeInputBackground = Color.FromArgb(31, 39, 49);
    private static readonly Color ThemeButtonBackground = Color.FromArgb(36, 46, 58);
    private static readonly Color ThemeButtonHover = Color.FromArgb(47, 60, 75);
    private static readonly Color ThemeBorder = Color.FromArgb(62, 75, 91);
    private static readonly Color ThemeAccent = Color.FromArgb(92, 169, 255);
    private static readonly Color ThemeText = Color.FromArgb(222, 232, 242);
    private static readonly Color ThemeMutedText = Color.FromArgb(151, 169, 186);
    private static readonly Color ThemeStatusBackground = Color.FromArgb(18, 25, 32);
    private readonly LaunchOptions _options;
    private readonly ObjDocument _document;
    private readonly MeshViewport _viewport;
    private readonly ListBox _submeshList = new();
    private readonly NumericUpDown _translateStep = new();
    private readonly ComboBox _selectionTarget = new();
    private readonly ComboBox _selectionOperation = new();
    private readonly CheckBox _xray = new();
    private readonly NumericUpDown _radius = new();
    private readonly NumericUpDown _strength = new();
    private readonly ComboBox _falloff = new();
    private readonly Label _statusLabel = new();
    private readonly Label _fpsLabel = new();
    private readonly NetMaterialSet _materials;
    private readonly NetTextureSet _textureSet;
    private readonly HashSet<int> _editedSubmeshes = new();
    private readonly System.Windows.Forms.Timer _timer = new();
    private bool _saved;
    private bool _externalTopologyDirty;
    private DateTime _lastMetricsProtocolUtc = DateTime.MinValue;

    public ExperimentForm(LaunchOptions options, ObjDocument document)
    {
        _options = options;
        _document = document;
        _materials = NetMaterialSet.Load(options.MaterialsPath);
        _textureSet = NetTextureSet.Load(_materials);
        Text = "CDMW .NET Mesh Editor Experiment";
        Width = 1180;
        Height = 760;
        BackColor = ThemeWindowBackground;
        ForeColor = ThemeText;
        StartPosition = options.Embedded ? FormStartPosition.Manual : FormStartPosition.CenterScreen;
        if (options.Embedded)
        {
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            MinimizeBox = false;
            MaximizeBox = false;
            Left = 0;
            Top = 0;
        }

        _viewport = new MeshViewport(document, _materials, _textureSet) { Dock = DockStyle.Fill };
        _viewport.ToolOptionsProvider = ToolOptionsPayload;
        _viewport.EditorEventRequested += WriteProtocolEvent;
        _viewport.StatusRequested += message => _statusLabel.Text = message;
        _viewport.SubmeshSelectedRequested += index =>
        {
            if (index >= 0 && index < _submeshList.Items.Count && _submeshList.SelectedIndex != index)
            {
                _submeshList.SelectedIndex = index;
            }
        };
        _submeshList.Dock = DockStyle.Fill;
        _submeshList.IntegralHeight = false;
        for (var index = 0; index < document.Submeshes.Count; index++)
        {
            _submeshList.Items.Add($"{index}: {document.Submeshes[index].Name}");
        }
        if (_submeshList.Items.Count > 0)
        {
            _submeshList.SelectedIndex = 0;
        }
        _submeshList.SelectedIndexChanged += (_, _) => _viewport.SelectedSubmeshIndex = _submeshList.SelectedIndex;

        ConfigureNumeric(_translateStep, decimalPlaces: 4, minimum: -10, maximum: 10, value: 0.0100M, increment: 0.0100M);
        ConfigureCombo(_selectionTarget, new object[] { "Vertex", "Face", "Edge", "Part" }, selectedIndex: 0);
        ConfigureCombo(_selectionOperation, new object[] { "Replace", "Add", "Subtract", "Toggle" }, selectedIndex: 0);
        ConfigureCheckBox(_xray, "X-Ray", isChecked: false);
        _xray.CheckedChanged += (_, _) =>
        {
            _viewport.ShowXRay = _xray.Checked;
            _viewport.Invalidate();
            _statusLabel.Text = _xray.Checked
                ? "X-Ray selection enabled; picking can include occluded mesh elements."
                : "Visible-only selection enabled; picking uses the front surface.";
        };
        ConfigureNumeric(_radius, decimalPlaces: 1, minimum: 1, maximum: 512, value: 24, increment: 2);
        ConfigureNumeric(_strength, decimalPlaces: 2, minimum: 0, maximum: 5, value: 0.5M, increment: 0.05M);
        ConfigureCombo(_falloff, new object[] { "Smooth", "Linear", "Constant" }, selectedIndex: 0);

        _fpsLabel.AutoSize = false;
        _fpsLabel.Height = 22;
        _fpsLabel.ForeColor = ThemeMutedText;
        _fpsLabel.BackColor = ThemeStatusBackground;
        _fpsLabel.Dock = DockStyle.Top;
        _statusLabel.AutoSize = false;
        _statusLabel.Height = 48;
        _statusLabel.ForeColor = ThemeText;
        _statusLabel.BackColor = ThemeStatusBackground;
        _statusLabel.Dock = DockStyle.Fill;
        _statusLabel.Text = $"Loaded package. materials={_materials.SlotCount} textureRefs={_materials.TextureReferenceCount} resolved={_materials.ExistingTextureFileCount}/{_materials.ResolvedTextureReferenceCount} decodable={_textureSet.DecodedCount}/{_materials.DecodableTextureFileCount}. Solid view is on; wire overlay is optional.";

        Controls.Add(_viewport);
        Controls.Add(BuildToolPanel());

        _timer.Interval = 16;
        _timer.Tick += (_, _) =>
        {
            if (_options.Embedded && _options.ParentHwnd > 0)
            {
                NativeWindowHost.ResizeToParent(this, new IntPtr(_options.ParentHwnd));
                if (File.Exists(_options.CloseRequestPath))
                {
                    Close();
                    return;
                }
            }
            if (_viewport.ConsumeRenderRequest())
            {
                _viewport.Invalidate();
            }
            _fpsLabel.Text = $"FPS: {_viewport.Metrics.AverageFps:0.0} | Frame: {_viewport.Metrics.AverageFrameMs:0.00} ms | Present: {_viewport.Metrics.AveragePresentMs:0.00} ms";
            if ((DateTime.UtcNow - _lastMetricsProtocolUtc).TotalMilliseconds >= 500)
            {
                _lastMetricsProtocolUtc = DateTime.UtcNow;
                var metricsPayload = MetricsPayload(_viewport.Metrics);
                metricsPayload["renderer"] = _viewport.RendererStatusPayload();
                WriteProtocolEvent("metrics", metricsPayload);
            }
        };
        _timer.Start();
        StartProtocolReader();
        WriteStatus(_options, "loaded", "Mesh loaded in .NET editor experiment.", _viewport.Metrics);
        WriteProtocolEvent("ready", new Dictionary<string, object?>
        {
            ["capabilities"] = _viewport.ActiveCapabilities(),
            ["selection_depth_mode"] = "visible",
            ["renderer"] = _viewport.RendererStatusPayload()
        });
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        if (_options.Embedded && _options.ParentHwnd > 0)
        {
            if (NativeWindowHost.Embed(this, new IntPtr(_options.ParentHwnd)))
            {
                _statusLabel.Text = "Embedded .NET mesh editor ready.";
            }
            else
            {
                _statusLabel.Text = "Embedded host was not available; .NET editor is running borderless.";
            }
        }
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (!_saved && _options.Embedded && _editedSubmeshes.Count > 0 && !_externalTopologyDirty)
        {
            SaveAndReport();
        }
        if (!_saved)
        {
            WriteStatus(_options, "closed", "Mesh .NET editor experiment closed without saving.", _viewport.Metrics);
        }
        _textureSet.Dispose();
        base.OnFormClosing(e);
    }

    private Panel BuildToolPanel()
    {
        _submeshList.BackColor = ThemeInputBackground;
        _submeshList.ForeColor = ThemeText;
        _submeshList.BorderStyle = BorderStyle.FixedSingle;
        _submeshList.Height = 104;
        _submeshList.Font = new Font(Font.FontFamily, 8.5f);

        var save = StyledButton("Save Edited Package", height: 30);
        save.Click += (_, _) => SaveAndReport();

        var solid = ToolCheckBox("Solid", true);
        solid.CheckedChanged += (_, _) =>
        {
            _viewport.ShowSolid = solid.Checked;
            _viewport.Invalidate();
        };
        var wire = ToolCheckBox("Wire", false);
        wire.CheckedChanged += (_, _) =>
        {
            _viewport.ShowWire = wire.Checked;
            _viewport.Invalidate();
        };
        var partPick = ToolCheckBox("Part Pick", false);
        partPick.CheckedChanged += (_, _) =>
        {
            if (partPick.Checked)
            {
                _selectionTarget.SelectedItem = "Part";
                _statusLabel.Text = "Part Pick enabled; selection requests target source parts.";
            }
        };
        var gizmo = DisabledButton("Gizmo", "Gizmo handles are owned by the native host path in this build.");

        var left = new Panel
        {
            Name = "DotNetMeshEditorToolPanel",
            Dock = DockStyle.Left,
            Width = 286,
            Padding = new Padding(0),
            BackColor = ThemePanelBackground
        };
        var statusFooter = new Panel
        {
            Dock = DockStyle.Bottom,
            Height = 82,
            Padding = new Padding(10, 6, 10, 8),
            BackColor = ThemeStatusBackground
        };
        statusFooter.Controls.Add(_statusLabel);
        statusFooter.Controls.Add(_fpsLabel);

        var scroll = new Panel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Padding = new Padding(8),
            BackColor = ThemePanelBackground
        };
        var stack = new TableLayoutPanel
        {
            Name = "DotNetMeshEditorToolStack",
            ColumnCount = 1,
            RowCount = 0,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Dock = DockStyle.Top,
            BackColor = ThemePanelBackground,
            Margin = new Padding(0),
            Padding = new Padding(0)
        };
        stack.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        scroll.Controls.Add(stack);
        scroll.Resize += (_, _) => ResizeToolStack(scroll, stack);

        AddSection(stack, "Mesh Edit Session",
            save,
            ButtonRow(CommandButton("Clear Selection", "clear_selection"), CommandButton("Select All", "select_all")),
            ButtonRow(CommandButton("Invert", "invert"), CommandButton("Undo", "undo"), CommandButton("Redo", "redo")));
        AddSection(stack, "Parts",
            _submeshList,
            partPick);
        AddSection(stack, "Selection",
            LabeledControl("Selection target", _selectionTarget),
            LabeledControl("Selection mode", _selectionOperation),
            _xray,
            ButtonRow(ToolButton("Select", "select"), CommandButton("Grow", "grow"), CommandButton("Shrink", "shrink")));
        AddSection(stack, "Transform",
            LabeledControl("Translate step", _translateStep),
            ButtonRow(StyledActionButton("Move +X", () => TranslateSelected((float)_translateStep.Value)), StyledActionButton("Move -X", () => TranslateSelected(-(float)_translateStep.Value))),
            ButtonRow(ToolButton("Move", "move"), ToolButton("Grab", "grab"), gizmo));
        AddSection(stack, "Brush Tools",
            LabeledControl("Radius", _radius),
            LabeledControl("Strength", _strength),
            LabeledControl("Falloff", _falloff),
            ButtonRow(ToolButton("Smooth", "smooth"), ToolButton("Inflate", "inflate"), ToolButton("Pinch", "pinch")));
        AddSection(stack, "Topology",
            ButtonRow(CommandButton("Delete", "delete"), CommandButton("Subdivide", "subdivide")),
            ButtonRow(CommandButton("Refine Smooth", "refine_smooth"), CommandButton("Duplicate", "duplicate")));
        AddSection(stack, "Clipboard",
            ButtonRow(
                DisabledButton("Copy", "Mesh clipboard is disabled until metadata-preserving paste is proved; use Duplicate for same-selection copies."),
                DisabledButton("Paste", "Mesh clipboard is disabled until metadata-preserving paste is proved; use Duplicate for same-selection copies.")));
        AddSection(stack, "Viewport",
            PreviewModeControl(solid, wire),
            MaterialDebugModeControl(),
            ButtonRow(CameraButton("Front", "front"), CameraButton("Left", "left"), CameraButton("Right", "right")),
            ButtonRow(CameraButton("Back", "back"), CameraButton("Top", "top"), CameraButton("Bottom", "bottom")),
            ButtonRow(StyledActionButton("-15", () => _viewport.RotateYawDegrees(-15.0f)), StyledActionButton("+15", () => _viewport.RotateYawDegrees(15.0f)), StyledActionButton("Reset/Fit", _viewport.FrameMesh)),
            ToolButton("Orbit", "orbit"));

        left.Controls.Add(scroll);
        left.Controls.Add(statusFooter);
        ResizeToolStack(scroll, stack);
        return left;
    }

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

    private Control PreviewModeControl(CheckBox solid, CheckBox wire)
    {
        var combo = new ComboBox();
        ConfigureCombo(combo, new object[] { "Solid", "Solid + Wire", "Wire", "X-Ray" }, selectedIndex: 0);
        combo.SelectedIndexChanged += (_, _) =>
        {
            var value = SelectionText(combo, "solid");
            solid.Checked = value is "solid" or "solid_+_wire";
            wire.Checked = value is "wire" or "solid_+_wire" or "x-ray";
            _xray.Checked = value == "x-ray";
            _statusLabel.Text = $"Preview mode: {combo.SelectedItem}.";
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
            var targetMode = SelectionTarget();
            if (_viewport.TryHandleLocalCommand(command, targetMode))
            {
                return;
            }
            WriteProtocolEvent("command_request", new Dictionary<string, object?>
            {
                ["command"] = command,
                ["target_mode"] = targetMode,
                ["selection_depth_mode"] = SelectionDepthMode(),
                ["local_selection"] = _viewport.SelectionSnapshotPayload()
            });
        };
        return button;
    }

    private Dictionary<string, object?> ToolOptionsPayload()
    {
        return new Dictionary<string, object?>
        {
            ["target_mode"] = SelectionTarget(),
            ["operation"] = SelectionOperation(),
            ["selection_depth_mode"] = SelectionDepthMode(),
            ["radius"] = (double)_radius.Value,
            ["strength"] = (double)_strength.Value,
            ["falloff"] = SelectionText(_falloff, "smooth")
        };
    }

    private string SelectionTarget()
    {
        var selected = SelectionText(_selectionTarget, "vertex");
        return selected == "part" ? "source" : selected;
    }

    private string SelectionOperation()
    {
        return SelectionText(_selectionOperation, "replace");
    }

    private string SelectionDepthMode()
    {
        return _xray.Checked ? "xray" : "visible";
    }

    private static string SelectionText(ComboBox combo, string fallback)
    {
        return (combo.SelectedItem?.ToString() ?? fallback).Trim().ToLowerInvariant().Replace(" ", "_");
    }

    private static Dictionary<string, object?> MetricsPayload(RenderMetrics metrics)
    {
        return new Dictionary<string, object?>
        {
            ["metrics"] = new Dictionary<string, object?>
            {
                ["average_fps"] = metrics.AverageFps,
                ["frame_time_ms"] = metrics.AverageFrameMs,
                ["present_time_ms"] = metrics.AveragePresentMs,
                ["dirty_to_present_ms"] = metrics.AverageDirtyToPresentMs,
                ["dropped_frames"] = metrics.DroppedFrames,
                ["responsiveness_ms"] = metrics.AverageResponsivenessMs,
                ["memory_mb"] = Process.GetCurrentProcess().WorkingSet64 / (1024.0 * 1024.0)
            }
        };
    }

    private void StartProtocolReader()
    {
        _ = Task.Run(() =>
        {
            try
            {
                string? line;
                while ((line = Console.In.ReadLine()) is not null)
                {
                    var captured = line;
                    try
                    {
                        BeginInvoke(new Action(() => HandleProtocolLine(captured)));
                    }
                    catch (InvalidOperationException)
                    {
                        break;
                    }
                }
            }
            catch (IOException)
            {
            }
        });
    }

    private void HandleProtocolLine(string line)
    {
        if (string.IsNullOrWhiteSpace(line))
        {
            return;
        }
        try
        {
            using var document = JsonDocument.Parse(line);
            if (document.RootElement.ValueKind != JsonValueKind.Object)
            {
                return;
            }
            var eventName = JsonString(document.RootElement, "event");
            if (eventName.Length == 0)
            {
                eventName = JsonString(document.RootElement, "type");
            }
            switch (eventName.Trim().ToLowerInvariant())
            {
                case "close_request":
                    Close();
                    break;
                case "session_state":
                    ApplySelectionUpdate(document.RootElement);
                    _statusLabel.Text = "Live MeshService bridge connected.";
                    break;
                case "selection_update":
                    ApplySelectionUpdate(document.RootElement);
                    _statusLabel.Text = "Selection updated by MeshService.";
                    break;
                case "preview_vertex_update":
                    ApplyPreviewVertexUpdate(document.RootElement);
                    break;
                case "preview_triangle_update":
                    ApplyPreviewTriangleUpdate(document.RootElement);
                    break;
                case "command_result":
                    _statusLabel.Text = $"Command result: {JsonString(document.RootElement, "status")}";
                    break;
            }
        }
        catch (JsonException ex)
        {
            WriteProtocolEvent("error", new Dictionary<string, object?> { ["message"] = $"Malformed protocol JSON: {ex.Message}" });
        }
    }

    private void ApplyPreviewVertexUpdate(JsonElement root)
    {
        if (!root.TryGetProperty("vertex_groups", out var groups) || groups.ValueKind != JsonValueKind.Array)
        {
            return;
        }
        var changed = false;
        foreach (var group in groups.EnumerateArray())
        {
            if (group.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var submeshIndex = JsonInt(group, "source_submesh_index", JsonInt(group, "index", -1));
            if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            var positions = JsonDoubleValues(group, "positions");
            if (positions.Count == 0 && group.TryGetProperty("positions_binary", out var positionsBinary))
            {
                positions = ReadDoubleBinary(positionsBinary);
            }
            if (positions.Count < 3)
            {
                continue;
            }
            var indices = JsonIntValues(group, "source_vertex_indices");
            if (indices.Count == 0 && group.TryGetProperty("source_vertex_indices_binary", out var indicesBinary))
            {
                indices = ReadIntBinary(indicesBinary);
            }
            if (indices.Count == 0)
            {
                var start = JsonInt(group, "source_vertex_start", -1);
                var count = JsonInt(group, "source_vertex_count", 0);
                if (start >= 0 && count > 0)
                {
                    indices = Enumerable.Range(start, count).ToList();
                }
            }
            if (indices.Count == 0 && positions.Count / 3 == submesh.Vertices.Count)
            {
                indices = Enumerable.Range(0, submesh.Vertices.Count).ToList();
            }
            var updateCount = Math.Min(indices.Count, positions.Count / 3);
            for (var i = 0; i < updateCount; i++)
            {
                var vertexIndex = indices[i];
                if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
                {
                    continue;
                }
                var p = i * 3;
                submesh.Vertices[vertexIndex] = new Vec3((float)positions[p], (float)positions[p + 1], (float)positions[p + 2]);
                changed = true;
            }
            if (updateCount > 0)
            {
                _editedSubmeshes.Add(submeshIndex);
            }
        }
        if (changed)
        {
            _viewport.RefreshBounds();
            _viewport.Invalidate();
            _statusLabel.Text = "Vertex update applied from MeshService.";
        }
    }

    private void ApplyPreviewTriangleUpdate(JsonElement root)
    {
        if (!root.TryGetProperty("triangle_groups", out var groups) || groups.ValueKind != JsonValueKind.Array)
        {
            return;
        }
        var changed = false;
        foreach (var group in groups.EnumerateArray())
        {
            if (group.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var submeshIndex = JsonInt(group, "source_submesh_index", JsonInt(group, "index", -1));
            if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var positions = JsonDoubleValues(group, "positions");
            if (positions.Count == 0 && group.TryGetProperty("positions_binary", out var positionsBinary))
            {
                positions = ReadDoubleBinary(positionsBinary);
            }
            var indices = JsonIntValues(group, "indices");
            if (indices.Count == 0 && group.TryGetProperty("indices_binary", out var indicesBinary))
            {
                indices = ReadIntBinary(indicesBinary);
            }
            if (positions.Count == 0 || indices.Count == 0)
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            submesh.Vertices.Clear();
            for (var i = 0; i + 2 < positions.Count; i += 3)
            {
                submesh.Vertices.Add(new Vec3((float)positions[i], (float)positions[i + 1], (float)positions[i + 2]));
            }
            var normals = JsonDoubleValues(group, "normals");
            if (normals.Count == 0 && group.TryGetProperty("normals_binary", out var normalsBinary))
            {
                normals = ReadDoubleBinary(normalsBinary);
            }
            submesh.Normals.Clear();
            for (var i = 0; i + 2 < normals.Count; i += 3)
            {
                submesh.Normals.Add(new Vec3((float)normals[i], (float)normals[i + 1], (float)normals[i + 2]));
            }
            var uvs = JsonDoubleValues(group, "uvs");
            if (uvs.Count == 0 && group.TryGetProperty("uvs_binary", out var uvsBinary))
            {
                uvs = ReadDoubleBinary(uvsBinary);
            }
            submesh.Uvs.Clear();
            for (var i = 0; i + 1 < uvs.Count; i += 2)
            {
                submesh.Uvs.Add(new Vec2((float)uvs[i], (float)uvs[i + 1]));
            }
            submesh.Faces.Clear();
            for (var i = 0; i + 2 < indices.Count; i += 3)
            {
                submesh.Faces.Add(new ObjFace(new[]
                {
                    new ObjCorner(indices[i], indices[i], indices[i]),
                    new ObjCorner(indices[i + 1], indices[i + 1], indices[i + 1]),
                    new ObjCorner(indices[i + 2], indices[i + 2], indices[i + 2])
                }));
            }
            changed = true;
        }
        if (changed)
        {
            _externalTopologyDirty = true;
            _viewport.RefreshBounds();
            _viewport.Invalidate();
            _statusLabel.Text = "Topology preview updated by MeshService; Python session remains authoritative.";
        }
    }

    private void ApplySelectionUpdate(JsonElement root)
    {
        if (!root.TryGetProperty("selection", out var selection) || selection.ValueKind != JsonValueKind.Object)
        {
            return;
        }
        var vertices = JsonSelectionMap(selection, "vertices_by_submesh");
        var faces = JsonSelectionMap(selection, "faces_by_submesh");
        var sources = JsonIntSet(selection, "source_indices");
        _viewport.UpdateSelection(vertices, faces, sources);
        _viewport.Invalidate();
    }

    private static Dictionary<int, HashSet<int>> JsonSelectionMap(JsonElement element, string name)
    {
        var result = new Dictionary<int, HashSet<int>>();
        if (!element.TryGetProperty(name, out var value))
        {
            return result;
        }
        return JsonSelectionMap(value);
    }

    private static Dictionary<int, HashSet<int>> JsonSelectionMap(JsonElement value)
    {
        var result = new Dictionary<int, HashSet<int>>();
        if (value.ValueKind != JsonValueKind.Array)
        {
            return result;
        }
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Array)
            {
                continue;
            }
            var parts = item.EnumerateArray().ToArray();
            if (parts.Length >= 2 && parts[0].ValueKind == JsonValueKind.Number && parts[0].TryGetInt32(out var key))
            {
                result[key] = JsonIntSet(parts[1]);
            }
        }
        return result;
    }

    private static HashSet<int> JsonIntSet(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) ? JsonIntSet(value) : new HashSet<int>();
    }

    private static HashSet<int> JsonIntSet(JsonElement value)
    {
        var result = new HashSet<int>();
        if (value.ValueKind != JsonValueKind.Array)
        {
            return result;
        }
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Number && item.TryGetInt32(out var number))
            {
                result.Add(number);
            }
            else if (item.ValueKind == JsonValueKind.String && int.TryParse(item.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out number))
            {
                result.Add(number);
            }
        }
        return result;
    }

    private static string JsonString(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? ""
            : "";
    }

    private static int JsonInt(JsonElement element, string name, int fallback)
    {
        if (!element.TryGetProperty(name, out var value))
        {
            return fallback;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number))
        {
            return number;
        }
        return value.ValueKind == JsonValueKind.String && int.TryParse(value.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out number)
            ? number
            : fallback;
    }

    private static List<int> JsonIntValues(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return new List<int>();
        }
        var result = new List<int>();
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Number && item.TryGetInt32(out var number))
            {
                result.Add(number);
            }
        }
        return result;
    }

    private static List<double> JsonDoubleValues(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return new List<double>();
        }
        var result = new List<double>();
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Number && item.TryGetDouble(out var number))
            {
                result.Add(number);
            }
        }
        return result;
    }

    private static List<int> ReadIntBinary(JsonElement descriptor)
    {
        var path = JsonString(descriptor, "path");
        var count = JsonInt(descriptor, "count", 0);
        if (path.Length == 0 || count <= 0 || !File.Exists(path))
        {
            return new List<int>();
        }
        var bytes = File.ReadAllBytes(path);
        var result = new List<int>(Math.Min(count, bytes.Length / sizeof(int)));
        for (var offset = 0; offset + sizeof(int) <= bytes.Length && result.Count < count; offset += sizeof(int))
        {
            result.Add(BitConverter.ToInt32(bytes, offset));
        }
        return result;
    }

    private static List<double> ReadDoubleBinary(JsonElement descriptor)
    {
        var path = JsonString(descriptor, "path");
        var count = JsonInt(descriptor, "count", 0);
        var components = JsonInt(descriptor, "components", 1);
        var total = count * components;
        if (path.Length == 0 || total <= 0 || !File.Exists(path))
        {
            return new List<double>();
        }
        var bytes = File.ReadAllBytes(path);
        var result = new List<double>(Math.Min(total, bytes.Length / sizeof(double)));
        for (var offset = 0; offset + sizeof(double) <= bytes.Length && result.Count < total; offset += sizeof(double))
        {
            result.Add(BitConverter.ToDouble(bytes, offset));
        }
        return result;
    }

    private static void WriteProtocolEvent(string eventName, Dictionary<string, object?>? payload = null)
    {
        var message = payload is null
            ? new Dictionary<string, object?>()
            : new Dictionary<string, object?>(payload);
        message["event"] = eventName;
        Console.Out.WriteLine(JsonSerializer.Serialize(message));
        Console.Out.Flush();
    }

    private void TranslateSelected(float deltaX)
    {
        var index = _submeshList.SelectedIndex;
        if (index < 0 || index >= _document.Submeshes.Count)
        {
            return;
        }
        var submesh = _document.Submeshes[index];
        var selectedVertices = _viewport.EditableVertexIndicesForSubmesh(index);
        var targetVertices = selectedVertices.Length > 0
            ? selectedVertices
            : Enumerable.Range(0, submesh.Vertices.Count).ToArray();
        foreach (var i in targetVertices)
        {
            var vertex = submesh.Vertices[i];
            submesh.Vertices[i] = vertex with { X = vertex.X + deltaX };
        }
        _editedSubmeshes.Add(index);
        _viewport.RefreshBounds();
        _viewport.Invalidate();
        _statusLabel.Text = selectedVertices.Length > 0
            ? $"Moved {targetVertices.Length} selected vertex item(s) in submesh {index} by {deltaX:0.####} on X."
            : $"Moved submesh {index} by {deltaX:0.####} on X.";
    }

    private void SaveAndReport()
    {
        SaveOutput(_options, _document, _editedSubmeshes, _viewport.Metrics);
        _saved = true;
        _statusLabel.Text = $"Saved edited package: {_options.OutputDir}";
    }

    public static void SaveOutput(
        LaunchOptions options,
        ObjDocument document,
        IEnumerable<int> editedSubmeshIndices,
        RenderMetrics metrics)
    {
        Directory.CreateDirectory(options.OutputDir);
        var outputObj = Path.Combine(options.OutputDir, "mesh.obj");
        document.Save(outputObj, options.MeshPath);
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
            outputObj);
    }

    public static void WriteStatus(
        LaunchOptions options,
        string eventName,
        string message,
        RenderMetrics? metrics,
        string? editedMeshPath = null)
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
            ["metrics"] = new Dictionary<string, object?>
            {
                ["average_fps"] = metrics?.AverageFps,
                ["frame_time_ms"] = metrics?.AverageFrameMs,
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
        File.WriteAllText(
            options.StatusPath,
            JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }),
            Utf8NoBom);
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
        var operations = editedSubmeshIndices
            .Where(index => index >= 0 && index < document.Submeshes.Count)
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

internal sealed class MeshViewport : Control
{
    private readonly ObjDocument _document;
    private readonly NetMaterialSet _materials;
    private readonly NetTextureSet _textureSet;
    private readonly Stopwatch _clock = Stopwatch.StartNew();
    private Point _lastMouse;
    private bool _rotating;
    private bool _panning;
    private float _yaw = -0.35f;
    private float _pitch = 0.25f;
    private float _zoom = 220.0f;
    private float _panX;
    private float _panY;
    private (Vec3 Min, Vec3 Max) _bounds;
    private Vec3 _center;
    private Point _strokeStart;
    private int _strokeId;
    private bool _editorStrokeActive;
    private readonly Dictionary<int, HashSet<int>> _selectedVertices = new();
    private readonly Dictionary<int, HashSet<int>> _selectedFaces = new();
    private readonly HashSet<int> _selectedSources = new();
    private NetEdgeTopology _edgeTopology = NetEdgeTopology.Empty;
    private readonly Dictionary<int, HashSet<int>> _partAdjacency = new();
    private readonly HashSet<int> _selectedEdges = new();
    private bool _frameDirty = true;
    private DateTime _dirtySinceUtc = DateTime.UtcNow;
    private int _hoverEdgeId = -1;
    private bool _edgeDragActive;
    private string _selectionDragTargetMode = "edge";
    private Point _edgeDragStart;
    private Point _edgeDragCurrent;
    private D3D11MaterialViewport? _d3d11Viewport;
    private System.Windows.Forms.Integration.ElementHost? _gpuHost;
    private WpfGpuMeshViewport? _gpuViewport;

    public RenderMetrics Metrics { get; } = new();
    public string RendererBackend => _d3d11Viewport is not null ? "d3d11_vortice_shader" : (_gpuViewport is not null ? "wpf_viewport3d_gpu" : "winforms_gdi_fallback");
    public int SelectedSubmeshIndex { get; set; }
    public bool ShowSolid { get; set; } = true;
    public bool ShowWire { get; set; } = false;
    public bool ShowXRay { get; set; } = false;
    public int MaterialDebugMode { get; set; }
    public string ActiveTool { get; set; } = "orbit";
    public Func<Dictionary<string, object?>>? ToolOptionsProvider { get; set; }
    public Action<string, Dictionary<string, object?>>? EditorEventRequested { get; set; }
    public Action<string>? StatusRequested { get; set; }
    public Action<int>? SubmeshSelectedRequested { get; set; }

    public bool ConsumeRenderRequest()
    {
        var activeInput = _editorStrokeActive || _rotating || _panning || _edgeDragActive;
        if (!_frameDirty && !activeInput)
        {
            return false;
        }
        _frameDirty = activeInput;
        return true;
    }

    private void RequestFrame()
    {
        if (!_frameDirty)
        {
            _dirtySinceUtc = DateTime.UtcNow;
        }
        _frameDirty = true;
    }

    private void RecordRenderedFrame(double frameMs, double presentMs, string deviceRemovedReason)
    {
        var dirtyToPresentMs = Math.Max(0.0, (DateTime.UtcNow - _dirtySinceUtc).TotalMilliseconds);
        Metrics.Record(frameMs, presentMs, dirtyToPresentMs, deviceRemovedReason);
        _dirtySinceUtc = DateTime.UtcNow;
    }

    public MeshViewport(ObjDocument document, NetMaterialSet materials, NetTextureSet textureSet)
    {
        _document = document;
        _materials = materials;
        _textureSet = textureSet;
        DoubleBuffered = true;
        BackColor = Color.FromArgb(23, 25, 29);
        ForeColor = Color.White;
        Dock = DockStyle.Fill;
        InitializeGpuViewport();
        FrameMesh();
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

    public Dictionary<string, object?> RendererStatusPayload()
    {
        return new Dictionary<string, object?>
        {
            ["backend"] = RendererBackend,
            ["gpu_backed"] = _d3d11Viewport is not null || _gpuViewport is not null,
            ["d3d11_hlsl"] = _d3d11Viewport is not null,
            ["d3d11_status"] = _d3d11Viewport?.LastError ?? string.Empty,
            ["device_removed_reason"] = _d3d11Viewport?.DeviceRemovedReason ?? string.Empty,
            ["material_debug_mode"] = MaterialDebugModeName(MaterialDebugMode),
            ["material_parity_contract"] = "base_normal_roughness_metallic_emissive_specular_final",
            ["capabilities"] = ActiveCapabilities(),
            ["material_slots"] = _materials.SlotCount,
            ["texture_references"] = _materials.TextureReferenceCount,
            ["resolved_texture_references"] = _materials.ResolvedTextureReferenceCount,
            ["existing_texture_files"] = _materials.ExistingTextureFileCount,
            ["decoded_texture_resources"] = _textureSet.DecodedCount,
            ["decodable_texture_files"] = _materials.DecodableTextureFileCount,
            ["dds_resources"] = _textureSet.DdsResourceCount,
            ["dds_decoded_resources"] = _textureSet.DdsDecodedCount,
            ["texture_load_failures"] = _textureSet.TextureLoadFailureCount,
            ["dds_decode"] = _textureSet.DdsDecodedCount > 0 ? "decoded_bc1_bc2_bc3_uncompressed32" : (_textureSet.DdsResourceCount > 0 ? "header_verified_not_sampled" : "not_present_or_unverified"),
            ["shader_model"] = _d3d11Viewport is not null ? "hlsl_vs5_ps5_per_pixel_materials" : (_gpuViewport is not null ? "wpf_materials" : "gdi_fallback"),
        };
    }

    public string[] ActiveCapabilities()
    {
        var capabilities = new List<string>
        {
            "solid",
            "wire",
            "visible_selection",
            "xray_selection",
            "local_edge_topology",
            "local_edge_picking",
            "local_edge_overlay",
            "stable_edge_descriptors",
            "topology_generation",
            "material_manifest",
            "decoded_texture_resources",
            "material_debug_channels",
            "strokes",
            "commands",
        };
        if (_d3d11Viewport is not null)
        {
            capabilities.Add("d3d11_vortice_hlsl_material_renderer");
            capabilities.Add("d3d11_overlay_vertices_edges_faces_parts_wire_xray");
        }
        else if (_gpuViewport is not null)
        {
            capabilities.Add("wpf_gpu_material_renderer");
        }
        else
        {
            capabilities.Add("winforms_gdi_fallback_renderer");
        }
        return capabilities.ToArray();
    }

    public Dictionary<string, object?> SelectionSnapshotPayload()
    {
        return new Dictionary<string, object?>
        {
            ["vertices_by_submesh"] = SelectionMapPayload(_selectedVertices),
            ["faces_by_submesh"] = SelectionMapPayload(_selectedFaces),
            ["edges"] = _selectedEdges.OrderBy(id => id).ToArray(),
            ["edge_descriptors"] = EdgeDescriptorPayloads(_selectedEdges),
            ["topology_generation"] = _edgeTopology.Generation,
            ["sources"] = _selectedSources.OrderBy(id => id).ToArray(),
            ["target_mode"] = CurrentTargetMode(),
            ["selection_depth_mode"] = ShowXRay ? "xray" : "visible",
        };
    }

    public bool TryHandleLocalCommand(string command, string targetMode)
    {
        var normalizedCommand = (command ?? string.Empty).Trim().ToLowerInvariant();
        var normalizedTarget = NormalizeSelectionTarget(targetMode);
        if (normalizedCommand is not ("clear_selection" or "select_all" or "invert" or "grow" or "shrink"))
        {
            return false;
        }
        if (normalizedCommand == "clear_selection")
        {
            ClearSelectionForTarget(normalizedTarget);
        }
        else if (normalizedCommand == "select_all")
        {
            SelectAllForTarget(normalizedTarget);
        }
        else if (normalizedCommand == "invert")
        {
            InvertSelectionForTarget(normalizedTarget);
        }
        else if (normalizedCommand == "grow")
        {
            GrowSelectionForTarget(normalizedTarget);
        }
        else if (normalizedCommand == "shrink")
        {
            ShrinkSelectionForTarget(normalizedTarget);
        }
        StatusRequested?.Invoke($"Selection {normalizedCommand} applied locally for {normalizedTarget}; selected={SelectionCountForTarget(normalizedTarget)}.");
        UpdateGpuViewport();
        Invalidate();
        return true;
    }

    private static Dictionary<string, int[]> SelectionMapPayload(Dictionary<int, HashSet<int>> selection)
    {
        return selection
            .OrderBy(pair => pair.Key)
            .ToDictionary(pair => pair.Key.ToString(CultureInfo.InvariantCulture), pair => pair.Value.OrderBy(value => value).ToArray());
    }

    private Dictionary<string, object?>[] EdgeDescriptorPayloads(IEnumerable<int> edgeIds)
    {
        return edgeIds
            .Select(edgeId => _edgeTopology.EdgeById(edgeId))
            .Where(edge => edge is not null)
            .Select(edge => edge!.ToDescriptorPayload(_edgeTopology.Generation))
            .ToArray();
    }

    private static string NormalizeSelectionTarget(string targetMode)
    {
        var normalized = (targetMode ?? string.Empty).Trim().ToLowerInvariant();
        return normalized == "source" ? "part" : normalized;
    }

    private int SelectionCountForTarget(string targetMode)
    {
        return NormalizeSelectionTarget(targetMode) switch
        {
            "vertex" => _selectedVertices.Values.Sum(values => values.Count),
            "face" => _selectedFaces.Values.Sum(values => values.Count),
            "edge" => _selectedEdges.Count,
            "part" => _selectedSources.Count,
            _ => 0,
        };
    }

    private void ClearSelectionForTarget(string targetMode)
    {
        if (targetMode == "vertex")
        {
            _selectedVertices.Clear();
        }
        else if (targetMode == "face")
        {
            _selectedFaces.Clear();
        }
        else if (targetMode == "edge")
        {
            _selectedEdges.Clear();
            _hoverEdgeId = -1;
        }
        else if (targetMode == "part")
        {
            _selectedSources.Clear();
        }
    }

    private void SelectAllForTarget(string targetMode)
    {
        ClearSelectionForTarget(targetMode);
        if (targetMode == "vertex")
        {
            for (var index = 0; index < _document.Submeshes.Count; index++)
            {
                _selectedVertices[index] = Enumerable.Range(0, _document.Submeshes[index].Vertices.Count).ToHashSet();
            }
        }
        else if (targetMode == "face")
        {
            for (var index = 0; index < _document.Submeshes.Count; index++)
            {
                _selectedFaces[index] = Enumerable.Range(0, _document.Submeshes[index].Faces.Count).ToHashSet();
            }
        }
        else if (targetMode == "edge")
        {
            foreach (var edge in _edgeTopology.Edges)
            {
                _selectedEdges.Add(edge.Id);
            }
        }
        else if (targetMode == "part")
        {
            for (var index = 0; index < _document.Submeshes.Count; index++)
            {
                _selectedSources.Add(index);
            }
        }
    }

    private void InvertSelectionForTarget(string targetMode)
    {
        if (targetMode == "vertex")
        {
            for (var index = 0; index < _document.Submeshes.Count; index++)
            {
                var selected = _selectedVertices.TryGetValue(index, out var current) ? current : new HashSet<int>();
                var inverted = Enumerable.Range(0, _document.Submeshes[index].Vertices.Count).Where(item => !selected.Contains(item)).ToHashSet();
                if (inverted.Count > 0)
                {
                    _selectedVertices[index] = inverted;
                }
                else
                {
                    _selectedVertices.Remove(index);
                }
            }
        }
        else if (targetMode == "face")
        {
            for (var index = 0; index < _document.Submeshes.Count; index++)
            {
                var selected = _selectedFaces.TryGetValue(index, out var current) ? current : new HashSet<int>();
                var inverted = Enumerable.Range(0, _document.Submeshes[index].Faces.Count).Where(item => !selected.Contains(item)).ToHashSet();
                if (inverted.Count > 0)
                {
                    _selectedFaces[index] = inverted;
                }
                else
                {
                    _selectedFaces.Remove(index);
                }
            }
        }
        else if (targetMode == "edge")
        {
            var selected = _selectedEdges.ToHashSet();
            _selectedEdges.Clear();
            foreach (var edge in _edgeTopology.Edges)
            {
                if (!selected.Contains(edge.Id))
                {
                    _selectedEdges.Add(edge.Id);
                }
            }
        }
        else if (targetMode == "part")
        {
            var selected = _selectedSources.ToHashSet();
            _selectedSources.Clear();
            for (var index = 0; index < _document.Submeshes.Count; index++)
            {
                if (!selected.Contains(index))
                {
                    _selectedSources.Add(index);
                }
            }
        }
    }

    private void GrowSelectionForTarget(string targetMode)
    {
        if (targetMode == "vertex")
        {
            var grown = CopySelectionMap(_selectedVertices);
            foreach (var edge in _edgeTopology.Edges)
            {
                if (!_selectedVertices.TryGetValue(edge.SubmeshIndex, out var selected))
                {
                    continue;
                }
                if (!grown.TryGetValue(edge.SubmeshIndex, out var target))
                {
                    target = new HashSet<int>();
                    grown[edge.SubmeshIndex] = target;
                }
                if (selected.Contains(edge.VertexA)) target.Add(edge.VertexB);
                if (selected.Contains(edge.VertexB)) target.Add(edge.VertexA);
            }
            ReplaceSelectionMap(_selectedVertices, grown);
        }
        else if (targetMode == "face")
        {
            var grown = CopySelectionMap(_selectedFaces);
            foreach (var edge in _edgeTopology.Edges)
            {
                if (!_selectedFaces.TryGetValue(edge.SubmeshIndex, out var selected) || !edge.AdjacentFaces.Any(selected.Contains))
                {
                    continue;
                }
                if (!grown.TryGetValue(edge.SubmeshIndex, out var target))
                {
                    target = new HashSet<int>();
                    grown[edge.SubmeshIndex] = target;
                }
                foreach (var face in edge.AdjacentFaces)
                {
                    target.Add(face);
                }
            }
            ReplaceSelectionMap(_selectedFaces, grown);
        }
        else if (targetMode == "edge")
        {
            var selected = _selectedEdges.ToHashSet();
            foreach (var edge in _edgeTopology.Edges)
            {
                if (selected.Contains(edge.Id))
                {
                    continue;
                }
                if (_edgeTopology.Edges.Any(other => selected.Contains(other.Id) && other.SubmeshIndex == edge.SubmeshIndex && (other.VertexA == edge.VertexA || other.VertexA == edge.VertexB || other.VertexB == edge.VertexA || other.VertexB == edge.VertexB)))
                {
                    _selectedEdges.Add(edge.Id);
                }
            }
        }
        else if (targetMode == "part")
        {
            var selected = _selectedSources.Count > 0 ? _selectedSources.ToHashSet() : new HashSet<int> { SelectedSubmeshIndex };
            foreach (var part in selected)
            {
                if (part >= 0 && part < _document.Submeshes.Count)
                {
                    _selectedSources.Add(part);
                    foreach (var neighbor in PartNeighbors(part))
                    {
                        _selectedSources.Add(neighbor);
                    }
                }
            }
        }
    }

    private void ShrinkSelectionForTarget(string targetMode)
    {
        if (targetMode == "vertex")
        {
            var shrunk = new Dictionary<int, HashSet<int>>();
            foreach (var pair in _selectedVertices)
            {
                var keep = new HashSet<int>();
                foreach (var vertex in pair.Value)
                {
                    var neighbors = VertexNeighbors(pair.Key, vertex).ToArray();
                    if (neighbors.Length > 0 && neighbors.All(pair.Value.Contains))
                    {
                        keep.Add(vertex);
                    }
                }
                if (keep.Count > 0)
                {
                    shrunk[pair.Key] = keep;
                }
            }
            ReplaceSelectionMap(_selectedVertices, shrunk);
        }
        else if (targetMode == "face")
        {
            var shrunk = new Dictionary<int, HashSet<int>>();
            foreach (var pair in _selectedFaces)
            {
                var keep = new HashSet<int>();
                foreach (var face in pair.Value)
                {
                    var neighbors = FaceNeighbors(pair.Key, face).ToArray();
                    if (neighbors.Length > 0 && neighbors.All(pair.Value.Contains))
                    {
                        keep.Add(face);
                    }
                }
                if (keep.Count > 0)
                {
                    shrunk[pair.Key] = keep;
                }
            }
            ReplaceSelectionMap(_selectedFaces, shrunk);
        }
        else if (targetMode == "edge")
        {
            var keep = new HashSet<int>();
            foreach (var edgeId in _selectedEdges)
            {
                var neighbors = EdgeNeighbors(edgeId).ToArray();
                if (neighbors.Length > 0 && neighbors.All(_selectedEdges.Contains))
                {
                    keep.Add(edgeId);
                }
            }
            _selectedEdges.Clear();
            foreach (var edgeId in keep)
            {
                _selectedEdges.Add(edgeId);
            }
        }
        else if (targetMode == "part")
        {
            var keep = new HashSet<int>();
            foreach (var part in _selectedSources)
            {
                var neighbors = PartNeighbors(part).ToArray();
                if (neighbors.Length > 0 && neighbors.All(_selectedSources.Contains))
                {
                    keep.Add(part);
                }
            }
            _selectedSources.Clear();
            foreach (var part in keep)
            {
                _selectedSources.Add(part);
            }
        }
    }

    private IEnumerable<int> VertexNeighbors(int submeshIndex, int vertexIndex)
    {
        foreach (var edge in _edgeTopology.Edges)
        {
            if (edge.SubmeshIndex != submeshIndex)
            {
                continue;
            }
            if (edge.VertexA == vertexIndex)
            {
                yield return edge.VertexB;
            }
            else if (edge.VertexB == vertexIndex)
            {
                yield return edge.VertexA;
            }
        }
    }

    private IEnumerable<int> FaceNeighbors(int submeshIndex, int faceIndex)
    {
        foreach (var edge in _edgeTopology.Edges)
        {
            if (edge.SubmeshIndex == submeshIndex && edge.AdjacentFaces.Contains(faceIndex))
            {
                foreach (var neighbor in edge.AdjacentFaces)
                {
                    if (neighbor != faceIndex)
                    {
                        yield return neighbor;
                    }
                }
            }
        }
    }

    private IEnumerable<int> EdgeNeighbors(int edgeId)
    {
        var edge = _edgeTopology.EdgeById(edgeId);
        if (edge is null)
        {
            yield break;
        }
        foreach (var other in _edgeTopology.Edges)
        {
            if (other.Id != edge.Id && other.SubmeshIndex == edge.SubmeshIndex && (other.VertexA == edge.VertexA || other.VertexA == edge.VertexB || other.VertexB == edge.VertexA || other.VertexB == edge.VertexB))
            {
                yield return other.Id;
            }
        }
    }

    private IEnumerable<int> PartNeighbors(int submeshIndex)
    {
        return _partAdjacency.TryGetValue(submeshIndex, out var neighbors)
            ? neighbors
            : Array.Empty<int>();
    }

    private static Dictionary<int, HashSet<int>> CopySelectionMap(Dictionary<int, HashSet<int>> source)
    {
        return source.ToDictionary(pair => pair.Key, pair => new HashSet<int>(pair.Value));
    }

    private void InitializeGpuViewport()
    {
        if (TryStartD3D11Viewport())
        {
            return;
        }
        _ = TryStartWpfViewport();
    }

    private bool TryStartD3D11Viewport()
    {
        D3D11MaterialViewport? viewport = null;
        try
        {
            viewport = new D3D11MaterialViewport(_document, _materials, _textureSet) { Dock = DockStyle.Fill };
            viewport.MouseDown += (_, e) => OnMouseDown(e);
            viewport.MouseUp += (_, e) => OnMouseUp(e);
            viewport.MouseMove += (_, e) => OnMouseMove(e);
            viewport.MouseWheel += (_, e) => OnMouseWheel(e);
            viewport.BackendUnavailable += HandleD3D11BackendUnavailable;
            viewport.FrameRendered += RecordRenderedFrame;
            if (!viewport.TryInitialize(out var error))
            {
                viewport.Dispose();
                StatusRequested?.Invoke($"D3D11/Vortice material viewport unavailable; trying WPF fallback: {error}");
                return false;
            }
            _d3d11Viewport = viewport;
            Controls.Add(_d3d11Viewport);
            _d3d11Viewport.BringToFront();
            StatusRequested?.Invoke("D3D11/Vortice HLSL material viewport initialized.");
            return true;
        }
        catch (Exception ex)
        {
            viewport?.Dispose();
            _d3d11Viewport = null;
            StatusRequested?.Invoke($"D3D11/Vortice material viewport unavailable; trying WPF fallback: {ex.Message}");
            return false;
        }
    }

    private bool TryStartWpfViewport()
    {
        try
        {
            _gpuViewport = new WpfGpuMeshViewport(_document, _materials, _textureSet);
            _gpuHost = new System.Windows.Forms.Integration.ElementHost
            {
                Dock = DockStyle.Fill,
                Child = _gpuViewport.Root,
                BackColor = BackColor,
            };
            _gpuHost.MouseDown += (_, e) => OnMouseDown(e);
            _gpuHost.MouseUp += (_, e) => OnMouseUp(e);
            _gpuHost.MouseMove += (_, e) => OnMouseMove(e);
            _gpuHost.MouseWheel += (_, e) => OnMouseWheel(e);
            Controls.Add(_gpuHost);
            _gpuHost.BringToFront();
            StatusRequested?.Invoke("WPF GPU material viewport initialized.");
            return true;
        }
        catch (Exception ex)
        {
            _gpuViewport?.Dispose();
            _gpuHost?.Dispose();
            _gpuViewport = null;
            _gpuHost = null;
            StatusRequested?.Invoke($"WPF GPU material viewport unavailable; using software fallback: {ex.Message}");
            return false;
        }
    }

    private void HandleD3D11BackendUnavailable(string message)
    {
        var failed = _d3d11Viewport;
        if (failed is null)
        {
            return;
        }
        failed.BackendUnavailable -= HandleD3D11BackendUnavailable;
        failed.FrameRendered -= RecordRenderedFrame;
        Controls.Remove(failed);
        _d3d11Viewport = null;
        failed.Dispose();
        StatusRequested?.Invoke($"{message} Falling back to WPF/GDI renderer.");
        if (_gpuViewport is null && _gpuHost is null)
        {
            _ = TryStartWpfViewport();
        }
        UpdateGpuViewport();
        Invalidate();
    }

    public void RefreshBounds()
    {
        _bounds = _document.Bounds();
        _center = new Vec3(
            (_bounds.Min.X + _bounds.Max.X) * 0.5f,
            (_bounds.Min.Y + _bounds.Max.Y) * 0.5f,
            (_bounds.Min.Z + _bounds.Max.Z) * 0.5f);
        RebuildEdgeTopology();
        RebuildPartAdjacency();
        if (_d3d11Viewport is not null)
        {
            _d3d11Viewport.RefreshGeometry();
        }
        _gpuViewport?.RefreshGeometry();
        UpdateGpuViewport();
    }

    private void UpdateGpuViewport()
    {
        RequestFrame();
        if (_d3d11Viewport is not null)
        {
            _d3d11Viewport.MaterialDebugMode = MaterialDebugMode;
            _d3d11Viewport.UpdateCamera(_center, _bounds, _yaw, _pitch, _zoom, _panX, _panY);
            _d3d11Viewport.UpdateOverlay(_edgeTopology, _selectedEdges, _hoverEdgeId, _edgeDragActive ? EdgeDragRectangle() : null, _selectedVertices, _selectedFaces, _selectedSources, SelectedSubmeshIndex, ShowWire, ShowXRay);
            return;
        }
        var viewport = _gpuViewport;
        if (viewport is null)
        {
            return;
        }
        viewport.UpdateCamera(_center, _bounds, _yaw, _pitch, _zoom, _panX, _panY, Math.Max(1, Width), Math.Max(1, Height));
        viewport.UpdateOverlay(
            _edgeTopology,
            _selectedEdges,
            _hoverEdgeId,
            _edgeDragActive ? EdgeDragRectangle() : null,
            _selectedVertices,
            _selectedFaces,
            _selectedSources,
            SelectedSubmeshIndex,
            ShowWire,
            ShowXRay,
            vertex => Project(vertex, MathF.Cos(_yaw), MathF.Sin(_yaw), MathF.Cos(_pitch), MathF.Sin(_pitch)));
    }

    private void RebuildEdgeTopology()
    {
        var selectedKeys = _selectedEdges
            .Select(edgeId => _edgeTopology.EdgeById(edgeId)?.StableKey)
            .Where(key => !string.IsNullOrWhiteSpace(key))
            .ToArray();
        var hoverKey = _edgeTopology.EdgeById(_hoverEdgeId)?.StableKey ?? string.Empty;
        _edgeTopology = NetEdgeTopology.Build(_document, _edgeTopology.Generation + 1);
        _selectedEdges.Clear();
        foreach (var key in selectedKeys)
        {
            var edge = _edgeTopology.EdgeByStableKey(key!);
            if (edge is not null)
            {
                _selectedEdges.Add(edge.Id);
            }
        }
        _hoverEdgeId = _edgeTopology.EdgeByStableKey(hoverKey)?.Id ?? -1;
    }

    private void RebuildPartAdjacency()
    {
        _partAdjacency.Clear();
        for (var index = 0; index < _document.Submeshes.Count; index++)
        {
            _partAdjacency[index] = new HashSet<int>();
        }
        var size = Math.Max(_bounds.Max.X - _bounds.Min.X, Math.Max(_bounds.Max.Y - _bounds.Min.Y, _bounds.Max.Z - _bounds.Min.Z));
        var tolerance = Math.Max(0.0001f, size * 0.001f);
        for (var left = 0; left < _document.Submeshes.Count; left++)
        {
            for (var right = left + 1; right < _document.Submeshes.Count; right++)
            {
                if (SubmeshesAdjacent(left, right, tolerance))
                {
                    _partAdjacency[left].Add(right);
                    _partAdjacency[right].Add(left);
                }
            }
        }
    }

    private bool SubmeshesAdjacent(int leftIndex, int rightIndex, float tolerance)
    {
        var left = _document.Submeshes[leftIndex];
        var right = _document.Submeshes[rightIndex];
        if (left.Vertices.Count == 0 || right.Vertices.Count == 0)
        {
            return false;
        }
        var leftBounds = SubmeshBounds(left);
        var rightBounds = SubmeshBounds(right);
        if (!BoundsTouchOrOverlap(leftBounds, rightBounds, tolerance))
        {
            return false;
        }
        var toleranceSquared = tolerance * tolerance;
        foreach (var a in left.Vertices)
        {
            foreach (var b in right.Vertices)
            {
                var dx = a.X - b.X;
                var dy = a.Y - b.Y;
                var dz = a.Z - b.Z;
                if ((dx * dx) + (dy * dy) + (dz * dz) <= toleranceSquared)
                {
                    return true;
                }
            }
        }
        return true;
    }

    private static (Vec3 Min, Vec3 Max) SubmeshBounds(ObjSubmesh submesh)
    {
        if (submesh.Vertices.Count == 0)
        {
            return (new Vec3(0, 0, 0), new Vec3(0, 0, 0));
        }
        return (
            new Vec3(submesh.Vertices.Min(vertex => vertex.X), submesh.Vertices.Min(vertex => vertex.Y), submesh.Vertices.Min(vertex => vertex.Z)),
            new Vec3(submesh.Vertices.Max(vertex => vertex.X), submesh.Vertices.Max(vertex => vertex.Y), submesh.Vertices.Max(vertex => vertex.Z)));
    }

    private static bool BoundsTouchOrOverlap((Vec3 Min, Vec3 Max) left, (Vec3 Min, Vec3 Max) right, float tolerance)
    {
        return left.Min.X <= right.Max.X + tolerance && left.Max.X + tolerance >= right.Min.X
            && left.Min.Y <= right.Max.Y + tolerance && left.Max.Y + tolerance >= right.Min.Y
            && left.Min.Z <= right.Max.Z + tolerance && left.Max.Z + tolerance >= right.Min.Z;
    }

    public void FrameMesh()
    {
        RefreshBounds();
        var size = Math.Max(_bounds.Max.X - _bounds.Min.X, Math.Max(_bounds.Max.Y - _bounds.Min.Y, _bounds.Max.Z - _bounds.Min.Z));
        _zoom = size > 0.0001f ? 380.0f / size : 220.0f;
        _panX = 0;
        _panY = 0;
        UpdateGpuViewport();
        Invalidate();
    }

    private static void ReplaceSelectionMap(Dictionary<int, HashSet<int>> target, Dictionary<int, HashSet<int>> source)
    {
        target.Clear();
        foreach (var pair in source)
        {
            target[pair.Key] = new HashSet<int>(pair.Value);
        }
    }

    public void UpdateSelection(Dictionary<int, HashSet<int>> vertices, Dictionary<int, HashSet<int>> faces, HashSet<int> sources)
    {
        ReplaceSelectionMap(_selectedVertices, vertices);
        ReplaceSelectionMap(_selectedFaces, faces);
        _selectedSources.Clear();
        foreach (var source in sources)
        {
            _selectedSources.Add(source);
        }
        UpdateGpuViewport();
    }

    private void AddSelectedVertices(int submeshIndex, HashSet<int> result)
    {
        var submesh = _document.Submeshes[submeshIndex];
        if (!_selectedVertices.TryGetValue(submeshIndex, out var selectedVertices))
        {
            return;
        }
        foreach (var vertexIndex in selectedVertices)
        {
            if (vertexIndex >= 0 && vertexIndex < submesh.Vertices.Count)
            {
                result.Add(vertexIndex);
            }
        }
    }

    private void AddSelectedFaceVertices(int submeshIndex, HashSet<int> result)
    {
        var submesh = _document.Submeshes[submeshIndex];
        if (!_selectedFaces.TryGetValue(submeshIndex, out var selectedFaces))
        {
            return;
        }
        foreach (var faceIndex in selectedFaces)
        {
            if (faceIndex < 0 || faceIndex >= submesh.Faces.Count)
            {
                continue;
            }
            foreach (var corner in submesh.Faces[faceIndex].Corners)
            {
                if (corner.VertexIndex >= 0 && corner.VertexIndex < submesh.Vertices.Count)
                {
                    result.Add(corner.VertexIndex);
                }
            }
        }
    }

    private HashSet<int> SelectionVerticesForSubmesh(int submeshIndex)
    {
        var result = new HashSet<int>();
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return result;
        }
        AddSelectedVertices(submeshIndex, result);
        AddSelectedFaceVertices(submeshIndex, result);
        return result;
    }

    public int[] EditableVertexIndicesForSubmesh(int submeshIndex)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return Array.Empty<int>();
        }
        return SelectionVerticesForSubmesh(submeshIndex).OrderBy(index => index).ToArray();
    }

    public void SetCameraPreset(string preset)
    {
        var normalized = (preset ?? string.Empty).Trim().ToLowerInvariant();
        _panX = 0;
        _panY = 0;
        if (normalized == "front")
        {
            _yaw = 0.0f;
            _pitch = 0.0f;
        }
        else if (normalized == "back")
        {
            _yaw = MathF.PI;
            _pitch = 0.0f;
        }
        else if (normalized == "left")
        {
            _yaw = -MathF.PI * 0.5f;
            _pitch = 0.0f;
        }
        else if (normalized == "right")
        {
            _yaw = MathF.PI * 0.5f;
            _pitch = 0.0f;
        }
        else if (normalized == "top")
        {
            _yaw = 0.0f;
            _pitch = 1.35f;
        }
        else if (normalized == "bottom")
        {
            _yaw = 0.0f;
            _pitch = -1.35f;
        }
        UpdateGpuViewport();
        Invalidate();
    }

    public void RotateYawDegrees(float degrees)
    {
        _yaw += degrees * MathF.PI / 180.0f;
        UpdateGpuViewport();
        Invalidate();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _d3d11Viewport?.Dispose();
            _gpuViewport?.Dispose();
            _gpuHost?.Dispose();
        }
        base.Dispose(disposing);
    }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        UpdateGpuViewport();
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        _lastMouse = e.Location;
        if (e.Button == MouseButtons.Left && !string.Equals(ActiveTool, "orbit", StringComparison.OrdinalIgnoreCase))
        {
            if (string.Equals(ActiveTool, "select", StringComparison.OrdinalIgnoreCase))
            {
                var targetMode = CurrentTargetMode();
                if (string.Equals(targetMode, "edge", StringComparison.OrdinalIgnoreCase))
                {
                    BeginEdgeDrag(e.Location);
                }
                else if (string.Equals(targetMode, "vertex", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(targetMode, "face", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(targetMode, "part", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(targetMode, "source", StringComparison.OrdinalIgnoreCase))
                {
                    BeginSelectionDrag(e.Location, targetMode);
                }
                else
                {
                    EditorEventRequested?.Invoke("select_request", PointerPayload(e.Location, null, false));
                }
            }
            else
            {
                _editorStrokeActive = true;
                _strokeStart = e.Location;
                _strokeId++;
                EditorEventRequested?.Invoke("stroke_begin", PointerPayload(e.Location, e.Location, true));
            }
            base.OnMouseDown(e);
            return;
        }
        _rotating = e.Button == MouseButtons.Left;
        _panning = e.Button == MouseButtons.Right || (ModifierKeys & Keys.Shift) == Keys.Shift;
        base.OnMouseDown(e);
    }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        if (_edgeDragActive)
        {
            FinishEdgeDrag(e.Location);
        }
        if (_editorStrokeActive)
        {
            EditorEventRequested?.Invoke("stroke_end", PointerPayload(e.Location, _strokeStart, true));
            _editorStrokeActive = false;
        }
        _rotating = false;
        _panning = false;
        base.OnMouseUp(e);
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        var dx = e.X - _lastMouse.X;
        var dy = e.Y - _lastMouse.Y;
        _lastMouse = e.Location;
        if (_edgeDragActive)
        {
            _edgeDragCurrent = e.Location;
            UpdateGpuViewport();
            Invalidate();
        }
        if (!_edgeDragActive
            && !_editorStrokeActive
            && !_rotating
            && !_panning
            && string.Equals(ActiveTool, "select", StringComparison.OrdinalIgnoreCase)
            && string.Equals(CurrentTargetMode(), "edge", StringComparison.OrdinalIgnoreCase))
        {
            UpdateHoverEdge(e.Location);
        }
        if (_editorStrokeActive)
        {
            EditorEventRequested?.Invoke("stroke_update", PointerPayload(e.Location, _strokeStart, true));
            Invalidate();
        }
        else if (_rotating)
        {
            _yaw += dx * 0.01f;
            _pitch = Math.Clamp(_pitch + dy * 0.01f, -1.45f, 1.45f);
            Invalidate();
        }
        else if (_panning)
        {
            _panX += dx;
            _panY += dy;
            Invalidate();
        }
        UpdateGpuViewport();
        base.OnMouseMove(e);
    }

    protected override void OnMouseWheel(MouseEventArgs e)
    {
        _zoom *= e.Delta > 0 ? 1.1f : 0.9f;
        _zoom = Math.Clamp(_zoom, 10.0f, 5000.0f);
        UpdateGpuViewport();
        Invalidate();
        base.OnMouseWheel(e);
    }

    private Dictionary<string, object?> PointerPayload(Point point, Point? start, bool stroke)
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        var radius = NumberOption(options, "radius", 24.0);
        var screenPayload = ScreenPayload(point, radius);
        var payload = new Dictionary<string, object?>(options)
        {
            ["tool"] = ActiveTool,
            ["screen_brush"] = screenPayload
        };
        if (stroke)
        {
            var origin = start ?? point;
            payload["stroke_id"] = _strokeId.ToString(CultureInfo.InvariantCulture);
            payload["screen_drag"] = ScreenDragPayload(origin, point);
        }
        return payload;
    }

    private Dictionary<string, object?> ScreenPayload(Point point, double radius)
    {
        return new Dictionary<string, object?>
        {
            ["x"] = point.X,
            ["y"] = point.Y,
            ["radius"] = radius,
            ["radius_pixels"] = radius,
            ["viewport_width"] = Math.Max(1, Width),
            ["viewport_height"] = Math.Max(1, Height),
            ["world_view_projection"] = WorldViewProjection()
        };
    }

    private Dictionary<string, object?> ScreenDragPayload(Point start, Point end)
    {
        return new Dictionary<string, object?>
        {
            ["start_x"] = start.X,
            ["start_y"] = start.Y,
            ["end_x"] = end.X,
            ["end_y"] = end.Y,
            ["viewport_width"] = Math.Max(1, Width),
            ["viewport_height"] = Math.Max(1, Height),
            ["world_view_projection"] = WorldViewProjection()
        };
    }

    private double[] WorldViewProjection()
    {
        var width = Math.Max(1.0, Width);
        var height = Math.Max(1.0, Height);
        var size = Math.Max(_bounds.Max.X - _bounds.Min.X, Math.Max(_bounds.Max.Y - _bounds.Min.Y, _bounds.Max.Z - _bounds.Min.Z));
        var sx = 2.0 * _zoom / width;
        var sy = 2.0 * _zoom / height;
        var sz = 1.0 / Math.Max(size * 4.0, 0.0001);
        var cosYaw = Math.Cos(_yaw);
        var sinYaw = Math.Sin(_yaw);
        var cosPitch = Math.Cos(_pitch);
        var sinPitch = Math.Sin(_pitch);
        var m = new double[16];
        m[0] = sx * cosYaw;
        m[8] = -sx * sinYaw;
        m[12] = sx * (-_center.X * cosYaw + _center.Z * sinYaw) + (2.0 * _panX / width);
        m[1] = -sy * sinYaw * sinPitch;
        m[5] = sy * cosPitch;
        m[9] = -sy * cosYaw * sinPitch;
        m[13] = sy * (-_center.Y * cosPitch + _center.X * sinYaw * sinPitch + _center.Z * cosYaw * sinPitch) - (2.0 * _panY / height);
        m[2] = -sz * sinYaw * cosPitch;
        m[6] = -sz * sinPitch;
        m[10] = -sz * cosYaw * cosPitch;
        m[14] = 0.5 + sz * (_center.X * sinYaw * cosPitch + _center.Y * sinPitch + _center.Z * cosYaw * cosPitch);
        m[15] = 1.0;
        return m;
    }

    private void BeginSelectionDrag(Point point, string mode)
    {
        _edgeDragActive = true;
        _selectionDragTargetMode = (mode ?? "edge").Trim().ToLowerInvariant();
        _edgeDragStart = point;
        _edgeDragCurrent = point;
        _hoverEdgeId = _selectionDragTargetMode == "edge" ? PickEdgeAt(point) : -1;
        UpdateGpuViewport();
        Invalidate();
    }

    private void SelectVertexAt(Point point)
    {
        var hit = PickVertexAt(point);
        if (hit is null)
        {
            if (string.Equals(CurrentSelectionOperation(), "replace", StringComparison.OrdinalIgnoreCase))
            {
                _selectedVertices.Clear();
            }
            StatusRequested?.Invoke($"Vertex mode: selected={_selectedVertices.Values.Sum(vertices => vertices.Count)} hit=0 xray={(ShowXRay ? "on" : "off")}");
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        ApplySelectionMapOperation(_selectedVertices, hit.Value.SubmeshIndex, hit.Value.ItemIndex, CurrentSelectionOperation());
        SelectedSubmeshIndex = hit.Value.SubmeshIndex;
        SubmeshSelectedRequested?.Invoke(hit.Value.SubmeshIndex);
        StatusRequested?.Invoke($"Vertex mode: selected={_selectedVertices.Values.Sum(vertices => vertices.Count)} hit=1 xray={(ShowXRay ? "on" : "off")}");
        UpdateGpuViewport();
        Invalidate();
    }

    private void SelectFaceAt(Point point)
    {
        var hit = PickFaceAt(point);
        if (hit is null)
        {
            if (string.Equals(CurrentSelectionOperation(), "replace", StringComparison.OrdinalIgnoreCase))
            {
                _selectedFaces.Clear();
            }
            StatusRequested?.Invoke($"Face mode: selected={_selectedFaces.Values.Sum(faces => faces.Count)} hit=0 xray={(ShowXRay ? "on" : "off")}");
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        ApplySelectionMapOperation(_selectedFaces, hit.Value.SubmeshIndex, hit.Value.ItemIndex, CurrentSelectionOperation());
        SelectedSubmeshIndex = hit.Value.SubmeshIndex;
        SubmeshSelectedRequested?.Invoke(hit.Value.SubmeshIndex);
        StatusRequested?.Invoke($"Face mode: selected={_selectedFaces.Values.Sum(faces => faces.Count)} hit=1 xray={(ShowXRay ? "on" : "off")}");
        UpdateGpuViewport();
        Invalidate();
    }

    private void SelectPartAt(Point point)
    {
        var submeshIndex = PickPartAt(point);
        if (submeshIndex < 0)
        {
            if (string.Equals(CurrentSelectionOperation(), "replace", StringComparison.OrdinalIgnoreCase))
            {
                _selectedSources.Clear();
            }
            StatusRequested?.Invoke($"Part mode: selected={_selectedSources.Count} hit=0 xray={(ShowXRay ? "on" : "off")}");
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        ApplyPartSelectionOperation(new[] { submeshIndex }, CurrentSelectionOperation());
        SelectedSubmeshIndex = submeshIndex;
        SubmeshSelectedRequested?.Invoke(submeshIndex);
        StatusRequested?.Invoke($"Part mode: selected={_selectedSources.Count} hit=1 xray={(ShowXRay ? "on" : "off")}");
        UpdateGpuViewport();
        Invalidate();
    }

    private int PickPartAt(Point point)
    {
        var face = PickFaceAt(point);
        return face?.SubmeshIndex ?? -1;
    }

    private void ApplyPartSelectionOperation(IEnumerable<int> sourceIndices, string operation)
    {
        var ids = sourceIndices.Where(index => index >= 0 && index < _document.Submeshes.Count).Distinct().ToArray();
        var normalized = (operation ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized == "replace")
        {
            _selectedSources.Clear();
        }
        foreach (var id in ids)
        {
            if (normalized == "subtract")
            {
                _selectedSources.Remove(id);
            }
            else if (normalized == "toggle")
            {
                if (!_selectedSources.Remove(id))
                {
                    _selectedSources.Add(id);
                }
            }
            else
            {
                _selectedSources.Add(id);
            }
        }
        if (_selectedSources.Count > 0)
        {
            var first = _selectedSources.OrderBy(index => index).First();
            SelectedSubmeshIndex = first;
            SubmeshSelectedRequested?.Invoke(first);
        }
    }

    private void ApplySelectionMapOperation(Dictionary<int, HashSet<int>> target, int submeshIndex, int itemIndex, string operation)
    {
        if (submeshIndex < 0 || itemIndex < 0)
        {
            return;
        }
        var normalized = (operation ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized == "replace")
        {
            target.Clear();
        }
        if (!target.TryGetValue(submeshIndex, out var set))
        {
            set = new HashSet<int>();
            target[submeshIndex] = set;
        }
        if (normalized == "subtract")
        {
            set.Remove(itemIndex);
        }
        else if (normalized == "toggle")
        {
            if (!set.Remove(itemIndex))
            {
                set.Add(itemIndex);
            }
        }
        else
        {
            set.Add(itemIndex);
        }
        if (set.Count == 0)
        {
            target.Remove(submeshIndex);
        }
    }

    private void ApplySelectionMapOperation(Dictionary<int, HashSet<int>> target, IEnumerable<(int SubmeshIndex, int ItemIndex)> hits, string operation)
    {
        var items = hits.Where(hit => hit.SubmeshIndex >= 0 && hit.ItemIndex >= 0).Distinct().ToArray();
        var normalized = (operation ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized == "replace")
        {
            target.Clear();
        }
        foreach (var item in items)
        {
            if (!target.TryGetValue(item.SubmeshIndex, out var set))
            {
                set = new HashSet<int>();
                target[item.SubmeshIndex] = set;
            }
            if (normalized == "subtract")
            {
                set.Remove(item.ItemIndex);
            }
            else if (normalized == "toggle")
            {
                if (!set.Remove(item.ItemIndex))
                {
                    set.Add(item.ItemIndex);
                }
            }
            else
            {
                set.Add(item.ItemIndex);
            }
            if (set.Count == 0)
            {
                target.Remove(item.SubmeshIndex);
            }
        }
    }

    private (int SubmeshIndex, int ItemIndex)? PickVertexAt(Point point)
    {
        var cosYaw = MathF.Cos(_yaw);
        var sinYaw = MathF.Sin(_yaw);
        var cosPitch = MathF.Cos(_pitch);
        var sinPitch = MathF.Sin(_pitch);
        var bestDistance = 8.0;
        (int SubmeshIndex, int ItemIndex)? best = null;
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            var submesh = _document.Submeshes[submeshIndex];
            for (var vertexIndex = 0; vertexIndex < submesh.Vertices.Count; vertexIndex++)
            {
                if (!ShowXRay && !IsVertexFrontFacing(submeshIndex, vertexIndex, cosYaw, sinYaw, cosPitch, sinPitch))
                {
                    continue;
                }
                var projected = Project(submesh.Vertices[vertexIndex], cosYaw, sinYaw, cosPitch, sinPitch);
                var dx = point.X - projected.X;
                var dy = point.Y - projected.Y;
                var distance = Math.Sqrt((dx * dx) + (dy * dy));
                if (distance < bestDistance)
                {
                    bestDistance = distance;
                    best = (submeshIndex, vertexIndex);
                }
            }
        }
        return best;
    }

    private (int SubmeshIndex, int ItemIndex)? PickFaceAt(Point point)
    {
        var cosYaw = MathF.Cos(_yaw);
        var sinYaw = MathF.Sin(_yaw);
        var cosPitch = MathF.Cos(_pitch);
        var sinPitch = MathF.Sin(_pitch);
        var bestScore = double.MaxValue;
        (int SubmeshIndex, int ItemIndex)? best = null;
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            var submesh = _document.Submeshes[submeshIndex];
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                if (!ShowXRay && !IsFaceFrontFacing(submeshIndex, faceIndex, cosYaw, sinYaw, cosPitch, sinPitch))
                {
                    continue;
                }
                var face = submesh.Faces[faceIndex];
                if (face.Corners.Length != 3)
                {
                    continue;
                }
                var points = new PointF[3];
                var valid = true;
                for (var cornerIndex = 0; cornerIndex < 3; cornerIndex++)
                {
                    var vertexIndex = face.Corners[cornerIndex].VertexIndex;
                    if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
                    {
                        valid = false;
                        break;
                    }
                    points[cornerIndex] = Project(submesh.Vertices[vertexIndex], cosYaw, sinYaw, cosPitch, sinPitch);
                }
                if (!valid || !PointInTriangle(point, points[0], points[1], points[2]))
                {
                    continue;
                }
                var centerX = (points[0].X + points[1].X + points[2].X) / 3.0;
                var centerY = (points[0].Y + points[1].Y + points[2].Y) / 3.0;
                var score = Math.Pow(point.X - centerX, 2.0) + Math.Pow(point.Y - centerY, 2.0);
                if (score < bestScore)
                {
                    bestScore = score;
                    best = (submeshIndex, faceIndex);
                }
            }
        }
        return best;
    }

    private bool IsVertexFrontFacing(int submeshIndex, int vertexIndex, float cosYaw, float sinYaw, float cosPitch, float sinPitch)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count || vertexIndex < 0)
        {
            return false;
        }
        var submesh = _document.Submeshes[submeshIndex];
        if (vertexIndex >= submesh.Vertices.Count)
        {
            return false;
        }
        for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
        {
            var face = submesh.Faces[faceIndex];
            if (face.Corners.Any(corner => corner.VertexIndex == vertexIndex)
                && IsFaceFrontFacing(submeshIndex, faceIndex, cosYaw, sinYaw, cosPitch, sinPitch))
            {
                return true;
            }
        }
        return false;
    }

    private static bool PointInTriangle(Point point, PointF a, PointF b, PointF c)
    {
        static float Sign(PointF p1, PointF p2, PointF p3)
        {
            return ((p1.X - p3.X) * (p2.Y - p3.Y)) - ((p2.X - p3.X) * (p1.Y - p3.Y));
        }
        var p = new PointF(point.X, point.Y);
        var d1 = Sign(p, a, b);
        var d2 = Sign(p, b, c);
        var d3 = Sign(p, c, a);
        var hasNegative = d1 < 0 || d2 < 0 || d3 < 0;
        var hasPositive = d1 > 0 || d2 > 0 || d3 > 0;
        return !(hasNegative && hasPositive);
    }

    private void BeginEdgeDrag(Point point)
    {
        BeginSelectionDrag(point, "edge");
    }

    private void FinishEdgeDrag(Point point)
    {
        _edgeDragCurrent = point;
        var rectangle = EdgeDragRectangle();
        var targetMode = _selectionDragTargetMode;
        _edgeDragActive = false;
        if (rectangle.Width < 4 && rectangle.Height < 4)
        {
            if (targetMode == "vertex")
            {
                SelectVertexAt(point);
            }
            else if (targetMode == "face")
            {
                SelectFaceAt(point);
            }
            else if (targetMode == "part" || targetMode == "source")
            {
                SelectPartAt(point);
            }
            else
            {
                SelectEdgeAt(point);
            }
            return;
        }
        if (targetMode == "vertex")
        {
            var hits = VertexIdsInRectangle(rectangle);
            ApplySelectionMapOperation(_selectedVertices, hits, CurrentSelectionOperation());
            if (hits.Length > 0)
            {
                SelectedSubmeshIndex = hits[0].SubmeshIndex;
                SubmeshSelectedRequested?.Invoke(hits[0].SubmeshIndex);
            }
            StatusRequested?.Invoke($"Vertex mode: selected={_selectedVertices.Values.Sum(vertices => vertices.Count)} drag={hits.Length} xray={(ShowXRay ? "on" : "off")}");
        }
        else if (targetMode == "face")
        {
            var hits = FaceIdsInRectangle(rectangle);
            ApplySelectionMapOperation(_selectedFaces, hits, CurrentSelectionOperation());
            if (hits.Length > 0)
            {
                SelectedSubmeshIndex = hits[0].SubmeshIndex;
                SubmeshSelectedRequested?.Invoke(hits[0].SubmeshIndex);
            }
            StatusRequested?.Invoke($"Face mode: selected={_selectedFaces.Values.Sum(faces => faces.Count)} drag={hits.Length} xray={(ShowXRay ? "on" : "off")}");
        }
        else if (targetMode == "part" || targetMode == "source")
        {
            var hits = PartIdsInRectangle(rectangle);
            ApplyPartSelectionOperation(hits, CurrentSelectionOperation());
            StatusRequested?.Invoke($"Part mode: selected={_selectedSources.Count} drag={hits.Length} xray={(ShowXRay ? "on" : "off")}");
        }
        else
        {
            var edgeIds = EdgeIdsInRectangle(rectangle);
            ApplyEdgeSelectionOperation(edgeIds, CurrentSelectionOperation());
            StatusRequested?.Invoke($"Edge mode: selected={_selectedEdges.Count} drag={edgeIds.Length} xray={(ShowXRay ? "on" : "off")}");
        }
        _hoverEdgeId = -1;
        UpdateGpuViewport();
        Invalidate();
    }

    private Rectangle EdgeDragRectangle()
    {
        var left = Math.Min(_edgeDragStart.X, _edgeDragCurrent.X);
        var top = Math.Min(_edgeDragStart.Y, _edgeDragCurrent.Y);
        var right = Math.Max(_edgeDragStart.X, _edgeDragCurrent.X);
        var bottom = Math.Max(_edgeDragStart.Y, _edgeDragCurrent.Y);
        return Rectangle.FromLTRB(left, top, right, bottom);
    }

    private (int SubmeshIndex, int ItemIndex)[] VertexIdsInRectangle(Rectangle rectangle)
    {
        var cosYaw = MathF.Cos(_yaw);
        var sinYaw = MathF.Sin(_yaw);
        var cosPitch = MathF.Cos(_pitch);
        var sinPitch = MathF.Sin(_pitch);
        var expanded = Rectangle.Inflate(rectangle, 3, 3);
        var result = new List<(int SubmeshIndex, int ItemIndex)>();
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            var submesh = _document.Submeshes[submeshIndex];
            for (var vertexIndex = 0; vertexIndex < submesh.Vertices.Count; vertexIndex++)
            {
                if (!ShowXRay && !IsVertexFrontFacing(submeshIndex, vertexIndex, cosYaw, sinYaw, cosPitch, sinPitch))
                {
                    continue;
                }
                var point = Project(submesh.Vertices[vertexIndex], cosYaw, sinYaw, cosPitch, sinPitch);
                if (expanded.Contains(Point.Round(point)))
                {
                    result.Add((submeshIndex, vertexIndex));
                }
            }
        }
        return result.OrderBy(hit => hit.SubmeshIndex).ThenBy(hit => hit.ItemIndex).ToArray();
    }

    private (int SubmeshIndex, int ItemIndex)[] FaceIdsInRectangle(Rectangle rectangle)
    {
        var cosYaw = MathF.Cos(_yaw);
        var sinYaw = MathF.Sin(_yaw);
        var cosPitch = MathF.Cos(_pitch);
        var sinPitch = MathF.Sin(_pitch);
        var expanded = Rectangle.Inflate(rectangle, 3, 3);
        var result = new List<(int SubmeshIndex, int ItemIndex)>();
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            var submesh = _document.Submeshes[submeshIndex];
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                if (!ShowXRay && !IsFaceFrontFacing(submeshIndex, faceIndex, cosYaw, sinYaw, cosPitch, sinPitch))
                {
                    continue;
                }
                if (FaceIntersectsRectangle(submesh, submesh.Faces[faceIndex], expanded, cosYaw, sinYaw, cosPitch, sinPitch))
                {
                    result.Add((submeshIndex, faceIndex));
                }
            }
        }
        return result.OrderBy(hit => hit.SubmeshIndex).ThenBy(hit => hit.ItemIndex).ToArray();
    }

    private int[] PartIdsInRectangle(Rectangle rectangle)
    {
        return FaceIdsInRectangle(rectangle)
            .Select(hit => hit.SubmeshIndex)
            .Distinct()
            .OrderBy(index => index)
            .ToArray();
    }

    private bool FaceIntersectsRectangle(ObjSubmesh submesh, ObjFace face, Rectangle rectangle, float cosYaw, float sinYaw, float cosPitch, float sinPitch)
    {
        if (face.Corners.Length != 3)
        {
            return false;
        }
        var points = new PointF[3];
        for (var i = 0; i < 3; i++)
        {
            var vertexIndex = face.Corners[i].VertexIndex;
            if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
            {
                return false;
            }
            points[i] = Project(submesh.Vertices[vertexIndex], cosYaw, sinYaw, cosPitch, sinPitch);
        }
        var center = new PointF((points[0].X + points[1].X + points[2].X) / 3.0f, (points[0].Y + points[1].Y + points[2].Y) / 3.0f);
        return rectangle.Contains(Point.Round(points[0]))
            || rectangle.Contains(Point.Round(points[1]))
            || rectangle.Contains(Point.Round(points[2]))
            || rectangle.Contains(Point.Round(center))
            || SegmentIntersectsRectangle(points[0], points[1], rectangle)
            || SegmentIntersectsRectangle(points[1], points[2], rectangle)
            || SegmentIntersectsRectangle(points[2], points[0], rectangle);
    }

    private int[] EdgeIdsInRectangle(Rectangle rectangle)
    {
        var cosYaw = MathF.Cos(_yaw);
        var sinYaw = MathF.Sin(_yaw);
        var cosPitch = MathF.Cos(_pitch);
        var sinPitch = MathF.Sin(_pitch);
        var expanded = Rectangle.Inflate(rectangle, 3, 3);
        var result = new List<int>();
        foreach (var edge in _edgeTopology.Edges)
        {
            if (!ShowXRay && !IsEdgeFrontFacing(edge, cosYaw, sinYaw, cosPitch, sinPitch))
            {
                continue;
            }
            if (edge.SubmeshIndex < 0 || edge.SubmeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[edge.SubmeshIndex];
            if (edge.VertexA < 0 || edge.VertexA >= submesh.Vertices.Count || edge.VertexB < 0 || edge.VertexB >= submesh.Vertices.Count)
            {
                continue;
            }
            var a = Project(submesh.Vertices[edge.VertexA], cosYaw, sinYaw, cosPitch, sinPitch);
            var b = Project(submesh.Vertices[edge.VertexB], cosYaw, sinYaw, cosPitch, sinPitch);
            var midpoint = new PointF((a.X + b.X) * 0.5f, (a.Y + b.Y) * 0.5f);
            if (expanded.Contains(Point.Round(a)) || expanded.Contains(Point.Round(b)) || expanded.Contains(Point.Round(midpoint)) || SegmentIntersectsRectangle(a, b, expanded))
            {
                result.Add(edge.Id);
            }
        }
        return result.OrderBy(edgeId => edgeId).ToArray();
    }

    private static bool SegmentIntersectsRectangle(PointF a, PointF b, Rectangle rectangle)
    {
        if (rectangle.Contains(Point.Round(a)) || rectangle.Contains(Point.Round(b)))
        {
            return true;
        }
        var topLeft = new PointF(rectangle.Left, rectangle.Top);
        var topRight = new PointF(rectangle.Right, rectangle.Top);
        var bottomLeft = new PointF(rectangle.Left, rectangle.Bottom);
        var bottomRight = new PointF(rectangle.Right, rectangle.Bottom);
        return LinesIntersect(a, b, topLeft, topRight)
            || LinesIntersect(a, b, topRight, bottomRight)
            || LinesIntersect(a, b, bottomRight, bottomLeft)
            || LinesIntersect(a, b, bottomLeft, topLeft);
    }

    private static bool LinesIntersect(PointF a, PointF b, PointF c, PointF d)
    {
        static float Cross(PointF p, PointF q, PointF r)
        {
            return ((q.X - p.X) * (r.Y - p.Y)) - ((q.Y - p.Y) * (r.X - p.X));
        }
        var ab1 = Cross(a, b, c);
        var ab2 = Cross(a, b, d);
        var cd1 = Cross(c, d, a);
        var cd2 = Cross(c, d, b);
        return (ab1 == 0.0f || ab2 == 0.0f || Math.Sign(ab1) != Math.Sign(ab2))
            && (cd1 == 0.0f || cd2 == 0.0f || Math.Sign(cd1) != Math.Sign(cd2));
    }

    private void SelectEdgeAt(Point point)
    {
        var edgeId = PickEdgeAt(point);
        if (edgeId < 0)
        {
            if (string.Equals(CurrentSelectionOperation(), "replace", StringComparison.OrdinalIgnoreCase))
            {
                _selectedEdges.Clear();
            }
            _hoverEdgeId = -1;
            StatusRequested?.Invoke($"Edge mode: selected={_selectedEdges.Count} hover=0 xray={(ShowXRay ? "on" : "off")}");
            UpdateGpuViewport();
            Invalidate();
            return;
        }
        ApplyEdgeSelectionOperation(edgeId, CurrentSelectionOperation());
        _hoverEdgeId = edgeId;
        StatusRequested?.Invoke($"Edge mode: selected={_selectedEdges.Count} hover=1 xray={(ShowXRay ? "on" : "off")}");
        UpdateGpuViewport();
        Invalidate();
    }

    private void UpdateHoverEdge(Point point)
    {
        var edgeId = PickEdgeAt(point);
        if (edgeId == _hoverEdgeId)
        {
            return;
        }
        _hoverEdgeId = edgeId;
        StatusRequested?.Invoke($"Edge mode: selected={_selectedEdges.Count} hover={(edgeId >= 0 ? 1 : 0)} xray={(ShowXRay ? "on" : "off")}");
        UpdateGpuViewport();
        Invalidate();
    }

    private void ApplyEdgeSelectionOperation(IEnumerable<int> edgeIds, string operation)
    {
        var ids = edgeIds.Where(_edgeTopology.Contains).Distinct().ToArray();
        var normalized = (operation ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized == "add")
        {
            foreach (var edgeId in ids)
            {
                _selectedEdges.Add(edgeId);
            }
        }
        else if (normalized == "subtract")
        {
            foreach (var edgeId in ids)
            {
                _selectedEdges.Remove(edgeId);
            }
        }
        else if (normalized == "toggle")
        {
            foreach (var edgeId in ids)
            {
                if (!_selectedEdges.Remove(edgeId))
                {
                    _selectedEdges.Add(edgeId);
                }
            }
        }
        else
        {
            _selectedEdges.Clear();
            foreach (var edgeId in ids)
            {
                _selectedEdges.Add(edgeId);
            }
        }
    }

    private void ApplyEdgeSelectionOperation(int edgeId, string operation)
    {
        var normalized = (operation ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized == "add")
        {
            _selectedEdges.Add(edgeId);
        }
        else if (normalized == "subtract")
        {
            _selectedEdges.Remove(edgeId);
        }
        else if (normalized == "toggle")
        {
            if (!_selectedEdges.Remove(edgeId))
            {
                _selectedEdges.Add(edgeId);
            }
        }
        else
        {
            _selectedEdges.Clear();
            _selectedEdges.Add(edgeId);
        }
    }

    private int PickEdgeAt(Point point)
    {
        var cosYaw = MathF.Cos(_yaw);
        var sinYaw = MathF.Sin(_yaw);
        var cosPitch = MathF.Cos(_pitch);
        var sinPitch = MathF.Sin(_pitch);
        var bestEdgeId = -1;
        var bestDistance = 9.0;
        foreach (var edge in _edgeTopology.Edges)
        {
            if (!ShowXRay && !IsEdgeFrontFacing(edge, cosYaw, sinYaw, cosPitch, sinPitch))
            {
                continue;
            }
            if (edge.SubmeshIndex < 0 || edge.SubmeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[edge.SubmeshIndex];
            if (edge.VertexA < 0 || edge.VertexA >= submesh.Vertices.Count || edge.VertexB < 0 || edge.VertexB >= submesh.Vertices.Count)
            {
                continue;
            }
            var a = Project(submesh.Vertices[edge.VertexA], cosYaw, sinYaw, cosPitch, sinPitch);
            var b = Project(submesh.Vertices[edge.VertexB], cosYaw, sinYaw, cosPitch, sinPitch);
            var distance = DistanceToSegment(point, a, b);
            if (distance < bestDistance)
            {
                bestDistance = distance;
                bestEdgeId = edge.Id;
            }
        }
        return bestEdgeId;
    }

    private bool IsEdgeFrontFacing(NetEdge edge, float cosYaw, float sinYaw, float cosPitch, float sinPitch)
    {
        if (edge.AdjacentFaces.Count == 0)
        {
            return true;
        }
        foreach (var faceIndex in edge.AdjacentFaces)
        {
            if (IsFaceFrontFacing(edge.SubmeshIndex, faceIndex, cosYaw, sinYaw, cosPitch, sinPitch))
            {
                return true;
            }
        }
        return false;
    }

    private bool IsFaceFrontFacing(int submeshIndex, int faceIndex, float cosYaw, float sinYaw, float cosPitch, float sinPitch)
    {
        if (submeshIndex < 0 || submeshIndex >= _document.Submeshes.Count)
        {
            return false;
        }
        var submesh = _document.Submeshes[submeshIndex];
        if (faceIndex < 0 || faceIndex >= submesh.Faces.Count)
        {
            return false;
        }
        var face = submesh.Faces[faceIndex];
        if (face.Corners.Length != 3)
        {
            return false;
        }
        var points = new PointF[3];
        for (var i = 0; i < 3; i++)
        {
            var vertexIndex = face.Corners[i].VertexIndex;
            if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
            {
                return false;
            }
            points[i] = Project(submesh.Vertices[vertexIndex], cosYaw, sinYaw, cosPitch, sinPitch);
        }
        var area = ((points[1].X - points[0].X) * (points[2].Y - points[0].Y)) - ((points[1].Y - points[0].Y) * (points[2].X - points[0].X));
        return area < -0.01f;
    }

    private static double DistanceToSegment(Point point, PointF a, PointF b)
    {
        var vx = b.X - a.X;
        var vy = b.Y - a.Y;
        var wx = point.X - a.X;
        var wy = point.Y - a.Y;
        var lengthSquared = (vx * vx) + (vy * vy);
        var t = lengthSquared > 0.0001f ? Math.Clamp(((wx * vx) + (wy * vy)) / lengthSquared, 0.0f, 1.0f) : 0.0f;
        var x = a.X + (t * vx);
        var y = a.Y + (t * vy);
        var dx = point.X - x;
        var dy = point.Y - y;
        return Math.Sqrt((dx * dx) + (dy * dy));
    }

    private string CurrentTargetMode()
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        return options.TryGetValue("target_mode", out var value)
            ? (value?.ToString() ?? "vertex").Trim().ToLowerInvariant()
            : "vertex";
    }

    private string CurrentSelectionOperation()
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        return options.TryGetValue("operation", out var value)
            ? (value?.ToString() ?? "replace").Trim().ToLowerInvariant()
            : "replace";
    }

    private static double NumberOption(Dictionary<string, object?> options, string key, double fallback)
    {
        return options.TryGetValue(key, out var value) && value is IConvertible
            ? Convert.ToDouble(value, CultureInfo.InvariantCulture)
            : fallback;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var started = _clock.ElapsedTicks;
        if (_gpuViewport is not null)
        {
            UpdateGpuViewport();
            Metrics.Record((_clock.ElapsedTicks - started) * 1000.0 / Stopwatch.Frequency, 0.0, Math.Max(0.0, (DateTime.UtcNow - _dirtySinceUtc).TotalMilliseconds), string.Empty);
            base.OnPaint(e);
            return;
        }
        e.Graphics.Clear(BackColor);
        e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.None;
        var normalAlpha = ShowXRay ? 70 : 150;
        using var normalPen = new Pen(Color.FromArgb(ShowXRay ? 155 : 95, 92, 130, 175), ShowXRay ? 0.8f : 1.0f);
        using var selectedPen = new Pen(Color.FromArgb(245, 211, 95), 1.6f);
        using var normalBrush = new SolidBrush(Color.FromArgb(normalAlpha, 79, 112, 152));
        using var selectedBrush = new SolidBrush(Color.FromArgb(190, 225, 190, 58));
        var points = new PointF[3];
        var cosYaw = MathF.Cos(_yaw);
        var sinYaw = MathF.Sin(_yaw);
        var cosPitch = MathF.Cos(_pitch);
        var sinPitch = MathF.Sin(_pitch);

        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            var submesh = _document.Submeshes[submeshIndex];
            var partSelected = IsPartSelected(submeshIndex);
            var pen = partSelected ? selectedPen : normalPen;
            var brush = partSelected ? selectedBrush : normalBrush;
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                var face = submesh.Faces[faceIndex];
                if (face.Corners.Length != 3)
                {
                    continue;
                }
                var valid = true;
                for (var i = 0; i < 3; i++)
                {
                    var vertexIndex = face.Corners[i].VertexIndex;
                    if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
                    {
                        valid = false;
                        break;
                    }
                    points[i] = Project(submesh.Vertices[vertexIndex], cosYaw, sinYaw, cosPitch, sinPitch);
                }
                if (valid)
                {
                    var faceSelected = IsFaceSelected(submeshIndex, faceIndex);
                    var faceBrush = faceSelected ? selectedBrush : brush;
                    var facePen = faceSelected ? selectedPen : pen;
                    var textured = ShowSolid && !faceSelected && TryDrawTexturedFace(e.Graphics, submeshIndex, submesh, face, points);
                    if ((ShowSolid || faceSelected) && !textured)
                    {
                        e.Graphics.FillPolygon(faceBrush, points);
                    }
                    if (ShowWire || ShowXRay || faceSelected)
                    {
                        e.Graphics.DrawPolygon(facePen, points);
                    }
                }
            }
        }

        DrawSelectedEdges(e.Graphics, cosYaw, sinYaw, cosPitch, sinPitch);
        DrawSelectedVertices(e.Graphics, cosYaw, sinYaw, cosPitch, sinPitch);
        DrawEdgeSelectionRectangle(e.Graphics);

        var frameTicks = _clock.ElapsedTicks - started;
        Metrics.Record(frameTicks * 1000.0 / Stopwatch.Frequency, 0.0, Math.Max(0.0, (DateTime.UtcNow - _dirtySinceUtc).TotalMilliseconds), string.Empty);
        base.OnPaint(e);
    }

    private bool TryDrawTexturedFace(Graphics graphics, int submeshIndex, ObjSubmesh submesh, ObjFace face, PointF[] destination)
    {
        var texturePath = _materials.BaseTexturePathForSubmesh(submeshIndex);
        var bitmap = _textureSet.BitmapForPath(texturePath);
        if (bitmap is null || face.Corners.Length != 3)
        {
            return false;
        }
        var source = new PointF[3];
        for (var i = 0; i < 3; i++)
        {
            var uvIndex = face.Corners[i].UvIndex;
            if (uvIndex < 0 || uvIndex >= submesh.Uvs.Count)
            {
                return false;
            }
            var uv = submesh.Uvs[uvIndex];
            source[i] = new PointF(uv.U * bitmap.Width, (1.0f - uv.V) * bitmap.Height);
        }
        return DrawAffineTexturedTriangle(graphics, bitmap, source, destination);
    }

    private static bool DrawAffineTexturedTriangle(Graphics graphics, Bitmap bitmap, PointF[] source, PointF[] destination)
    {
        var denominator = source[0].X * (source[1].Y - source[2].Y)
            + source[1].X * (source[2].Y - source[0].Y)
            + source[2].X * (source[0].Y - source[1].Y);
        if (Math.Abs(denominator) < 0.001f)
        {
            return false;
        }
        var m11 = (destination[0].X * (source[1].Y - source[2].Y)
            + destination[1].X * (source[2].Y - source[0].Y)
            + destination[2].X * (source[0].Y - source[1].Y)) / denominator;
        var m12 = (destination[0].Y * (source[1].Y - source[2].Y)
            + destination[1].Y * (source[2].Y - source[0].Y)
            + destination[2].Y * (source[0].Y - source[1].Y)) / denominator;
        var m21 = (destination[0].X * (source[2].X - source[1].X)
            + destination[1].X * (source[0].X - source[2].X)
            + destination[2].X * (source[1].X - source[0].X)) / denominator;
        var m22 = (destination[0].Y * (source[2].X - source[1].X)
            + destination[1].Y * (source[0].X - source[2].X)
            + destination[2].Y * (source[1].X - source[0].X)) / denominator;
        var dx = (destination[0].X * ((source[1].X * source[2].Y) - (source[2].X * source[1].Y))
            + destination[1].X * ((source[2].X * source[0].Y) - (source[0].X * source[2].Y))
            + destination[2].X * ((source[0].X * source[1].Y) - (source[1].X * source[0].Y))) / denominator;
        var dy = (destination[0].Y * ((source[1].X * source[2].Y) - (source[2].X * source[1].Y))
            + destination[1].Y * ((source[2].X * source[0].Y) - (source[0].X * source[2].Y))
            + destination[2].Y * ((source[0].X * source[1].Y) - (source[1].X * source[0].Y))) / denominator;
        var state = graphics.Save();
        try
        {
            using var clipPath = new System.Drawing.Drawing2D.GraphicsPath();
            clipPath.AddPolygon(destination);
            graphics.SetClip(clipPath);
            using var matrix = new System.Drawing.Drawing2D.Matrix(m11, m12, m21, m22, dx, dy);
            graphics.Transform = matrix;
            graphics.DrawImage(bitmap, 0, 0, bitmap.Width, bitmap.Height);
        }
        finally
        {
            graphics.Restore(state);
        }
        return true;
    }

    private bool IsPartSelected(int submeshIndex)
    {
        return submeshIndex == SelectedSubmeshIndex || _selectedSources.Contains(submeshIndex);
    }

    private bool IsFaceSelected(int submeshIndex, int faceIndex)
    {
        return _selectedFaces.TryGetValue(submeshIndex, out var faces) && faces.Contains(faceIndex);
    }

    private void DrawEdgeSelectionRectangle(Graphics graphics)
    {
        if (!_edgeDragActive)
        {
            return;
        }
        var rectangle = EdgeDragRectangle();
        using var pen = new Pen(Color.FromArgb(190, 96, 202, 255), 1.0f) { DashStyle = System.Drawing.Drawing2D.DashStyle.Dash };
        using var brush = new SolidBrush(Color.FromArgb(36, 96, 202, 255));
        graphics.FillRectangle(brush, rectangle);
        graphics.DrawRectangle(pen, rectangle);
    }

    private void DrawSelectedEdges(Graphics graphics, float cosYaw, float sinYaw, float cosPitch, float sinPitch)
    {
        using var selectedPen = new Pen(Color.FromArgb(245, 255, 224, 92), 2.2f);
        using var hoverPen = new Pen(Color.FromArgb(245, 96, 202, 255), 2.0f);
        foreach (var edge in _edgeTopology.Edges)
        {
            var selected = _selectedEdges.Contains(edge.Id);
            var hovered = edge.Id == _hoverEdgeId;
            if (!selected && !hovered)
            {
                continue;
            }
            if (edge.SubmeshIndex < 0 || edge.SubmeshIndex >= _document.Submeshes.Count)
            {
                continue;
            }
            var submesh = _document.Submeshes[edge.SubmeshIndex];
            if (edge.VertexA < 0 || edge.VertexA >= submesh.Vertices.Count || edge.VertexB < 0 || edge.VertexB >= submesh.Vertices.Count)
            {
                continue;
            }
            var a = Project(submesh.Vertices[edge.VertexA], cosYaw, sinYaw, cosPitch, sinPitch);
            var b = Project(submesh.Vertices[edge.VertexB], cosYaw, sinYaw, cosPitch, sinPitch);
            graphics.DrawLine(hovered ? hoverPen : selectedPen, a, b);
        }
    }

    private void DrawSelectedVertices(Graphics graphics, float cosYaw, float sinYaw, float cosPitch, float sinPitch)
    {
        using var brush = new SolidBrush(Color.FromArgb(235, 255, 224, 92));
        using var pen = new Pen(Color.FromArgb(255, 44, 25, 10), 1.0f);
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            var submesh = _document.Submeshes[submeshIndex];
            foreach (var vertexIndex in SelectionVerticesForSubmesh(submeshIndex))
            {
                if (vertexIndex < 0 || vertexIndex >= submesh.Vertices.Count)
                {
                    continue;
                }
                var point = Project(submesh.Vertices[vertexIndex], cosYaw, sinYaw, cosPitch, sinPitch);
                var rect = new RectangleF(point.X - 3.0f, point.Y - 3.0f, 6.0f, 6.0f);
                graphics.FillEllipse(brush, rect);
                graphics.DrawEllipse(pen, rect);
            }
        }
    }

    private PointF Project(Vec3 vertex, float cosYaw, float sinYaw, float cosPitch, float sinPitch)
    {
        var x = vertex.X - _center.X;
        var y = vertex.Y - _center.Y;
        var z = vertex.Z - _center.Z;
        var rx = x * cosYaw - z * sinYaw;
        var rz = x * sinYaw + z * cosYaw;
        var ry = y * cosPitch - rz * sinPitch;

        return new PointF(
            Width * 0.5f + _panX + rx * _zoom,
            Height * 0.5f + _panY - ry * _zoom);
    }
}

internal sealed class RenderMetrics
{
    private readonly Queue<double> _frameMs = new();
    private readonly Queue<double> _presentMs = new();
    private readonly Queue<double> _dirtyToPresentMs = new();
    private readonly Queue<double> _responsivenessMs = new();

    public double AverageFrameMs { get; private set; }
    public double AveragePresentMs { get; private set; }
    public double AverageDirtyToPresentMs { get; private set; }
    public double AverageResponsivenessMs { get; private set; }
    public int DroppedFrames { get; private set; }
    public string DeviceRemovedReason { get; private set; } = string.Empty;
    public double AverageFps => AverageFrameMs > 0.0001 ? 1000.0 / AverageFrameMs : 0.0;

    public void Record(double frameMs, double presentMs, double dirtyToPresentMs, string deviceRemovedReason)
    {
        var normalizedFrameMs = Math.Max(0.0, frameMs);
        _frameMs.Enqueue(normalizedFrameMs);
        _presentMs.Enqueue(Math.Max(0.0, presentMs));
        _dirtyToPresentMs.Enqueue(Math.Max(0.0, dirtyToPresentMs));
        while (_frameMs.Count > 120)
        {
            _frameMs.Dequeue();
        }
        while (_presentMs.Count > 120)
        {
            _presentMs.Dequeue();
        }
        while (_dirtyToPresentMs.Count > 120)
        {
            _dirtyToPresentMs.Dequeue();
        }
        if (normalizedFrameMs > 16.7)
        {
            DroppedFrames++;
        }
        if (!string.IsNullOrWhiteSpace(deviceRemovedReason))
        {
            DeviceRemovedReason = deviceRemovedReason;
        }
        AverageFrameMs = _frameMs.Count == 0 ? 0.0 : _frameMs.Average();
        AveragePresentMs = _presentMs.Count == 0 ? 0.0 : _presentMs.Average();
        AverageDirtyToPresentMs = _dirtyToPresentMs.Count == 0 ? 0.0 : _dirtyToPresentMs.Average();
    }

    public void RecordResponsiveness(double responsivenessMs)
    {
        _responsivenessMs.Enqueue(Math.Max(0.0, responsivenessMs));
        while (_responsivenessMs.Count > 120)
        {
            _responsivenessMs.Dequeue();
        }
        AverageResponsivenessMs = _responsivenessMs.Count == 0 ? 0.0 : _responsivenessMs.Average();
    }
}

internal static class HeadlessRenderer
{
    public static RenderMetrics Measure(ObjDocument document, int frameCount = 60)
    {
        var metrics = new RenderMetrics();
        var bounds = document.Bounds();
        var center = new Vec3(
            (bounds.Min.X + bounds.Max.X) * 0.5f,
            (bounds.Min.Y + bounds.Max.Y) * 0.5f,
            (bounds.Min.Z + bounds.Max.Z) * 0.5f);
        var size = Math.Max(bounds.Max.X - bounds.Min.X, Math.Max(bounds.Max.Y - bounds.Min.Y, bounds.Max.Z - bounds.Min.Z));
        var zoom = size > 0.0001f ? 380.0f / size : 220.0f;
        for (var frame = 0; frame < frameCount; frame++)
        {
            var yaw = -0.35f + frame * 0.01f;
            var pitch = 0.25f;
            var started = Stopwatch.GetTimestamp();
            var projected = 0;
            foreach (var submesh in document.Submeshes)
            {
                foreach (var face in submesh.Faces)
                {
                    foreach (var corner in face.Corners)
                    {
                        if (corner.VertexIndex < 0 || corner.VertexIndex >= submesh.Vertices.Count)
                        {
                            continue;
                        }
                        _ = Project(submesh.Vertices[corner.VertexIndex], center, yaw, pitch, zoom);
                        projected++;
                    }
                }
            }
            var elapsedMs = (Stopwatch.GetTimestamp() - started) * 1000.0 / Stopwatch.Frequency;
            metrics.Record(elapsedMs, 0.0, 0.0, string.Empty);
            metrics.RecordResponsiveness(elapsedMs / Math.Max(1, projected));
        }
        return metrics;
    }

    private static PointF Project(Vec3 vertex, Vec3 center, float yaw, float pitch, float zoom)
    {
        var x = vertex.X - center.X;
        var y = vertex.Y - center.Y;
        var z = vertex.Z - center.Z;
        var cosYaw = MathF.Cos(yaw);
        var sinYaw = MathF.Sin(yaw);
        var rx = x * cosYaw - z * sinYaw;
        var rz = x * sinYaw + z * cosYaw;
        var cosPitch = MathF.Cos(pitch);
        var sinPitch = MathF.Sin(pitch);
        var ry = y * cosPitch - rz * sinPitch;
        return new PointF(rx * zoom, -ry * zoom);
    }
}

internal sealed record LaunchOptions(
    string InputPackage,
    string MeshPath,
    string MetadataPath,
    string StatusPath,
    string OutputDir,
    string EditOperationsPath,
    string EvaluationPath,
    bool HeadlessSmoke,
    bool Embedded,
    long ParentHwnd)
{
    public string CloseRequestPath => Path.Combine(InputPackage, "dotnet_close_requested.txt");
    public string MaterialsPath => Path.Combine(InputPackage, "net_materials.json");

    public static LaunchOptions Parse(string[] args)
    {
        var values = ParseArgs(args);
        string Required(string name)
        {
            if (!values.TryGetValue(name, out var value) || string.IsNullOrWhiteSpace(value))
            {
                throw new ArgumentException($"Missing required argument: --{name}");
            }
            return Path.GetFullPath(value);
        }

        return new LaunchOptions(
            Required("input-package"),
            Required("mesh"),
            Required("metadata"),
            Required("status"),
            Required("output"),
            Required("edit-operations"),
            values.TryGetValue("evaluation", out var evaluation) && !string.IsNullOrWhiteSpace(evaluation)
                ? Path.GetFullPath(evaluation)
                : Path.Combine(Required("input-package"), "dotnet_evaluation.md"),
            values.ContainsKey("headless-smoke"),
            values.ContainsKey("embedded"),
            values.TryGetValue("parent-hwnd", out var parentHwnd) && long.TryParse(parentHwnd, NumberStyles.Integer, CultureInfo.InvariantCulture, out var hwnd)
                ? hwnd
                : 0L);
    }

    public static LaunchOptions? TryParse(string[] args)
    {
        try
        {
            return Parse(args);
        }
        catch
        {
            return null;
        }
    }

    private static Dictionary<string, string> ParseArgs(string[] args)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var i = 0; i < args.Length; i++)
        {
            var arg = args[i];
            if (!arg.StartsWith("--", StringComparison.Ordinal))
            {
                continue;
            }
            var key = arg[2..];
            if (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
            {
                result[key] = args[++i];
            }
            else
            {
                result[key] = "true";
            }
        }
        return result;
    }
}

internal static class NativeWindowHost
{
    private const int GwlStyle = -16;
    private const long WsChild = 0x40000000L;
    private const long WsPopup = 0x80000000L;
    private const long WsCaption = 0x00C00000L;
    private const uint SwpNoZOrder = 0x0004;
    private const uint SwpNoActivate = 0x0010;
    private const uint SwpFrameChanged = 0x0020;
    private const uint SwpShowWindow = 0x0040;

    public static bool Embed(Form form, IntPtr parent)
    {
        if (parent == IntPtr.Zero || !IsWindow(parent))
        {
            return false;
        }
        SetParent(form.Handle, parent);
        var style = GetWindowLongPtrSafe(form.Handle, GwlStyle).ToInt64();
        style |= WsChild;
        style &= ~WsPopup;
        style &= ~WsCaption;
        SetWindowLongPtrSafe(form.Handle, GwlStyle, new IntPtr(style));
        ResizeToParent(form, parent);
        return true;
    }

    public static void ResizeToParent(Form form, IntPtr parent)
    {
        if (parent == IntPtr.Zero || !IsWindow(parent) || !GetClientRect(parent, out var rect))
        {
            return;
        }
        var width = Math.Max(1, rect.Right - rect.Left);
        var height = Math.Max(1, rect.Bottom - rect.Top);
        SetWindowPos(form.Handle, IntPtr.Zero, 0, 0, width, height, SwpNoZOrder | SwpNoActivate | SwpFrameChanged | SwpShowWindow);
    }

    private static IntPtr GetWindowLongPtrSafe(IntPtr hwnd, int index)
    {
        return IntPtr.Size == 8 ? GetWindowLongPtr64(hwnd, index) : new IntPtr(GetWindowLong32(hwnd, index));
    }

    private static IntPtr SetWindowLongPtrSafe(IntPtr hwnd, int index, IntPtr value)
    {
        return IntPtr.Size == 8 ? SetWindowLongPtr64(hwnd, index, value) : new IntPtr(SetWindowLong32(hwnd, index, value.ToInt32()));
    }

    [DllImport("user32.dll")]
    private static extern IntPtr SetParent(IntPtr child, IntPtr parent);

    [DllImport("user32.dll")]
    private static extern bool IsWindow(IntPtr hwnd);

    [DllImport("user32.dll")]
    private static extern bool GetClientRect(IntPtr hwnd, out Rect rect);

    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr hwnd, IntPtr hwndInsertAfter, int x, int y, int cx, int cy, uint flags);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    private static extern IntPtr GetWindowLongPtr64(IntPtr hwnd, int index);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
    private static extern IntPtr SetWindowLongPtr64(IntPtr hwnd, int index, IntPtr value);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongW")]
    private static extern int GetWindowLong32(IntPtr hwnd, int index);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongW")]
    private static extern int SetWindowLong32(IntPtr hwnd, int index, int value);

    [StructLayout(LayoutKind.Sequential)]
    private struct Rect
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }
}

internal sealed class ObjDocument
{
    public List<string> HeaderComments { get; } = new();
    public List<string> MaterialLibraries { get; } = new();
    public List<ObjSubmesh> Submeshes { get; } = new();

    public static ObjDocument Load(string path)
    {
        var document = new ObjDocument();
        var globalVertices = new List<Vec3>();
        var globalUvs = new List<Vec2>();
        var globalNormals = new List<Vec3>();
        ObjSubmesh? current = null;
        foreach (var rawLine in File.ReadLines(path))
        {
            var line = rawLine.Trim();
            if (line.Length == 0)
            {
                continue;
            }
            if (line.StartsWith("#", StringComparison.Ordinal))
            {
                document.HeaderComments.Add(line);
                continue;
            }
            var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 0)
            {
                continue;
            }
            switch (parts[0])
            {
                case "mtllib":
                    if (parts.Length > 1)
                    {
                        document.MaterialLibraries.Add(parts[1]);
                    }
                    break;
                case "o":
                case "g":
                    current = new ObjSubmesh(
                        parts.Length > 1 ? parts[1] : $"submesh_{document.Submeshes.Count}",
                        globalVertices.Count,
                        globalUvs.Count,
                        globalNormals.Count);
                    document.Submeshes.Add(current);
                    break;
                case "usemtl":
                    current ??= document.EnsureDefaultSubmesh(globalVertices.Count, globalUvs.Count, globalNormals.Count);
                    current.Material = parts.Length > 1 ? parts[1] : "";
                    break;
                case "v":
                    current ??= document.EnsureDefaultSubmesh(globalVertices.Count, globalUvs.Count, globalNormals.Count);
                    var vertex = new Vec3(ParseFloat(parts, 1), ParseFloat(parts, 2), ParseFloat(parts, 3));
                    globalVertices.Add(vertex);
                    current.Vertices.Add(vertex);
                    break;
                case "vt":
                    current ??= document.EnsureDefaultSubmesh(globalVertices.Count, globalUvs.Count, globalNormals.Count);
                    var uv = new Vec2(ParseFloat(parts, 1), ParseFloat(parts, 2));
                    globalUvs.Add(uv);
                    current.Uvs.Add(uv);
                    break;
                case "vn":
                    current ??= document.EnsureDefaultSubmesh(globalVertices.Count, globalUvs.Count, globalNormals.Count);
                    var normal = new Vec3(ParseFloat(parts, 1), ParseFloat(parts, 2), ParseFloat(parts, 3));
                    globalNormals.Add(normal);
                    current.Normals.Add(normal);
                    break;
                case "f":
                    current ??= document.EnsureDefaultSubmesh(globalVertices.Count, globalUvs.Count, globalNormals.Count);
                    var corners = parts.Skip(1).Select(token => ParseCorner(token, current, globalVertices.Count, globalUvs.Count, globalNormals.Count)).ToArray();
                    for (var i = 1; i < corners.Length - 1; i++)
                    {
                        current.Faces.Add(new ObjFace(new[] { corners[0], corners[i], corners[i + 1] }));
                    }
                    break;
            }
        }
        if (document.Submeshes.Count == 0)
        {
            throw new InvalidOperationException("OBJ did not contain any submeshes.");
        }
        return document;
    }

    public void Save(string outputPath, string inputObjPath)
    {
        var outputDir = Path.GetDirectoryName(outputPath);
        if (!string.IsNullOrWhiteSpace(outputDir))
        {
            Directory.CreateDirectory(outputDir);
        }

        using var writer = new StreamWriter(outputPath, false, new UTF8Encoding(false));
        foreach (var comment in HeaderComments.Where(comment => comment.StartsWith("# source_", StringComparison.OrdinalIgnoreCase)))
        {
            writer.WriteLine(comment);
        }
        var materialName = MaterialLibraries.FirstOrDefault() ?? "mesh.mtl";
        var inputMtl = Path.Combine(Path.GetDirectoryName(inputObjPath) ?? "", materialName);
        if (File.Exists(inputMtl) && outputDir is not null)
        {
            File.Copy(inputMtl, Path.Combine(outputDir, Path.GetFileName(materialName)), overwrite: true);
            writer.WriteLine($"mtllib {Path.GetFileName(materialName)}");
        }

        var vertexOffset = 0;
        var uvOffset = 0;
        var normalOffset = 0;
        foreach (var submesh in Submeshes)
        {
            writer.WriteLine($"o {submesh.Name}");
            foreach (var vertex in submesh.Vertices)
            {
                writer.WriteLine(FormattableString.Invariant($"v {vertex.X:R} {vertex.Y:R} {vertex.Z:R}"));
            }
            foreach (var uv in submesh.Uvs)
            {
                writer.WriteLine(FormattableString.Invariant($"vt {uv.U:R} {uv.V:R}"));
            }
            foreach (var normal in submesh.Normals)
            {
                writer.WriteLine(FormattableString.Invariant($"vn {normal.X:R} {normal.Y:R} {normal.Z:R}"));
            }
            if (!string.IsNullOrWhiteSpace(submesh.Material))
            {
                writer.WriteLine($"usemtl {submesh.Material}");
            }
            foreach (var face in submesh.Faces)
            {
                writer.WriteLine("f " + string.Join(" ", face.Corners.Select(corner => FormatCorner(corner, vertexOffset, uvOffset, normalOffset, submesh))));
            }
            vertexOffset += submesh.Vertices.Count;
            uvOffset += submesh.Uvs.Count;
            normalOffset += submesh.Normals.Count;
        }
    }

    public (Vec3 Min, Vec3 Max) Bounds()
    {
        var found = false;
        var minX = 0.0f;
        var minY = 0.0f;
        var minZ = 0.0f;
        var maxX = 0.0f;
        var maxY = 0.0f;
        var maxZ = 0.0f;
        foreach (var submesh in Submeshes)
        {
            foreach (var vertex in submesh.Vertices)
            {
                if (!found)
                {
                    minX = maxX = vertex.X;
                    minY = maxY = vertex.Y;
                    minZ = maxZ = vertex.Z;
                    found = true;
                    continue;
                }
                minX = Math.Min(minX, vertex.X);
                minY = Math.Min(minY, vertex.Y);
                minZ = Math.Min(minZ, vertex.Z);
                maxX = Math.Max(maxX, vertex.X);
                maxY = Math.Max(maxY, vertex.Y);
                maxZ = Math.Max(maxZ, vertex.Z);
            }
        }
        if (!found)
        {
            return (new Vec3(-1, -1, -1), new Vec3(1, 1, 1));
        }
        return (new Vec3(minX, minY, minZ), new Vec3(maxX, maxY, maxZ));
    }

    private ObjSubmesh EnsureDefaultSubmesh(int vertexStart, int uvStart, int normalStart)
    {
        if (Submeshes.Count > 0)
        {
            return Submeshes[^1];
        }
        var submesh = new ObjSubmesh("default", vertexStart, uvStart, normalStart);
        Submeshes.Add(submesh);
        return submesh;
    }

    private static ObjCorner ParseCorner(string token, ObjSubmesh submesh, int vertexCount, int uvCount, int normalCount)
    {
        var parts = token.Split('/');
        var vertex = ResolveObjIndex(parts.ElementAtOrDefault(0), vertexCount) - submesh.VertexStart;
        var uv = parts.Length > 1 && parts[1].Length > 0 ? ResolveObjIndex(parts[1], uvCount) - submesh.UvStart : -1;
        var normal = parts.Length > 2 && parts[2].Length > 0 ? ResolveObjIndex(parts[2], normalCount) - submesh.NormalStart : -1;
        return new ObjCorner(vertex, uv, normal);
    }

    private static int ResolveObjIndex(string? raw, int count)
    {
        if (!int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value))
        {
            return 0;
        }
        if (value > 0)
        {
            return value - 1;
        }
        if (value < 0)
        {
            return count + value;
        }
        return 0;
    }

    private static string FormatCorner(ObjCorner corner, int vertexOffset, int uvOffset, int normalOffset, ObjSubmesh submesh)
    {
        var vertex = vertexOffset + Math.Clamp(corner.VertexIndex, 0, Math.Max(0, submesh.Vertices.Count - 1)) + 1;
        var hasUv = corner.UvIndex >= 0 && corner.UvIndex < submesh.Uvs.Count;
        var hasNormal = corner.NormalIndex >= 0 && corner.NormalIndex < submesh.Normals.Count;
        if (hasUv && hasNormal)
        {
            return $"{vertex}/{uvOffset + corner.UvIndex + 1}/{normalOffset + corner.NormalIndex + 1}";
        }
        if (hasUv)
        {
            return $"{vertex}/{uvOffset + corner.UvIndex + 1}";
        }
        if (hasNormal)
        {
            return $"{vertex}//{normalOffset + corner.NormalIndex + 1}";
        }
        return vertex.ToString(CultureInfo.InvariantCulture);
    }

    private static float ParseFloat(string[] parts, int index)
    {
        return index < parts.Length && float.TryParse(parts[index], NumberStyles.Float, CultureInfo.InvariantCulture, out var value)
            ? value
            : 0.0f;
    }
}

internal sealed class ObjSubmesh
{
    public ObjSubmesh(string name, int vertexStart, int uvStart, int normalStart)
    {
        Name = name;
        VertexStart = vertexStart;
        UvStart = uvStart;
        NormalStart = normalStart;
    }

    public string Name { get; }
    public string Material { get; set; } = "";
    public int VertexStart { get; }
    public int UvStart { get; }
    public int NormalStart { get; }
    public List<Vec3> Vertices { get; } = new();
    public List<Vec2> Uvs { get; } = new();
    public List<Vec3> Normals { get; } = new();
    public List<ObjFace> Faces { get; } = new();
}

internal sealed record ObjFace(ObjCorner[] Corners);
internal sealed record ObjCorner(int VertexIndex, int UvIndex, int NormalIndex);

internal sealed class NetEdge
{
    public NetEdge(int id, int submeshIndex, int vertexA, int vertexB, int sourceVertexA, int sourceVertexB)
    {
        Id = id;
        SubmeshIndex = submeshIndex;
        VertexA = vertexA;
        VertexB = vertexB;
        SourceVertexA = Math.Min(sourceVertexA, sourceVertexB);
        SourceVertexB = Math.Max(sourceVertexA, sourceVertexB);
        StableKey = $"submesh:{submeshIndex}|source_vertices:{SourceVertexA}:{SourceVertexB}";
    }

    public int Id { get; }
    public int SubmeshIndex { get; }
    public int VertexA { get; }
    public int VertexB { get; }
    public int SourceVertexA { get; }
    public int SourceVertexB { get; }
    public string StableKey { get; }
    public List<int> AdjacentFaces { get; } = new();
    public bool IsBoundary => AdjacentFaces.Count <= 1;

    public Dictionary<string, object?> ToDescriptorPayload(int topologyGeneration)
    {
        return new Dictionary<string, object?>
        {
            ["id"] = Id,
            ["stable_key"] = StableKey,
            ["native_edge_identifier"] = StableKey,
            ["topology_generation"] = topologyGeneration,
            ["source_submesh_index"] = SubmeshIndex,
            ["submesh_index"] = SubmeshIndex,
            ["vertex_a"] = VertexA,
            ["vertex_b"] = VertexB,
            ["source_vertex_a"] = SourceVertexA,
            ["source_vertex_b"] = SourceVertexB,
            ["source_vertex_pair"] = new[] { SourceVertexA, SourceVertexB },
            ["adjacent_faces"] = AdjacentFaces.OrderBy(value => value).ToArray(),
            ["boundary"] = IsBoundary,
        };
    }
}

internal sealed class NetEdgeTopology
{
    public static NetEdgeTopology Empty { get; } = new(Array.Empty<NetEdge>(), 0);

    private readonly Dictionary<int, NetEdge> _edgesById;
    private readonly Dictionary<string, NetEdge> _edgesByStableKey;

    private NetEdgeTopology(IEnumerable<NetEdge> edges, int generation)
    {
        Edges = edges.ToArray();
        Generation = generation;
        _edgesById = Edges.ToDictionary(edge => edge.Id);
        _edgesByStableKey = Edges.ToDictionary(edge => edge.StableKey, StringComparer.OrdinalIgnoreCase);
    }

    public IReadOnlyList<NetEdge> Edges { get; }
    public int Generation { get; }

    public bool Contains(int edgeId)
    {
        return edgeId >= 0 && _edgesById.ContainsKey(edgeId);
    }

    public NetEdge? EdgeById(int edgeId)
    {
        return _edgesById.TryGetValue(edgeId, out var edge) ? edge : null;
    }

    public NetEdge? EdgeByStableKey(string stableKey)
    {
        return !string.IsNullOrWhiteSpace(stableKey) && _edgesByStableKey.TryGetValue(stableKey, out var edge) ? edge : null;
    }

    public static NetEdgeTopology Build(ObjDocument document, int generation = 1)
    {
        var edges = new List<NetEdge>();
        var lookup = new Dictionary<(int SubmeshIndex, int A, int B), NetEdge>();
        var nextId = 0;
        for (var submeshIndex = 0; submeshIndex < document.Submeshes.Count; submeshIndex++)
        {
            var submesh = document.Submeshes[submeshIndex];
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                var face = submesh.Faces[faceIndex];
                if (face.Corners.Length != 3)
                {
                    continue;
                }
                AddFaceEdge(submeshIndex, faceIndex, submesh.VertexStart, face.Corners[0].VertexIndex, face.Corners[1].VertexIndex, edges, lookup, ref nextId);
                AddFaceEdge(submeshIndex, faceIndex, submesh.VertexStart, face.Corners[1].VertexIndex, face.Corners[2].VertexIndex, edges, lookup, ref nextId);
                AddFaceEdge(submeshIndex, faceIndex, submesh.VertexStart, face.Corners[2].VertexIndex, face.Corners[0].VertexIndex, edges, lookup, ref nextId);
            }
        }
        return new NetEdgeTopology(edges, generation);
    }

    private static void AddFaceEdge(
        int submeshIndex,
        int faceIndex,
        int sourceVertexOffset,
        int vertexA,
        int vertexB,
        List<NetEdge> edges,
        Dictionary<(int SubmeshIndex, int A, int B), NetEdge> lookup,
        ref int nextId)
    {
        if (vertexA < 0 || vertexB < 0 || vertexA == vertexB)
        {
            return;
        }
        var a = Math.Min(vertexA, vertexB);
        var b = Math.Max(vertexA, vertexB);
        var key = (submeshIndex, a, b);
        if (!lookup.TryGetValue(key, out var edge))
        {
            edge = new NetEdge(nextId++, submeshIndex, a, b, sourceVertexA: sourceVertexOffset + a, sourceVertexB: sourceVertexOffset + b);
            lookup[key] = edge;
            edges.Add(edge);
        }
        edge.AdjacentFaces.Add(faceIndex);
    }
}

internal sealed class NetMaterialSet
{
    public static NetMaterialSet Empty { get; } = new(Array.Empty<NetMaterialSlot>(), Array.Empty<NetSubmeshMaterialBinding>(), string.Empty);

    private NetMaterialSet(IReadOnlyList<NetMaterialSlot> slots, IReadOnlyList<NetSubmeshMaterialBinding> submeshes, string manifestDirectory)
    {
        Slots = slots;
        Submeshes = submeshes;
        ManifestDirectory = manifestDirectory;
    }

    public IReadOnlyList<NetMaterialSlot> Slots { get; }
    public IReadOnlyList<NetSubmeshMaterialBinding> Submeshes { get; }
    public string ManifestDirectory { get; }
    public int SlotCount => Slots.Count;
    public int TextureReferenceCount => Slots.Sum(slot => slot.Channels.Values.Count(value => !string.IsNullOrWhiteSpace(value)))
        + SubmeshTexturePaths().Count(value => !string.IsNullOrWhiteSpace(value));
    public int ResolvedTextureReferenceCount => SubmeshTexturePaths().Count(value => !string.IsNullOrWhiteSpace(value));
    public int ExistingTextureFileCount => SubmeshTexturePaths().Count(value => !string.IsNullOrWhiteSpace(value) && File.Exists(value));
    public int DecodableTextureFileCount => SubmeshTexturePaths().Count(IsDecodableImagePath);

    public IEnumerable<string> SubmeshTexturePaths()
    {
        foreach (var submesh in Submeshes)
        {
            foreach (var value in submesh.PackageChannels.Values)
            {
                yield return ResolveManifestPath(value);
            }
            foreach (var value in submesh.ResolvedChannels.Values)
            {
                yield return value;
            }
        }
    }

    private string ResolveManifestPath(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }
        return Path.IsPathRooted(value) || string.IsNullOrWhiteSpace(ManifestDirectory)
            ? value
            : Path.GetFullPath(Path.Combine(ManifestDirectory, value));
    }

    public string TexturePathForSubmesh(int submeshIndex, params string[] keys)
    {
        var binding = Submeshes.FirstOrDefault(item => item.SubmeshIndex == submeshIndex);
        if (binding is null)
        {
            return string.Empty;
        }
        foreach (var key in keys)
        {
            if (binding.PackageChannels.TryGetValue(key, out var packaged) && !string.IsNullOrWhiteSpace(packaged))
            {
                return ResolveManifestPath(packaged);
            }
            if (binding.ResolvedChannels.TryGetValue(key, out var value) && !string.IsNullOrWhiteSpace(value))
            {
                return value;
            }
        }
        return string.Empty;
    }

    public string BaseTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "base", "albedo", "diffuse");
    }

    public string EmissiveTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "emissive");
    }

    public string NormalTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "normal");
    }

    public string SpecularTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "specular", "material");
    }

    public string RoughnessTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "roughness", "material");
    }

    public string MetallicTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "metallic", "material");
    }

    public string HeightTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "height");
    }

    public static NetMaterialSet Load(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            return Empty;
        }
        using var document = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
        var root = document.RootElement;
        return new NetMaterialSet(
            ParseSlots(root, "material_slots"),
            ParseSubmeshes(root, "submeshes"),
            Path.GetDirectoryName(path) ?? string.Empty);
    }

    private static IReadOnlyList<NetMaterialSlot> ParseSlots(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var array) || array.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<NetMaterialSlot>();
        }
        var result = new List<NetMaterialSlot>();
        foreach (var item in array.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            result.Add(new NetMaterialSlot(
                JsonInt(item, "index", result.Count),
                JsonString(item, "name"),
                JsonString(item, "texture"),
                JsonStringMap(item, "channels")));
        }
        return result;
    }

    private static IReadOnlyList<NetSubmeshMaterialBinding> ParseSubmeshes(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var array) || array.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<NetSubmeshMaterialBinding>();
        }
        var result = new List<NetSubmeshMaterialBinding>();
        foreach (var item in array.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            result.Add(new NetSubmeshMaterialBinding(
                JsonInt(item, "submesh_index", result.Count),
                JsonInt(item, "material_slot_index", result.Count),
                JsonString(item, "material"),
                JsonString(item, "texture"),
                JsonStringMap(item, "resolved_channels"),
                JsonStringMap(item, "packaged_channels")));
        }
        return result;
    }

    private static Dictionary<string, string> JsonStringMap(JsonElement element, string name)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Object)
        {
            return result;
        }
        foreach (var property in value.EnumerateObject())
        {
            if (property.Value.ValueKind == JsonValueKind.String)
            {
                result[property.Name] = property.Value.GetString() ?? string.Empty;
            }
        }
        return result;
    }

    private static bool IsDecodableImagePath(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || !File.Exists(value))
        {
            return false;
        }
        var extension = Path.GetExtension(value).ToLowerInvariant();
        return extension is ".png" or ".jpg" or ".jpeg" or ".bmp" or ".gif" or ".tif" or ".tiff";
    }

    private static string JsonString(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? string.Empty
            : string.Empty;
    }

    private static int JsonInt(JsonElement element, string name, int fallback)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number)
            ? number
            : fallback;
    }
}

internal sealed record NetMaterialSlot(int Index, string Name, string Texture, Dictionary<string, string> Channels);

internal sealed class NetTextureSet : IDisposable
{
    private readonly Dictionary<string, Bitmap> _decoded = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Bitmap> _materialPreviews = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, NetDdsTextureInfo> _ddsResources = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<string> _textureLoadFailures = new();

    private NetTextureSet()
    {
    }

    public int DecodedCount => _decoded.Count;
    public int DdsResourceCount => _ddsResources.Count;
    public int DdsDecodedCount => _ddsResources.Values.Count(info => info.Decoded);
    public int TextureLoadFailureCount => _textureLoadFailures.Count;
    public IReadOnlyDictionary<string, NetDdsTextureInfo> DdsResources => _ddsResources;
    public IReadOnlyList<string> TextureLoadFailures => _textureLoadFailures;

    public static NetTextureSet Load(NetMaterialSet materials)
    {
        var set = new NetTextureSet();
        foreach (var path in materials.SubmeshTexturePaths()
            .Where(value => !string.IsNullOrWhiteSpace(value) && File.Exists(value))
            .Distinct(StringComparer.OrdinalIgnoreCase))
        {
            if (IsDdsPath(path))
            {
                var dds = DecodeDds(path);
                if (dds.Info is not null)
                {
                    set._ddsResources[path] = dds.Info;
                    if (dds.Bitmap is not null)
                    {
                        set._decoded[path] = dds.Bitmap;
                    }
                }
                else
                {
                    set._textureLoadFailures.Add(path);
                }
                continue;
            }
            if (!IsDecodableImagePath(path))
            {
                continue;
            }
            try
            {
                set._decoded[path] = new Bitmap(path);
            }
            catch
            {
                set._textureLoadFailures.Add(path);
            }
        }
        return set;
    }

    public Bitmap? BitmapForPath(string path)
    {
        return _decoded.TryGetValue(path, out var bitmap) ? bitmap : null;
    }

    public Color? AverageColorForPath(string path)
    {
        var bitmap = BitmapForPath(path);
        if (bitmap is null)
        {
            return null;
        }
        var stepX = Math.Max(1, bitmap.Width / 64);
        var stepY = Math.Max(1, bitmap.Height / 64);
        long a = 0;
        long r = 0;
        long g = 0;
        long b = 0;
        long count = 0;
        for (var y = 0; y < bitmap.Height; y += stepY)
        {
            for (var x = 0; x < bitmap.Width; x += stepX)
            {
                var color = bitmap.GetPixel(x, y);
                a += color.A;
                r += color.R;
                g += color.G;
                b += color.B;
                count++;
            }
        }
        if (count == 0)
        {
            return null;
        }
        return Color.FromArgb((int)(a / count), (int)(r / count), (int)(g / count), (int)(b / count));
    }

    public double AverageBrightnessForPath(string path)
    {
        var color = AverageColorForPath(path);
        return color is null ? 0.0 : ((color.Value.R + color.Value.G + color.Value.B) / (255.0 * 3.0));
    }

    public Bitmap? MaterialPreviewBitmap(string basePath, string normalPath, string specularPath, string roughnessPath, string metallicPath, string heightPath)
    {
        var baseBitmap = BitmapForPath(basePath);
        if (baseBitmap is null)
        {
            return null;
        }
        var key = string.Join("|", basePath, normalPath, specularPath, roughnessPath, metallicPath, heightPath);
        if (_materialPreviews.TryGetValue(key, out var cached))
        {
            return cached;
        }
        var normalBitmap = BitmapForPath(normalPath);
        var specularBitmap = BitmapForPath(specularPath);
        var roughnessBitmap = BitmapForPath(roughnessPath);
        var metallicBitmap = BitmapForPath(metallicPath);
        var heightBitmap = BitmapForPath(heightPath);
        var maxDimension = Math.Max(baseBitmap.Width, baseBitmap.Height);
        var scale = maxDimension > 1024 ? 1024.0 / maxDimension : 1.0;
        var width = Math.Max(1, (int)Math.Round(baseBitmap.Width * scale));
        var height = Math.Max(1, (int)Math.Round(baseBitmap.Height * scale));
        var preview = new Bitmap(width, height, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        var light = Normalize3(-0.35, -0.45, 0.82);
        var view = Normalize3(0.0, 0.0, 1.0);
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var u = width <= 1 ? 0.0 : x / (double)(width - 1);
                var v = height <= 1 ? 0.0 : y / (double)(height - 1);
                var baseColor = SampleBitmap(baseBitmap, u, v) ?? Color.Black;
                var normalColor = SampleBitmap(normalBitmap, u, v) ?? Color.FromArgb(255, 128, 128, 255);
                var specularColor = SampleBitmap(specularBitmap, u, v) ?? Color.FromArgb(255, 96, 96, 96);
                var roughnessColor = SampleBitmap(roughnessBitmap, u, v) ?? Color.FromArgb(255, 96, 96, 96);
                var metallicColor = SampleBitmap(metallicBitmap, u, v) ?? Color.FromArgb(255, 0, 0, 0);
                var heightColor = SampleBitmap(heightBitmap, u, v) ?? Color.FromArgb(255, 128, 128, 128);
                var normal = Normalize3((normalColor.R / 127.5) - 1.0, (normalColor.G / 127.5) - 1.0, (normalColor.B / 127.5) - 1.0);
                var ndotl = Math.Max(0.0, Dot(normal, light));
                var halfVector = Normalize3(light.X + view.X, light.Y + view.Y, light.Z + view.Z);
                var ndoth = Math.Max(0.0, Dot(normal, halfVector));
                var roughness = Math.Clamp((roughnessColor.R + roughnessColor.G + roughnessColor.B) / (255.0 * 3.0), 0.04, 1.0);
                var metallic = Math.Clamp((metallicColor.R + metallicColor.G + metallicColor.B) / (255.0 * 3.0), 0.0, 1.0);
                var heightGain = ((heightColor.R + heightColor.G + heightColor.B) / (255.0 * 3.0) - 0.5) * 0.12;
                var specStrength = Math.Clamp((specularColor.R + specularColor.G + specularColor.B) / (255.0 * 3.0), 0.0, 1.0);
                var specPower = Math.Clamp(96.0 - (roughness * 72.0), 8.0, 128.0);
                var diffuse = Math.Clamp(0.22 + ndotl * 0.86 + heightGain, 0.0, 1.3);
                var spec = Math.Pow(ndoth, specPower) * specStrength * (0.35 + metallic * 0.65);
                var r = Math.Clamp((int)Math.Round(baseColor.R * diffuse + 255.0 * spec), 0, 255);
                var g = Math.Clamp((int)Math.Round(baseColor.G * diffuse + 255.0 * spec), 0, 255);
                var b = Math.Clamp((int)Math.Round(baseColor.B * diffuse + 255.0 * spec), 0, 255);
                preview.SetPixel(x, y, Color.FromArgb(baseColor.A, r, g, b));
            }
        }
        _materialPreviews[key] = preview;
        return preview;
    }

    private static Color? SampleBitmap(Bitmap? bitmap, double u, double v)
    {
        if (bitmap is null || bitmap.Width <= 0 || bitmap.Height <= 0)
        {
            return null;
        }
        var x = Math.Clamp((int)Math.Round(u * (bitmap.Width - 1)), 0, bitmap.Width - 1);
        var y = Math.Clamp((int)Math.Round(v * (bitmap.Height - 1)), 0, bitmap.Height - 1);
        return bitmap.GetPixel(x, y);
    }

    private static (double X, double Y, double Z) Normalize3(double x, double y, double z)
    {
        var length = Math.Sqrt((x * x) + (y * y) + (z * z));
        return length <= 0.000001 ? (0.0, 0.0, 1.0) : (x / length, y / length, z / length);
    }

    private static double Dot((double X, double Y, double Z) a, (double X, double Y, double Z) b)
    {
        return (a.X * b.X) + (a.Y * b.Y) + (a.Z * b.Z);
    }

    public void Dispose()
    {
        foreach (var bitmap in _decoded.Values)
        {
            bitmap.Dispose();
        }
        _decoded.Clear();
        foreach (var bitmap in _materialPreviews.Values)
        {
            bitmap.Dispose();
        }
        _materialPreviews.Clear();
        _ddsResources.Clear();
        _textureLoadFailures.Clear();
    }

    private static bool IsDecodableImagePath(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || !File.Exists(value))
        {
            return false;
        }
        var extension = Path.GetExtension(value).ToLowerInvariant();
        return extension is ".png" or ".jpg" or ".jpeg" or ".bmp" or ".gif" or ".tif" or ".tiff";
    }

    private static bool IsDdsPath(string value)
    {
        return !string.IsNullOrWhiteSpace(value) && Path.GetExtension(value).Equals(".dds", StringComparison.OrdinalIgnoreCase);
    }

    private static (NetDdsTextureInfo? Info, Bitmap? Bitmap) DecodeDds(string path)
    {
        try
        {
            using var stream = File.OpenRead(path);
            using var reader = new BinaryReader(stream, Encoding.ASCII, leaveOpen: false);
            if (stream.Length < 128)
            {
                return (null, null);
            }
            var magic = reader.ReadBytes(4);
            if (magic.Length != 4 || magic[0] != (byte)'D' || magic[1] != (byte)'D' || magic[2] != (byte)'S' || magic[3] != (byte)' ')
            {
                return (null, null);
            }
            var headerSize = reader.ReadInt32();
            if (headerSize != 124)
            {
                return (null, null);
            }
            _ = reader.ReadInt32();
            var height = Math.Max(0, reader.ReadInt32());
            var width = Math.Max(0, reader.ReadInt32());
            _ = reader.ReadInt32();
            _ = reader.ReadInt32();
            var mipCount = Math.Max(1, reader.ReadInt32());
            stream.Position = 80;
            var pixelFlags = reader.ReadUInt32();
            var fourCcBytes = reader.ReadBytes(4);
            var fourCc = Encoding.ASCII.GetString(fourCcBytes).TrimEnd('\0', ' ');
            var rgbBitCount = reader.ReadInt32();
            var rMask = reader.ReadUInt32();
            var gMask = reader.ReadUInt32();
            var bMask = reader.ReadUInt32();
            var aMask = reader.ReadUInt32();
            var dxgiFormat = 0;
            var formatKey = fourCc;
            if (string.Equals(fourCc, "DX10", StringComparison.OrdinalIgnoreCase) && stream.Length >= 148)
            {
                stream.Position = 128;
                dxgiFormat = reader.ReadInt32();
                _ = reader.ReadInt32();
                _ = reader.ReadInt32();
                _ = reader.ReadInt32();
                _ = reader.ReadInt32();
                formatKey = DxgiDecodeKey(dxgiFormat);
                fourCc = $"DXGI_{dxgiFormat}";
            }
            var dataOffset = dxgiFormat != 0 ? 148 : 128;
            stream.Position = Math.Min(stream.Length, dataOffset);
            var data = reader.ReadBytes((int)Math.Max(0, stream.Length - stream.Position));
            var bitmap = DecodeDdsBitmap(width, height, formatKey, rgbBitCount, rMask, gMask, bMask, aMask, data)
                ?? DecodeDdsWithCdTextureDx(path)
                ?? DecodeDdsWithTexconv(path);
            return (new NetDdsTextureInfo(path, width, height, mipCount, fourCc, bitmap is not null), bitmap);
        }
        catch
        {
            return (null, null);
        }
    }

    private static Bitmap? DecodeDdsWithCdTextureDx(string path)
    {
        var converter = FindCdTextureDxExecutable();
        if (string.IsNullOrWhiteSpace(converter) || !File.Exists(converter))
        {
            return null;
        }
        var outputDir = Path.Combine(Path.GetTempPath(), "cdmw-dotnet-dds", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(outputDir);
        try
        {
            var outputPng = Path.Combine(outputDir, "preview.png");
            var jobPath = Path.Combine(outputDir, "job.json");
            var reportPath = Path.Combine(outputDir, "report.json");
            var job = new Dictionary<string, object?>
            {
                ["jobs"] = new[]
                {
                    new Dictionary<string, object?>
                    {
                        ["input"] = path,
                        ["output"] = outputPng,
                        ["slot"] = "dotnet_preview",
                        ["max_dimension"] = 4096,
                        ["srgb"] = true,
                        ["normal_space"] = string.Empty,
                    }
                }
            };
            File.WriteAllText(jobPath, JsonSerializer.Serialize(job), Encoding.UTF8);
            var start = new ProcessStartInfo
            {
                FileName = converter,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardError = true,
                RedirectStandardOutput = true,
            };
            start.ArgumentList.Add("batch-preview-json");
            start.ArgumentList.Add(jobPath);
            start.ArgumentList.Add(reportPath);
            using var process = Process.Start(start);
            if (process is null)
            {
                return null;
            }
            if (!process.WaitForExit(10000) || process.ExitCode != 0 || !File.Exists(outputPng))
            {
                return null;
            }
            using var decoded = new Bitmap(outputPng);
            return new Bitmap(decoded);
        }
        catch
        {
            return null;
        }
        finally
        {
            try
            {
                Directory.Delete(outputDir, recursive: true);
            }
            catch
            {
                // Best-effort temp cleanup.
            }
        }
    }

    private static Bitmap? DecodeDdsWithTexconv(string path)
    {
        var texconv = FindTexconvExecutable();
        if (string.IsNullOrWhiteSpace(texconv) || !File.Exists(texconv))
        {
            return null;
        }
        var outputDir = Path.Combine(Path.GetTempPath(), "cdmw-dotnet-dds", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(outputDir);
        try
        {
            var start = new ProcessStartInfo
            {
                FileName = texconv,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardError = true,
                RedirectStandardOutput = true,
            };
            start.ArgumentList.Add("-y");
            start.ArgumentList.Add("-ft");
            start.ArgumentList.Add("png");
            start.ArgumentList.Add("-o");
            start.ArgumentList.Add(outputDir);
            start.ArgumentList.Add(path);
            using var process = Process.Start(start);
            if (process is null)
            {
                return null;
            }
            if (!process.WaitForExit(10000) || process.ExitCode != 0)
            {
                return null;
            }
            var png = Directory.EnumerateFiles(outputDir, "*.png").FirstOrDefault();
            if (string.IsNullOrWhiteSpace(png) || !File.Exists(png))
            {
                return null;
            }
            using var decoded = new Bitmap(png);
            return new Bitmap(decoded);
        }
        catch
        {
            return null;
        }
        finally
        {
            try
            {
                Directory.Delete(outputDir, recursive: true);
            }
            catch
            {
                // Best-effort temp cleanup.
            }
        }
    }

    private static string FindCdTextureDxExecutable()
    {
        var env = Environment.GetEnvironmentVariable("CDMW_CD_TEXTURE_DX_EXE");
        var baseDir = AppContext.BaseDirectory;
        var candidates = new[]
        {
            env,
            Path.Combine(baseDir, "cd-texture-dx.exe"),
            Path.Combine(baseDir, "native", "cd-texture-dx.exe"),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "cd_texture_dx", "build", "Release", "cd-texture-dx.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "cd_texture_dx", "build", "Debug", "cd-texture-dx.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "native", "cd_texture_dx", "build", "Release", "cd-texture-dx.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "native", "cd_texture_dx", "build", "Debug", "cd-texture-dx.exe")),
        };
        foreach (var candidate in candidates)
        {
            if (!string.IsNullOrWhiteSpace(candidate) && File.Exists(candidate))
            {
                return candidate;
            }
        }
        return string.Empty;
    }

    private static string FindTexconvExecutable()
    {
        var env = Environment.GetEnvironmentVariable("CDMW_TEXCONV_EXE");
        var baseDir = AppContext.BaseDirectory;
        var candidates = new[]
        {
            env,
            Path.Combine(baseDir, "texconv.exe"),
            Path.Combine(baseDir, "native", "texconv.exe"),
            Path.Combine(baseDir, "native", "cd_texture_dx", "texconv.exe"),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "cd_texture_dx", "build", "bin", "Release", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "cd_texture_dx", "build", "bin", "Debug", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "cdmw_d3d11_preview", "build", "bin", "Release", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "cdmw_d3d11_preview", "build", "bin", "Debug", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "native", "cd_texture_dx", "build", "bin", "Release", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "native", "cd_texture_dx", "build", "bin", "Debug", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "native", "cdmw_d3d11_preview", "build", "bin", "Release", "texconv.exe")),
            Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "native", "cdmw_d3d11_preview", "build", "bin", "Debug", "texconv.exe")),
        };
        foreach (var candidate in candidates)
        {
            if (!string.IsNullOrWhiteSpace(candidate) && File.Exists(candidate))
            {
                return candidate;
            }
        }
        return string.Empty;
    }

    private static string DxgiDecodeKey(int dxgiFormat)
    {
        return dxgiFormat switch
        {
            28 or 29 => "RGBA8",
            49 => "RG8",
            56 => "R16",
            61 => "R8",
            70 or 71 => "BC1",
            72 or 73 => "BC2",
            74 or 75 => "BC3",
            76 or 77 => "BC4",
            80 or 83 => "BC5",
            87 or 91 => "BGRA8",
            88 or 93 => "BGRX8",
            _ => $"DXGI_{dxgiFormat}",
        };
    }

    private static Bitmap? DecodeDdsBitmap(int width, int height, string fourCc, int rgbBitCount, uint rMask, uint gMask, uint bMask, uint aMask, byte[] data)
    {
        if (width <= 0 || height <= 0 || data.Length == 0)
        {
            return null;
        }
        var normalized = (fourCc ?? string.Empty).Trim().ToUpperInvariant();
        return normalized switch
        {
            "DXT1" => DecodeBc1(width, height, data),
            "DXT3" => DecodeBc2(width, height, data),
            "DXT5" => DecodeBc3(width, height, data),
            "BC1" => DecodeBc1(width, height, data),
            "BC2" => DecodeBc2(width, height, data),
            "BC3" => DecodeBc3(width, height, data),
            "BC4" => DecodeBc4(width, height, data),
            "BC5" => DecodeBc5(width, height, data),
            "RGBA8" => DecodeRgba32(width, height, data),
            "BGRA8" => DecodeBgra32(width, height, data, opaqueAlpha: false),
            "BGRX8" => DecodeBgra32(width, height, data, opaqueAlpha: true),
            "R8" => DecodeR8(width, height, data),
            "RG8" => DecodeRg8(width, height, data),
            _ when rgbBitCount == 32 => DecodeUncompressed32(width, height, rMask, gMask, bMask, aMask, data),
            _ => null,
        };
    }

    private static Bitmap? DecodeBc1(int width, int height, byte[] data)
    {
        var pixels = new byte[width * height * 4];
        var blocksWide = Math.Max(1, (width + 3) / 4);
        var blocksHigh = Math.Max(1, (height + 3) / 4);
        var offset = 0;
        for (var by = 0; by < blocksHigh; by++)
        {
            for (var bx = 0; bx < blocksWide; bx++)
            {
                if (offset + 8 > data.Length)
                {
                    return BitmapFromBgra(width, height, pixels);
                }
                DecodeBcColorBlock(width, height, pixels, bx * 4, by * 4, data, offset, allowPunchThroughAlpha: true);
                offset += 8;
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeBc2(int width, int height, byte[] data)
    {
        var pixels = new byte[width * height * 4];
        var blocksWide = Math.Max(1, (width + 3) / 4);
        var blocksHigh = Math.Max(1, (height + 3) / 4);
        var offset = 0;
        for (var by = 0; by < blocksHigh; by++)
        {
            for (var bx = 0; bx < blocksWide; bx++)
            {
                if (offset + 16 > data.Length)
                {
                    return BitmapFromBgra(width, height, pixels);
                }
                DecodeBcColorBlock(width, height, pixels, bx * 4, by * 4, data, offset + 8, allowPunchThroughAlpha: false);
                for (var row = 0; row < 4; row++)
                {
                    var alphaRow = data[offset + (row * 2)] | (data[offset + (row * 2) + 1] << 8);
                    for (var col = 0; col < 4; col++)
                    {
                        var alpha4 = (alphaRow >> (col * 4)) & 0x0F;
                        SetAlpha(pixels, width, height, bx * 4 + col, by * 4 + row, (byte)((alpha4 << 4) | alpha4));
                    }
                }
                offset += 16;
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeBc3(int width, int height, byte[] data)
    {
        var pixels = new byte[width * height * 4];
        var blocksWide = Math.Max(1, (width + 3) / 4);
        var blocksHigh = Math.Max(1, (height + 3) / 4);
        var offset = 0;
        for (var by = 0; by < blocksHigh; by++)
        {
            for (var bx = 0; bx < blocksWide; bx++)
            {
                if (offset + 16 > data.Length)
                {
                    return BitmapFromBgra(width, height, pixels);
                }
                DecodeBcColorBlock(width, height, pixels, bx * 4, by * 4, data, offset + 8, allowPunchThroughAlpha: false);
                var alphas = Bc3AlphaPalette(data[offset], data[offset + 1]);
                ulong alphaBits = 0;
                for (var i = 0; i < 6; i++)
                {
                    alphaBits |= ((ulong)data[offset + 2 + i]) << (8 * i);
                }
                for (var row = 0; row < 4; row++)
                {
                    for (var col = 0; col < 4; col++)
                    {
                        var pixelIndex = row * 4 + col;
                        var alphaIndex = (int)((alphaBits >> (3 * pixelIndex)) & 0x07);
                        SetAlpha(pixels, width, height, bx * 4 + col, by * 4 + row, alphas[alphaIndex]);
                    }
                }
                offset += 16;
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeBc4(int width, int height, byte[] data)
    {
        var pixels = new byte[width * height * 4];
        var blocksWide = Math.Max(1, (width + 3) / 4);
        var blocksHigh = Math.Max(1, (height + 3) / 4);
        var offset = 0;
        for (var by = 0; by < blocksHigh; by++)
        {
            for (var bx = 0; bx < blocksWide; bx++)
            {
                if (offset + 8 > data.Length)
                {
                    return BitmapFromBgra(width, height, pixels);
                }
                var values = DecodeBc4Block(data, offset);
                for (var row = 0; row < 4; row++)
                {
                    for (var col = 0; col < 4; col++)
                    {
                        var value = values[row * 4 + col];
                        SetBgra(pixels, width, height, bx * 4 + col, by * 4 + row, value, value, value, 255);
                    }
                }
                offset += 8;
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeBc5(int width, int height, byte[] data)
    {
        var pixels = new byte[width * height * 4];
        var blocksWide = Math.Max(1, (width + 3) / 4);
        var blocksHigh = Math.Max(1, (height + 3) / 4);
        var offset = 0;
        for (var by = 0; by < blocksHigh; by++)
        {
            for (var bx = 0; bx < blocksWide; bx++)
            {
                if (offset + 16 > data.Length)
                {
                    return BitmapFromBgra(width, height, pixels);
                }
                var red = DecodeBc4Block(data, offset);
                var green = DecodeBc4Block(data, offset + 8);
                for (var row = 0; row < 4; row++)
                {
                    for (var col = 0; col < 4; col++)
                    {
                        var pixelIndex = row * 4 + col;
                        var rx = (red[pixelIndex] / 127.5) - 1.0;
                        var gy = (green[pixelIndex] / 127.5) - 1.0;
                        var bz = Math.Sqrt(Math.Max(0.0, 1.0 - (rx * rx) - (gy * gy)));
                        var blue = (byte)Math.Clamp((int)Math.Round((bz * 0.5 + 0.5) * 255.0), 0, 255);
                        SetBgra(pixels, width, height, bx * 4 + col, by * 4 + row, red[pixelIndex], green[pixelIndex], blue, 255);
                    }
                }
                offset += 16;
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static byte[] DecodeBc4Block(byte[] data, int offset)
    {
        var palette = Bc3AlphaPalette(data[offset], data[offset + 1]);
        ulong bits = 0;
        for (var i = 0; i < 6; i++)
        {
            bits |= ((ulong)data[offset + 2 + i]) << (8 * i);
        }
        var values = new byte[16];
        for (var i = 0; i < 16; i++)
        {
            values[i] = palette[(int)((bits >> (3 * i)) & 0x07)];
        }
        return values;
    }

    private static void DecodeBcColorBlock(int width, int height, byte[] pixels, int originX, int originY, byte[] data, int offset, bool allowPunchThroughAlpha)
    {
        var c0 = BitConverter.ToUInt16(data, offset);
        var c1 = BitConverter.ToUInt16(data, offset + 2);
        var palette = BcColorPalette(c0, c1, allowPunchThroughAlpha);
        var bits = BitConverter.ToUInt32(data, offset + 4);
        for (var row = 0; row < 4; row++)
        {
            for (var col = 0; col < 4; col++)
            {
                var index = (int)((bits >> (2 * (row * 4 + col))) & 0x03);
                var color = palette[index];
                SetBgra(pixels, width, height, originX + col, originY + row, color.R, color.G, color.B, color.A);
            }
        }
    }

    private static DdsColor[] BcColorPalette(ushort color0, ushort color1, bool allowPunchThroughAlpha)
    {
        var first = ColorFrom565(color0);
        var second = ColorFrom565(color1);
        var palette = new DdsColor[4];
        palette[0] = new DdsColor(first.R, first.G, first.B, 255);
        palette[1] = new DdsColor(second.R, second.G, second.B, 255);
        if (color0 > color1 || !allowPunchThroughAlpha)
        {
            palette[2] = new DdsColor((byte)((2 * first.R + second.R) / 3), (byte)((2 * first.G + second.G) / 3), (byte)((2 * first.B + second.B) / 3), 255);
            palette[3] = new DdsColor((byte)((first.R + 2 * second.R) / 3), (byte)((first.G + 2 * second.G) / 3), (byte)((first.B + 2 * second.B) / 3), 255);
        }
        else
        {
            palette[2] = new DdsColor((byte)((first.R + second.R) / 2), (byte)((first.G + second.G) / 2), (byte)((first.B + second.B) / 2), 255);
            palette[3] = new DdsColor(0, 0, 0, 0);
        }
        return palette;
    }

    private static DdsColor ColorFrom565(ushort value)
    {
        var r = (byte)((((value >> 11) & 0x1F) * 255 + 15) / 31);
        var g = (byte)((((value >> 5) & 0x3F) * 255 + 31) / 63);
        var b = (byte)(((value & 0x1F) * 255 + 15) / 31);
        return new DdsColor(r, g, b, 255);
    }

    private static byte[] Bc3AlphaPalette(byte alpha0, byte alpha1)
    {
        var alphas = new byte[8];
        alphas[0] = alpha0;
        alphas[1] = alpha1;
        if (alpha0 > alpha1)
        {
            for (var i = 1; i <= 6; i++)
            {
                alphas[i + 1] = (byte)(((7 - i) * alpha0 + i * alpha1) / 7);
            }
        }
        else
        {
            for (var i = 1; i <= 4; i++)
            {
                alphas[i + 1] = (byte)(((5 - i) * alpha0 + i * alpha1) / 5);
            }
            alphas[6] = 0;
            alphas[7] = 255;
        }
        return alphas;
    }

    private static Bitmap? DecodeRgba32(int width, int height, byte[] data)
    {
        if (data.Length < width * height * 4)
        {
            return null;
        }
        var pixels = new byte[width * height * 4];
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var offset = ((y * width) + x) * 4;
                SetBgra(pixels, width, height, x, y, data[offset], data[offset + 1], data[offset + 2], data[offset + 3]);
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeBgra32(int width, int height, byte[] data, bool opaqueAlpha)
    {
        if (data.Length < width * height * 4)
        {
            return null;
        }
        var pixels = new byte[width * height * 4];
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var sourceOffset = ((y * width) + x) * 4;
                var targetOffset = ((y * width) + x) * 4;
                pixels[targetOffset] = data[sourceOffset];
                pixels[targetOffset + 1] = data[sourceOffset + 1];
                pixels[targetOffset + 2] = data[sourceOffset + 2];
                pixels[targetOffset + 3] = opaqueAlpha ? (byte)255 : data[sourceOffset + 3];
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeR8(int width, int height, byte[] data)
    {
        if (data.Length < width * height)
        {
            return null;
        }
        var pixels = new byte[width * height * 4];
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var value = data[(y * width) + x];
                SetBgra(pixels, width, height, x, y, value, value, value, 255);
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeRg8(int width, int height, byte[] data)
    {
        if (data.Length < width * height * 2)
        {
            return null;
        }
        var pixels = new byte[width * height * 4];
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var offset = ((y * width) + x) * 2;
                SetBgra(pixels, width, height, x, y, data[offset], data[offset + 1], 128, 255);
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static Bitmap? DecodeUncompressed32(int width, int height, uint rMask, uint gMask, uint bMask, uint aMask, byte[] data)
    {
        if (data.Length < width * height * 4)
        {
            return null;
        }
        var pixels = new byte[width * height * 4];
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var sourceOffset = ((y * width) + x) * 4;
                var packed = BitConverter.ToUInt32(data, sourceOffset);
                var r = ExtractMaskedChannel(packed, rMask, defaultValue: 0);
                var g = ExtractMaskedChannel(packed, gMask, defaultValue: 0);
                var b = ExtractMaskedChannel(packed, bMask, defaultValue: 0);
                var a = ExtractMaskedChannel(packed, aMask, defaultValue: 255);
                SetBgra(pixels, width, height, x, y, r, g, b, a);
            }
        }
        return BitmapFromBgra(width, height, pixels);
    }

    private static byte ExtractMaskedChannel(uint packed, uint mask, byte defaultValue)
    {
        if (mask == 0)
        {
            return defaultValue;
        }
        var shift = 0;
        var shiftedMask = mask;
        while ((shiftedMask & 1) == 0)
        {
            shiftedMask >>= 1;
            shift++;
        }
        var value = (packed & mask) >> shift;
        return shiftedMask == 0 ? defaultValue : (byte)Math.Clamp((int)(value * 255 / shiftedMask), 0, 255);
    }

    private static void SetBgra(byte[] pixels, int width, int height, int x, int y, byte r, byte g, byte b, byte a)
    {
        if (x < 0 || y < 0 || x >= width || y >= height)
        {
            return;
        }
        var offset = ((y * width) + x) * 4;
        pixels[offset] = b;
        pixels[offset + 1] = g;
        pixels[offset + 2] = r;
        pixels[offset + 3] = a;
    }

    private static void SetAlpha(byte[] pixels, int width, int height, int x, int y, byte a)
    {
        if (x < 0 || y < 0 || x >= width || y >= height)
        {
            return;
        }
        pixels[((y * width) + x) * 4 + 3] = a;
    }

    private static Bitmap BitmapFromBgra(int width, int height, byte[] pixels)
    {
        var bitmap = new Bitmap(width, height, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        var rect = new Rectangle(0, 0, width, height);
        var locked = bitmap.LockBits(rect, System.Drawing.Imaging.ImageLockMode.WriteOnly, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        try
        {
            if (locked.Stride == width * 4)
            {
                Marshal.Copy(pixels, 0, locked.Scan0, pixels.Length);
            }
            else
            {
                for (var y = 0; y < height; y++)
                {
                    Marshal.Copy(pixels, y * width * 4, locked.Scan0 + y * locked.Stride, width * 4);
                }
            }
        }
        finally
        {
            bitmap.UnlockBits(locked);
        }
        return bitmap;
    }
}

internal readonly record struct DdsColor(byte R, byte G, byte B, byte A);

internal sealed record NetDdsTextureInfo(string Path, int Width, int Height, int MipCount, string FourCc, bool Decoded);

internal sealed record NetSubmeshMaterialBinding(
    int SubmeshIndex,
    int MaterialSlotIndex,
    string Material,
    string Texture,
    Dictionary<string, string> ResolvedChannels,
    Dictionary<string, string> PackageChannels);

internal readonly record struct Vec2(float U, float V);
internal readonly record struct Vec3(float X, float Y, float Z);
