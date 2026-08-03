using System.Globalization;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed class MorphAuthorDialog : Form
{
    private readonly IReadOnlyList<MorphPartChoice> _allParts;
    private readonly IReadOnlyList<MorphPartChoice> _initialParts;
    private readonly Dictionary<string, object?> _capturedMeshSelection;
    private readonly Color _section;
    private readonly Color _input;
    private readonly Color _text;
    private readonly Color _muted;
    private readonly Label _stepTitle = new();
    private readonly Label _stepDescription = new();
    private readonly Label _validation = new();
    private readonly Panel _pageHost = new();
    private readonly List<Control> _pages = new();
    private readonly Button _back = new();
    private readonly Button _next = new();
    private readonly Button _finish = new();
    private readonly Button _cancel = new();
    private readonly List<Button> _previewButtons = new();
    private readonly TextBox _profileName = new();
    private readonly TextBox _profileId = new();
    private readonly TextBox _definitionId = new();
    private readonly TextBox _label = new();
    private readonly TextBox _category = new();
    private readonly ComboBox _rule = new();
    private readonly ComboBox _axis = new();
    private readonly ComboBox _falloff = new();
    private readonly ComboBox _mirror = new();
    private readonly NumericUpDown _amount = new();
    private readonly NumericUpDown _feather = new();
    private readonly NumericUpDown _minimum = new();
    private readonly NumericUpDown _maximum = new();
    private readonly NumericUpDown _default = new();
    private readonly CheckedListBox _partList = new();
    private readonly RadioButton _useParts = new();
    private readonly RadioButton _useMeshSelection = new();
    private readonly CheckBox _replaceExistingSelection = new();
    private readonly Label _meshSelectionSummary = new();
    private readonly Panel _axisField = new();
    private readonly Panel _advancedBody = new();
    private readonly Label _review = new();
    private readonly bool _editingExistingDefinition;
    private int _pageIndex;
    private bool _protocolBusy;

    public event Action<MorphAuthorDialog, double>? PreviewRequested;

    public bool PreviewWasSent { get; private set; }
    public bool PreviewDefinitionCreated { get; private set; }
    public string ProfileId => _profileId.Text.Trim();
    public string ProfileName => _profileName.Text.Trim();
    public string DefinitionId => _definitionId.Text.Trim();
    public bool PreserveExistingSelection =>
        _editingExistingDefinition && !_replaceExistingSelection.Checked;

    public Dictionary<string, object?> Payload => new()
    {
        ["profile_id"] = ProfileId,
        ["profile_name"] = ProfileName,
        ["definition_id"] = DefinitionId,
        ["label"] = _label.Text.Trim(),
        ["category"] = _category.Text.Trim(),
        ["rule"] = ComboValue(_rule).ToLowerInvariant(),
        ["axis"] = ComboValue(_axis).ToLowerInvariant(),
        ["amount"] = (double)_amount.Value,
        ["feather"] = (int)_feather.Value,
        ["falloff"] = ComboValue(_falloff).ToLowerInvariant(),
        ["mirror_mode"] = ComboValue(_mirror).ToLowerInvariant(),
        ["min_percent"] = (double)_minimum.Value,
        ["max_percent"] = (double)_maximum.Value,
        ["default_percent"] = (double)_default.Value,
        ["local_selection"] = LocalSelectionPayload(),
    };

    public MorphAuthorDialog(
        string profileId,
        string profileName,
        JsonElement? definition,
        IReadOnlyList<MorphPartChoice> allParts,
        IReadOnlyList<MorphPartChoice> selectedParts,
        Dictionary<string, object?> capturedMeshSelection,
        Color background,
        Color section,
        Color input,
        Color text,
        Color muted)
    {
        _allParts = allParts;
        _initialParts = selectedParts;
        _capturedMeshSelection = new Dictionary<string, object?>(capturedMeshSelection);
        _section = section;
        _input = input;
        _text = text;
        _muted = muted;
        var hasDefinition = definition.HasValue && definition.Value.ValueKind == JsonValueKind.Object;
        _editingExistingDefinition = hasDefinition;

        Text = hasDefinition ? "Edit Morph Profile Slider" : "Create Morph Profile";
        Name = "MorphProfileWizard";
        Width = 660;
        Height = 620;
        MinimumSize = new Size(560, 520);
        StartPosition = FormStartPosition.CenterParent;
        BackColor = background;
        ForeColor = text;
        FormBorderStyle = FormBorderStyle.SizableToolWindow;

        _stepTitle.Name = "MorphWizardStepTitle";
        _validation.Name = "MorphWizardValidationLabel";
        _profileName.Name = "MorphWizardProfileName";
        _profileId.Name = "MorphWizardProfileId";
        _definitionId.Name = "MorphWizardDefinitionId";
        _label.Name = "MorphWizardSliderLabel";
        _category.Name = "MorphWizardCategory";
        _rule.Name = "MorphWizardDeformation";
        _axis.Name = "MorphWizardAxis";
        _falloff.Name = "MorphWizardFalloff";
        _mirror.Name = "MorphWizardMirror";
        _amount.Name = "MorphWizardAmount";
        _feather.Name = "MorphWizardFeather";
        _minimum.Name = "MorphWizardMinimum";
        _maximum.Name = "MorphWizardMaximum";
        _default.Name = "MorphWizardDefault";
        _axisField.Name = "MorphWizardAxisField";
        _advancedBody.Name = "MorphWizardAdvancedBody";
        _review.Name = "MorphWizardReview";

        _profileName.Text = profileName.Length > 0 ? profileName : "My Morph Profile";
        _profileId.Text = profileId.Length > 0 ? profileId : $"profile-{Guid.NewGuid():N}"[..18];
        _definitionId.Text = DefinitionString(definition, "definition_id", $"slider-{Guid.NewGuid():N}"[..17]);
        _label.Text = DefinitionString(definition, "label", "New Slider");
        _category.Text = DefinitionString(definition, "category", "General");

        ConfigureTextBox(_profileName);
        ConfigureTextBox(_profileId);
        ConfigureTextBox(_definitionId);
        _profileId.ReadOnly = true;
        _definitionId.ReadOnly = true;
        ConfigureTextBox(_label);
        ConfigureTextBox(_category);
        ConfigureCombo(_rule, "Volume", "Scale", "Move", "Flatten", "Taper", "Twist");
        ConfigureCombo(_axis, "X", "Y", "Z");
        ConfigureCombo(_falloff, "Smooth", "Linear", "Constant");
        ConfigureCombo(_mirror, "Off", "X", "Y", "Z");
        SelectComboValue(_rule, DefinitionString(definition, "rule", "volume"));
        SelectComboValue(_axis, DefinitionString(definition, "axis", "y"));
        SelectComboValue(_falloff, DefinitionString(definition, "falloff", "smooth"));
        SelectComboValue(_mirror, DefinitionString(definition, "mirror_mode", "off"));
        ConfigureNumber(_amount, -1000, 1000, DefinitionDouble(definition, "amount", 0.1), 0.01M, 4);
        ConfigureNumber(_feather, 0, 64, DefinitionLong(definition, "feather", 2), 1, 0);
        ConfigureNumber(_minimum, -1000, 1000, DefinitionDouble(definition, "min_percent", -100.0), 5, 1);
        ConfigureNumber(_maximum, -1000, 1000, DefinitionDouble(definition, "max_percent", 100.0), 5, 1);
        ConfigureNumber(_default, -1000, 1000, DefinitionDouble(definition, "default_percent", 0.0), 1, 1);

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 4,
            Padding = new Padding(16),
            BackColor = section,
        };
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        _stepTitle.AutoSize = true;
        _stepTitle.Font = new Font(Font.FontFamily, 13f, FontStyle.Bold);
        _stepTitle.ForeColor = text;
        _stepTitle.Margin = new Padding(0, 0, 0, 4);
        _stepDescription.AutoSize = true;
        _stepDescription.MaximumSize = new Size(590, 0);
        _stepDescription.ForeColor = muted;
        _stepDescription.Margin = new Padding(0, 0, 0, 10);
        _pageHost.Dock = DockStyle.Fill;
        _pageHost.BackColor = section;

        _pages.Add(BuildProfilePage());
        _pages.Add(BuildPartsPage());
        _pages.Add(BuildDeformationPage());
        _pages.Add(BuildReviewPage());
        foreach (var page in _pages)
        {
            page.Dock = DockStyle.Fill;
            page.Visible = false;
            _pageHost.Controls.Add(page);
        }

        _validation.AutoSize = true;
        _validation.ForeColor = Color.Salmon;
        _validation.Margin = new Padding(0, 5, 10, 0);
        var navigation = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            FlowDirection = FlowDirection.RightToLeft,
            WrapContents = false,
        };
        _cancel.Name = "MorphWizardCancelButton";
        _cancel.Text = "Cancel";
        _cancel.DialogResult = DialogResult.Cancel;
        _cancel.AutoSize = true;
        _finish.Name = "MorphWizardFinishButton";
        _finish.Text = "Save Profile";
        _finish.AutoSize = true;
        _next.Name = "MorphWizardNextButton";
        _next.Text = "Next";
        _next.AutoSize = true;
        _back.Name = "MorphWizardBackButton";
        _back.Text = "Back";
        _back.AutoSize = true;
        _finish.Click += (_, _) => Finish();
        _next.Click += (_, _) => MovePage(1);
        _back.Click += (_, _) => MovePage(-1);
        navigation.Controls.Add(_cancel);
        navigation.Controls.Add(_finish);
        navigation.Controls.Add(_next);
        navigation.Controls.Add(_back);
        navigation.Controls.Add(_validation);

        root.Controls.Add(_stepTitle, 0, 0);
        root.Controls.Add(_stepDescription, 0, 1);
        root.Controls.Add(_pageHost, 0, 2);
        root.Controls.Add(navigation, 0, 3);
        Controls.Add(root);
        CancelButton = _cancel;
        InitializeSelectionPage();
        ShowPage(0);
    }

    private Control BuildProfilePage()
    {
        var page = Page();
        AddField(page, "Profile name", _profileName);
        var hint = Hint("Use a friendly name. Stable profile and slider IDs are generated automatically and shown under Advanced.");
        AddRow(page, hint);
        return page;
    }

    private Control BuildPartsPage()
    {
        var page = Page();
        _replaceExistingSelection.Name = "MorphWizardReplaceSelection";
        _replaceExistingSelection.Text = "Replace this slider's authored mesh region";
        _replaceExistingSelection.AutoSize = true;
        _replaceExistingSelection.ForeColor = _text;
        _replaceExistingSelection.BackColor = _section;
        _replaceExistingSelection.Visible = _editingExistingDefinition;
        _useParts.Name = "MorphWizardUseParts";
        _useParts.Text = "Choose whole parts";
        _useParts.AutoSize = true;
        _useParts.ForeColor = _text;
        _useParts.BackColor = _section;
        _useMeshSelection.Name = "MorphWizardUseMeshSelection";
        _useMeshSelection.Text = "Use viewport mesh selection captured when this wizard opened";
        _useMeshSelection.AutoSize = true;
        _useMeshSelection.ForeColor = _text;
        _useMeshSelection.BackColor = _section;
        _partList.Name = "MorphWizardPartList";
        _partList.Dock = DockStyle.Top;
        _partList.Height = 210;
        _partList.CheckOnClick = true;
        _partList.BackColor = _input;
        _partList.ForeColor = _text;
        _partList.BorderStyle = BorderStyle.FixedSingle;
        _meshSelectionSummary.Name = "MorphWizardMeshSelectionSummary";
        _meshSelectionSummary.AutoSize = true;
        _meshSelectionSummary.ForeColor = _muted;
        _meshSelectionSummary.BackColor = _section;
        _meshSelectionSummary.MaximumSize = new Size(580, 0);
        _useParts.CheckedChanged += (_, _) => UpdateSelectionChoice();
        _useMeshSelection.CheckedChanged += (_, _) => UpdateSelectionChoice();
        _replaceExistingSelection.CheckedChanged += (_, _) => UpdateSelectionChoice();
        _partList.ItemCheck += (_, _) =>
        {
            if (IsHandleCreated)
            {
                BeginInvoke((Action)UpdateReview);
            }
        };
        AddRow(page, _replaceExistingSelection);
        AddRow(page, Hint(_editingExistingDefinition
            ? "The authored mesh region is preserved unless you explicitly replace it below."
            : "Choose parts directly here, or use the acknowledged vertex selection that was captured from the viewport."));
        AddRow(page, _useParts);
        AddRow(page, _partList);
        AddRow(page, _useMeshSelection);
        AddRow(page, _meshSelectionSummary);
        return page;
    }

    private Control BuildDeformationPage()
    {
        var page = Page();
        AddField(page, "Slider label", _label);
        AddField(page, "Deformation", _rule);
        var axisLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            ColumnCount = 1,
            RowCount = 0,
            BackColor = _section,
            Margin = new Padding(0),
        };
        axisLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        AddField(axisLayout, "Axis", _axis);
        _axisField.Dock = DockStyle.Top;
        _axisField.AutoSize = true;
        _axisField.Controls.Add(axisLayout);
        AddRow(page, _axisField);
        AddField(page, "Amount at 100%", _amount);

        var advancedToggle = new Button
        {
            Text = "Advanced ▸",
            AutoSize = true,
            FlatStyle = FlatStyle.Flat,
            ForeColor = _muted,
            BackColor = _section,
            Margin = new Padding(0, 12, 0, 4),
        };
        advancedToggle.Name = "MorphWizardAdvancedToggle";
        _advancedBody.Dock = DockStyle.Top;
        _advancedBody.AutoSize = true;
        _advancedBody.Visible = false;
        _advancedBody.BackColor = _section;
        var advanced = Page();
        advanced.Dock = DockStyle.Top;
        advanced.AutoSize = true;
        advanced.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        advanced.AutoScroll = false;
        AddField(advanced, "Category", _category);
        AddField(advanced, "Profile ID", _profileId);
        AddField(advanced, "Slider ID", _definitionId);
        AddField(advanced, "Feather rings", _feather);
        AddField(advanced, "Falloff", _falloff);
        AddField(advanced, "Mirror", _mirror);
        AddField(advanced, "Minimum percent", _minimum);
        AddField(advanced, "Default percent", _default);
        AddField(advanced, "Maximum percent", _maximum);
        AddRow(advanced, Hint("Local basis: preserve the current profile basis (World XYZ for new profiles)."));
        _advancedBody.Controls.Add(advanced);
        advancedToggle.Click += (_, _) =>
        {
            _advancedBody.Visible = !_advancedBody.Visible;
            advancedToggle.Text = _advancedBody.Visible ? "Advanced ▾" : "Advanced ▸";
            _advancedBody.PerformLayout();
            page.PerformLayout();
        };
        AddRow(page, advancedToggle);
        AddRow(page, _advancedBody);
        _rule.SelectedIndexChanged += (_, _) => UpdateAxisVisibility();
        UpdateAxisVisibility();
        return page;
    }

    private Control BuildReviewPage()
    {
        var page = Page();
        _review.AutoSize = true;
        _review.MaximumSize = new Size(580, 0);
        _review.ForeColor = _text;
        _review.Margin = new Padding(0, 0, 0, 12);
        AddRow(page, _review);
        AddRow(page, Hint("Preview changes are temporary. Save Profile returns the slider to zero and stores the v2 profile; it does not Bake mesh changes."));
        var previews = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            WrapContents = true,
            BackColor = _section,
            Margin = new Padding(0, 12, 0, 0),
        };
        previews.Controls.Add(PreviewButton("MorphWizardPreviewMinimum", "Preview Minimum", () => (double)_minimum.Value));
        previews.Controls.Add(PreviewButton("MorphWizardPreviewDefault", "Preview Default", () => (double)_default.Value));
        previews.Controls.Add(PreviewButton("MorphWizardPreviewMaximum", "Preview Maximum", () => (double)_maximum.Value));
        AddRow(page, previews);
        return page;
    }

    private Button PreviewButton(string name, string text, Func<double> value)
    {
        var button = new Button { Name = name, Text = text, AutoSize = true };
        button.Click += (_, _) =>
        {
            if (!ValidateAll())
            {
                return;
            }
            PreviewWasSent = true;
            PreviewRequested?.Invoke(this, value());
            if (!_protocolBusy)
            {
                _validation.ForeColor = _muted;
                _validation.Text = $"Showing {text.Replace("Preview ", string.Empty).ToLowerInvariant()} preview. Save or Cancel returns it to zero.";
            }
        };
        _previewButtons.Add(button);
        return button;
    }

    public void SetProtocolBusy(bool busy, string message)
    {
        _protocolBusy = busy;
        UseWaitCursor = busy;
        _back.Enabled = !busy;
        _next.Enabled = !busy;
        _finish.Enabled = !busy;
        _cancel.Enabled = !busy;
        foreach (var button in _previewButtons)
        {
            button.Enabled = !busy;
        }
        _validation.ForeColor = busy ? _muted : _text;
        _validation.Text = message;
    }

    public void MarkPreviewDefinitionCreated()
    {
        PreviewDefinitionCreated = true;
    }

    private void InitializeSelectionPage()
    {
        var initiallySelected = _initialParts.Select(part => part.Index).ToHashSet();
        _partList.BeginUpdate();
        foreach (var part in _allParts)
        {
            _partList.Items.Add(part, initiallySelected.Contains(part.Index));
        }
        _partList.EndUpdate();
        var meshVertexCount = SelectionMapCount(_capturedMeshSelection, "vertices_by_submesh");
        var meshFaceCount = SelectionMapCount(_capturedMeshSelection, "faces_by_submesh");
        var meshEdgeCount = SelectionMapCount(_capturedMeshSelection, "edges_by_submesh");
        var hasMeshSelection = meshVertexCount + meshFaceCount + meshEdgeCount > 0;
        _meshSelectionSummary.Text = hasMeshSelection
            ? $"Captured mesh selection: {meshVertexCount} vertices, {meshEdgeCount} edges, {meshFaceCount} faces."
            : "No acknowledged viewport mesh selection was available when the wizard opened.";
        _useMeshSelection.Enabled = hasMeshSelection;
        _useParts.Checked = initiallySelected.Count > 0 || !hasMeshSelection;
        _useMeshSelection.Checked = !_useParts.Checked && hasMeshSelection;
        _replaceExistingSelection.Checked = false;
        UpdateSelectionChoice();
    }

    private void UpdateSelectionChoice()
    {
        var replacementEnabled = !PreserveExistingSelection;
        _useParts.Enabled = replacementEnabled;
        _useMeshSelection.Enabled = replacementEnabled && CapturedMeshSelectionHasElements();
        _partList.Enabled = replacementEnabled && _useParts.Checked;
        _validation.Text = string.Empty;
        UpdateReview();
    }

    private IReadOnlyList<MorphPartChoice> SelectedParts() =>
        _partList.CheckedItems.Cast<MorphPartChoice>()
            .OrderBy(part => part.Index)
            .ToArray();

    private Dictionary<string, object?> LocalSelectionPayload()
    {
        if (_useParts.Checked)
        {
            var sourceIndices = SelectedParts().Select(part => part.Index).ToArray();
            return new Dictionary<string, object?>
            {
                ["vertices_by_submesh"] = new Dictionary<string, object?>(),
                ["edges_by_submesh"] = new Dictionary<string, object?>(),
                ["faces_by_submesh"] = new Dictionary<string, object?>(),
                ["source_indices"] = sourceIndices,
                ["sources"] = sourceIndices,
                ["empty"] = sourceIndices.Length == 0,
            };
        }
        var captured = new Dictionary<string, object?>(_capturedMeshSelection)
        {
            ["source_indices"] = Array.Empty<int>(),
            ["sources"] = Array.Empty<int>(),
            ["empty"] = !CapturedMeshSelectionHasElements(),
        };
        return captured;
    }

    private bool CapturedMeshSelectionHasElements() =>
        SelectionMapCount(_capturedMeshSelection, "vertices_by_submesh")
        + SelectionMapCount(_capturedMeshSelection, "edges_by_submesh")
        + SelectionMapCount(_capturedMeshSelection, "faces_by_submesh") > 0;

    private static int SelectionMapCount(
        IReadOnlyDictionary<string, object?> selection,
        string key)
    {
        if (!selection.TryGetValue(key, out var raw) || raw is null)
        {
            return 0;
        }
        var value = JsonSerializer.SerializeToElement(raw);
        if (value.ValueKind != JsonValueKind.Object)
        {
            return 0;
        }
        var count = 0;
        foreach (var group in value.EnumerateObject())
        {
            if (group.Value.ValueKind == JsonValueKind.Array)
            {
                count += group.Value.GetArrayLength();
            }
        }
        return count;
    }

    private void MovePage(int delta)
    {
        if (delta > 0 && !ValidatePage(_pageIndex))
        {
            return;
        }
        ShowPage(Math.Clamp(_pageIndex + delta, 0, _pages.Count - 1));
    }

    private void ShowPage(int index)
    {
        _pageIndex = index;
        for (var page = 0; page < _pages.Count; page++)
        {
            _pages[page].Visible = page == index;
        }
        var titles = new[] { "1. Profile", "2. Parts", "3. Deformation", "4. Preview & Save" };
        var descriptions = new[]
        {
            "Name the profile people will choose in Morph & Refit.",
            _editingExistingDefinition
                ? "Keep the authored mesh region, or explicitly replace it with parts or the captured viewport selection."
                : "Choose whole parts here, or use the viewport mesh selection captured when the wizard opened.",
            "Name the slider and choose how the selected mesh region deforms.",
            "Check the setup at its minimum, default, and maximum before saving.",
        };
        _stepTitle.Text = titles[index];
        _stepDescription.Text = descriptions[index];
        _back.Visible = index > 0;
        _next.Visible = index < _pages.Count - 1;
        _finish.Visible = index == _pages.Count - 1;
        AcceptButton = index == _pages.Count - 1 ? _finish : _next;
        _validation.Text = string.Empty;
        if (index == _pages.Count - 1)
        {
            UpdateReview();
        }
        _pages[index].BringToFront();
    }

    private bool ValidatePage(int index)
    {
        _validation.ForeColor = Color.Salmon;
        _validation.Text = string.Empty;
        if (index == 0 && ProfileName.Length == 0)
        {
            _validation.Text = "Enter a profile name.";
        }
        else if (index == 1
            && !PreserveExistingSelection
            && (_useParts.Checked ? SelectedParts().Count == 0 : !CapturedMeshSelectionHasElements()))
        {
            _validation.Text = "Choose at least one part or open the wizard with a viewport mesh selection.";
        }
        else if (index == 2 && _label.Text.Trim().Length == 0)
        {
            _validation.Text = "Enter a slider label.";
        }
        else if (index == 2 && DefinitionId.Length == 0)
        {
            _validation.Text = "Slider ID cannot be empty.";
        }
        else if (index == 2 && ProfileId.Length == 0)
        {
            _validation.Text = "Profile ID cannot be empty.";
        }
        else if (index == 2 && _minimum.Value >= _maximum.Value)
        {
            _validation.Text = "Minimum percent must be lower than maximum percent.";
        }
        else if (index == 2 && (_default.Value < _minimum.Value || _default.Value > _maximum.Value))
        {
            _validation.Text = "Default percent must be inside the selected range.";
        }
        return _validation.Text.Length == 0;
    }

    private bool ValidateAll()
    {
        for (var page = 0; page < _pages.Count - 1; page++)
        {
            if (ValidatePage(page))
            {
                continue;
            }
            var message = _validation.Text;
            ShowPage(page);
            _validation.ForeColor = Color.Salmon;
            _validation.Text = message;
            return false;
        }
        return true;
    }

    private void Finish()
    {
        if (_protocolBusy || !ValidateAll())
        {
            return;
        }
        DialogResult = DialogResult.OK;
        Close();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (_protocolBusy)
        {
            e.Cancel = true;
            return;
        }
        base.OnFormClosing(e);
    }

    private void UpdateAxisVisibility()
    {
        _axisField.Visible = !string.Equals(ComboValue(_rule), "Volume", StringComparison.OrdinalIgnoreCase);
    }

    private void UpdateReview()
    {
        var selectedParts = SelectedParts();
        var selectionText = PreserveExistingSelection
            ? "Existing authored mesh region"
            : _useParts.Checked
            ? selectedParts.Count > 0
                ? string.Join(", ", selectedParts.Select(part => part.Name))
                : "No parts chosen"
            : "Captured viewport mesh selection";
        var axis = _axisField.Visible ? $" on {ComboValue(_axis)}" : string.Empty;
        _review.Text = $"Profile: {ProfileName}\nSelection: {selectionText}\nSlider: {_label.Text.Trim()} — {ComboValue(_rule)}{axis}\nRange: {_minimum.Value}% to {_maximum.Value}% (default {_default.Value}%)";
    }

    private TableLayoutPanel Page()
    {
        var page = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            AutoSize = false,
            ColumnCount = 1,
            RowCount = 0,
            BackColor = _section,
            Padding = new Padding(0),
        };
        page.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        return page;
    }

    private Label Hint(string text)
    {
        return new Label
        {
            Text = text,
            AutoSize = true,
            MaximumSize = new Size(580, 0),
            ForeColor = _muted,
            BackColor = _section,
            Margin = new Padding(0, 4, 0, 8),
        };
    }

    private void ConfigureTextBox(TextBox box)
    {
        box.Dock = DockStyle.Top;
        box.BackColor = _input;
        box.ForeColor = _text;
        box.BorderStyle = BorderStyle.FixedSingle;
    }

    private void ConfigureCombo(ComboBox combo, params object[] values)
    {
        combo.Dock = DockStyle.Top;
        combo.DropDownStyle = ComboBoxStyle.DropDownList;
        combo.BackColor = _input;
        combo.ForeColor = _text;
        combo.FlatStyle = FlatStyle.Flat;
        combo.Items.AddRange(values);
    }

    private void ConfigureNumber(
        NumericUpDown control,
        decimal minimum,
        decimal maximum,
        double value,
        decimal increment,
        int decimalPlaces)
    {
        control.Dock = DockStyle.Top;
        control.Minimum = minimum;
        control.Maximum = maximum;
        control.Value = Math.Clamp((decimal)value, minimum, maximum);
        control.Increment = increment;
        control.DecimalPlaces = decimalPlaces;
        control.BackColor = _input;
        control.ForeColor = _text;
        control.BorderStyle = BorderStyle.FixedSingle;
    }

    private void AddField(TableLayoutPanel page, string caption, Control control)
    {
        AddRow(page, new Label
        {
            Text = caption,
            AutoSize = true,
            ForeColor = _muted,
            BackColor = _section,
            Margin = new Padding(0, 8, 0, 2),
        });
        AddRow(page, control);
    }

    private static void AddRow(TableLayoutPanel page, Control control)
    {
        var row = page.RowCount++;
        page.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        control.Dock = control is FlowLayoutPanel ? DockStyle.Top : control.Dock;
        page.Controls.Add(control, 0, row);
    }

    private static string ComboValue(ComboBox combo) =>
        Convert.ToString(combo.SelectedItem, CultureInfo.InvariantCulture)?.Trim() ?? string.Empty;

    private static void SelectComboValue(ComboBox combo, string value)
    {
        for (var index = 0; index < combo.Items.Count; index++)
        {
            if (string.Equals(ComboValueAt(combo, index), value, StringComparison.OrdinalIgnoreCase))
            {
                combo.SelectedIndex = index;
                return;
            }
        }
        combo.SelectedIndex = combo.Items.Count > 0 ? 0 : -1;
    }

    private static string ComboValueAt(ComboBox combo, int index) =>
        Convert.ToString(combo.Items[index], CultureInfo.InvariantCulture)?.Trim() ?? string.Empty;

    private static string DefinitionString(JsonElement? definition, string property, string fallback)
    {
        if (!definition.HasValue
            || definition.Value.ValueKind != JsonValueKind.Object
            || !definition.Value.TryGetProperty(property, out var value)
            || value.ValueKind != JsonValueKind.String)
        {
            return fallback;
        }
        return value.GetString()?.Trim() is { Length: > 0 } result ? result : fallback;
    }

    private static double DefinitionDouble(JsonElement? definition, string property, double fallback)
    {
        return definition.HasValue
               && definition.Value.ValueKind == JsonValueKind.Object
               && definition.Value.TryGetProperty(property, out var value)
               && value.TryGetDouble(out var result)
               && double.IsFinite(result)
            ? result
            : fallback;
    }

    private static int DefinitionLong(JsonElement? definition, string property, int fallback)
    {
        return definition.HasValue
               && definition.Value.ValueKind == JsonValueKind.Object
               && definition.Value.TryGetProperty(property, out var value)
               && value.TryGetInt32(out var result)
            ? result
            : fallback;
    }
}
