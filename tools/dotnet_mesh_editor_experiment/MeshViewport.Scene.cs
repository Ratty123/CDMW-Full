using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private PointF SceneProjectedPoint(NetViewportCamera camera, int submeshIndex, Vec3 vertex)
    {
        var transformed = Vector3.Transform(new Vector3(vertex.X, vertex.Y, vertex.Z), ActiveSceneModelMatrix(submeshIndex));
        return camera.Project(new Vec3(transformed.X, transformed.Y, transformed.Z));
    }

    /// <summary>
    /// Same screen position as <see cref="SceneProjectedPoint"/>, with the
    /// projected depth the paint occlusion raster compares against. The x/y
    /// math must mirror <see cref="NetViewportCamera.Project"/> exactly.
    /// </summary>
    private PointF SceneProjectedPointWithDepth(
        NetViewportCamera camera,
        int submeshIndex,
        Vec3 vertex,
        out float depth)
    {
        var transformed = Vector3.Transform(new Vector3(vertex.X, vertex.Y, vertex.Z), ActiveSceneModelMatrix(submeshIndex));
        var clip = Vector4.Transform(new Vector4(transformed, 1.0f), camera.WorldViewProjection);
        if (Math.Abs(clip.W) > 0.000001f)
        {
            clip /= clip.W;
        }
        depth = clip.Z;
        return new PointF(
            (clip.X * 0.5f + 0.5f) * camera.ViewportWidth,
            (0.5f - clip.Y * 0.5f) * camera.ViewportHeight);
    }
}
