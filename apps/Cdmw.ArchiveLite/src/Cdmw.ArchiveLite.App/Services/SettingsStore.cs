using System.Text.Json;

namespace Cdmw.ArchiveLite.App.Services;

internal static class SettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true,
    };

    public static async Task<LiteSettings> LoadAsync(CancellationToken cancellationToken)
    {
        try
        {
            await using var stream = new FileStream(
                AppDataPaths.Settings,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete,
                16 * 1024,
                FileOptions.Asynchronous | FileOptions.SequentialScan);
            return await JsonSerializer.DeserializeAsync<LiteSettings>(stream, JsonOptions, cancellationToken).ConfigureAwait(false)
                ?? new LiteSettings();
        }
        catch (FileNotFoundException)
        {
            return new LiteSettings();
        }
        catch (JsonException exception)
        {
            await DiagnosticLog.WriteAsync("settings", exception.ToString(), cancellationToken).ConfigureAwait(false);
            return new LiteSettings();
        }
        catch (IOException exception)
        {
            await DiagnosticLog.WriteAsync("settings", exception.ToString(), cancellationToken).ConfigureAwait(false);
            return new LiteSettings();
        }
    }

    public static async Task SaveAsync(LiteSettings settings, CancellationToken cancellationToken)
    {
        AppDataPaths.EnsureCreated();
        var staging = Path.Combine(AppDataPaths.Root, $".settings.{Guid.NewGuid():N}.tmp");
        try
        {
            await using (var stream = new FileStream(
                staging,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                16 * 1024,
                FileOptions.Asynchronous | FileOptions.SequentialScan))
            {
                await JsonSerializer.SerializeAsync(stream, settings, JsonOptions, cancellationToken).ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
                stream.Flush(flushToDisk: true);
            }

            cancellationToken.ThrowIfCancellationRequested();
            File.Move(staging, AppDataPaths.Settings, overwrite: true);
        }
        finally
        {
            try
            {
                File.Delete(staging);
            }
            catch (IOException)
            {
                // The previous settings remain authoritative.
            }
        }
    }
}
