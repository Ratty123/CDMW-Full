using System.Text.RegularExpressions;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveQueryService(ArchiveSessionManager sessions)
{
    private const int MaximumBoundedEntryIds = 4096;
    public Task<ArchiveQueryHandle> CreateAsync(
        ArchiveQuery query,
        long generation,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ArgumentNullException.ThrowIfNull(query);
        var session = sessions.GetRequired(query.SessionId);
        return Task.Run(
            () => Compile(session, query, generation, cancellationToken, progress),
            CancellationToken.None);
    }

    public ArchivePage FetchPage(string sessionId, FetchPageRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(sessionId);
        var compiled = session.GetRequiredQuery(request.QueryId);
        var pageStart = Math.Max(0, request.PageStart);
        var pageSize = Math.Clamp(request.PageSize, 1, WorkerProtocol.MaximumPageSize);
        var available = Math.Max(0L, compiled.EntryIds.LongLength - pageStart);
        var count = (int)Math.Min(pageSize, available);
        var rows = new ArchiveEntryDto[count];
        for (var index = 0; index < count; index++)
        {
            rows[index] = session.ReadEntry(compiled.EntryIds[pageStart + index]);
        }
        return new ArchivePage(
            session.Id,
            compiled.QueryId,
            compiled.Generation,
            compiled.EntryIds.LongLength,
            pageStart,
            rows);
    }

    public ArchiveChildrenResult FetchChildren(
        string sessionId,
        ArchiveChildrenRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(sessionId);
        var compiled = string.IsNullOrWhiteSpace(request.QueryId)
            ? null
            : session.GetRequiredQuery(request.QueryId);
        var limit = Math.Clamp(request.Limit, 1, WorkerProtocol.MaximumPageSize);
        var offset = Math.Max(0, request.Offset);
        var parent = NormalizeFolder(request.ParentPath);
        var folders = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        var entries = new List<(string Path, long EntryId)>();
        var entryCount = compiled?.EntryIds.LongLength ?? session.Index.EntryCount;
        for (long entryIndex = 0; entryIndex < entryCount; entryIndex++)
        {
            if ((entryIndex & 0xFFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }
            var entryId = compiled is null ? entryIndex : compiled.EntryIds[entryIndex];
            var entry = session.ReadEntry(entryId);
            if (!string.IsNullOrWhiteSpace(request.Category) &&
                !entry.Category.Equals(request.Category, StringComparison.OrdinalIgnoreCase) &&
                !entry.Role.ToString().Equals(request.Category, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            var hierarchyPath = request.IncludePackageRoot
                ? StructurePath(entry)
                : entry.Path;
            if (!hierarchyPath.StartsWith(parent, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            var relative = hierarchyPath[parent.Length..].TrimStart('/');
            if (relative.Length == 0)
            {
                continue;
            }
            var separator = relative.IndexOf('/');
            if (separator >= 0)
            {
                var name = relative[..separator];
                var full = string.IsNullOrEmpty(parent) ? name : $"{parent.TrimEnd('/')}/{name}";
                folders[full] = folders.GetValueOrDefault(full) + 1;
            }
            else
            {
                entries.Add((entry.Path, entry.EntryId));
            }
        }

        var folderNodes = folders
            .OrderBy(static pair => pair.Key, StringComparer.OrdinalIgnoreCase)
            .Select(static pair => new ArchiveChildNode(pair.Key, Path.GetFileName(pair.Key), true, pair.Value))
            .ToArray();
        entries.Sort(static (left, right) =>
        {
            var compared = StringComparer.OrdinalIgnoreCase.Compare(left.Path, right.Path);
            return compared != 0 ? compared : left.EntryId.CompareTo(right.EntryId);
        });
        var totalChildren = (long)folderNodes.Length + entries.Count;
        var pageNodes = new List<ArchiveChildNode>(limit);
        for (long childIndex = offset; childIndex < totalChildren && pageNodes.Count < limit; childIndex++)
        {
            if (childIndex < folderNodes.Length)
            {
                pageNodes.Add(folderNodes[childIndex]);
                continue;
            }
            var direct = entries[checked((int)(childIndex - folderNodes.Length))];
            var entry = session.ReadEntry(direct.EntryId);
            pageNodes.Add(new ArchiveChildNode(
                $"entry:{entry.EntryId}",
                entry.Name,
                false,
                1,
                entry));
        }
        var consumed = (long)offset + pageNodes.Count;
        cancellationToken.ThrowIfCancellationRequested();
        var nextOffset = consumed < totalChildren ? checked((int)consumed) : (int?)null;
        return new ArchiveChildrenResult(
            session.Id,
            request.QueryId,
            pageNodes,
            nextOffset is not null,
            offset,
            totalChildren,
            nextOffset);
    }

    public IReadOnlyList<long> GetEntryIds(string sessionId, string queryId)
    {
        var session = sessions.GetRequired(sessionId);
        return session.GetRequiredQuery(queryId).EntryIds;
    }

    private static ArchiveQueryHandle Compile(
        ArchiveSession session,
        ArchiveQuery query,
        long generation,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var requestedIds = query.EntryIds?.Distinct().ToArray();
        if (requestedIds is { Length: > MaximumBoundedEntryIds })
        {
            throw new InvalidDataException($"Archive queries may contain at most {MaximumBoundedEntryIds} bounded entry ids.");
        }
        var candidates = query.SortActive ? new List<QueryCandidate>() : null;
        var unsortedIds = query.SortActive ? null : new List<long>();
        var total = requestedIds?.LongLength ?? session.Index.EntryCount;
        Publish(progress, new ProgressUpdate(0, total, "query_scan"));
        for (long candidateIndex = 0; candidateIndex < total; candidateIndex++)
        {
            if ((candidateIndex & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                Publish(progress, new ProgressUpdate(candidateIndex, total, "query_scan"));
            }
            var entryId = requestedIds is null ? candidateIndex : requestedIds[candidateIndex];
            if (entryId < 0 || entryId >= session.Index.EntryCount)
            {
                continue;
            }
            var entry = session.ReadEntry(entryId);
            if (!Matches(entry, query))
            {
                continue;
            }
            if (candidates is not null)
            {
                candidates.Add(QueryCandidate.Create(entry, query.SortField));
            }
            else
            {
                unsortedIds!.Add(entry.EntryId);
            }
        }

        cancellationToken.ThrowIfCancellationRequested();
        long[] ids;
        if (candidates is not null)
        {
            candidates.Sort((left, right) => CompareCandidates(left, right, query.SortField, query.SortDescending));
            ids = candidates.Select(static item => item.EntryId).ToArray();
        }
        else
        {
            ids = unsortedIds!.ToArray();
        }
        var queryId = Guid.NewGuid().ToString("N");
        session.StoreQuery(new CompiledArchiveQuery(queryId, generation, query, ids));
        Publish(progress, new ProgressUpdate(total, total, "query_complete"));
        return new ArchiveQueryHandle(session.Id, queryId, generation, ids.LongLength);
    }

    private static bool Matches(ArchiveEntryDto entry, ArchiveQuery query)
    {
        if (!MatchesAnyTextPattern(entry, query.IncludeText))
        {
            return false;
        }
        if (!string.IsNullOrWhiteSpace(query.ExcludeText) && MatchesAnyTextPattern(entry, query.ExcludeText))
        {
            return false;
        }
        if (query.Extensions is { Count: > 0 } &&
            !query.Extensions.Any(value => MatchesExtension(entry.Extension, value)))
        {
            return false;
        }
        if (query.Packages is { Count: > 0 } &&
            !query.Packages.Any(value => MatchesPackage(entry, value)))
        {
            return false;
        }
        if (!string.IsNullOrWhiteSpace(query.Folder))
        {
            var folder = NormalizeFolder(query.Folder);
            if (!StructurePath(entry).StartsWith(folder, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
        }
        if (query.Roles is { Count: > 0 } && !query.Roles.Contains(entry.Role))
        {
            return false;
        }
        if (query.TechnicalSuffixes is { Count: > 0 } &&
            query.TechnicalSuffixes.Any(pattern => MatchesTextPattern(entry, pattern)))
        {
            return false;
        }
        if (query.MinimumSize is { } minimum && entry.OriginalSize < minimum)
        {
            return false;
        }
        if (query.PreviewableOnly && !entry.IsPreviewable)
        {
            return false;
        }
        return !query.ActiveOverridesOnly || entry.IsActiveOverride;
    }

    private static bool MatchesAnyTextPattern(ArchiveEntryDto entry, string? filter)
    {
        if (string.IsNullOrWhiteSpace(filter))
        {
            return true;
        }
        return filter
            .Split([';', ',', '\r', '\n'], StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
            .Any(pattern => MatchesTextPattern(entry, pattern));
    }

    private static bool MatchesTextPattern(ArchiveEntryDto entry, string filter)
    {
        var text = filter.Trim();
        if (!text.ContainsAny(['*', '?', '[']))
        {
            return entry.Path.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                entry.Name.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                entry.KnownName.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                entry.ExactName.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                entry.NameEvidence.Contains(text, StringComparison.OrdinalIgnoreCase);
        }
        var pattern = "^" + Regex.Escape(text).Replace("\\*", ".*").Replace("\\?", ".") + "$";
        return Regex.IsMatch(entry.Path, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250)) ||
            Regex.IsMatch(entry.Name, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250)) ||
            Regex.IsMatch(entry.KnownName, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250));
    }

    private static bool MatchesPackage(ArchiveEntryDto entry, string candidate)
    {
        var text = candidate.Trim();
        if (text.Length == 0)
        {
            return true;
        }
        if (!text.ContainsAny(['*', '?', '[']))
        {
            return entry.Package.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                entry.SourcePamt.Contains(text, StringComparison.OrdinalIgnoreCase);
        }
        var pattern = "^" + Regex.Escape(text).Replace("\\*", ".*").Replace("\\?", ".") + "$";
        return Regex.IsMatch(entry.Package, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250)) ||
            Regex.IsMatch(entry.SourcePamt, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250));
    }

    private static bool MatchesExtension(string extension, string candidate)
    {
        var normalized = candidate.Trim().ToLowerInvariant();
        if (normalized is "*" or ".*" or "all")
        {
            return true;
        }
        if (!normalized.StartsWith('.'))
        {
            normalized = "." + normalized;
        }
        return extension.Equals(normalized, StringComparison.OrdinalIgnoreCase);
    }

    private static int CompareCandidates(
        QueryCandidate left,
        QueryCandidate right,
        ArchiveSortField field,
        bool descending)
    {
        var result = CompareCandidateValues(left, right, field);
        if (result != 0)
        {
            return descending ? -result : result;
        }
        return left.EntryId.CompareTo(right.EntryId);
    }

    private static int CompareCandidateValues(QueryCandidate left, QueryCandidate right, ArchiveSortField field)
    {
        var result = field switch
        {
            ArchiveSortField.OriginalSize or ArchiveSortField.StoredSize =>
                CompareNumbers(left.PrimaryNumber, right.PrimaryNumber, left.SecondaryNumber, right.SecondaryNumber),
            ArchiveSortField.Compression =>
                CompareCompression(left, right),
            _ => CompareNatural(left.PrimaryText, right.PrimaryText),
        };
        if (result != 0) return result;
        result = CompareNatural(left.Path, right.Path);
        if (result != 0) return result;
        result = CompareNatural(left.Package, right.Package);
        if (result != 0) return result;
        result = left.PazIndex.CompareTo(right.PazIndex);
        if (result != 0) return result;
        result = left.ArchiveOffset.CompareTo(right.ArchiveOffset);
        if (result != 0) return result;
        result = left.OriginalSize.CompareTo(right.OriginalSize);
        if (result != 0) return result;
        return left.StoredSize.CompareTo(right.StoredSize);
    }

    private static int CompareNumbers(long left, long right, long leftSecondary, long rightSecondary)
    {
        var result = left.CompareTo(right);
        return result != 0 ? result : leftSecondary.CompareTo(rightSecondary);
    }

    private static int CompareCompression(QueryCandidate left, QueryCandidate right)
    {
        var result = CompareNatural(left.PrimaryText, right.PrimaryText);
        if (result != 0) return result;
        result = left.PrimaryNumber.CompareTo(right.PrimaryNumber);
        return result != 0 ? result : left.SecondaryNumber.CompareTo(right.SecondaryNumber);
    }

    private static int CompareNatural(string left, string right)
    {
        var leftIndex = 0;
        var rightIndex = 0;
        while (leftIndex < left.Length && rightIndex < right.Length)
        {
            var leftDigit = char.IsDigit(left[leftIndex]);
            var rightDigit = char.IsDigit(right[rightIndex]);
            if (leftDigit != rightDigit)
            {
                return leftDigit ? -1 : 1;
            }
            var leftEnd = leftIndex + 1;
            while (leftEnd < left.Length && char.IsDigit(left[leftEnd]) == leftDigit) leftEnd++;
            var rightEnd = rightIndex + 1;
            while (rightEnd < right.Length && char.IsDigit(right[rightEnd]) == rightDigit) rightEnd++;
            int result;
            if (leftDigit)
            {
                var leftSignificant = leftIndex;
                while (leftSignificant < leftEnd - 1 && left[leftSignificant] == '0') leftSignificant++;
                var rightSignificant = rightIndex;
                while (rightSignificant < rightEnd - 1 && right[rightSignificant] == '0') rightSignificant++;
                result = (leftEnd - leftSignificant).CompareTo(rightEnd - rightSignificant);
                if (result == 0)
                {
                    result = left.AsSpan(leftSignificant, leftEnd - leftSignificant)
                        .SequenceCompareTo(right.AsSpan(rightSignificant, rightEnd - rightSignificant));
                }
                if (result == 0)
                {
                    result = left.AsSpan(leftIndex, leftEnd - leftIndex)
                        .SequenceCompareTo(right.AsSpan(rightIndex, rightEnd - rightIndex));
                }
            }
            else
            {
                result = left.AsSpan(leftIndex, leftEnd - leftIndex)
                    .SequenceCompareTo(right.AsSpan(rightIndex, rightEnd - rightIndex));
            }
            if (result != 0) return result;
            leftIndex = leftEnd;
            rightIndex = rightEnd;
        }
        return (left.Length - leftIndex).CompareTo(right.Length - rightIndex);
    }

    private static string NaturalText(string? value) =>
        (value ?? string.Empty).Replace('\\', '/').Trim().ToLowerInvariant();

    private static string CompressionLabel(int compressionType) => compressionType switch
    {
        0 => "None",
        1 => "Partial",
        2 => "LZ4",
        3 => "Zlib",
        4 => "QuickLZ",
        _ => compressionType.ToString(System.Globalization.CultureInfo.InvariantCulture),
    };

    private static readonly HashSet<string> BrowserImageExtensions = new(StringComparer.Ordinal)
    {
        ".bmp", ".dds", ".gif", ".hdr", ".jpeg", ".jpg", ".png", ".tga", ".tif", ".tiff", ".webp",
    };

    private static readonly HashSet<string> BrowserAudioExtensions = new(StringComparer.Ordinal)
    {
        ".mp3", ".ogg", ".wem", ".wav",
    };

    private static readonly HashSet<string> BrowserVideoExtensions = new(StringComparer.Ordinal)
    {
        ".bk2", ".mp4",
    };

    private static readonly HashSet<string> BrowserTextExtensions = new(StringComparer.Ordinal)
    {
        ".bnk", ".cfg", ".css", ".csv", ".dae", ".html", ".gltf", ".h", ".hpp", ".ini", ".json",
        ".log", ".lua", ".material", ".mtl", ".obj", ".paloc", ".app_xml", ".pami", ".pac_xml",
        ".pam_xml", ".pamlod_xml", ".prefabdata_xml", ".shader", ".thtml", ".txt", ".xml", ".yaml", ".yml",
    };

    private static readonly HashSet<string> BrowserAnimationExtensions = new(StringComparer.Ordinal)
    {
        ".paa", ".motionblending", ".pae", ".paem", ".papr", ".paseq", ".paseqc", ".paschedule",
        ".paschedulepath", ".pastage",
    };

    private static readonly HashSet<string> BrowserModelExtensions = new(StringComparer.Ordinal)
    {
        ".pac", ".pam", ".pamlod", ".obj", ".fbx", ".dae", ".gltf", ".glb", ".mesh", ".mdl", ".model",
        ".pat", ".patx",
    };

    private static string RoleDisplayText(ArchiveEntryDto entry)
    {
        var extension = entry.Extension.ToLowerInvariant();
        var path = entry.Path.Replace('\\', '/').ToLowerInvariant();
        var basename = path[(path.LastIndexOf('/') + 1)..];
        string role;
        if (BrowserImageExtensions.Contains(extension))
        {
            role = "Texture";
        }
        else if (extension is ".pami" or ".pac_xml" or ".pam_xml" or ".pamlod_xml" ||
                 extension == ".xml" &&
                 (basename.EndsWith(".pac.xml", StringComparison.Ordinal) ||
                  basename.EndsWith(".pam.xml", StringComparison.Ordinal) ||
                  basename.EndsWith(".pamlod.xml", StringComparison.Ordinal)))
        {
            role = "Material";
        }
        else if (extension is ".hkx" or ".hkt")
        {
            role = path.Contains("meshphysics", StringComparison.Ordinal) ||
                path.Contains("havokphysics", StringComparison.Ordinal) ||
                path.Contains("ragdoll", StringComparison.Ordinal) ||
                path.Contains("physics", StringComparison.Ordinal) ? "Physics" : "HKX";
        }
        else if (extension == ".paa_metabin")
        {
            role = "Animation Metadata";
        }
        else if (BrowserAnimationExtensions.Contains(extension))
        {
            role = "Animation";
        }
        else if (extension == ".pab")
        {
            role = "Skeleton / Rig";
        }
        else if (extension is ".prefab" or ".prefabdata_xml" or ".prefabdata.xml" or ".pappt")
        {
            role = "Prefab";
        }
        else if (extension == ".pamhc")
        {
            role = "Model Property Metadata";
        }
        else if (extension == ".paccd")
        {
            role = "Character Customization";
        }
        else if (extension == ".seqmt")
        {
            role = "Sequence Texture Metadata";
        }
        else if (BrowserAudioExtensions.Contains(extension))
        {
            role = "Audio";
        }
        else if (BrowserVideoExtensions.Contains(extension))
        {
            role = "Video";
        }
        else if (BrowserTextExtensions.Contains(extension) ||
                 extension is ".meshinfo" or ".motionblending" or ".paa_metabin" or ".prefab" or ".pappt" or ".pamhc" or ".paccd" or ".seqmt")
        {
            role = IsUiPath(path) ? "UI" : "Metadata";
        }
        else if (BrowserModelExtensions.Contains(extension))
        {
            role = "Mesh";
        }
        else
        {
            role = IsUiPath(path) ? "UI" : "Unknown";
        }
        return $"{role} {extension}".Trim();
    }

    private static bool IsUiPath(string normalizedPath) =>
        normalizedPath.Contains("/ui", StringComparison.Ordinal) || normalizedPath.StartsWith("ui/", StringComparison.Ordinal);

    private static string NormalizeFolder(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }
        return value.Replace('\\', '/').Trim('/') + "/";
    }

    private static string StructurePath(ArchiveEntryDto entry)
    {
        var packageDirectory = Path.GetFileName(Path.GetDirectoryName(entry.SourcePamt));
        if (string.IsNullOrWhiteSpace(packageDirectory))
        {
            packageDirectory = "package";
        }
        return $"{packageDirectory.Trim('/')}/{entry.Path.Trim('/')}";
    }

    private static void Publish(Func<ProgressUpdate, Task>? progress, ProgressUpdate update) =>
        progress?.Invoke(update).GetAwaiter().GetResult();

    private sealed record QueryCandidate(
        long EntryId,
        string PrimaryText,
        long PrimaryNumber,
        long SecondaryNumber,
        string Path,
        string Package,
        int PazIndex,
        long ArchiveOffset,
        long OriginalSize,
        long StoredSize)
    {
        public static QueryCandidate Create(ArchiveEntryDto entry, ArchiveSortField field)
        {
            var (text, number, secondary) = field switch
            {
                ArchiveSortField.Name => (entry.Name, 0L, 0L),
                ArchiveSortField.KnownName => (entry.KnownName, 0L, 0L),
                ArchiveSortField.ExactName => (entry.ExactName, 0L, 0L),
                ArchiveSortField.NameEvidence => (entry.NameEvidence, 0L, 0L),
                ArchiveSortField.Extension => (entry.Extension, 0L, 0L),
                ArchiveSortField.Package => (entry.Package, 0L, 0L),
                ArchiveSortField.OriginalSize => (string.Empty, entry.OriginalSize, entry.StoredSize),
                ArchiveSortField.StoredSize => (string.Empty, entry.StoredSize, entry.OriginalSize),
                ArchiveSortField.Compression => (CompressionLabel(entry.CompressionType), entry.CompressionType, entry.Flags),
                ArchiveSortField.Role => (ArchiveRoleDisplay.For(entry), 0L, 0L),
                ArchiveSortField.Category => (entry.Category, 0L, 0L),
                ArchiveSortField.ActiveOverride => (entry.OverrideState, 0L, 0L),
                _ => (entry.Path, 0L, 0L),
            };
            return new QueryCandidate(
                entry.EntryId,
                NaturalText(text),
                number,
                secondary,
                NaturalText(entry.Path),
                NaturalText(entry.Package),
                entry.PazIndex,
                entry.Offset,
                entry.OriginalSize,
                entry.StoredSize);
        }
    }
}
