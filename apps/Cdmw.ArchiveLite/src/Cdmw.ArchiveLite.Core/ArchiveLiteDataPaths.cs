namespace Cdmw.ArchiveLite.Core;

public static class ArchiveLiteDataPaths
{
    public const string CacheRootEnvironmentVariable = "CDMW_ARCHIVE_LITE_CACHE_ROOT";
    public const string PortableRootEnvironmentVariable = "CDMW_ARCHIVE_LITE_PORTABLE_ROOT";

    public static string Root { get; } = ResolveRoot();

    public static string Cache { get; } = ResolveCache();
    public static string IndexCache { get; } = Path.Combine(Cache, "index");
    public static string IndexRootManifests { get; } = Path.Combine(IndexCache, "roots");
    public static string PreviewCache { get; } = Path.Combine(Cache, "preview");
    public static string ContentAnalysisCache { get; } = Path.Combine(PreviewCache, "content-analysis");
    public static string NameIndexCache { get; } = Path.Combine(Cache, "names");

    public static string CreateSessionIndexPath() => Path.Combine(
        Path.GetTempPath(),
        $"cdmw-archive-lite-session-{Environment.ProcessId}-{Guid.NewGuid():N}.ali");

    public static void EnsureCreated()
    {
        Directory.CreateDirectory(IndexCache);
        Directory.CreateDirectory(IndexRootManifests);
        Directory.CreateDirectory(PreviewCache);
        Directory.CreateDirectory(ContentAnalysisCache);
        Directory.CreateDirectory(NameIndexCache);
    }

    private static string ResolveRoot()
    {
        var testRoot = ResolveTestRoot();
        if (testRoot is not null)
        {
            return testRoot;
        }

        var portableRoot = Environment.GetEnvironmentVariable(PortableRootEnvironmentVariable);
        return TryResolveNonRootPath(portableRoot, out var resolvedPortableRoot)
            ? resolvedPortableRoot
            : Path.GetFullPath(AppContext.BaseDirectory);
    }

    private static string ResolveCache()
    {
        var testRoot = ResolveTestRoot();
        if (testRoot is not null)
        {
            return Path.Combine(testRoot, "cache");
        }

        var overrideRoot = Environment.GetEnvironmentVariable(CacheRootEnvironmentVariable);
        if (TryResolveNonRootPath(overrideRoot, out var resolvedOverride))
        {
            return resolvedOverride;
        }

        return Path.Combine(Root, "cache");
    }

    private static string? ResolveTestRoot()
    {
        var overrideRoot = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_DATA_ROOT");
        var testMode = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_TEST_MODE");
        return testMode == "1" && TryResolveNonRootPath(overrideRoot, out var resolved)
            ? resolved
            : null;
    }

    private static bool TryResolveNonRootPath(string? path, out string resolved)
    {
        resolved = string.Empty;
        if (string.IsNullOrWhiteSpace(path))
        {
            return false;
        }
        try
        {
            resolved = Path.GetFullPath(path);
            return !resolved.Equals(Path.GetPathRoot(resolved), StringComparison.OrdinalIgnoreCase);
        }
        catch (Exception exception) when (exception is ArgumentException or NotSupportedException)
        {
            resolved = string.Empty;
            return false;
        }
    }
}
