namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// How wide the Edit Mesh dock columns need to be.
/// </summary>
/// <remarks>
/// The rail-and-panel layout spent a constant 414 logical pixels on the tool
/// dock — 74 for the rail plus 340 for the property column — at every window
/// size and whether or not anything was open. The list layout has one column, so
/// the width can follow what is actually in it: the tool rows when nothing is
/// expanded, and the open page's own measured width when something is.
///
/// These are logical (96 dpi) pixels. Callers scale them.
/// </remarks>
internal static class EditMeshToolColumnMetrics
{
    /// <summary>Glyph, caption and the row's own padding, with nothing open.</summary>
    public const int CollapsedFloor = 196;

    /// <summary>Below this an open page starts clipping its own controls.</summary>
    public const int ExpandedFloor = 300;

    /// <summary>
    /// The widest a capped page may push the column. Past this the column is
    /// taking room the viewport can use better than the settings can.
    /// </summary>
    public const int ExpandedCeiling = 420;

    /// <summary>
    /// A hard stop for the uncapped page, so a runaway measurement cannot leave
    /// the viewport at its minimum.
    /// </summary>
    public const int UncappedCeiling = 620;

    public const int InspectorFloor = 260;
    public const int InspectorCeiling = 340;

    /// <summary>
    /// The width a wrapping status label is measured against. Held at the old
    /// fixed column's usable width so those labels wrap exactly where they
    /// always have: a status line that re-wraps as the column resizes reads as
    /// the text changing, and these labels report authority state.
    /// </summary>
    public const int WrappedStatusWidth = 300;

    /// <summary>
    /// The chrome around the measured content: the scroll host's left and right
    /// padding plus room for its vertical scrollbar, which appears exactly when
    /// the column is at its tightest.
    /// </summary>
    public const int ColumnChromeWidth = 20 + 17;

    /// <summary>
    /// Morph &amp; Refit is allowed past <see cref="ExpandedCeiling"/>. Its
    /// three-button row — Author Slider…, Save Profile, Delete Profile — is the
    /// widest real content in the dock, and those buttons clip rather than wrap.
    /// Capping the column at the same width as every other page would hide the
    /// end of a command name, which is worse than a wider column on the one page
    /// that needs it.
    /// </summary>
    public static bool PageWidthIsUncapped(ToolRailPage page) => page == ToolRailPage.MorphRefit;

    /// <summary>
    /// The tool column's width. <paramref name="measuredContentWidth"/> is the
    /// preferred width of the open page, or of the widest row when nothing is
    /// open; it already excludes chrome, which this adds.
    /// </summary>
    public static int PreferredColumnWidth(
        int measuredContentWidth,
        ToolRailPage? expandedPage)
    {
        var requested = Math.Max(0, measuredContentWidth) + ColumnChromeWidth;
        if (expandedPage is not { } page)
        {
            // Nothing open: the column only has to name the tools. It still gets
            // a floor, because a column that hugs the captions reads as a
            // truncated panel rather than a deliberate one.
            return Math.Clamp(requested, CollapsedFloor, ExpandedFloor);
        }
        var ceiling = PageWidthIsUncapped(page) ? UncappedCeiling : ExpandedCeiling;
        return Math.Clamp(requested, ExpandedFloor, ceiling);
    }

    /// <summary>
    /// The scene inspector's width. It is never modal — Parts, Action History
    /// and Viewport are all open at once — so it measures once and stays there.
    /// </summary>
    public static int PreferredInspectorWidth(int measuredContentWidth)
    {
        var requested = Math.Max(0, measuredContentWidth) + ColumnChromeWidth;
        return Math.Clamp(requested, InspectorFloor, InspectorCeiling);
    }
}
