using System.Text.Json;

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

    private void ApplyGizmoAppearanceFromPresentation(JsonElement quality)
    {
        var current = _gizmoAppearance;
        SetGizmoAppearance(new GizmoAppearance(
            GizmoAppearance.ParseColor(
                JsonText(quality, "gizmo_x_axis_color", GizmoAppearance.Hex(current.XAxis)),
                current.XAxis),
            GizmoAppearance.ParseColor(
                JsonText(quality, "gizmo_y_axis_color", GizmoAppearance.Hex(current.YAxis)),
                current.YAxis),
            GizmoAppearance.ParseColor(
                JsonText(quality, "gizmo_z_axis_color", GizmoAppearance.Hex(current.ZAxis)),
                current.ZAxis),
            GizmoAppearance.ParseColor(
                JsonText(quality, "gizmo_highlight_color", GizmoAppearance.Hex(current.Highlight)),
                current.Highlight),
            GizmoAppearance.ParseColor(
                JsonText(quality, "gizmo_label_color", GizmoAppearance.Hex(current.Label)),
                current.Label),
            JsonFloat(quality, "gizmo_line_thickness_pixels", current.LineThicknessPixels),
            JsonFloat(quality, "gizmo_size_scale", current.SizeScale),
            JsonFloat(quality, "gizmo_label_size_pixels", current.LabelSizePixels),
            JsonFloat(quality, "gizmo_handle_size_pixels", current.HandleSizePixels)));
    }
}
