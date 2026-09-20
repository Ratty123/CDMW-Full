using System.Xml;

namespace Cdmw.FullArchive.Core;

// PBD names in PAC properties are symbolic keys, not filenames. Keep this
// catalogue lookup separate from the general file-reference token scanner.
internal static class ArchivePbdMaterialReferences
{
    public const string ConfigPath = "character/descriptors/pbd/pbdconfig.xml";
    private const string RootPath = "character/descriptors/pbd/";
    private const int MaximumNames = 4096;
    private const int MaximumCharacters = 16 * 1024 * 1024;

    public static (IReadOnlyCollection<string> Names, bool Incomplete) Names(
        byte[] data, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (!TextDecoding.LooksTextual(data)) return (names, false);
        var text = TextDecoding.Decode(data);
        if (!text.Contains("pbdSimulationMaterialName", StringComparison.Ordinal)) return (names, false);
        var incomplete = ReadElements(text, cancellationToken, reader =>
        {
            var name = (reader.GetAttribute("_pbdSimulationMaterialName")
                ?? reader.GetAttribute("pbdSimulationMaterialName") ?? string.Empty).Trim();
            if (name.Length == 0) return true;
            if (name.Length > 1024 || (names.Count >= MaximumNames && !names.Contains(name))) return false;
            names.Add(name);
            return true;
        });
        return (names, incomplete);
    }

    public static (IReadOnlyDictionary<string, HashSet<string>> Materials, bool Incomplete) Materials(
        byte[] data, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var materials = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
        var count = 0;
        var incomplete = ReadElements(TextDecoding.Decode(data), cancellationToken, reader =>
        {
            if (reader.LocalName != "Material") return true;
            var name = (reader.GetAttribute("Name") ?? reader.GetAttribute("_name") ?? reader.GetAttribute("name") ?? "").Trim();
            var filename = (reader.GetAttribute("Filename") ?? reader.GetAttribute("_filename") ?? reader.GetAttribute("filename") ?? "")
                .Trim().Replace('\\', '/');
            if (name.Length == 0 || filename.Length == 0) return true;
            if (++count > MaximumNames || name.Length > 1024 || filename.Length > 1024) return false;
            var path = filename.StartsWith("character/", StringComparison.OrdinalIgnoreCase)
                ? filename : RootPath + filename.TrimStart('/');
            if (!materials.TryGetValue(name, out var paths)) materials[name] = paths = new(StringComparer.OrdinalIgnoreCase);
            paths.Add(path);
            return true;
        });
        return (materials, incomplete);
    }

    private static bool ReadElements(string text, CancellationToken cancellationToken, Func<XmlReader, bool> visit)
    {
        if (text.Length > MaximumCharacters) return true;
        try
        {
            using var reader = XmlReader.Create(new StringReader(text.TrimStart('\uFEFF')), new XmlReaderSettings
            {
                DtdProcessing = DtdProcessing.Prohibit,
                XmlResolver = null,
                ConformanceLevel = ConformanceLevel.Fragment,
                MaxCharactersInDocument = MaximumCharacters,
            });
            while (reader.Read())
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (reader.NodeType == XmlNodeType.Element && !visit(reader)) return true;
            }
            return false;
        }
        catch (XmlException)
        {
            return true;
        }
    }
}
