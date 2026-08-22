namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// What a row of the Edit Mesh tool list does when it is clicked.
/// </summary>
internal enum ToolListRowKind
{
    /// <summary>Arms the tool it names and opens that tool's settings.</summary>
    Tool,

    /// <summary>Opens a page of one-shot commands without arming anything.</summary>
    CommandPage,
}

/// <summary>
/// One row of the Edit Mesh tool list: the thing the reader clicks, and the
/// page of settings that opens underneath it.
/// </summary>
/// <remarks>
/// Six tool rows share three page bodies. Move and Grab both open Transform;
/// Smooth, Inflate and Pinch all open Brush. Keeping the row and the page as
/// separate ideas is what stops the list repeating itself: the row is the only
/// place a tool is named, and the page holds only settings. The old rail listed
/// the tools and then let each page list them again, which is the duplication
/// this list exists to remove.
/// </remarks>
/// <remarks>
/// The row carries structure only. Its glyph, caption and description live in
/// <c>ExperimentForm.ToolList.cs</c> beside the controls they are assigned to,
/// because the localization manifest keys a UI string by the callsite that
/// sinks it — a caption parked in a data table here would be shipped
/// untranslated.
/// </remarks>
internal sealed record ToolListRow(
    ToolListRowKind Kind,
    string Key,
    ToolRailPage Page);

internal static class EditMeshToolListContract
{
    /// <summary>
    /// The row keys. Named constants rather than bare literals at the callsites
    /// that switch on them: a lowercase key sitting in a method that returns UI
    /// text is picked up by the localization scanner as if it were a caption,
    /// and "colour" is not a string anyone should be asked to translate.
    /// </summary>
    public static class Keys
    {
        public const string Select = "select";
        public const string Move = "move";
        public const string Grab = "grab";
        public const string Smooth = "smooth";
        public const string Inflate = "inflate";
        public const string Pinch = "pinch";
        public const string Topology = "topology";
        public const string Morph = "morph";
    }

    /// <summary>
    /// Every row, in list order: the six armable tools, then the two command
    /// pages. The order matches <see cref="EditMeshLayoutContracts.RailToolOrder"/>
    /// and <see cref="EditMeshLayoutContracts.RailCommandPageOrder"/>, and
    /// <see cref="RequireCompleteList"/> is what keeps it matching.
    /// </summary>
    /// <remarks>
    /// Rows carry no shortcut hint because the editor binds no tool
    /// accelerators — only Ctrl+Z, Ctrl+Y and Ctrl+Shift+Z, which belong to the
    /// session bar. A hint for a key that does nothing is worse than no hint.
    /// </remarks>
    public static readonly ToolListRow[] RowOrder =
    {
        new(ToolListRowKind.Tool, Keys.Select, ToolRailPage.Selection),
        new(ToolListRowKind.Tool, Keys.Move, ToolRailPage.Transform),
        new(ToolListRowKind.Tool, Keys.Grab, ToolRailPage.Transform),
        new(ToolListRowKind.Tool, Keys.Smooth, ToolRailPage.Brush),
        new(ToolListRowKind.Tool, Keys.Inflate, ToolRailPage.Brush),
        new(ToolListRowKind.Tool, Keys.Pinch, ToolRailPage.Brush),
        new(ToolListRowKind.CommandPage, Keys.Topology, ToolRailPage.Topology),
        new(ToolListRowKind.CommandPage, Keys.Morph, ToolRailPage.MorphRefit),
    };

    /// <summary>
    /// The index the group label sits above: the first command-page row. The
    /// break is what tells the reader that everything below it opens a page
    /// without touching the armed tool.
    /// </summary>
    public static int CommandGroupStartIndex =>
        Array.FindIndex(RowOrder, row => row.Kind == ToolListRowKind.CommandPage);

