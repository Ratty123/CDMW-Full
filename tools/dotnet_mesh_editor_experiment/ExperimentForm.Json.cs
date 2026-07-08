using System.Globalization;
using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class ExperimentForm
{
    private static Dictionary<int, HashSet<int>> JsonSelectionMap(JsonElement element, string name)
    {
        var result = new Dictionary<int, HashSet<int>>();
        if (!element.TryGetProperty(name, out var value))
        {
            return result;
        }
        return JsonSelectionMap(value);
    }

    private static Dictionary<int, HashSet<int>> JsonSelectionMap(JsonElement value)
    {
        var result = new Dictionary<int, HashSet<int>>();
        if (value.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in value.EnumerateObject())
            {
                if (int.TryParse(property.Name, NumberStyles.Integer, CultureInfo.InvariantCulture, out var key) && key >= 0)
                {
                    result[key] = JsonIntSet(property.Value);
                }
            }
            return result;
        }
        if (value.ValueKind != JsonValueKind.Array)
        {
            return result;
        }
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Object)
            {
                var key = JsonInt(item, "index", JsonInt(item, "submesh_index", -1));
                if (key >= 0)
                {
                    result[key] = JsonIntSet(item.TryGetProperty("indices", out var indices) ? indices : item);
                }
                continue;
            }
            if (item.ValueKind != JsonValueKind.Array)
            {
                continue;
            }
            var parts = item.EnumerateArray().ToArray();
            if (parts.Length >= 2 && parts[0].ValueKind == JsonValueKind.Number && parts[0].TryGetInt32(out var pairKey))
            {
                result[pairKey] = JsonIntSet(parts[1]);
            }
        }
        return result;
    }

    private static Dictionary<int, HashSet<(int A, int B)>> JsonEdgeSelectionMap(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value))
        {
            return new Dictionary<int, HashSet<(int A, int B)>>();
        }
        var result = new Dictionary<int, HashSet<(int A, int B)>>();
        if (value.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in value.EnumerateObject())
            {
                if (int.TryParse(property.Name, NumberStyles.Integer, CultureInfo.InvariantCulture, out var key) && key >= 0)
                {
                    result[key] = JsonEdgePairs(property.Value);
                }
            }
            return result;
        }
        if (value.ValueKind != JsonValueKind.Array)
        {
            return result;
        }
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Array)
            {
                continue;
            }
            var parts = item.EnumerateArray().ToArray();
            if (parts.Length >= 2 && parts[0].ValueKind == JsonValueKind.Number && parts[0].TryGetInt32(out var key) && key >= 0)
            {
                result[key] = JsonEdgePairs(parts[1]);
            }
        }
        return result;
    }

    private static Dictionary<int, HashSet<(int A, int B)>> JsonEdgeDescriptorSelectionMap(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return new Dictionary<int, HashSet<(int A, int B)>>();
        }
        var result = new Dictionary<int, HashSet<(int A, int B)>>();
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var submesh = JsonInt(item, "source_submesh_index", JsonInt(item, "submesh_index", -1));
            var vertexA = JsonInt(item, "vertex_a", -1);
            var vertexB = JsonInt(item, "vertex_b", -1);
            if (submesh < 0 || vertexA < 0 || vertexB < 0 || vertexA == vertexB)
            {
                continue;
            }
            var pair = vertexA <= vertexB ? (vertexA, vertexB) : (vertexB, vertexA);
            if (!result.TryGetValue(submesh, out var set))
            {
                set = new HashSet<(int A, int B)>();
                result[submesh] = set;
            }
            set.Add(pair);
        }
        return result;
    }

    private static HashSet<(int A, int B)> JsonEdgePairs(JsonElement value)
    {
        var result = new HashSet<(int A, int B)>();
        if (value.ValueKind != JsonValueKind.Array)
        {
            return result;
        }
        foreach (var item in value.EnumerateArray())
        {
            int vertexA;
            int vertexB;
            if (item.ValueKind == JsonValueKind.Object)
            {
                vertexA = JsonInt(item, "vertex_a", -1);
                vertexB = JsonInt(item, "vertex_b", -1);
            }
            else if (item.ValueKind == JsonValueKind.Array)
            {
                var values = item.EnumerateArray().ToArray();
                if (values.Length < 2)
                {
                    continue;
                }
                vertexA = values[0].ValueKind == JsonValueKind.Number && values[0].TryGetInt32(out var a) ? a : -1;
                vertexB = values[1].ValueKind == JsonValueKind.Number && values[1].TryGetInt32(out var b) ? b : -1;
            }
            else
            {
                continue;
            }
            if (vertexA >= 0 && vertexB >= 0 && vertexA != vertexB)
            {
                result.Add(vertexA <= vertexB ? (vertexA, vertexB) : (vertexB, vertexA));
            }
        }
        return result;
    }

    private static HashSet<int> JsonIntSet(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) ? JsonIntSet(value) : new HashSet<int>();
    }

    private static HashSet<int> JsonIntSet(JsonElement value)
    {
        var result = new HashSet<int>();
        if (value.ValueKind != JsonValueKind.Array)
        {
            return result;
        }
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Number && item.TryGetInt32(out var number))
            {
                result.Add(number);
            }
            else if (item.ValueKind == JsonValueKind.String && int.TryParse(item.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out number))
            {
                result.Add(number);
            }
        }
        return result;
    }

    private static string JsonString(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? ""
            : "";
    }

    private static int JsonInt(JsonElement element, string name, int fallback)
    {
        if (!element.TryGetProperty(name, out var value))
        {
            return fallback;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number))
        {
            return number;
        }
        return value.ValueKind == JsonValueKind.String && int.TryParse(value.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out number)
            ? number
            : fallback;
    }

    private static List<int> JsonIntValues(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return new List<int>();
        }
        var result = new List<int>();
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Number && item.TryGetInt32(out var number))
            {
                result.Add(number);
            }
        }
        return result;
    }

    private static List<double> JsonDoubleValues(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return new List<double>();
        }
        var result = new List<double>();
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.Number && item.TryGetDouble(out var number))
            {
                result.Add(number);
            }
        }
        return result;
    }

    private static List<int> ReadIntBinary(JsonElement descriptor)
    {
        var path = JsonString(descriptor, "path");
        var count = JsonInt(descriptor, "count", 0);
        if (path.Length == 0 || count <= 0 || !File.Exists(path))
        {
            return new List<int>();
        }
        var bytes = File.ReadAllBytes(path);
        var result = new List<int>(Math.Min(count, bytes.Length / sizeof(int)));
        for (var offset = 0; offset + sizeof(int) <= bytes.Length && result.Count < count; offset += sizeof(int))
        {
            result.Add(BitConverter.ToInt32(bytes, offset));
        }
        return result;
    }

    private static List<double> ReadDoubleBinary(JsonElement descriptor)
    {
        var path = JsonString(descriptor, "path");
        var count = JsonInt(descriptor, "count", 0);
        var components = JsonInt(descriptor, "components", 1);
        var total = count * components;
        if (path.Length == 0 || total <= 0 || !File.Exists(path))
        {
            return new List<double>();
        }
        var bytes = File.ReadAllBytes(path);
        var result = new List<double>(Math.Min(total, bytes.Length / sizeof(double)));
        for (var offset = 0; offset + sizeof(double) <= bytes.Length && result.Count < total; offset += sizeof(double))
        {
            result.Add(BitConverter.ToDouble(bytes, offset));
        }
        return result;
    }
}
