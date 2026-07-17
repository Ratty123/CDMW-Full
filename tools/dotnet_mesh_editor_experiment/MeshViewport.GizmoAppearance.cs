namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private GizmoAppearance _gizmoAppearance = GizmoAppearance.Default;

    public void SetGizmoAppearance(GizmoAppearance appearance)
    {
        _gizmoAppearance = appearance.Normalized();
        _d3d11Viewport?.SetGizmoAppearance(_gizmoAppearance);
        UpdateGpuViewport();
        Invalidate();
    }
}
