namespace Cdmw.ArchiveLite.Core;

public static class AtomicFile
{
    public static async Task WriteAsync(
        string destination,
        Func<Stream, CancellationToken, Task> writer,
        CancellationToken cancellationToken,
        bool overwrite = true,
        bool flushToDisk = true)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(destination);
        ArgumentNullException.ThrowIfNull(writer);
        var fullDestination = Path.GetFullPath(destination);
        var directory = Path.GetDirectoryName(fullDestination)
            ?? throw new InvalidDataException("Destination has no parent directory.");
        Directory.CreateDirectory(directory);
        var staging = Path.Combine(directory, $".{Path.GetFileName(fullDestination)}.{Guid.NewGuid():N}.tmp");
        try
        {
            await using (var stream = new FileStream(
                staging,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                128 * 1024,
                FileOptions.Asynchronous | FileOptions.SequentialScan))
            {
                await writer(stream, cancellationToken).ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
                if (flushToDisk)
                {
                    stream.Flush(flushToDisk: true);
                }
            }

            cancellationToken.ThrowIfCancellationRequested();
            File.Move(staging, fullDestination, overwrite);
        }
        finally
        {
            try
            {
                File.Delete(staging);
            }
            catch (IOException)
            {
                // A later cache cleanup can remove a locked staging file.
            }
            catch (UnauthorizedAccessException)
            {
                // Preserve the primary operation result.
            }
        }
    }
}
