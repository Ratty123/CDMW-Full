using System.Drawing;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// What a real form does when the host asks for Solid (Textured), and when
/// Edit Mesh opens. Neither is reachable from the stand-in controls the layout
/// smoke builds: one lives in the presentation payload the host republishes,
/// the other in the order the rail's hosts adopt their sections.
/// </summary>
internal sealed partial class ExperimentForm
{
    /// <summary>
    /// Solid (Textured) must sample the material even though the Builder
    /// publishes <c>use_textures_by_default</c> false beside it.
    /// </summary>
    /// <remarks>
    /// That flag is Preview Settings' "load textures automatically after
    /// geometry", off by default. It rode the same quality payload as the
    /// display mode and was applied after it, so every republish (one after
    /// every accepted scene frame) switched textures back off under a mode that
    /// means nothing else. Picking the mode again re-textured the scene until
    /// the next frame, which is what made it look random.
    ///
    /// Both directions are proven: a payload that names no mode must still
    /// honour the flag, or a fix that simply deleted the line would strand the
    /// archive preview's own toggle with nothing to catch it.
    /// </remarks>
    internal Dictionary<string, object?> SolidTexturedViewProof()
    {
        var withMode = ApplyPresentationTextureCase(
            "textured",
            useTexturesByDefault: false);
        var untexturedWithMode = ApplyPresentationTextureCase(
            "untextured_faces",
            useTexturesByDefault: true);
        // Park on a textured mode, then send a payload that names none: the
        // flag is the only authority left and must still be obeyed.
        _ = ApplyPresentationTextureCase("textured", useTexturesByDefault: false);
        var withoutMode = ApplyPresentationTextureCase(
            mode: null,
            useTexturesByDefault: false);
        return new Dictionary<string, object?>
        {
            ["ok"] = withMode.Applied
                && withMode.TexturesEnabled
                && withMode.PaneTexturesEnabled
                && untexturedWithMode.Applied
                && !untexturedWithMode.TexturesEnabled
                && !untexturedWithMode.PaneTexturesEnabled
                && withoutMode.Applied
                && !withoutMode.TexturesEnabled,
            ["named_textured_mode"] = withMode.Payload,
            ["named_untextured_mode"] = untexturedWithMode.Payload,
            ["unnamed_mode_honours_flag"] = withoutMode.Payload,
        };
    }

    private (bool Applied, bool TexturesEnabled, bool PaneTexturesEnabled, Dictionary<string, object?> Payload)
        ApplyPresentationTextureCase(string? mode, bool useTexturesByDefault)
    {
        var display = new Dictionary<string, object?>
        {
            ["grid_visible"] = true,
            ["quality"] = new Dictionary<string, object?>
            {
                ["use_textures_by_default"] = useTexturesByDefault,
            },
        };
        if (mode is not null)
        {
            display["mode"] = mode;
        }
        var state = new Dictionary<string, object?>
        {
            ["active_view"] = "editable",
            ["comparison_mode"] = "replacement_only",
            ["display"] = display,
        };
        using var document = JsonDocument.Parse(JsonSerializer.Serialize(state));
        var applied = _viewport.TryApplyPresentationState(document.RootElement, out var error);
        // The panes are what the renderer actually draws from, and they take
        // their own copy of the flag. Asserting the viewport property alone
        // would miss a synchronisation that never reached them.
        var paneTextures = _viewport.PresentationContextTexturesEnabled();
        return (
            applied,
            _viewport.TexturesEnabled,
            paneTextures,
            new Dictionary<string, object?>
            {
                ["requested_mode"] = mode ?? "(none)",
                ["use_textures_by_default"] = useTexturesByDefault,
                ["applied"] = applied,
                ["error"] = error,
                ["display_mode"] = _viewport.DisplayMode,
                ["textures_enabled"] = _viewport.TexturesEnabled,
                ["pane_textures_enabled"] = paneTextures,
            });
    }

