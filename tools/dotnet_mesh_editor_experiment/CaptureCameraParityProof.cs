using System.Drawing;
using System.IO;
using System.Numerics;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

/// <summary>
/// The capture camera against the screen camera, with no GPU and no window. An icon
/// taken from the resident viewport (New Item Studio's "Take the icon from this view",
/// the Model Library's icon capture) has to show the view the user set up, at any yaw,
/// pitch and pan; the visual-audit capture has to keep the archive object-rotation
/// basis it is given. Both go through
/// <see cref="D3D11MaterialViewport.CameraForCaptureViewport"/>, which this runs over
/// the real camera constructors and compares where the same points land. The same views
/// check that the interactive camera's <see cref="NetViewportCamera.World"/> is the view
/// frame its projection draws in, since lighting and the transparent sort read it.
/// </summary>
internal static class CaptureCameraParityProof
{
    private const string Schema = "cdmw_capture_camera_parity_v1";
    private const float PixelTolerance = 0.05f;
    private const int SourceWidth = 800;
    private const int SourceHeight = 600;
    private const int IconSize = 512;
    private const int AuditWidth = 320;
    private const int AuditHeight = 192;
    private const float Zoom = 300.0f;

    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(arg, "--headless-capture-camera-parity", StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var reportPath = RequiredValue(args, "--capture-camera-report");
        Directory.CreateDirectory(
            Path.GetDirectoryName(reportPath)
                ?? throw new InvalidOperationException("Capture camera report has no parent directory."));
        try
        {
            var center = new Vec3(0.12f, 0.4f, -0.2f);
            var bounds = (Min: new Vec3(-1.0f, -0.5f, -0.3f), Max: new Vec3(1.2f, 1.3f, 0.1f));
            var points = new[]
            {
                new Vec3(0.9f, 0.7f, -0.3f),
                new Vec3(-0.8f, 0.1f, 0.05f),
                new Vec3(0.3f, -0.4f, -0.25f),
                new Vec3(0.12f, 1.2f, 0.0f),
            };
            // Yaw 0 is where a capture built from the camera's World matrix agreed with
            // the screen (the overhead framing a weapon loads with); every other view here
            // is one an orbit or a pan reaches.
            var views = new (string Name, float YawDegrees, float PitchDegrees, float PanX, float PanY)[]
            {
                ("front", 0.0f, 0.0f, 0.0f, 0.0f),
                ("weapon_overhead", 0.0f, -89.0f, 0.0f, 0.0f),
                ("three_quarter", 30.0f, -20.0f, 0.0f, 0.0f),
                ("orbited", 30.0f, -45.0f, 0.0f, 0.0f),
                ("behind_high", -120.0f, 20.0f, 0.0f, 0.0f),
                ("side_panned", 90.0f, -10.0f, 120.0f, -60.0f),
                ("overhead_panned", 0.0f, -89.0f, 0.0f, 80.0f),
            };

            var sameSize = new List<Dictionary<string, object?>>();
            var rescaled = new List<Dictionary<string, object?>>();
            var audit = new List<Dictionary<string, object?>>();
            var viewFrame = new List<Dictionary<string, object?>>();
            foreach (var view in views)
            {
                var yaw = view.YawDegrees * MathF.PI / 180.0f;
                var pitch = view.PitchDegrees * MathF.PI / 180.0f;
                var screen = NetViewportCamera.Create(
                    center, bounds, yaw, pitch, Zoom, view.PanX, view.PanY, SourceWidth, SourceHeight);

                // A capture at the viewport's own size is what is on screen.
                var capture = D3D11MaterialViewport.CameraForCaptureViewport(screen, SourceWidth, SourceHeight);
                sameSize.Add(Compare(view.Name, points, screen.Project, capture.Project));

                // The World matrix lighting and the transparent sort read is the view
                // frame the projection draws in, at this yaw, pitch and pan.
                viewFrame.Add(ViewFrameCheck(view.Name, screen, points, center, yaw, view.PanX, view.PanY));

                // A square icon from a wider viewport: the same camera re-made at the
                // scaled zoom and pan, which is what the host documents.
                var uniform = Math.Min(IconSize / (float)SourceWidth, IconSize / (float)SourceHeight);
                var expected = NetViewportCamera.Create(
                    center, bounds, yaw, pitch, Zoom * uniform, view.PanX * uniform, view.PanY * uniform, IconSize, IconSize);
                var iconCapture = D3D11MaterialViewport.CameraForCaptureViewport(screen, IconSize, IconSize);
                rescaled.Add(Compare(view.Name, points, expected.Project, iconCapture.Project));

                // The visual audit's camera: its World and projection agree by
                // construction, and its capture stays World times the capture projection
                // (the contract the audit baselines were measured against).
                var auditCamera = NetViewportCamera.CreateArchiveAudit(
                    center, bounds, yaw, pitch, Zoom, AuditWidth, AuditHeight);
                var auditCapture = D3D11MaterialViewport.CameraForCaptureViewport(auditCamera, IconSize, IconSize);
                var auditUniform = Math.Min(IconSize / (float)AuditWidth, IconSize / (float)AuditHeight);
                var auditZoom = auditCamera.Zoom * auditUniform;
                var depthScale = 1.0f / Math.Max(auditCamera.SceneSize * 4.0f, 0.0001f);
                var captureProjection = new Matrix4x4(
                    2.0f * auditZoom / IconSize, 0.0f, 0.0f, 0.0f,
                    0.0f, 2.0f * auditZoom / IconSize, 0.0f, 0.0f,
                    0.0f, 0.0f, depthScale, 0.0f,
                    0.0f, 0.0f, 0.5f, 1.0f);
                var auditExpected = auditCamera.World * captureProjection;
                audit.Add(Compare(
                    view.Name,
                    points,
                    point => ProjectWith(auditExpected, point, IconSize, IconSize),
                    auditCapture.Project));
            }

            // Which way a plain left drag turns the subject, on a synthetic viewport: the
            // side facing the reader follows the pointer on both axes, as pan does.
            var orbit = MeshViewport.OrbitFollowsPointerContract();
            var gates = new Dictionary<string, bool>
            {
                ["interactive_capture_matches_screen"] = sameSize.All(Passed),
                ["interactive_icon_capture_is_the_camera_rescaled"] = rescaled.All(Passed),
                ["archive_audit_capture_keeps_object_rotation_basis"] = audit.All(Passed),
                ["interactive_world_is_the_view_frame_of_the_projection"] = viewFrame.All(Passed),
                ["interactive_world_unchanged_at_yaw_zero"] = viewFrame.All(
                    entry => entry["yaw_zero_unchanged"] is not false),
                ["orbit_follows_pointer"] = orbit["ok"] is true,
            };
            var ok = gates.Values.All(value => value);
            File.WriteAllText(
                reportPath,
                JsonSerializer.Serialize(
                    new Dictionary<string, object?>
                    {
                        ["schema"] = Schema,
                        ["ok"] = ok,
                        ["gates"] = gates,
                        ["pixel_tolerance"] = PixelTolerance,
                        ["source_viewport"] = new[] { SourceWidth, SourceHeight },
                        ["icon_size"] = IconSize,
                        ["same_size"] = sameSize,
                        ["rescaled"] = rescaled,
                        ["archive_audit"] = audit,
                        ["view_frame"] = viewFrame,
                        ["orbit"] = orbit,
                        ["renderer_started"] = false,
                        ["visible_window_started"] = false,
                    },
                    new JsonSerializerOptions { WriteIndented = true }));
            return ok ? 0 : 1;
        }
        catch (Exception ex)
        {
            File.WriteAllText(
                reportPath,
                JsonSerializer.Serialize(
                    new Dictionary<string, object?>
                    {
                        ["schema"] = Schema,
                        ["ok"] = false,
                        ["error"] = ex.Message,
                        ["error_type"] = ex.GetType().FullName,
                    },
                    new JsonSerializerOptions { WriteIndented = true }));
            return 1;
        }
    }

