namespace Cdmw.FullArchive.Tests;

internal static class Program
{
    public static Task<int> Main(string[] args) =>
        args.Length >= 2 && args[0] == "--baseline-report"
            ? SyntheticBaselineProbe.RunAsync(args[1])
            : args.Length >= 2 && args[0] == "--cache-scale-report"
                ? SyntheticCacheScaleProbe.RunAsync(args[1])
                : args.Length == 1 && args[0] == "--character-catalogue"
                    ? CharacterAsync()
                    : FullArchiveTestRunner.RunAsync();

    private static async Task<int> CharacterAsync()
    {
        await CharacterCatalogTests.CatalogueAsync();
        await CharacterCatalogTests.CacheAsync();
        Console.WriteLine("Character catalogue fixtures: PASS");
        return 0;
    }
}