    /// <summary>
    /// The row that owns a tool, or null when no row does. Orbit owns no row —
    /// the camera is not a list entry, it is reached through the modifiers named
    /// on the navigation strip — so Edit Mesh opens with nothing expanded and
    /// nothing armed.
    /// </summary>
    public static ToolListRow? RowForTool(string? tool)
    {
        var normalized = (tool ?? string.Empty).Trim();
        if (normalized.Length == 0)
        {
            return null;
        }
        return Array.Find(
            RowOrder,
            row => row.Kind == ToolListRowKind.Tool
                && string.Equals(row.Key, normalized, StringComparison.OrdinalIgnoreCase));
    }

    public static int IndexOfRow(ToolListRow row) => Array.IndexOf(RowOrder, row);

    /// <summary>
    /// The first row that opens a page. A page has no name of its own in this
    /// layout — the rows do — so callers that need one ask the row.
    /// </summary>
    public static ToolListRow? FirstRowForPage(ToolRailPage page) =>
        Array.Find(RowOrder, row => row.Page == page);

    /// <summary>
    /// Where a row's button sits with nothing expanded. The group label owns a
    /// cell of its own directly above the first command row, so every command
    /// row sits one cell lower than its position in <see cref="RowOrder"/>.
    /// </summary>
    public static int BaseCell(int rowIndex) =>
        rowIndex + (rowIndex >= CommandGroupStartIndex ? 1 : 0);

    /// <summary>The group label's cell, which never moves relative to the rows above it.</summary>
    public static int GroupLabelBaseCell => CommandGroupStartIndex;

    /// <summary>
    /// Where a cell ends up once one row is expanded. The open body occupies the
    /// cell directly beneath the row that opened it, so everything below that
    /// point — later rows and the group label alike — moves down by one.
    /// </summary>
    public static int ResolvedCell(int baseCell, int? expandedBaseCell) =>
        expandedBaseCell is { } expanded && baseCell > expanded ? baseCell + 1 : baseCell;

    /// <summary>
    /// Where the shared body host sits: directly under the row that opened it,
    /// which is the whole point of the layout.
    /// </summary>
    public static int BodyCell(int expandedBaseCell) => expandedBaseCell + 1;

    /// <summary>
    /// The number of table cells the list needs: one per row, one for the group
    /// label, one for the open body, and a trailing spring that keeps the rows
    /// packed to the top instead of spreading down the column.
    /// </summary>
    public static int TableRowCount => RowOrder.Length + 3;

    /// <summary>The cell the body host parks in while nothing is expanded.</summary>
    public static int ParkedBodyCell => TableRowCount - 1;

    /// <summary>
    /// Fails construction when the built list disagrees with the rail
    /// inventories it is built from. The rows are literals so each caption stays
    /// a translatable callsite, and this is what keeps those literals from
    /// drifting away from the executed contract.
    /// </summary>
    public static void RequireCompleteList(IReadOnlyCollection<string> builtRowKeys)
    {
        ArgumentNullException.ThrowIfNull(builtRowKeys);
        if (!RowOrder.Select(row => row.Key).SequenceEqual(builtRowKeys, StringComparer.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                "The Edit Mesh tool list's rows do not match the contract's row inventory.");
        }

        var toolKeys = RowOrder
            .Where(row => row.Kind == ToolListRowKind.Tool)
            .Select(row => row.Key)
            .ToArray();
        if (!EditMeshLayoutContracts.RailToolOrder.SequenceEqual(toolKeys, StringComparer.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                "The Edit Mesh tool list's tool rows do not match the rail's tool inventory.");
        }

        var commandPages = RowOrder
            .Where(row => row.Kind == ToolListRowKind.CommandPage)
            .Select(row => row.Page)
            .ToArray();
        if (!EditMeshLayoutContracts.RailCommandPageOrder.SequenceEqual(commandPages))
        {
            throw new InvalidOperationException(
                "The Edit Mesh tool list's command rows do not match the rail's page inventory.");
        }

        // A tool row must open the page that owns its tool, or expanding it
        // would show settings for something else.
        foreach (var row in RowOrder.Where(row => row.Kind == ToolListRowKind.Tool))
        {
            if (EditMeshLayoutContracts.ToolRailPageForTool(row.Key) != row.Page)
            {
                throw new InvalidOperationException(
                    $"The Edit Mesh tool list row '{row.Key}' opens a page that does not own it.");
            }
        }
    }
}
