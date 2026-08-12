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
    private const double EditorStrokeProtocolIntervalMs = 16.0;

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
            FinishSelectionGesture(e.Location, cancelled: false);
            EndEditorStroke(e.Location, cancelled: false);
            base.OnMouseUp(e);
        }
        finally
        {
            FinishSelectionGesture(_edgeDragCurrent, cancelled: true);
            _rotating = false;
            _panning = false;
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
            // The left button is no longer held, so any left-button gesture that
            // was waiting for a mouse-up is over whether or not that mouse-up
            // ever arrived. Closing it here keeps a lost capture from leaving a
            // stroke open across later gestures.
            FinishSelectionGesture(e.Location, cancelled: false);
            EndEditorStroke(e.Location, cancelled: false);
            if (_placementDragActive)
            {
                // Same reasoning as the stroke above, and the host now treats an
                // active placement drag as owning the provisional placement, so
                // a drag left open by a lost mouse-up would stall every later
                // authoritative frame.
                EndPlacementGizmoDrag();
            }
        }
        if ((e.Button & (MouseButtons.Left | MouseButtons.Middle | MouseButtons.Right)) == MouseButtons.None)
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
            if (_selectionLassoPoints.Count > 0)
            {
                var lastPoint = _selectionLassoPoints[^1];
                if (Math.Abs(e.X - lastPoint.X) + Math.Abs(e.Y - lastPoint.Y) >= 3)
                {
                    _selectionLassoPoints.Add(e.Location);
                }
            }
            if (_selectionPaintActive && (e.Button & MouseButtons.Left) == MouseButtons.Left)
            {
                MaybeEmitSelectionPaintSample(e.Location);
            }
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
                UpdateProvisionalEditorStroke(e.Location);
                MaybeEmitEditorStrokeUpdate(e.Location);
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

    private bool IsPanGesture(MouseEventArgs e)
    {
        if (e.Button == MouseButtons.Middle)
        {
            return string.Equals(CameraMiddleDrag, CameraModifierBindings.DragPan, StringComparison.Ordinal);
        }
        if (e.Button == MouseButtons.Right)
        {
            return string.Equals(CameraRightDrag, CameraModifierBindings.DragPan, StringComparison.Ordinal);
        }
        return e.Button == MouseButtons.Left
            && CameraModifierBindings.IsHeld(CameraPanModifier, ModifierKeys);
    }

    /// <summary>
    /// The camera takes the left button away from the active edit tool while the
    /// bound modifier is held, and the middle or right button belongs to the
    /// camera outright. <see cref="IsPanGesture"/> is tested before this, so a
    /// modifier bound to both pans.
    /// </summary>
    private bool IsOrbitOverrideGesture(MouseEventArgs e)
    {
        if (e.Button == MouseButtons.Middle)
        {
            return string.Equals(CameraMiddleDrag, CameraModifierBindings.DragOrbit, StringComparison.Ordinal);
        }
        if (e.Button == MouseButtons.Right)
        {
            return string.Equals(CameraRightDrag, CameraModifierBindings.DragOrbit, StringComparison.Ordinal);
        }
        return e.Button == MouseButtons.Left
            && CameraModifierBindings.IsHeld(CameraOrbitModifier, ModifierKeys);
    }

    private void BeginEditorStroke(Point location)
    {
        _strokeTool = ActiveTool;
        _strokePrevious = location;
        _strokeProtocolPrevious = location;
        _strokeLastProtocolTicks = 0;
        _strokeId++;
        if (!BeginProvisionalEditorStroke(location, _strokeTool, _strokeId))
        {
            _strokeTool = string.Empty;
            return;
        }
        _editorStrokeActive = true;
        EditorEventRequested?.Invoke("stroke_begin", StrokePointerPayload(location, location));
        _strokeLastProtocolTicks = Environment.TickCount64;
    }

    private void MaybeEmitEditorStrokeUpdate(Point location, bool final = false)
    {
        if (!_editorStrokeActive)
        {
            return;
        }
        var now = Environment.TickCount64;
        if (!final
            && now - _strokeLastProtocolTicks < (long)EditorStrokeProtocolIntervalMs)
        {
            return;
        }
        EditorEventRequested?.Invoke("stroke_update", StrokePointerPayload(location, _strokeProtocolPrevious));
        _strokeProtocolPrevious = location;
        _strokeLastProtocolTicks = now;
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
        var payload = StrokePointerPayload(location, _strokeProtocolPrevious);
        _strokePrevious = location;
        _strokeProtocolPrevious = location;
        MarkProvisionalEditorStrokeEnded(cancelled);
        _strokeTool = string.Empty;
        EditorEventRequested?.Invoke(cancelled ? "stroke_cancel" : "stroke_end", payload);
    }

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
    /// the committed overlay and retires all paint/lasso/cache state so the
    /// next gesture cannot inherit a stale stroke id.
    /// </summary>
    private void FinishSelectionGesture(Point location, bool cancelled)
    {
        var wasActive = _edgeDragActive || !string.IsNullOrWhiteSpace(_selectionStrokeId);
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
        ReleasePaintProjectionCache();
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
        if (string.Equals(_scene.InteractionMode, "mesh_edit", StringComparison.OrdinalIgnoreCase))
        {
            BeginSelectionStroke();
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
