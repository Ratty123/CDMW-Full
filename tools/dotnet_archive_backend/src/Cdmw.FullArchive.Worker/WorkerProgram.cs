using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Worker;

internal static class WorkerProgram
{
    public static async Task<int> RunAsync(string[] args)
    {
        string? cacheRoot = null;
        var selfTest = false;
        for (var index = 0; index < args.Length; index++)
        {
            switch (args[index])
            {
                case "--cache-root" when index + 1 < args.Length:
                    cacheRoot = args[++index];
                    break;
                case "--self-test":
                    selfTest = true;
                    break;
            }
        }

        if (selfTest)
        {
            try
            {
                var native = new NativeArchiveCore();
                native.EnsureCompatible();
                Console.WriteLine($"CDMW full archive worker self-test: OK (archive ABI {native.AbiVersion}, index {ArchiveIndex.Version})");
                return 0;
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine($"CDMW full archive worker self-test: FAIL: {exception.Message}");
                return 1;
            }
        }

        cacheRoot ??= Environment.GetEnvironmentVariable("CDMW_FULL_ARCHIVE_CACHE_ROOT");
        if (string.IsNullOrWhiteSpace(cacheRoot))
        {
            Console.Error.WriteLine("usage: cdmw-full-archive-worker --cache-root <path> | --self-test");
            return 2;
        }

        using var shutdown = new CancellationTokenSource();
        Console.CancelKeyPress += (_, eventArgs) =>
        {
            eventArgs.Cancel = true;
            shutdown.Cancel();
        };

        try
        {
            var server = new WorkerServer(
                Console.OpenStandardInput(),
                Console.OpenStandardOutput(),
                cacheRoot);
            await server.RunAsync(shutdown.Token).ConfigureAwait(false);
            return 0;
        }
        catch (OperationCanceledException)
        {
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception);
            return 1;
        }
    }
}
