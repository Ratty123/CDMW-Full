namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// The Parts group in the Edit Mesh scene inspector: which parts the mesh has,
/// which one is selected, and what that part is made of.
/// </summary>
/// <remarks>
/// The list used to be names alone, so answering "how heavy is this part" or
/// "which material does it route through" meant leaving the editor. Every field
/// below is already on this side of the protocol — the parsed submesh carries
/// its vertices and faces, and the material set carries the route and texture —
/// so this reads local state rather than asking the host for anything.
/// </remarks>
internal sealed partial class ExperimentForm
{
    private TableLayoutPanel? _partDetail;
    private Label? _partDetailSummary;
    private Label? _partDetailWeight;
    private Label? _partDetailMaterialCaption;
    private Label? _partDetailMaterialValue;
    private Label? _partDetailTextureCaption;
    private Label? _partDetailTextureValue;
    private Label? _partDetailHidden;
    // The value colours follow the editor's own dark palette: names of things
    // read warm, references to resources read cool, and a state that hides
    // geometry reads as a warning.
    private static readonly Color PartDetailMaterialColor = Color.FromArgb(206, 145, 120);
    private static readonly Color PartDetailTextureColor = Color.FromArgb(86, 156, 214);

    private Label PartDetailLabel(Color foreColor, float size = 8f, bool bold = false)
    {
        return new Label
        {
            AutoSize = true,
            AutoEllipsis = true,
            ForeColor = foreColor,
            BackColor = ThemeSectionBackground,
            Font = new Font(Font.FontFamily, size, bold ? FontStyle.Bold : FontStyle.Regular),
            Margin = new Padding(0, 0, 4, 1),
            UseMnemonic = false,
            MaximumSize = new Size(
                ScaleToolPanelWidth(EditMeshToolColumnMetrics.InspectorFloor - 60),
                0),
        };
    }

    private GroupBox BuildPartsSection(
        TableLayoutPanel stack,
        Button duplicatePartButton,
        Button deletePartButton)
    {
        // A structured readout rather than one grey paragraph: what is
        // selected, how heavy it is, and what the one selected part routes
        // through, each on its own captioned, colour-coded row. Auto-sized and
        // a step smaller than the section, because this is reference detail
        // read at a glance, not a control.
        _partDetailSummary = PartDetailLabel(ThemeStrongText, bold: true);
        _partDetailWeight = PartDetailLabel(ThemeText);
        _partDetailMaterialCaption = PartDetailLabel(ThemeMutedText);
        _partDetailMaterialCaption.Text = "Material";
        _partDetailMaterialValue = PartDetailLabel(PartDetailMaterialColor);
        _partDetailTextureCaption = PartDetailLabel(ThemeMutedText);
        _partDetailTextureCaption.Text = "Texture";
        _partDetailTextureValue = PartDetailLabel(PartDetailTextureColor);
        _partDetailHidden = PartDetailLabel(Color.Salmon);
        _partDetailHidden.Text = "Hidden";
        _partDetail = new TableLayoutPanel
        {
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Dock = DockStyle.Top,
            BackColor = ThemeSectionBackground,
            ColumnCount = 2,
            Margin = new Padding(0, 1, 0, 5),
            Padding = new Padding(2, 0, 2, 0),
        };
        _partDetail.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        _partDetail.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _partDetail.Controls.Add(_partDetailSummary, 0, 0);
        _partDetail.SetColumnSpan(_partDetailSummary, 2);
        _partDetail.Controls.Add(_partDetailWeight, 0, 1);
        _partDetail.SetColumnSpan(_partDetailWeight, 2);
        _partDetail.Controls.Add(_partDetailMaterialCaption, 0, 2);
        _partDetail.Controls.Add(_partDetailMaterialValue, 1, 2);
        _partDetail.Controls.Add(_partDetailTextureCaption, 0, 3);
        _partDetail.Controls.Add(_partDetailTextureValue, 1, 3);
        _partDetail.Controls.Add(_partDetailHidden, 0, 4);
        _partDetail.SetColumnSpan(_partDetailHidden, 2);
        _partDetail.Name = "DotNetMeshEditorPartDetail";
        _partDetail.AccessibleName = "Selected part detail";

        var section = AddSection(
            stack,
            "Parts",
            _submeshList,
            _partDetail,
            // Two rows of three, selection above whole-part commands. Short
            // captions so each row fits the column instead of wrapping a lone
            // button onto a third row.
            ButtonRow(
                StyledActionButton("All", SelectAllParts),
                StyledActionButton("None", ClearPartSelection),
                StyledActionButton("Invert", InvertPartSelection)),
            ButtonRow(
                CommandButton("Hide", "toggle_visibility"),
                duplicatePartButton,
                deletePartButton));
        _submeshList.SelectedIndexChanged += (_, _) => RefreshPartDetail();
        RefreshPartDetail();
        return section;
    }

