using System.Drawing;
using System.Globalization;
using System.Numerics;
using System.Windows.Forms;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    /// <summary>Tools allowed to open mesh-edit strokes; all others select or orbit.</summary>
    private static readonly HashSet<string> StrokeTools = new(StringComparer.OrdinalIgnoreCase)
    {
        "move", "grab", "smooth", "inflate", "pinch",
    };
    private const double EditorStrokeProtocolIntervalMs = 16.0;
    // The tool a stroke opened with. Update and end phases report this instead
    // of the live ActiveTool, so switching tools (or leaving mesh-edit mode)
    // mid-gesture can never emit a stroke the host has to reject.
    private string _strokeTool = string.Empty;
    internal Action<string>? InputBoundaryFaultInjector { get; set; }
    private readonly MeshEditOperatorController _editOperators = new();
    private readonly MeshViewportInputAdapter _inputAdapter = new();
    internal Dictionary<string, object?> EditOperatorDiagnostics() => _editOperators.Diagnostics();

    private bool BeginEditOperator(
        string kind,
        string tool,
        string selectionDomain,
        string gestureId)
    {
        var snapshot = new MeshEditOperatorSnapshot(
            kind,
            tool,
            _scene.InteractionMode,
            selectionDomain,
            gestureId,
            _paintProjectionBuildRequest,
            _paintProjectionGeometryRevision,
            AcknowledgedSelectionRevision,
            _edgeTopology.Generation);
        if (_editOperators.Begin(snapshot, out var reason))
        {
            return true;
        }
        StatusRequested?.Invoke(
            $"Mesh Editor gesture blocked: {reason.Replace('_', ' ')}.");
        return false;
    }

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
        InvalidatePaintProjectionCache("camera_preset");
        NotifyViewStateChanged();
        UpdateGpuViewport();
        QueuePaintProjectionPrewarm();
    }

    public void RotateYawDegrees(float degrees)
    {
        _yaw += degrees * MathF.PI / 180.0f;
        InvalidatePaintProjectionCache("camera_yaw");
        NotifyViewStateChanged();
        UpdateGpuViewport();
        QueuePaintProjectionPrewarm();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            CancelPaintProjectionBuild();
            StopPerformanceRenderPump();
            _renderSurfaceResizeTimer.Stop();
            _renderSurfaceResizeTimer.Tick -= OnRenderSurfaceResizeTimerTick;
            _renderSurfaceResizeTimer.Dispose();
            _d3d11Viewport?.Dispose();
            _gpuViewport?.Dispose();
            _gpuHost?.Dispose();
            _editOperators.Dispose();
        }
        base.Dispose(disposing);
    }

    protected override void OnResize(EventArgs e)
    {
        base.OnResize(e);
        InvalidatePaintProjectionCache("viewport_size");
        if (_d3d11Viewport is not null)
        {
            QueueRenderSurfaceResize();
        }
        else
        {
            UpdateGpuViewport();
            QueuePaintProjectionPrewarm();
        }
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        try
        {
            if (TryBeginPaneDividerDrag(e))
            {
                return;
            }
            HandleMouseDownCore(
                _inputAdapter.NormalizeDown(e, ModifierKeys, Capture, Focused),
                e);
        }
        catch (Exception ex)
        {
            RecoverInputBoundary("mouse_down", ex);
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

    private void HandleMouseDownCore(
        MeshPointerInput input,
        MouseEventArgs platformEvent)
    {
        var paneId = PaneAt(input.Location);
        if (paneId.Length == 0)
        {
            return;
        }
        FocusPresentationPane(paneId);
        _capturedInputPane = paneId;
        SetRenderSurfaceCapture(true);
        input = input.At(PaneLocalPoint(input.Location, paneId));
        _pointerInside = true;
        _pointerLocation = input.Location;
        _lastMouse = input.Location;
        if (IsPanGesture(input))
        {
            _rotating = false;
            _panning = true;
            base.OnMouseDown(platformEvent);
            return;
        }
        if (IsOrbitOverrideGesture(input))
        {
            _rotating = true;
            _panning = false;
            base.OnMouseDown(platformEvent);
            return;
        }
        if (!PresentationInteractionAllowed)
        {
            _rotating = input.Changed(MeshPointerButtons.Left);
            _panning = false;
            base.OnMouseDown(platformEvent);
            return;
        }
        if (input.Changed(MeshPointerButtons.Left)
            && !string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase))
        {
            if (TryBeginPlacementGizmoDrag(input.Location))
            {
                return;
            }
            if (PartPickEnabled)
            {
                BeginSelectionDrag(input.Location, "source");
                base.OnMouseDown(platformEvent);
                return;
            }
            _rotating = true;
            base.OnMouseDown(platformEvent);
            return;
        }
        if (input.Changed(MeshPointerButtons.Left) && !string.Equals(ActiveTool, "orbit", StringComparison.OrdinalIgnoreCase))
        {
            if (string.Equals(ActiveTool, "select", StringComparison.OrdinalIgnoreCase))
            {
                var targetMode = CurrentTargetMode();
                if (string.Equals(targetMode, "edge", StringComparison.OrdinalIgnoreCase))
                {
                    BeginEdgeDrag(input.Location);
                }
                else if (string.Equals(targetMode, "vertex", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(targetMode, "face", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(targetMode, "part", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(targetMode, "source", StringComparison.OrdinalIgnoreCase))
                {
                    BeginSelectionDrag(input.Location, targetMode);
                }
                else
                {
                    EditorEventRequested?.Invoke("select_request", PointerPayload(input.Location, null, false));
                }
            }
            else if (IsStrokeTool(ActiveTool))
            {
                BeginEditorStroke(input.Location);
            }
            else
            {
                // An unknown tool must orbit rather than open a stroke the host
                // is guaranteed to reject.
                _rotating = true;
            }
            base.OnMouseDown(platformEvent);
            return;
        }
        _rotating = input.Changed(MeshPointerButtons.Left);
        _panning = false;
        base.OnMouseDown(platformEvent);
    }

    protected override void OnMouseUp(MouseEventArgs e)
    {
        if (TryEndPaneDividerDrag(e))
        {
            return;
        }
        var input = _inputAdapter.NormalizeUp(e, ModifierKeys, Capture, Focused);
        var paneId = _capturedInputPane.Length > 0 ? _capturedInputPane : PaneAt(input.Location);
        try
        {
            if (paneId.Length == 0)
            {
                return;
            }
            input = input.At(PaneLocalPoint(input.Location, paneId));
            FinishSelectionGesture(input.Location, cancelled: false);
            EndEditorStroke(input.Location, cancelled: false);
            base.OnMouseUp(e);
        }
        catch (Exception ex)
        {
            RecoverInputBoundary("mouse_up", ex);
        }
        finally
        {
            ForceInputGestureTerminalState();
            if (_placementDragActive)
            {
                EndPlacementGizmoDrag();
            }
            QueuePaintProjectionPrewarm();
        }
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        try
        {
            if (TryUpdatePaneDividerDrag(e))
            {
                return;
            }
            HandleMouseMoveCore(
                _inputAdapter.NormalizeMove(e, ModifierKeys, Capture, Focused),
                e);
        }
        catch (Exception ex)
        {
            RecoverInputBoundary("mouse_move", ex);
        }
    }

    private void HandleMouseMoveCore(
        MeshPointerInput input,
        MouseEventArgs platformEvent)
    {
        var paneId = _capturedInputPane.Length > 0 ? _capturedInputPane : PaneAt(input.Location);
        if (paneId.Length == 0
            || (_capturedInputPane.Length == 0
                && !string.Equals(paneId, _activeCameraContextId, StringComparison.OrdinalIgnoreCase)))
        {
            return;
        }
        input = input.At(PaneLocalPoint(input.Location, paneId));
        _pointerInside = true;
        _pointerLocation = input.Location;
        var dx = input.Location.X - _lastMouse.X;
        var dy = input.Location.Y - _lastMouse.Y;
        _lastMouse = input.Location;
        if (!input.IsHeld(MeshPointerButtons.Left))
        {
            // The left button is no longer held, so any left-button gesture that
            // was waiting for a mouse-up is over whether or not that mouse-up
            // ever arrived. Closing it here keeps a lost capture from leaving a
            // stroke open across later gestures.
            FinishSelectionGesture(input.Location, cancelled: false);
            EndEditorStroke(input.Location, cancelled: false);
            if (_placementDragActive)
            {
                // Same reasoning as the stroke above, and the host now treats an
                // active placement drag as owning the provisional placement, so
                // a drag left open by a lost mouse-up would stall every later
                // authoritative frame.
                EndPlacementGizmoDrag();
            }
        }
        if (input.HeldButtons == MeshPointerButtons.None)
        {
            // No camera-capable button is held at all, so orbit and pan are over
            // too. This is deliberately looser than the left-button check above:
            // a middle-drag or right-drag drives the camera with the left button
            // up, and closing the camera gesture on the first move — as the
            // left-only check used to — is what made holding the scroll wheel
            // to pan do nothing.
            _rotating = false;
            _panning = false;
            _capturedInputPane = string.Empty;
            SetRenderSurfaceCapture(false);
        }
        if (_placementDragActive && input.IsHeld(MeshPointerButtons.Left))
        {
            UpdatePlacementGizmoDrag(input.Location);
            base.OnMouseMove(platformEvent);
            return;
        }
        if (!_rotating
            && !_panning
            && !string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase))
        {
            UpdateGizmoHover(input.Location);
        }
        if (_edgeDragActive)
        {
            _edgeDragCurrent = input.Location;
            if (_selectionLassoPoints.Count > 0)
            {
                var lastPoint = _selectionLassoPoints[^1];
                if (Math.Abs(input.Location.X - lastPoint.X) + Math.Abs(input.Location.Y - lastPoint.Y) >= 3)
                {
                    _selectionLassoPoints.Add(input.Location);
                }
            }
            if (_selectionPaintActive && input.IsHeld(MeshPointerButtons.Left))
            {
                MaybeEmitSelectionPaintSample(input.Location);
            }
        }
        if (!_edgeDragActive
            && !_editorStrokeActive
            && !_rotating
            && !_panning
            && string.Equals(ActiveTool, "select", StringComparison.OrdinalIgnoreCase)
            && string.Equals(CurrentTargetMode(), "edge", StringComparison.OrdinalIgnoreCase))
        {
            UpdateHoverEdge(input.Location);
        }
        if (_editorStrokeActive)
        {
            if (input.IsHeld(MeshPointerButtons.Left))
            {
                var checkpointEmitted = MaybeEmitEditorStrokeUpdate(input.Location);
                if (!IsCheckpointedSculptTool(_strokeTool) || checkpointEmitted)
                {
                    UpdateProvisionalEditorStroke(input.Location);
                }
                _strokePrevious = input.Location;
            }
        }
        else if (_rotating)
        {
            var radiansPerPixel = _residentPresentationSettings.OrbitSensitivity * MathF.PI / 180.0f;
            // The side of the subject facing the reader follows the pointer on both axes,
            // the way pan already does and the way Blender and Maya orbit: drag right and
            // the near side turns right, drag down and it tips down. In the camera's own
            // terms that is a yaw that runs against the pointer (see NetViewportCamera:
            // a larger yaw swings the near side to screen left) and a pitch that runs
            // with it. The invert settings reverse whichever axis a reader wants.
            var orbitX = _residentPresentationSettings.InvertOrbitX ? dx : -dx;
            var orbitY = _residentPresentationSettings.InvertOrbitY ? -dy : dy;
            _yaw += orbitX * radiansPerPixel;
            _pitch = Math.Clamp(_pitch + orbitY * radiansPerPixel, -1.45f, 1.45f);
            InvalidatePaintProjectionCache("camera_orbit");
            NotifyViewStateChanged();
        }
        else if (_panning)
        {
            var panX = _residentPresentationSettings.InvertPanX ? -dx : dx;
            var panY = _residentPresentationSettings.InvertPanY ? -dy : dy;
            _panX += panX * _residentPresentationSettings.PanSensitivity;
            _panY += panY * _residentPresentationSettings.PanSensitivity;
            InvalidatePaintProjectionCache("camera_pan");
            NotifyViewStateChanged();
        }
        UpdateGpuViewport();
        base.OnMouseMove(platformEvent);
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
        try
        {
            HandleMouseWheelCore(
                _inputAdapter.NormalizeWheel(e, ModifierKeys, Capture, Focused),
                e);
        }
        catch (Exception ex)
        {
            RecoverInputBoundary("mouse_wheel", ex);
        }
    }

    private void HandleMouseWheelCore(
        MeshPointerInput input,
        MouseEventArgs platformEvent)
    {
        var paneId = PaneAt(input.Location);
        if (paneId.Length == 0)
        {
            return;
        }
        if (!ApplyWheelZoomToPane(paneId, input.WheelDelta))
        {
            return;
        }
        NotifyViewStateChanged();
        InvalidatePaintProjectionCache("camera_zoom");
        UpdateGpuViewport();
        QueuePaintProjectionPrewarm();
        base.OnMouseWheel(platformEvent);
    }

    internal string CameraOrbitModifier => CameraModifierBindings.Normalize(
        _residentPresentationSettings.CameraOrbitModifier,
        CameraModifierBindings.DefaultOrbit);

    internal string CameraPanModifier => CameraModifierBindings.Normalize(
        _residentPresentationSettings.CameraPanModifier,
        CameraModifierBindings.DefaultPan);

    internal string CameraMiddleDrag => CameraModifierBindings.NormalizeDrag(
        _residentPresentationSettings.CameraMiddleDrag,
        CameraModifierBindings.DefaultMiddleDrag);

    internal string CameraRightDrag => CameraModifierBindings.NormalizeDrag(
        _residentPresentationSettings.CameraRightDrag,
        CameraModifierBindings.DefaultRightDrag);

    private bool IsPanGesture(MeshPointerInput input)
    {
        if (input.Changed(MeshPointerButtons.Middle))
        {
            return string.Equals(CameraMiddleDrag, CameraModifierBindings.DragPan, StringComparison.Ordinal);
        }
        if (input.Changed(MeshPointerButtons.Right))
        {
            return string.Equals(CameraRightDrag, CameraModifierBindings.DragPan, StringComparison.Ordinal);
        }
        return input.Changed(MeshPointerButtons.Left)
            && CameraModifierBindings.IsHeld(
                CameraPanModifier,
                input.Alt,
                input.Control,
                input.Shift);
    }

    /// <summary>
    /// The camera takes the left button away from the active edit tool while the
    /// bound modifier is held, and the middle or right button belongs to the
    /// camera outright. <see cref="IsPanGesture"/> is tested before this, so a
    /// modifier bound to both pans.
    /// </summary>
    private bool IsOrbitOverrideGesture(MeshPointerInput input)
    {
        if (input.Changed(MeshPointerButtons.Middle))
        {
            return string.Equals(CameraMiddleDrag, CameraModifierBindings.DragOrbit, StringComparison.Ordinal);
        }
        if (input.Changed(MeshPointerButtons.Right))
        {
            return string.Equals(CameraRightDrag, CameraModifierBindings.DragOrbit, StringComparison.Ordinal);
        }
        return input.Changed(MeshPointerButtons.Left)
            && CameraModifierBindings.IsHeld(
                CameraOrbitModifier,
                input.Alt,
                input.Control,
                input.Shift);
    }

    private void BeginEditorStroke(Point location)
    {
        _strokeTool = ActiveTool;
        _strokePrevious = location;
        _strokeProtocolPrevious = location;
        _strokeLastProtocolTicks = 0;
        _strokeId++;
        var gestureId = _strokeId.ToString(CultureInfo.InvariantCulture);
        if (!BeginEditOperator(
                _strokeTool,
                _strokeTool,
                CurrentTargetMode(),
                gestureId))
        {
            _strokeTool = string.Empty;
            return;
        }
        if (!BeginProvisionalEditorStroke(location, _strokeTool, _strokeId))
        {
            _editOperators.Cancel(gestureId);
            _strokeTool = string.Empty;
            return;
        }
        _editorStrokeActive = true;
        EditorEventRequested?.Invoke("stroke_begin", StrokePointerPayload(location, location));
        _strokeLastProtocolTicks = Environment.TickCount64;
    }

    private bool MaybeEmitEditorStrokeUpdate(Point location, bool final = false)
    {
        if (!_editorStrokeActive)
        {
            return false;
        }
        var now = Environment.TickCount64;
        if (!final
            && now - _strokeLastProtocolTicks < (long)EditorStrokeProtocolIntervalMs)
        {
            return false;
        }
        EditorEventRequested?.Invoke("stroke_update", StrokePointerPayload(location, _strokeProtocolPrevious));
        _strokeProtocolPrevious = location;
        _strokeLastProtocolTicks = now;
        return true;
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
        var gestureId = _editOperators.Active?.GestureId
            ?? _strokeId.ToString(CultureInfo.InvariantCulture);
        var payload = StrokePointerPayload(location, _strokeProtocolPrevious);
        payload["apply_terminal_sample"] = location != _strokeProtocolPrevious;
        if (!cancelled
            && payload["apply_terminal_sample"] is true
            && IsCheckpointedSculptTool(_strokeTool))
        {
            UpdateProvisionalEditorStroke(location);
        }
        _strokePrevious = location;
        _strokeProtocolPrevious = location;
        MarkProvisionalEditorStrokeEnded(cancelled);
        if (cancelled)
        {
            _editOperators.Cancel(gestureId);
        }
        else
        {
            _editOperators.Confirm(gestureId);
        }
        _strokeTool = string.Empty;
        EditorEventRequested?.Invoke(cancelled ? "stroke_cancel" : "stroke_end", payload);
    }

    private static bool IsCheckpointedSculptTool(string tool) =>
        tool is "smooth" or "inflate" or "pinch";

    /// <summary>
    /// Aborts an open stroke without committing it. Used when the tool, the
    /// interaction mode, or the input focus changes underneath a live gesture.
    /// </summary>
    internal void CancelActiveStroke()
    {
        FinishSelectionGesture(_edgeDragCurrent, cancelled: true);
        EndEditorStroke(_strokePrevious, cancelled: true);
        _rotating = false;
        _panning = false;
        _capturedInputPane = string.Empty;
        SetRenderSurfaceCapture(false);
    }

    /// <summary>
    /// Closes every piece of a Select gesture through one idempotent path. A
    /// release commits exactly what the viewport drew; cancellation restores
    /// the committed overlay and retires provisional paint/lasso state. The
    /// resident projection cache survives so the next short gesture does not
    /// rebuild the mesh; its key invalidation owns stale-cache retirement.
    /// </summary>
    private void FinishSelectionGesture(Point location, bool cancelled)
    {
        InputBoundaryFaultInjector?.Invoke("finish_selection");
        var wasActive = _edgeDragActive || !string.IsNullOrWhiteSpace(_selectionStrokeId);
        var gestureId = _editOperators.Active?.GestureId ?? _selectionStrokeId;
        if (wasActive)
        {
            if (cancelled)
            {
                CancelSelectionStroke();
                ClearProvisionalSelectionEcho();
            }
            else if (_edgeDragActive)
            {
                FinishEdgeDrag(location);
            }
            else
            {
                CancelSelectionStroke();
                ClearProvisionalSelectionEcho();
            }
        }
        _edgeDragActive = false;
        _selectionPaintActive = false;
        _selectionPaintPainted = false;
        _selectionLassoPoints.Clear();
        _selectionPaintPathPoints.Clear();
        _selectionPaintToggleTouchedVertices.Clear();
        _selectionPaintToggleTouchedFaces.Clear();
        _selectionPaintToggleTouchedEdges.Clear();
        EndPaintProjectionGesture();
        if (wasActive && gestureId.Length > 0)
        {
            if (cancelled)
            {
                _editOperators.Cancel(gestureId);
            }
            else
            {
                _editOperators.Confirm(gestureId);
            }
        }
    }

    protected override void OnLostFocus(EventArgs e)
    {
        try
        {
            CancelActiveStroke();
        }
        catch (Exception ex)
        {
            RecoverInputBoundary("lost_focus", ex);
        }
        base.OnLostFocus(e);
    }

    private void RecoverInputBoundary(string boundary, Exception exception)
    {
        try
        {
            CancelActiveStroke();
        }
        catch (Exception)
        {
            // The forced state reset below does not call tool code again.
        }
        try
        {
            ClearProvisionalSelectionEcho();
            ClearProvisionalEditorStroke();
            EndPaintProjectionGesture();
        }
        catch (Exception)
        {
            // Renderer recovery will rehydrate the authoritative document if
            // even cleanup failed; input is still forced to a terminal state.
        }
        _editorStrokeActive = false;
        _strokeTool = string.Empty;
        _edgeDragActive = false;
        _selectionStrokeId = string.Empty;
        _selectionPaintActive = false;
        _selectionPaintPainted = false;
        _provisionalPartSelectionActive = false;
        _selectionLassoPoints.Clear();
        _selectionPaintPathPoints.Clear();
        _selectionPaintToggleTouchedVertices.Clear();
        _selectionPaintToggleTouchedFaces.Clear();
        _selectionPaintToggleTouchedEdges.Clear();
        _pendingPaintSample = null;
        ForceInputGestureTerminalState();
        _editOperators.Fail("viewport_input_failed", exception.Message);
        _editOperators.RecoverToIdle();
        var message = $"Mesh Editor input recovered after {boundary}: {exception.Message}";
        StatusRequested?.Invoke(message);
        try
        {
            EditorEventRequested?.Invoke("interaction_failed", new Dictionary<string, object?>
            {
                ["status"] = "failed",
                ["diagnostic_code"] = "viewport_input_failed",
                ["reason"] = "input_exception",
                ["boundary"] = boundary,
                ["tool"] = ActiveTool,
                ["exception_type"] = exception.GetType().FullName ?? exception.GetType().Name,
                ["message"] = exception.Message,
            });
        }
        catch (Exception)
        {
            // A diagnostic transport failure cannot reopen the gesture.
        }
    }

    private void ForceInputGestureTerminalState()
    {
        try
        {
            FinishSelectionGesture(_edgeDragCurrent, cancelled: true);
        }
        catch (Exception) { }
        try
        {
            EndEditorStroke(_strokePrevious, cancelled: true);
        }
        catch (Exception) { }
        _rotating = false;
        _panning = false;
        _capturedInputPane = string.Empty;
        _inputAdapter.Reset();
        SetRenderSurfaceCapture(false);
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
            if (_provisionalStroke is { } provisional)
            {
                payload["scope_source_indices"] = provisional.SourceIndices;
            }
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
            ["pane_bounds_diagnostics"] = PaneBoundsDiagnostics(),
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
            ["pane_bounds_diagnostics"] = PaneBoundsDiagnostics(),
        };
    }

    private int[] VisibleEditableSubmeshIndices()
    {
        return Enumerable.Range(0, Math.Min(_scene.EditableSubmeshCount, _document.Submeshes.Count))
            .Where(IsSubmeshVisibleForViewportSelection)
            .ToArray();
    }

    /// <summary>
    /// A per-submesh world-view-projection for every submesh the pick is
    /// allowed to touch, and no others.
    /// </summary>
    /// <remarks>
    /// Every stroke sample and every brush dab carries this array twice, once
    /// in <c>screen_drag</c> and once in <c>screen_brush</c>, at sixteen
    /// doubles per entry. Sending an entry for a hidden or non-editable submesh
    /// is pure protocol weight: the native reader filters by
    /// <c>source_submesh_indices</c> before it ever resolves a projection, so
    /// an override outside that list cannot be reached. On a character with
    /// most of its parts switched off this is the difference between a
    /// kilobyte a sample and tens of them, on the path that has to keep up with
    /// the pointer.
    /// </remarks>
    private Dictionary<string, object?>[] SourceProjectionOverrides(NetViewportCamera camera)
    {
        return VisibleEditableSubmeshIndices()
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

    /// <summary>
    /// Adopts the host's Select drag mode. Only the three drag modes are
    /// accepted; anything else -- the standalone host publishes its element
    /// mode in the same field -- leaves the current mode standing rather than
    /// silently resetting a choice.
    /// </summary>
    internal void SetSelectionDragMode(string? mode)
    {
        var normalized = (mode ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized is "brush" or "lasso" or "rectangle")
        {
            _selectionDragMode = normalized;
        }
    }

    private void BeginSelectionDrag(Point point, string mode)
    {
        var meshEdit = string.Equals(
            _scene.InteractionMode,
            "mesh_edit",
            StringComparison.OrdinalIgnoreCase);
        var gestureId = Guid.NewGuid().ToString("N");
        if (meshEdit
            && !BeginEditOperator(
                _selectionDragMode switch
                {
                    "brush" => "brush_select",
                    "lasso" => "lasso_select",
                    "rectangle" => "rectangle_select",
                    _ => "click_select",
                },
                "select",
                (mode ?? "edge").Trim().ToLowerInvariant(),
                gestureId))
        {
            return;
        }
        _edgeDragActive = true;
        _selectionDragTargetMode = (mode ?? "edge").Trim().ToLowerInvariant();
        _edgeDragStart = point;
        _edgeDragCurrent = point;
        _hoverEdgeId = _selectionDragTargetMode == "edge" ? PickEdgeAt(point) : -1;
        _selectionPaintActive = false;
        _selectionPaintPainted = false;
        _selectionPaintToggleTouchedVertices.Clear();
        _selectionPaintToggleTouchedFaces.Clear();
        _selectionPaintToggleTouchedEdges.Clear();
        _selectionPaintPathPoints.Clear();
        _selectionPaintPathPoints.Add(point);
        _selectionLassoPoints.Clear();
        ReplaceSelectionMap(_provisionalSelectedVertices, _selectedVertices);
        ReplaceSelectionMap(_provisionalSelectedFaces, _selectedFaces);
        _provisionalSelectedEdges.Clear();
        _provisionalSelectedEdges.UnionWith(_selectedEdges);
        _provisionalSelectedSources.Clear();
        _provisionalSelectedSources.UnionWith(_selectedSources);
        _provisionalPartSelectionActive = string.Equals(
            _scene.InteractionMode,
            "mesh_edit",
            StringComparison.OrdinalIgnoreCase)
            && _selectionDragTargetMode is "source" or "part";
        // Brush and lasso are Edit Mesh interactions; placement part-pick
        // drags keep their rectangle semantics whatever the combo says.
        if (meshEdit)
        {
            BeginPaintProjectionGesture();
            BeginSelectionStroke(gestureId);
            if (_selectionDragMode == "brush")
            {
                var operation = CurrentSelectionOperation();
                _selectionPaintFirstOperation = operation;
                _selectionPaintOperation = operation switch
                {
                    "subtract" => "subtract",
                    "toggle" => "toggle",
                    _ => "add",
                };
                _selectionPaintActive = true;
                _selectionPaintLastSample = point;
                _selectionPaintLastEcho = point;
                _selectionPaintLastSampleTicks = 0;
            }
            else if (_selectionDragMode == "lasso")
            {
                _selectionLassoPoints.Add(point);
            }
        }
        UpdateGpuViewport();
    }
}
