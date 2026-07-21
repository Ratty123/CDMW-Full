namespace Cdmw.FullArchive.Tests;

internal static class Program
{
    public static Task<int> Main(string[] args) =>
        args.Length >= 2 && args[0] == "--baseline-report"
            ? SyntheticBaselineProbe.RunAsync(args[1])
            : args.Length >= 2 && args[0] == "--cache-scale-report"
                ? SyntheticCacheScaleProbe.RunAsync(args[1])
                : FullArchiveTestRunner.RunAsync();
}