    /// <summary>
    /// Opening Edit Mesh must leave the scene inspector already settled.
    /// </summary>
    /// <remarks>
    /// The rail adopts the placement sections with every layout suspended and
    /// resumes them with <c>performLayout: false</c>, and a form-wide layout
    /// only cascades where a bound actually changes. A section left on its
    /// previous parent's bounds is therefore possible rather than prevented,
    /// and it shows as the right-hand menu opening with its rows on top of each
    /// other and its buttons clipped past the column edge. Comparing the bounds
    /// after entry against the bounds a full re-layout produces pins the
    /// contract without depending on any particular column width.
    /// </remarks>
    internal Dictionary<string, object?> SceneInspectorEntryLayoutProof()
    {
        // A realistic frame: the defect needs the placement flank and the rail
        // inspector to disagree about width, and a zero-size form has neither.
        Size = new Size(1480, 900);
        PerformLayout();
        // Enter the way the host does. Calling ActivateToolRailLayout directly
        // skips ApplyInteractionModeControls, which is what reveals the
        // mesh-edit-only sections -- and a TableLayoutPanel lays out no hidden
        // child, so the shortcut would prove nothing about three of the four
        // rows.
        _scene.SetInteractionMode("mesh_edit");
        ApplyInteractionModeControls();

        var afterEntry = SceneInspectorSectionBounds();
        var columnWidthOnEntry = _sceneInspectorColumn?.ClientSize.Width ?? 0;
        var overflowingOnEntry = SceneInspectorSections()
            .Where(section => section.Right > columnWidthOnEntry)
            .Select(section => section.Name)
            .ToArray();

        // The closest headless stand-in for dragging the window border: a real
        // size change followed by a full layout pass. If entry skipped a
        // cascade, this is what runs it and the bounds move.
        Width += 1;
        PerformLayout();
        Width -= 1;
        PerformLayout();
        var afterResize = SceneInspectorSectionBounds();

        var settled = afterEntry.Count == afterResize.Count
            && afterEntry.Keys.All(name =>
                afterResize.TryGetValue(name, out var resized)
                && string.Equals(afterEntry[name], resized, StringComparison.Ordinal));
        return new Dictionary<string, object?>
        {
            // Entering must already be what a resize would produce, and the
            // column must contain its own sections. Either one alone is not
            // enough: a column that clips every section the same way before and
            // after a resize is stable and still unusable.
            ["ok"] = settled
                && overflowingOnEntry.Length == 0
                && afterEntry.Count > 0
                && columnWidthOnEntry > 0,
            ["settled_on_entry"] = settled,
            ["column_width"] = columnWidthOnEntry,
            ["diagnostic"] = SceneInspectorDiagnostic(),
            ["sections_overflowing_column"] = overflowingOnEntry,
            ["bounds_after_entry"] = afterEntry,
            ["bounds_after_resize"] = afterResize,
        };
    }

    /// <summary>
    /// The sections the rail adopted, read by membership rather than by
    /// <c>Visible</c>, so a section the transition failed to reveal is reported
    /// with its stale bounds instead of disappearing from the evidence.
    /// </summary>
    private IEnumerable<Control> SceneInspectorSections() =>
        _sceneInspectorColumn is null
            ? Enumerable.Empty<Control>()
            : _sceneInspectorColumn.Controls.Cast<Control>();

    /// <summary>
    /// Enough to act on a failure without attaching a debugger to a WinExe.
    /// A stale row reads as a cell the column never assigned, or as a section
    /// still carrying the width of the flank it came from.
    /// </summary>
    private Dictionary<string, object?> SceneInspectorDiagnostic()
    {
        var column = _sceneInspectorColumn;
        return new Dictionary<string, object?>
        {
            ["tool_rail_active"] = _toolRailLayoutActive,
            ["column_bounds"] = column?.Bounds.ToString(),
            ["column_row_count"] = column?.RowCount,
            ["inspector_panel_bounds"] = _rightToolSplit?.Panel2.Bounds.ToString(),
            ["sections"] = SceneInspectorSections().Select(section => new Dictionary<string, object?>
            {
                ["name"] = section.Name,
                ["cell"] = column?.GetCellPosition(section).ToString(),
                ["visible"] = section.Visible,
                ["bounds"] = section.Bounds.ToString(),
            }).ToArray(),
        };
    }

    private Dictionary<string, string> SceneInspectorSectionBounds() =>
        SceneInspectorSections().ToDictionary(
            section => section.Name,
            section => $"{section.Left},{section.Top},{section.Width},{section.Height}",
            StringComparer.Ordinal);
}
