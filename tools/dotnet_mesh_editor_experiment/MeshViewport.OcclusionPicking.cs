using System.Drawing;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private Vector3 SceneWorldPoint(int submeshIndex, Vec3 vertex) =>
        Vector3.Transform(
            new Vector3(vertex.X, vertex.Y, vertex.Z),
            ActiveSceneModelMatrix(submeshIndex));

    private bool IsWorldPointOccluded(Point screenPoint, Vector3 worldPoint)
    {
        if (ShowXRay
            || !TryScreenRay(screenPoint, out var rayOrigin, out var rayDirection)
            || !TryNearestVisibleSurface(
                rayOrigin,
                rayDirection,
                out var nearestDistance,
                out _,
                out _))
        {
            return false;
        }
        var candidateDistance = Vector3.Dot(worldPoint - rayOrigin, rayDirection);
        if (!float.IsFinite(candidateDistance) || candidateDistance <= 0.0f)
        {
            return true;
        }
        var depthTolerance = Math.Max(_scene.SceneExtent * 0.01f, 0.0005f);
        return nearestDistance + depthTolerance < candidateDistance;
    }

    private bool TryNearestVisibleSurface(
        Point screenPoint,
        out float distance,
        out int submeshIndex,
        out int faceIndex)
    {
        distance = float.PositiveInfinity;
        submeshIndex = -1;
        faceIndex = -1;
        return TryScreenRay(screenPoint, out var rayOrigin, out var rayDirection)
            && TryNearestVisibleSurface(
                rayOrigin,
                rayDirection,
                out distance,
                out submeshIndex,
                out faceIndex);
    }

    private bool TryNearestVisibleSurface(
        Vector3 rayOrigin,
        Vector3 rayDirection,
        out float distance,
        out int nearestSubmeshIndex,
        out int nearestFaceIndex)
    {
        distance = float.PositiveInfinity;
        nearestSubmeshIndex = -1;
        nearestFaceIndex = -1;
        var camera = CurrentCamera();
        for (var submeshIndex = 0; submeshIndex < _document.Submeshes.Count; submeshIndex++)
        {
            if (!ActivePaneIncludesForPicking(submeshIndex)
                || _materials.ParametersForSubmesh(submeshIndex).Visible is false)
            {
                continue;
            }
            var submesh = _document.Submeshes[submeshIndex];
            for (var faceIndex = 0; faceIndex < submesh.Faces.Count; faceIndex++)
            {
                var face = submesh.Faces[faceIndex];
                if (face.Corners.Length != 3
                    || !IsFaceFrontFacing(submeshIndex, faceIndex, camera))
                {
                    continue;
                }
                var indices = face.Corners.Select(corner => corner.VertexIndex).ToArray();
                if (indices.Any(index => index < 0 || index >= submesh.Vertices.Count))
                {
                    continue;
                }
                var a = SceneWorldPoint(submeshIndex, submesh.Vertices[indices[0]]);
                var b = SceneWorldPoint(submeshIndex, submesh.Vertices[indices[1]]);
                var c = SceneWorldPoint(submeshIndex, submesh.Vertices[indices[2]]);
                if (RayIntersectsTriangle(rayOrigin, rayDirection, a, b, c, out var hitDistance)
                    && hitDistance < distance)
                {
                    distance = hitDistance;
                    nearestSubmeshIndex = submeshIndex;
                    nearestFaceIndex = faceIndex;
                }
            }
        }
        return nearestSubmeshIndex >= 0;
    }

    private static bool RayIntersectsTriangle(
        Vector3 origin,
        Vector3 direction,
        Vector3 a,
        Vector3 b,
        Vector3 c,
        out float distance)
    {
        distance = float.PositiveInfinity;
        var edge1 = b - a;
        var edge2 = c - a;
        var p = Vector3.Cross(direction, edge2);
        var determinant = Vector3.Dot(edge1, p);
        if (Math.Abs(determinant) <= 1.0e-8f)
        {
            return false;
        }
        var inverse = 1.0f / determinant;
        var t = origin - a;
        var u = Vector3.Dot(t, p) * inverse;
        if (u < 0.0f || u > 1.0f)
        {
            return false;
        }
        var q = Vector3.Cross(t, edge1);
        var v = Vector3.Dot(direction, q) * inverse;
        if (v < 0.0f || u + v > 1.0f)
        {
            return false;
        }
        var hitDistance = Vector3.Dot(edge2, q) * inverse;
        if (!float.IsFinite(hitDistance) || hitDistance <= 1.0e-6f)
        {
            return false;
        }
        distance = hitDistance;
        return true;
    }

    private static float ScreenSegmentParameter(Point point, PointF a, PointF b)
    {
        var dx = b.X - a.X;
        var dy = b.Y - a.Y;
        var lengthSquared = (dx * dx) + (dy * dy);
        if (lengthSquared <= 1.0e-8f)
        {
            return 0.0f;
        }
        return Math.Clamp(((point.X - a.X) * dx + (point.Y - a.Y) * dy) / lengthSquared, 0.0f, 1.0f);
    }
}
