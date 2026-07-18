using Cdmw.ArchiveLite.Tests;

var dataRoot = Path.Combine(Path.GetTempPath(), $"cdmw-archive-lite-test-data-{Guid.NewGuid():N}");
Environment.SetEnvironmentVariable("CDMW_ARCHIVE_LITE_TEST_MODE", "1");
Environment.SetEnvironmentVariable("CDMW_ARCHIVE_LITE_DATA_ROOT", dataRoot);
try
{
    return await ArchiveLiteTestRunner.RunAsync().ConfigureAwait(false);
}
finally
{
    try
    {
        if (Directory.Exists(dataRoot)) Directory.Delete(dataRoot, recursive: true);
    }
    catch (IOException)
    {
        // Worker/process teardown can release cache handles just after the test.
    }
}
