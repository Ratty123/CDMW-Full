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
    private const int ToolPanelSplitterWidth = 6;
    private const int MinimumViewportWidth = 240;
    private static readonly UTF8Encoding Utf8NoBom = new(false);
    // The workbench shell's "graphite" scheme, verbatim from
    // cdmw/ui/theme_schemes.py. The editor is embedded in that shell, so it has
    // to read as the same application rather than a second one.
    private static readonly Color ThemeWindowBackground = Color.FromArgb(30, 30, 30);      // #1e1e1e
    private static readonly Color ThemePanelBackground = Color.FromArgb(37, 37, 38);       // #252526
    private static readonly Color ThemeSectionBackground = Color.FromArgb(37, 37, 38);     // #252526
    private static readonly Color ThemeRailBackground = Color.FromArgb(45, 45, 48);        // #2d2d30
    private static readonly Color ThemeInputBackground = Color.FromArgb(31, 31, 31);       // #1f1f1f
    private static readonly Color ThemeButtonBackground = Color.FromArgb(45, 45, 48);      // #2d2d30
    private static readonly Color ThemeButtonHover = Color.FromArgb(55, 55, 61);           // #37373d
    private static readonly Color ThemeButtonPressed = Color.FromArgb(37, 37, 38);         // #252526
    private static readonly Color ThemeButtonBorder = Color.FromArgb(69, 73, 74);          // #45494a
    private static readonly Color ThemeBorder = Color.FromArgb(60, 60, 60);                // #3c3c3c
    private static readonly Color ThemeAccent = Color.FromArgb(0, 122, 204);               // #007acc
    private static readonly Color ThemeAccentHover = Color.FromArgb(28, 145, 224);
    private static readonly Color ThemeAccentPressed = Color.FromArgb(0, 90, 158);
    private static readonly Color ThemeText = Color.FromArgb(204, 204, 204);               // #cccccc
    private static readonly Color ThemeStrongText = Color.FromArgb(243, 243, 243);         // #f3f3f3
    private static readonly Color ThemeMutedText = Color.FromArgb(157, 160, 166);          // #9da0a6
    private static readonly Color ThemeStatusBackground = Color.FromArgb(30, 30, 30);      // #1e1e1e
    private readonly LaunchOptions _options;
    private ObjDocument _document;
    private readonly MeshViewport _viewport;
    private readonly ListBox _submeshList = new();
    private readonly ListBox _actionHistoryList = new();
    private readonly NumericUpDown _translateStep = new();
    private readonly ComboBox _selectionTarget = new();
    private readonly ComboBox _selectionOperation = new();
    private readonly ComboBox _previewMode = new();
    private bool _syncingPreviewModeSelection;
    private string _placementPreviewMode = "untextured_wire";
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
    private readonly ToolTip _helpToolTip = new()
    {
        AutoPopDelay = 20000,
        InitialDelay = 350,
        ReshowDelay = 100,
        ShowAlways = true,
    };
    private readonly Dictionary<string, Button> _toolButtons = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, Button> _gizmoButtons = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<Control> _meshEditOnlySections = new();
    private readonly List<Control> _placementOnlySections = new();
    private Panel? _leftToolPanel;
    private Panel? _rightToolPanel;
    private TableLayoutPanel? _leftToolStack;
    private TableLayoutPanel? _rightToolStack;
    private Control? _viewportHelpMarker;
    private SplitContainer? _leftToolSplit;
    private SplitContainer? _rightToolSplit;
    private Button? _undoButton;
    private Button? _redoButton;
    private NetMaterialSet _materials;
    private NetTextureSet _textureSet;
    private NetSceneState _scene;
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
    private bool _applyingToolPanelLayout;
    private MeshOverlaySettings _overlaySettings = MeshOverlayPreferences.Load();
    private MeshToolPanelLayout _toolPanelLayout = MeshToolPanelLayoutPreferences.Load();

    public ExperimentForm(LaunchOptions options, ObjDocument document, long sourceParseCount)
    {
        _options = options;
        _document = document;
        _sourceParseCount = Math.Max(0, sourceParseCount);
        _materials = NetMaterialSet.Load(options.MaterialsPath);
        _scene = NetSceneState.Load(options.ScenePath, document.Submeshes.Count);
        if (options.SimplePreview)
        {
            _scene.SetComparisonMode("replacement_only");
            _scene.SetPresentationOverlayVisibility(gridVisible: false, gizmoVisible: false);
        }
        _textureSet = NetTextureSet.Load(_materials);
        _ = _textureSet.LoadAsync(_materials);
        Text = "CDMW .NET Mesh Editor Experiment";
        Width = 1180;
        Height = 760;
        BackColor = ThemeWindowBackground;
        ForeColor = ThemeText;
        DoubleBuffered = true;
        SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
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
        InitializeResidentPackageProtocol();
        if (options.SimplePreview)
        {
            _overlaySettings = new MeshOverlaySettings(
                new MeshOverlayColors(Color.FromArgb(48, 60, 74), MeshOverlayColors.Default.Vertex),
                new MeshOverlaySizing(1.0f, MeshOverlaySizing.Default.VertexMarkerSizePixels));
            _ = _viewport.TrySetSynchronizedDisplayMode(
                _viewport.InitialResidentDisplayMode(HasResidentTextureResources()),
                out _);
        }
        _viewport.SetOverlaySettings(_overlaySettings);
        _viewport.ToolOptionsProvider = ToolOptionsPayload;
        _viewport.EditorEventRequested += HandleViewportEditorEvent;
        _viewport.StatusRequested += message => _statusLabel.Text = message;
        _viewport.TextureRegionCompleted += CompleteQueuedTextureRegionUpdate;
        _viewport.MouseDown += (_, _) => _viewport.Focus();
        _viewport.SubmeshSelectedRequested += _ => SyncSubmeshListSelection();
        _submeshList.Dock = DockStyle.Fill;
        _submeshList.IntegralHeight = false;
        // Both list sections size to their content in the dock columns, so the
        // list's own height is what the reader actually gets.
        _submeshList.Height = 150;
        _actionHistoryList.Height = 150;
        _actionHistoryList.IntegralHeight = false;
        _submeshList.HorizontalScrollbar = true;
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
            if (!_xray.Checked && _previewMode.SelectedIndex == 7)
            {
                _previewMode.SelectedIndex = 4;
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
        _fpsLabel.Height = Math.Max(24, Font.Height + 8);
        _fpsLabel.ForeColor = ThemeMutedText;
        _fpsLabel.BackColor = ThemeStatusBackground;
        _fpsLabel.Dock = DockStyle.Fill;
        _fpsLabel.TextAlign = ContentAlignment.MiddleRight;
        _fpsLabel.AutoEllipsis = true;
        _fpsLabel.Text = "FPS -- | Frame -- ms";
        _statusLabel.AutoSize = false;
        _statusLabel.Height = Math.Max(52, (Font.Height * 2) + 12);
        _statusLabel.ForeColor = ThemeText;
        _statusLabel.BackColor = ThemeStatusBackground;
        _statusLabel.Dock = DockStyle.Fill;
        _statusLabel.AutoEllipsis = true;
        _statusLabel.Text = $"Loaded package. materials={_materials.SlotCount} textureRefs={_materials.TextureReferenceCount} resolved={_materials.ExistingTextureFileCount}/{_materials.ResolvedTextureReferenceCount} decodable={_textureSet.DecodedCount}/{_materials.DecodableTextureFileCount}. Solid view is on; wire overlay is optional.";

        // Display state both profiles drive over the protocol, so it is
        // configured before the tool panels that merely present it.
        ConfigurePreviewModeCombo();

        // Roughly a second of WinForms layout that no embedded profile has on
        // screen while the host waits for its first frame: preview rejects every
        // authoring mutation so it can never uncollapse these, and an embedded
        // authoring host opens in placement mode with both flanks collapsed. A
        // standalone window shows them immediately, so it still builds up front.
        if (!DeferAuthoringToolPanels)
        {
            BuildAuthoringToolPanels();
        }
        _viewport.Margin = new Padding(0);
        _presentationViewportRegion = BuildPresentationViewportRegion();
        _rightToolSplit = CreateToolPanelSplit("DotNetMeshEditorViewportRightSplit", FixedPanel.Panel2);
        _leftToolSplit = CreateToolPanelSplit("DotNetMeshEditorLeftViewportSplit", FixedPanel.Panel1);
        if (_leftToolPanel is not null)
        {
            _leftToolSplit.Panel1.Controls.Add(_leftToolPanel);
        }
        _leftToolSplit.Panel2.Controls.Add(_rightToolSplit);
        InitializeEditMeshLayoutHost(_leftToolSplit);
        ConfigureToolPanelSplitters();
        if (options.SimplePreview)
        {
            // Both flanks are empty in this profile, so collapse them up front
            // instead of leaving the saved authoring widths as blank bands.
            // ApplySavedToolPanelLayout then correctly declines to restore them.
            _leftToolSplit.Panel1MinSize = 0;
            _rightToolSplit.Panel2MinSize = 0;
            _leftToolSplit.Panel1Collapsed = true;
            _rightToolSplit.Panel2Collapsed = true;
        }
        ApplySavedToolPanelLayout();
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
        ApplySavedToolPanelLayout();
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
            ["profile"] = _options.Profile,
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
        // The deferred authoring panels cost about a second of layout. Building
        // them here, once the first frame is out and ready has been published,
        // keeps that off both the startup path and the Edit Mesh click. The
        // mesh-edit entry point still calls the same builder, so an entry that
        // somehow beats this post is still correct.
        if (DeferAuthoringToolPanels && !_options.SimplePreview)
        {
            try
            {
                BeginInvoke(new Action(EnsureAuthoringToolPanelsReady));
            }
            catch (InvalidOperationException)
            {
                // No handle to post to; mesh-edit entry will build them.
            }
        }
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
        SaveToolPanelLayout();
        CancelResidentPackageLoad();
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

    /// <summary>
    /// True when the authoring tool panels can wait until the user actually
    /// enters mesh edit. Preview never builds them at all; an embedded
    /// authoring host opens in placement mode with both flanks collapsed, so it
    /// builds them on first entry instead of before its first frame.
    /// </summary>
    private bool DeferAuthoringToolPanels => _options.SimplePreview || _options.Embedded;

    private bool _authoringToolPanelsBuilt;

    private void BuildAuthoringToolPanels()
    {
        if (_options.SimplePreview || _authoringToolPanelsBuilt)
        {
            return;
        }
        _authoringToolPanelsBuilt = true;
        (_leftToolPanel, _rightToolPanel) = BuildToolPanels();
        _leftToolPanel.Dock = DockStyle.Fill;
        _leftToolPanel.Margin = new Padding(0);
        _rightToolPanel.Dock = DockStyle.Fill;
        _rightToolPanel.Margin = new Padding(0);
        // These panels are built long after the first RefreshSubmeshList, so
        // the Colour page would otherwise open with stale enablement and an
        // empty status line until the first selection change.
        LoadPartColourControls();
    }

    /// <summary>
    /// Build and attach the deferred authoring panels. Called the first time the
    /// scene enters mesh edit, which is the first moment the flanks uncollapse.
    /// </summary>
    private void EnsureAuthoringToolPanelsReady()
    {
        if (_options.SimplePreview || _authoringToolPanelsBuilt || _leftToolSplit is null)
        {
            return;
        }
        // This runs after the first frame, so the window is already on screen
        // and every attachment below would otherwise paint as it lands.
        using var redraw = BeginRedrawBatch();
        SuspendLayout();
        try
        {
            BuildAuthoringToolPanels();
            if (_leftToolPanel is not null)
            {
                _leftToolSplit.Panel1.Controls.Add(_leftToolPanel);
            }
            AttachPermanentToolModeHosts();
            AttachCompactSessionBar();
            ApplySavedToolPanelLayout();
        }
        finally
        {
            ResumeLayout(performLayout: false);
        }
    }

    private (Panel Left, Panel Right) BuildToolPanels()
    {
        _submeshList.BackColor = ThemeInputBackground;
        _submeshList.ForeColor = ThemeText;
        _submeshList.BorderStyle = BorderStyle.FixedSingle;
        _submeshList.Height = 112;
        _submeshList.Font = new Font(Font.FontFamily, 8.5f);
        ApplyDarkScrollbars(_submeshList);
        _actionHistoryList.Name = "ResidentActionHistoryList";
        _actionHistoryList.BackColor = ThemeInputBackground;
        _actionHistoryList.ForeColor = ThemeText;
        _actionHistoryList.BorderStyle = BorderStyle.FixedSingle;
        _actionHistoryList.IntegralHeight = false;
        _actionHistoryList.SelectionMode = SelectionMode.None;
        _actionHistoryList.Height = 124;
        _actionHistoryList.Font = new Font(Font.FontFamily, 8.5f);
        _actionHistoryList.Items.Add("No edit actions yet");
        ApplyDarkScrollbars(_actionHistoryList);

        var finish = StyledButton(_options.Embedded ? "Finish Edit Mesh" : "Save Edited Package", height: 30);
        finish.Click += (_, _) =>
        {
            if (_options.Embedded)
            {
                RequestFinishEditMesh();
            }
            else
            {
                SaveAndReport();
            }
        };
        _sessionFinishButton = finish;

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
        var left = CreateToolPanel(
            "DotNetMeshEditorLeftToolPanel",
            "DotNetMeshEditorLeftToolScroll",
            "DotNetMeshEditorLeftToolStack",
            _toolPanelLayout.LeftWidth,
            out var leftStack);
        var right = CreateToolPanel(
            "DotNetMeshEditorRightToolPanel",
            "DotNetMeshEditorRightToolScroll",
            "DotNetMeshEditorRightToolStack",
            _toolPanelLayout.RightWidth,
            out var rightStack);
        _leftToolStack = leftStack;
        _rightToolStack = rightStack;

        var clearSelectionButton = CommandButton("Clear Selection", "clear_selection");
        var selectAllButton = CommandButton("Select All", "select_all");
        var invertButton = CommandButton("Invert", "invert");
        var undoButton = CommandButton("Undo", "undo");
        var redoButton = CommandButton("Redo", "redo");
        _sessionClearSelectionButton = clearSelectionButton;
        _sessionSelectAllButton = selectAllButton;
        _sessionInvertButton = invertButton;
        _undoButton = undoButton;
        _redoButton = redoButton;
        undoButton.Enabled = false;
        redoButton.Enabled = false;
        _classicSessionSelectionRow = ButtonRow(clearSelectionButton, selectAllButton);
        _classicSessionHistoryRow = ButtonRow(invertButton, undoButton, redoButton);
        var classicLayoutToggleButton = StyledActionButton(
            "Use Tool Rail Layout",
            () => RequestEditMeshLayout(EditMeshLayoutMode.ToolRail));
        classicLayoutToggleButton.Name = "UseToolRailEditMeshLayoutButton";
        classicLayoutToggleButton.AccessibleName = "Use the tool rail Edit Mesh layout";
        classicLayoutToggleButton.AccessibleDescription =
            "Switches only the Edit Mesh control layout. The resident viewport and edit state remain active.";
        _classicSessionSection = AddSection(leftStack, "Mesh Edit Session",
            finish,
            _classicSessionSelectionRow,
            _classicSessionHistoryRow,
            classicLayoutToggleButton);
        _classicSessionSection.Name = "ClassicMeshEditSessionSection";
        _classicSessionBody = _classicSessionSection.Controls.OfType<TableLayoutPanel>().Single();
        _meshEditOnlySections.Add(_classicSessionSection);
        _actionHistorySection = AddHelpSection(
            rightStack,
            "Action History",
            "Every applied mesh edit and selection change appears here. Undone actions remain visible for Redo.",
            out _,
            _actionHistoryList);
        _actionHistorySection.Name = "CompactActionHistorySection";
        _meshEditOnlySections.Add(_actionHistorySection);
        _morphRefitSection = BuildMorphRefitSection(rightStack);
        _partPickSection = AddSection(leftStack, "Part Pick", _partPick);
        _partPickSection.Name = "CompactPartPickSection";
        var duplicatePartButton = CommandButton("Duplicate", "duplicate");
        var deletePartButton = CommandButton("Delete", "delete");
        RegisterTopologyMutationButton(duplicatePartButton);
        RegisterTopologyMutationButton(deletePartButton);
        _partsSection = AddSection(rightStack, "Parts",
            _submeshList,
            ButtonRow(
                CommandButton("Show / Hide", "toggle_visibility"),
                duplicatePartButton,
                deletePartButton));
        _partsSection.Name = "CompactPartsSection";
        _meshEditOnlySections.Add(_partsSection);
        var selectionSection = AddHelpSection(
            leftStack,
            "Selection",
            "Choose Vertex, Edge, Face, or Part; then click the mesh or drag a selection box. X-Ray selects through the mesh.",
            out _,
            LabeledControl("Selection target", _selectionTarget),
            LabeledControl("Selection mode", _selectionOperation),
            _xray,
            ButtonRow(ToolButton("Select", "select"), CommandButton("Grow", "grow"), CommandButton("Shrink", "shrink")));
        selectionSection.Name = "CompactSelectionSection";
        _selectionSection = selectionSection;
        _meshEditOnlySections.Add(selectionSection);
        _placementSection = AddSection(leftStack, "Placement",
            SceneComparisonControl(),
            ButtonRow(GizmoButton("Move", "move"), GizmoButton("Rotate", "rotate"), GizmoButton("Scale", "scale")));
        _placementSection.Name = "ClassicPlacementSection";
        _placementOnlySections.Add(_placementSection);
        var transformSection = AddHelpSection(
            leftStack,
            "Transform",
            "Move drags the current selection freely in screen space; Grab pulls vertices under the brush. "
            + "The axis buttons nudge the selection by the exact translate step.",
            out _,
            LabeledControl("Translate step", _translateStep),
            AxisNudgeRow("x"),
            AxisNudgeRow("y"),
            AxisNudgeRow("z"),
            ButtonRow(ToolButton("Move", "move"), ToolButton("Grab", "grab")));
        transformSection.Name = "CompactTransformSection";
        _transformSection = transformSection;
        _meshEditOnlySections.Add(transformSection);
        var brushSection = AddHelpSection(
            leftStack,
            "Brush Tools",
            "Brushes paint the replacement under the yellow circle; no preselection is required. Left-drag to apply. Right-drag pans; wheel zooms.",
            out _,
            LabeledControl("Radius", _radius),
            LabeledControl("Strength", _strength),
            LabeledControl("Falloff", _falloff),
            ButtonRow(ToolButton("Smooth", "smooth"), ToolButton("Inflate", "inflate"), ToolButton("Pinch", "pinch")));
        brushSection.Name = "CompactBrushSection";
        _brushSection = brushSection;
        _meshEditOnlySections.Add(brushSection);
        var subdivideButton = CommandButton("Subdivide", "subdivide");
        var refineButton = CommandButton("Refine Smooth", "refine_smooth");
        // Deleting and duplicating geometry is driven by the current selection
        // target, so it belongs beside the other topology edits. The Parts group
        // keeps its own pair for whole-part actions.
        var deleteSelectionButton = CommandButton("Delete Selection", "delete");
        var duplicateSelectionButton = CommandButton("Duplicate Selection", "duplicate");
        RegisterTopologyMutationButton(subdivideButton);
        RegisterTopologyMutationButton(refineButton);
        RegisterTopologyMutationButton(deleteSelectionButton);
        RegisterTopologyMutationButton(duplicateSelectionButton);
        var topologySection = AddHelpSection(
            leftStack,
            "Topology",
            "Acts on the current Selection target. Delete and Duplicate remove or copy the selected "
            + "vertices, edges, faces or parts; Subdivide and Refine Smooth add density.",
            out _,
            ButtonRow(deleteSelectionButton, duplicateSelectionButton),
            ButtonRow(subdivideButton, refineButton));
        topologySection.Name = "CompactTopologySection";
        _topologySection = topologySection;
        _meshEditOnlySections.Add(topologySection);
        var colourSection = BuildColourSection(leftStack);
        var leftNavigator = BuildToolNavigator(
            ("Select", selectionSection),
            ("Move", transformSection),
            ("Brush", brushSection),
            ("Topology", topologySection),
            ("Colour", colourSection));
        left.Controls.Add(leftNavigator);
        leftNavigator.BringToFront();
        _meshEditOnlySections.Add(leftNavigator);
        _viewportSection = AddHelpSection(
            rightStack,
            "Viewport",
            "Choose the preview mode, topology appearance, or a camera preset. Mouse and keyboard bindings update with the active tool.",
            out var viewportHelpMarker,
            PreviewModeControl(),
            OverlayAppearanceControls(),
            ButtonRow(CameraButton("Front", "front"), CameraButton("Left", "left"), CameraButton("Right", "right")),
            ButtonRow(CameraButton("Back", "back"), CameraButton("Top", "top"), CameraButton("Bottom", "bottom")),
            ButtonRow(StyledActionButton("-15", () => _viewport.RotateYawDegrees(-15.0f)), StyledActionButton("+15", () => _viewport.RotateYawDegrees(15.0f)), StyledActionButton("Reset/Fit", _viewport.FrameMesh)),
            ToolButton("Orbit", "orbit"));
        _viewportSection.Name = "CompactViewportSection";
        _viewportHelpMarker = viewportHelpMarker;

        return (left, right);
    }

    private static Panel CreateToolPanel(
        string panelName,
        string scrollName,
        string stackName,
        int width,
        out TableLayoutPanel stack)
    {
        var panel = new MeshEditorBufferedPanel
        {
            Name = panelName,
            Dock = DockStyle.Fill,
            Width = width,
            Padding = new Padding(0),
            TabStop = true,
            BackColor = ThemePanelBackground,
        };
        panel.MouseDown += (_, _) => panel.Focus();
        var scrollPanel = new MeshEditorBufferedPanel
        {
            Name = scrollName,
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Padding = new Padding(10, 8, 10, 8),
            BackColor = ThemePanelBackground,
        };
        ApplyDarkScrollbars(scrollPanel);
        var stackPanel = new MeshEditorBufferedTableLayoutPanel
        {
            Name = stackName,
            ColumnCount = 1,
            RowCount = 0,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Dock = DockStyle.Top,
            BackColor = ThemePanelBackground,
            Margin = new Padding(0),
            Padding = new Padding(0),
        };
        stackPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        scrollPanel.Controls.Add(stackPanel);
        panel.Controls.Add(scrollPanel);
        stack = stackPanel;
        return panel;
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
        // Also runs after an acknowledged material parameter update, so the
        // swatches re-read the exact host values rather than the local guess.
        LoadPartColourControls();
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
        LoadPartColourControls();
    }

    [DllImport("uxtheme.dll", CharSet = CharSet.Unicode)]
    private static extern int SetWindowTheme(IntPtr hWnd, string? pszSubAppName, string? pszSubIdList);

    private long WriteCommandRequest(string command, Dictionary<string, object?>? extraPayload = null)
    {
        if (!string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase)
            && !string.Equals(command, "clear_selection", StringComparison.OrdinalIgnoreCase))
        {
            _statusLabel.Text = "Placement mode: enable Edit Mesh to mutate geometry.";
            return 0;
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
        return _outgoingMutationRequestSequence;
    }

    private void RequestTransformMove(string axis, float step)
    {
        var normalized = (axis ?? "x").Trim().ToLowerInvariant();
        WriteCommandRequest("transform_move", new Dictionary<string, object?>
        {
            ["axis"] = normalized,
            ["step"] = step,
            ["delta"] = new[]
            {
                normalized == "x" ? step : 0.0f,
                normalized == "y" ? step : 0.0f,
                normalized == "z" ? step : 0.0f,
            }
        });
    }

    /// <summary>
    /// One signed pair of nudge buttons per axis. Dragging with the Move tool
    /// already moves the selection freely in screen space; these give the same
    /// motion an exact, repeatable step.
    /// </summary>
    private Control AxisNudgeRow(string axis)
    {
        var upper = axis.ToUpperInvariant();
        var minus = StyledActionButton(
            $"-{upper}",
            () => RequestTransformMove(axis, -(float)_translateStep.Value));
        var plus = StyledActionButton(
            $"+{upper}",
            () => RequestTransformMove(axis, (float)_translateStep.Value));
        minus.Name = $"TransformMoveMinus{upper}Button";
        plus.Name = $"TransformMovePlus{upper}Button";
        SetHelpText(minus, $"Move the selection one step along -{upper}.");
        SetHelpText(plus, $"Move the selection one step along +{upper}.");
        return ButtonRow(minus, plus);
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

    private ObjDocument _document;
    private NetMaterialSet _materials;
    private NetTextureSet _textureSet;
    private NetSceneState _scene;
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
    private bool _partPickEnabled;

    /// <summary>
    /// Also reported in view state, so a change has to reach the host rather
    /// than only the viewport.
    /// </summary>
    public bool PartPickEnabled
    {
        get => _partPickEnabled;
        set
        {
            if (_partPickEnabled == value)
            {
                return;
            }
            _partPickEnabled = value;
            NotifyViewStateChanged();
        }
    }

    public bool TexturesEnabled { get; private set; } = true;
    public string DisplayMode { get; private set; } = "textured";
    public int MaterialDebugMode { get; set; }
    private string _activeTool = "orbit";

    /// <summary>
    /// Changing the tool closes any stroke that is still open, so a gesture can
    /// never straddle two tools.
    /// </summary>
    public string ActiveTool
    {
        get => _activeTool;
        set
        {
            var next = value ?? "orbit";
            if (string.Equals(_activeTool, next, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }
            CancelActiveStroke();
            _activeTool = next;
            UpdateGpuViewport();
            Invalidate();
        }
    }
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
        _presentationGridVisible = scene.GridVisible;
        _presentationGizmoVisible = scene.GizmoVisible;
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
