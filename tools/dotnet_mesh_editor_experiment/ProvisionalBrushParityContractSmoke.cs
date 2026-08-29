using System.Drawing;
using System.Globalization;
using System.IO;

namespace Cdmw.MeshEditorExperiment;

internal static class ProvisionalBrushParityContractSmoke
{
    private const string Schema = "cdmw_provisional_brush_parity_contract_v1";

    public static bool IsRequested(string[] args) => args.Any(arg =>
        string.Equals(arg, "--headless-provisional-brush-parity", StringComparison.OrdinalIgnoreCase));

    public static int Run(string[] args)
    {
        var reportPath = ValueAfter(args, "--provisional-brush-parity-report");
        try
        {
            var cases = new[] { "smooth", "inflate", "pinch" }
                .Select(RunCase)
                .ToArray();
            var report = new Dictionary<string, object?>
            {
                ["schema"] = Schema,
                ["ok"] = cases.All(item => item.GetValueOrDefault("ok") is true),
                ["position_tolerance"] = new Dictionary<string, double>
                {
                    ["smooth"] = 0.00005,
                    ["inflate"] = 0.0005,
                    ["pinch"] = 0.00001,
                },
                ["cases"] = cases,
            };
            PreviewPerformanceReport.WriteAtomic(reportPath, report);
            return report["ok"] is true ? 0 : 2;
        }
        catch (Exception ex)
        {
            PreviewPerformanceReport.WriteAtomic(reportPath, new Dictionary<string, object?>
            {
                ["schema"] = Schema,
                ["ok"] = false,
                ["error"] = $"{ex.GetType().Name}: {ex.Message}",
            });
            return 1;
        }
    }

    private static Dictionary<string, object?> RunCase(string tool)
    {
        var document = BuildPerturbedGrid();
        var before = document.Submeshes[0].Vertices.ToArray();
        var materials = NetMaterialSet.Empty;
        using var textures = NetTextureSet.Load(materials);
        var scene = NetSceneState.Load(string.Empty, document.Submeshes.Count);
        scene.SetInteractionMode("mesh_edit");
        using var viewport = new MeshViewport(
            document,
            materials,
            textures,
            scene,
            HeadlessGpuInteractionSoak.SyntheticLaunchOptions())
        {
            ClientSize = new Size(640, 480),
        };
        var events = new List<Dictionary<string, object?>>();
        viewport.ToolOptionsProvider = () => new Dictionary<string, object?>
        {
            ["target_mode"] = "vertex",
            ["operation"] = "add",
            ["radius"] = 90.0,
            ["strength"] = 0.5,
            ["falloff"] = "smooth",
            ["iterations"] = 1,
            ["invert"] = false,
        };
        viewport.EditorEventRequested = (eventName, payload) =>
        {
            if (eventName is "stroke_begin" or "stroke_update" or "stroke_end")
            {
                events.Add(new Dictionary<string, object?>
                {
                    ["event"] = eventName,
                    ["payload"] = new Dictionary<string, object?>(payload),
                });
            }
        };
        var start = viewport.InteractionSoakMeshAnchor();
        viewport.BeginInteractionSoak(tool, start);
        Thread.Sleep(20);
        viewport.StepInteractionSoak(new Point(start.X + 6, start.Y + 3));
        Thread.Sleep(20);
        var result = viewport.FinishInteractionSoak(new Point(start.X + 12, start.Y + 6));
        var after = document.Submeshes[0].Vertices.ToArray();
        return new Dictionary<string, object?>
        {
            ["ok"] = result.ChangedVertexCount > 0
                && result.FinalAuthorityMatches
                && result.ProvisionalCleared
                && events.Count >= 2,
            ["tool"] = tool,
            ["vertices_before"] = before.Select(Vector).ToArray(),
            ["vertices_after"] = after.Select(Vector).ToArray(),
            ["normals"] = document.Submeshes[0].Normals.Select(Vector).ToArray(),
            ["faces"] = document.Submeshes[0].Faces
                .Select(face => face.Corners.Select(corner => corner.VertexIndex).ToArray())
                .ToArray(),
            ["selected_vertex_indices"] = Enumerable.Range(0, before.Length).ToArray(),
            ["events"] = events,
            ["changed_vertex_count"] = result.ChangedVertexCount,
        };
    }

    private static ObjDocument BuildPerturbedGrid()
    {
        const int side = 7;
        var document = new ObjDocument();
        var submesh = new ObjSubmesh("parity_grid", 0, 0, 0)
        {
            NormalsVertexAligned = true,
        };
        document.Submeshes.Add(submesh);
        for (var row = 0; row < side; row++)
        {
            for (var column = 0; column < side; column++)
            {
                var x = (column - (side - 1) * 0.5f) * 0.1f;
                var y = (row - (side - 1) * 0.5f) * 0.1f;
                var z = row == side / 2 && column == side / 2 ? 0.12f : 0.0f;
                submesh.Vertices.Add(new Vec3(x, y, z));
                submesh.Normals.Add(new Vec3(0, 0, 1));
                submesh.Uvs.Add(new Vec2(column / (float)(side - 1), row / (float)(side - 1)));
            }
        }
        for (var row = 0; row < side - 1; row++)
        {
            for (var column = 0; column < side - 1; column++)
            {
                var a = row * side + column;
                var b = a + 1;
                var c = a + side;
                var d = c + 1;
                submesh.Faces.Add(Face(a, b, c));
                submesh.Faces.Add(Face(b, d, c));
            }
        }
        return document;
    }

    private static ObjFace Face(int a, int b, int c) => new(new[]
    {
        new ObjCorner(a, a, a),
        new ObjCorner(b, b, b),
        new ObjCorner(c, c, c),
    });

    private static float[] Vector(Vec3 value) => new[] { value.X, value.Y, value.Z };

    private static string ValueAfter(string[] args, string option)
    {
        for (var index = 0; index < args.Length - 1; index++)
        {
            if (string.Equals(args[index], option, StringComparison.OrdinalIgnoreCase))
            {
                return Path.GetFullPath(args[index + 1]);
            }
        }
        return Path.Combine(Path.GetTempPath(), "cdmw-provisional-brush-parity.json");
    }
}
