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
    bool InteractionAllowed);

internal sealed partial class D3D11MaterialViewport
{
    private D3D11RenderPane[] _renderPanes = Array.Empty<D3D11RenderPane>();
    private D3D11RenderPane? _activeRenderPane;
    private long _referencePaneRenderCount;
    private long _editablePaneRenderCount;

    public bool HasRenderedBothRolePanes =>
        _referencePaneRenderCount > 0 && _editablePaneRenderCount > 0;

    public void UpdateRenderPanes(IEnumerable<D3D11RenderPane> panes)
    {
        _renderPanes = panes
            .Where(pane => pane.Bounds.Width > 0 && pane.Bounds.Height > 0)
            .ToArray();
    }

    private IReadOnlyList<D3D11RenderPane> PanesForFrame(bool replacementOnly)
    {
        if (!replacementOnly && _renderPanes.Length > 0)
        {
            return _renderPanes;
        }
        return new[]
        {
            new D3D11RenderPane(
                new Rectangle(0, 0, Math.Max(1, _renderWidth), Math.Max(1, _renderHeight)),
                _camera,
                replacementOnly ? "editable" : "comparison",
                TexturesEnabled ? "textured" : (ShowSolid ? "solid" : "wire"),
                MaterialDebugMode,
                TexturesEnabled,
                _scene.GridVisible,
                _scene.GizmoVisible,
                true),
        };
    }

    private void ActivateRenderPane(D3D11RenderPane pane)
    {
        _activeRenderPane = pane;
        _camera = pane.Camera;
        _materialDebugMode = Math.Clamp(pane.MaterialDebugMode, 0, 12);
        var mode = (pane.DisplayMode ?? "textured").Trim().ToLowerInvariant();
        ShowSolid = mode is not ("wire" or "vertices");
        TexturesEnabled = pane.TexturesEnabled && mode is ("textured" or "textured_wire");
        _overlayShowWire = mode is "wire" or "wire_vertices" or "xray";
        _overlayShowVertices = mode is "vertices" or "wire_vertices";
        _overlayShowXRay = mode == "xray";
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
        && !string.Equals(_activeRenderPane?.Role, "reference", StringComparison.OrdinalIgnoreCase);

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
        if (_renderPanes.Length != 2
            || _context is null
            || _device is null
            || _overlayInputLayout is null
            || _overlayVertexShader is null
            || _overlayPixelShader is null
            || _overlayCameraBuffer is null)
        {
            return;
        }
        var ordered = _renderPanes.OrderBy(pane => pane.Bounds.Left).ToArray();
        var gapLeft = ordered[0].Bounds.Right;
        var gapRight = ordered[1].Bounds.Left;
        if (gapRight <= gapLeft)
        {
            return;
        }
        _context.RSSetViewport(new Viewport(0, 0, Math.Max(1, _renderWidth), Math.Max(1, _renderHeight), 0, 1));
        _context.OMSetBlendState(_overlayBlendState);
        _context.OMSetDepthStencilState(_overlayNoDepthState);
        _context.IASetInputLayout(_overlayInputLayout);
        _context.VSSetShader(_overlayVertexShader);
        _context.PSSetShader(_overlayPixelShader);
        DrawSurfaceQuad(gapLeft, 0, gapRight, _renderHeight, OverlayColor(112, 121, 132, 245));
        var center = (gapLeft + gapRight) * 0.5f;
        DrawSurfaceQuad(center - 1.0f, 0, center + 1.0f, _renderHeight, OverlayColor(232, 236, 240, 255));
        _context.OMSetBlendState(_blendState);
        _context.OMSetDepthStencilState(_depthState);
    }

    private void DrawSurfaceQuad(float left, float top, float right, float bottom, Vector4 color)
    {
        var width = Math.Max(1.0f, _renderWidth);
        var height = Math.Max(1.0f, _renderHeight);
        Vector3 Clip(float x, float y) => new((2.0f * x / width) - 1.0f, 1.0f - (2.0f * y / height), 0.0f);
        var a = Clip(left, top);
        var b = Clip(right, top);
        var c = Clip(right, bottom);
        var d = Clip(left, bottom);
        DrawOverlayPrimitive(
            PrimitiveTopology.TriangleList,
            new[] { a, b, c, a, c, d },
            color,
            Matrix4x4.Identity);
    }

    public Dictionary<string, object?> PaneRenderStatusPayload() => new()
    {
        ["simultaneous"] = _renderPanes.Length == 2,
        ["shared_device"] = true,
        ["shared_geometry_resources"] = true,
        ["reference_render_count"] = _referencePaneRenderCount,
        ["editable_render_count"] = _editablePaneRenderCount,
        ["views"] = _renderPanes.Select(pane => new Dictionary<string, object?>
        {
            ["role"] = pane.Role,
            ["x"] = pane.Bounds.X,
            ["y"] = pane.Bounds.Y,
            ["width"] = pane.Bounds.Width,
            ["height"] = pane.Bounds.Height,
            ["grid_visible"] = pane.GridVisible,
            ["interaction_allowed"] = pane.InteractionAllowed,
            ["textures_enabled"] = pane.TexturesEnabled,
        }).ToArray(),
    };
}
