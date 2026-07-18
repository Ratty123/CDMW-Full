namespace Cdmw.ArchiveLite.Core;

public static class ArchiveLiteDataPaths
{
    public static string Root { get; } = ResolveRoot();

    public static string Cache { get; } = Path.Combine(Root, "cache");
    public static string IndexCache { get; } = Path.Combine(Cache, "index");
    public static string IndexRootManifests { get; } = Path.Combine(IndexCache, "roots");
    public static string PreviewCache { get; } = Path.Combine(Cache, "preview");
    public static string NameIndexCache { get; } = Path.Combine(Cache, "names");

    public static string CreateSessionIndexPath() => Path.Combine(
        Path.GetTempPath(),
        $"cdmw-archive-lite-session-{Environment.ProcessId}-{Guid.NewGuid():N}.ali");

    public static void EnsureCreated()
    {
        Directory.CreateDirectory(IndexCache);
        Directory.CreateDirectory(IndexRootManifests);
        Directory.CreateDirectory(PreviewCache);
        Directory.CreateDirectory(NameIndexCache);
    }

    private static string ResolveRoot()
    {
        var overrideRoot = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_DATA_ROOT");
        var testMode = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_TEST_MODE");
        if (testMode == "1" && !string.IsNullOrWhiteSpace(overrideRoot))
        {
            var resolved = Path.GetFullPath(overrideRoot);
            if (!resolved.Equals(Path.GetPathRoot(resolved), StringComparison.OrdinalIgnoreCase))
            {
                return resolved;
            }
        }
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Ratrider",
            "CDMWArchiveLite");
    }
}
