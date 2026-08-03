using System.Globalization;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed record MorphPartChoice(int Index, string Name);

internal sealed partial class ExperimentForm
{
    private sealed record MorphChoice(string Id, string Name)
    {
        public override string ToString() => Name;
    }

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
    private readonly HashSet<int> _morphDriverPartIndices = new();
    private readonly Queue<(string Command, Dictionary<string, object?> Payload)> _morphWizardCommandQueue = new();
    private bool _morphWizardSequenceActive;
    private long _morphWizardCommandRequestId;
    private MorphAuthorDialog? _morphWizardActiveDialog;
    private Action<bool>? _morphWizardSequenceCompleted;
    private string _morphWizardSuccessMessage = string.Empty;

    private Control BuildMorphRefitSection(TableLayoutPanel stack)
    {
        ConfigureCombo(_morphProfile, Array.Empty<object>(), selectedIndex: 0);
        ConfigureCombo(_morphPreset, Array.Empty<object>(), selectedIndex: 0);
        _morphProfile.Name = "MorphProfileSelector";
        _morphPreset.Name = "MorphPresetSelector";
        _morphProfile.SelectedIndexChanged += (_, _) =>
        {
            if (!_syncingMorphUi && _morphProfile.SelectedItem is MorphChoice choice)
            {
                WriteCommandRequest("morph_activate", new Dictionary<string, object?> { ["profile_id"] = choice.Id });
            }
        };
        _morphPreset.SelectedIndexChanged += (_, _) =>
        {
            if (!_syncingMorphUi && _morphPreset.SelectedItem is MorphChoice choice && choice.Id.Length > 0)
            {
                WriteCommandRequest("morph_apply_preset", new Dictionary<string, object?> { ["preset_id"] = choice.Id });
            }
        };

        ConfigureMorphStatusLabel(_morphDriverStatus, "Driver: not set");
        ConfigureMorphStatusLabel(_morphBindingStatus, "Garment: not bound");
        ConfigureMorphStatusLabel(_morphDiagnosticStatus, "Select or author a topology-matched profile.");
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

        var author = StyledActionButton("Create Profile...", () => ShowMorphAuthorDialog());
        _morphAuthorButton = author;
        var saveProfile = StyledActionButton("Save Profile", () => WriteCommandRequest("morph_save_profile"));
        var deleteProfile = StyledActionButton("Delete Profile", () =>
        {
            if (_morphProfile.SelectedItem is MorphChoice choice)
            {
                WriteCommandRequest("morph_delete_profile", new Dictionary<string, object?> { ["profile_id"] = choice.Id });
            }
        });
        var savePreset = StyledActionButton("Save Preset...", SaveMorphPreset);
        var deletePreset = StyledActionButton("Delete Preset", () =>
        {
            if (_morphPreset.SelectedItem is MorphChoice choice && choice.Id.Length > 0)
            {
                WriteCommandRequest("morph_delete_preset", new Dictionary<string, object?> { ["preset_id"] = choice.Id });
            }
        });
        var setDriver = StyledActionButton("1. Set Selected Driver Parts", RequestMorphSetDriver);
        var bind = StyledActionButton("2. Bind Selected Garment Parts", RequestMorphBind);
        var clear = StyledActionButton("Clear Refit", () => WriteCommandRequest("morph_clear_refit"));
        var reset = StyledActionButton("Reset", () => WriteCommandRequest("morph_reset"));
        var bake = StyledActionButton("Bake", () => WriteCommandRequest("morph_bake"));
        // The five buttons whose captions alone do not say what happens next.
        // The workflow hint below the header carries the order; these carry
        // the consequence of each click.
        _helpToolTip.SetToolTip(setDriver, "Make the selected parts the driver body that bound garments follow.");
        _helpToolTip.SetToolTip(bind, "Refit the selected garment parts against the driver whenever a slider moves.");
        _helpToolTip.SetToolTip(clear, "Unbind every refit garment.");
        _helpToolTip.SetToolTip(reset, "Discard all live slider values.");
        _helpToolTip.SetToolTip(bake, "Write the visible slider result permanently into the mesh topology.");
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
                _morphBindingActions);
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
        _morphFinishRequestId = 0;
        _morphEndRequestId = 0;
        _morphFinishPending = false;
        _morphUnbaked = false;
        _morphBusy = false;
        _morphDriverPartIndices.Clear();
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
            if (!accepted)
            {
                _morphBusy = false;
                _morphFinishPending = false;
            }
        }
        if (!accepted && pending.Command.StartsWith("morph_", StringComparison.Ordinal) && pending.Command != "morph_refresh")
        {
            _morphFinishPending = false;
        }
        if (pending.Command != "morph_finish" || pending.RequestId != _morphFinishRequestId)
        {
            // This result may have been the last blocker a pending Finish was
            // waiting on; without this the finish only resumed from a fresh
            // morph state update, which quiet sessions never send.
            ResumePendingFinishIfClear();
            return;
        }
        _morphFinishRequestId = 0;
        _morphFinishPending = false;
        if (accepted)
        {
            _morphUnbaked = false;
            WriteProtocolEvent("save_request");
        }
    }

    private void RegisterTopologyMutationButton(Button button)
    {
        _topologyMutationButtons.Add(button);
        button.Enabled = !_morphUnbaked;
    }

    private void HandleMorphStateUpdate(JsonElement root)
    {
        var sessionId = JsonString(root, "session_id").Trim();
        var processGeneration = JsonLongValue(root, "process_generation");
        var requestId = JsonLongValue(root, "request_id");
        var stateRevision = JsonLongValue(root, "state_revision");
        var editRevision = JsonLongValue(root, "edit_revision");
        if (sessionId.Length == 0
            || !string.Equals(sessionId, _residentMaterialSessionId, StringComparison.Ordinal)
            || processGeneration != _residentProcessGeneration
            || requestId <= _morphStateRequestId
            || editRevision < _lastObservedSessionRevision
            || (_morphStateReceived && stateRevision <= _morphStateRevision))
        {
            _statusLabel.Text = "Ignored stale Morph & Refit state.";
            return;
        }
        var changeId = JsonString(root, "change_id").Trim();
        if (_morphActiveChangeId.Length > 0
            && changeId.Length > 0
            && !string.Equals(changeId, _morphActiveChangeId, StringComparison.Ordinal)
            && JsonBoolean(root, "busy"))
        {
            _statusLabel.Text = "Ignored stale Morph & Refit change.";
            return;
        }
        _morphSessionId = sessionId;
        _morphStateRequestId = requestId;
        _morphStateRevision = stateRevision;
        _morphStateReceived = true;
        _morphRefreshRequested = false;
        _morphUnbaked = JsonBoolean(root, "unbaked");
        _morphBusy = JsonBoolean(root, "busy");
        foreach (var button in _topologyMutationButtons)
        {
            button.Enabled = !_morphUnbaked;
            _helpToolTip.SetToolTip(button, _morphUnbaked
                ? "Bake or Reset active procedural sliders before changing topology."
                : string.Empty);
        }
        ApplyMorphChoices(root, "available_profiles", "profile_id", _morphProfile, JsonString(root, "profile_id"));
        ApplyMorphChoices(root, "available_presets", "preset_id", _morphPreset, JsonString(root, "preset_id"), includeEmpty: true);
        ApplyMorphDefinitions(root);
        ApplyMorphRefitStatus(root);
        var diagnostics = JsonStringArray(root, "diagnostics");
        var failure = JsonString(root, "failure").Trim();
        _morphDiagnosticStatus.ForeColor = failure.Length > 0 ? Color.Salmon : ThemeMutedText;
        _morphDiagnosticStatus.Text = failure.Length > 0
            ? failure
            : _morphBusy
                ? "Applying the latest Morph & Refit value..."
                : diagnostics.Count > 0
                ? string.Join(" ", diagnostics)
                : _morphUnbaked
                    ? "Active procedural values are non-destructive. Bake or Reset before topology edits."
                    : "Morph & Refit is ready.";
        var acknowledgement = new Dictionary<string, object?>
        {
            ["session_id"] = sessionId,
            ["process_generation"] = processGeneration,
            ["state_revision"] = stateRevision,
            ["change_id"] = changeId,
        };
        UpdateMorphWorkflowHint();
        CopyMutationEnvelope(root, acknowledgement);
        WriteProtocolEvent("morph_state_update_ack", acknowledgement);
        ResumePendingFinishIfClear();
    }

    private void ApplyMorphChoices(
        JsonElement root,
        string propertyName,
        string idName,
        ComboBox combo,
        string selectedId,
        bool includeEmpty = false)
    {
        if (!root.TryGetProperty(propertyName, out var values) || values.ValueKind != JsonValueKind.Array)
        {
            return;
        }
        var choices = new List<MorphChoice>();
        if (includeEmpty)
        {
            choices.Add(new MorphChoice(string.Empty, "(Current values)"));
        }
        foreach (var item in values.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var id = JsonString(item, idName).Trim();
            if (id.Length > 0)
            {
                choices.Add(new MorphChoice(id, JsonString(item, "name").Trim() is { Length: > 0 } name ? name : id));
            }
        }
        _syncingMorphUi = true;
        try
        {
            combo.BeginUpdate();
            combo.Items.Clear();
            combo.Items.AddRange(choices.Cast<object>().ToArray());
            var selectedIndex = choices.FindIndex(choice => string.Equals(choice.Id, selectedId, StringComparison.Ordinal));
            combo.SelectedIndex = selectedIndex >= 0 ? selectedIndex : includeEmpty && choices.Count > 0 ? 0 : -1;
            if (combo.Items.Count == 0)
            {
                combo.SelectedIndex = -1;
            }
            combo.EndUpdate();
        }
        finally
        {
            _syncingMorphUi = false;
        }
    }

    private void ApplyMorphDefinitions(JsonElement root)
    {
        if (!root.TryGetProperty("definitions", out var definitions) || definitions.ValueKind != JsonValueKind.Array)
        {
            return;
        }
        var items = definitions.EnumerateArray()
            .Where(item => item.ValueKind == JsonValueKind.Object)
            .Select(item => new
            {
                Element = item.Clone(),
                Id = JsonString(item, "definition_id").Trim(),
                Label = JsonString(item, "label").Trim(),
                Category = JsonString(item, "category").Trim(),
                Minimum = JsonDoubleValue(item, "min_percent", -100.0),
                Maximum = JsonDoubleValue(item, "max_percent", 100.0),
                Default = JsonDoubleValue(item, "default_percent", 0.0),
                Value = JsonDoubleValue(item, "value", 0.0),
                Rule = JsonString(item, "rule").Trim(),
                Axis = JsonString(item, "axis").Trim(),
                Amount = JsonDoubleValue(item, "amount", 0.1),
                Feather = JsonLongValue(item, "feather"),
                Falloff = JsonString(item, "falloff").Trim(),
                Mirror = JsonString(item, "mirror_mode").Trim(),
            })
            .Where(item => item.Id.Length > 0)
            .OrderBy(item => item.Category, StringComparer.OrdinalIgnoreCase)
            .ThenBy(item => item.Label, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        var signature = string.Join("|", items.Select(item =>
            $"{item.Category}\u001f{item.Id}\u001f{item.Label}\u001f{item.Minimum:R}\u001f{item.Maximum:R}\u001f{item.Default:R}\u001f{item.Rule}\u001f{item.Axis}\u001f{item.Amount:R}\u001f{item.Feather}\u001f{item.Falloff}\u001f{item.Mirror}"));
        if (!string.Equals(signature, _morphDefinitionSignature, StringComparison.Ordinal))
        {
            _morphDefinitionSignature = signature;
            _morphSliders.Clear();
            _morphSliderStack.SuspendLayout();
            _morphSliderStack.Controls.Clear();
            _morphSliderStack.RowStyles.Clear();
            _morphSliderStack.RowCount = 0;
            string? category = null;
            foreach (var item in items)
            {
                if (!string.Equals(category, item.Category, StringComparison.Ordinal))
                {
                    category = item.Category.Length > 0 ? item.Category : "General";
                    var heading = new Label
                    {
                        Text = category,
                        AutoSize = true,
                        Font = new Font(Font, FontStyle.Bold),
                        ForeColor = ThemeAccent,
                        BackColor = ThemeSectionBackground,
                        Margin = new Padding(0, 5, 0, 4),
                    };
                    AddStackRow(_morphSliderStack, heading);
                }
                AddStackRow(_morphSliderStack, CreateMorphSlider(item.Element, item.Id, item.Label, item.Minimum, item.Maximum, item.Default, item.Value));
            }
            _morphSliderStack.ResumeLayout(performLayout: true);
        }
        else
        {
            foreach (var item in items)
            {
                if (_morphSliders.TryGetValue(item.Id, out var controls))
                {
                    SetMorphSliderValue(controls, item.Value);
                }
            }
        }
    }

    private Control CreateMorphSlider(
        JsonElement definition,
        string definitionId,
        string label,
        double minimum,
        double maximum,
        double defaultValue,
        double value)
    {
        const int resolution = 10;
        var track = new TrackBar
        {
            Name = $"MorphSlider_{definitionId}",
            Minimum = (int)Math.Floor(minimum * resolution),
            Maximum = (int)Math.Ceiling(maximum * resolution),
            TickFrequency = Math.Max(1, (int)Math.Round((maximum - minimum) * resolution / 8.0)),
            SmallChange = 1,
            LargeChange = 10,
            AutoSize = false,
            Height = 34,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0),
        };
        var numeric = new NumericUpDown();
        ConfigureNumeric(
            numeric,
            decimalPlaces: 1,
            minimum: (decimal)minimum,
            maximum: (decimal)maximum,
            value: (decimal)Math.Clamp(value, minimum, maximum),
            increment: 1.0M);
        numeric.Width = 74;
        var controls = new MorphSliderControls
        {
            DefinitionId = definitionId,
            Minimum = minimum,
            Maximum = maximum,
            DefaultValue = defaultValue,
            Track = track,
            Numeric = numeric,
        };
        _morphSliders[definitionId] = controls;
        SetMorphSliderValue(controls, value);
        track.MouseDown += (_, _) =>
        {
            _morphActiveChangeId = Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture);
            SendMorphValue(controls, "begin", _morphActiveChangeId);
        };
        track.ValueChanged += (_, _) =>
        {
            if (controls.Synchronizing)
            {
                return;
            }
            controls.Synchronizing = true;
            numeric.Value = Math.Clamp((decimal)track.Value / resolution, numeric.Minimum, numeric.Maximum);
            controls.Synchronizing = false;
            SendMorphValue(controls, _morphActiveChangeId.Length > 0 ? "update" : "end", _morphActiveChangeId);
        };
        track.MouseUp += (_, _) =>
        {
            if (_morphActiveChangeId.Length > 0)
            {
                SendMorphValue(controls, "end", _morphActiveChangeId);
                _morphActiveChangeId = string.Empty;
            }
        };
        numeric.ValueChanged += (_, _) =>
        {
            if (controls.Synchronizing)
            {
                return;
            }
            controls.Synchronizing = true;
            track.Value = Math.Clamp((int)Math.Round((double)numeric.Value * resolution), track.Minimum, track.Maximum);
            controls.Synchronizing = false;
            SendMorphValue(controls, "end", Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture));
        };
        var reset = StyledActionButton("Reset", () =>
        {
            SetMorphSliderValue(controls, controls.DefaultValue);
            SendMorphValue(controls, "end", Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture));
        });
        reset.MinimumSize = new Size(58, reset.MinimumSize.Height);
        var edit = StyledActionButton("Edit...", () => ShowMorphAuthorDialog(definition));
        var delete = StyledActionButton("Delete", () => WriteCommandRequest(
            "morph_delete_definition",
            new Dictionary<string, object?> { ["definition_id"] = definitionId }));
        var labelControl = new Label
        {
            Text = label.Length > 0 ? label : definitionId,
            AutoSize = true,
            ForeColor = ThemeText,
            BackColor = ThemeSectionBackground,
            Margin = new Padding(0, 0, 0, 2),
        };
        return StackControls(labelControl, track, ButtonRow(numeric, reset, edit, delete));
    }

    private static void SetMorphSliderValue(MorphSliderControls controls, double value)
    {
        const int resolution = 10;
        controls.Synchronizing = true;
        try
        {
            var normalized = Math.Clamp(value, controls.Minimum, controls.Maximum);
            controls.Track.Value = Math.Clamp((int)Math.Round(normalized * resolution), controls.Track.Minimum, controls.Track.Maximum);
            controls.Numeric.Value = Math.Clamp((decimal)normalized, controls.Numeric.Minimum, controls.Numeric.Maximum);
        }
        finally
        {
            controls.Synchronizing = false;
        }
    }

    private void SendMorphValue(MorphSliderControls controls, string phase, string changeId)
    {
        var id = changeId.Length > 0 ? changeId : Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture);
        _morphBusy = true;
        var requestId = WriteCommandRequest("morph_change", new Dictionary<string, object?>
        {
            ["definition_id"] = controls.DefinitionId,
            ["value"] = (double)controls.Numeric.Value,
            ["phase"] = phase,
            ["change_id"] = id,
        });
        if (requestId <= 0)
        {
            _morphBusy = false;
        }
        else if (phase == "end")
        {
            _morphEndRequestId = requestId;
        }
    }

    private void ApplyMorphRefitStatus(JsonElement root)
    {
        var drivers = JsonIntValues(root, "driver_submesh_indices");
        _morphDriverPartIndices.Clear();
        _morphDriverPartIndices.UnionWith(drivers);
        _morphDriverStatus.Text = drivers.Count > 0
            ? $"Driver: {string.Join(", ", drivers.Select(MorphPartDisplayName))}"
            : "Driver: not set";
        if (!root.TryGetProperty("refit", out var refit) || refit.ValueKind != JsonValueKind.Object)
        {
            _morphBindingStatus.Text = "Garment: not bound";
            return;
        }
        var garments = JsonIntValues(refit, "garment_submesh_indices");
        var bound = JsonLongValue(refit, "bound_vertex_count");
        if (garments.Count == 0 || bound <= 0)
        {
            _morphBindingStatus.Text = "Garment: not bound";
            _morphBindingStatus.ForeColor = ThemeMutedText;
            return;
        }
        var maximum = JsonDoubleValue(refit, "maximum_distance", 0.0);
        var p95 = JsonDoubleValue(refit, "p95_distance", 0.0);
        var warning = JsonBoolean(refit, "distance_warning");
        _morphBindingStatus.Text = $"Garment: {string.Join(", ", garments.Select(MorphPartDisplayName))} | {bound} vertices | max {maximum:G4} | p95 {p95:G4}";
        _morphBindingStatus.ForeColor = warning ? Color.Gold : ThemeMutedText;
    }

    private IReadOnlyList<MorphPartChoice> SelectedMorphParts()
    {
        return _viewport.SelectedSubmeshIndices
            .Where(index => index >= 0 && index < _document.Submeshes.Count)
            .Distinct()
            .OrderBy(index => index)
            .Select(index => new MorphPartChoice(index, _document.Submeshes[index].Name))
            .ToArray();
    }

    private string MorphPartDisplayName(int index)
    {
        return index >= 0 && index < _document.Submeshes.Count
            ? $"{_document.Submeshes[index].Name} (Part {index})"
            : $"Part {index}";
    }

    private void RequestMorphSetDriver()
    {
        var selected = SelectedMorphParts();
        if (selected.Count == 0)
        {
            _morphDiagnosticStatus.ForeColor = Color.Salmon;
            _morphDiagnosticStatus.Text = "Select one or more driver parts in the viewport, then choose Set Selected Driver Parts.";
            return;
        }
        WriteCommandRequest("morph_set_driver");
    }

    private void RequestMorphBind()
    {
        var selected = SelectedMorphParts();
        if (selected.Count == 0)
        {
            _morphDiagnosticStatus.ForeColor = Color.Salmon;
            _morphDiagnosticStatus.Text = "Select one or more garment parts in the viewport, then choose Bind Selected Garment Parts.";
            return;
        }
        var overlap = selected.Where(part => _morphDriverPartIndices.Contains(part.Index)).ToArray();
        if (overlap.Length > 0)
        {
            _morphDiagnosticStatus.ForeColor = Color.Salmon;
            _morphDiagnosticStatus.Text = $"A part cannot be both driver and garment: {string.Join(", ", overlap.Select(part => part.Name))}.";
            return;
        }
        WriteCommandRequest("morph_bind");
    }

    private void ShowMorphAuthorDialog(JsonElement? definition = null)
    {
        if (_morphWizardSequenceActive)
        {
            _morphDiagnosticStatus.ForeColor = Color.Salmon;
            _morphDiagnosticStatus.Text = "Finish the current Morph profile preview or save before opening another wizard.";
            return;
        }
        using var dialog = new MorphAuthorDialog(
            _morphProfile.SelectedItem is MorphChoice profile ? profile.Id : string.Empty,
            _morphProfile.SelectedItem is MorphChoice namedProfile ? namedProfile.Name : string.Empty,
            definition,
            SelectedMorphParts,
            ThemeWindowBackground,
            ThemeSectionBackground,
            ThemeInputBackground,
            ThemeText,
            ThemeMutedText);
        dialog.PreviewRequested += (_, value) => PreviewMorphAuthorDialog(dialog, definition, value);
        var result = dialog.ShowDialog(this);
        if (result == DialogResult.OK)
        {
            var commands = new List<(string Command, Dictionary<string, object?> Payload)>();
            if (dialog.PreviewWasSent)
            {
                commands.Add(("morph_change", MorphWizardChangePayload(dialog.DefinitionId, 0.0)));
            }
            commands.Add(("morph_author_definition", MorphAuthorPayload(dialog.Payload, definition)));
            commands.Add(("morph_change", MorphWizardChangePayload(dialog.DefinitionId, 0.0)));
            commands.Add(("morph_save_profile", new Dictionary<string, object?>()));
            _ = BeginMorphWizardCommandSequence(
                null,
                commands,
                "Morph profile saved at zero. Bake remains a separate action.");
            return;
        }
        if (!dialog.PreviewWasSent)
        {
            return;
        }
        var cancellation = new List<(string Command, Dictionary<string, object?> Payload)>
        {
            ("morph_change", MorphWizardChangePayload(dialog.DefinitionId, 0.0)),
        };
        if (definition.HasValue)
        {
            cancellation.Add(("morph_author_definition", OriginalMorphAuthorPayload(
                    definition.Value,
                    _morphProfile.SelectedItem is MorphChoice currentProfile ? currentProfile.Id : dialog.ProfileId,
                    _morphProfile.SelectedItem is MorphChoice currentNamedProfile ? currentNamedProfile.Name : dialog.ProfileName)));
            cancellation.Add(("morph_change", MorphWizardChangePayload(dialog.DefinitionId, 0.0)));
        }
        else
        {
            cancellation.Add(("morph_delete_definition", new Dictionary<string, object?>
            {
                ["definition_id"] = dialog.DefinitionId,
            }));
        }
        _ = BeginMorphWizardCommandSequence(
            null,
            cancellation,
            "Morph profile preview cancelled and temporary changes removed.");
    }

    private void PreviewMorphAuthorDialog(MorphAuthorDialog dialog, JsonElement? definition, double value)
    {
        var commands = new List<(string Command, Dictionary<string, object?> Payload)>();
        if (dialog.PreviewDefinitionCreated)
        {
            commands.Add(("morph_change", MorphWizardChangePayload(dialog.DefinitionId, 0.0)));
        }
        commands.Add(("morph_author_definition", MorphAuthorPayload(dialog.Payload, definition)));
        commands.Add(("morph_change", MorphWizardChangePayload(dialog.DefinitionId, value)));
        if (!BeginMorphWizardCommandSequence(
                dialog,
                commands,
                $"Morph preview ready at {value:0.#}%.",
                accepted =>
                {
                    if (accepted)
                    {
                        dialog.MarkPreviewDefinitionCreated();
                    }
                }))
        {
            dialog.SetProtocolBusy(false, "Another Morph profile command is still running.");
        }
    }

    private static Dictionary<string, object?> MorphWizardChangePayload(
        string definitionId,
        double value)
    {
        return new Dictionary<string, object?>
        {
            ["definition_id"] = definitionId,
            ["value"] = value,
            ["phase"] = "end",
            ["change_id"] = Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture),
        };
    }

    private bool BeginMorphWizardCommandSequence(
        MorphAuthorDialog? dialog,
        IEnumerable<(string Command, Dictionary<string, object?> Payload)> commands,
        string successMessage,
        Action<bool>? completed = null)
    {
        if (_morphWizardSequenceActive)
        {
            return false;
        }
        foreach (var (command, payload) in commands)
        {
            _morphWizardCommandQueue.Enqueue((command, new Dictionary<string, object?>(payload)));
        }
        if (_morphWizardCommandQueue.Count == 0)
        {
            return false;
        }
        _morphWizardActiveDialog = dialog;
        _morphWizardSequenceCompleted = completed;
        _morphWizardSuccessMessage = successMessage;
        _morphWizardSequenceActive = true;
        dialog?.SetProtocolBusy(true, "Applying the correlated Morph preview commands...");
        SendNextMorphWizardCommand();
        return _morphWizardCommandRequestId > 0 || _morphWizardCommandQueue.Count > 0;
    }

    private void SendNextMorphWizardCommand()
    {
        if (_morphWizardCommandRequestId > 0)
        {
            return;
        }
        if (_morphWizardCommandQueue.Count == 0)
        {
            CompleteMorphWizardCommandSequence(accepted: true);
            return;
        }
        var (command, payload) = _morphWizardCommandQueue.Dequeue();
        _morphWizardCommandRequestId = WriteCommandRequest(command, payload);
        if (_morphWizardCommandRequestId <= 0)
        {
            CompleteMorphWizardCommandSequence(accepted: false);
        }
    }

    private void CompleteMorphWizardCommandSequence(bool accepted)
    {
        var hadSequence = _morphWizardSequenceActive
            || _morphWizardCommandRequestId > 0
            || _morphWizardCommandQueue.Count > 0
            || _morphWizardActiveDialog is not null
            || _morphWizardSequenceCompleted is not null
            || _morphWizardSuccessMessage.Length > 0;
        if (!hadSequence)
        {
            return;
        }
        _morphWizardCommandRequestId = 0;
        _morphWizardCommandQueue.Clear();
        _morphWizardSequenceActive = false;
        var dialog = _morphWizardActiveDialog;
        var completed = _morphWizardSequenceCompleted;
        var successMessage = _morphWizardSuccessMessage;
        _morphWizardActiveDialog = null;
        _morphWizardSequenceCompleted = null;
        _morphWizardSuccessMessage = string.Empty;
        completed?.Invoke(accepted);
        if (dialog is not null && !dialog.IsDisposed)
        {
            dialog.SetProtocolBusy(
                false,
                accepted ? successMessage : "The Morph preview command was rejected; no further preview commands were sent.");
        }
        _statusLabel.Text = accepted
            ? successMessage
            : "Morph profile command sequence stopped after a rejected step.";
        ResumePendingFinishIfClear();
    }

    private static Dictionary<string, object?> MorphAuthorPayload(
        Dictionary<string, object?> payload,
        JsonElement? definition)
    {
        payload["preserve_selection"] = false;
        payload["source_definition_id"] = definition.HasValue
            ? JsonString(definition.Value, "definition_id").Trim()
            : string.Empty;
        payload["local_basis"] = MorphLocalBasis(definition);
        return payload;
    }

    private static Dictionary<string, object?> OriginalMorphAuthorPayload(
        JsonElement definition,
        string profileId,
        string profileName)
    {
        var definitionId = JsonString(definition, "definition_id").Trim();
        return new Dictionary<string, object?>
        {
            ["profile_id"] = profileId,
            ["profile_name"] = profileName,
            ["definition_id"] = definitionId,
            ["label"] = JsonString(definition, "label"),
            ["category"] = JsonString(definition, "category"),
            ["rule"] = JsonString(definition, "rule"),
            ["axis"] = JsonString(definition, "axis"),
            ["amount"] = JsonDoubleValue(definition, "amount", 0.1),
            ["feather"] = JsonLongValue(definition, "feather"),
            ["falloff"] = JsonString(definition, "falloff"),
            ["mirror_mode"] = JsonString(definition, "mirror_mode"),
            ["min_percent"] = JsonDoubleValue(definition, "min_percent", -100.0),
            ["max_percent"] = JsonDoubleValue(definition, "max_percent", 100.0),
            ["default_percent"] = JsonDoubleValue(definition, "default_percent", 0.0),
            ["preserve_selection"] = true,
            ["source_definition_id"] = definitionId,
            ["local_basis"] = MorphLocalBasis(definition),
        };
    }

    private static double[][] MorphLocalBasis(JsonElement? definition)
    {
        static double[][] Identity() =>
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ];
        if (!definition.HasValue
            || !definition.Value.TryGetProperty("local_basis", out var rawBasis)
            || rawBasis.ValueKind != JsonValueKind.Array)
        {
            return Identity();
        }
        var basis = new List<double[]>();
        foreach (var rawAxis in rawBasis.EnumerateArray())
        {
            if (rawAxis.ValueKind != JsonValueKind.Array)
            {
                return Identity();
            }
            var axis = rawAxis.EnumerateArray()
                .Select(value => value.TryGetDouble(out var number) && double.IsFinite(number) ? number : double.NaN)
                .ToArray();
            if (axis.Length != 3 || axis.Any(value => !double.IsFinite(value)))
            {
                return Identity();
            }
            basis.Add(axis);
        }
        return basis.Count == 3 ? basis.ToArray() : Identity();
    }

    private void SaveMorphPreset()
    {
        using var dialog = new MorphPresetNameDialog(ThemeWindowBackground, ThemeInputBackground, ThemeText);
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }
        WriteCommandRequest("morph_save_preset", new Dictionary<string, object?>
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
