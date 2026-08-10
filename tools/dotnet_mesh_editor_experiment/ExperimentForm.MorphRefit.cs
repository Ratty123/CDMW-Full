using System.Globalization;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed record MorphPartChoice(int Index, string Name)
{
    public override string ToString() => $"{Name} (Part {Index})";
}

internal sealed partial class ExperimentForm
{
    private sealed record MorphChoice(string Id, string Name)
    {
        public override string ToString() => Name;
    }

    private sealed record MorphRefitGarmentState(
        bool Enabled,
        double IntensityPercent,
        string Mode,
        double ClearancePercent);

    private sealed class MorphSliderControls
    {
        public required string DefinitionId { get; init; }
        public required double Minimum { get; init; }
        public required double Maximum { get; init; }
        public required double DefaultValue { get; init; }
        public required TrackBar Track { get; init; }
        public required NumericUpDown Numeric { get; init; }
        public bool Synchronizing { get; set; }
    }

    private readonly ComboBox _morphProfile = new();
    private readonly ComboBox _morphPreset = new();
    private readonly TableLayoutPanel _morphSliderStack = new();
    private readonly Label _morphDriverStatus = new();
    private readonly Label _morphBindingStatus = new();
    private readonly Label _morphDiagnosticStatus = new();
    private readonly CheckBox _morphRefitEnabled = new();
    private readonly ComboBox _morphRefitMode = new();
    private readonly NumericUpDown _morphRefitIntensity = new();
    private readonly NumericUpDown _morphRefitClearance = new();
    private readonly Dictionary<string, MorphSliderControls> _morphSliders = new(StringComparer.Ordinal);
    private readonly List<Button> _topologyMutationButtons = new();
    private TableLayoutPanel? _morphSectionLayout;
    private TableLayoutPanel? _morphSectionBody;
    private Button? _morphSectionHeader;
    private Label? _morphWorkflowHint;
    private Label? _morphStepDefinition;
    private Label? _morphStepRefit;
    private Label? _morphStepKeep;
    private Button? _morphAuthorButton;
    private Control? _morphProfileControl;
    private Control? _morphProfileActions;
    private Control? _morphPresetControl;
    private Control? _morphPresetActions;
    private Control? _morphBindingActions;
    private Control? _morphRefitSettingsControl;
    private Control? _morphCommitActions;
    private GroupBox? _morphDefinitionCard;
    private GroupBox? _morphPresetCard;
    private GroupBox? _morphSlidersCard;
    private GroupBox? _morphRefitCard;
    private GroupBox? _morphCommitCard;
    private TableLayoutPanel? _morphDefinitionCardBody;
    private TableLayoutPanel? _morphPresetCardBody;
    private TableLayoutPanel? _morphSlidersCardBody;
    private TableLayoutPanel? _morphRefitCardBody;
    private TableLayoutPanel? _morphCommitCardBody;
    private bool _morphCompactLayoutActive;
    private bool _morphClassicExpanded = true;
    private bool _syncingMorphUi;
    private bool _morphStateReceived;
    private bool _morphRefreshRequested;
    private bool _morphUnbaked;
    private bool _morphBusy;
    private long _morphStateRevision = -1;
    private long _morphStateRequestId;
    private long _morphFinishRequestId;
    private long _morphEndRequestId;
    private bool _morphFinishPending;
    // Finish Edit Mesh must always finish. Every waiting branch below resumes
    // when the state it waits for arrives -- and if that message is lost, this
    // timer forces the save anyway rather than leaving the button dead.
    private readonly System.Windows.Forms.Timer _morphFinishFallbackTimer = new() { Interval = 4000 };
    private bool _morphFinishFallbackWired;
    private string _morphSessionId = string.Empty;
    private string _morphDefinitionSignature = string.Empty;
    private string _morphActiveChangeId = string.Empty;
    private readonly System.Windows.Forms.Timer _morphUpdateTimer = new() { Interval = 33 };
    private bool _morphUpdateTimerWired;
    private MorphSliderControls? _pendingMorphUpdateControls;
    private string _pendingMorphUpdateChangeId = string.Empty;
    private long _morphUpdateRequestId;
    private readonly HashSet<int> _morphDriverPartIndices = new();
    private readonly HashSet<int> _morphBoundGarmentPartIndices = new();
    private readonly Dictionary<int, MorphRefitGarmentState> _morphGarmentSettings = new();
    private readonly Queue<(string Command, Dictionary<string, object?> Payload)> _morphWizardCommandQueue = new();
    private bool _morphWizardSequenceActive;
    private long _morphWizardCommandRequestId;
    private MorphAuthorDialog? _morphWizardActiveDialog;
    private Action<bool>? _morphWizardSequenceCompleted;
    private string _morphWizardSuccessMessage = string.Empty;
    private readonly Queue<(string Command, Dictionary<string, object?> Payload)> _morphUiCommandQueue = new();
    private long _morphUiCommandRequestId;

