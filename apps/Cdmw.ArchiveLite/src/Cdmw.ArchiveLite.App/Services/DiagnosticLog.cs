using System.Text;

namespace Cdmw.ArchiveLite.App.Services;

internal static class DiagnosticLog
{
    private static readonly SemaphoreSlim WriteGate = new(1, 1);

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
}
