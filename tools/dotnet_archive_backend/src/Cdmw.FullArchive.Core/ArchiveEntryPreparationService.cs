using System.Buffers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveEntryPreparationService(
    ArchiveSessionManager sessions,
    NativeArchiveCore native)
{
    public const int MaximumBatchEntries = 4096;
    private const int PreparedMetadataSchema = 1;
    private const int HashBufferSize = 128 * 1024;
    private const int HashProgressIntervalBytes = 8 * 1024 * 1024;

    public async Task<PrepareEntryResult> PrepareAsync(
        PrepareEntryRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(request.SessionId);
        var entry = session.ReadEntry(request.EntryId);
        var sourceSha256 = await HashArchiveRangeAsync(entry, cancellationToken, progress).ConfigureAwait(false);
        var identityText = $"{session.Fingerprint}\n{entry.Identity.NormalizedPath}\n{entry.Identity.SourcePamt}\n{entry.PazIndex}\n{entry.Offset}\n{sourceSha256}";
        var key = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identityText))).ToLowerInvariant();
        var preparedRoot = Path.Combine(session.GenerationPath, "prepared", key[..2]);
        Directory.CreateDirectory(preparedRoot);
        var extension = entry.Extension.Length <= 16 ? entry.Extension : string.Empty;
        var destination = Path.Combine(preparedRoot, key + extension);
        if (File.Exists(destination))
        {
            var info = new FileInfo(destination);
            var metadata = await ReadPreparedMetadataAsync(destination, cancellationToken).ConfigureAwait(false);
            if (MetadataMatches(metadata, info, sourceSha256))
            {
                return Result(
                    session,
                    entry,
                    destination,
                    info.Length,
                    metadata!.PreparedSha256,
                    "prepared cache hit");
            }
            if (metadata is null)
            {
                var existingHash = await HashFileAsync(destination, cancellationToken).ConfigureAwait(false);
                await WritePreparedMetadataAsync(
                    destination,
                    sourceSha256,
                    existingHash,
                    info,
                    cancellationToken).ConfigureAwait(false);
                return Result(session, entry, destination, info.Length, existingHash, "prepared cache hit");
            }
            TryDelete(destination);
            TryDelete(MetadataPath(destination));
        }

        if (progress is not null)
        {
            await progress(new ProgressUpdate(0, entry.OriginalSize, "prepare_decode", entry.Path)).ConfigureAwait(false);
        }
        var decoded = await Task.Run(() => native.Decode(entry), cancellationToken).ConfigureAwait(false);
        var preparedSha256 = Convert.ToHexString(SHA256.HashData(decoded.Bytes)).ToLowerInvariant();
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
                var publishedHash = await HashFileAsync(destination, cancellationToken).ConfigureAwait(false);
                if (!string.Equals(publishedHash, preparedSha256, StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidDataException("Concurrent prepared cache publication produced different bytes.");
                }
            }
            var info = new FileInfo(destination);
            await WritePreparedMetadataAsync(
                destination,
                sourceSha256,
                preparedSha256,
                info,
                cancellationToken).ConfigureAwait(false);
            if (progress is not null)
            {
                await progress(new ProgressUpdate(decoded.Bytes.LongLength, decoded.Bytes.LongLength, "prepare_complete", entry.Path)).ConfigureAwait(false);
            }
            return Result(session, entry, destination, info.Length, preparedSha256, decoded.Note);
        }
        finally
        {
            TryDelete(staging);
        }
    }

    public async Task<PrepareEntriesResult> PrepareManyAsync(
        PrepareEntriesRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (request.EntryIds.Count is < 1 or > MaximumBatchEntries)
        {
            throw new InvalidDataException(
                $"Prepare entry batches require between 1 and {MaximumBatchEntries:N0} entry ids.");
        }
        if (request.EntryIds.Any(static entryId => entryId < 0) ||
            request.EntryIds.Distinct().Count() != request.EntryIds.Count)
        {
            throw new InvalidDataException("Prepare entry batches require unique non-negative entry ids.");
        }

        var items = new List<PrepareEntryResult>(request.EntryIds.Count);
        long totalBytes = 0;
        foreach (var entryId in request.EntryIds)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var item = await PrepareAsync(
                new PrepareEntryRequest(request.SessionId, entryId),
                cancellationToken,
                progress).ConfigureAwait(false);
            items.Add(item);
            totalBytes = checked(totalBytes + item.Size);
        }
        cancellationToken.ThrowIfCancellationRequested();
        return new PrepareEntriesResult(
            request.SessionId,
            items,
            request.EntryIds.Count,
            items.Count,
            totalBytes);
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

    private static async Task<string> HashArchiveRangeAsync(
        ArchiveEntryDto entry,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        if (entry.Offset < 0 || entry.StoredSize < 0)
        {
            throw new InvalidDataException("Archive entry has a negative source range.");
        }
        await using var stream = new FileStream(
            entry.PazFile,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete,
            HashBufferSize,
            FileOptions.Asynchronous | FileOptions.RandomAccess);
        if (entry.Offset > stream.Length || entry.StoredSize > stream.Length - entry.Offset)
        {
            throw new InvalidDataException("Archive entry source range is outside its PAZ file.");
        }
        stream.Seek(entry.Offset, SeekOrigin.Begin);
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = ArrayPool<byte>.Shared.Rent(HashBufferSize);
        try
        {
            long remaining = entry.StoredSize;
            long completed = 0;
            long nextProgress = 0;
            if (progress is not null)
            {
                await progress(new ProgressUpdate(0, entry.StoredSize, "prepare_fingerprint", entry.Path))
                    .ConfigureAwait(false);
            }
            while (remaining > 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var requested = checked((int)Math.Min(remaining, buffer.Length));
                var read = await stream.ReadAsync(buffer.AsMemory(0, requested), cancellationToken).ConfigureAwait(false);
                if (read <= 0) throw new EndOfStreamException("Archive entry source range ended unexpectedly.");
                hash.AppendData(buffer, 0, read);
                remaining -= read;
                completed += read;
                if (progress is not null && (completed >= nextProgress || remaining == 0))
                {
                    await progress(new ProgressUpdate(completed, entry.StoredSize, "prepare_fingerprint", entry.Path))
                        .ConfigureAwait(false);
                    nextProgress = completed + HashProgressIntervalBytes;
                }
            }
            return Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private static async Task<PreparedCacheMetadata?> ReadPreparedMetadataAsync(
        string destination,
        CancellationToken cancellationToken)
    {
        try
        {
            await using var stream = new FileStream(
                MetadataPath(destination),
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete,
                16 * 1024,
                FileOptions.Asynchronous | FileOptions.SequentialScan);
            return await JsonSerializer.DeserializeAsync<PreparedCacheMetadata>(stream, cancellationToken: cancellationToken)
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or JsonException)
        {
            return null;
        }
    }

    private static bool MetadataMatches(
        PreparedCacheMetadata? metadata,
        FileInfo info,
        string sourceSha256) =>
        metadata is not null &&
        metadata.Schema == PreparedMetadataSchema &&
        metadata.Size == info.Length &&
        metadata.LastWriteTimeUtcTicks == info.LastWriteTimeUtc.Ticks &&
        string.Equals(metadata.SourceSha256, sourceSha256, StringComparison.OrdinalIgnoreCase) &&
        metadata.PreparedSha256.Length == 64 &&
        metadata.PreparedSha256.All(Uri.IsHexDigit);

    private static async Task WritePreparedMetadataAsync(
        string destination,
        string sourceSha256,
        string preparedSha256,
        FileInfo info,
        CancellationToken cancellationToken)
    {
        var metadataPath = MetadataPath(destination);
        var staging = $"{metadataPath}.{Guid.NewGuid():N}.tmp";
        try
        {
            await using (var stream = new FileStream(
                staging,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                16 * 1024,
                FileOptions.Asynchronous | FileOptions.WriteThrough))
            {
                await JsonSerializer.SerializeAsync(
                    stream,
                    new PreparedCacheMetadata(
                        PreparedMetadataSchema,
                        sourceSha256,
                        preparedSha256,
                        info.Length,
                        info.LastWriteTimeUtc.Ticks),
                    cancellationToken: cancellationToken).ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
                stream.Flush(flushToDisk: true);
            }
            File.Move(staging, metadataPath, overwrite: true);
        }
        finally
        {
            TryDelete(staging);
        }
    }

    private static string MetadataPath(string destination) => destination + ".meta.json";

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

    private sealed record PreparedCacheMetadata(
        int Schema,
        string SourceSha256,
        string PreparedSha256,
        long Size,
        long LastWriteTimeUtcTicks);
}
