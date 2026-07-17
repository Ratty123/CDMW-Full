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
    private const int ToolPanelWidth = 286;
    private static readonly UTF8Encoding Utf8NoBom = new(false);
    private static readonly Color ThemeWindowBackground = Color.FromArgb(15, 20, 26);
    private static readonly Color ThemePanelBackground = Color.FromArgb(21, 27, 35);
    private static readonly Color ThemeSectionBackground = Color.FromArgb(25, 32, 41);
    private static readonly Color ThemeInputBackground = Color.FromArgb(31, 39, 49);
    private static readonly Color ThemeButtonBackground = Color.FromArgb(36, 46, 58);
    private static readonly Color ThemeButtonHover = Color.FromArgb(47, 60, 75);
    private static readonly Color ThemeButtonPressed = Color.FromArgb(25, 32, 41);
    private static readonly Color ThemeButtonHighlight = Color.FromArgb(91, 108, 128);
    private static readonly Color ThemeButtonShadow = Color.FromArgb(8, 12, 17);
    private static readonly Color ThemeBorder = Color.FromArgb(62, 75, 91);
    private static readonly Color ThemeAccent = Color.FromArgb(92, 169, 255);
    private static readonly Color ThemeAccentHover = Color.FromArgb(116, 185, 255);
    private static readonly Color ThemeAccentPressed = Color.FromArgb(68, 132, 204);
    private static readonly Color ThemeText = Color.FromArgb(222, 232, 242);
    private static readonly Color ThemeMutedText = Color.FromArgb(151, 169, 186);
    private static readonly Color ThemeStatusBackground = Color.FromArgb(18, 25, 32);
    private readonly LaunchOptions _options;
    private readonly ObjDocument _document;
    private readonly MeshViewport _viewport;
    private readonly ListBox _submeshList = new();
    private readonly ListBox _actionHistoryList = new();
    private readonly NumericUpDown _translateStep = new();
    private readonly ComboBox _selectionTarget = new();
    private readonly ComboBox _selectionOperation = new();
    private readonly ComboBox _previewMode = new();
    private readonly CheckBox _xray = new();
    private Button? _wireColorButton;
    private Button? _vertexColorButton;
    private readonly NumericUpDown _wireOverlayWidth = new();
    private readonly NumericUpDown _vertexMarkerSize = new();
    private readonly CheckBox _partPick = new();
    private readonly NumericUpDown _radius = new();
    private readonly NumericUpDown _strength = new();
    private readonly ComboBox _falloff = new();
    private readonly Label _statusLabel = new();
    private readonly Label _fpsLabel = new();
    private readonly Label _controlsHintLabel = new();
    private readonly Dictionary<string, Button> _toolButtons = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Button> _gizmoButtons = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<Control> _meshEditOnlySections = new();
    private readonly List<Control> _placementOnlySections = new();
    private Panel? _toolPanel;
    private TableLayoutPanel? _editorLayout;
    private Button? _undoButton;
    private Button? _redoButton;
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
    private DateTime _lastEmbeddedHostMaintenanceUtc = DateTime.MinValue;
    private DateTime _lastEmbeddedCloseCheckUtc = DateTime.MinValue;
    private Size _pendingEmbeddedParentSize = Size.Empty;
    private long _pendingEmbeddedParentSizeTimestamp;
    private long _embeddedHostResizeDeferredCount;
    private long _embeddedHostResizeCoalescedCount;
    private long _embeddedHostResizeCommitCount;
    private DateTime _lastMetricsUiUtc = DateTime.MinValue;
    private DateTime _lastMetricsProtocolUtc = DateTime.MinValue;
    private string _lastMetricsUiText = string.Empty;
    private bool _meshEditInteractionActive;
    private bool _syncingOverlayAppearanceControls;
    private MeshOverlaySettings _overlaySettings = MeshOverlayPreferences.Load();

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
        _viewport.SetOverlaySettings(_overlaySettings);
        _viewport.SetGizmoAppearance(_gizmoAppearance);
        _viewport.ToolOptionsProvider = ToolOptionsPayload;
        _viewport.EditorEventRequested += HandleViewportEditorEvent;
        _viewport.StatusRequested += message => _statusLabel.Text = message;
        _viewport.TextureRegionCompleted += CompleteQueuedTextureRegionUpdate;
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
        _selectionTarget.SelectedIndexChanged += (_, _) => UpdateViewportControlsHint();
        _selectionOperation.SelectedIndexChanged += (_, _) => UpdateViewportControlsHint();
        ConfigureCheckBox(_xray, "X-Ray", isChecked: false);
        _xray.CheckedChanged += (_, _) =>
        {
            if (!_xray.Checked && _previewMode.SelectedIndex == 6)
            {
                _previewMode.SelectedIndex = 3;
                return;
            }
            _viewport.SetXRayEnabled(_xray.Checked);
            _statusLabel.Text = _xray.Checked
                ? "X-Ray enabled: visible and occluded topology is drawn without depth rejection; wire and vertex colors switch automatically."
                : "Visible-only selection enabled; picking uses the front surface.";
        };
        ConfigureNumeric(_radius, decimalPlaces: 1, minimum: 1, maximum: 512, value: 24, increment: 2);
        ConfigureNumeric(_strength, decimalPlaces: 2, minimum: 0, maximum: 1, value: 0.5M, increment: 0.05M);
        ConfigureCombo(_falloff, new object[] { "Smooth", "Linear", "Constant" }, selectedIndex: 0);

        _fpsLabel.AutoSize = false;
        _fpsLabel.Height = 22;
        _fpsLabel.ForeColor = ThemeMutedText;
        _fpsLabel.BackColor = ThemeStatusBackground;
        _fpsLabel.Dock = DockStyle.Top;
        _fpsLabel.TextAlign = ContentAlignment.MiddleRight;
        _fpsLabel.Text = "FPS -- | Frame -- ms";
        _statusLabel.AutoSize = false;
        _statusLabel.Height = 48;
        _statusLabel.ForeColor = ThemeText;
        _statusLabel.BackColor = ThemeStatusBackground;
        _statusLabel.Dock = DockStyle.Fill;
        _statusLabel.Text = $"Loaded package. materials={_materials.SlotCount} textureRefs={_materials.TextureReferenceCount} resolved={_materials.ExistingTextureFileCount}/{_materials.ResolvedTextureReferenceCount} decodable={_textureSet.DecodedCount}/{_materials.DecodableTextureFileCount}. Solid view is on; wire overlay is optional.";

        _toolPanel = BuildToolPanel();
        _toolPanel.Dock = DockStyle.Fill;
        _toolPanel.Margin = new Padding(0);
        _viewport.Margin = new Padding(0);
        _editorLayout = new TableLayoutPanel
        {
            Name = "DotNetMeshEditorLayout",
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            Margin = new Padding(0),
            Padding = new Padding(0),
        };
        _editorLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, _options.Embedded ? 0 : ToolPanelWidth));
        _editorLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _editorLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _toolPanel.Visible = !_options.Embedded;
        _editorLayout.Controls.Add(_toolPanel, 0, 0);
        _editorLayout.Controls.Add(BuildPresentationViewportRegion(), 1, 0);
        Controls.Add(_editorLayout);
        ApplyInteractionModeControls();

        StartFrameTimer();
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
                    var requiredFailures = _materials.FailedRequiredResources(_textureSet.TextureLoadFailures);
                    if (requiredFailures.Count > 0)
                    {
                        var message = "Required production texture resources failed: " + string.Join(
                            "; ",
                            requiredFailures.Select(resource =>
                                $"{resource.Role}[{resource.SubmeshIndex}].{resource.MaterialChannel}: {resource.Path}"));
                        _statusLabel.Text = message;
                        WriteProtocolEvent("textures_error", new Dictionary<string, object?>
                        {
                            ["message"] = message,
                            ["terminal"] = true,
                            ["required_resource_failures"] = requiredFailures.Select(resource => resource.ResourceId).ToArray(),
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
                    var optionalFailures = _materials.FailedOptionalResources(_textureSet.TextureLoadFailures);
                    _statusLabel.Text = $"Textures ready: {_textureSet.DecodedCount} decoded, {optionalFailures.Count} optional fallback(s).";
                    WriteProtocolEvent("textures_ready", new Dictionary<string, object?>
                    {
                        ["decoded_texture_resources"] = _textureSet.DecodedCount,
                        ["texture_load_failures"] = _textureSet.TextureLoadFailureCount,
                        ["optional_resource_failures"] = optionalFailures.Select(resource => new Dictionary<string, object?>
                        {
                            ["resource_id"] = resource.ResourceId,
                            ["channel"] = resource.MaterialChannel,
                            ["fallback_policy"] = resource.FallbackPolicy,
                        }).ToArray(),
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

    private Panel BuildToolPanel()
    {
        _submeshList.BackColor = ThemeInputBackground;
        _submeshList.ForeColor = ThemeText;
        _submeshList.BorderStyle = BorderStyle.FixedSingle;
        _submeshList.Height = 104;
        _submeshList.Font = new Font(Font.FontFamily, 8.5f);
        ApplyDarkScrollbars(_submeshList);
        _actionHistoryList.Name = "ResidentActionHistoryList";
        _actionHistoryList.BackColor = ThemeInputBackground;
        _actionHistoryList.ForeColor = ThemeText;
        _actionHistoryList.BorderStyle = BorderStyle.FixedSingle;
        _actionHistoryList.IntegralHeight = false;
        _actionHistoryList.SelectionMode = SelectionMode.None;
        _actionHistoryList.Height = 112;
        _actionHistoryList.Font = new Font(Font.FontFamily, 8.5f);
        _actionHistoryList.Items.Add("No edit actions yet");
        ApplyDarkScrollbars(_actionHistoryList);

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

        ConfigureCheckBox(_partPick, "Part Pick", isChecked: false);
        _partPick.CheckedChanged += (_, _) =>
        {
            _viewport.PartPickEnabled = _partPick.Checked;
            if (_partPick.Checked)
            {
                _selectionTarget.SelectedItem = "Part";
                _statusLabel.Text = "Part Pick enabled; selection requests target source parts.";
            }
            else
            {
                _statusLabel.Text = "Part Pick disabled; clearing selection.";
                WriteCommandRequest("clear_selection");
            }
        };
        var left = new Panel
        {
            Name = "DotNetMeshEditorToolPanel",
            Dock = DockStyle.Left,
            Width = ToolPanelWidth,
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

        var undoButton = CommandButton("Undo", "undo");
        var redoButton = CommandButton("Redo", "redo");
        _undoButton = undoButton;
        _redoButton = redoButton;
        undoButton.Enabled = false;
        redoButton.Enabled = false;
        _meshEditOnlySections.Add(AddSection(stack, "Mesh Edit Session",
            finish,
            ButtonRow(CommandButton("Clear Selection", "clear_selection"), CommandButton("Select All", "select_all")),
            ButtonRow(CommandButton("Invert", "invert"), undoButton, redoButton)));
        _meshEditOnlySections.Add(AddSection(stack, "Action History",
            new Label
            {
                Text = "Every applied mesh edit and selection change appears here. Undone actions remain visible for Redo.",
                AutoSize = true,
                MaximumSize = new Size(248, 0),
                ForeColor = ThemeMutedText,
                BackColor = ThemeSectionBackground,
                Margin = new Padding(0, 0, 0, 6)
            },
            _actionHistoryList));
        AddSection(stack, "Part Pick", _partPick);
        _meshEditOnlySections.Add(AddSection(stack, "Parts",
            _submeshList,
            ButtonRow(
                CommandButton("Show / Hide", "toggle_visibility"),
                CommandButton("Duplicate", "duplicate"),
                CommandButton("Delete", "delete"))));
        _meshEditOnlySections.Add(AddSection(stack, "Selection",
            new Label
            {
                Text = "Choose Vertex, Edge, Face, or Part; then click the mesh or drag a selection box. X-Ray selects through the mesh.",
                AutoSize = true,
                MaximumSize = new Size(248, 0),
                ForeColor = ThemeMutedText,
                BackColor = ThemeSectionBackground,
                Margin = new Padding(0, 0, 0, 6)
            },
            LabeledControl("Selection target", _selectionTarget),
            LabeledControl("Selection mode", _selectionOperation),
            _xray,
            ButtonRow(ToolButton("Select", "select"), CommandButton("Grow", "grow"), CommandButton("Shrink", "shrink"))));
        _placementOnlySections.Add(AddSection(stack, "Placement",
            SceneComparisonControl(),
            ButtonRow(GizmoButton("Move", "move"), GizmoButton("Rotate", "rotate"), GizmoButton("Scale", "scale"))));
        _meshEditOnlySections.Add(AddSection(stack, "Transform",
            LabeledControl("Translate step", _translateStep),
            ButtonRow(StyledActionButton("Move +X", () => RequestTransformMove((float)_translateStep.Value)), StyledActionButton("Move -X", () => RequestTransformMove(-(float)_translateStep.Value))),
            ButtonRow(ToolButton("Move", "move"), ToolButton("Grab", "grab"))));
        _meshEditOnlySections.Add(AddSection(stack, "Brush Tools",
            new Label
            {
                Text = "Brushes paint the replacement under the yellow circle; no preselection is required. Left-drag to apply. Right-drag pans; wheel zooms.",
                AutoSize = true,
                MaximumSize = new Size(248, 0),
                ForeColor = ThemeMutedText,
                BackColor = ThemeSectionBackground,
                Margin = new Padding(0, 0, 0, 6)
            },
            LabeledControl("Radius", _radius),
            LabeledControl("Strength", _strength),
            LabeledControl("Falloff", _falloff),
            ButtonRow(ToolButton("Smooth", "smooth"), ToolButton("Inflate", "inflate"), ToolButton("Pinch", "pinch"))));
        _meshEditOnlySections.Add(AddSection(stack, "Topology",
            ButtonRow(CommandButton("Subdivide", "subdivide"), CommandButton("Refine Smooth", "refine_smooth"))));
        AddSection(stack, "Viewport",
            PreviewModeControl(),
            OverlayAppearanceControls(),
            GizmoAppearanceControls(),
            ButtonRow(CameraButton("Front", "front"), CameraButton("Left", "left"), CameraButton("Right", "right")),
            ButtonRow(CameraButton("Back", "back"), CameraButton("Top", "top"), CameraButton("Bottom", "bottom")),
            ButtonRow(StyledActionButton("-15", () => _viewport.RotateYawDegrees(-15.0f)), StyledActionButton("+15", () => _viewport.RotateYawDegrees(15.0f)), StyledActionButton("Reset/Fit", _viewport.FrameMesh)),
            ToolButton("Orbit", "orbit"));

        left.Controls.Add(scroll);
        left.Controls.Add(statusFooter);
        ApplyInteractionModeControls();
        ResizeToolStack(scroll, stack);
        return left;
    }

    private Button GizmoButton(string text, string tool)
    {
        var button = StyledButton(text);
        _gizmoButtons[tool] = button;
        button.Click += (_, _) =>
        {
            _scene.SetGizmoTool(tool);
            RefreshGizmoButtonStates();
            _viewport.ApplySceneState();
            _statusLabel.Text = $"Placement gizmo: {text}. Left-drag the viewport or use the Builder placement values.";
        };
        return button;
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
        if (!string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase)
            && !string.Equals(command, "clear_selection", StringComparison.OrdinalIgnoreCase))
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
            ["falloff"] = SelectionText(_falloff, "smooth"),
            ["smooth_iterations"] = 3,
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
    private const uint PerformanceTimerResolutionMilliseconds = 1;

    [DllImport("winmm.dll", EntryPoint = "timeBeginPeriod")]
    private static extern uint TimeBeginPeriod(uint periodMilliseconds);

    [DllImport("winmm.dll", EntryPoint = "timeEndPeriod")]
    private static extern uint TimeEndPeriod(uint periodMilliseconds);

    private sealed class PerformanceRenderPumpState
    {
        public PerformanceRenderPumpState(MeshViewport owner, long generation, long minimumIntervalTicks)
        {
            Generation = generation;
            MinimumIntervalTicks = minimumIntervalTicks;
            UiCallback = () => owner.PumpPerformanceRenderFrameOnUiThread(this);
        }

        public long Generation { get; }
        public long MinimumIntervalTicks { get; }
        public Action UiCallback { get; }
        public long LastRequestTimestamp;
        public int Queued;
    }

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
    private bool _renderInvalidationQueued;
    private volatile bool _performanceRenderPumpActive;
    private System.Threading.Timer? _performanceRenderTimer;
    private PerformanceRenderPumpState? _performanceRenderPumpState;
    private long _performanceRenderPumpGeneration;
    private bool _performanceTimerResolutionRaised;
    private uint _performanceTimerResolutionBeginResult = uint.MaxValue;
    private readonly System.Windows.Forms.Timer _renderSurfaceResizeTimer = new() { Interval = 150 };
    private DateTime _dirtySinceUtc = DateTime.UtcNow;
    private int _hoverEdgeId = -1;
    private bool _edgeDragActive;
    private bool _placementDragActive;
    private string _selectionDragTargetMode = "edge";
    private Point _edgeDragStart;
    private Point _edgeDragCurrent;
    private D3D11MaterialViewport? _d3d11Viewport;
    private System.Windows.Forms.Integration.ElementHost? _gpuHost;
    private WpfGpuMeshViewport? _gpuViewport;
    private bool _rendererBlocked;
    private string _rendererBlockReason = string.Empty;
    private string _lastD3D11Error = string.Empty;
    private MeshOverlaySettings _overlaySettings = MeshOverlaySettings.Default;

    public RenderMetrics Metrics { get; } = new();
    public bool RendererBlocked => _rendererBlocked;
    public string RendererBlockReason => _rendererBlockReason;
    public string RendererBackend => _rendererBlocked ? "blocked_renderer_unavailable" : (_d3d11Viewport is not null ? "d3d11_vortice_shader" : (_gpuViewport is not null ? "wpf_viewport3d_gpu" : "winforms_gdi_fallback"));
    public int SelectedSubmeshIndex => _selectedSources.Count > 0 ? _selectedSources.Min() : -1;
    public int[] SelectedSubmeshIndices => _selectedSources.OrderBy(index => index).ToArray();
    public uint PerformanceTimerResolutionBeginResult => _performanceTimerResolutionBeginResult;
    public bool ShowSolid { get; private set; } = true;
    public bool ShowWire { get; private set; }
    public bool ShowVertices { get; private set; }
    public bool ShowXRay { get; private set; }
    public bool PartPickEnabled { get; set; }
    public bool TexturesEnabled { get; private set; } = true;
    public string DisplayMode { get; private set; } = "textured";
    public int MaterialDebugMode { get; set; }
    public string ActiveTool { get; set; } = "orbit";
    public Func<Dictionary<string, object?>>? ToolOptionsProvider { get; set; }
    public Action<string, Dictionary<string, object?>>? EditorEventRequested { get; set; }
    public Action<string>? StatusRequested { get; set; }
    public Action<NetTextureRegionUpdate, int, string>? TextureRegionCompleted { get; set; }
    public Action<int>? SubmeshSelectedRequested { get; set; }

    public bool ConsumeRenderRequest()
    {
        if (!_frameDirty)
        {
            return false;
        }
        _frameDirty = false;
        return true;
    }

    private void RequestFrame()
    {
        var captureActive = PreviewPerformanceCapture.IsActive;
        var allocatedBytesBefore = captureActive ? GC.GetAllocatedBytesForCurrentThread() : 0L;
        var started = captureActive ? Stopwatch.GetTimestamp() : 0L;
        if (!_frameDirty)
        {
            _dirtySinceUtc = DateTime.UtcNow;
        }
        _frameDirty = true;
        EnsureRenderScheduled();
        if (captureActive)
        {
            PreviewPerformanceCapture.RecordPhase(
                PreviewPerformancePhase.Invalidation,
                started,
                Stopwatch.GetTimestamp(),
                allocatedBytesBefore);
        }
    }

    private void RecordRenderedFrame(double frameMs, double presentMs, string deviceRemovedReason)
    {
        var dirtyToPresentMs = Math.Max(0.0, (DateTime.UtcNow - _dirtySinceUtc).TotalMilliseconds);
        Metrics.Record(frameMs, presentMs, dirtyToPresentMs, deviceRemovedReason);
        _dirtySinceUtc = DateTime.UtcNow;
    }

    public void StartPerformanceRenderPump(double targetHz)
    {
        var minimumIntervalTicks = Math.Max(
            1L,
            (long)Math.Round(Stopwatch.Frequency / Math.Clamp(targetHz, 1.0, 1000.0) * 0.9));
        var current = Volatile.Read(ref _performanceRenderPumpState);
        if (_performanceRenderPumpActive
            && current is not null
            && current.MinimumIntervalTicks == minimumIntervalTicks
            && Volatile.Read(ref _performanceRenderTimer) is not null)
        {
            return;
        }
        StopPerformanceRenderPump();
        _performanceTimerResolutionBeginResult = TimeBeginPeriod(PerformanceTimerResolutionMilliseconds);
        _performanceTimerResolutionRaised = _performanceTimerResolutionBeginResult == 0;
        var generation = Interlocked.Increment(ref _performanceRenderPumpGeneration);
        var pump = new PerformanceRenderPumpState(this, generation, minimumIntervalTicks);
        Volatile.Write(ref _performanceRenderPumpState, pump);
        _performanceRenderPumpActive = true;
        _performanceRenderTimer = new System.Threading.Timer(
            QueuePerformanceRenderFrame,
            pump,
            TimeSpan.Zero,
            TimeSpan.FromMilliseconds(1));
    }

    private void QueuePerformanceRenderFrame(object? state)
    {
        if (state is not PerformanceRenderPumpState pump
            || !_performanceRenderPumpActive
            || pump.Generation != Interlocked.Read(ref _performanceRenderPumpGeneration))
        {
            return;
        }
        var now = Stopwatch.GetTimestamp();
        var previous = Interlocked.Read(ref pump.LastRequestTimestamp);
        if (previous > 0 && now - previous < pump.MinimumIntervalTicks)
        {
            return;
        }
        if (Interlocked.CompareExchange(ref pump.Queued, 1, 0) != 0)
        {
            return;
        }
        try
        {
            BeginInvoke(pump.UiCallback);
        }
        catch (InvalidOperationException)
        {
            Interlocked.Exchange(ref pump.Queued, 0);
        }
    }

    private void PumpPerformanceRenderFrameOnUiThread(PerformanceRenderPumpState pump)
    {
        Interlocked.Exchange(ref pump.Queued, 0);
        if (!_performanceRenderPumpActive
            || pump.Generation != Interlocked.Read(ref _performanceRenderPumpGeneration)
            || IsDisposed
            || Disposing
            || _d3d11Viewport is not { IsDisposed: false } viewport)
        {
            return;
        }
        Interlocked.Exchange(ref pump.LastRequestTimestamp, Stopwatch.GetTimestamp());
        PreviewPerformanceCapture.RecordHeartbeat(PreviewPerformanceHeartbeatKind.WinForms);
        viewport.Invalidate();
    }

    public void StopPerformanceRenderPump()
    {
        _performanceRenderPumpActive = false;
        Interlocked.Increment(ref _performanceRenderPumpGeneration);
        Volatile.Write(ref _performanceRenderPumpState, null);
        Interlocked.Exchange(ref _performanceRenderTimer, null)?.Dispose();
        if (_performanceTimerResolutionRaised)
        {
            _performanceTimerResolutionRaised = false;
            _ = TimeEndPeriod(PerformanceTimerResolutionMilliseconds);
        }
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
        _renderSurfaceResizeTimer.Tick += OnRenderSurfaceResizeTimerTick;
        InitializeGpuViewport();
        FrameMesh();
        InitializePresentationContexts();
    }

}
