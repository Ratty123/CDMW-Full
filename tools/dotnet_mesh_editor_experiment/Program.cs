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
    // Not readonly: the host window this form is embedded in is destroyed and
    // recreated by Qt when the app moves to a screen at a different scale, and
    // the replacement has a different HWND. See HandleReembedRequest.
    private LaunchOptions _options;
    private ObjDocument _document;
    private readonly MeshViewport _viewport;
    private readonly ListBox _submeshList = new();
    private readonly ListBox _actionHistoryList = new();
    private readonly NumericUpDown _translateStep = new();
    private readonly ComboBox _selectionTarget = new();
    private readonly ComboBox _selectionOperation = new();
    private readonly ComboBox _selectionShape = new();
    private readonly ComboBox _previewMode = new();
    private bool _syncingPreviewModeSelection;
    private string _placementPreviewMode = "untextured_wire";
    private readonly CheckBox _xray = new();
    private Button? _wireColorButton;
    private Button? _vertexColorButton;
    private Button? _selectionColorButton;
    private Button? _liveSelectionColorButton;
    private Button? _backgroundColorButton;
    private Button? _gridColorButton;
    private readonly NumericUpDown _wireOverlayWidth = new();
    private readonly NumericUpDown _vertexMarkerSize = new();
    private readonly CheckBox _partPick = new();
    private readonly NumericUpDown _radius = new();
    private readonly NumericUpDown _grabRadius = new();
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
    private long _embeddedParentHwnd;
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
    private bool _meshEditDisplayInitialized;
    private string _lastHostSelectionDragMode = "";
    private string _lastHostSelectionOperation = "";
    private bool _syncingOverlayAppearanceControls;
    private bool _applyingToolPanelLayout;
    private MeshOverlaySettings _overlaySettings = MeshOverlayPreferences.Load();
    private MeshViewportBackgroundColors _viewportColors = MeshViewportBackgroundPreferences.Load();
    private MeshToolPanelLayout _toolPanelLayout = MeshToolPanelLayoutPreferences.Load();

    private void ConfigureSubmeshList()
    {
    _submeshList.Dock = DockStyle.Fill;
    _submeshList.IntegralHeight = false;
    // Both list sections size to their content in the dock columns, so the
    // list's own height is what the reader actually gets.
    _submeshList.Height = 150;
    _actionHistoryList.Height = 150;
    _actionHistoryList.IntegralHeight = false;
    _submeshList.HorizontalScrollbar = true;
    // MultiSimple: a click toggles a part rather than replacing the selection.
    _submeshList.SelectionMode = SelectionMode.MultiSimple;
    RefreshSubmeshList();
    _submeshList.SelectedIndexChanged += (_, _) =>
    {
        if (!_syncingSubmeshListSelection)
        {
            _viewport.SelectPartsFromList(_submeshList.SelectedIndices.Cast<int>());
            ApplySelectedMorphRefitSettings();
        }
    };
    _submeshList.MouseDown += (_, eventArgs) =>
    {
        if (eventArgs.Button == MouseButtons.Left && _submeshList.IndexFromPoint(eventArgs.Location) == ListBox.NoMatches)
        {
            _submeshList.SelectedIndex = -1;
        }
    };
    }

    public ExperimentForm(LaunchOptions options, ObjDocument document, long sourceParseCount)
    {
        _options = options;
        _embeddedParentHwnd = options.ParentHwnd;
        _document = document;
        _sourceParseCount = Math.Max(0, sourceParseCount);
        _materials = NetMaterialSet.Load(options.MaterialsPath);
        _scene = NetSceneState.Load(options.ScenePath, document.Submeshes.Count);
        if (options.DirectAuthoring && options.Authoring)
        {
            _scene.SetInteractionMode("mesh_edit");
            _scene.SetComparisonMode("replacement_only");
        }
        if (options.SimplePreview)
        {
            _scene.SetComparisonMode("replacement_only");
            _scene.SetPresentationOverlayVisibility(gridVisible: false, gizmoVisible: false);
        }
        _textureSet = NetTextureSet.Load(_materials);
        _ = _textureSet.LoadAsync(_materials);
        StartupTiming.Mark("package_metadata_loaded");
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
        StartupTiming.Root = this;
        if (EmbedsAtBirth
            && NativeWindowHost.TryGetClientSize(new IntPtr(options.ParentHwnd), out var hostClientSize)
            && hostClientSize.Width >= 200
            && hostClientSize.Height >= 200)
        {
            // Take the host's size now, before a single child exists. The
            // startup realisation embeds and sizes this window again later, and
            // when that changed the size from the constructor's default it
            // re-laid out the whole finished tool tree at a new width: the most
            // expensive resize the editor ever does, spent on a window nobody
            // could see yet. Taking the final size first makes that a no-op.
            NativeWindowHost.ResizeToParent(this, new IntPtr(options.ParentHwnd), forceFrameRefresh: false, show: false);
        }
        StartupTiming.Mark("form_handle_created");
        if (!options.HeadlessSmoke)
        {
            StartProtocolReader();
            // From here on every startup mark is also a protocol event, so the
            // host can tell a helper that is still building from one that hung.
            StartupTiming.Reporter = (phase, atMs) => WriteProtocolEvent("startup_progress", new Dictionary<string, object?>
            {
                ["phase"] = phase,
                ["at_ms"] = Math.Round(atMs, 1),
            });
        }

        _viewport = new MeshViewport(document, _materials, _textureSet, _scene, options) { Dock = DockStyle.Fill };
        StartupTiming.Mark("viewport_created");
        InitializeResidentPackageProtocol();
        // A package booted from the command line may carry an effect particle
        // description beside its scene; a resident swap loads its own later.
        if (!options.HeadlessSmoke && !string.IsNullOrWhiteSpace(options.ScenePath))
        {
            _viewport.LoadEffectParticlePreview(Path.GetDirectoryName(options.ScenePath));
        }
        if (options.SimplePreview)
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
        _viewport.SetOverlaySettings(_overlaySettings);
        // Applied before the first frame, so a remembered background is what the
        // reader sees rather than the renderer default followed by a repaint.
        _viewport.SetViewportColorOverrides(_viewportColors.Background, _viewportColors.Grid);
        _viewport.ToolOptionsProvider = ToolOptionsPayload;
        _viewport.EditorEventRequested += HandleViewportEditorEvent;
        _viewport.StatusRequested += message => _statusLabel.Text = message;
        _viewport.MouseDown += (_, _) => _viewport.Focus();
        _viewport.SubmeshSelectedRequested += _ => SyncSubmeshListSelection();
        ConfigureSubmeshList();
        ConfigureNumeric(_translateStep, decimalPlaces: 4, minimum: -10, maximum: 10, value: 0.0100M, increment: 0.0100M);
        // Whole-part selection is owned only by the explicit PARTS list. The
        // viewport Select tool operates on one element domain at a time.
        ConfigureCombo(_selectionTarget, new object[] { "Vertices", "Wires", "Faces" }, selectedIndex: 0);
        // Add, not Replace: the reader paints a mesh region across several
        // gestures more often than they restart it.
        ConfigureCombo(_selectionOperation, new object[] { "Add", "Replace", "Subtract", "Toggle" }, selectedIndex: 0);
        // Brush is the drag-shape default, matching the host combo's default;
        // picking here drives the viewport directly, and the host's tool_state
        // only re-adopts the value when its own combo actually changes.
        ConfigureCombo(_selectionShape, new object[] { "Brush", "Rectangle", "Lasso" }, selectedIndex: 0);
        // ConfigureCombo assigns SelectedIndex before the handler below exists,
        // so the viewport never heard the default and stayed on its own
        // "rectangle" while the combo read "Brush".
        _viewport.SetSelectionDragMode(SelectionText(_selectionShape, "brush"));
        _selectionShape.SelectedIndexChanged += (_, _) =>
        {
            _viewport.SetSelectionDragMode(SelectionText(_selectionShape, "brush"));
            UpdateViewportControlsHint();
        };
        _selectionTarget.SelectedIndexChanged += (_, _) => UpdateViewportControlsHint();
        _selectionOperation.SelectedIndexChanged += (_, _) => UpdateViewportControlsHint();
        ConfigureCheckBox(_xray, "X-Ray", isChecked: false);
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
        ConfigureNumeric(_radius, decimalPlaces: 1, minimum: 1, maximum: 512, value: 24, increment: 2);
        ConfigureNumeric(_grabRadius, decimalPlaces: 1, minimum: 1, maximum: 512, value: 24, increment: 2);
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
        // One line, not two: the second line was empty for every message the
        // editor actually shows, and the row it reserved is height the viewport
        // and the tool columns need. Long messages ellipsize into the tooltip.
        _statusLabel.Height = Math.Max(26, Font.Height + 10);
        _statusLabel.ForeColor = ThemeText;
        _statusLabel.BackColor = ThemeStatusBackground;
        _statusLabel.Dock = DockStyle.Fill;
        _statusLabel.TextAlign = ContentAlignment.MiddleLeft;
        _statusLabel.AutoEllipsis = true;
        _statusLabel.TextChanged += (_, _) => _helpToolTip.SetToolTip(_statusLabel, _statusLabel.Text);
        _statusLabel.Text = $"Loaded package. materials={_materials.SlotCount} textureRefs={_materials.TextureReferenceCount} resolved={_materials.ExistingTextureFileCount}/{_materials.ResolvedTextureReferenceCount} decodable={_textureSet.DecodedCount}/{_materials.DecodableTextureFileCount}. Solid view is on; wire overlay is optional.";

        StartupTiming.Mark("basic_controls_configured");
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
        StartupTiming.Mark("presentation_region_built");
        _rightToolSplit = CreateToolPanelSplit("DotNetMeshEditorViewportRightSplit", FixedPanel.Panel2);
        _leftToolSplit = CreateToolPanelSplit("DotNetMeshEditorLeftViewportSplit", FixedPanel.Panel1);
        if (_leftToolPanel is not null)
        {
            _leftToolSplit.Panel1.Controls.Add(_leftToolPanel);
        }
        _leftToolSplit.Panel2.Controls.Add(_rightToolSplit);
        InitializeEditMeshLayoutHost(_leftToolSplit);
        StartupTiming.Mark("layout_host_initialized");
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
        StartupTiming.Mark("tool_panel_splitters_configured");
        ApplySavedToolPanelLayout();
        StartupTiming.Mark("saved_tool_panel_layout_applied");
        using (SuspendLayoutTree(_leftToolSplit))
        {
            // Booting into mesh edit moves every rail section into its page
            // here; one closing layout pass covers all of those moves.
            ApplyInteractionModeControls();
        }
        StartupTiming.Mark("interaction_mode_controls_applied");

        StartFrameTimer();
        StartupTiming.Mark("form_constructed");
    }

    private void StartTextureLoad()
    {
        _initialTextureLoadCount++;
        StartupTiming.Mark("texture_load_started");
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
                    var textureReadinessError = _materials.TextureReadinessError(_textureSet);
                    if (!string.IsNullOrWhiteSpace(textureReadinessError))
                    {
                        var message = textureReadinessError;
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
                    StartupTiming.Mark("textures_ready");
                    _statusLabel.Text = $"Textures ready: {_textureSet.DecodedCount} decoded, {optionalFailures.Count} optional fallback(s).";
                    WriteProtocolEvent("textures_ready", new Dictionary<string, object?>
                    {
                        ["decoded_texture_resources"] = _textureSet.DecodedCount,
                        ["texture_resources_ready"] = _viewport.HasTexturedMaterialResources,
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
        StartupTiming.Mark("ready_queued_for_first_frame");
        _statusLabel.Text = "Textures ready; drawing the first .NET/Vortice frame...";
        _viewport.ApplySceneState();
        // The reveal cannot wait for the frame itself — the frame is produced by
        // a paint, and a hidden window never gets one. This is as late as it can
        // go: geometry, materials and textures are all bound, so the first paint
        // draws the finished model rather than an empty viewport.
        //
        // A prewarm launch is the exception and must stay hidden. Its scene is a
        // procedural placeholder nobody asked to see; revealing it painted that
        // placeholder into the host pane and then hid it again the moment the
        // host answered `ready` with `deactivate_request` — a flash of the wrong
        // model at dialog-open time. The host does not need `ready` from a
        // prewarm (it warms the GPU with an offscreen capture instead), and
        // without a reveal there is no paint, so `ready` correctly stays pending
        // until `activate_request` reveals the window over a real package.
        if (!_options.PrewarmLaunch)
        {
            EnsureEmbeddedWindowRevealed();
        }
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        if (_startupRealizationQueued)
        {
            // An embedded window runs its startup while still hidden; this
            // OnShown is that startup's own reveal, not a second entry.
            return;
        }
        RunStartupRealization();
    }

    /// <summary>
    /// Everything between a built form and a window the user should be looking
    /// at. Embedded, this runs hidden (see <see cref="SetVisibleCore"/>) and the
    /// reveal is deferred to the texture load's completion; standalone, it runs
    /// from OnShown as before.
    /// </summary>
    /// <remarks>
    /// The reveal used to sit here, before <see cref="StartTextureLoad"/>, which
    /// meant the host pane showed a fully built but untextured editor for the
    /// whole texture decode — the chrome arriving seconds before the model, read
    /// as the editor loading in stages. It sat here because it had to: the D3D11
    /// device was created by the first paint, a hidden window never paints, and
    /// <c>TryApplyMaterialState</c> fails outright without a device. Initialising
    /// the renderer explicitly breaks that dependency, so the window can stay
    /// hidden until there is a finished picture to show.
    /// </remarks>
    private void RunStartupRealization()
    {
        _startupRealizationQueued = true;
        StartupTiming.Mark("startup_realization_begin");
        // Build the expensive authoring tree while the Qt host still shows its
        // loading surface. Besides moving the cost off the Edit Mesh click,
        // this ensures the first visible WinForms frame contains one settled
        // layout instead of controls being attached and repainted in stages.
        if (DeferAuthoringToolPanels && !_options.SimplePreview)
        {
            EnsureAuthoringToolPanelsReady();
        }
        StartupTiming.Mark("authoring_tool_panels_ready");
        bool rendererInitialized;
        using (SuspendLayoutTree(_leftToolSplit))
        {
            // Handle creation and the embed both re-lay out the flanks, and the
            // window is still hidden; one pass when this closes is enough.
            //
            // Must precede the reveal: no layout switch may be the first
            // realisation of its subtree, and none of that realisation should be
            // something the user watches happen.
            RealizeClassicToolFlanks();
            StartupTiming.Mark("classic_tool_flanks_realized");
            if (_options.Embedded && !TryEmbedOrFail("startup"))
            {
                return;
            }
            StartupTiming.Mark("embedded_in_host");
            ApplySavedToolPanelLayout();
            StartupTiming.Mark("embedded_and_layout_applied");
            // EnsureRendererInitialized needs the viewport's handle, and nothing has
            // forced it while the form is hidden.
            RealizeControlTree(_viewport);
            StartupTiming.Mark("viewport_handles_realized");
            rendererInitialized = _viewport.EnsureRendererInitialized();
            StartupTiming.Mark("renderer_ensured");
        }
        StartupTiming.Mark("startup_realization_layout_settled");
        if (!rendererInitialized)
        {
            // Not fatal, and not worth blocking the reveal over: the first paint
            // still creates the device the way it always did, and a renderer that
            // genuinely cannot start reports through the texture/ready path.
            WriteProtocolEvent("renderer_prewarm_skipped", new Dictionary<string, object?>
            {
                ["reason"] = _viewport.RendererBlocked ? _viewport.RendererBlockReason : "device not ready before reveal",
                ["embedded"] = _options.Embedded,
                ["prewarm_launch"] = _options.PrewarmLaunch,
            });
            if (!_options.PrewarmLaunch)
            {
                EnsureEmbeddedWindowRevealed();
            }
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
        // Every terminal texture failure publishes ready directly, without ever
        // reaching QueueReadyAfterFirstFrame. Without this the editor would stay
        // hidden behind the host's spinner with the error only in a status line
        // nobody can see. A failed prewarm still stays hidden: nobody asked to
        // see it, and the host simply launches again for the real package.
        if (!_options.PrewarmLaunch)
        {
            EnsureEmbeddedWindowRevealed();
        }
        var rendererStatus = RendererStatusWithLifecycle();
        WriteStatus(
            _options,
            _viewport.RendererBlocked ? "blocked_renderer_unavailable" : "loaded",
            _viewport.RendererBlocked ? _viewport.RendererBlockReason : "Mesh loaded in .NET editor experiment.",
            _viewport.Metrics,
            rendererStatus: rendererStatus);
        StartupTiming.Mark("ready_published");
        WriteProtocolEvent("startup_timing", StartupTiming.Payload(this));
        StartupTiming.Seal();
        WriteProtocolEvent("ready", new Dictionary<string, object?>
        {
            ["capabilities"] = _viewport.ActiveCapabilities(),
            ["profile"] = _options.Profile,
            ["selection_depth_mode"] = "visible",
            ["tool_enabled"] = !string.Equals(_viewport.ActiveTool, "orbit", StringComparison.OrdinalIgnoreCase),
            ["tool"] = _viewport.ActiveTool,
            ["target_mode"] = _viewport.CurrentTargetMode(),
            ["selection_mode"] = SelectionText(_selectionShape, "brush"),
            ["selection_operation"] = SelectionOperation(),
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
        // Before the first reveal this only verifies and sizes the window the
        // constructor already created inside the host; forcing it on screen
        // here is what RevealEmbeddedWindow is for.
        if (NativeWindowHost.Embed(this, new IntPtr(_options.ParentHwnd), reveal: _embeddedWindowRevealed))
        {
            _statusLabel.Text = "Embedded .NET mesh editor ready.";
            if (_embeddedWindowRevealed)
            {
                Focus();
                _viewport.Focus();
            }
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
    /// True when the constructor may defer authoring panels. Preview never
    /// builds them; an embedded authoring host builds them during hidden startup
    /// instead of making the constructor or first Edit Mesh click pay the cost.
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
    /// Build and attach the deferred authoring panels. Embedded startup calls
    /// this while hidden; mesh-edit entry remains an idempotent backstop.
    /// </summary>
    private void EnsureAuthoringToolPanelsReady()
    {
        if (_options.SimplePreview || _authoringToolPanelsBuilt || _leftToolSplit is null)
        {
            return;
        }
        // The redraw batch is also required for the entry backstop, where the
        // window may already be visible.
        using var redraw = BeginRedrawBatch();
        SuspendLayout();
        // Deep, not just the form: every attach, re-parent and dock change below
        // otherwise lays out the freshly built flanks again, and there is no
        // screen to keep current while this runs.
        using var layouts = SuspendLayoutTree(_leftToolSplit, _rightToolSplit, _editMeshLayoutHost);
        try
        {
            BuildAuthoringToolPanels();
            layouts.Include(_leftToolPanel);
            layouts.Include(_rightToolPanel);
            StartupTiming.Mark("authoring_tool_panels_built");
            if (_leftToolPanel is not null)
            {
                _leftToolSplit.Panel1.Controls.Add(_leftToolPanel);
            }
            StartupTiming.Mark("left_tool_panel_attached");
            AttachPermanentToolModeHosts();
            layouts.Include(_leftToolModeHost);
            layouts.Include(_rightToolModeHost);
            StartupTiming.Mark("permanent_tool_mode_hosts_attached");
            AttachCompactSessionBar();
            layouts.Include(_compactSessionBar);
            PrimeToolRailSectionOwnership();
            StartupTiming.Mark("tool_rail_sections_primed");
            ApplySavedToolPanelLayout();
        }
        finally
        {
            ResumeLayout(performLayout: false);
        }
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
            Padding = new Padding(8, 6, 8, 8),
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
                _submeshList.Items.Add(DescribePartRow(index));
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
        ApplySelectedMorphRefitSettings();
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
        var normalizedCommand = (command ?? string.Empty).Trim().ToLowerInvariant();
        var topologyCanWaitForSelection = normalizedCommand is "subdivide" or "refine_smooth"
            && _viewport.HasPendingSelectionAuthority;
        if (normalizedCommand is "transform_move" or "delete" or "duplicate" or "subdivide" or "refine_smooth" or "copy"
            && !_viewport.HasEditableSelection
            && !topologyCanWaitForSelection)
        {
            _statusLabel.Text = normalizedCommand == "transform_move"
                ? "Move requires a selection. Use Select in the viewport or choose a part under PARTS."
                : "This topology command requires a viewport mesh selection or an explicit PARTS selection.";
            return 0;
        }
        var targetMode = SelectionTarget();
        var payload = new Dictionary<string, object?>
        {
            ["command"] = command,
            ["target_mode"] = targetMode,
            ["selection_depth_mode"] = SelectionDepthMode(),
        };
        if (topologyCanWaitForSelection)
        {
            // The visible brush/lasso result is still provisional. Sending the
            // previous authoritative snapshot here would make the host queue
            // the right command for the wrong faces. The host waits for the
            // selection terminal and then executes against resident authority.
            payload["selection_pending"] = true;
        }
        else
        {
            payload["local_selection"] = _viewport.SelectionSnapshotPayload();
        }
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
        var activeTool = (_viewport.ActiveTool ?? string.Empty).Trim().ToLowerInvariant();
        return new Dictionary<string, object?>
        {
            ["target_mode"] = SelectionTarget(),
            ["operation"] = SelectionOperation(),
            ["selection_depth_mode"] = SelectionDepthMode(),
            ["radius"] = (double)(activeTool == "grab" ? _grabRadius.Value : _radius.Value),
            ["strength"] = (double)_strength.Value,
            ["falloff"] = SelectionText(_falloff, "smooth"),
            ["smooth_iterations"] = 3,
        };
    }

    private string SelectionTarget()
    {
        return SelectionText(_selectionTarget, "vertices") switch
        {
            "wires" => "edge",
            "faces" => "face",
            _ => "vertex",
        };
    }

    private string SelectionOperation()
    {
        return SelectionText(_selectionOperation, "add");
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
    private Point _strokeProtocolPrevious;
    private long _strokeLastProtocolTicks;
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
    private string _selectionDragTargetMode = "vertex";
    // How a Select drag resolves: brush paint (default), rectangle, or lasso.
    // Matches the Select shape combo's own default, so the two agree before
    // anything has been picked. Host state from the builder's Selection combo
    // via tool_state.
    private string _selectionDragMode = "brush";
    // Instant local echo of a paint/click selection, drawn until the
    // authoritative native result lands (~one protocol round trip later).
    private readonly Dictionary<int, HashSet<int>> _provisionalSelectedVertices = new();
    private readonly Dictionary<int, HashSet<int>> _provisionalSelectedFaces = new();
    private readonly HashSet<int> _provisionalSelectedEdges = new();
    private readonly HashSet<int> _provisionalSelectedSources = new();
    private bool _provisionalPartSelectionActive;
    private bool _selectionPaintActive;
    private bool _selectionPaintPainted;
    private string _selectionPaintFirstOperation = "add";
    private string _selectionPaintOperation = "add";
    // Toggle is a gesture operation: crossing the same vertex twice in one
    // Brush stroke must not toggle it back off. The final exact vertex set is
    // published once, so the host records one selection-history entry.
    private readonly HashSet<(int SubmeshIndex, int VertexIndex)> _selectionPaintToggleTouchedVertices = new();
    private readonly HashSet<(int SubmeshIndex, int FaceIndex)> _selectionPaintToggleTouchedFaces = new();
    private readonly HashSet<int> _selectionPaintToggleTouchedEdges = new();
    private Point _selectionPaintLastSample;
    // Where the local tint has been painted up to. It runs ahead of
    // _selectionPaintLastSample, which is where the host was last asked for an
    // authoritative result.
    private Point _selectionPaintLastEcho;
    private long _selectionPaintLastSampleTicks;
    private readonly List<Point> _selectionPaintPathPoints = new();
    private readonly List<Point> _selectionLassoPoints = new();
    private string _selectionStrokeId = string.Empty;
    private long _selectionStrokeSequence;
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

    /// <summary>
    /// The parts a vertex or face selection sits on, for tools that act per
    /// part but should still follow a sub-part selection rather than going dead.
    /// </summary>
    public int[] SubmeshIndicesTouchedBySelection =>
        _selectedVertices.Concat(_selectedFaces)
            .Where(pair => pair.Value.Count > 0)
            .Select(pair => pair.Key)
            .Distinct()
            .OrderBy(index => index)
            .ToArray();

    /// <summary>True when the selection is a sub-region rather than whole parts.</summary>
    public bool HasSubPartSelection =>
        _selectedVertices.Any(pair => pair.Value.Count > 0)
        || _selectedFaces.Any(pair => pair.Value.Count > 0);

    public bool HasEditableSelection =>
        _selectedVertices.Any(pair => pair.Value.Count > 0)
        || _selectedFaces.Any(pair => pair.Value.Count > 0)
        || _selectedEdges.Count > 0
        || _selectedSources.Count > 0;

    /// <summary>
    /// True when faces specifically are selected. Splitting a selection into its
    /// own part moves whole faces, so a vertex-only selection cannot drive it —
    /// the host would separate the entire part instead.
    /// </summary>
    public bool HasFaceSelection => _selectedFaces.Any(pair => pair.Value.Count > 0);
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
        StartupTiming.Mark("gpu_viewport_initialized");
        FrameMesh();
        ApplyArchivePreviewInitialCamera();
        InitializePresentationContexts();
        StartupTiming.Mark("viewport_presentation_initialized");
    }

}
