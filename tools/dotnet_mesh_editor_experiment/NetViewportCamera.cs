using System.Drawing;
using System.Numerics;

namespace Cdmw.MeshEditorExperiment;

internal readonly record struct NetViewportCamera(
    Vec3 Center,
    (Vec3 Min, Vec3 Max) Bounds,
    float Yaw,
    float Pitch,
    float Zoom,
    float PanX,
    float PanY,
    float ViewportWidth,
    float ViewportHeight,
    float SceneSize,
    Vector3 Forward,
    Vector3 Right,
    Vector3 Up,
    Matrix4x4 World,
    Matrix4x4 WorldViewProjection)
{
    public static NetViewportCamera Create(
        Vec3 center,
        (Vec3 Min, Vec3 Max) bounds,
        float yaw,
        float pitch,
        float zoom,
        float panX,
        float panY,
        int viewportWidth,
        int viewportHeight)
    {
        var width = Math.Max(1.0f, viewportWidth);
        var height = Math.Max(1.0f, viewportHeight);
        var safeZoom = Math.Max(zoom, 0.001f);
        var size = Math.Max(bounds.Max.X - bounds.Min.X, Math.Max(bounds.Max.Y - bounds.Min.Y, bounds.Max.Z - bounds.Min.Z));
        var depthScale = 1.0f / Math.Max(size * 4.0f, 0.0001f);
        var scaleX = 2.0f * safeZoom / width;
        var scaleY = 2.0f * safeZoom / height;
        var cosYaw = MathF.Cos(yaw);
        var sinYaw = MathF.Sin(yaw);
        var cosPitch = MathF.Cos(pitch);
        var sinPitch = MathF.Sin(pitch);

        var forward = NormalizeOrFallback(
            new Vector3(sinYaw * cosPitch, sinPitch, cosYaw * cosPitch),
            Vector3.UnitZ);
        var right = NormalizeOrFallback(new Vector3(cosYaw, 0.0f, -sinYaw), Vector3.UnitX);
        var up = NormalizeOrFallback(Vector3.Cross(forward, right), Vector3.UnitY);

        var world = Matrix4x4.CreateTranslation(
            -center.X + (panX / safeZoom),
            -center.Y - (panY / safeZoom),
            -center.Z)
            * Matrix4x4.CreateRotationX(pitch)
            * Matrix4x4.CreateRotationY(yaw);

        var worldViewProjection = new Matrix4x4(
            scaleX * cosYaw,
            -scaleY * sinYaw * sinPitch,
            -depthScale * sinYaw * cosPitch,
            0.0f,
            0.0f,
            scaleY * cosPitch,
            -depthScale * sinPitch,
            0.0f,
            -scaleX * sinYaw,
            -scaleY * cosYaw * sinPitch,
            -depthScale * cosYaw * cosPitch,
            0.0f,
            scaleX * ((-center.X * cosYaw) + (center.Z * sinYaw)) + (2.0f * panX / width),
            scaleY * ((-center.Y * cosPitch) + (center.X * sinYaw * sinPitch) + (center.Z * cosYaw * sinPitch)) - (2.0f * panY / height),
            0.5f + depthScale * ((center.X * sinYaw * cosPitch) + (center.Y * sinPitch) + (center.Z * cosYaw * cosPitch)),
            1.0f);

        return new NetViewportCamera(
            center,
            bounds,
            yaw,
            pitch,
            safeZoom,
            panX,
            panY,
            width,
            height,
            size,
            forward,
            right,
            up,
            world,
            worldViewProjection);
    }

    public static NetViewportCamera CreateArchiveAudit(
        Vec3 center,
        (Vec3 Min, Vec3 Max) bounds,
        float yaw,
        float pitch,
        float zoom,
        int viewportWidth,
        int viewportHeight)
    {
        var width = Math.Max(1.0f, viewportWidth);
        var height = Math.Max(1.0f, viewportHeight);
        var safeZoom = Math.Max(zoom, 0.001f);
        var size = Math.Max(
            bounds.Max.X - bounds.Min.X,
            Math.Max(bounds.Max.Y - bounds.Min.Y, bounds.Max.Z - bounds.Min.Z));
        var depthScale = 1.0f / Math.Max(size * 4.0f, 0.0001f);
        var scaleX = 2.0f * safeZoom / width;
        var scaleY = 2.0f * safeZoom / height;

        // Archive Browser rotates the normalized object in this order while its
        // camera stays fixed. Keep that basis audit-only so the paired captures
        // match without changing the interactive Mesh Editor camera contract.
        var world = Matrix4x4.CreateTranslation(-center.X, -center.Y, -center.Z)
            * Matrix4x4.CreateRotationX(pitch)
            * Matrix4x4.CreateRotationY(yaw);
        var orthographicProjection = new Matrix4x4(
            scaleX,
            0.0f,
            0.0f,
            0.0f,
            0.0f,
            scaleY,
            0.0f,
            0.0f,
            0.0f,
            0.0f,
            depthScale,
            0.0f,
            0.0f,
            0.0f,
            0.5f,
            1.0f);
        var worldViewProjection = world * orthographicProjection;

        return new NetViewportCamera(
            center,
            bounds,
            yaw,
            pitch,
            safeZoom,
            0.0f,
            0.0f,
            width,
            height,
            size,
            Vector3.UnitZ,
            Vector3.UnitX,
            Vector3.UnitY,
            world,
            worldViewProjection);
    }

    public PointF Project(Vec3 vertex)
    {
        var clip = Vector4.Transform(new Vector4(vertex.X, vertex.Y, vertex.Z, 1.0f), WorldViewProjection);
        if (Math.Abs(clip.W) > 0.000001f)
        {
            clip /= clip.W;
        }
        return new PointF(
            (clip.X * 0.5f + 0.5f) * ViewportWidth,
            (0.5f - clip.Y * 0.5f) * ViewportHeight);
    }

    public double[] WorldViewProjectionRowMajorArray()
    {
        return new[]
        {
            (double)WorldViewProjection.M11,
            (double)WorldViewProjection.M12,
            (double)WorldViewProjection.M13,
            (double)WorldViewProjection.M14,
            (double)WorldViewProjection.M21,
            (double)WorldViewProjection.M22,
            (double)WorldViewProjection.M23,
            (double)WorldViewProjection.M24,
            (double)WorldViewProjection.M31,
            (double)WorldViewProjection.M32,
            (double)WorldViewProjection.M33,
            (double)WorldViewProjection.M34,
            (double)WorldViewProjection.M41,
            (double)WorldViewProjection.M42,
            (double)WorldViewProjection.M43,
            (double)WorldViewProjection.M44,
        };
    }

    public static PointF Project(
        Vec3 vertex,
        Vec3 center,
        (Vec3 Min, Vec3 Max) bounds,
        float yaw,
        float pitch,
        float zoom,
        int viewportWidth,
        int viewportHeight)
    {
        return Create(center, bounds, yaw, pitch, zoom, 0.0f, 0.0f, viewportWidth, viewportHeight).Project(vertex);
    }

    private static Vector3 NormalizeOrFallback(Vector3 vector, Vector3 fallback)
    {
        return vector.LengthSquared() > 0.000001f ? Vector3.Normalize(vector) : fallback;
    }

    /// <summary>
    /// Framing angles for a model, derived from its own extents.
    /// </summary>
    /// <remarks>
    /// A flat object -- a shield, a blade, a banner -- has one extent far
    /// smaller than the other two, and a fixed viewing angle shows it edge-on:
    /// a shield resting in its authored pose reads as a line, and a sword blade
    /// presents its edge rather than its face. Looking down the thinnest axis
    /// turns the largest face toward the camera. Anything roughly
    /// equidimensional is left on the caller's angles, because there is no flat
    /// face to prefer and the standard three-quarter view reads better.
    /// A small tilt is kept off-axis so the result still shows form rather than
    /// looking orthographic.
    /// </remarks>
    public static (float Yaw, float Pitch) FramingAnglesFor(
        (Vec3 Min, Vec3 Max) bounds,
        float defaultYaw,
        float defaultPitch)
    {
        var ex = MathF.Abs(bounds.Max.X - bounds.Min.X);
        var ey = MathF.Abs(bounds.Max.Y - bounds.Min.Y);
        var ez = MathF.Abs(bounds.Max.Z - bounds.Min.Z);
        var smallest = MathF.Min(ex, MathF.Min(ey, ez));
        var largest = MathF.Max(ex, MathF.Max(ey, ez));
        if (largest <= 0.000001f)
        {
            return (defaultYaw, defaultPitch);
        }
        // The middle extent is what decides flatness: comparing against the
        // largest alone would call a long thin rod flat.
        var middle = ex + ey + ez - smallest - largest;
        if (middle <= 0.000001f || smallest > middle * 0.45f)
        {
            return (defaultYaw, defaultPitch);
        }
        const float Tilt = 0.20f;
        if (smallest == ey)
        {
            // Lying flat in its authored pose: look down at the face.
            return (defaultYaw, -MathF.PI * 0.5f + Tilt);
        }
        if (smallest == ex)
        {
            return (MathF.PI * 0.5f - Tilt, Tilt * 0.5f);
        }
        return (Tilt, Tilt * 0.5f);
    }
}
