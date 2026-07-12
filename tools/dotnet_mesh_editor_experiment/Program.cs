using System.Diagnostics;
using System.IO;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Numerics;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm : Form
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
    private readonly Dictionary<string, Button> _toolButtons = new(StringComparer.OrdinalIgnoreCase);
    private readonly NetMaterialSet _materials;
    private readonly NetTextureSet _textureSet;
    private readonly NetSceneState _scene;
    private readonly HashSet<int> _editedSubmeshes = new();
    private readonly System.Windows.Forms.Timer _timer = new();
    private bool _saved;
    private bool _externalTopologyDirty;
    private bool _embeddedViewportActive = true;
    private bool _embeddedHostFailed;
    private bool _readyPublished;
    private bool _readyPendingFirstFrame;
    private string _pendingTextureState = string.Empty;
    private string _pendingTextureError = string.Empty;
    private bool _syncingSubmeshListSelection;
    private DateTime _lastMetricsProtocolUtc = DateTime.MinValue;

    public ExperimentForm(LaunchOptions options, ObjDocument document, long sourceParseCount)
    {
        _options = options;
        _document = document;
        _sourceParseCount = Math.Max(0, sourceParseCount);
        _materials = NetMaterialSet.Load(options.MaterialsPath);
        _scene = NetSceneState.Load(options.ScenePath, document.Submeshes.Count);
        _textureSet = NetTextureSet.Load(_materials);
        _ = _textureSet.LoadAsync(_materials);
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

        _ = Handle;
        StartProtocolReader();

        _viewport = new MeshViewport(document, _materials, _textureSet, _scene, options) { Dock = DockStyle.Fill };
        _viewport.ToolOptionsProvider = ToolOptionsPayload;
        _viewport.EditorEventRequested += WriteProtocolEvent;
        _viewport.StatusRequested += message => _statusLabel.Text = message;
        _viewport.MouseDown += (_, _) => _viewport.Focus();
        _viewport.SubmeshSelectedRequested += _ => SyncSubmeshListSelection();
        _submeshList.Dock = DockStyle.Fill;
        _submeshList.IntegralHeight = false;
        _submeshList.SelectionMode = SelectionMode.MultiExtended;
        RefreshSubmeshList();
        _submeshList.SelectedIndexChanged += (_, _) =>
        {
            if (!_syncingSubmeshListSelection)
            {
                if (_submeshList.SelectedIndex >= 0)
                {
                    _selectionTarget.SelectedItem = "Part";
                }
                _viewport.SelectPartsFromList(_submeshList.SelectedIndices.Cast<int>());
            }
        };
        _submeshList.MouseDown += (_, eventArgs) =>
        {
            if (eventArgs.Button == MouseButtons.Left && _submeshList.IndexFromPoint(eventArgs.Location) == ListBox.NoMatches)
            {
                _submeshList.SelectedIndex = -1;
            }
        };

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

        var toolPanel = BuildToolPanel();
        toolPanel.Dock = DockStyle.Fill;
        toolPanel.Margin = new Padding(0);
        _viewport.Margin = new Padding(0);
        var editorLayout = new TableLayoutPanel
        {
            Name = "DotNetMeshEditorLayout",
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            Margin = new Padding(0),
            Padding = new Padding(0),
        };
        editorLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, toolPanel.Width));
        editorLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        editorLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        editorLayout.Controls.Add(toolPanel, 0, 0);
        editorLayout.Controls.Add(_viewport, 1, 0);
        Controls.Add(editorLayout);

        _timer.Interval = 16;
        _timer.Tick += (_, _) =>
        {
            if (_options.Embedded && _options.ParentHwnd > 0 && _embeddedViewportActive)
            {
                NativeWindowHost.ResizeToParent(this, new IntPtr(_options.ParentHwnd));
                if (File.Exists(_options.CloseRequestPath))
                {
                    Close();
                    return;
                }
            }
            if (!_embeddedViewportActive)
            {
                return;
            }
            var renderRequested = _viewport.ConsumeRenderRequest();
            if (renderRequested)
            {
                _viewport.Invalidate();
            }
            if (_readyPendingFirstFrame && _viewport.Metrics.HasRenderedFrame)
            {
                _readyPendingFirstFrame = false;
                PublishReady(_pendingTextureState, _pendingTextureError);
            }
            _fpsLabel.Text = RendererMetricsText(_viewport.Metrics, RendererStatusWithLifecycle(), renderRequested);
            if ((DateTime.UtcNow - _lastMetricsProtocolUtc).TotalMilliseconds >= 500)
            {
                _lastMetricsProtocolUtc = DateTime.UtcNow;
                var metricsPayload = MetricsPayload(_viewport.Metrics);
                metricsPayload["renderer"] = RendererStatusWithLifecycle();
                metricsPayload["lifecycle_counts"] = LifecycleCountsPayload();
                WriteProtocolEvent("metrics", metricsPayload);
            }
        };
        _timer.Start();
    }

    private void StartTextureLoad()
    {
        _initialTextureLoadCount++;
        _statusLabel.Text = "Loading textures before the resident editor becomes ready...";
        _ = _textureSet.LoadAsync(_materials).ContinueWith(task =>
        {
            if (IsDisposed || Disposing || !IsHandleCreated)
            {
                return;
            }
            try
            {
                BeginInvoke(new Action(() =>
                {
                    if (task.IsFaulted || task.IsCanceled)
                    {
                        var message = task.Exception?.GetBaseException().Message ?? "Texture load was cancelled.";
                        _statusLabel.Text = message;
                        WriteProtocolEvent("textures_error", new Dictionary<string, object?>
                        {
                            ["message"] = message,
                            ["terminal"] = true,
                            ["lifecycle_counts"] = LifecycleCountsPayload(),
                        });
                        PublishReady("error", message);
                        return;
                    }
                    var allSubmeshes = Enumerable.Range(0, _document.Submeshes.Count).ToArray();
                    if (!_viewport.TryApplyMaterialState(allSubmeshes, out var bindError))
                    {
                        _statusLabel.Text = bindError;
                        WriteProtocolEvent("textures_error", new Dictionary<string, object?>
                        {
                            ["message"] = bindError,
                            ["terminal"] = true,
                            ["renderer"] = RendererStatusWithLifecycle(),
                            ["lifecycle_counts"] = LifecycleCountsPayload(),
                        });
                        PublishReady("error", bindError);
                        return;
                    }
                    _statusLabel.Text = $"Textures ready: {_textureSet.DecodedCount} decoded, {_textureSet.TextureLoadFailureCount} failed.";
                    WriteProtocolEvent("textures_ready", new Dictionary<string, object?>
                    {
                        ["decoded_texture_resources"] = _textureSet.DecodedCount,
                        ["texture_load_failures"] = _textureSet.TextureLoadFailureCount,
                        ["renderer"] = RendererStatusWithLifecycle(),
                        ["lifecycle_counts"] = LifecycleCountsPayload(),
                    });
                    QueueReadyAfterFirstFrame("ready", string.Empty);
                }));
            }
            catch (InvalidOperationException)
            {
            }
        }, TaskScheduler.Default);
    }

    private void QueueReadyAfterFirstFrame(string textureState, string textureError)
    {
        _pendingTextureState = textureState;
        _pendingTextureError = textureError;
        _readyPendingFirstFrame = true;
        _statusLabel.Text = "Textures ready; drawing the first .NET/Vortice frame...";
        _viewport.ApplySceneState();
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        if (_options.Embedded && !TryEmbedOrFail("startup"))
        {
            return;
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
        var rendererStatus = RendererStatusWithLifecycle();
        WriteStatus(
            _options,
            _viewport.RendererBlocked ? "blocked_renderer_unavailable" : "loaded",
            _viewport.RendererBlocked ? _viewport.RendererBlockReason : "Mesh loaded in .NET editor experiment.",
            _viewport.Metrics,
            rendererStatus: rendererStatus);
        WriteProtocolEvent("ready", new Dictionary<string, object?>
        {
            ["capabilities"] = _viewport.ActiveCapabilities(),
            ["selection_depth_mode"] = "visible",
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
        if (NativeWindowHost.Embed(this, new IntPtr(_options.ParentHwnd)))
        {
            _statusLabel.Text = "Embedded .NET mesh editor ready.";
            Focus();
            _viewport.Focus();
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

    private Panel BuildToolPanel()
    {
        _submeshList.BackColor = ThemeInputBackground;
        _submeshList.ForeColor = ThemeText;
        _submeshList.BorderStyle = BorderStyle.FixedSingle;
        _submeshList.Height = 104;
        _submeshList.Font = new Font(Font.FontFamily, 8.5f);
        ApplyDarkScrollbars(_submeshList);

        var finish = StyledButton(_options.Embedded ? "Finish Edit Mesh" : "Save Edited Package", height: 30);
        finish.Click += (_, _) =>
        {
            if (_options.Embedded)
            {
                WriteProtocolEvent("save_request");
            }
            else
            {
                SaveAndReport();
            }
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
        var left = new Panel
        {
            Name = "DotNetMeshEditorToolPanel",
            Dock = DockStyle.Left,
            Width = 286,
            Padding = new Padding(0),
            TabStop = true,
            BackColor = ThemePanelBackground
        };
        left.MouseDown += (_, _) => left.Focus();
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
            Name = "DotNetMeshEditorToolScroll",
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Padding = new Padding(8),
            BackColor = ThemePanelBackground
        };
        ApplyDarkScrollbars(scroll);
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
            finish,
            ButtonRow(CommandButton("Clear Selection", "clear_selection"), CommandButton("Select All", "select_all")),
            ButtonRow(CommandButton("Invert", "invert"), CommandButton("Undo", "undo"), CommandButton("Redo", "redo")));
        AddSection(stack, "Parts",
            _submeshList,
            partPick,
            ButtonRow(
                CommandButton("Show / Hide", "toggle_visibility"),
                CommandButton("Duplicate", "duplicate"),
                CommandButton("Delete", "delete")));
        AddSection(stack, "Selection",
            LabeledControl("Selection target", _selectionTarget),
            LabeledControl("Selection mode", _selectionOperation),
            _xray,
            ButtonRow(ToolButton("Select", "select"), CommandButton("Grow", "grow"), CommandButton("Shrink", "shrink")));
        AddSection(stack, "Placement",
            SceneComparisonControl(),
            ButtonRow(GizmoButton("Move", "move"), GizmoButton("Rotate", "rotate"), GizmoButton("Scale", "scale")));
        AddSection(stack, "Transform",
            LabeledControl("Translate step", _translateStep),
            ButtonRow(StyledActionButton("Move +X", () => RequestTransformMove((float)_translateStep.Value)), StyledActionButton("Move -X", () => RequestTransformMove(-(float)_translateStep.Value))),
            ButtonRow(ToolButton("Move", "move"), ToolButton("Grab", "grab")));
        AddSection(stack, "Brush Tools",
            new Label
            {
                Text = "Choose a brush, then left-drag on the mesh. Right-drag pans; wheel zooms.",
                AutoSize = true,
                MaximumSize = new Size(248, 0),
                ForeColor = ThemeMutedText,
                BackColor = ThemeSectionBackground,
                Margin = new Padding(0, 0, 0, 6)
            },
            LabeledControl("Radius", _radius),
            LabeledControl("Strength", _strength),
            LabeledControl("Falloff", _falloff),
            ButtonRow(ToolButton("Smooth", "smooth"), ToolButton("Inflate", "inflate"), ToolButton("Pinch", "pinch")));
        AddSection(stack, "Topology",
            ButtonRow(CommandButton("Subdivide", "subdivide"), CommandButton("Refine Smooth", "refine_smooth")));
        AddSection(stack, "Viewport",
            PreviewModeControl(),
            MaterialDebugModeControl(),
            ButtonRow(CameraButton("Front", "front"), CameraButton("Left", "left"), CameraButton("Right", "right")),
            ButtonRow(CameraButton("Back", "back"), CameraButton("Top", "top"), CameraButton("Bottom", "bottom")),
            ButtonRow(StyledActionButton("-15", () => _viewport.RotateYawDegrees(-15.0f)), StyledActionButton("+15", () => _viewport.RotateYawDegrees(15.0f)), StyledActionButton("Reset/Fit", _viewport.FrameMesh)),
            ToolButton("Orbit", "orbit"));
        _toolButtons["orbit"].BackColor = ThemeAccent;

        left.Controls.Add(scroll);
        left.Controls.Add(statusFooter);
        ResizeToolStack(scroll, stack);
        return left;
    }

    private Control SceneComparisonControl()
    {
        var combo = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList };
        combo.Items.AddRange(new object[] { "Side by side", "Overlay", "Replacement only", "Original only" });
        combo.SelectedIndex = _scene.ComparisonMode switch
        {
            "side_by_side" => 0,
            "overlay" => 1,
            "original_only" => 3,
            _ => 2,
        };
        combo.SelectedIndexChanged += (_, _) =>
        {
            var mode = combo.SelectedIndex switch { 0 => "side_by_side", 1 => "overlay", 3 => "original_only", _ => "replacement_only" };
            _scene.SetComparisonMode(mode);
            _viewport.ApplySceneState();
            _statusLabel.Text = $"Comparison: {combo.SelectedItem}.";
        };
        return LabeledControl("Comparison", combo);
    }

    private Button GizmoButton(string text, string tool)
    {
        return StyledActionButton(text, () =>
        {
            _scene.SetGizmoTool(tool);
            _viewport.ApplySceneState();
            _statusLabel.Text = $"Placement gizmo: {text}. Left-drag the viewport or use the Builder placement values.";
        });
    }

    private static void ApplyDarkScrollbars(Control control)
    {
        void Apply() => _ = SetWindowTheme(control.Handle, "DarkMode_Explorer", null);
        control.HandleCreated += (_, _) => Apply();
        if (control.IsHandleCreated)
        {
            Apply();
        }
    }

    private void RefreshSubmeshList()
    {
        var selectedIndices = _viewport.SelectedSubmeshIndices.ToHashSet();
        _syncingSubmeshListSelection = true;
        _submeshList.BeginUpdate();
        try
        {
            _submeshList.Items.Clear();
            for (var index = 0; index < _scene.EditableSubmeshCount; index++)
            {
                var visibility = _materials.ParametersForSubmesh(index).Visible is false ? "hidden" : "shown";
                _submeshList.Items.Add($"{index}: {_document.Submeshes[index].Name} [{visibility}]");
            }
            for (var index = 0; index < _submeshList.Items.Count; index++)
            {
                _submeshList.SetSelected(index, selectedIndices.Contains(index));
            }
        }
        finally
        {
            _submeshList.EndUpdate();
            _syncingSubmeshListSelection = false;
        }
    }

    private void SyncSubmeshListSelection()
    {
        var selectedIndices = _viewport.SelectedSubmeshIndices.ToHashSet();
        _syncingSubmeshListSelection = true;
        try
        {
            for (var index = 0; index < _submeshList.Items.Count; index++)
            {
                _submeshList.SetSelected(index, selectedIndices.Contains(index));
            }
        }
        finally
        {
            _syncingSubmeshListSelection = false;
        }
    }

    [DllImport("uxtheme.dll", CharSet = CharSet.Unicode)]
    private static extern int SetWindowTheme(IntPtr hWnd, string? pszSubAppName, string? pszSubIdList);

    private void WriteCommandRequest(string command, Dictionary<string, object?>? extraPayload = null)
    {
        if (!string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase))
        {
            _statusLabel.Text = "Placement mode: enable Edit Mesh to mutate geometry.";
            return;
        }
        var targetMode = SelectionTarget();
        var payload = new Dictionary<string, object?>
        {
            ["command"] = command,
            ["target_mode"] = targetMode,
            ["selection_depth_mode"] = SelectionDepthMode(),
            ["local_selection"] = _viewport.SelectionSnapshotPayload()
        };
        if (extraPayload is not null)
        {
            foreach (var pair in extraPayload)
            {
                payload[pair.Key] = pair.Value;
            }
        }
        WriteProtocolEvent("command_request", payload);
    }

    private void RequestTransformMove(float deltaX)
    {
        WriteCommandRequest("transform_move", new Dictionary<string, object?>
        {
            ["axis"] = "x",
            ["step"] = deltaX,
            ["delta"] = new[] { deltaX, 0.0f, 0.0f }
        });
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

}

internal sealed partial class MeshViewport : Control
{
    private readonly ObjDocument _document;
    private readonly NetMaterialSet _materials;
    private readonly NetTextureSet _textureSet;
    private readonly NetSceneState _scene;
    private readonly LaunchOptions _options;
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
    private NetViewportCamera _camera;
    private Point _strokePrevious;
    private Point _pointerLocation;
    private bool _pointerInside;
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
    private bool _placementDragActive;
    private Point _placementDragStart;
    private Vector3 _placementStartTranslation;
    private Vector3 _placementStartRotation;
    private Vector3 _placementStartScale = Vector3.One;
    private string _selectionDragTargetMode = "edge";
    private Point _edgeDragStart;
    private Point _edgeDragCurrent;
    private D3D11MaterialViewport? _d3d11Viewport;
    private System.Windows.Forms.Integration.ElementHost? _gpuHost;
    private WpfGpuMeshViewport? _gpuViewport;
    private bool _rendererBlocked;
    private string _rendererBlockReason = string.Empty;
    private string _lastD3D11Error = string.Empty;

    public RenderMetrics Metrics { get; } = new();
    public bool RendererBlocked => _rendererBlocked;
    public string RendererBlockReason => _rendererBlockReason;
    public string RendererBackend => _rendererBlocked ? "blocked_renderer_unavailable" : (_d3d11Viewport is not null ? "d3d11_vortice_shader" : (_gpuViewport is not null ? "wpf_viewport3d_gpu" : "winforms_gdi_fallback"));
    public int SelectedSubmeshIndex => _selectedSources.Count > 0 ? _selectedSources.Min() : -1;
    public int[] SelectedSubmeshIndices => _selectedSources.OrderBy(index => index).ToArray();
    public bool ShowSolid { get; private set; } = true;
    public bool ShowWire { get; private set; }
    public bool ShowVertices { get; private set; }
    public bool ShowXRay { get; set; }
    public bool TexturesEnabled { get; private set; } = true;
    public string DisplayMode { get; private set; } = "textured";
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

    public MeshViewport(ObjDocument document, NetMaterialSet materials, NetTextureSet textureSet, NetSceneState scene, LaunchOptions options)
    {
        _document = document;
        _materials = materials;
        _textureSet = textureSet;
        _scene = scene;
        _options = options;
        DoubleBuffered = true;
        BackColor = Color.FromArgb(23, 25, 29);
        ForeColor = Color.White;
        Dock = DockStyle.Fill;
        TabStop = true;
        InitializeGpuViewport();
        FrameMesh();
    }

}