    private void ConfigureMorphSelectors()
    {
    ConfigureCombo(_morphProfile, Array.Empty<object>(), selectedIndex: 0);
    ConfigureCombo(_morphPreset, Array.Empty<object>(), selectedIndex: 0);
    _morphProfile.Name = "MorphProfileSelector";
    _morphPreset.Name = "MorphPresetSelector";
    _morphProfile.SelectedIndexChanged += (_, _) =>
    {
        if (!_syncingMorphUi && _morphProfile.SelectedItem is MorphChoice choice)
        {
            RequestMorphUiCommand("morph_activate", new Dictionary<string, object?> { ["profile_id"] = choice.Id });
        }
    };
    _morphPreset.SelectedIndexChanged += (_, _) =>
    {
        if (!_syncingMorphUi && _morphPreset.SelectedItem is MorphChoice choice && choice.Id.Length > 0)
        {
            RequestMorphUiCommand("morph_apply_preset", new Dictionary<string, object?> { ["preset_id"] = choice.Id });
        }
    };
    }

    private void ConfigureMorphRefitInputs()
    {
    ConfigureMorphStatusLabel(_morphDriverStatus, "Driver: not set");
    ConfigureMorphStatusLabel(_morphBindingStatus, "Garment: not bound");
    ConfigureMorphStatusLabel(_morphDiagnosticStatus, "Select or author a topology-matched profile.");
    ConfigureCheckBox(_morphRefitEnabled, "Refit enabled for selected garments", isChecked: true);
    _morphRefitEnabled.Name = "MorphRefitEnabledCheckBox";
    ConfigureCombo(
        _morphRefitMode,
        new object[]
        {
            new MorphChoice("surface", "Surface (flexible)"),
            new MorphChoice("rigid", "Rigid (hard surface)"),
        },
        selectedIndex: 0);
    _morphRefitMode.Name = "MorphRefitModeSelector";
    ConfigureNumeric(
        _morphRefitIntensity,
        decimalPlaces: 1,
        minimum: 0m,
        maximum: 200m,
        value: 100m,
        increment: 5m);
    _morphRefitIntensity.Name = "MorphRefitIntensityNumeric";
    ConfigureNumeric(
        _morphRefitClearance,
        decimalPlaces: 2,
        minimum: 0m,
        maximum: 5m,
        value: 0m,
        increment: 0.05m);
    _morphRefitClearance.Name = "MorphRefitClearanceNumeric";
    // Wrap inside the narrowest column this section is shown in. A wider
    // bound leaves the tail of every diagnostic clipped by the tool rail's
    // property column instead of wrapping onto a second line.
    _morphDiagnosticStatus.MaximumSize = new Size(ScaleToolPanelWidth(EditMeshToolColumnMetrics.WrappedStatusWidth), 0);

    _morphSliderStack.Name = "MorphSliderStack";
    _morphSliderStack.ColumnCount = 1;
    _morphSliderStack.RowCount = 0;
    _morphSliderStack.AutoSize = true;
    _morphSliderStack.AutoSizeMode = AutoSizeMode.GrowAndShrink;
    _morphSliderStack.BackColor = ThemeSectionBackground;
    _morphSliderStack.Margin = new Padding(0);
    _morphSliderStack.Padding = new Padding(0);
    _morphSliderStack.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
    }

    private void ConfigureMorphHelp(
        Button setDriver,
        Button bind,
        Button clear,
        Button applyRefitSettings,
        Button reset,
        Button bake)
    {
    // The five buttons whose captions alone do not say what happens next.
    // The workflow hint below the header carries the order; these carry
    // the consequence of each click.
    _helpToolTip.SetToolTip(setDriver, "Make the selected parts the driver body that bound garments follow.");
    _helpToolTip.SetToolTip(bind, "Refit the selected garment parts against the driver whenever a slider moves.");
    _helpToolTip.SetToolTip(clear, "Unbind every refit garment.");
    _helpToolTip.SetToolTip(
        _morphRefitMode,
        "Surface follows the bound body triangle. Rigid transports each vertex in the triangle's local frame for armour and other hard parts.");
    _helpToolTip.SetToolTip(
        _morphRefitIntensity,
        "Scale how strongly the selected bound garments follow the driver. Zero leaves them stationary unless clearance relief is needed.");
    _helpToolTip.SetToolTip(
        _morphRefitClearance,
        "Push penetration outward to this percentage of the driver's bounding-box diagonal after refit.");
    _helpToolTip.SetToolTip(
        applyRefitSettings,
        "Apply Enabled, mode, intensity, and clearance to the selected bound garment parts as one undoable edit.");
    _helpToolTip.SetToolTip(reset, "Discard all live slider values.");
    _helpToolTip.SetToolTip(bake, "Write the visible slider result permanently into the mesh topology.");
    }

