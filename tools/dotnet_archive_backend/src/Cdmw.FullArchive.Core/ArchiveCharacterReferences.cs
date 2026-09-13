using System.Globalization;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

internal sealed record CharacterAppearanceNode(string Role, string Name, Dictionary<string, string> Attributes);
internal sealed record CharacterReferenceResolution(long[] Models, long[] Context, string Resolution, string[] Evidence);

internal sealed class ArchiveCharacterReferences(
    IReadOnlyDictionary<string, ArchiveEntryDto> entries, Func<ArchiveEntryDto, byte[]> decode, CancellationToken token)
{
    private const int MaximumChainEntries = 4096;
    private readonly Dictionary<string, ArchiveEntryDto[]> _basenames = entries.Values
        .GroupBy(static entry => entry.Name, StringComparer.OrdinalIgnoreCase)
        .ToDictionary(static group => group.Key, static group => group.ToArray(), StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<long, ((string Attribute, string Value)[] References, string[] Evidence)> _references = [];
    private readonly Dictionary<long, (string Role, bool EmbeddedFace)> _modelRoles = [];
    private static readonly string[] NameExtensions = [".prefab", ".prefabdata_xml", ".pac", ".pam", ".pamlod", ".pac_xml"];
    private static readonly HashSet<string> Readable = new(StringComparer.OrdinalIgnoreCase)
        { ".prefab", ".prefabdata_xml", ".pac_xml", ".pam_xml", ".pamlod_xml", ".pami", ".xml" };

    internal static string Normalize(string value) => value.Replace('\\', '/').Trim().Trim('/').ToLowerInvariant();
    internal static bool IsModel(ArchiveEntryDto entry) => entry.Extension is ".pac" or ".pam" or ".pamlod";
    internal static bool IsCandidate(ArchiveEntryDto entry) => IsModel(entry)
        || entry.Extension is ".app_xml" or ".prefab" or ".prefabdata_xml";

    public bool HasEmbeddedFace(ArchiveEntryDto model) => ModelClassification(model).EmbeddedFace;

    public string ModelRole(ArchiveEntryDto model) => ModelClassification(model).Role;

    private (string Role, bool EmbeddedFace) ModelClassification(ArchiveEntryDto model)
    {
        if (_modelRoles.TryGetValue(model.EntryId, out var cached)) return cached;
        var role = Role(model.Path);
        var path = Normalize(model.Path).Replace("/model/", "/modelproperty/") + "_xml";
        var found = false;
        if (entries.TryGetValue(path, out var descriptor) && descriptor.OriginalSize <= 16 * 1024 * 1024)
        {
            try
            {
                var document = ReadXml(TextDecoding.Decode(decode(descriptor)), [], fragment: true);
                var names = document.Descendants().Attributes()
                    .Where(static attribute => attribute.Name.LocalName == "_subMeshName")
                    .Select(static attribute => Normalize(attribute.Value)).ToArray();
                var roles = names.Select(Role).Distinct().ToArray();
                found = roles.Contains("body") && roles.Contains("head");
                // A body prefab can include clothing, fur and separate facial parts.
                // Classify the physical mesh from its own submeshes, not its parent.
                // Unknown submeshes prevent a partial match (e.g. a gorilla's head)
                // from turning the whole character into a standalone head asset.
                if (role is "body" or "unclassified")
                {
                    if (roles.Contains("body")) role = "body";
                    else if (roles.Length == 1 && roles[0] != "unclassified") role = roles[0];
                    else if (roles.Length > 0 && roles.All(static value => value is "head" or "facial_detail")) role = "head";
                    else if (roles.Length > 0 && roles.All(static value => value is "hair" or "beard")) role = "hair";
                }
            }
            catch (Exception error) when (error is IOException or XmlException or InvalidDataException or ArgumentException) { }
        }
        return _modelRoles[model.EntryId] = (role, found);
    }

    internal static string Role(string path)
    {
        var normalized = Normalize(path);
        var parts = normalized.Split('/');
        var stem = Path.GetFileNameWithoutExtension(normalized);
        if (parts.Contains("armor") || parts.Contains("weapon") || Regex.IsMatch(stem, @"_(?:armor|ub|lb|hand|foot|hel|cloak|sword|shield|bow|saddle|parthide|bag|belt|chain|flail|floor|saliva|uw|wagon|boat)_")) return "excluded";
        if (parts.Contains("hair") || Regex.IsMatch(stem, @"_(?:hair\d*|fur|fuzz)_")) return "hair";
        if (parts.Contains("beard") || stem.Contains("_beard_")) return "beard";
        if (parts.Contains("head_sub") || Regex.IsMatch(stem, @"_(?:head_sub|eyebrow|eyeline|eyelash|eye|eyeleft|eyeright|teeth|tooth|horn|tongue|tear)(?:_|$)")) return "facial_detail";
        if (parts.Contains("head") || parts.Contains("face") || Regex.IsMatch(stem, @"_(?:head|face)_")) return "head";
        if (parts.Contains("nude") || parts.Contains("body") || Regex.IsMatch(stem, @"_(?:nude|body)_")) return "body";
        if (normalized.Contains("/6_object/") || normalized.Contains("/7_montower/")) return "excluded";
        return "unclassified";
    }

    internal static string SourceGroup(string path)
    {
        var parts = Normalize(path).Split('/');
        return parts.FirstOrDefault(static part => part is "1_pc" or "2_mon" or "3_npc" or "4_riding" or "6_object" or "7_montower") ?? "unknown";
    }

    internal static string BodyFamily(string path)
    {
        var parts = Normalize(path).Split('/');
        var pc = Array.IndexOf(parts, "1_pc");
        if (pc >= 0 && pc + 1 < parts.Length)
            return Regex.Replace(parts[pc + 1], @"^0+(?=\d)", "");
        return "unknown";
    }

    internal static XDocument ReadXml(string text, List<string> evidence, bool fragment = false)
    {
        XDocument Parse(string source)
        {
            using var reader = XmlReader.Create(new StringReader(source), new XmlReaderSettings {
                DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = 16 * 1024 * 1024,
                ConformanceLevel = fragment ? ConformanceLevel.Fragment : ConformanceLevel.Document });
            if (!fragment) return XDocument.Load(reader);
            // Model-property and bone-mask files intentionally contain sibling roots.
            var root = new XElement("CharacterDescriptorFragment");
            reader.Read();
            while (!reader.EOF)
            {
                if (reader.NodeType == XmlNodeType.Element) root.Add(XNode.ReadFrom(reader));
                else reader.Read();
            }
            return new XDocument(root);
        }
        try { return Parse(text.TrimStart('\uFEFF')); }
        catch (XmlException)
        {
            // Only insert a missing separator after a quoted attribute inside a tag.
            // Attribute values and archive bytes are preserved.
            var recovered = Regex.Replace(text, @"<[^>]+>", tag => Regex.Replace(tag.Value,
                "(=[\"'][^\"']*[\"'])(?=[A-Za-z_][A-Za-z0-9_:.-]*\\s*=)", "$1 "));
            if (recovered == text) throw;
            var document = Parse(recovered.TrimStart('\uFEFF'));
            evidence.Add("Recovered missing whitespace between XML attributes in memory.");
            return document;
        }
    }

    public static CharacterAppearanceNode[] AppearanceNodes(string text, List<string> evidence, out string[] customization)
    {
        var document = ReadXml(text, evidence);
        customization = document.Descendants().Where(static element => element.Name.LocalName.Equals("Customization", StringComparison.OrdinalIgnoreCase))
            .SelectMany(static element => element.Attributes())
            .Where(static attribute => !string.IsNullOrWhiteSpace(attribute.Value)).Select(static attribute => attribute.Value).Distinct().ToArray();
        var result = new List<CharacterAppearanceNode>();
        foreach (var section in document.Descendants())
        {
            var sectionName = section.Name.LocalName.ToLowerInvariant();
            if (sectionName is not ("nude" or "body" or "head" or "face" or "hair")) continue;
            var prefabs = section.Attribute("Name") is not null ? new[] { section } : section.Elements();
            foreach (var element in prefabs)
            {
                var name = element.Attributes().FirstOrDefault(static attribute => attribute.Name.LocalName.Equals("Name", StringComparison.OrdinalIgnoreCase))?.Value;
                if (string.IsNullOrWhiteSpace(name)) continue;
                var attributes = section.Attributes().Concat(element.Attributes())
                    .GroupBy(static attribute => attribute.Name.LocalName, StringComparer.OrdinalIgnoreCase)
                    .ToDictionary(static group => group.Key, static group => group.Last().Value, StringComparer.OrdinalIgnoreCase);
                var role = sectionName is "nude" or "body" ? "body" : sectionName == "face" ? "facial_detail" : sectionName;
                var nameRole = Role(name);
                if (role == "hair" && nameRole == "beard") role = "beard";
                if (role == "head" && nameRole == "facial_detail") role = "facial_detail";
                result.Add(new(role, name, attributes));
            }
        }
        return result.ToArray();
    }

    public long[] ResolveCustomization(IEnumerable<string> names, List<string> evidence)
    {
        var result = new HashSet<long>();
        foreach (var name in names)
        {
            var found = Candidates(name, [".paccd", ".xml"], out var ambiguous);
            if (found.Length == 0) evidence.Add($"Unresolved customization reference: {name}");
            if (ambiguous) evidence.Add($"Ambiguous customization reference: {name}; all candidates retained.");
            foreach (var entry in found) result.Add(entry.EntryId);
        }
        return result.Order().ToArray();
    }

    public CharacterReferenceResolution Resolve(string name, string role, ArchiveEntryDto? physical = null)
    {
        var models = new HashSet<long>();
        var context = new HashSet<long>();
        var visited = new HashSet<long>();
        var evidence = new List<string>();
        var ambiguous = false;
        var incomplete = false;
        var queue = new Queue<ArchiveEntryDto>();
        void Offer(ArchiveEntryDto entry)
        {
            if (visited.Contains(entry.EntryId)) return;
            if (visited.Count >= MaximumChainEntries) { incomplete = true; return; }
            visited.Add(entry.EntryId);
            queue.Enqueue(entry);
        }
        void OfferReference(string value, string[] extensions)
        {
            var found = Candidates(value, extensions, out var multiple);
            ambiguous |= multiple;
            foreach (var entry in found) Offer(entry);
            if (found.Length == 0) evidence.Add($"Unresolved reference: {value}");
        }
        if (physical is not null) Offer(physical);
        OfferReference(name, NameExtensions);
        void Drain()
        {
          while (queue.TryDequeue(out var entry))
          {
            token.ThrowIfCancellationRequested();
            if (IsModel(entry))
            {
                models.Add(entry.EntryId);
                var sidecar = Normalize(entry.Path).Replace("/model/", "/modelproperty/") + "_xml";
                if (entries.TryGetValue(sidecar, out var material)) Offer(material);
                var stem = Path.GetFileNameWithoutExtension(entry.Name);
                foreach (var suffix in new[] { ".prefabdata_xml", ".pami" })
                    foreach (var companion in Candidates(stem + suffix, [], out var multiple))
                    { ambiguous |= multiple; Offer(companion); }
                continue;
            }
            context.Add(entry.EntryId);
            if (!Readable.Contains(entry.Extension)) continue;
            try
            {
                foreach (var (attribute, value) in ReadReferences(entry, evidence))
                    OfferReference(value, attribute == "customizationfile" ? [".paccd", ".xml"] : NameExtensions);
            }
            catch (Exception error) when (error is IOException or InvalidDataException or XmlException or ArgumentException)
            { incomplete = true; evidence.Add($"Could not decode {entry.Path}: {error.Message}"); }
          }
        }
        Drain();
        var inferred = false;
        if (models.Count == 0 && role == "body")
        {
            // Retain the existing supported actor-family base-body convention, and
            // expose its inferred authority instead of labelling it an exact link.
            var match = Regex.Match(name, @"^(?<prefix>.+?_nude_)\d+_\d+(?:_[a-z][a-z0-9]*)?$", RegexOptions.IgnoreCase);
            if (match.Success)
            {
                var fallback = Candidates(match.Groups["prefix"].Value + "00_0001.pac", [], out var multiple);
                ambiguous |= multiple;
                foreach (var entry in fallback) Offer(entry);
                Drain();
                inferred = fallback.Length > 0;
                if (inferred) evidence.Add("Base mesh resolved by the existing actor body-family convention; authored descriptor retained.");
            }
        }
        if (incomplete) evidence.Add("Dependency discovery is incomplete.");
        var resolution = models.Count == 0 ? "unresolved" : ambiguous ? "ambiguous" : incomplete || inferred ? "inferred" : "resolved";
        return new(models.Order().ToArray(), context.Order().ToArray(), resolution, evidence.Distinct().ToArray());
    }

    private ArchiveEntryDto[] Candidates(string value, string[] extensions, out bool ambiguous)
    {
        var normalized = Normalize(value);
        ambiguous = false;
        if (entries.TryGetValue(normalized, out var exact)) return [exact];
        var basename = Path.GetFileName(normalized);
        var names = Path.HasExtension(basename) ? new[] { basename } : extensions.Select(extension => basename + extension).ToArray();
        var result = new List<ArchiveEntryDto>();
        foreach (var name in names)
        {
            var found = _basenames.GetValueOrDefault(name) ?? [];
            if (normalized.Contains('/'))
            {
                var suffix = Path.HasExtension(basename) ? normalized : normalized + Path.GetExtension(name);
                found = found.Where(entry => Normalize(entry.Path).EndsWith('/' + suffix, StringComparison.Ordinal)).ToArray();
            }
            ambiguous |= found.Length > 1;
            result.AddRange(found);
        }
        return result.DistinctBy(static entry => entry.EntryId).ToArray();
    }

    private (string Attribute, string Value)[] ReadReferences(ArchiveEntryDto entry, List<string> evidence)
    {
        if (_references.TryGetValue(entry.EntryId, out var cached))
        { evidence.AddRange(cached.Evidence); return cached.References; }
        var evidenceStart = evidence.Count;
        if (entry.OriginalSize > 16 * 1024 * 1024) throw new InvalidDataException("Character descriptor exceeds 16 MiB.");
        var bytes = decode(entry);
        var references = new List<(string, string)>();
        if (TextDecoding.LooksTextual(bytes) && TextDecoding.Decode(bytes).TrimStart('\uFEFF', ' ', '\r', '\n', '\t').StartsWith('<'))
        {
            var doc = ReadXml(TextDecoding.Decode(bytes), evidence, fragment: true);
            foreach (var attribute in doc.Descendants().Attributes())
            {
                var key = attribute.Name.LocalName.ToLowerInvariant();
                if (key is "filename" or "path" or "customizationfile" or "meshparamfile" or "decorationparamfile"
                    || Path.HasExtension(attribute.Value) && attribute.Value.Contains('/'))
                    if (!string.IsNullOrWhiteSpace(attribute.Value)) references.Add((key, attribute.Value));
            }
        }
        else
        {
            var tokens = ArchivePreviewReferenceScanner.Extract(bytes, token, includeMaterialBasenameHints: false);
            // The scanner also exposes printable diagnostic tokens. Length-prefixed
            // binary strings can abut a printable byte (for example .pacB); those
            // diagnostic tokens are not authored file references.
            references.AddRange(tokens.Tokens.Where(static value => value.Contains('/') &&
                new[] { ".pac", ".pam", ".pamlod", ".pac_xml", ".pam_xml", ".pamlod_xml", ".prefab", ".prefabdata_xml",
                    ".pab", ".pabc", ".pabv", ".pamt", ".pami", ".xml", ".dds", ".paccd", ".hkt", ".papr" }
                    .Contains(Path.GetExtension(value), StringComparer.OrdinalIgnoreCase))
                .Select(static value => ("path", value)));
            if (tokens.Truncated) evidence.Add($"Reference tokens truncated: {entry.Path}");
        }
        var result = references.Distinct().ToArray();
        _references[entry.EntryId] = (result, evidence.Skip(evidenceStart).ToArray());
        return result;
    }

    public static double Scale(CharacterAppearanceNode node)
    {
        var name = node.Role == "body" ? "CharacterScale" : node.Role == "head" ? "HeadScale" : "Scale";
        return node.Attributes.TryGetValue(name, out var value)
            && double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var scale)
            && double.IsFinite(scale) && scale > 0 && scale <= 1000 ? scale : 1.0;
    }
}
