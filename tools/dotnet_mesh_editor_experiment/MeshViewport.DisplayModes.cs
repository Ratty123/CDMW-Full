namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    public void SetOverlaySettings(MeshOverlaySettings settings)
    {
        _overlaySettings = settings.Normalized();
        _d3d11Viewport?.SetOverlaySettings(_overlaySettings);
        _gpuViewport?.SetOverlaySettings(_overlaySettings);
        UpdateGpuViewport();
        Invalidate();
    }

    public void SetXRayEnabled(bool enabled)
    {
        ShowXRay = enabled;
        if (_presentationContexts.TryGetValue(_activeCameraContextId, out var context))
        {
            context.XRay = enabled;
        }
        UpdateGpuViewport();
        Invalidate();
    }

    public bool TrySetDisplayMode(string mode, out string error)
    {
        var normalized = (mode ?? string.Empty).Trim().ToLowerInvariant().Replace('-', '_');
        (bool Solid, bool Wire, bool Vertices, bool XRay, bool Textures) state = normalized switch
        {
            "textured" => (true, false, false, false, true),
            "untextured_faces" or "faces" => (true, false, false, false, false),
            "untextured_wire" => (true, true, false, false, false),
            "textured_wire" or "solid_wire" => (true, true, false, false, true),
            "wire" => (false, true, false, false, false),
            "vertices" => (false, false, true, false, false),
            "wire_vertices" => (false, true, true, false, false),
            "xray" => (false, true, true, true, false),
            _ => default,
        };
        if (normalized is not (
            "textured" or "untextured_faces" or "faces" or "untextured_wire" or "textured_wire" or "solid_wire"
            or "wire" or "vertices" or "wire_vertices" or "xray"))
        {
            error = $"Unknown viewport display mode: {mode}";
            return false;
        }

        DisplayMode = normalized switch
        {
            "faces" => "untextured_faces",
            "solid_wire" => "textured_wire",
            _ => normalized,
        };
        ShowSolid = state.Solid;
        ShowWire = state.Wire;
        ShowVertices = state.Vertices;
        ShowXRay = state.XRay;
        if (_presentationContexts.TryGetValue(_activeCameraContextId, out var context))
        {
            context.XRay = ShowXRay;
        }
        TexturesEnabled = state.Textures;
        error = string.Empty;
        UpdateGpuViewport();
        Invalidate();
        return true;
    }
}