    private Control BuildMorphRefitSection(TableLayoutPanel stack)
    {
        ConfigureMorphSelectors();
        ConfigureMorphRefitInputs();
        var author = StyledActionButton("Create Profile...", () => ShowMorphAuthorDialog());
        _morphAuthorButton = author;
        var saveProfile = StyledActionButton("Save Profile", () => RequestMorphUiCommand("morph_save_profile"));
        saveProfile.Name = "MorphSaveProfileButton";
        var deleteProfile = StyledActionButton("Delete Profile", () =>
        {
            if (_morphProfile.SelectedItem is MorphChoice choice)
            {
                RequestMorphUiCommand("morph_delete_profile", new Dictionary<string, object?> { ["profile_id"] = choice.Id });
            }
        });
        deleteProfile.Name = "MorphDeleteProfileButton";
        var savePreset = StyledActionButton("Save Preset...", SaveMorphPreset);
        var deletePreset = StyledActionButton("Delete Preset", () =>
        {
            if (_morphPreset.SelectedItem is MorphChoice choice && choice.Id.Length > 0)
            {
                RequestMorphUiCommand("morph_delete_preset", new Dictionary<string, object?> { ["preset_id"] = choice.Id });
            }
        });
        var setDriver = StyledActionButton("1. Set Selected Driver Parts", RequestMorphSetDriver);
        var bind = StyledActionButton("2. Bind Selected Garment Parts", RequestMorphBind);
        var clear = StyledActionButton("Clear Refit", () => RequestMorphUiCommand("morph_clear_refit"));
        var applyRefitSettings = StyledActionButton("Apply to Selected Garments", RequestMorphConfigureRefit);
        var reset = StyledActionButton("Reset", () => RequestMorphUiCommand("morph_reset"));
        var bake = StyledActionButton("Bake", () => RequestMorphUiCommand("morph_bake"));
        reset.Name = "MorphResetButton";
        bake.Name = "MorphBakeButton";
        ConfigureMorphHelp(setDriver, bind, clear, applyRefitSettings, reset, bake);
        _morphWorkflowHint = new Label
        {
            AutoSize = true,
            ForeColor = ThemeMutedText,
            BackColor = ThemeSectionBackground,
            Font = new Font(Font.FontFamily, 8f),
            Margin = new Padding(2, 2, 2, 6),
            UseMnemonic = false,
            MaximumSize = new Size(ScaleToolPanelWidth(EditMeshToolColumnMetrics.WrappedStatusWidth), 0),
        };
        _morphWorkflowHint.Text = "Create or choose a profile, adjust its sliders, optionally bind a garment, then review and Bake. Saving a profile never bakes the mesh.";
        // The four steps, named on the surface rather than in a tooltip. The
        // section is a single column of eleven controls, and reading it top to
        // bottom did not say which of them is the place to start, that a
        // definition profile is a thing you create rather than something the
        // mesh arrives with, or that the garment half is optional. Numbering
        // the groups says all three without a document.
        _morphStepDefinition = MorphStepLabel("Step 1: Profile and sliders");
        _morphStepRefit = MorphStepLabel("Step 2: Refit (optional)");
        _morphStepKeep = MorphStepLabel("Step 3: Review and apply");

        _morphProfileControl = LabeledControl("Profile", _morphProfile);
        _morphProfileActions = ButtonRow(author, saveProfile, deleteProfile);
        _morphPresetControl = LabeledControl("Value preset", _morphPreset);
        _morphPresetActions = ButtonRow(savePreset, deletePreset);
        _morphBindingActions = ButtonRow(setDriver, bind, clear);
        _morphRefitSettingsControl = StackControls(
            _morphRefitEnabled,
            LabeledControl("Refit mode", _morphRefitMode),
            LabeledControl("Follow intensity (%)", _morphRefitIntensity),
            LabeledControl("Clearance (% driver size)", _morphRefitClearance),
            ButtonRow(applyRefitSettings));
        _morphRefitSettingsControl.Enabled = false;
        _morphCommitActions = ButtonRow(reset, bake);
        var body = (TableLayoutPanel)StackControls(
            _morphWorkflowHint,
            _morphStepDefinition,
            _morphProfileControl,
            _morphProfileActions,
            _morphPresetControl,
            _morphPresetActions,
            _morphSliderStack,
            _morphStepRefit,
            _morphDriverStatus,
            _morphBindingStatus,
            _morphBindingActions,
            _morphRefitSettingsControl,
            _morphStepKeep,
            _morphCommitActions,
            _morphDiagnosticStatus);
        _morphSectionBody = body;
        var section = new TableLayoutPanel
        {
            Name = "MorphRefitSection",
            ColumnCount = 1,
            RowCount = 2,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0, 0, 0, 10),
            Padding = new Padding(0),
        };
        section.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        section.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        section.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        var header = StyledButton("▾  Morph & Refit", 32);
        _morphSectionLayout = section;
        _morphSectionHeader = header;
        header.Name = "MorphRefitCollapseButton";
        header.TextAlign = ContentAlignment.MiddleLeft;
        header.Click += (_, _) =>
        {
            body.Visible = !body.Visible;
            _morphClassicExpanded = body.Visible;
            header.Text = body.Visible ? "▾  Morph & Refit" : "▸  Morph & Refit";
            section.PerformLayout();
        };
        body.Dock = DockStyle.Top;
        section.Controls.Add(header, 0, 0);
        section.Controls.Add(body, 0, 1);
        _morphDefinitionCard = CreateMorphCompactCard(
            "Profile",
            "Create or choose a topology-matched profile and its sliders.",
            out _morphDefinitionCardBody);
        _morphPresetCard = CreateMorphCompactCard(
            "Profile Values",
            "Apply or save a named set of slider values.",
            out _morphPresetCardBody);
        _morphSlidersCard = CreateMorphCompactCard(
            "Shape Sliders",
            "Adjust the active topology-bound values.",
            out _morphSlidersCardBody);
        _morphRefitCard = CreateMorphCompactCard(
            "Optional Refit",
            "First set selected driver parts, then select and bind garment parts.",
            out _morphRefitCardBody);
        _morphCommitCard = CreateMorphCompactCard(
            "Review & Apply",
            "Reset or Bake the visible result. Saving a profile does not Bake.",
            out _morphCommitCardBody);
        AddStackRow(stack, section);
        _meshEditOnlySections.Add(section);
        // Before any morph state has arrived the list is empty, which is the
        // state the "where do profiles come from" question is asked in.
        UpdateMorphWorkflowHint();
        return section;
    }

    /// <summary>
    /// One step caption in the section's single column. Assigned outside the
    /// initializer for the same reason every other control name here is: a
    /// control name sitting beside a Text literal is picked up by the
    /// localization scanner as if it were one.
    /// </summary>
    private Label MorphStepLabel(string text)
    {
        var label = new Label
        {
            Text = text,
            AutoSize = true,
            ForeColor = ThemeStrongText,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(2, 8, 2, 2),
            UseMnemonic = false,
        };
        label.Name = $"MorphStepLabel{_morphStepLabelCount++}";
        return label;
    }

    private int _morphStepLabelCount;

    private void AddMorphStepRow(Label? label)
    {
        if (label is not null && _morphSectionBody is not null)
        {
            AddStackRow(_morphSectionBody, label);
        }
    }

    /// <summary>
    /// Says what to do now, from what the section is actually holding.
    /// </summary>
    /// <remarks>
    /// A fixed sentence describing the whole workflow could not answer the
    /// question a reader opening this page actually has, which is "there is no
    /// profile in this list and nothing tells me where one comes from". Each
    /// state names its own next action, and the button that performs it is
    /// accented while it is the one to press.
    /// </remarks>
    private void UpdateMorphWorkflowHint()
    {
        if (_morphWorkflowHint is null)
        {
            return;
        }
        var hasProfiles = _morphProfile.Items.Count > 0;
        var profileChosen = hasProfiles && _morphProfile.SelectedIndex >= 0;
        var startHere = !hasProfiles || !profileChosen || _morphSliders.Count == 0;
        // One assignment per state rather than a nested conditional: the
        // localization scanner reads assignments to a UI sink, and only the
        // first branch of a conditional expression reaches it, which would
        // leave the other four English in every other language.
        if (!hasProfiles)
        {
            _morphWorkflowHint.Text = "No profile yet. Select one or more parts, then Create Profile... to build the first slider. Saving it does not Bake the mesh.";
        }
        else if (!profileChosen)
        {
            _morphWorkflowHint.Text = "Choose a profile above, or Create Profile... to build another one from selected parts.";
        }
        else if (_morphSliders.Count == 0)
        {
            _morphWorkflowHint.Text = "This profile has no sliders yet. Select parts, then Create Profile... to add one.";
        }
        else if (_morphUnbaked)
        {
            _morphWorkflowHint.Text = "Review the visible result. Bake writes it into the mesh; Reset discards it. Topology edits stay blocked until one runs.";
        }
        else
        {
            _morphWorkflowHint.Text = "Adjust profile sliders, optionally bind garment parts, then review and Bake. Slider changes remain non-destructive until baked.";
        }
        if (_morphAuthorButton is not null)
        {
            SetButtonAccent(_morphAuthorButton, startHere);
        }
    }

    private GroupBox CreateMorphCompactCard(
        string title,
        string helpText,
        out TableLayoutPanel body)
    {
        var card = new MeshEditorSectionBox
        {
            Name = $"EditMeshToolRailMorph{title.Replace(" ", string.Empty).Replace("&", string.Empty)}Card",
            Text = title,
            ForeColor = ThemeText,
            BackColor = ThemeSectionBackground,
            Padding = new Padding(10, 24, 10, 10),
            Margin = new Padding(4),
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Dock = DockStyle.Fill,
            AccessibleDescription = helpText,
        };
        body = new MeshEditorBufferedTableLayoutPanel
        {
            Name = $"{card.Name}Body",
            ColumnCount = 1,
            RowCount = 0,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Dock = DockStyle.Top,
            Margin = new Padding(0),
            Padding = new Padding(0),
            BackColor = ThemeSectionBackground,
        };
        body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        card.Controls.Add(body);
        _helpToolTip.SetToolTip(card, helpText);
        return card;
    }

    private void EnterCompactMorphLayout(int requestedColumns)
    {
        if (_morphSectionLayout is null
            || _morphSectionBody is null
            || _morphSectionHeader is null
            || _morphDefinitionCard is null
            || _morphPresetCard is null
            || _morphSlidersCard is null
            || _morphRefitCard is null
            || _morphCommitCard is null
            || _morphDefinitionCardBody is null
            || _morphPresetCardBody is null
            || _morphSlidersCardBody is null
            || _morphRefitCardBody is null
            || _morphCommitCardBody is null
            || _morphProfileControl is null
            || _morphProfileActions is null
            || _morphPresetControl is null
            || _morphPresetActions is null
            || _morphBindingActions is null
            || _morphRefitSettingsControl is null
            || _morphCommitActions is null)
        {
            return;
        }
        if (!_morphCompactLayoutActive)
        {
            _morphClassicExpanded = _morphSectionBody.Visible;
            PopulateMorphCompactCard(
                _morphDefinitionCardBody,
                _morphProfileControl,
                _morphProfileActions);
            PopulateMorphCompactCard(
                _morphPresetCardBody,
                _morphPresetControl,
                _morphPresetActions);
            PopulateMorphCompactCard(
                _morphSlidersCardBody,
                _morphSliderStack);
            PopulateMorphCompactCard(
                _morphRefitCardBody,
                _morphDriverStatus,
                _morphBindingStatus,
                _morphBindingActions,
                _morphRefitSettingsControl);
            PopulateMorphCompactCard(
                _morphCommitCardBody,
                _morphCommitActions,
                _morphDiagnosticStatus);
            _morphCompactLayoutActive = true;
        }

        var columns = requestedColumns >= 4 ? 4 : requestedColumns >= 2 ? 2 : 1;
        _morphSectionLayout.SuspendLayout();
        _morphSectionBody.SuspendLayout();
        try
        {
            _morphSectionHeader.Visible = false;
            _morphSectionLayout.AutoSize = true;
            _morphSectionLayout.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            _morphSectionLayout.Dock = DockStyle.Top;
            _morphSectionLayout.Margin = new Padding(0);
            _morphSectionLayout.RowStyles[0].SizeType = SizeType.Absolute;
            _morphSectionLayout.RowStyles[0].Height = 0;
            _morphSectionLayout.RowStyles[1].SizeType = SizeType.AutoSize;
            _morphSectionBody.Visible = true;
            _morphSectionBody.Dock = DockStyle.Top;
            _morphSectionBody.AutoSize = true;
            _morphSectionBody.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            _morphSectionBody.Padding = new Padding(4);
            _morphDiagnosticStatus.MaximumSize = Size.Empty;

            _morphSectionBody.Controls.Clear();
            _morphSectionBody.ColumnStyles.Clear();
            _morphSectionBody.RowStyles.Clear();
            _morphSectionBody.ColumnCount = columns;
            _morphSectionBody.RowCount = 0;
            for (var column = 0; column < columns; column++)
            {
                _morphSectionBody.ColumnStyles.Add(
                    new ColumnStyle(SizeType.Percent, 100.0f / columns));
            }
            if (columns == 4)
            {
                AddMorphCompactGridRow(
                    _morphSectionBody,
                    _morphDefinitionCard,
                    _morphPresetCard,
                    _morphRefitCard,
                    _morphCommitCard);
                AddMorphCompactSpanningRow(
                    _morphSectionBody,
                    _morphSlidersCard,
                    columns);
            }
            else if (columns == 2)
            {
                AddMorphCompactGridRow(
                    _morphSectionBody,
                    _morphDefinitionCard,
                    _morphPresetCard);
                AddMorphCompactSpanningRow(
                    _morphSectionBody,
                    _morphSlidersCard,
                    columns);
                AddMorphCompactGridRow(
                    _morphSectionBody,
                    _morphRefitCard,
                    _morphCommitCard);
            }
            else
            {
                AddMorphCompactGridRow(_morphSectionBody, _morphDefinitionCard);
                AddMorphCompactGridRow(_morphSectionBody, _morphPresetCard);
                AddMorphCompactGridRow(_morphSectionBody, _morphSlidersCard);
                AddMorphCompactGridRow(_morphSectionBody, _morphRefitCard);
                AddMorphCompactGridRow(_morphSectionBody, _morphCommitCard);
            }
        }
        finally
        {
            _morphSectionBody.ResumeLayout(performLayout: true);
            _morphSectionLayout.ResumeLayout(performLayout: true);
        }
    }

    private void ExitCompactMorphLayout()
    {
        if (!_morphCompactLayoutActive
            || _morphSectionLayout is null
            || _morphSectionBody is null
            || _morphSectionHeader is null
            || _morphProfileControl is null
            || _morphProfileActions is null
            || _morphPresetControl is null
            || _morphPresetActions is null
            || _morphBindingActions is null
            || _morphRefitSettingsControl is null
            || _morphCommitActions is null)
        {
            return;
        }
        _morphSectionLayout.SuspendLayout();
        _morphSectionBody.SuspendLayout();
        try
        {
            ClearMorphCompactCard(_morphDefinitionCardBody);
            ClearMorphCompactCard(_morphPresetCardBody);
            ClearMorphCompactCard(_morphSlidersCardBody);
            ClearMorphCompactCard(_morphRefitCardBody);
            ClearMorphCompactCard(_morphCommitCardBody);
            _morphSectionBody.Controls.Clear();
            _morphSectionBody.ColumnStyles.Clear();
            _morphSectionBody.RowStyles.Clear();
            _morphSectionBody.ColumnCount = 1;
            _morphSectionBody.RowCount = 0;
            _morphSectionBody.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            if (_morphWorkflowHint is not null)
            {
                AddStackRow(_morphSectionBody, _morphWorkflowHint);
            }
            AddMorphStepRow(_morphStepDefinition);
            AddStackRow(_morphSectionBody, _morphProfileControl);
            AddStackRow(_morphSectionBody, _morphProfileActions);
            AddStackRow(_morphSectionBody, _morphPresetControl);
            AddStackRow(_morphSectionBody, _morphPresetActions);
            AddStackRow(_morphSectionBody, _morphSliderStack);
            AddMorphStepRow(_morphStepRefit);
            AddStackRow(_morphSectionBody, _morphDriverStatus);
            AddStackRow(_morphSectionBody, _morphBindingStatus);
            AddStackRow(_morphSectionBody, _morphBindingActions);
            AddStackRow(_morphSectionBody, _morphRefitSettingsControl);
            AddMorphStepRow(_morphStepKeep);
            AddStackRow(_morphSectionBody, _morphCommitActions);
            AddStackRow(_morphSectionBody, _morphDiagnosticStatus);

            _morphSectionHeader.Visible = true;
            _morphSectionHeader.Text = _morphClassicExpanded
                ? "▾  Morph & Refit"
                : "▸  Morph & Refit";
            _morphSectionLayout.AutoSize = true;
            _morphSectionLayout.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            _morphSectionLayout.Dock = DockStyle.Top;
            _morphSectionLayout.Margin = new Padding(0, 0, 0, 10);
            _morphSectionLayout.RowStyles[0].SizeType = SizeType.AutoSize;
            _morphSectionLayout.RowStyles[1].SizeType = SizeType.AutoSize;
            _morphSectionBody.Dock = DockStyle.Top;
            _morphSectionBody.AutoSize = true;
            _morphSectionBody.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            _morphSectionBody.Padding = new Padding(0);
            _morphSectionBody.Visible = _morphClassicExpanded;
            _morphDiagnosticStatus.MaximumSize =
                new Size(ScaleToolPanelWidth(EditMeshToolColumnMetrics.WrappedStatusWidth), 0);
            _morphCompactLayoutActive = false;
        }
        finally
        {
            _morphSectionBody.ResumeLayout(performLayout: true);
            _morphSectionLayout.ResumeLayout(performLayout: true);
        }
    }

    private static void PopulateMorphCompactCard(
        TableLayoutPanel body,
        params Control[] controls)
    {
        body.Controls.Clear();
        body.RowStyles.Clear();
        body.RowCount = 0;
        foreach (var control in controls)
        {
            AddStackRow(body, control);
        }
    }

    private static void ClearMorphCompactCard(TableLayoutPanel? body)
    {
        if (body is null)
        {
            return;
        }
        body.Controls.Clear();
        body.RowStyles.Clear();
        body.RowCount = 0;
    }

    private static void AddMorphCompactGridRow(
        TableLayoutPanel grid,
        params Control[] controls)
    {
        var row = grid.RowCount;
        grid.RowCount = row + 1;
        grid.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        for (var column = 0; column < controls.Length; column++)
        {
            controls[column].Dock = DockStyle.Fill;
            grid.Controls.Add(controls[column], column, row);
        }
    }

    private static void AddMorphCompactSpanningRow(
        TableLayoutPanel grid,
        Control control,
        int columns)
    {
        var row = grid.RowCount;
        grid.RowCount = row + 1;
        grid.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        control.Dock = DockStyle.Fill;
        grid.Controls.Add(control, 0, row);
        grid.SetColumnSpan(control, columns);
    }

    private void DisposeDetachedCompactMorphCards()
    {
        foreach (var card in new[]
                 {
                     _morphDefinitionCard,
                     _morphPresetCard,
                     _morphSlidersCard,
                     _morphRefitCard,
                     _morphCommitCard,
                 })
        {
            if (card is { Parent: null })
            {
                card.Dispose();
            }
        }
    }

    private static void ConfigureMorphStatusLabel(Label label, string text)
    {
        label.Text = text;
        label.AutoSize = true;
        label.ForeColor = ThemeMutedText;
        label.BackColor = ThemeSectionBackground;
        label.Margin = new Padding(0, 0, 0, 6);
    }

    private long RequestMorphUiCommand(
        string command,
        Dictionary<string, object?>? payload = null)
    {
        var normalized = (command ?? string.Empty).Trim().ToLowerInvariant();
        var commandPayload = payload is null
            ? new Dictionary<string, object?>()
            : new Dictionary<string, object?>(payload);
        if (MorphUiCommandBlocked() || _morphUiCommandQueue.Count > 0)
        {
            _morphUiCommandQueue.Enqueue((normalized, commandPayload));
            _morphDiagnosticStatus.ForeColor = ThemeMutedText;
            var displayName = (normalized.StartsWith("morph_", StringComparison.Ordinal)
                ? normalized["morph_".Length..]
                : normalized).Replace('_', ' ');
            _morphDiagnosticStatus.Text = $"Queued {displayName} until the active Morph change finishes.";
            return 0;
        }
        _morphUiCommandRequestId = WriteCommandRequest(normalized, commandPayload);
        return _morphUiCommandRequestId;
    }

    private bool MorphUiCommandBlocked() =>
        _morphUiCommandRequestId > 0
        || _morphBusy
        || _morphActiveChangeId.Length > 0
        || _morphEndRequestId > 0
        || _morphUpdateRequestId > 0
        || _pendingMorphUpdateControls is not null
        || _morphWizardSequenceActive
        || _morphWizardCommandRequestId > 0
        || _morphWizardCommandQueue.Count > 0;

    private void ResumeQueuedMorphUiCommandIfClear()
    {
        if (MorphUiCommandBlocked() || _morphUiCommandQueue.Count == 0)
        {
            return;
        }
        var (command, payload) = _morphUiCommandQueue.Dequeue();
        _morphUiCommandRequestId = WriteCommandRequest(command, payload);
        if (_morphUiCommandRequestId <= 0 && _morphUiCommandQueue.Count > 0)
        {
            BeginInvoke((Action)ResumeQueuedMorphUiCommandIfClear);
        }
    }

    private void RequestMorphStateRefresh()
    {
        if (_morphRefreshRequested
            || _residentMaterialSessionId.Length == 0
            || (_morphStateReceived && string.Equals(_morphSessionId, _residentMaterialSessionId, StringComparison.Ordinal)))
        {
            return;
        }
        _morphRefreshRequested = true;
        WriteCommandRequest("morph_refresh");
    }

    private void ResetMorphStateAuthority()
    {
        CompleteMorphWizardCommandSequence(accepted: false);
        _morphStateReceived = false;
        _morphRefreshRequested = false;
        _morphStateRevision = -1;
        _morphStateRequestId = 0;
        _morphSessionId = string.Empty;
        _morphActiveChangeId = string.Empty;
        _morphUpdateTimer.Stop();
        _pendingMorphUpdateControls = null;
        _pendingMorphUpdateChangeId = string.Empty;
        _morphUpdateRequestId = 0;
        _morphUiCommandQueue.Clear();
        _morphUiCommandRequestId = 0;
        _morphFinishRequestId = 0;
        _morphEndRequestId = 0;
        _morphFinishPending = false;
        _morphUnbaked = false;
        _morphBusy = false;
        _morphDriverPartIndices.Clear();
        _morphBoundGarmentPartIndices.Clear();
        _morphGarmentSettings.Clear();
        if (_morphRefitSettingsControl is not null)
        {
            _morphRefitSettingsControl.Enabled = false;
        }
        foreach (var button in _topologyMutationButtons)
        {
            button.Enabled = true;
            _helpToolTip.SetToolTip(button, string.Empty);
        }
    }

    private void RequestFinishEditMesh()
    {
        _morphFinishPending = true;
        if (!_morphStateReceived)
        {
            // A helper that never received Morph & Refit state cannot have
            // authored a resident morph change. Finishing that no-op edit
            // session must only return interaction to placement mode; waiting
            // for a state refresh here can strand the otherwise healthy host.
            _morphFinishPending = false;
            WriteProtocolEvent("save_request");
            return;
        }
        if (_residentMaterialSessionId.Length > 0
            && !string.Equals(_morphSessionId, _residentMaterialSessionId, StringComparison.Ordinal))
        {
            RequestMorphStateRefresh();
            _statusLabel.Text = "Waiting for resident Morph & Refit state before Finish Edit Mesh...";
            ArmMorphFinishFallback();
            return;
        }
        if (_morphActiveChangeId.Length > 0
            || _morphEndRequestId > 0
            || _morphBusy
            || _morphWizardSequenceActive
            || _morphWizardCommandRequestId > 0
            || _morphWizardCommandQueue.Count > 0
            || _morphUiCommandRequestId > 0
            || _morphUiCommandQueue.Count > 0
            || _pendingMutationRequests.Values.Any(pending =>
                pending.Command.StartsWith("morph_", StringComparison.Ordinal)
                && pending.Command != "morph_finish"))
        {
            _statusLabel.Text = "Waiting for the final Morph & Refit value before Finish Edit Mesh...";
            ArmMorphFinishFallback();
            return;
        }
        BeginFinishCommitOrSave();
    }

    /// <summary>
    /// Guarantees a pending Finish resolves even if the message it waits for
    /// never arrives. Forcing the save skips at most an uncommitted procedural
    /// morph value; a Finish button that stays dead skips the whole exit.
    /// </summary>
    private void ArmMorphFinishFallback()
    {
        if (!_morphFinishFallbackWired)
        {
            _morphFinishFallbackWired = true;
            _morphFinishFallbackTimer.Tick += (_, _) =>
            {
                _morphFinishFallbackTimer.Stop();
                if (!_morphFinishPending)
                {
                    return;
                }
                WriteProtocolEvent("morph_finish_fallback_forced", new Dictionary<string, object?>
                {
                    ["active_change_id"] = _morphActiveChangeId,
                    ["end_request_id"] = _morphEndRequestId,
                    ["busy"] = _morphBusy,
                    ["unbaked"] = _morphUnbaked,
                    ["pending_morph_commands"] = _pendingMutationRequests.Values
                        .Count(pending => pending.Command.StartsWith("morph_", StringComparison.Ordinal)),
                });
                _morphFinishPending = false;
                _morphFinishRequestId = 0;
                WriteProtocolEvent("save_request");
            };
        }
        _morphFinishFallbackTimer.Stop();
        _morphFinishFallbackTimer.Start();
    }

    /// <summary>
    /// A pending Finish resumes the moment its blockers clear, from whichever
    /// message cleared them -- a morph state update or a command result.
    /// </summary>
    private void ResumePendingFinishIfClear()
    {
        if (_morphFinishPending
            && _morphActiveChangeId.Length == 0
            && _morphEndRequestId == 0
            && !_morphBusy
            && !_morphWizardSequenceActive
            && _morphWizardCommandRequestId == 0
            && _morphWizardCommandQueue.Count == 0
            && _morphUiCommandRequestId == 0
            && _morphUiCommandQueue.Count == 0
            && !_pendingMutationRequests.Values.Any(pending =>
                pending.Command.StartsWith("morph_", StringComparison.Ordinal)
                && pending.Command != "morph_finish"))
        {
            BeginFinishCommitOrSave();
        }
    }

    private void BeginFinishCommitOrSave()
    {
        if (!_morphFinishPending)
        {
            return;
        }
        if (!_morphUnbaked)
        {
            _morphFinishPending = false;
            WriteProtocolEvent("save_request");
            return;
        }
        _morphFinishRequestId = WriteCommandRequest("morph_finish");
        if (_morphFinishRequestId <= 0)
        {
            _morphFinishPending = false;
            return;
        }
        _statusLabel.Text = "Committing visible Morph & Refit state before Finish Edit Mesh...";
    }

    private void CompleteMorphCommandResult(PendingMutationRequest pending, bool accepted)
    {
        if (pending.RequestId == _morphUiCommandRequestId)
        {
            _morphUiCommandRequestId = 0;
        }
        if (pending.RequestId == _morphWizardCommandRequestId)
        {
            _morphWizardCommandRequestId = 0;
            if (accepted)
            {
                BeginInvoke((Action)SendNextMorphWizardCommand);
            }
            else
            {
                CompleteMorphWizardCommandSequence(accepted: false);
            }
        }
        if (pending.Command == "morph_refresh")
        {
            _morphRefreshRequested = false;
        }
        if (pending.Command == "morph_change" && pending.Phase == "end" && pending.RequestId == _morphEndRequestId)
        {
            _morphEndRequestId = 0;
            _morphBusy = false;
            if (!accepted)
            {
                _morphFinishPending = false;
            }
        }
        if (!accepted && pending.Command.StartsWith("morph_", StringComparison.Ordinal) && pending.Command != "morph_refresh")
        {
            _morphFinishPending = false;
        }
        if (pending.Command == "morph_change" && pending.Phase == "update" && pending.RequestId == _morphUpdateRequestId)
        {
            _morphUpdateRequestId = 0;
            BeginInvoke((Action)FlushPendingMorphUpdate);
        }
        if (pending.Command != "morph_finish" || pending.RequestId != _morphFinishRequestId)
        {
            // This result may have been the last blocker a pending Finish was
            // waiting on; without this the finish only resumed from a fresh
            // morph state update, which quiet sessions never send.
            ResumePendingFinishIfClear();
            BeginInvoke((Action)ResumeQueuedMorphUiCommandIfClear);
            return;
        }
        _morphFinishRequestId = 0;
        _morphFinishPending = false;
        if (accepted)
        {
            _morphUnbaked = false;
            WriteProtocolEvent("save_request");
        }
        BeginInvoke((Action)ResumeQueuedMorphUiCommandIfClear);
    }

    private void RegisterTopologyMutationButton(Button button)
    {
        _topologyMutationButtons.Add(button);
        button.Enabled = !_morphUnbaked;
    }

    private void SaveMorphPreset()
    {
        using var dialog = new MorphPresetNameDialog(ThemeWindowBackground, ThemeInputBackground, ThemeText);
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }
        RequestMorphUiCommand("morph_save_preset", new Dictionary<string, object?>
        {
            ["preset_id"] = dialog.PresetId,
            ["name"] = dialog.PresetName,
        });
    }

    private static List<string> JsonStringArray(JsonElement root, string propertyName)
    {
        var result = new List<string>();
        if (!root.TryGetProperty(propertyName, out var values) || values.ValueKind != JsonValueKind.Array)
        {
            return result;
        }
        foreach (var item in values.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.String && item.GetString() is { Length: > 0 } value)
            {
                result.Add(value);
            }
        }
        return result;
    }
}

internal sealed class MorphPresetNameDialog : Form
{
    private readonly TextBox _name = new();
    public string PresetName => _name.Text.Trim();
    public string PresetId => string.Join("-", PresetName.ToLowerInvariant().Split(
        new[] { ' ', '\t', '/', '\\', '.', ':' }, StringSplitOptions.RemoveEmptyEntries));

    public MorphPresetNameDialog(Color background, Color input, Color text)
    {
        Text = "Save Morph Preset";
        Width = 380;
        Height = 150;
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedToolWindow;
        BackColor = background;
        ForeColor = text;
        _name.Text = "My Preset";
        _name.BackColor = input;
        _name.ForeColor = text;
        _name.Dock = DockStyle.Top;
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, AutoSize = true, FlowDirection = FlowDirection.RightToLeft };
        var save = new Button { Text = "Save", DialogResult = DialogResult.OK, AutoSize = true };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, AutoSize = true };
        buttons.Controls.Add(save);
        buttons.Controls.Add(cancel);
        Controls.Add(_name);
        Controls.Add(buttons);
        AcceptButton = save;
        CancelButton = cancel;
    }
}
