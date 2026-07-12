using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private PointF SceneProjectedPoint(NetViewportCamera camera, int submeshIndex, Vec3 vertex)
    {
        var transformed = Vector3.Transform(new Vector3(vertex.X, vertex.Y, vertex.Z), _scene.ModelMatrix(submeshIndex));
        return camera.Project(new Vec3(transformed.X, transformed.Y, transformed.Z));
    }
}
