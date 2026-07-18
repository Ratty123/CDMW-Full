using System.IO.Pipes;
using Cdmw.ArchiveLite.Core;

namespace Cdmw.ArchiveLite.Worker;

internal static class WorkerProgram
{
    public static async Task<int> RunAsync(string[] args)
    {
        string? pipeName = null;
        var selfTest = false;
        for (var index = 0; index < args.Length; index++)
        {
            switch (args[index])
            {
                case "--pipe" when index + 1 < args.Length:
                    pipeName = args[++index];
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
                Console.WriteLine($"CDMW Archive Lite worker self-test: OK (archive ABI {native.AbiVersion})");
                return 0;
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine($"CDMW Archive Lite worker self-test: FAIL: {exception.Message}");
                return 1;
            }
        }

        if (string.IsNullOrWhiteSpace(pipeName))
        {
            Console.Error.WriteLine("usage: CdmwArchiveLite.Worker --pipe <name> | --self-test");
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
            await using var pipe = new NamedPipeServerStream(
                pipeName,
                PipeDirection.InOut,
                1,
                PipeTransmissionMode.Byte,
                PipeOptions.Asynchronous | PipeOptions.WriteThrough | PipeOptions.CurrentUserOnly);
            await pipe.WaitForConnectionAsync(shutdown.Token).ConfigureAwait(false);
            var server = new WorkerServer(pipe);
            await server.RunAsync(shutdown.Token).ConfigureAwait(false);
            return 0;
        }
        catch (OperationCanceledException)
        {
            return 0;
        }
        catch (IOException exception)
        {
            Console.Error.WriteLine($"Worker transport failed: {exception.Message}");
            return 3;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception);
            return 1;
        }
    }
}
