using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private bool BeginResidentNativeStroke(Point point, string tool, string operatorGestureId)
    {
        if (!TryMapResidentNativeTool(tool, out var nativeTool))
        {
            return false;
        }
        EnsureResidentNativePresentationState();
        SynchronizeResidentNativeSelection(expandSelectedParts: true);
        var gesture = NewResidentNativeGesture(
            nativeTool,
            point,
            operatorGestureId,
            NativeMeshSelectionTarget.Vertex,
            NativeMeshSelectionShape.Brush,
            NativeMeshSelectionOperation.Replace);
        PrepareResidentNativeGeometryPreview();
        var result = RequireResidentNativeSession().Begin(
            ResidentNativeGestureRequest(gesture, point, point));
        if (!result.IsSuccess)
        {
            ClearResidentNativePreview();
            StatusRequested?.Invoke($"Mesh Editor {tool} could not start: {result.Message}");
            return false;
        }
        _residentNativeGesture = gesture;
        ApplyResidentNativeResult(result);
        return true;
    }

    private bool BeginResidentNativeSelection(
        Point point,
        string targetMode,
        string operatorGestureId)
    {
        EnsureResidentNativePresentationState();
        SynchronizeResidentNativeSelection(expandSelectedParts: false);
        var gesture = NewResidentNativeGesture(
            NativeMeshInteractionTool.Select,
            point,
            operatorGestureId,
            ResidentNativeSelectionTarget(targetMode),
            ResidentNativeSelectionShape(_selectionDragMode),
            ResidentNativeSelectionOperation(CurrentSelectionOperation()));
        PrepareResidentNativeSelectionPreview();
        var result = RequireResidentNativeSession().Begin(
            ResidentNativeGestureRequest(gesture, point, point));
        if (!result.IsSuccess)
        {
            ClearProvisionalSelectionEcho();
            StatusRequested?.Invoke($"Mesh Editor Select could not start: {result.Message}");
            return false;
        }
        _residentNativeGesture = gesture;
        ApplyResidentNativeResult(result);
        return true;
    }

    private ResidentNativeGesture NewResidentNativeGesture(
        NativeMeshInteractionTool tool,
        Point point,
        string operatorGestureId,
        NativeMeshSelectionTarget target,
        NativeMeshSelectionShape shape,
        NativeMeshSelectionOperation operation) => new()
    {
        GestureId = ++_residentNativeGestureSequence,
        OperatorGestureId = operatorGestureId,
        Tool = tool,
        Start = point,
        Previous = point,
        SelectionTarget = target,
        SelectionShape = shape,
        SelectionOperation = operation,
    };

    private void UpdateResidentNativeInteraction(Point point)
    {
        var gesture = _residentNativeGesture;
        if (gesture is null)
        {
            return;
        }
        if (gesture.Tool == NativeMeshInteractionTool.Select
            && gesture.SelectionShape == NativeMeshSelectionShape.Lasso
            && _selectionLassoPoints.Count < 3)
        {
            return;
        }
        var provisionalFeedbackStarted = ResidentNativeTimingTimestamp();
        EnsureResidentNativePresentationState();
        var result = TimeResidentNativeUpdate(gesture, point);
        RequireResidentNativeSuccess(result, "gesture update");
        gesture.Previous = point;
        ApplyTimedResidentNativeResult(result, provisionalFeedbackStarted);
    }

    private void EndResidentNativeInteraction(Point point, bool cancelled)
    {
        var gesture = _residentNativeGesture;
        if (gesture is null)
        {
            return;
        }
        if (cancelled)
        {
            CancelResidentNativeGesture(gesture, "input_cancelled");
            return;
        }
        if (gesture.SelectionShape == NativeMeshSelectionShape.Lasso
            && (_selectionLassoPoints.Count == 0 || _selectionLassoPoints[^1] != point))
        {
            _selectionLassoPoints.Add(point);
        }
        if (point != gesture.Previous)
        {
            UpdateResidentNativeInteraction(point);
        }
        var result = RequireResidentNativeSession().End(
            ResidentNativeGestureRequest(gesture, point, point));
        RequireResidentNativeSuccess(result, "gesture end");
        _residentNativeGesture = null;
        var lease = CreateResidentNativeTransaction(gesture, result);
        if (lease is null)
        {
            RejectResidentNativeGestureWithoutHost(gesture, "no_change");
            return;
        }
        _residentNativeTransactions[gesture.GestureId] = lease;
        _residentNativeAwaitingAuthority = true;
        if (!_editOperators.Confirm(gesture.OperatorGestureId))
        {
            RejectResidentNativeGestureWithoutHost(gesture, "operator_confirmation_failed");
            return;
        }
        try
        {
            EditorEventRequested?.Invoke(
                "resident_interaction_transaction",
                lease.Descriptor(_residentNativeSessionId));
            if (lease.RequestId <= 0)
            {
                throw new InvalidOperationException("The host did not register the resident transaction request.");
            }
        }
        catch
        {
            RejectResidentNativeGestureWithoutHost(gesture, "transaction_publish_failed");
            throw;
        }
    }

    private void CancelResidentNativeGesture(ResidentNativeGesture gesture, string reason)
    {
        var result = RequireResidentNativeSession().Cancel(
            ResidentNativeGestureRequest(gesture, gesture.Previous, gesture.Previous));
        if (!result.IsSuccess)
        {
            _residentNativeFailure = $"Native gesture cancellation failed: {result.Status} {result.Message}";
        }
        _residentNativeGesture = null;
        ClearResidentNativePreview();
        _editOperators.Cancel(gesture.OperatorGestureId);
        StatusRequested?.Invoke(reason == "input_cancelled"
            ? "Mesh Editor gesture cancelled."
            : $"Mesh Editor gesture cancelled: {reason.Replace('_', ' ')}.");
    }

    private NativeMeshInteractionGestureRequest ResidentNativeGestureRequest(
        ResidentNativeGesture gesture,
        Point current,
        Point deltaStart)
    {
        var options = ToolOptionsProvider?.Invoke() ?? new Dictionary<string, object?>();
        var delta = ResidentNativeWorldDelta(deltaStart, current);
        return new NativeMeshInteractionGestureRequest
        {
            GestureId = gesture.GestureId,
            MeshRevision = _residentNativeMeshRevision,
            SelectionRevision = _residentNativeSelectionRevision,
            TopologyGeneration = _residentNativeTopologyGeneration,
            CameraRevision = _residentNativeCameraRevision,
            ViewportRevision = _residentNativeViewportRevision,
            Tool = gesture.Tool,
            SelectionTarget = gesture.SelectionTarget,
            SelectionShape = gesture.SelectionShape,
            SelectionOperation = gesture.SelectionOperation,
            XRay = ShowXRay,
            StartX = gesture.Start.X,
            StartY = gesture.Start.Y,
            CurrentX = current.X,
            CurrentY = current.Y,
            RadiusPixels = Math.Clamp(NumberOption(options, "radius", 24.0), 2.0, 256.0),
            Strength = Math.Clamp(NumberOption(options, "strength", 0.5), 0.0, 1.0),
            Pressure = 1.0,
            DeltaX = delta.X,
            DeltaY = delta.Y,
            DeltaZ = delta.Z,
            PointsXy = ResidentNativeSelectionPoints(gesture),
        };
    }

    private Vector3 ResidentNativeWorldDelta(Point start, Point end)
    {
        SetProvisionalViewportSize();
        return UnprojectScreenDelta(
            CurrentCamera().WorldViewProjection,
            new Vector3(_center.X, _center.Y, _center.Z),
            start,
            end);
    }

    private double[] ResidentNativeSelectionPoints(ResidentNativeGesture gesture)
    {
        if (gesture.SelectionShape != NativeMeshSelectionShape.Lasso)
        {
            return [];
        }
        var points = _selectionLassoPoints.Count >= 3
            ? _selectionLassoPoints
            : new StrokeSampleBuffer { gesture.Start, gesture.Start, gesture.Start };
        return points.SelectMany(point => new[] { (double)point.X, (double)point.Y }).ToArray();
    }

    private static bool TryMapResidentNativeTool(
        string tool,
        out NativeMeshInteractionTool value)
    {
        value = (tool ?? string.Empty).Trim().ToLowerInvariant() switch
        {
            "move" => NativeMeshInteractionTool.Move,
            "grab" => NativeMeshInteractionTool.Grab,
            "smooth" => NativeMeshInteractionTool.Smooth,
            "inflate" => NativeMeshInteractionTool.Inflate,
            "pinch" => NativeMeshInteractionTool.Pinch,
            _ => 0,
        };
        return value != 0;
    }

    private static NativeMeshSelectionTarget ResidentNativeSelectionTarget(string target) =>
        (target ?? string.Empty).Trim().ToLowerInvariant() switch
        {
            "edge" => NativeMeshSelectionTarget.Edge,
            "face" => NativeMeshSelectionTarget.Face,
            _ => NativeMeshSelectionTarget.Vertex,
        };

    private static NativeMeshSelectionShape ResidentNativeSelectionShape(string shape) =>
        (shape ?? string.Empty).Trim().ToLowerInvariant() switch
        {
            "rectangle" => NativeMeshSelectionShape.Rectangle,
            "lasso" => NativeMeshSelectionShape.Lasso,
            _ => NativeMeshSelectionShape.Brush,
        };

    private static NativeMeshSelectionOperation ResidentNativeSelectionOperation(string operation) =>
        (operation ?? string.Empty).Trim().ToLowerInvariant() switch
        {
            "add" => NativeMeshSelectionOperation.Add,
            "subtract" => NativeMeshSelectionOperation.Subtract,
            "toggle" => NativeMeshSelectionOperation.Toggle,
            _ => NativeMeshSelectionOperation.Replace,
        };
}
