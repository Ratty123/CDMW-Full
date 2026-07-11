using System.Drawing;
using System.Globalization;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    public void SetCameraPreset(string preset)
    {
        var normalized = (preset ?? string.Empty).Trim().ToLowerInvariant();
        _panX = 0;
        _panY = 0;
        if (normalized == "front")
        {
            _yaw = 0.0f;
            _pitch = 0.0f;
        }
        else if (normalized == "back")
        {
            _yaw = MathF.PI;
            _pitch = 0.0f;
        }
        else if (normalized == "left")
        {
            _yaw = -MathF.PI * 0.5f;
            _pitch = 0.0f;
        }
        else if (normalized == "right")
        {
            _yaw = MathF.PI * 0.5f;
            _pitch = 0.0f;
        }
        else if (normalized == "top")
        {
            _yaw = 0.0f;
            _pitch = -1.35f;
        }
        else if (normalized == "bottom")
        {
            _yaw = 0.0f;
            _pitch = 1.35f;
        }
        UpdateGpuViewport();
        Invalidate();
    }

    public void RotateYawDegrees(float degrees)
    {
        _yaw += degrees * MathF.PI / 180.0f;
        UpdateGpuViewport();
        Invalidate();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _d3d11Viewport?.Dispose();
            _gpuViewport?.Dispose();
            _gpuHost?.Dispose();
        }
        base.Dispose(disposing);
    }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        UpdateGpuViewport();
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        _lastMouse = e.Location;
        if (e.Button == MouseButtons.Left && !string.Equals(ActiveTool, "orbit", StringComparison.OrdinalIgnoreCase))
        {
            if (string.Equals(ActiveTool, "select", StringComparison.OrdinalIgnoreCase))
            {
                var targetMode = CurrentTargetMode();
                if (string.Equals(targetMode, "edge", StringComparison.OrdinalIgnoreCase))
                {
                    BeginEdgeDrag(e.Location);
                }
                else if (string.Equals(targetMode, "vertex", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(targetMode, "face", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(targetMode, "part", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(targetMode, "source", StringComparison.OrdinalIgnoreCase))
                {
                    BeginSelectionDrag(e.Location, targetMode);
                }
                else
                {
                    EditorEventRequested?.Invoke("select_request", PointerPayload(e.Location, null, false));
                }
            }
            else
            {
                _editorStrokeActive = true;
                _strokePrevious = e.Location;
                _strokeId++;
                EditorEventRequested?.Invoke("stroke_begin", PointerPayload(e.Location, e.Location, true, includeLocalSelection: true));
            }
            base.OnMouseDown(e);
            return;
        }
        _rotating = e.Button == MouseButtons.Left;
        _panning = e.Button == MouseButtons.Right || (ModifierKeys & Keys.Shift) == Keys.Shift;
        base.OnMouseDown(e);
    }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        if (_edgeDragActive)
        {
            FinishEdgeDrag(e.Location);
        }
        if (_editorStrokeActive)
        {
            EditorEventRequested?.Invoke("stroke_end", PointerPayload(e.Location, _strokePrevious, true));
            _strokePrevious = e.Location;
            _editorStrokeActive = false;
        }
        _rotating = false;
        _panning = false;
        base.OnMouseUp(e);
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        var dx = e.X - _lastMouse.X;
        var dy = e.Y - _lastMouse.Y;
        _lastMouse = e.Location;
        if (_edgeDragActive)
        {
            _edgeDragCurrent = e.Location;
            UpdateGpuViewport();
            Invalidate();
        }
        if (!_edgeDragActive
            && !_editorStrokeActive
            && !_rotating
            && !_panning
            && string.Equals(ActiveTool, "select", StringComparison.OrdinalIgnoreCase)
            && string.Equals(CurrentTargetMode(), "edge", StringComparison.OrdinalIgnoreCase))
        {
            UpdateHoverEdge(e.Location);
        }
        if (_editorStrokeActive)
        {
            if ((e.Button & MouseButtons.Left) == MouseButtons.Left)
            {
                EditorEventRequested?.Invoke("stroke_update", PointerPayload(e.Location, _strokePrevious, true));
                _strokePrevious = e.Location;
                Invalidate();
            }
        }
        else if (_rotating)
        {
            _yaw += dx * 0.01f;
            _pitch = Math.Clamp(_pitch + dy * 0.01f, -1.45f, 1.45f);
            Invalidate();
        }
        else if (_panning)
        {
            _panX += dx;
            _panY += dy;
            Invalidate();
        }
        UpdateGpuViewport();
        base.OnMouseMove(e);
    }

    protected override void OnMouseWheel(MouseEventArgs e)
    {
        _zoom *= e.Delta > 0 ? 1.1f : 0.9f;
        _zoom = Math.Clamp(_zoom, 10.0f, 5000.0f);
        UpdateGpuViewport();
        Invalidate();
        base.OnMouseWheel(e);
    }

    private Dictionary<string, object?> PointerPayload(Point point, Point? start, bool stroke, bool includeLocalSelection = false)
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        var radius = NumberOption(options, "radius", 24.0);
        var screenPayload = ScreenPayload(point, radius);
        var payload = new Dictionary<string, object?>(options)
        {
            ["tool"] = ActiveTool,
            ["screen_brush"] = screenPayload
        };
        if (includeLocalSelection)
        {
            payload["local_selection"] = SelectionSnapshotPayload();
        }
        if (stroke)
        {
            var origin = start ?? point;
            payload["stroke_id"] = _strokeId.ToString(CultureInfo.InvariantCulture);
            payload["screen_drag"] = ScreenDragPayload(origin, point);
        }
        return payload;
    }

    private Dictionary<string, object?> ScreenPayload(Point point, double radius)
    {
        return new Dictionary<string, object?>
        {
            ["x"] = point.X,
            ["y"] = point.Y,
            ["radius"] = radius,
            ["radius_pixels"] = radius,
            ["viewport_width"] = Math.Max(1, Width),
            ["viewport_height"] = Math.Max(1, Height),
            ["world_view_projection"] = WorldViewProjection()
        };
    }

    private Dictionary<string, object?> ScreenDragPayload(Point start, Point end)
    {
        return new Dictionary<string, object?>
        {
            ["start_x"] = start.X,
            ["start_y"] = start.Y,
            ["end_x"] = end.X,
            ["end_y"] = end.Y,
            ["viewport_width"] = Math.Max(1, Width),
            ["viewport_height"] = Math.Max(1, Height),
            ["world_view_projection"] = WorldViewProjection()
        };
    }

    private double[] WorldViewProjection()
    {
        return CurrentCamera().WorldViewProjectionRowMajorArray();
    }

    private void BeginSelectionDrag(Point point, string mode)
    {
        _edgeDragActive = true;
        _selectionDragTargetMode = (mode ?? "edge").Trim().ToLowerInvariant();
        _edgeDragStart = point;
        _edgeDragCurrent = point;
        _hoverEdgeId = _selectionDragTargetMode == "edge" ? PickEdgeAt(point) : -1;
        UpdateGpuViewport();
        Invalidate();
    }
}
