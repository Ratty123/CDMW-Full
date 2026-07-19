using System.Security.Cryptography;
using System.Text;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveEntryPreparationService(
    ArchiveSessionManager sessions,
    NativeArchiveCore native)
{
    public async Task<PrepareEntryResult> PrepareAsync(
        PrepareEntryRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(request.SessionId);
        var entry = session.ReadEntry(request.EntryId);
        var identityText = $"{session.Fingerprint}\n{entry.Identity.NormalizedPath}\n{entry.Identity.SourcePamt}\n{entry.PazIndex}\n{entry.Offset}";
        var key = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identityText))).ToLowerInvariant();
        var preparedRoot = Path.Combine(session.GenerationPath, "prepared", key[..2]);
        Directory.CreateDirectory(preparedRoot);
        var extension = entry.Extension.Length <= 16 ? entry.Extension : string.Empty;
        var destination = Path.Combine(preparedRoot, key + extension);
        if (File.Exists(destination))
        {
            var existingHash = await HashFileAsync(destination, cancellationToken).ConfigureAwait(false);
            var info = new FileInfo(destination);
            return Result(session, entry, destination, info.Length, existingHash, "prepared cache hit");
        }

        if (progress is not null)
        {
            await progress(new ProgressUpdate(0, entry.OriginalSize, "prepare_decode", entry.Path)).ConfigureAwait(false);
        }
        var decoded = await Task.Run(() => native.Decode(entry), cancellationToken).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        var staging = Path.Combine(preparedRoot, $".{key}.{Guid.NewGuid():N}.tmp");
        try
        {
            await using (var stream = new FileStream(
                staging,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                128 * 1024,
                FileOptions.Asynchronous | FileOptions.WriteThrough))
            {
                await stream.WriteAsync(decoded.Bytes, cancellationToken).ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
                stream.Flush(flushToDisk: true);
            }
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                File.Move(staging, destination);
            }
            catch (IOException) when (File.Exists(destination))
            {
                // A concurrent identical preparation published first.
            }
            var hash = await HashFileAsync(destination, cancellationToken).ConfigureAwait(false);
            if (progress is not null)
            {
                await progress(new ProgressUpdate(decoded.Bytes.LongLength, decoded.Bytes.LongLength, "prepare_complete", entry.Path)).ConfigureAwait(false);
            }
            return Result(session, entry, destination, decoded.Bytes.LongLength, hash, decoded.Note);
        }
        finally
        {
            TryDelete(staging);
        }
    }

    private static PrepareEntryResult Result(
        ArchiveSession session,
        ArchiveEntryDto entry,
        string path,
        long size,
        string hash,
        string? note) => new(
        new ArchiveEntryRef(session.Id, entry.EntryId, entry.Identity, entry.Path),
        path,
        size,
        hash,
        note);

    private static async Task<string> HashFileAsync(string path, CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete,
            128 * 1024,
            FileOptions.Asynchronous | FileOptions.SequentialScan);
        var hash = await SHA256.HashDataAsync(stream, cancellationToken).ConfigureAwait(false);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // A later cache prune can remove an abandoned staging file.
        }
    }
}
