using System.Drawing;
using System.Numerics;
using Vortice.Direct3D;
using Vortice.Direct3D11;
using Vortice.Mathematics;

namespace Cdmw.MeshEditorExperiment;

internal readonly record struct D3D11RenderPane(
    Rectangle Bounds,
    NetViewportCamera Camera,
    string Role,
    string DisplayMode,
    int MaterialDebugMode,
    bool TexturesEnabled,
    bool GridVisible,
    bool GizmoVisible,
    bool XRay,
    bool InteractionAllowed);

internal sealed partial class D3D11MaterialViewport
{
    private readonly D3D11RenderPane[] _renderPanes = new D3D11RenderPane[2];
    private int _renderPaneCount;
    private readonly D3D11RenderPane[] _fallbackRenderPane = new D3D11RenderPane[1];
    private readonly Vector3[] _surfaceQuadVertices = new Vector3[6];
    private D3D11RenderPane? _activeRenderPane;
    private long _referencePaneRenderCount;
    private long _editablePaneRenderCount;

    public bool HasRenderedBothRolePanes =>
        _referencePaneRenderCount > 0 && _editablePaneRenderCount > 0;

    public void UpdateRenderPanes(IEnumerable<D3D11RenderPane> panes)
    {
        var count = 0;
        foreach (var pane in panes)
        {
            if (pane.Bounds.Width > 0 && pane.Bounds.Height > 0 && count < _renderPanes.Length)
            {
                _renderPanes[count++] = pane;
            }
        }
        _renderPaneCount = count;
    }

    public void UpdateRenderPanes(D3D11RenderPane[] panes, int count)
    {
        var writeCount = 0;
        var limit = Math.Min(Math.Min(count, panes.Length), _renderPanes.Length);
        for (var index = 0; index < limit; index++)
        {
            var pane = panes[index];
            if (pane.Bounds.Width > 0 && pane.Bounds.Height > 0)
            {
                _renderPanes[writeCount++] = pane;
            }
        }
        _renderPaneCount = writeCount;
    }

    private D3D11RenderPane[] PanesForFrame(bool replacementOnly, out int count)
    {
        if (!replacementOnly && _renderPaneCount > 0)
        {
            count = _renderPaneCount;
            return _renderPanes;
        }
        _fallbackRenderPane[0] = new D3D11RenderPane(
            new Rectangle(0, 0, Math.Max(1, _renderWidth), Math.Max(1, _renderHeight)),
            _camera,
            replacementOnly ? "editable" : "comparison",
            TexturesEnabled ? "textured" : (ShowSolid ? "solid" : "wire"),
            MaterialDebugMode,
            TexturesEnabled,
            _scene.GridVisible,
            _scene.GizmoVisible,
            _overlayShowXRay,
            true);
        count = 1;
        return _fallbackRenderPane;
    }

    private void ActivateRenderPane(D3D11RenderPane pane)
    {
        _activeRenderPane = pane;
        _camera = pane.Camera;
        _materialDebugMode = Math.Clamp(pane.MaterialDebugMode, 0, 12);
        var mode = pane.DisplayMode ?? "textured";
        ShowSolid = !string.Equals(mode, "wire", StringComparison.OrdinalIgnoreCase)
            && !string.Equals(mode, "vertices", StringComparison.OrdinalIgnoreCase);
        TexturesEnabled = pane.TexturesEnabled
            && (string.Equals(mode, "textured", StringComparison.OrdinalIgnoreCase)
                || string.Equals(mode, "textured_wire", StringComparison.OrdinalIgnoreCase));
        _overlayShowWire = string.Equals(mode, "wire", StringComparison.OrdinalIgnoreCase)
            || string.Equals(mode, "untextured_wire", StringComparison.OrdinalIgnoreCase)
            || string.Equals(mode, "textured_wire", StringComparison.OrdinalIgnoreCase)
            || string.Equals(mode, "wire_vertices", StringComparison.OrdinalIgnoreCase)
            || string.Equals(mode, "xray", StringComparison.OrdinalIgnoreCase);
        _overlayShowVertices = string.Equals(mode, "vertices", StringComparison.OrdinalIgnoreCase)
            || string.Equals(mode, "wire_vertices", StringComparison.OrdinalIgnoreCase)
            || string.Equals(mode, "xray", StringComparison.OrdinalIgnoreCase);
        _overlayShowXRay = pane.XRay;
        _overlayShowWire = _overlayShowWire || _overlayShowXRay;
        _context?.RSSetViewport(new Viewport(
            pane.Bounds.X,
            pane.Bounds.Y,
            Math.Max(1, pane.Bounds.Width),
            Math.Max(1, pane.Bounds.Height),
            0,
            1));
    }

    private bool ActivePaneIncludes(int submeshIndex)
    {
        // An explicit hide holds whatever the pane is showing. The role says
        // which side of a comparison is on screen; it is not a statement about
        // whether a part the caller hid should come back.
        if (_scene.IsHiddenByPresentation(submeshIndex))
        {
            return false;
        }
        var role = _activeRenderPane?.Role ?? "comparison";
        return role switch
        {
            "reference" => _scene.IsReference(submeshIndex),
            "editable" => _scene.IsEditable(submeshIndex),
            _ => _scene.IsVisible(submeshIndex),
        };
    }

