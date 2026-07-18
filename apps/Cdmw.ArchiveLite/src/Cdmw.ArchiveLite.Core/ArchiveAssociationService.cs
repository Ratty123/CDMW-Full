using System.Collections.Concurrent;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveAssociationService
{
    private const int MaximumCanonicalResults = 256;
    private const int MaximumMatchesPerBasename = 32;
    private const long MaximumReferenceContainerBytes = 16L * 1024L * 1024L;

    private static readonly string[] FamilySuffixes =
    [
        ".prefabdata_xml", ".prefabdata.xml", ".pamlod_xml", ".pamlod.xml",
        ".pac_xml", ".pac.xml", ".pam_xml", ".pam.xml", ".app_xml", ".app.xml",
        ".paa_metabin", ".sockets.xml", ".motionblending", ".paschedulepath",
        ".pamlod", ".meshinfo", ".prefab", ".pappt", ".pamhc", ".pami",
        ".hkx", ".hkt", ".pac", ".pam", ".pabgb", ".pabgh", ".pabc",
        ".pabv", ".papr", ".pab", ".paa", ".paem", ".pae", ".paseqc",
        ".paseq", ".paschedule", ".pastage", ".seqmt", ".xml",
    ];

    private static readonly string[] TextureFamilySuffixes =
    [
        ".dds", "_d.dds", "_n.dds", "_m.dds", "_r.dds", "_s.dds", "_a.dds",
        "_ao.dds", "_orm.dds", "_mra.dds", "_albedo.dds", "_basecolor.dds",
        "_diffuse.dds", "_normal.dds", "_mask.dds", "_roughness.dds",
        "_metallic.dds", "_specular.dds", "_emissive.dds", "_opacity.dds",
    ];

    private static readonly HashSet<string> ReferenceContainerExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".pac", ".pam", ".pamlod", ".pac_xml", ".pam_xml", ".pamlod_xml",
        ".pami", ".app_xml", ".prefabdata_xml", ".prefab", ".pappt", ".pamhc",
        ".meshinfo", ".xml", ".json", ".material",
    };

    private static readonly Regex TextureVariantSuffix = new(
        @"(?:_(?:d|n|m|r|s|a|ao|orm|mra|albedo|basecolor|diffuse|normal|nrm|mask|roughness|metallic|specular|emissive|opacity))+$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant,
        TimeSpan.FromMilliseconds(250));

    private static readonly Regex AssetReferencePattern = new(
        @"(?<path>(?:[A-Za-z0-9_@%+\-.]+[\\/])*(?:[A-Za-z0-9_@%+\-.]+)\.(?:prefabdata_xml|prefabdata\.xml|pamlod_xml|pamlod\.xml|pac_xml|pac\.xml|pam_xml|pam\.xml|app_xml|app\.xml|paa_metabin|sockets\.xml|motionblending|paschedulepath|pamlod|meshinfo|prefab|pappt|pamhc|pami|paschedule|pastage|paseqc|paseq|seqmt|pabgb|pabgh|pabc|pabv|papr|paem|pac|pam|hkx|hkt|pab|paa|pae|dds|wem|bnk|xml|json))",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant,
        TimeSpan.FromSeconds(1));

    private readonly ArchiveSessionManager _sessions;
    private readonly NativeArchiveCore _native;
    private readonly ConcurrentDictionary<AssociationCacheKey, FindAssociatedAssetsResult> _completed = new();
    private readonly ConcurrentDictionary<AssociationCacheKey, ConcurrentDictionary<long, AssociatedAssetDto>> _learned = new();

    public ArchiveAssociationService(ArchiveSessionManager sessions, NativeArchiveCore native)
    {
        _sessions = sessions;
        _native = native;
    }

    public async Task<FindAssociatedAssetsResult> FindAsync(
        FindAssociatedAssetsRequest request,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = _sessions.GetRequired(request.SessionId);
        var source = session.EnrichEntry(session.Index.ReadEntry(request.EntryId));
        var maximumResults = Math.Clamp(request.MaximumResults, 1, MaximumCanonicalResults);
        var cacheKey = new AssociationCacheKey(session.Id, source.EntryId);

        if (_completed.TryGetValue(cacheKey, out var cached))
        {
            return BuildResponse(session.Id, source.EntryId, cached.Assets, maximumResults, 0, cached.Truncated);
        }

        if (TryReadLearned(cacheKey, out var learnedOnly) && learnedOnly.Count > 0)
        {
            return BuildResponse(session.Id, source.EntryId, learnedOnly, maximumResults, 0, false);
        }

        var discovered = new Dictionary<long, AssociatedAssetDto>();
        var parsedEntryIds = new HashSet<long>();
        var references = new Dictionary<string, ReferenceCandidate>(StringComparer.OrdinalIgnoreCase);
        var familyStem = GetFamilyStem(source.Path);
        var candidateBasenames = BuildCandidateBasenames(familyStem);

        foreach (var candidatePath in BuildExpectedVirtualPaths(source, candidateBasenames))
        {
            cancellationToken.ThrowIfCancellationRequested();
            foreach (var candidate in session.Index.FindEntriesByPath(candidatePath, 8)
                         .OrderByDescending(entry => ScoreCandidate(source, entry)))
            {
                AddCandidate(
                    session,
                    source,
                    candidate,
                    AssociationEvidence.ExactCompanion,
                    source.Name,
                    discovered);
            }
        }

        AddReferencesFromEntry(source, parsedEntryIds, references, cancellationToken);
        foreach (var companion in discovered.Values.Select(static item => item.Entry).ToArray())
        {
            AddReferencesFromEntry(companion, parsedEntryIds, references, cancellationToken);
        }
        ResolveExactReferences(session, source, references.Values, discovered, cancellationToken);

        var scannedBasenames = new HashSet<string>(candidateBasenames, StringComparer.OrdinalIgnoreCase);
        foreach (var reference in references.Values)
        {
            scannedBasenames.Add(reference.Basename);
        }

        long scannedEntries = 0;
        if (scannedBasenames.Count > 0)
        {
            var matches = await ScanByBasenameAsync(
                session,
                scannedBasenames,
                "1",
                publishProgress,
                cancellationToken).ConfigureAwait(false);
            scannedEntries += session.Index.EntryCount;
            ApplyScanMatches(session, source, matches, references.Values, discovered);
        }

        foreach (var companion in discovered.Values.Select(static item => item.Entry).ToArray())
        {
            AddReferencesFromEntry(companion, parsedEntryIds, references, cancellationToken);
        }
        ResolveExactReferences(session, source, references.Values, discovered, cancellationToken);

        var secondPassBasenames = references.Values
            .Select(static reference => reference.Basename)
            .Where(basename => !scannedBasenames.Contains(basename))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (secondPassBasenames.Count > 0)
        {
            var matches = await ScanByBasenameAsync(
                session,
                secondPassBasenames,
                "2",
                publishProgress,
                cancellationToken).ConfigureAwait(false);
            scannedEntries += session.Index.EntryCount;
            ApplyScanMatches(session, source, matches, references.Values, discovered);
        }

        cancellationToken.ThrowIfCancellationRequested();
        var ordered = discovered.Values
            .OrderBy(static asset => asset.Category)
            .ThenBy(static asset => asset.Evidence)
            .ThenBy(asset => string.Equals(asset.Entry.SourcePamt, source.SourcePamt, StringComparison.OrdinalIgnoreCase) ? 0 : 1)
            .ThenBy(static asset => asset.Entry.Path, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        var canonicalTruncated = ordered.Length > MaximumCanonicalResults;
        var canonicalAssets = ordered.Take(MaximumCanonicalResults).ToArray();
        var canonical = new FindAssociatedAssetsResult(
            session.Id,
            source.EntryId,
            canonicalAssets,
            scannedEntries,
            canonicalTruncated);
        _completed[cacheKey] = canonical;
        LearnFamily(session.Id, source, canonicalAssets);
        return BuildResponse(
            session.Id,
            source.EntryId,
            canonicalAssets,
            maximumResults,
            scannedEntries,
            canonicalTruncated);
    }

    private void AddReferencesFromEntry(
        ArchiveEntryDto entry,
        ISet<long> parsedEntryIds,
        IDictionary<string, ReferenceCandidate> references,
        CancellationToken cancellationToken)
    {
        if (!parsedEntryIds.Add(entry.EntryId) || !IsReferenceContainer(entry))
        {
            return;
        }

        cancellationToken.ThrowIfCancellationRequested();
        try
        {
            var decoded = _native.Decode(entry);
            cancellationToken.ThrowIfCancellationRequested();
            var searchable = TextDecoding.LooksTextual(decoded.Bytes)
                ? TextDecoding.Decode(decoded.Bytes)
                : BuildPrintableText(decoded.Bytes);
            foreach (Match match in AssetReferencePattern.Matches(searchable))
            {
                cancellationToken.ThrowIfCancellationRequested();
                var normalized = NormalizeReference(match.Groups["path"].Value);
                if (string.IsNullOrWhiteSpace(normalized)
                    || string.Equals(normalized, NormalizeReference(entry.Path), StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                references.TryAdd(
                    normalized,
                    new ReferenceCandidate(normalized, GetBasename(normalized), entry.Name));
            }
        }
        catch (Exception exception) when (exception is NativeArchiveException or InvalidDataException or DecoderFallbackException)
        {
            // Relationship hints are best-effort; same-family discovery remains available.
        }
    }

    private static async Task<IReadOnlyDictionary<string, IReadOnlyList<ArchiveEntryDto>>> ScanByBasenameAsync(
        ArchiveSession session,
        IReadOnlySet<string> requestedBasenames,
        string pass,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        var matches = new Dictionary<string, List<ArchiveEntryDto>>(StringComparer.OrdinalIgnoreCase);
        var total = session.Index.EntryCount;
        if (publishProgress is not null)
        {
            await publishProgress(new ProgressUpdate(0, total, "association_scan", pass)).ConfigureAwait(false);
        }

        for (long entryId = 0; entryId < total; entryId++)
        {
            if ((entryId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (publishProgress is not null)
                {
                    await publishProgress(new ProgressUpdate(entryId, total, "association_scan", pass)).ConfigureAwait(false);
                }
            }

            var entry = session.Index.ReadEntry(entryId);
            var basename = GetBasename(entry.Path);
            if (!requestedBasenames.Contains(basename))
            {
                continue;
            }

            if (!matches.TryGetValue(basename, out var candidates))
            {
                candidates = [];
                matches.Add(basename, candidates);
            }
            if (candidates.Count < MaximumMatchesPerBasename)
            {
                candidates.Add(entry);
            }
        }

        cancellationToken.ThrowIfCancellationRequested();
        if (publishProgress is not null)
        {
            await publishProgress(new ProgressUpdate(total, total, "association_scan", pass)).ConfigureAwait(false);
        }
        return matches.ToDictionary(
            static pair => pair.Key,
            static pair => (IReadOnlyList<ArchiveEntryDto>)pair.Value,
            StringComparer.OrdinalIgnoreCase);
    }

    private static void ApplyScanMatches(
        ArchiveSession session,
        ArchiveEntryDto source,
        IReadOnlyDictionary<string, IReadOnlyList<ArchiveEntryDto>> matches,
        IEnumerable<ReferenceCandidate> references,
        IDictionary<long, AssociatedAssetDto> discovered)
    {
        var referencesByBasename = references
            .GroupBy(static reference => reference.Basename, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(static group => group.Key, static group => group.First(), StringComparer.OrdinalIgnoreCase);
        foreach (var (basename, candidates) in matches)
        {
            var isExplicit = referencesByBasename.TryGetValue(basename, out var reference);
            var evidence = isExplicit ? AssociationEvidence.ExplicitReference : AssociationEvidence.SameStem;
            var evidenceSource = reference?.SourceName ?? source.Name;
            var take = isExplicit ? 8 : 4;
            foreach (var candidate in candidates
                         .OrderByDescending(entry => ScoreCandidate(source, entry))
                         .Take(take))
            {
                AddCandidate(session, source, candidate, evidence, evidenceSource, discovered);
            }
        }
    }

    private static void ResolveExactReferences(
        ArchiveSession session,
        ArchiveEntryDto source,
        IEnumerable<ReferenceCandidate> references,
        IDictionary<long, AssociatedAssetDto> discovered,
        CancellationToken cancellationToken)
    {
        foreach (var reference in references)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!reference.Path.Contains('/'))
            {
                continue;
            }
            foreach (var candidate in session.Index.FindEntriesByPath(reference.Path, 16)
                         .OrderByDescending(entry => ScoreCandidate(source, entry))
                         .Take(8))
            {
                AddCandidate(
                    session,
                    source,
                    candidate,
                    AssociationEvidence.ExplicitReference,
                    reference.SourceName,
                    discovered);
            }
        }
    }

    private static void AddCandidate(
        ArchiveSession session,
        ArchiveEntryDto source,
        ArchiveEntryDto candidate,
        AssociationEvidence evidence,
        string evidenceSource,
        IDictionary<long, AssociatedAssetDto> discovered)
    {
        if (candidate.EntryId == source.EntryId)
        {
            return;
        }

        var associated = new AssociatedAssetDto(
            session.EnrichEntry(candidate),
            ClassifyCategory(candidate),
            evidence,
            string.IsNullOrWhiteSpace(evidenceSource) ? source.Name : evidenceSource);
        if (!discovered.TryGetValue(candidate.EntryId, out var current) || evidence < current.Evidence)
        {
            discovered[candidate.EntryId] = associated;
        }
    }

    private void LearnFamily(string sessionId, ArchiveEntryDto source, IReadOnlyList<AssociatedAssetDto> assets)
    {
        var members = new[] { source }
            .Concat(assets.Select(static asset => asset.Entry))
            .DistinctBy(static entry => entry.EntryId)
            .Take(64)
            .ToArray();
        foreach (var owner in members)
        {
            var map = _learned.GetOrAdd(
                new AssociationCacheKey(sessionId, owner.EntryId),
                static _ => new ConcurrentDictionary<long, AssociatedAssetDto>());
            foreach (var target in members)
            {
                if (target.EntryId == owner.EntryId)
                {
                    continue;
                }
                var candidate = new AssociatedAssetDto(
                    target,
                    ClassifyCategory(target),
                    AssociationEvidence.CachedFamily,
                    source.Name);
                map.AddOrUpdate(
                    target.EntryId,
                    candidate,
                    (_, current) => candidate.Evidence < current.Evidence ? candidate : current);
            }
        }
    }

    private bool TryReadLearned(AssociationCacheKey cacheKey, out IReadOnlyList<AssociatedAssetDto> assets)
    {
        if (_learned.TryGetValue(cacheKey, out var learned))
        {
            assets = learned.Values
                .OrderBy(static asset => asset.Category)
                .ThenBy(static asset => asset.Entry.Path, StringComparer.OrdinalIgnoreCase)
                .ToArray();
            return true;
        }
        assets = [];
        return false;
    }

    private static FindAssociatedAssetsResult BuildResponse(
        string sessionId,
        long entryId,
        IReadOnlyList<AssociatedAssetDto> assets,
        int maximumResults,
        long scannedEntries,
        bool alreadyTruncated)
    {
        var truncated = alreadyTruncated || assets.Count > maximumResults;
        return new FindAssociatedAssetsResult(
            sessionId,
            entryId,
            assets.Take(maximumResults).ToArray(),
            scannedEntries,
            truncated);
    }

    private static HashSet<string> BuildCandidateBasenames(string stem)
    {
        var basenames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(stem))
        {
            return basenames;
        }
        foreach (var suffix in FamilySuffixes)
        {
            basenames.Add(stem + suffix);
        }
        foreach (var suffix in TextureFamilySuffixes)
        {
            basenames.Add(stem + suffix);
        }
        return basenames;
    }

    private static IReadOnlySet<string> BuildExpectedVirtualPaths(
        ArchiveEntryDto source,
        IReadOnlySet<string> candidateBasenames)
    {
        var directories = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            GetParent(source.Path),
        };
        AddParallelDirectory(directories, GetParent(source.Path), "model", "modelproperty");
        AddParallelDirectory(directories, GetParent(source.Path), "modelproperty", "model");
        AddParallelDirectory(directories, GetParent(source.Path), "texture", "model");
        AddParallelDirectory(directories, GetParent(source.Path), "texture", "modelproperty");
        AddParallelDirectory(directories, GetParent(source.Path), "model", "texture");
        AddParallelDirectory(directories, GetParent(source.Path), "modelproperty", "texture");

        var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var directory in directories)
        {
            foreach (var basename in candidateBasenames)
            {
                paths.Add(string.IsNullOrWhiteSpace(directory) ? basename : $"{directory}/{basename}");
            }
        }
        return paths;
    }

    private static void AddParallelDirectory(ISet<string> directories, string directory, string from, string to)
    {
        var marker = $"/{from}/";
        if (directory.Contains(marker, StringComparison.OrdinalIgnoreCase))
        {
            directories.Add(directory.Replace(marker, $"/{to}/", StringComparison.OrdinalIgnoreCase));
        }
        if (directory.EndsWith($"/{from}", StringComparison.OrdinalIgnoreCase))
        {
            directories.Add(directory[..^(from.Length)] + to);
        }
    }

    private static int ScoreCandidate(ArchiveEntryDto source, ArchiveEntryDto candidate)
    {
        var score = string.Equals(source.SourcePamt, candidate.SourcePamt, StringComparison.OrdinalIgnoreCase) ? 100 : 0;
        if (string.Equals(GetParent(source.Path), GetParent(candidate.Path), StringComparison.OrdinalIgnoreCase))
        {
            score += 60;
        }
        score += CommonPrefixSegments(source.Path, candidate.Path) * 8;
        score -= Math.Min(candidate.Path.Length, 200) / 20;
        return score;
    }

    private static int CommonPrefixSegments(string left, string right)
    {
        var leftParts = left.Replace('\\', '/').Split('/', StringSplitOptions.RemoveEmptyEntries);
        var rightParts = right.Replace('\\', '/').Split('/', StringSplitOptions.RemoveEmptyEntries);
        var count = 0;
        while (count < leftParts.Length && count < rightParts.Length
               && string.Equals(leftParts[count], rightParts[count], StringComparison.OrdinalIgnoreCase))
        {
            count++;
        }
        return count;
    }

    private static AssociatedAssetCategory ClassifyCategory(ArchiveEntryDto entry)
    {
        var extension = entry.Extension.ToLowerInvariant();
        var basename = GetBasename(entry.Path);
        var path = entry.Path.Replace('\\', '/').ToLowerInvariant();
        if (extension is ".pac" or ".pam" or ".pamlod") return AssociatedAssetCategory.Model;
        if (IsMaterialSidecar(extension, basename) || extension == ".pamhc") return AssociatedAssetCategory.Material;
        if (extension is ".dds" or ".seqmt") return AssociatedAssetCategory.Texture;
        if (extension is ".hkx" or ".hkt"
            && (path.Contains("physics", StringComparison.Ordinal) || path.Contains("ragdoll", StringComparison.Ordinal)))
        {
            return AssociatedAssetCategory.Physics;
        }
        if (extension == ".meshinfo") return AssociatedAssetCategory.MeshMetadata;
        if (extension is ".prefab" or ".prefabdata_xml" or ".app_xml" or ".pappt"
            || basename.EndsWith(".prefabdata.xml", StringComparison.OrdinalIgnoreCase))
        {
            return AssociatedAssetCategory.PrefabMetadata;
        }
        if (extension is ".pab" or ".pabc" or ".pabv" or ".pabgb" or ".pabgh" or ".papr")
        {
            return AssociatedAssetCategory.SkeletonRig;
        }
        if (extension is ".hkx" or ".hkt" or ".paa" or ".paa_metabin" or ".pae" or ".paem"
            or ".motionblending" or ".paseq" or ".paseqc" or ".paschedule" or ".paschedulepath" or ".pastage")
        {
            return AssociatedAssetCategory.AnimationMotion;
        }
        if (entry.Role is ArchiveEntryRole.Audio or ArchiveEntryRole.Video) return AssociatedAssetCategory.AudioVideo;
        if (entry.Role == ArchiveEntryRole.UserInterface) return AssociatedAssetCategory.UserInterface;
        return AssociatedAssetCategory.Other;
    }

    private static bool IsMaterialSidecar(string extension, string basename) =>
        extension is ".pami" or ".pac_xml" or ".pam_xml" or ".pamlod_xml"
        || basename.EndsWith(".pac.xml", StringComparison.OrdinalIgnoreCase)
        || basename.EndsWith(".pam.xml", StringComparison.OrdinalIgnoreCase)
        || basename.EndsWith(".pamlod.xml", StringComparison.OrdinalIgnoreCase);

    private static bool IsReferenceContainer(ArchiveEntryDto entry) =>
        entry.OriginalSize is > 0 and <= MaximumReferenceContainerBytes
        && (ReferenceContainerExtensions.Contains(entry.Extension)
            || entry.Role is ArchiveEntryRole.Text or ArchiveEntryRole.Metadata);

    private static string BuildPrintableText(byte[] bytes)
    {
        var characters = new char[bytes.Length];
        for (var index = 0; index < bytes.Length; index++)
        {
            var value = bytes[index];
            characters[index] = value is >= 0x20 and <= 0x7E ? (char)value : ' ';
        }
        return new string(characters);
    }

    private static string NormalizeReference(string value)
    {
        var normalized = WebUtility.HtmlDecode(value ?? string.Empty)
            .Replace('\\', '/')
            .Trim().Trim('"', '\'', '<', '>', '(', ')');
        if (normalized.Contains("://", StringComparison.Ordinal) || normalized.Contains(':', StringComparison.Ordinal))
        {
            return string.Empty;
        }

        var parts = new List<string>();
        foreach (var part in normalized.Split('/', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (part == ".")
            {
                continue;
            }
            if (part == "..")
            {
                if (parts.Count > 0) parts.RemoveAt(parts.Count - 1);
                continue;
            }
            parts.Add(part);
        }
        return string.Join('/', parts).Trim('/').ToLowerInvariant();
    }

    private static string GetFamilyStem(string path)
    {
        var basename = GetBasename(path);
        foreach (var suffix in FamilySuffixes.OrderByDescending(static value => value.Length))
        {
            if (basename.EndsWith(suffix, StringComparison.OrdinalIgnoreCase))
            {
                return basename[..^suffix.Length];
            }
        }

        var stem = Path.GetFileNameWithoutExtension(basename).ToLowerInvariant();
        return TextureVariantSuffix.Replace(stem, string.Empty);
    }

    private static string GetParent(string path)
    {
        var normalized = path.Replace('\\', '/').Trim('/');
        var separator = normalized.LastIndexOf('/');
        return separator <= 0 ? string.Empty : normalized[..separator];
    }

    private static string GetBasename(string path)
    {
        var normalized = path.Replace('\\', '/').Trim('/');
        var separator = normalized.LastIndexOf('/');
        return (separator < 0 ? normalized : normalized[(separator + 1)..]).ToLowerInvariant();
    }

    private readonly record struct AssociationCacheKey(string SessionId, long EntryId);
    private sealed record ReferenceCandidate(string Path, string Basename, string SourceName);
}
