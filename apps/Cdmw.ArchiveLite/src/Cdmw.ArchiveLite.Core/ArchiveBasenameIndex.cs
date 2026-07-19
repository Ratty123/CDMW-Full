using System.Buffers.Binary;
using System.IO.MemoryMappedFiles;
using System.Text;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

internal sealed class ArchiveBasenameIndex : IDisposable
{
    private const int Version = 1;
    private const int HeaderSize = 64;
    private const int RecordSize = 16;
    private const int WriteBufferSize = 1024 * 1024;
    private static readonly byte[] Magic = "CDMWABI1"u8.ToArray();
    private readonly MemoryMappedFile _mapping;
    private readonly MemoryMappedViewAccessor _view;
    private readonly long _recordsOffset;
    private int _disposed;

    private ArchiveBasenameIndex(
        string path,
        MemoryMappedFile mapping,
        MemoryMappedViewAccessor view,
        long recordCount,
        long recordsOffset)
    {
        Path = path;
        _mapping = mapping;
        _view = view;
        RecordCount = recordCount;
        _recordsOffset = recordsOffset;
    }

    public string Path { get; }
    public long RecordCount { get; }

    public static async Task<ArchiveBasenameIndex> OpenOrBuildAsync(
        ArchiveIndex source,
        string path,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        try
        {
            return Open(path, source);
        }
        catch (Exception exception) when (exception is FileNotFoundException or InvalidDataException or IOException)
        {
            // A missing, stale, or damaged derived lookup is always safe to rebuild.
        }

        var records = await Task.Run(
            () => BuildRecords(source, publishProgress, cancellationToken),
            CancellationToken.None).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        await AtomicFile.WriteAsync(
            path,
            (stream, token) => WriteAsync(stream, source, records, token),
            cancellationToken).ConfigureAwait(false);
        return Open(path, source);
    }

    public IReadOnlyList<ArchiveEntryDto> FindEntriesByBasename(
        ArchiveIndex source,
        string basename,
        int maximumResults = 32)
    {
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
        ArgumentNullException.ThrowIfNull(source);
        ArgumentException.ThrowIfNullOrWhiteSpace(basename);
        if (maximumResults < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(maximumResults));
        }

        var normalized = NormalizeBasename(basename);
        var hash = HashBasename(Encoding.UTF8.GetBytes(normalized));
        long low = 0;
        long high = RecordCount;
        while (low < high)
        {
            var middle = low + (high - low) / 2;
            if (ReadHash(middle) < hash)
            {
                low = middle + 1;
            }
            else
            {
                high = middle;
            }
        }

