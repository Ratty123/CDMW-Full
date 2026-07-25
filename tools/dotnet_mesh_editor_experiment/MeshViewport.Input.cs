using System.Drawing;
using System.Globalization;
using System.Numerics;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    /// <summary>
    /// The tools that drive a mesh-edit stroke. Every other tool either orbits
    /// or resolves a selection, and must never open a stroke: the host rejects
    /// a stroke payload whose tool is not one of these.
    /// </summary>
    private static readonly HashSet<string> StrokeTools = new(StringComparer.OrdinalIgnoreCase)
    {
        "move", "grab", "smooth", "inflate", "pinch",
    };

    // The tool a stroke opened with. Update and end phases report this instead
    // of the live ActiveTool, so switching tools (or leaving mesh-edit mode)
    // mid-gesture can never emit a stroke the host has to reject.
    private string _strokeTool = string.Empty;

    internal static bool IsStrokeTool(string? tool) =>
        tool is not null && StrokeTools.Contains(tool.Trim());

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
        NotifyViewStateChanged();
        UpdateGpuViewport();
    }

    public void RotateYawDegrees(float degrees)
    {
        _yaw += degrees * MathF.PI / 180.0f;
        NotifyViewStateChanged();
        UpdateGpuViewport();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            StopPerformanceRenderPump();
            _renderSurfaceResizeTimer.Stop();
            _renderSurfaceResizeTimer.Tick -= OnRenderSurfaceResizeTimerTick;
            _renderSurfaceResizeTimer.Dispose();
            _d3d11Viewport?.Dispose();
            _gpuViewport?.Dispose();
            _gpuHost?.Dispose();
        }
        base.Dispose(disposing);
    }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        if (_d3d11Viewport is not null)
        {
            QueueRenderSurfaceResize();
        }
        else
        {
            UpdateGpuViewport();
        }
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        try
        {
            HandleMouseDownCore(e);
        }
        finally
        {
            // Handlers attached to MouseDown move focus onto the viewport, and a
            // focus change cancels the render surface's mouse capture. Without
            // capture the matching mouse-up is delivered to whatever control the
            // pointer happens to be over, so a drag that leaves the viewport
            // strands the gesture: the stroke stays open and every later drag
            // emits stroke updates for whichever tool is active by then.
            // Re-assert capture once the handlers have run.
            if (_capturedInputPane.Length > 0 || _paneDividerDragging)
            {
                SetRenderSurfaceCapture(true);
            }
        }
    }

    private void HandleMouseDownCore(MouseEventArgs e)
    {
        if (TryBeginPaneDividerDrag(e))
        {
            return;
        }
        var paneId = PaneAt(e.Location);
        if (paneId.Length == 0)
        {
            return;
        }
        FocusPresentationPane(paneId);
        _capturedInputPane = paneId;
        SetRenderSurfaceCapture(true);
        e = PaneMouseEvent(e, paneId);
        _pointerInside = true;
        _pointerLocation = e.Location;
        _lastMouse = e.Location;
        if (IsPanGesture(e))
        {
            _rotating = false;
            _panning = true;
            base.OnMouseDown(e);
            return;
        }
        if (IsOrbitOverrideGesture(e))
        {
            _rotating = true;
            _panning = false;
            base.OnMouseDown(e);
            return;
        }
        if (!PresentationInteractionAllowed)
        {
            _rotating = e.Button == MouseButtons.Left;
            _panning = false;
            base.OnMouseDown(e);
            return;
        }
        if (e.Button == MouseButtons.Left
            && !string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase))
        {
            if (TryBeginPlacementGizmoDrag(e.Location))
            {
                return;
            }
            if (PartPickEnabled)
            {
                BeginSelectionDrag(e.Location, "source");
                base.OnMouseDown(e);
                return;
            }
            _rotating = true;
            base.OnMouseDown(e);
            return;
        }
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
            else if (IsStrokeTool(ActiveTool))
            {
                BeginEditorStroke(e.Location);
            }
            else
            {
                // An unknown tool must orbit rather than open a stroke the host
                // is guaranteed to reject.
                _rotating = true;
            }
            base.OnMouseDown(e);
            return;
        }
        _rotating = e.Button == MouseButtons.Left;
        _panning = false;
        base.OnMouseDown(e);
    }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        if (TryEndPaneDividerDrag(e))
        {
            return;
        }
        var paneId = _capturedInputPane.Length > 0 ? _capturedInputPane : PaneAt(e.Location);
        try
        {
            if (paneId.Length == 0)
            {
                return;
            }
            e = PaneMouseEvent(e, paneId);
            if (_edgeDragActive)
            {
                FinishEdgeDrag(e.Location);
            }
            EndEditorStroke(e.Location, cancelled: false);
            base.OnMouseUp(e);
        }
        finally
        {
            _rotating = false;
            _panning = false;
            _edgeDragActive = false;
            EndEditorStroke(_strokePrevious, cancelled: true);
            _capturedInputPane = string.Empty;
            SetRenderSurfaceCapture(false);
            if (_placementDragActive)
            {
                EndPlacementGizmoDrag();
            }
        }
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        if (TryUpdatePaneDividerDrag(e))
        {
            return;
        }
        var paneId = _capturedInputPane.Length > 0 ? _capturedInputPane : PaneAt(e.Location);
        if (paneId.Length == 0
            || (_capturedInputPane.Length == 0
                && !string.Equals(paneId, _activeCameraContextId, StringComparison.OrdinalIgnoreCase)))
        {
            return;
        }
        e = PaneMouseEvent(e, paneId);
        _pointerInside = true;
        _pointerLocation = e.Location;
        var dx = e.X - _lastMouse.X;
        var dy = e.Y - _lastMouse.Y;
        _lastMouse = e.Location;
        if ((e.Button & MouseButtons.Left) != MouseButtons.Left)
        {
            // The button is no longer held, so any gesture that was waiting for
            // a mouse-up is over whether or not that mouse-up ever arrived.
            // Closing it here keeps a lost capture from leaving the camera
            // orbiting on hover or a stroke open across later gestures.
            EndEditorStroke(e.Location, cancelled: false);
            _rotating = false;
            _panning = false;
        }
        if (_placementDragActive && (e.Button & MouseButtons.Left) == MouseButtons.Left)
        {
            UpdatePlacementGizmoDrag(e.Location);
            base.OnMouseMove(e);
            return;
        }
        if (!_rotating
            && !_panning
            && !string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase))
        {
            UpdateGizmoHover(e.Location);
        }
        if (_edgeDragActive)
        {
            _edgeDragCurrent = e.Location;
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
                EditorEventRequested?.Invoke("stroke_update", StrokePointerPayload(e.Location, _strokePrevious));
                _strokePrevious = e.Location;
            }
        }
        else if (_rotating)
        {
            var radiansPerPixel = _residentPresentationSettings.OrbitSensitivity * MathF.PI / 180.0f;
            var orbitX = _residentPresentationSettings.InvertOrbitX ? -dx : dx;
            var orbitY = _residentPresentationSettings.InvertOrbitY ? -dy : dy;
            _yaw += orbitX * radiansPerPixel;
            _pitch = Math.Clamp(_pitch + orbitY * radiansPerPixel, -1.45f, 1.45f);
            NotifyViewStateChanged();
        }
        else if (_panning)
        {
            var panX = _residentPresentationSettings.InvertPanX ? -dx : dx;
            var panY = _residentPresentationSettings.InvertPanY ? -dy : dy;
            _panX += panX * _residentPresentationSettings.PanSensitivity;
            _panY += panY * _residentPresentationSettings.PanSensitivity;
            NotifyViewStateChanged();
        }
        UpdateGpuViewport();
        base.OnMouseMove(e);
    }

    protected override void OnMouseEnter(EventArgs e)
    {
        _pointerInside = true;
        base.OnMouseEnter(e);
    }

    protected override void OnMouseLeave(EventArgs e)
    {
        _pointerInside = false;
        if (!_paneDividerDragging)
        {
            Cursor = Cursors.Default;
        }
        UpdateGpuViewport();
        base.OnMouseLeave(e);
    }

    protected override void OnMouseWheel(MouseEventArgs e)
    {
        var paneId = PaneAt(e.Location);
        if (paneId.Length == 0)
        {
            return;
        }
        if (!ApplyWheelZoomToPane(paneId, e.Delta))
        {
            return;
        }
        NotifyViewStateChanged();
        UpdateGpuViewport();
        base.OnMouseWheel(e);
    }

    private static bool IsPanGesture(MouseEventArgs e)
    {
        return e.Button is MouseButtons.Middle or MouseButtons.Right
            || (e.Button == MouseButtons.Left && (ModifierKeys & Keys.Shift) == Keys.Shift);
    }

    private static bool IsOrbitOverrideGesture(MouseEventArgs e)
    {
        return e.Button == MouseButtons.Left
            && (ModifierKeys & Keys.Control) == Keys.Control;
    }

    private void BeginEditorStroke(Point location)
    {
        _editorStrokeActive = true;
        _strokeTool = ActiveTool;
        _strokePrevious = location;
        _strokeId++;
        EditorEventRequested?.Invoke("stroke_begin", StrokePointerPayload(location, location));
    }

    /// <summary>
    /// Closes the stroke that is currently open, if any. Safe to call more than
    /// once for the same gesture: only the first call reports a phase.
    /// </summary>
    private void EndEditorStroke(Point location, bool cancelled)
    {
        if (!_editorStrokeActive)
        {
            return;
        }
        _editorStrokeActive = false;
        var payload = StrokePointerPayload(location, _strokePrevious);
        _strokePrevious = location;
        _strokeTool = string.Empty;
        EditorEventRequested?.Invoke(cancelled ? "stroke_cancel" : "stroke_end", payload);
    }

    /// <summary>
    /// Aborts an open stroke without committing it. Used when the tool, the
    /// interaction mode, or the input focus changes underneath a live gesture.
    /// </summary>
    internal void CancelActiveStroke()
    {
        EndEditorStroke(_strokePrevious, cancelled: true);
        _rotating = false;
        _panning = false;
    }

    protected override void OnLostFocus(EventArgs e)
    {
        CancelActiveStroke();
        base.OnLostFocus(e);
    }

    private Dictionary<string, object?> StrokePointerPayload(Point point, Point? start) =>
        PointerPayload(point, start, stroke: true, toolOverride: _strokeTool);

    private Dictionary<string, object?> PointerPayload(
        Point point,
        Point? start,
        bool stroke,
        string? toolOverride = null)
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        var radius = NumberOption(options, "radius", 24.0);
        var screenPayload = ScreenPayload(point, radius);
        var tool = string.IsNullOrEmpty(toolOverride) ? ActiveTool : toolOverride;
        var payload = new Dictionary<string, object?>(options)
        {
            ["tool"] = tool,
            ["screen_brush"] = screenPayload
        };
        if (tool is "inflate" or "pinch")
        {
            payload["screen_radius"] = new Dictionary<string, object?>(screenPayload)
            {
                ["amount_scale"] = 0.08,
            };
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
        var viewport = ActivePaneBounds();
        var camera = CurrentCamera();
        return new Dictionary<string, object?>
        {
            ["x"] = point.X,
            ["y"] = point.Y,
            ["radius"] = radius,
            ["radius_pixels"] = radius,
            ["viewport_width"] = Math.Max(1, viewport.Width),
            ["viewport_height"] = Math.Max(1, viewport.Height),
            ["world_view_projection"] = camera.WorldViewProjectionRowMajorArray(),
            ["source_submesh_indices"] = VisibleEditableSubmeshIndices(),
            ["source_submesh_world_view_projections"] = SourceProjectionOverrides(camera),
        };
    }

    private Dictionary<string, object?> ScreenDragPayload(Point start, Point end)
    {
        var viewport = ActivePaneBounds();
        var camera = CurrentCamera();
        return new Dictionary<string, object?>
        {
            ["start_x"] = start.X,
            ["start_y"] = start.Y,
            ["end_x"] = end.X,
            ["end_y"] = end.Y,
            ["viewport_width"] = Math.Max(1, viewport.Width),
            ["viewport_height"] = Math.Max(1, viewport.Height),
            ["world_view_projection"] = camera.WorldViewProjectionRowMajorArray(),
            ["source_submesh_indices"] = VisibleEditableSubmeshIndices(),
            ["source_submesh_world_view_projections"] = SourceProjectionOverrides(camera),
        };
    }

    private int[] VisibleEditableSubmeshIndices()
    {
        return Enumerable.Range(0, Math.Min(_scene.EditableSubmeshCount, _document.Submeshes.Count))
            .Where(IsSubmeshVisibleForViewportSelection)
            .ToArray();
    }

    private Dictionary<string, object?>[] SourceProjectionOverrides(NetViewportCamera camera)
    {
        return Enumerable.Range(0, Math.Min(_scene.EditableSubmeshCount, _document.Submeshes.Count))
            .Select(submeshIndex => new Dictionary<string, object?>
            {
                ["source_submesh_index"] = submeshIndex,
                ["world_view_projection"] = MatrixRowMajorArray(
                    ActiveSceneModelMatrix(submeshIndex) * camera.WorldViewProjection),
            })
            .ToArray();
    }

    private static double[] MatrixRowMajorArray(Matrix4x4 matrix)
    {
        return new[]
        {
            (double)matrix.M11, (double)matrix.M12, (double)matrix.M13, (double)matrix.M14,
            (double)matrix.M21, (double)matrix.M22, (double)matrix.M23, (double)matrix.M24,
            (double)matrix.M31, (double)matrix.M32, (double)matrix.M33, (double)matrix.M34,
            (double)matrix.M41, (double)matrix.M42, (double)matrix.M43, (double)matrix.M44,
        };
    }

    private void BeginSelectionDrag(Point point, string mode)
    {
        _edgeDragActive = true;
        _selectionDragTargetMode = (mode ?? "edge").Trim().ToLowerInvariant();
        _edgeDragStart = point;
        _edgeDragCurrent = point;
        _hoverEdgeId = _selectionDragTargetMode == "edge" ? PickEdgeAt(point) : -1;
        UpdateGpuViewport();
    }
}
