namespace Cdmw.ArchiveLite.App.Services;

internal static class AppDataPaths
{
    public static string Root { get; } = ResolveRoot();

    public static string Settings => Path.Combine(Root, "settings.json");
    public static string Cache => Path.Combine(Root, "cache");
    public static string Logs => Path.Combine(Root, "logs");
    public static string Crash => Path.Combine(Root, "crash");

    public static void EnsureCreated()
    {
        Directory.CreateDirectory(Root);
        Directory.CreateDirectory(Cache);
        Directory.CreateDirectory(Logs);
        Directory.CreateDirectory(Crash);
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
