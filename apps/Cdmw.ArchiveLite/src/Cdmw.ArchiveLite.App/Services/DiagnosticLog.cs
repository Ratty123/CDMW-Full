using System.Text;

namespace Cdmw.ArchiveLite.App.Services;

internal static class DiagnosticLog
{
    private static readonly SemaphoreSlim WriteGate = new(1, 1);
    private static readonly object FatalWriteGate = new();
    private static readonly string CrashFileName =
        $"archive-lite-crash-{DateTimeOffset.UtcNow:yyyyMMdd-HHmmss}-{Environment.ProcessId}.log";

    public static async Task WriteAsync(string area, string message, CancellationToken cancellationToken)
    {
        try
        {
            AppDataPaths.EnsureCreated();
            var line = $"{DateTimeOffset.UtcNow:O} [{area}] {message}{Environment.NewLine}";
            await WriteGate.WaitAsync(cancellationToken).ConfigureAwait(false);
            try
            {
                await File.AppendAllTextAsync(
                    Path.Combine(AppDataPaths.Logs, "archive-lite.log"),
                    line,
                    new UTF8Encoding(false),
                    cancellationToken).ConfigureAwait(false);
            }
            finally
            {
                WriteGate.Release();
            }
        }
        catch
        {
            // Diagnostics must never replace the primary failure.
        }
    }

    public static void WriteFatal(string area, Exception exception)
    {
        try
        {
            AppDataPaths.EnsureCreated();
            var report =
                $"{DateTimeOffset.UtcNow:O} [{area}] process={Environment.ProcessId}{Environment.NewLine}"
                + exception
                + Environment.NewLine;
            lock (FatalWriteGate)
            {
                File.AppendAllText(
                    Path.Combine(AppDataPaths.Crash, CrashFileName),
                    report,
                    new UTF8Encoding(false));
                File.AppendAllText(
                    Path.Combine(AppDataPaths.Logs, "archive-lite.log"),
                    report,
                    new UTF8Encoding(false));
            }
        }
        catch
        {
            // Fatal diagnostics must not mask or replace the original exception.
        }
    }
}
