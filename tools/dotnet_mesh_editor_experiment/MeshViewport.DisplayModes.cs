namespace Cdmw.MeshEditorExperiment;

internal readonly record struct MeshDisplayModeState(
    string Mode,
    bool Solid,
    bool Wire,
    bool Vertices,
    bool XRay,
    bool Textures)
{
    internal static bool TryResolve(string? mode, out MeshDisplayModeState state, out string error)
    {
        var normalized = (mode ?? string.Empty).Trim().ToLowerInvariant().Replace('-', '_');
        if (normalized is "textured_wire" or "solid_wire")
        {
            normalized = "textured";
        }
        state = normalized switch
        {
            "textured" => new(normalized, true, false, false, false, true),
            "untextured_faces" or "faces" => new("untextured_faces", true, false, false, false, false),
            "untextured_wire" => new(normalized, true, true, false, false, false),
            "wire" => new(normalized, false, true, false, false, false),
            "vertices" => new(normalized, false, false, true, false, false),
            "wire_vertices" => new(normalized, false, true, true, false, false),
            "xray" => new(normalized, false, true, true, true, false),
            _ => default,
        };
        if (string.IsNullOrEmpty(state.Mode))
        {
            error = $"Unknown viewport display mode: {mode}";
            return false;
        }
        error = string.Empty;
        return true;
    }
}

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
        // The host mirrors xray in view state, so a silent change here leaves it
        // holding a stale value to restore from.
        NotifyViewStateChanged();
        UpdateGpuViewport();
        Invalidate();
    }

    public bool TrySetDisplayMode(string mode, out string error)
    {
        if (!TryApplyDisplayModeState(mode, out error))
        {
            return false;
        }
        // display_mode, xray and textures_enabled are all reported view state.
        NotifyViewStateChanged();
        UpdateGpuViewport();
        Invalidate();
        return true;
    }

    private bool TryApplyDisplayModeState(string mode, out string error)
    {
        if (!MeshDisplayModeState.TryResolve(mode, out var state, out error))
        {
            return false;
        }

        DisplayMode = state.Mode;
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
        return true;
    }
}