    /// <summary>
    /// Restates the list selection in words, and names what the one selected
    /// part is made of. Multiple parts report their total instead, because a
    /// material route only means something for a single part.
    /// </summary>
    private void RefreshPartDetail()
    {
        if (_partDetail is null
            || _partDetailSummary is null
            || _partDetailWeight is null
            || _partDetailMaterialCaption is null
            || _partDetailMaterialValue is null
            || _partDetailTextureCaption is null
            || _partDetailTextureValue is null
            || _partDetailHidden is null)
        {
            return;
        }
        var total = _submeshList.Items.Count;
        var selected = _submeshList.SelectedIndices.Cast<int>().ToArray();
        _partDetailSummary.Text = $"Selected {selected.Length} of {total}";
        var vertices = 0;
        var triangles = 0;
        foreach (var index in selected)
        {
            if (index >= 0 && index < _document.Submeshes.Count)
            {
                vertices += _document.Submeshes[index].Vertices.Count;
                triangles += _document.Submeshes[index].Faces.Count;
            }
        }
        _partDetailWeight.Visible = selected.Length > 0;
        _partDetailWeight.Text = selected.Length > 0 ? $"{vertices:N0} v · {triangles:N0} tri" : string.Empty;
        // A material route only means something for one part, so a multi-part
        // selection reports its total and stops there. A part's texture is
        // usually named after the part, so it is shown only when it differs
        // from the part's own name -- the list row already names the part.
        var material = string.Empty;
        var texture = string.Empty;
        var hidden = false;
        if (selected.Length == 1 && selected[0] >= 0 && selected[0] < _document.Submeshes.Count)
        {
            var index = selected[0];
            var submesh = _document.Submeshes[index];
            var binding = index < _materials.Submeshes.Count ? _materials.Submeshes[index] : null;
            material = string.IsNullOrWhiteSpace(binding?.Material)
                ? submesh.Material
                : binding!.Material;
            var boundTexture = binding?.Texture;
            if (!string.IsNullOrWhiteSpace(boundTexture)
                && !string.Equals(boundTexture, submesh.Name, StringComparison.OrdinalIgnoreCase))
            {
                texture = boundTexture;
            }
            hidden = _materials.ParametersForSubmesh(index).Visible is false;
        }
        var showMaterial = !string.IsNullOrWhiteSpace(material);
        _partDetailMaterialCaption.Visible = showMaterial;
        _partDetailMaterialValue.Visible = showMaterial;
        _partDetailMaterialValue.Text = showMaterial ? material : string.Empty;
        var showTexture = texture.Length > 0;
        _partDetailTextureCaption.Visible = showTexture;
        _partDetailTextureValue.Visible = showTexture;
        _partDetailTextureValue.Text = showTexture ? texture : string.Empty;
        _partDetailHidden.Visible = hidden;
        SetHelpText(_partDetail, _partDetailSummary.Text);
    }

    /// <summary>
    /// One list row: the part's name and nothing else. Counts and the material
    /// route belong to the detail below, where they describe the selection
    /// rather than repeating on every line. Hidden parts are reported there too.
    /// </summary>
    private string DescribePartRow(int index) => _document.Submeshes[index].Name;

    private void SelectAllParts() => SetPartSelection(Enumerable.Range(0, _submeshList.Items.Count));

    private void ClearPartSelection() => SetPartSelection(Enumerable.Empty<int>());

    private void InvertPartSelection()
    {
        var selected = _submeshList.SelectedIndices.Cast<int>().ToHashSet();
        SetPartSelection(
            Enumerable.Range(0, _submeshList.Items.Count).Where(index => !selected.Contains(index)));
    }

    /// <summary>
    /// Applies a whole-part selection through the same path a click does, so the
    /// viewport highlight and the host's notion of the selection stay together.
    /// </summary>
    private void SetPartSelection(IEnumerable<int> indices)
    {
        var wanted = indices.ToHashSet();
        _syncingSubmeshListSelection = true;
        // Each SetSelected repaints the list on its own, so Select All, Invert
        // and Clear cost one repaint per part -- which on a mesh with any real
        // number of them is seen as the Parts list flashing through the change
        // rather than making it. The list is repopulated under the same pair in
        // RefreshSubmeshList; a selection sweep is no different.
        _submeshList.BeginUpdate();
        try
        {
            for (var index = 0; index < _submeshList.Items.Count; index++)
            {
                _submeshList.SetSelected(index, wanted.Contains(index));
            }
        }
        finally
        {
            _submeshList.EndUpdate();
            _syncingSubmeshListSelection = false;
        }
        _viewport.SelectPartsFromList(_submeshList.SelectedIndices.Cast<int>());
        RefreshPartDetail();
    }
}