    private static Dictionary<string, object?> Compare(
        string view,
        IReadOnlyList<Vec3> points,
        Func<Vec3, PointF> expected,
        Func<Vec3, PointF> actual)
    {
        var worst = 0.0f;
        var samples = new List<Dictionary<string, object?>>(points.Count);
        foreach (var point in points)
        {
            var a = expected(point);
            var b = actual(point);
            var error = MathF.Sqrt(((a.X - b.X) * (a.X - b.X)) + ((a.Y - b.Y) * (a.Y - b.Y)));
            worst = Math.Max(worst, error);
            samples.Add(new Dictionary<string, object?>
            {
                ["point"] = new[] { point.X, point.Y, point.Z },
                ["expected_px"] = new[] { a.X, a.Y },
                ["actual_px"] = new[] { b.X, b.Y },
                ["error_px"] = error,
            });
        }
        return new Dictionary<string, object?>
        {
            ["view"] = view,
            ["ok"] = worst <= PixelTolerance,
            ["max_error_px"] = worst,
            ["samples"] = samples,
        };
    }

    private static bool Passed(Dictionary<string, object?> entry) => entry["ok"] is true;

    /// <summary>
    /// Whether <paramref name="camera"/>'s World is the view frame its projection draws
    /// in: the same points land in the same pixels through World times the projection as
    /// through WorldViewProjection; the subject's centre plus the camera's right, up and
    /// forward land on the frame's x, y and z axes (plus the pan); the rotation is proper;
    /// and at yaw 0 with no pan the matrix is the one the lighting was tuned on, the
    /// translation followed by the pitch.
    /// </summary>
    private static Dictionary<string, object?> ViewFrameCheck(
        string view,
        NetViewportCamera camera,
        IReadOnlyList<Vec3> points,
        Vec3 center,
        float yaw,
        float panX,
        float panY)
    {
        var depthScale = 1.0f / Math.Max(camera.SceneSize * 4.0f, 0.0001f);
        var projection = new Matrix4x4(
            2.0f * camera.Zoom / camera.ViewportWidth, 0.0f, 0.0f, 0.0f,
            0.0f, 2.0f * camera.Zoom / camera.ViewportHeight, 0.0f, 0.0f,
            0.0f, 0.0f, -depthScale, 0.0f,
            0.0f, 0.0f, 0.5f, 1.0f);
        var throughWorld = camera.World * projection;
        var projected = Compare(
            view,
            points,
            camera.Project,
            point => ProjectWith(throughWorld, point, camera.ViewportWidth, camera.ViewportHeight));

        var subject = new Vector3(center.X, center.Y, center.Z);
        var pan = new Vector3(panX / camera.Zoom, -(panY / camera.Zoom), 0.0f);
        var basisError = MathF.Max(
            Vector3.Distance(Vector3.Transform(subject + camera.Right, camera.World), pan + Vector3.UnitX),
            MathF.Max(
                Vector3.Distance(Vector3.Transform(subject + camera.Up, camera.World), pan + Vector3.UnitY),
                Vector3.Distance(Vector3.Transform(subject + camera.Forward, camera.World), pan + Vector3.UnitZ)));

        var rotation = camera.World;
        rotation.M41 = 0.0f;
        rotation.M42 = 0.0f;
        rotation.M43 = 0.0f;
        var determinant = rotation.GetDeterminant();

        bool? yawZeroUnchanged = null;
        if (yaw == 0.0f && panX == 0.0f && panY == 0.0f)
        {
            var tuned = Matrix4x4.CreateTranslation(-subject) * Matrix4x4.CreateRotationX(camera.Pitch);
            yawZeroUnchanged = MaxAbsoluteDifference(camera.World, tuned) <= 1e-5f;
        }

        var ok = projected["ok"] is true
            && basisError <= 1e-4f
            && Math.Abs(determinant - 1.0f) <= 1e-4f
            && yawZeroUnchanged is not false;
        return new Dictionary<string, object?>
        {
            ["view"] = view,
            ["ok"] = ok,
            ["max_error_px"] = projected["max_error_px"],
            ["basis_error"] = basisError,
            ["rotation_determinant"] = determinant,
            ["yaw_zero_unchanged"] = yawZeroUnchanged,
            ["samples"] = projected["samples"],
        };
    }

