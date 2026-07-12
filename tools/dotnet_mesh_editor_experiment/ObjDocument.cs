using System.Globalization;
using System.IO;
using System.Text;

namespace Cdmw.MeshEditorExperiment;

internal sealed class ObjDocument
{
    public List<string> HeaderComments { get; } = new();
    public List<string> MaterialLibraries { get; } = new();
    public List<ObjSubmesh> Submeshes { get; } = new();

    public static ObjDocument Load(string path)
    {
        var document = new ObjDocument();
        var globalVertices = new List<Vec3>();
        var globalUvs = new List<Vec2>();
        var globalNormals = new List<Vec3>();
        ObjSubmesh? current = null;
        foreach (var rawLine in File.ReadLines(path))
        {
            var line = rawLine.Trim();
            if (line.Length == 0)
            {
                continue;
            }
            if (line.StartsWith("#", StringComparison.Ordinal))
            {
                document.HeaderComments.Add(line);
                continue;
            }
            var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 0)
            {
                continue;
            }
            switch (parts[0])
            {
                case "mtllib":
                    if (parts.Length > 1)
                    {
                        document.MaterialLibraries.Add(parts[1]);
                    }
                    break;
                case "o":
                case "g":
                    current = new ObjSubmesh(
                        parts.Length > 1 ? parts[1] : $"submesh_{document.Submeshes.Count}",
                        globalVertices.Count,
                        globalUvs.Count,
                        globalNormals.Count);
                    document.Submeshes.Add(current);
                    break;
                case "usemtl":
                    current ??= document.EnsureDefaultSubmesh(globalVertices.Count, globalUvs.Count, globalNormals.Count);
                    current.Material = parts.Length > 1 ? parts[1] : "";
                    break;
                case "v":
                    current ??= document.EnsureDefaultSubmesh(globalVertices.Count, globalUvs.Count, globalNormals.Count);
                    var vertex = new Vec3(ParseFloat(parts, 1), ParseFloat(parts, 2), ParseFloat(parts, 3));
                    globalVertices.Add(vertex);
                    current.Vertices.Add(vertex);
                    break;
                case "vt":
                    current ??= document.EnsureDefaultSubmesh(globalVertices.Count, globalUvs.Count, globalNormals.Count);
                    var uv = new Vec2(ParseFloat(parts, 1), ParseFloat(parts, 2));
                    globalUvs.Add(uv);
                    current.Uvs.Add(uv);
                    break;
                case "vn":
                    current ??= document.EnsureDefaultSubmesh(globalVertices.Count, globalUvs.Count, globalNormals.Count);
                    var normal = new Vec3(ParseFloat(parts, 1), ParseFloat(parts, 2), ParseFloat(parts, 3));
                    globalNormals.Add(normal);
                    current.Normals.Add(normal);
                    break;
                case "f":
                    current ??= document.EnsureDefaultSubmesh(globalVertices.Count, globalUvs.Count, globalNormals.Count);
                    var corners = parts.Skip(1).Select(token => ParseCorner(token, current, globalVertices.Count, globalUvs.Count, globalNormals.Count)).ToArray();
                    for (var i = 1; i < corners.Length - 1; i++)
                    {
                        current.Faces.Add(new ObjFace(new[] { corners[0], corners[i], corners[i + 1] }));
                    }
                    break;
            }
        }
        if (document.Submeshes.Count == 0)
        {
            throw new InvalidOperationException("OBJ did not contain any submeshes.");
        }
        return document;
    }

    public void Save(string outputPath, string inputObjPath, int? submeshCount = null)
    {
        var outputDir = Path.GetDirectoryName(outputPath);
        if (!string.IsNullOrWhiteSpace(outputDir))
        {
            Directory.CreateDirectory(outputDir);
        }

        using var writer = new StreamWriter(outputPath, false, new UTF8Encoding(false));
        foreach (var comment in HeaderComments.Where(comment => comment.StartsWith("# source_", StringComparison.OrdinalIgnoreCase)))
        {
            writer.WriteLine(comment);
        }
        var materialName = MaterialLibraries.FirstOrDefault() ?? "mesh.mtl";
        var inputMtl = Path.Combine(Path.GetDirectoryName(inputObjPath) ?? "", materialName);
        if (File.Exists(inputMtl) && outputDir is not null)
        {
            File.Copy(inputMtl, Path.Combine(outputDir, Path.GetFileName(materialName)), overwrite: true);
            writer.WriteLine($"mtllib {Path.GetFileName(materialName)}");
        }

        var vertexOffset = 0;
        var uvOffset = 0;
        var normalOffset = 0;
        foreach (var submesh in Submeshes.Take(Math.Clamp(submeshCount ?? Submeshes.Count, 0, Submeshes.Count)))
        {
            writer.WriteLine($"o {submesh.Name}");
            foreach (var vertex in submesh.Vertices)
            {
                writer.WriteLine(FormattableString.Invariant($"v {vertex.X:R} {vertex.Y:R} {vertex.Z:R}"));
            }
            foreach (var uv in submesh.Uvs)
            {
                writer.WriteLine(FormattableString.Invariant($"vt {uv.U:R} {uv.V:R}"));
            }
            foreach (var normal in submesh.Normals)
            {
                writer.WriteLine(FormattableString.Invariant($"vn {normal.X:R} {normal.Y:R} {normal.Z:R}"));
            }
            if (!string.IsNullOrWhiteSpace(submesh.Material))
            {
                writer.WriteLine($"usemtl {submesh.Material}");
            }
            foreach (var face in submesh.Faces)
            {
                writer.WriteLine("f " + string.Join(" ", face.Corners.Select(corner => FormatCorner(corner, vertexOffset, uvOffset, normalOffset, submesh))));
            }
            vertexOffset += submesh.Vertices.Count;
            uvOffset += submesh.Uvs.Count;
            normalOffset += submesh.Normals.Count;
        }
    }

    public (Vec3 Min, Vec3 Max) Bounds()
    {
        var found = false;
        var minX = 0.0f;
        var minY = 0.0f;
        var minZ = 0.0f;
        var maxX = 0.0f;
        var maxY = 0.0f;
        var maxZ = 0.0f;
        foreach (var submesh in Submeshes)
        {
            foreach (var vertex in submesh.Vertices)
            {
                if (!found)
                {
                    minX = maxX = vertex.X;
                    minY = maxY = vertex.Y;
                    minZ = maxZ = vertex.Z;
                    found = true;
                    continue;
                }
                minX = Math.Min(minX, vertex.X);
                minY = Math.Min(minY, vertex.Y);
                minZ = Math.Min(minZ, vertex.Z);
                maxX = Math.Max(maxX, vertex.X);
                maxY = Math.Max(maxY, vertex.Y);
                maxZ = Math.Max(maxZ, vertex.Z);
            }
        }
        if (!found)
        {
            return (new Vec3(-1, -1, -1), new Vec3(1, 1, 1));
        }
        return (new Vec3(minX, minY, minZ), new Vec3(maxX, maxY, maxZ));
    }

    private ObjSubmesh EnsureDefaultSubmesh(int vertexStart, int uvStart, int normalStart)
    {
        if (Submeshes.Count > 0)
        {
            return Submeshes[^1];
        }
        var submesh = new ObjSubmesh("default", vertexStart, uvStart, normalStart);
        Submeshes.Add(submesh);
        return submesh;
    }

    private static ObjCorner ParseCorner(string token, ObjSubmesh submesh, int vertexCount, int uvCount, int normalCount)
    {
        var parts = token.Split('/');
        var vertex = ResolveObjIndex(parts.ElementAtOrDefault(0), vertexCount) - submesh.VertexStart;
        var uv = parts.Length > 1 && parts[1].Length > 0 ? ResolveObjIndex(parts[1], uvCount) - submesh.UvStart : -1;
        var normal = parts.Length > 2 && parts[2].Length > 0 ? ResolveObjIndex(parts[2], normalCount) - submesh.NormalStart : -1;
        return new ObjCorner(vertex, uv, normal);
    }

    private static int ResolveObjIndex(string? raw, int count)
    {
        if (!int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value))
        {
            return 0;
        }
        if (value > 0)
        {
            return value - 1;
        }
        if (value < 0)
        {
            return count + value;
        }
        return 0;
    }

    private static string FormatCorner(ObjCorner corner, int vertexOffset, int uvOffset, int normalOffset, ObjSubmesh submesh)
    {
        var vertex = vertexOffset + Math.Clamp(corner.VertexIndex, 0, Math.Max(0, submesh.Vertices.Count - 1)) + 1;
        var hasUv = corner.UvIndex >= 0 && corner.UvIndex < submesh.Uvs.Count;
        var hasNormal = corner.NormalIndex >= 0 && corner.NormalIndex < submesh.Normals.Count;
        if (hasUv && hasNormal)
        {
            return $"{vertex}/{uvOffset + corner.UvIndex + 1}/{normalOffset + corner.NormalIndex + 1}";
        }
        if (hasUv)
        {
            return $"{vertex}/{uvOffset + corner.UvIndex + 1}";
        }
        if (hasNormal)
        {
            return $"{vertex}//{normalOffset + corner.NormalIndex + 1}";
        }
        return vertex.ToString(CultureInfo.InvariantCulture);
    }

    private static float ParseFloat(string[] parts, int index)
    {
        return index < parts.Length && float.TryParse(parts[index], NumberStyles.Float, CultureInfo.InvariantCulture, out var value)
            ? value
            : 0.0f;
    }
}

internal sealed class ObjSubmesh
{
    public ObjSubmesh(string name, int vertexStart, int uvStart, int normalStart)
    {
        Name = name;
        VertexStart = vertexStart;
        UvStart = uvStart;
        NormalStart = normalStart;
    }

    public string Name { get; }
    public string Material { get; set; } = "";
    public int VertexStart { get; }
    public int UvStart { get; }
    public int NormalStart { get; }
    public List<Vec3> Vertices { get; } = new();
    public List<Vec2> Uvs { get; } = new();
    public List<Vec3> Normals { get; } = new();
    public bool NormalsVertexAligned { get; set; }
    public bool UvsVertexAligned { get; set; }
    public List<ObjFace> Faces { get; } = new();
}

internal sealed record ObjFace(ObjCorner[] Corners);
internal sealed record ObjCorner(int VertexIndex, int UvIndex, int NormalIndex);
