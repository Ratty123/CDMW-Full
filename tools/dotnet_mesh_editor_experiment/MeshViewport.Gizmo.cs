using System.Drawing;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private sealed record GizmoDragState(
        string Handle,
        Point StartPoint,
        Vector3 Pivot,
        Vector3 StartTranslation,
        Vector3 StartRotation,
        Vector3 StartScale,
        float StartAxisParameter,
        Vector3 StartPlanePoint);

    private GizmoDragState? _gizmoDragState;

    private static readonly Vector3[] GizmoAxes =
    {
        Vector3.UnitX,
        Vector3.UnitY,
        Vector3.UnitZ,
    };

    private float GizmoLength() => _gizmoAppearance.ScaleLength(
        Math.Max(_scene.SceneExtent * 0.18f, _scene.GridSpacing * 2.0f));

    private double GizmoLineHitTolerancePixels() =>
        Math.Max(9.0, _gizmoAppearance.LineThicknessPixels + 4.0);

    private static PointF GizmoProjectedPoint(Vector3 value, NetViewportCamera camera)
    {
        return camera.Project(new Vec3(value.X, value.Y, value.Z));
    }

    private bool TryBeginPlacementGizmoDrag(Point point)
    {
        if (!_scene.GizmoVisible || _scene.EditableSubmeshCount <= 0)
        {
            return false;
        }
        var handle = HitTestGizmo(point);
        if (string.IsNullOrEmpty(handle))
        {
            return false;
        }
        _scene.BeginProvisionalPlacement();
        var pivot = ActiveGizmoPivot();
        var axis = GizmoAxis(handle);
        var startAxis = TryScreenRay(point, out var rayOrigin, out var rayDirection)
            ? ClosestAxisParameter(rayOrigin, rayDirection, pivot, axis)
            : 0.0f;
        var planeNormal = GizmoPlaneNormal(handle, axis);
        var startPlanePoint = TryScreenRay(point, out rayOrigin, out rayDirection)
            && TryRayPlane(rayOrigin, rayDirection, pivot, planeNormal, out var hit)
                ? hit
                : pivot;
        _gizmoDragState = new GizmoDragState(
            handle,
            point,
            pivot,
            _scene.Translation,
            _scene.RotationDegrees,
            _scene.Scale,
            startAxis,
            startPlanePoint);
        _scene.SetActiveGizmoHandle(handle);
        _scene.SetHoveredGizmoHandle(handle);
        _placementDragActive = true;
        ApplySceneState();
        return true;
    }

    private bool UpdatePlacementGizmoDrag(Point point)
    {
        var state = _gizmoDragState;
        if (!_placementDragActive || state is null)
        {
            return false;
        }
        var handle = state.Handle;
        var axis = GizmoAxis(handle);
        if (_scene.GizmoTool == "rotate")
        {
            ApplyRotationRingDrag(state, point, axis);
        }
        else if (_scene.GizmoTool == "scale")
        {
            ApplyScaleHandleDrag(state, point, axis);
        }
        else
        {
            ApplyMoveHandleDrag(state, point, axis);
        }
        EmitPlacementTransformRequest("update", handle);
        ApplySceneState();
        return true;
    }

    private void EndPlacementGizmoDrag()
    {
        var handle = _gizmoDragState?.Handle ?? _scene.ActiveGizmoHandle;
        EmitPlacementTransformRequest("end", handle);
        _placementDragActive = false;
        _gizmoDragState = null;
        _scene.SetActiveGizmoHandle(string.Empty);
        ApplySceneState();
    }

    private void EmitPlacementTransformRequest(string phase, string handle)
    {
        EditorEventRequested?.Invoke("placement_transform_request", new Dictionary<string, object?>
        {
            ["placement"] = _scene.PlacementPayload(),
            ["placement_phase"] = phase,
            ["gizmo_tool"] = _scene.GizmoTool,
            ["gizmo_handle"] = handle,
        });
    }

    private void UpdateGizmoHover(Point point)
    {
        if (_placementDragActive || !_scene.GizmoVisible)
        {
            return;
        }
        var handle = HitTestGizmo(point);
        if (string.Equals(handle, _scene.HoveredGizmoHandle, StringComparison.Ordinal))
        {
            return;
        }
        _scene.SetHoveredGizmoHandle(handle);
        ApplySceneState();
    }

    private string HitTestGizmo(Point point)
    {
        var camera = CurrentCamera();
        var pivot = ActiveGizmoPivot();
        var length = GizmoLength();
        var center = GizmoProjectedPoint(pivot, camera);
        if (_scene.GizmoTool == "rotate")
        {
            var bestHandle = string.Empty;
            var bestDistance = GizmoLineHitTolerancePixels();
            for (var axisIndex = 0; axisIndex < 3; axisIndex++)
            {
                var marker = GizmoProjectedPoint(GizmoRotationHandlePoint(pivot, length, axisIndex), camera);
                if (GizmoMarkerContains(point, marker))
                {
                    return AxisHandle(axisIndex);
                }
                PointF? previous = null;
                for (var segment = 0; segment <= 64; segment++)
                {
                    var angle = segment * MathF.Tau / 64.0f;
                    var world = GizmoCirclePoint(pivot, length, axisIndex, angle);
                    var projected = GizmoProjectedPoint(world, camera);
                    if (previous is PointF before)
                    {
                        var distance = DistanceToSegment(point, before, projected);
                        if (distance < bestDistance)
                        {
                            bestDistance = distance;
                            bestHandle = AxisHandle(axisIndex);
                        }
                    }
                    previous = projected;
                }
            }
            return bestHandle;
        }

        if (_scene.GizmoTool == "move")
        {
            foreach (var plane in new[] { "xy", "xz", "yz" })
            {
                var axes = PlaneAxes(plane);
                var a = GizmoProjectedPoint(pivot + (GizmoAxes[axes.A] * length * 0.22f), camera);
                var b = GizmoProjectedPoint(pivot + (GizmoAxes[axes.A] * length * 0.42f), camera);
                var c = GizmoProjectedPoint(pivot + (GizmoAxes[axes.B] * length * 0.42f), camera);
                var d = GizmoProjectedPoint(pivot + (GizmoAxes[axes.B] * length * 0.22f), camera);
                if (PointInTriangle(point, a, b, c) || PointInTriangle(point, a, c, d))
                {
                    return plane;
                }
            }
        }

        var bestAxis = string.Empty;
        var bestAxisDistance = GizmoLineHitTolerancePixels();
        for (var axisIndex = 0; axisIndex < 3; axisIndex++)
        {
            var endpoint = GizmoProjectedPoint(pivot + (GizmoAxes[axisIndex] * length), camera);
            if (GizmoMarkerContains(point, endpoint))
            {
                return AxisHandle(axisIndex);
            }
            var distance = DistanceToSegment(point, center, endpoint);
            if (distance < bestAxisDistance)
            {
                bestAxisDistance = distance;
                bestAxis = AxisHandle(axisIndex);
            }
        }
        if (_scene.GizmoTool == "scale")
        {
            var centerDistance = Math.Sqrt(Math.Pow(point.X - center.X, 2.0) + Math.Pow(point.Y - center.Y, 2.0));
            if (centerDistance <= Math.Max(8.0, (_gizmoAppearance.HandleSizePixels * 0.5f) + 4.0f))
            {
                return "center";
            }
        }
        return bestAxis;
    }

    private void ApplyMoveHandleDrag(GizmoDragState state, Point point, Vector3 axis)
    {
        if (!TryScreenRay(point, out var rayOrigin, out var rayDirection))
        {
            return;
        }
        if (state.Handle.Length == 2)
        {
            var normal = GizmoPlaneNormal(state.Handle, axis);
            if (TryRayPlane(rayOrigin, rayDirection, state.Pivot, normal, out var hit))
            {
                var delta = hit - state.StartPlanePoint;
                _scene.ApplyConstrainedTranslation(state.StartTranslation, ConstrainToPlane(delta, normal));
            }
            return;
        }
        var current = ClosestAxisParameter(rayOrigin, rayDirection, state.Pivot, axis);
        _scene.ApplyConstrainedTranslation(state.StartTranslation, axis * (current - state.StartAxisParameter));
    }

    private void ApplyRotationRingDrag(GizmoDragState state, Point point, Vector3 axis)
    {
        if (!TryScreenRay(point, out var rayOrigin, out var rayDirection)
            || !TryRayPlane(rayOrigin, rayDirection, state.Pivot, axis, out var hit))
        {
            return;
        }
        var start = Vector3.Normalize(state.StartPlanePoint - state.Pivot);
        var current = Vector3.Normalize(hit - state.Pivot);
        if (!IsFinite(start) || !IsFinite(current))
        {
            return;
        }
        var radians = MathF.Atan2(Vector3.Dot(axis, Vector3.Cross(start, current)), Vector3.Dot(start, current));
        _scene.ApplyConstrainedRotation(state.StartRotation, AxisIndex(state.Handle), radians * 180.0f / MathF.PI);
    }

    private void ApplyScaleHandleDrag(GizmoDragState state, Point point, Vector3 axis)
    {
        if (state.Handle == "center")
        {
            var uniformFactor = MathF.Exp((state.StartPoint.Y - point.Y) * 0.01f);
            _scene.ApplyConstrainedScale(state.StartScale, -1, uniformFactor);
            return;
        }
        if (!TryScreenRay(point, out var rayOrigin, out var rayDirection))
        {
            return;
        }
        var current = ClosestAxisParameter(rayOrigin, rayDirection, state.Pivot, axis);
        var factor = 1.0f + ((current - state.StartAxisParameter) / Math.Max(GizmoLength(), 0.0001f));
        _scene.ApplyConstrainedScale(state.StartScale, AxisIndex(state.Handle), factor);
    }

    private bool TryScreenRay(Point point, out Vector3 origin, out Vector3 direction)
    {
        origin = Vector3.Zero;
        direction = Vector3.UnitZ;
        var camera = CurrentCamera();
        if (!Matrix4x4.Invert(camera.WorldViewProjection, out var inverse))
        {
            return false;
        }
        var x = (2.0f * point.X / Math.Max(1.0f, camera.ViewportWidth)) - 1.0f;
        var y = 1.0f - (2.0f * point.Y / Math.Max(1.0f, camera.ViewportHeight));
        var near = Vector4.Transform(new Vector4(x, y, 0.0f, 1.0f), inverse);
        var far = Vector4.Transform(new Vector4(x, y, 1.0f, 1.0f), inverse);
        if (Math.Abs(near.W) <= 1.0e-6f || Math.Abs(far.W) <= 1.0e-6f)
        {
            return false;
        }
        origin = new Vector3(near.X, near.Y, near.Z) / near.W;
        var end = new Vector3(far.X, far.Y, far.Z) / far.W;
        direction = Vector3.Normalize(end - origin);
        return IsFinite(origin) && IsFinite(direction);
    }

    private static bool TryRayPlane(
        Vector3 rayOrigin,
        Vector3 rayDirection,
        Vector3 planePoint,
        Vector3 planeNormal,
        out Vector3 hit)
    {
        hit = planePoint;
        var denominator = Vector3.Dot(rayDirection, planeNormal);
        if (Math.Abs(denominator) <= 1.0e-6f)
        {
            return false;
        }
        var distance = Vector3.Dot(planePoint - rayOrigin, planeNormal) / denominator;
        hit = rayOrigin + (rayDirection * distance);
        return float.IsFinite(distance) && IsFinite(hit);
    }

    private static float ClosestAxisParameter(
        Vector3 rayOrigin,
        Vector3 rayDirection,
        Vector3 axisOrigin,
        Vector3 axis)
    {
        var offset = rayOrigin - axisOrigin;
        var b = Vector3.Dot(rayDirection, axis);
        var d = Vector3.Dot(rayDirection, offset);
        var e = Vector3.Dot(axis, offset);
        var denominator = 1.0f - (b * b);
        return Math.Abs(denominator) <= 1.0e-6f ? e : (e - (b * d)) / denominator;
    }

    private static Vector3 GizmoAxis(string handle) => GizmoAxes[Math.Clamp(AxisIndex(handle), 0, 2)];
    private static int AxisIndex(string handle) => handle.StartsWith("x", StringComparison.Ordinal) ? 0 : handle.StartsWith("y", StringComparison.Ordinal) ? 1 : 2;
    private static string AxisHandle(int axis) => axis == 0 ? "x" : axis == 1 ? "y" : "z";
    private static (int A, int B) PlaneAxes(string handle) => handle switch { "xy" => (0, 1), "xz" => (0, 2), _ => (1, 2) };
    private static Vector3 GizmoPlaneNormal(string handle, Vector3 fallback) => handle switch
    {
        "xy" => Vector3.UnitZ,
        "xz" => Vector3.UnitY,
        "yz" => Vector3.UnitX,
        _ => fallback,
    };
    private static Vector3 ConstrainToPlane(Vector3 value, Vector3 normal) => value - (normal * Vector3.Dot(value, normal));
    private static bool IsFinite(Vector3 value) => float.IsFinite(value.X) && float.IsFinite(value.Y) && float.IsFinite(value.Z);
    private static Vector3 GizmoCirclePoint(Vector3 origin, float radius, int axis, float angle) => axis switch
    {
        0 => origin + new Vector3(0, MathF.Cos(angle) * radius, MathF.Sin(angle) * radius),
        1 => origin + new Vector3(MathF.Cos(angle) * radius, 0, MathF.Sin(angle) * radius),
        _ => origin + new Vector3(MathF.Cos(angle) * radius, MathF.Sin(angle) * radius, 0),
    };

    private static Vector3 GizmoRotationHandlePoint(Vector3 origin, float radius, int axis)
    {
        var angle = axis == 1 ? MathF.PI * 0.5f : 0.0f;
        return GizmoCirclePoint(origin, radius, axis, angle);
    }

    private bool GizmoMarkerContains(Point point, PointF marker)
    {
        var handleHalfSize = _gizmoAppearance.HandleSizePixels * 0.5f;
        var labelWidth = _gizmoAppearance.LabelSizePixels * (7.0f / 12.0f);
        var left = -(handleHalfSize + 3.0f);
        var right = handleHalfSize + 4.0f + labelWidth + 8.0f;
        var vertical = Math.Max(handleHalfSize + 3.0f, (_gizmoAppearance.LabelSizePixels * 0.5f) + 7.0f);
        return point.X >= marker.X + left
            && point.X <= marker.X + right
            && point.Y >= marker.Y - vertical
            && point.Y <= marker.Y + vertical;
    }
}