    private static float MaxAbsoluteDifference(Matrix4x4 a, Matrix4x4 b)
    {
        var d = a - b;
        var entries = new[]
        {
            d.M11, d.M12, d.M13, d.M14,
            d.M21, d.M22, d.M23, d.M24,
            d.M31, d.M32, d.M33, d.M34,
            d.M41, d.M42, d.M43, d.M44,
        };
        return entries.Max(Math.Abs);
    }

    private static PointF ProjectWith(Matrix4x4 worldViewProjection, Vec3 vertex, float width, float height)
    {
        var clip = Vector4.Transform(new Vector4(vertex.X, vertex.Y, vertex.Z, 1.0f), worldViewProjection);
        if (Math.Abs(clip.W) > 0.000001f)
        {
            clip /= clip.W;
        }
        return new PointF(
            (clip.X * 0.5f + 0.5f) * width,
            (0.5f - clip.Y * 0.5f) * height);
    }

    private static string RequiredValue(string[] args, string name)
    {
        var index = Array.FindIndex(
            args,
            arg => string.Equals(arg, name, StringComparison.OrdinalIgnoreCase));
        if (index < 0 || index + 1 >= args.Length)
        {
            throw new ArgumentException($"{name} requires a value.");
        }
        return Path.GetFullPath(args[index + 1]);
    }
}
