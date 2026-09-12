using System.Security.Cryptography;
using System.Text;
using System.Xml;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public static class ArchiveCharacterCatalogBuilder
{
    public const int Version = 4;
    private static readonly HashSet<string> CharacterExtensions = new(StringComparer.OrdinalIgnoreCase) {
        ".pac", ".pam", ".pamlod", ".app_xml", ".prefab", ".prefabdata_xml", ".pappt",
        ".pac_xml", ".pam_xml", ".pamlod_xml", ".pami", ".pab", ".pabc", ".pamt", ".pabv", ".paccd", ".xml", ".dds", ".hkt", ".papr" };

    public static CharacterCatalogSnapshot Build(
        string packageRoot, string signature, IEnumerable<ArchiveEntryDto> inventory,
        Func<ArchiveEntryDto, byte[]> read, CancellationToken token,
        Action<int, int, string>? progress = null)
    {
        var sources = new ArchiveItemSources(packageRoot);
        var entries = new Dictionary<string, ArchiveEntryDto>(StringComparer.OrdinalIgnoreCase);
        var candidates = new List<ArchiveEntryDto>();
        var warnings = new List<string>();
        var seen = 0;
        foreach (var entry in inventory)
        {
            if ((seen++ & 0x1FFF) == 0) { token.ThrowIfCancellationRequested(); progress?.Invoke(seen, 0, "Reading character archive inventory"); }
            sources.Offer(entry);
            if (!entry.Path.StartsWith("character/", StringComparison.OrdinalIgnoreCase) || !CharacterExtensions.Contains(entry.Extension)) continue;
            if (ArchiveCharacterReferences.IsCandidate(entry)) candidates.Add(entry);
            if (!sources.Accepts(entry)) continue;
            var path = ArchiveCharacterReferences.Normalize(entry.Path);
            if (!entries.TryGetValue(path, out var previous) || sources.Order(entry).CompareTo(sources.Order(previous)) > 0)
                entries[path] = entry;
        }
        byte[] Decode(ArchiveEntryDto entry)
        {
            token.ThrowIfCancellationRequested();
            if (entry.OriginalSize > 128 * 1024 * 1024 || entry.StoredSize > 128 * 1024 * 1024)
                throw new InvalidDataException($"Character metadata exceeds 128 MiB: {entry.Path}");
            var bytes = read(entry);
            token.ThrowIfCancellationRequested();
            return bytes;
        }
        var byId = entries.Values.ToDictionary(static entry => entry.EntryId);
        var apps = entries.Values.Where(static entry => entry.Extension == ".app_xml").OrderBy(static entry => entry.Path, StringComparer.OrdinalIgnoreCase).ToArray();
        var unresolvedNames = new List<CharacterUnresolvedNameLink>();
        var names = ArchiveCharacterNames.Read(sources, apps, Decode, warnings, unresolvedNames, token);
        var resolver = new ArchiveCharacterReferences(entries, Decode, token);
        var records = new Dictionary<string, CharacterCatalogRecord>(StringComparer.Ordinal);
        var coverage = new Dictionary<string, CharacterCatalogRow>(StringComparer.Ordinal);
        var uses = new Dictionary<long, HashSet<string>>();
        var usedRoles = new Dictionary<long, HashSet<string>>();
        var embedded = new HashSet<long>();

        CharacterCatalogRow Row(string key, string view, string role, string label, string internalName,
            string path, string resolution, int count, string evidence, bool embeddedFace = false) =>
            new(key, view, role, label, internalName, path, ArchiveCharacterReferences.SourceGroup(path),
                ArchiveCharacterReferences.BodyFamily(path), resolution, count > 0 && resolution != "ambiguous" ? "base_appearance" : "unresolved_model",
                count, 0, evidence, embeddedFace);
        void Account(ArchiveEntryDto entry, string resolution, string reason) =>
            coverage["coverage:" + entry.EntryId] = Row("coverage:" + entry.EntryId, "coverage", ArchiveCharacterReferences.Role(entry.Path),
                entry.Name, entry.Name, entry.Path, resolution, 0, reason);
        string[] SearchNames(CharacterNameLink[] links, string[] extra) => links.SelectMany(static link => link.SearchNames).Concat(extra).Distinct().ToArray();

        foreach (var missing in unresolvedNames)
        {
            var owner = missing.Link.Owner;
            var key = $"appearance-link:{owner.CharacterId}/{missing.Variant}";
            var row = Row(key, "appearances", "unclassified", string.IsNullOrEmpty(owner.DisplayName) ? owner.InternalName : owner.DisplayName,
                owner.InternalName, missing.Table.Path, "unresolved", 0, owner.Evidence);
            records[key] = new(row, missing.Link.SearchNames, [missing.Table.EntryId, missing.HeaderId],
                [missing.Table.EntryId, missing.HeaderId], [], [], [owner], [owner.Evidence], ContextKey: key);
            coverage["reference:" + key] = row with { Key = "reference:" + key, View = "coverage" };
        }

        for (var appIndex = 0; appIndex < apps.Length; appIndex++)
        {
            token.ThrowIfCancellationRequested();
            var app = apps[appIndex];
            progress?.Invoke(appIndex, apps.Length, "Resolving body and face appearances");
            var evidence = new List<string>();
            var links = names.GetValueOrDefault(ArchiveCharacterReferences.Normalize(app.Path))?.ToArray() ?? [];
            var displayNames = links.Select(static link => link.Owner.DisplayName).Where(static name => name.Length > 0).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
            var label = displayNames.Length == 1 ? displayNames[0] : displayNames.Length > 1 ? $"Shared appearance ({displayNames.Length} names)" : Path.GetFileNameWithoutExtension(app.Name);
            CharacterAppearanceNode[] nodes;
            string[] customization;
            try { nodes = ArchiveCharacterReferences.AppearanceNodes(TextDecoding.Decode(Decode(app)), evidence, out customization); }
            catch (Exception error) when (error is IOException or XmlException or InvalidDataException or ArgumentException)
            { nodes = []; customization = []; evidence.Add($"Appearance could not be decoded: {error.Message}"); }
            if (nodes.Length == 0)
            {
                var key = "appearance:" + ArchiveCharacterReferences.Normalize(app.Path) + "#unclassified";
                if (evidence.Count == 0) evidence.Add("Appearance has no supported body or face component declarations.");
                records[key] = new(Row(key, "appearances", "unclassified", label, app.Name, app.Path, "unresolved", 0, evidence[0]),
                    SearchNames(links, [app.Name]), [app.EntryId], [app.EntryId], [], [], links.Select(static link => link.Owner).ToArray(), evidence.ToArray(), app.Path);
                Account(app, "unresolved", evidence[0]);
                continue;
            }
            var customIds = resolver.ResolveCustomization(customization, evidence);
            if (customization.Length > 0) evidence.Add("Customization dependencies are retained. The preview applies supported base appearance; complete customization rendering is unavailable.");
            var components = new List<CharacterCatalogComponent>();
            var nodeIndex = 0;
            foreach (var node in nodes)
            {
                var resolved = resolver.Resolve(node.Name, node.Role);
                components.Add(new(node.Role, node.Name, resolved.Models, resolved.Context, ArchiveCharacterReferences.Scale(node), node.Attributes, resolved.Resolution));
                evidence.AddRange(resolved.Evidence);
                var referenceKey = $"reference:{app.EntryId}:{nodeIndex++}";
                coverage[referenceKey] = Row(referenceKey, "coverage", node.Role, node.Name, node.Name, app.Path,
                    resolved.Resolution, resolved.Models.Length, $"Authored {node.Role} reference: {node.Name}");
            }
            var bodyModels = components.Where(static component => component.Role == "body").SelectMany(static component => component.ModelEntryIds).Distinct().ToArray();
            var headModels = components.Where(static component => component.Role is "head" or "facial_detail").SelectMany(static component => component.ModelEntryIds).Distinct().ToArray();
            // An authored full body with no separate head is retained as one combined
            // appearance. This is descriptor evidence, not a fabricated head mesh.
            var combined = bodyModels.Length > 0 && (headModels.Length == 0 || bodyModels.Intersect(headModels).Any()
                || bodyModels.Any(id => resolver.HasEmbeddedFace(byId[id])));
            if (combined)
            {
                foreach (var model in bodyModels.Where(id => resolver.ModelRole(byId[id]) == "body")) embedded.Add(model);
                evidence.Add("Appearance uses a combined body/head mesh or has no resolved separate head. Body preview retains its embedded face; separate facial components remain independently discoverable.");
            }
            foreach (var group in components.GroupBy(static component => component.Role))
            {
                var role = group.Key;
                var primary = group.ToArray();
                var selected = components.Where(component => role == "body" ? component.Role is "body" or "head" or "facial_detail"
                    : role == "head" ? component.Role is "head" or "facial_detail" : component.Role == role).ToArray();
                if (role == "head" && selected.All(static component => component.ModelEntryIds.Count == 0) && combined)
                    selected = selected.Concat(components.Where(static component => component.Role == "body")).ToArray();
                var models = selected.SelectMany(static component => component.ModelEntryIds).Distinct().ToArray();
                var context = selected.SelectMany(static component => component.ContextEntryIds).Concat(customIds).Distinct().ToArray();
                var resolution = models.Length == 0 ? "unresolved" : selected.Any(static component => component.Resolution == "ambiguous") ? "ambiguous"
                    : selected.Any(static component => component.Resolution != "resolved") ? "inferred" : "resolved";
                var key = "appearance:" + ArchiveCharacterReferences.Normalize(app.Path) + "#" + role;
                var row = Row(key, "appearances", role, label, string.Join(" / ", primary.Select(static component => component.Name)),
                    app.Path, resolution, models.Length, "Authored appearance components and preserved variant context.", combined && (role == "body" || role == "head" && headModels.Length == 0));
                var family = models.Select(id => ArchiveCharacterReferences.BodyFamily(byId[id].Path)).FirstOrDefault(static family => family != "unknown");
                if (family is not null) row = row with { BodyFamily = family };
                var contextKey = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(key + "|" + string.Join('|', selected.Select(component =>
                    component.Name + ":" + component.Scale.ToString(System.Globalization.CultureInfo.InvariantCulture) + ":" + string.Join(',', component.ContextEntryIds))) + "|" + string.Join(',', customIds))));
                records[key] = new(row, SearchNames(links, nodes.Select(static node => node.Name).ToArray()),
                    models.Append(app.EntryId).Distinct().ToArray(), models.Concat(context).Append(app.EntryId).Distinct().ToArray(),
                    models.Select(id => "asset:" + ArchiveCharacterReferences.Normalize(byId[id].Path)).ToArray(), selected,
                    links.Select(static link => link.Owner).ToArray(), evidence.Distinct().ToArray(), app.Path, contextKey);
                foreach (var component in primary)
                {
                    var unclassified = component.ModelEntryIds.Where(id => resolver.ModelRole(byId[id]) == "unclassified").Distinct().ToArray();
                    var hasPrimary = component.ModelEntryIds.Any(id => resolver.ModelRole(byId[id]) == role);
                    // Inherit a declaration only for a single otherwise unclassified
                    // primary mesh. Other members of its assembly are dependencies.
                    if (unclassified.Length == 1 && !hasPrimary)
                    {
                        var model = unclassified[0];
                        if (!usedRoles.TryGetValue(model, out var roles)) usedRoles[model] = roles = [];
                        roles.Add(role);
                    }
                }
                foreach (var model in models)
                {
                    if (!uses.TryGetValue(model, out var keys)) uses[model] = keys = [];
                    keys.Add(key);
                }
            }
            Account(app, components.All(static component => component.Resolution == "resolved") ? "resolved" : "unresolved",
                evidence.Count > 0 ? string.Join(" ", evidence.Take(3)) : "Appearance body and face references resolved.");
        }

        foreach (var entry in candidates)
        {
            token.ThrowIfCancellationRequested();
            var path = ArchiveCharacterReferences.Normalize(entry.Path);
            if (!entries.TryGetValue(path, out var active) || active.EntryId != entry.EntryId)
            { Account(entry, "excluded", "Shadowed or unmounted source; active mount precedence applied."); continue; }
            if (entry.Extension == ".app_xml") continue;
            var role = ArchiveCharacterReferences.IsModel(entry) ? resolver.ModelRole(entry) : ArchiveCharacterReferences.Role(path);
            if (role == "unclassified" && usedRoles.TryGetValue(entry.EntryId, out var declaredRoles))
                role = declaredRoles.Order(StringComparer.Ordinal).First();
            if (role == "excluded") { Account(entry, "excluded", "Equipment or non-body component; retained only in its owning appearance dependencies."); continue; }
            if (ArchiveCharacterReferences.IsModel(entry))
            {
                var resolved = resolver.Resolve(path, role, entry);
                var key = "asset:" + path;
                var relatedKeys = uses.GetValueOrDefault(entry.EntryId)?.Order(StringComparer.Ordinal).ToArray() ?? [];
                var owners = relatedKeys.SelectMany(related => records[related].Characters).DistinctBy(static owner => owner.CharacterId).ToArray();
                var searchNames = relatedKeys.SelectMany(related => records[related].SearchNames).Append(entry.Name).Distinct().ToArray();
                var isEmbedded = embedded.Contains(entry.EntryId) || role == "body" && resolver.HasEmbeddedFace(entry);
                if (isEmbedded && role == "body") role = "whole_character";
                var row = Row(key, "assets", role, entry.Name, Path.GetFileNameWithoutExtension(entry.Name), entry.Path,
                    resolved.Resolution, 1, role == "unclassified" ? "Installed model awaits role classification; available through Unclassified." : "Installed model asset.", isEmbedded)
                    with { UsageCount = relatedKeys.Length };
                records[key] = new(row, searchNames, [entry.EntryId], resolved.Context.Append(entry.EntryId)
                    .Concat(relatedKeys.SelectMany(related => records[related].DirectIds).Where(id => byId[id].Extension == ".app_xml")).Distinct().ToArray(), relatedKeys,
                    [new(role, entry.Name, [entry.EntryId], resolved.Context, 1, new Dictionary<string, string>(), resolved.Resolution)],
                    owners, resolved.Evidence, ContextKey: key);
                Account(entry, row.Resolution, row.Evidence);
            }
            else
            {
                var resolved = resolver.Resolve(Path.GetFileNameWithoutExtension(entry.Name), role);
                Account(entry, resolved.Resolution, resolved.Models.Length > 0 ? "Descriptor links installed model assets."
                    : "Descriptor has no resolved body/face model. Accounted for as a reference, not a unique model asset.");
            }
        }
        // Resolve links after all physical assets exist. References that point at
        // excluded entries stay explicit instead of yielding dead navigation links.
        var allKeys = records.Keys.ToHashSet(StringComparer.Ordinal);
        var final = records.Values.Select(record => record with { RelatedKeys = record.RelatedKeys.Where(allKeys.Contains).ToArray() }).ToArray();
        progress?.Invoke(apps.Length, apps.Length, "Character catalogue ready");
        return new(Version, signature, final, coverage.Values.ToArray(), warnings.Distinct().ToArray());
    }
}