    private Matrix4x4 ActivePaneModelMatrix(int submeshIndex)
    {
        var role = _activeRenderPane?.Role ?? "comparison";
        return role is "reference" or "editable"
            ? _scene.RoleViewModelMatrix(submeshIndex)
            : _scene.ModelMatrix(submeshIndex);
    }

    private bool ActivePaneGridVisible => _activeRenderPane?.GridVisible ?? _scene.GridVisible;

    private bool ActivePaneGizmoVisible =>
        (_activeRenderPane?.GizmoVisible ?? _scene.GizmoVisible)
        && !string.Equals(_activeRenderPane?.Role, "reference", StringComparison.OrdinalIgnoreCase)
        && !string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase);

    private bool ActivePaneInteractionAllowed => _activeRenderPane?.InteractionAllowed ?? true;

    private void RecordActivePaneRender()
    {
        if (string.Equals(_activeRenderPane?.Role, "reference", StringComparison.OrdinalIgnoreCase))
        {
            _referencePaneRenderCount++;
        }
        else if (string.Equals(_activeRenderPane?.Role, "editable", StringComparison.OrdinalIgnoreCase))
        {
            _editablePaneRenderCount++;
        }
    }

    private void DrawPaneDividerOverlay()
    {
        if (_renderPaneCount != 2
            || _context is null
            || _device is null
            || _overlayInputLayout is null
            || _overlayVertexShader is null
            || _overlayPixelShader is null
            || _overlayCameraBuffer is null)
        {
            return;
        }
        var first = _renderPanes[0];
        var second = _renderPanes[1];
        var leftPane = first.Bounds.Left <= second.Bounds.Left ? first : second;
        var rightPane = first.Bounds.Left <= second.Bounds.Left ? second : first;
        var gapLeft = leftPane.Bounds.Right;
        var gapRight = rightPane.Bounds.Left;
        if (gapRight <= gapLeft)
        {
            return;
        }
        _context.RSSetViewport(new Viewport(0, 0, Math.Max(1, _renderWidth), Math.Max(1, _renderHeight), 0, 1));
        _context.OMSetBlendState(_overlayBlendState);
        _context.OMSetDepthStencilState(_overlayNoDepthState);
        _overlayCommandDepthMode = 1;
        _context.IASetInputLayout(_overlayInputLayout);
        _context.VSSetShader(_overlayVertexShader);
        _context.PSSetShader(_overlayPixelShader);
        DrawSurfaceQuad(gapLeft, 0, gapRight, _renderHeight, OverlayColor(112, 121, 132, 245));
        var center = (gapLeft + gapRight) * 0.5f;
        DrawSurfaceQuad(center - 1.0f, 0, center + 1.0f, _renderHeight, OverlayColor(232, 236, 240, 255));
        FlushOverlayPrimitives();
        _overlayCommandDepthMode = 0;
        _context.OMSetBlendState(_blendState);
        _context.OMSetDepthStencilState(_depthState);
    }

    private void DrawSurfaceQuad(float left, float top, float right, float bottom, Vector4 color)
    {
        var width = Math.Max(1.0f, _renderWidth);
        var height = Math.Max(1.0f, _renderHeight);
        var a = new Vector3((2.0f * left / width) - 1.0f, 1.0f - (2.0f * top / height), 0.0f);
        var b = new Vector3((2.0f * right / width) - 1.0f, 1.0f - (2.0f * top / height), 0.0f);
        var c = new Vector3((2.0f * right / width) - 1.0f, 1.0f - (2.0f * bottom / height), 0.0f);
        var d = new Vector3((2.0f * left / width) - 1.0f, 1.0f - (2.0f * bottom / height), 0.0f);
        _surfaceQuadVertices[0] = a;
        _surfaceQuadVertices[1] = b;
        _surfaceQuadVertices[2] = c;
        _surfaceQuadVertices[3] = a;
        _surfaceQuadVertices[4] = c;
        _surfaceQuadVertices[5] = d;
        DrawOverlayPrimitive(
            PrimitiveTopology.TriangleList,
            _surfaceQuadVertices,
            color,
            Matrix4x4.Identity);
    }

    public Dictionary<string, object?> PaneRenderStatusPayload() => new()
    {
        ["simultaneous"] = _renderPaneCount == 2,
        ["shared_device"] = true,
        ["shared_geometry_resources"] = true,
        ["reference_render_count"] = _referencePaneRenderCount,
        ["editable_render_count"] = _editablePaneRenderCount,
        ["views"] = _renderPanes.Take(_renderPaneCount).Select(pane => new Dictionary<string, object?>
        {
            ["role"] = pane.Role,
            ["x"] = pane.Bounds.X,
            ["y"] = pane.Bounds.Y,
            ["width"] = pane.Bounds.Width,
            ["height"] = pane.Bounds.Height,
            ["grid_visible"] = pane.GridVisible,
            ["xray"] = pane.XRay,
            ["interaction_allowed"] = pane.InteractionAllowed,
            ["textures_enabled"] = pane.TexturesEnabled,
        }).ToArray(),
    };
}
