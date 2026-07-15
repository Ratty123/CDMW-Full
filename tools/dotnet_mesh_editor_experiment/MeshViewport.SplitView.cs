using System.Drawing;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private const int PaneDividerWidth = 8;
    private float _paneSplitRatio = 0.5f;
    private bool _paneDividerDragging;
    private string _capturedInputPane = string.Empty;

    public event Action<float>? PaneSplitRatioChanged;
    public event Action<string>? ActivePresentationPaneChanged;

    public float PaneSplitRatio => _paneSplitRatio;
    public string ActivePresentationPane => _activeCameraContextId;
    internal static bool UsesSimultaneousRolePanes(
        string? comparisonMode,
        int editableSubmeshCount,
        int referenceSubmeshCount) =>
        string.Equals(comparisonMode, "side_by_side", StringComparison.OrdinalIgnoreCase)
        && editableSubmeshCount > 0
        && referenceSubmeshCount > 0;

    internal static string SinglePaneRoleForMode(string? comparisonMode) =>
        (comparisonMode ?? string.Empty).Trim().ToLowerInvariant() switch
        {
            "original_only" => "reference",
            "replacement_only" => "editable",
            _ => "comparison",
        };

    public bool HasSimultaneousRolePanes =>
        UsesSimultaneousRolePanes(
            _scene.ComparisonMode,
            _scene.EditableSubmeshCount,
            _scene.ReferenceSubmeshCount);
    public bool HasRenderedRequiredPresentation =>
        Metrics.HasRenderedFrame
        && (!HasSimultaneousRolePanes || _d3d11Viewport?.HasRenderedBothRolePanes == true);

    public void SetPaneSplitRatio(float ratio, bool notifyHost = false)
    {
        var normalized = Math.Clamp(float.IsFinite(ratio) ? ratio : 0.5f, 0.18f, 0.82f);
        var changed = Math.Abs(normalized - _paneSplitRatio) >= 0.0001f;
        if (changed)
        {
            _paneSplitRatio = normalized;
            PaneSplitRatioChanged?.Invoke(normalized);
        }
        if (notifyHost)
        {
            EditorEventRequested?.Invoke("presentation_split_changed", new Dictionary<string, object?>
            {
                ["ratio"] = normalized,
                ["layout"] = "simultaneous_role_panes",
            });
        }
        if (!changed)
        {
            return;
        }
        UpdateGpuViewport();
        Invalidate();
    }

    public void FocusPresentationPane(string view)
    {
        var contextId = string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase)
            ? "editable"
            : NormalizePaneId(view);
        var changed = !string.Equals(_activeCameraContextId, contextId, StringComparison.OrdinalIgnoreCase);
        SaveActivePresentationContext();
        LoadPresentationContext(contextId);
        if (changed)
        {
            ActivePresentationPaneChanged?.Invoke(contextId);
        }
        RequestFrame();
        UpdateGpuViewport();
        Invalidate();
    }

    private bool ApplyWheelZoomToPane(string view, int delta)
    {
        InitializePresentationContexts();
        SaveActivePresentationContext();
        var contextId = NormalizePaneId(view);
        if (!_presentationContexts.TryGetValue(contextId, out var context))
        {
            return false;
        }
        ApplyWheelZoomToContext(context, delta);
        if (string.Equals(contextId, _activeCameraContextId, StringComparison.OrdinalIgnoreCase))
        {
            _zoom = context.Zoom;
        }
        return true;
    }

    internal static void ApplyWheelZoomToContext(NetViewPresentationContext context, int delta)
    {
        context.Zoom = CameraZoomPolicy.ApplyWheelDelta(
            context.Zoom,
            FitZoomForBounds((context.CameraMinimum, context.CameraMaximum)),
            delta);
    }

    private static string NormalizePaneId(string? view) =>
        (view ?? string.Empty).Trim().ToLowerInvariant() is "original" or "reference" or "original_only"
            ? "reference"
            : "editable";

    private (Rectangle Reference, Rectangle Editable) RolePaneBounds()
    {
        var width = Math.Max(1, Width);
        var height = Math.Max(1, Height);
        var splitX = width <= PaneDividerWidth * 2
            ? Math.Max(1, width / 2)
            : Math.Clamp((int)MathF.Round(width * _paneSplitRatio), PaneDividerWidth, width - PaneDividerWidth);
        var halfGap = PaneDividerWidth / 2;
        var reference = new Rectangle(0, 0, Math.Max(1, splitX - halfGap), height);
        var editableX = Math.Min(width - 1, splitX + halfGap);
        var editable = new Rectangle(editableX, 0, Math.Max(1, width - editableX), height);
        return (reference, editable);
    }

    private Rectangle ActivePaneBounds()
    {
        if (!HasSimultaneousRolePanes)
        {
            return new Rectangle(0, 0, Math.Max(1, Width), Math.Max(1, Height));
        }
        var panes = RolePaneBounds();
        return string.Equals(_activeCameraContextId, "reference", StringComparison.OrdinalIgnoreCase)
            ? panes.Reference
            : panes.Editable;
    }

    private string PaneAt(Point point)
    {
        if (!HasSimultaneousRolePanes)
        {
            return _activeCameraContextId;
        }
        var panes = RolePaneBounds();
        if (panes.Reference.Contains(point)) return "reference";
        if (panes.Editable.Contains(point)) return "editable";
        return string.Empty;
    }

    private Point PaneLocalPoint(Point point, string paneId)
    {
        if (!HasSimultaneousRolePanes)
        {
            return point;
        }
        var panes = RolePaneBounds();
        var bounds = string.Equals(paneId, "reference", StringComparison.OrdinalIgnoreCase)
            ? panes.Reference
            : panes.Editable;
        return new Point(point.X - bounds.Left, point.Y - bounds.Top);
    }

    private MouseEventArgs PaneMouseEvent(MouseEventArgs source, string paneId)
    {
        var local = PaneLocalPoint(source.Location, paneId);
        return new MouseEventArgs(source.Button, source.Clicks, local.X, local.Y, source.Delta);
    }

    private bool TryBeginPaneDividerDrag(MouseEventArgs e)
    {
        if (!HasSimultaneousRolePanes || e.Button != MouseButtons.Left || PaneAt(e.Location).Length > 0)
        {
            return false;
        }
        _paneDividerDragging = true;
        SetPaneCursor(Cursors.VSplit);
        if (_d3d11Viewport is not null) _d3d11Viewport.Capture = true;
        return true;
    }

    private bool TryUpdatePaneDividerDrag(MouseEventArgs e)
    {
        if (!HasSimultaneousRolePanes)
        {
            SetPaneCursor(Cursors.Default);
            return false;
        }
        if (_paneDividerDragging)
        {
            SetPaneSplitRatio((float)e.X / Math.Max(1, Width));
            SetPaneCursor(Cursors.VSplit);
            return true;
        }
        SetPaneCursor(PaneAt(e.Location).Length == 0 ? Cursors.VSplit : Cursors.Default);
        return false;
    }

    private bool TryEndPaneDividerDrag(MouseEventArgs e)
    {
        if (!_paneDividerDragging)
        {
            return false;
        }
        _paneDividerDragging = false;
        if (_d3d11Viewport is not null) _d3d11Viewport.Capture = false;
        SetPaneSplitRatio((float)e.X / Math.Max(1, Width), notifyHost: true);
        SetPaneCursor(PaneAt(e.Location).Length == 0 ? Cursors.VSplit : Cursors.Default);
        return true;
    }

    private void SetPaneCursor(Cursor cursor)
    {
        Cursor = cursor;
        if (_d3d11Viewport is not null)
        {
            _d3d11Viewport.Cursor = cursor;
        }
    }

    private (Vec3 Min, Vec3 Max) SceneBoundsForContext(string contextId)
    {
        if (!_scene.HasAuthoritativeFrame)
        {
            return _bounds;
        }
        var reference = string.Equals(contextId, "reference", StringComparison.OrdinalIgnoreCase);
        var minimum = reference ? _scene.ReferenceBoundsMinimum : _scene.EditableBoundsMinimum;
        var maximum = reference ? _scene.ReferenceBoundsMaximum : _scene.EditableBoundsMaximum;
        return (
            new Vec3(minimum.X, minimum.Y, minimum.Z),
            new Vec3(maximum.X, maximum.Y, maximum.Z));
    }

    private (Vec3 Min, Vec3 Max) CameraBoundsForContext(string contextId)
    {
        // Resident placement bounds move with the editable model. Camera frames
        // remain captured until an explicit Fit command requests a reframe.
        if (_presentationContexts.TryGetValue(contextId, out var context))
        {
            return (context.CameraMinimum, context.CameraMaximum);
        }
        return SceneBoundsForContext(contextId);
    }

    private void ReframePresentationContext(string contextId)
    {
        InitializePresentationContexts();
        if (!_presentationContexts.TryGetValue(contextId, out var context))
        {
            return;
        }
        var bounds = SceneBoundsForContext(contextId);
        context.CameraMinimum = bounds.Min;
        context.CameraMaximum = bounds.Max;
    }

    private static Vec3 BoundsCenter((Vec3 Min, Vec3 Max) bounds) => new(
        (bounds.Min.X + bounds.Max.X) * 0.5f,
        (bounds.Min.Y + bounds.Max.Y) * 0.5f,
        (bounds.Min.Z + bounds.Max.Z) * 0.5f);

    private static float FitZoomForBounds((Vec3 Min, Vec3 Max) bounds)
    {
        var size = Math.Max(
            bounds.Max.X - bounds.Min.X,
            Math.Max(bounds.Max.Y - bounds.Min.Y, bounds.Max.Z - bounds.Min.Z));
        return CameraZoomPolicy.FitZoomForSceneSize(size);
    }

    private float FitZoomForContext(string contextId) =>
        FitZoomForBounds(CameraBoundsForContext(contextId));

    private NetViewportCamera CameraForContext(string contextId, Rectangle bounds)
    {
        InitializePresentationContexts();
        var context = _presentationContexts.GetValueOrDefault(contextId)
            ?? _presentationContexts["editable"];
        var cameraBounds = CameraBoundsForContext(context.Id);
        return NetViewportCamera.Create(
            BoundsCenter(cameraBounds),
            cameraBounds,
            context.Yaw,
            context.Pitch,
            context.Zoom,
            context.PanX,
            context.PanY,
            Math.Max(1, bounds.Width),
            Math.Max(1, bounds.Height));
    }

    private D3D11RenderPane[] CurrentRenderPanes()
    {
        SaveActivePresentationContext();
        if (HasSimultaneousRolePanes)
        {
            var bounds = RolePaneBounds();
            var reference = _presentationContexts["reference"];
            var editable = _presentationContexts["editable"];
            return new[]
            {
                RenderPane(bounds.Reference, reference, "reference", interactionAllowed: false),
                RenderPane(bounds.Editable, editable, "editable", interactionAllowed: true),
            };
        }
        var role = SinglePaneRoleForMode(_scene.ComparisonMode);
        var context = _presentationContexts[_activeCameraContextId];
        var full = new Rectangle(0, 0, Math.Max(1, Width), Math.Max(1, Height));
        return new[] { RenderPane(full, context, role, PresentationInteractionAllowed) };
    }

    private D3D11RenderPane RenderPane(
        Rectangle bounds,
        NetViewPresentationContext context,
        string role,
        bool interactionAllowed) => new(
            bounds,
            CameraForContext(context.Id, bounds),
            role,
            context.DisplayMode,
            context.MaterialDebugMode,
            context.TexturesEnabled,
            context.GridVisible,
            context.GizmoVisible && role == "editable",
            interactionAllowed);

    private Dictionary<string, object?> PaneRectangleStatusPayload()
    {
        var bounds = HasSimultaneousRolePanes
            ? RolePaneBounds()
            : (new Rectangle(0, 0, Math.Max(1, Width), Math.Max(1, Height)),
               new Rectangle(0, 0, Math.Max(1, Width), Math.Max(1, Height)));
        Dictionary<string, object?> Payload(string id, Rectangle rectangle)
        {
            var cameraBounds = CameraBoundsForContext(id);
            var center = BoundsCenter(cameraBounds);
            return new Dictionary<string, object?>
            {
                ["x"] = rectangle.X,
                ["y"] = rectangle.Y,
                ["width"] = rectangle.Width,
                ["height"] = rectangle.Height,
                ["center"] = new[] { center.X, center.Y, center.Z },
                ["bounds_minimum"] = new[] { cameraBounds.Min.X, cameraBounds.Min.Y, cameraBounds.Min.Z },
                ["bounds_maximum"] = new[] { cameraBounds.Max.X, cameraBounds.Max.Y, cameraBounds.Max.Z },
            };
        }
        return new Dictionary<string, object?>
        {
            ["reference"] = Payload("reference", bounds.Item1),
            ["editable"] = Payload("editable", bounds.Item2),
        };
    }

    private System.Numerics.Matrix4x4 ActiveSceneModelMatrix(int submeshIndex) =>
        HasSimultaneousRolePanes
            ? _scene.RoleViewModelMatrix(submeshIndex)
            : _scene.ModelMatrix(submeshIndex);

    private bool ActivePaneIncludesForPicking(int submeshIndex)
    {
        if (!HasSimultaneousRolePanes)
        {
            return _scene.IsVisible(submeshIndex);
        }
        return string.Equals(_activeCameraContextId, "reference", StringComparison.OrdinalIgnoreCase)
            ? _scene.IsReference(submeshIndex)
            : _scene.IsEditable(submeshIndex);
    }

    private System.Numerics.Vector3 ActiveGizmoPivot() =>
        HasSimultaneousRolePanes
            ? _scene.RoleViewGizmoPivot()
            : _scene.EffectiveGizmoPivot();
}
