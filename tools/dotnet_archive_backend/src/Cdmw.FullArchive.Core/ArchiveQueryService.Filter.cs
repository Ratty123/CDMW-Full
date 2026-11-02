using System.Collections.Concurrent;
using System.Text.RegularExpressions;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed partial class ArchiveQueryService
{
    /// <summary>
    /// A query's filters, parsed once and evaluated against the index's own fields.
    /// Each test reads the same value <see cref="ArchiveIndex.ReadEntry"/> and
    /// <see cref="ArchiveNameIndex.Enrich"/> would put in the entry, but only the fields
    /// the query uses, so a scan no longer builds a full entry for every row.
    /// </summary>
    private sealed class QueryFilter
    {
        private readonly bool _includeActive;
        private readonly TextTerm[] _include;
        private readonly TextTerm[] _exclude;
        private readonly TextTerm[] _technical;
        private readonly IReadOnlyList<string>? _extensions;
        private readonly PackageTerm[]? _packages;
        private readonly string? _folder;
        private readonly IReadOnlyList<ArchiveEntryRole>? _roles;
        private readonly long? _minimumSize;
        private readonly bool _previewableOnly;
        private readonly bool _activeOverridesOnly;
        private readonly ConcurrentDictionary<ArchiveIndexStringRange, PamtFacts> _pamts = new();

        private QueryFilter(ArchiveQuery query)
        {
            _includeActive = !string.IsNullOrWhiteSpace(query.IncludeText);
            _include = _includeActive ? SplitTerms(query.IncludeText!) : [];
            _exclude = string.IsNullOrWhiteSpace(query.ExcludeText) ? [] : SplitTerms(query.ExcludeText);
            _technical = query.TechnicalSuffixes is { Count: > 0 } suffixes
                ? suffixes.Select(TextTerm.Parse).ToArray()
                : [];
            _extensions = query.Extensions is { Count: > 0 } ? query.Extensions : null;
            _packages = query.Packages is { Count: > 0 } packages ? packages.Select(PackageTerm.Parse).ToArray() : null;
            _folder = string.IsNullOrWhiteSpace(query.Folder) ? null : NormalizeFolder(query.Folder);
            _roles = query.Roles is { Count: > 0 } ? query.Roles : null;
            _minimumSize = query.MinimumSize;
            _previewableOnly = query.PreviewableOnly;
            _activeOverridesOnly = query.ActiveOverridesOnly;
            _readsPath = HasText || _extensions is not null || _roles is not null || _previewableOnly || _folder is not null;
        }

        /// <summary>False when only size, override and package filters (or none) apply.</summary>
        private readonly bool _readsPath;

        public static QueryFilter Create(ArchiveQuery query) => new(query);

        private bool HasText => _includeActive || _exclude.Length > 0 || _technical.Length > 0;

        /// <summary>
        /// True when a text term could match a name field. Otherwise every name field
        /// tests like the empty string an unnamed entry carries, and the scan skips them.
        /// </summary>
        public bool MayMatchNames(ArchiveNameIndex index) =>
            HasText && _include.Concat(_exclude).Concat(_technical).Any(term => term.MayMatchNames(index));

        public bool Matches(ArchiveIndex index, long entryId, ArchiveEntryNames?[]? names)
        {
            if (_minimumSize is { } minimum && index.ReadOriginalSize(entryId) < minimum)
            {
                return false;
            }
            if (_activeOverridesOnly && !index.ReadIsActiveOverride(entryId))
            {
                return false;
            }
            PamtFacts? pamt = null;
            if (_packages is not null || _folder is not null)
            {
                pamt = _pamts.GetOrAdd(index.GetPamtPathRange(entryId), range => PamtFacts.Create(index.ReadString(range), _packages));
                if (!pamt.PackageMatches)
                {
                    return false;
                }
            }
            if (!_readsPath)
            {
                return true;
            }
            var path = index.ReadEntryPath(entryId);
            if (_folder is not null && !(pamt!.StructurePrefix + path.Trim('/')).StartsWith(_folder, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
            if (_extensions is not null || _roles is not null || _previewableOnly)
            {
                var extension = Path.GetExtension(path).ToLowerInvariant();
                if (_extensions is not null && !_extensions.Any(value => MatchesExtension(extension, value)))
                {
                    return false;
                }
                if (_roles is not null || _previewableOnly)
                {
                    var role = ArchiveEntryClassifier.Classify(path, extension);
                    if (_roles is not null && !_roles.Contains(role))
                    {
                        return false;
                    }
                    if (_previewableOnly && !ArchiveEntryClassifier.IsPreviewable(extension, role))
                    {
                        return false;
                    }
                }
            }
            if (!HasText)
            {
                return true;
            }
            var name = Path.GetFileName(path.Replace('/', Path.DirectorySeparatorChar));
            var entryNames = names?[entryId];
            if (_includeActive && !_include.Any(term => term.Matches(path, name, entryNames)))
            {
                return false;
            }
            if (_exclude.Any(term => term.Matches(path, name, entryNames)))
            {
                return false;
            }
            return !_technical.Any(term => term.Matches(path, name, entryNames));
        }

        private static TextTerm[] SplitTerms(string filter) =>
            filter
                .Split([';', ',', '\r', '\n'], StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
                .Select(TextTerm.Parse)
                .ToArray();
    }

    /// <summary>One include, exclude or technical-suffix pattern, as the old per-entry test read it.</summary>
    private sealed class TextTerm(string text, Regex? wildcard)
    {
        public static TextTerm Parse(string filter)
        {
            var text = filter.Trim();
            return new TextTerm(text, text.ContainsAny(['*', '?', '[']) ? WildcardRegex(text) : null);
        }

        public bool Matches(string path, string name, ArchiveEntryNames? names)
        {
            if (wildcard is null)
            {
                // An unnamed entry's name fields are empty, and no term here is empty
                // unless the path test already matched it.
                return path.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                    name.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                    names is not null &&
                    (names.KnownName.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                     names.ExactName.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                     names.NameEvidence.Contains(text, StringComparison.OrdinalIgnoreCase));
            }
            return wildcard.IsMatch(path) ||
                wildcard.IsMatch(name) ||
                wildcard.IsMatch(names?.KnownName ?? string.Empty);
        }

        public bool MayMatchNames(ArchiveNameIndex index)
        {
            if (wildcard is null)
            {
                return text.Length > 0 && index.NameFieldValues().Any(value => value.Contains(text, StringComparison.OrdinalIgnoreCase));
            }
            // A wildcard tests KnownName only. Skipping the column tests "" instead,
            // which is the same answer unless some name value tests differently.
            var empty = wildcard.IsMatch(string.Empty);
            return index.KnownNameValues().Any(value => wildcard.IsMatch(value) != empty);
        }
    }

    private sealed class PackageTerm(string text, Regex? wildcard)
    {
        public static PackageTerm Parse(string candidate)
        {
            var text = candidate.Trim();
            return new PackageTerm(text, text.Length > 0 && text.ContainsAny(['*', '?', '[']) ? WildcardRegex(text) : null);
        }

        public bool Matches(string package, string sourcePamt)
        {
            if (text.Length == 0)
            {
                return true;
            }
            if (wildcard is null)
            {
                return package.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                    sourcePamt.Contains(text, StringComparison.OrdinalIgnoreCase);
            }
            return wildcard.IsMatch(package) || wildcard.IsMatch(sourcePamt);
        }
    }

    /// <summary>What the package and folder filters derive from one PAMT path.</summary>
    private sealed record PamtFacts(bool PackageMatches, string StructurePrefix)
    {
        public static PamtFacts Create(string sourcePamt, PackageTerm[]? packages)
        {
            var package = ArchiveEntryClassifier.PackageLabel(sourcePamt);
            var packageDirectory = Path.GetFileName(Path.GetDirectoryName(sourcePamt));
            if (string.IsNullOrWhiteSpace(packageDirectory))
            {
                packageDirectory = "package";
            }
            return new PamtFacts(
                packages is null || packages.Any(term => term.Matches(package, sourcePamt)),
                $"{packageDirectory.Trim('/')}/");
        }
    }

    private static Regex WildcardRegex(string text) => new(
        "^" + Regex.Escape(text).Replace("\\*", ".*").Replace("\\?", ".") + "$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled,
        TimeSpan.FromMilliseconds(250));
}
