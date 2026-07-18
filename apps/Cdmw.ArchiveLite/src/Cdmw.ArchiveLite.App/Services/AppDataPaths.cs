namespace Cdmw.ArchiveLite.App.Services;

internal static class AppDataPaths
{
    private const string CacheRootEnvironmentVariable = "CDMW_ARCHIVE_LITE_CACHE_ROOT";
    private const string PortableRootEnvironmentVariable = "CDMW_ARCHIVE_LITE_PORTABLE_ROOT";

    public static string Root { get; } = ResolveRoot();

    public static string Settings => Path.Combine(Root, "settings.json");
    public static string Cache { get; } = ResolveCache();
    public static string Logs => Path.Combine(Root, "logs");
    public static string Crash => Path.Combine(Root, "crash");

    public static void EnsureCreated()
    {
        Directory.CreateDirectory(Root);
        Directory.CreateDirectory(Cache);
        Directory.CreateDirectory(Logs);
        Directory.CreateDirectory(Crash);
        Environment.SetEnvironmentVariable(PortableRootEnvironmentVariable, Root);
        Environment.SetEnvironmentVariable(CacheRootEnvironmentVariable, Cache);
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
