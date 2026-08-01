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
    private Label? _partDetail;

    private GroupBox BuildPartsSection(
        TableLayoutPanel stack,
        Button duplicatePartButton,
        Button deletePartButton)
    {
        // Auto-sized and set a step smaller than the section: this is reference
        // detail read at a glance, not a control, and at body size it pushed the
        // Viewport group off the bottom of the column.
        _partDetail = new Label
        {
            AutoSize = true,
            Dock = DockStyle.Top,
            ForeColor = ThemeMutedText,
            BackColor = ThemeSectionBackground,
            Font = new Font(Font.FontFamily, 8f),
            Margin = new Padding(0, 1, 0, 5),
            Padding = new Padding(2, 0, 2, 0),
            UseMnemonic = false,
            MaximumSize = new Size(
                ScaleToolPanelWidth(EditMeshToolColumnMetrics.InspectorFloor - 40),
                0),
        };
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
        if (_partDetail is null)
        {
            return;
        }
        // Assigned from one method rather than assembled through a local
        // collection: the localization manifest keys a string by the callsite
        // that sinks it, and text built up in a List never reaches one.
        _partDetail.Text = PartDetailText();
        SetHelpText(_partDetail, _partDetail.Text);
    }

    private string PartDetailText()
    {
        var total = _submeshList.Items.Count;
        var selected = _submeshList.SelectedIndices.Cast<int>().ToArray();
        var count = $"Selected {selected.Length} of {total}";
        if (selected.Length == 0)
        {
            return count;
        }
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
        var weight = $"{vertices:N0} v · {triangles:N0} tri";
        // A material route only means something for one part, so a multi-part
        // selection reports its total and stops there.
        var routing = selected.Length == 1 ? DescribeSubmeshRouting(selected[0]) : string.Empty;
        return count + "   " + weight + routing;
    }

    /// <summary>
    /// The one selected part's material route, and its texture only when that
    /// differs from the part's own name.
    /// </summary>
    /// <remarks>
    /// A part's texture is usually named after the part, so printing both put
    /// the same long string on screen twice — once in the list and again here.
    /// The row above already names the part; this says what is different about
    /// it.
    /// </remarks>
    private string DescribeSubmeshRouting(int index)
    {
        if (index < 0 || index >= _document.Submeshes.Count)
        {
            return string.Empty;
        }
        var submesh = _document.Submeshes[index];
        var binding = index < _materials.Submeshes.Count ? _materials.Submeshes[index] : null;
        var material = string.IsNullOrWhiteSpace(binding?.Material)
            ? submesh.Material
            : binding!.Material;
        var routing = string.Empty;
        if (_materials.ParametersForSubmesh(index).Visible is false)
        {
            routing += Environment.NewLine + "Hidden";
        }
        if (!string.IsNullOrWhiteSpace(material))
        {
            routing += Environment.NewLine + $"Mat  {material}";
        }
        var texture = binding?.Texture;
        if (!string.IsNullOrWhiteSpace(texture)
            && !string.Equals(texture, submesh.Name, StringComparison.OrdinalIgnoreCase))
        {
            routing += Environment.NewLine + $"Tex  {texture}";
        }
        return routing;
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
        try
        {
            for (var index = 0; index < _submeshList.Items.Count; index++)
            {
                _submeshList.SetSelected(index, wanted.Contains(index));
            }
        }
        finally
        {
            _syncingSubmeshListSelection = false;
        }
        _viewport.SelectPartsFromList(_submeshList.SelectedIndices.Cast<int>());
        RefreshPartDetail();
    }
}