        var results = new List<ArchiveEntryDto>(Math.Min(maximumResults, 4));
        for (var recordId = low; recordId < RecordCount && results.Count < maximumResults; recordId++)
        {
            if (ReadHash(recordId) != hash)
            {
                break;
            }
            var entryId = checked((long)_view.ReadUInt64(checked(_recordsOffset + recordId * RecordSize + 8)));
            var entry = source.ReadEntry(entryId);
            if (string.Equals(NormalizeBasename(entry.Path), normalized, StringComparison.OrdinalIgnoreCase))
            {
                results.Add(entry);
            }
        }
        return results;
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 0)
        {
            _view.Dispose();
            _mapping.Dispose();
        }
    }

    private static ArchiveBasenameIndex Open(string path, ArchiveIndex source)
    {
        var fullPath = System.IO.Path.GetFullPath(path);
        var stream = new FileStream(fullPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        try
        {
            if (stream.Length < HeaderSize)
            {
                throw new InvalidDataException("Archive basename index is smaller than its header.");
            }
            var mapping = MemoryMappedFile.CreateFromFile(
                stream,
                null,
                0,
                MemoryMappedFileAccess.Read,
                HandleInheritability.None,
                leaveOpen: false);
            try
            {
                var view = mapping.CreateViewAccessor(0, 0, MemoryMappedFileAccess.Read);
                try
                {
                    var magic = new byte[Magic.Length];
                    view.ReadArray(0, magic, 0, magic.Length);
                    var version = view.ReadUInt32(8);
                    var recordSize = view.ReadUInt32(12);
                    var recordCount = checked((long)view.ReadUInt64(16));
                    var recordsOffset = checked((long)view.ReadUInt64(24));
                    var sourceEntryCount = checked((long)view.ReadUInt64(32));
                    var sourceFileSize = checked((long)view.ReadUInt64(40));
                    var expectedBytes = checked(recordCount * RecordSize);
                    if (!magic.AsSpan().SequenceEqual(Magic)
                        || version != Version
                        || recordSize != RecordSize
                        || recordCount != source.EntryCount
                        || sourceEntryCount != source.EntryCount
                        || sourceFileSize != new FileInfo(source.Path).Length
                        || recordsOffset < HeaderSize
                        || recordsOffset > stream.Length
                        || expectedBytes > stream.Length - recordsOffset)
                    {
                        throw new InvalidDataException("Archive basename index does not match its source archive index.");
                    }
                    return new ArchiveBasenameIndex(fullPath, mapping, view, recordCount, recordsOffset);
                }
                catch
                {
                    view.Dispose();
                    throw;
                }
            }
            catch
            {
                mapping.Dispose();
                throw;
            }
        }
        catch
        {
            stream.Dispose();
            throw;
        }
    }

    private static BasenameRecord[] BuildRecords(
        ArchiveIndex source,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        if (source.EntryCount > Array.MaxLength)
        {
            throw new InvalidDataException("Archive contains too many entries for the basename lookup index.");
        }
        var records = new BasenameRecord[checked((int)source.EntryCount)];
        var pathBuffer = new byte[1024];
        for (long entryId = 0; entryId < source.EntryCount; entryId++)
        {
            if ((entryId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                publishProgress?.Invoke(new ProgressUpdate(
                    entryId,
                    source.EntryCount,
                    "lookup_index_build",
                    null)).GetAwaiter().GetResult();
            }
            var length = source.GetPathByteLength(entryId);
            if (length > pathBuffer.Length)
            {
                pathBuffer = new byte[Math.Max(length, checked(pathBuffer.Length * 2))];
            }
            var read = source.ReadPathBytes(entryId, pathBuffer);
            if (read != length)
            {
                throw new InvalidDataException("Archive index returned a truncated virtual path.");
            }
            records[checked((int)entryId)] = new BasenameRecord(
                HashBasename(pathBuffer.AsSpan(0, length)),
                entryId);
        }
        cancellationToken.ThrowIfCancellationRequested();
        Array.Sort(records, BasenameRecordComparer.Instance);
        publishProgress?.Invoke(new ProgressUpdate(
            source.EntryCount,
            source.EntryCount,
            "lookup_index_build",
            "complete")).GetAwaiter().GetResult();
        return records;
    }

    private static async Task WriteAsync(
        Stream stream,
        ArchiveIndex source,
        IReadOnlyList<BasenameRecord> records,
        CancellationToken cancellationToken)
    {
        var header = new byte[HeaderSize];
        Magic.CopyTo(header, 0);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(8), Version);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(12), RecordSize);
        BinaryPrimitives.WriteUInt64LittleEndian(header.AsSpan(16), checked((ulong)records.Count));
        BinaryPrimitives.WriteUInt64LittleEndian(header.AsSpan(24), HeaderSize);
        BinaryPrimitives.WriteUInt64LittleEndian(header.AsSpan(32), checked((ulong)source.EntryCount));
        BinaryPrimitives.WriteUInt64LittleEndian(header.AsSpan(40), checked((ulong)new FileInfo(source.Path).Length));
        await stream.WriteAsync(header, cancellationToken).ConfigureAwait(false);

        var buffer = new byte[WriteBufferSize];
        var offset = 0;
        foreach (var record in records)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (offset > buffer.Length - RecordSize)
            {
                await stream.WriteAsync(buffer.AsMemory(0, offset), cancellationToken).ConfigureAwait(false);
                offset = 0;
            }
            BinaryPrimitives.WriteUInt64LittleEndian(buffer.AsSpan(offset), record.Hash);
            BinaryPrimitives.WriteUInt64LittleEndian(buffer.AsSpan(offset + 8), checked((ulong)record.EntryId));
            offset += RecordSize;
        }
        if (offset > 0)
        {
            await stream.WriteAsync(buffer.AsMemory(0, offset), cancellationToken).ConfigureAwait(false);
        }
    }

    private ulong ReadHash(long recordId) =>
        _view.ReadUInt64(checked(_recordsOffset + recordId * RecordSize));

    private static string NormalizeBasename(string value)
    {
        var normalized = value.Replace('\\', '/').Trim('/');
        var slash = normalized.LastIndexOf('/');
        return (slash >= 0 ? normalized[(slash + 1)..] : normalized).ToLowerInvariant();
    }

    internal static ulong HashBasename(ReadOnlySpan<byte> path)
    {
        var start = 0;
        for (var index = 0; index < path.Length; index++)
        {
            if (path[index] is (byte)'/' or (byte)'\\')
            {
                start = index + 1;
            }
        }
        const ulong offsetBasis = 14695981039346656037UL;
        const ulong prime = 1099511628211UL;
        var hash = offsetBasis;
        for (var index = start; index < path.Length; index++)
        {
            var value = path[index];
            if (value is >= (byte)'A' and <= (byte)'Z')
            {
                value = checked((byte)(value + ('a' - 'A')));
            }
            hash ^= value;
            hash *= prime;
        }
        return hash;
    }

    private readonly record struct BasenameRecord(ulong Hash, long EntryId);

    private sealed class BasenameRecordComparer : IComparer<BasenameRecord>
    {
        public static BasenameRecordComparer Instance { get; } = new();

        public int Compare(BasenameRecord left, BasenameRecord right)
        {
            var hash = left.Hash.CompareTo(right.Hash);
            return hash != 0 ? hash : left.EntryId.CompareTo(right.EntryId);
        }
    }
}
