namespace Cdmw.MeshEditorExperiment;

// Layout suspend and resume for Edit Mesh, plus the two rail tweaks that
// only run around a relayout. Split from ExperimentForm.EditMeshLayouts to
// keep that file inside the owned-file line cap; same partial class, so
// nothing about how these are called changes.
internal sealed partial class ExperimentForm
{
    /// <summary>
    /// The Morph &amp; Refit section carries its own collapse header. In the
    /// tool dock the header row is redundant — the dock header names the page —
    /// and the body must not stay collapsed from an earlier session.
    /// </summary>
    private void SetMorphCollapseHeaderVisible(bool visible)
    {
        if (_morphSectionHeader is null
            || _morphSectionLayout is null
            || _morphSectionLayout.RowStyles.Count == 0)
        {
            return;
        }
        _morphSectionHeader.Visible = visible;
        _morphSectionLayout.RowStyles[0].SizeType =
            visible ? SizeType.AutoSize : SizeType.Absolute;
        _morphSectionLayout.RowStyles[0].Height = 0;
        if (_morphSectionBody is not null)
        {
            _morphSectionBody.Visible = !visible || _morphClassicExpanded;
        }
    }

    /// <summary>
    /// Blanks the caption of the section a page is built around, because the
    /// list row that opened it already names it. Part Pick keeps its caption —
    /// it is the second box on the Selection page — as do the scene groups,
    /// which have no row at all.
    /// </summary>
    private void HideRailToolSectionCaptions()
    {
        foreach (var section in new[]
        {
            _selectionSection,
            _transformSection,
            _brushSection,
            _topologySection,
            _colourSection,
        })
        {
            if (section is not null)
            {
                section.Text = string.Empty;
            }
        }
    }

    private void PerformPlacementFlankLayout()
    {
        _leftToolStack?.PerformLayout();
        _rightToolStack?.PerformLayout();
        _leftToolPanel?.PerformLayout();
        _rightToolPanel?.PerformLayout();
    }

    private void SuspendAllEditMeshLayouts()
    {
        _editMeshLayoutHost?.SuspendLayout();
        _placementEditMeshLayoutRoot?.SuspendLayout();
        _viewportWorkspaceSplit?.SuspendLayout();
        _leftToolModeHost?.SuspendLayout();
        _rightToolModeHost?.SuspendLayout();
        _toolDock?.SuspendLayout();
        _sceneInspectorColumn?.SuspendLayout();
        _railSelectionStack?.SuspendLayout();
        SuspendToolPanelLayout();
    }

    private void ResumeAllEditMeshLayouts()
    {
        ResumeToolPanelLayout();
        _railSelectionStack?.ResumeLayout(performLayout: false);
        _sceneInspectorColumn?.ResumeLayout(performLayout: false);
        _toolDock?.ResumeLayout(performLayout: false);
        _rightToolModeHost?.ResumeLayout(performLayout: true);
        _leftToolModeHost?.ResumeLayout(performLayout: true);
        _viewportWorkspaceSplit?.ResumeLayout(performLayout: true);
        _placementEditMeshLayoutRoot?.ResumeLayout(performLayout: true);
        _editMeshLayoutHost?.ResumeLayout(performLayout: true);
    }
}
