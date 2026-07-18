using System.IO.MemoryMappedFiles;
using System.Text;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveIndex : IDisposable
{
    public const int Version = 1;
    private const int HeaderSize = 64;
    private const int RecordSize = 80;
    private static readonly byte[] Magic = "CDMWALI1"u8.ToArray();
    private readonly MemoryMappedFile _mapping;
    private readonly MemoryMappedViewAccessor _view;
    private readonly long _recordsOffset;
    private readonly long _stringsOffset;
    private readonly long _stringsSize;
    private int _disposed;

    private ArchiveIndex(
        string path,
        MemoryMappedFile mapping,
        MemoryMappedViewAccessor view,
        long entryCount,
        long recordsOffset,
        long stringsOffset,
        long stringsSize)
    {
        Path = path;
        _mapping = mapping;
        _view = view;
        EntryCount = entryCount;
        _recordsOffset = recordsOffset;
        _stringsOffset = stringsOffset;
        _stringsSize = stringsSize;
    }

    public string Path { get; }
    public long EntryCount { get; }

    public static ArchiveIndex Open(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        var fullPath = System.IO.Path.GetFullPath(path);
        var stream = new FileStream(fullPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        try
        {
            if (stream.Length < HeaderSize)
            {
                throw new InvalidDataException("Archive index is smaller than its header.");
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
                    if (!magic.AsSpan().SequenceEqual(Magic))
                    {
                        throw new InvalidDataException("Archive index has an unsupported magic value.");
                    }
                    var version = view.ReadUInt32(8);
                    var recordSize = view.ReadUInt32(12);
                    var entryCount = checked((long)view.ReadUInt64(16));
                    var recordsOffset = checked((long)view.ReadUInt64(24));
                    var stringsOffset = checked((long)view.ReadUInt64(32));
                    var stringsSize = checked((long)view.ReadUInt64(40));
                    if (version != Version || recordSize != RecordSize)
                    {
                        throw new InvalidDataException($"Archive index version {version}/{recordSize} is not supported.");
                    }
                    var recordsBytes = checked(entryCount * RecordSize);
                    if (recordsOffset < HeaderSize || stringsOffset < recordsOffset ||
                        stringsOffset - recordsOffset < recordsBytes || stringsSize < 0 ||
                        stringsOffset > stream.Length || stringsSize > stream.Length - stringsOffset)
                    {
                        throw new InvalidDataException("Archive index ranges are invalid.");
                    }
                    return new ArchiveIndex(fullPath, mapping, view, entryCount, recordsOffset, stringsOffset, stringsSize);
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

    public ArchiveEntryDto ReadEntry(long entryId)
    {
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
        if (entryId < 0 || entryId >= EntryCount)
        {
            throw new ArgumentOutOfRangeException(nameof(entryId));
        }
        var record = checked(_recordsOffset + entryId * RecordSize);
        var pathOffset = checked((long)_view.ReadUInt64(record));
        var pamtOffset = checked((long)_view.ReadUInt64(record + 8));
        var pazOffset = checked((long)_view.ReadUInt64(record + 16));
        var archiveOffset = checked((long)_view.ReadUInt64(record + 24));
        var storedSize = checked((long)_view.ReadUInt64(record + 32));
        var originalSize = checked((long)_view.ReadUInt64(record + 40));
        var pathLength = checked((int)_view.ReadUInt32(record + 48));
        var pamtLength = checked((int)_view.ReadUInt32(record + 52));
        var pazLength = checked((int)_view.ReadUInt32(record + 56));
        var flags = checked((int)_view.ReadUInt32(record + 60));
        var pazIndex = checked((int)_view.ReadUInt32(record + 64));
        var virtualPath = ReadString(pathOffset, pathLength).Replace('\\', '/').Trim('/');
        var pamt = ReadString(pamtOffset, pamtLength);
        var paz = ReadString(pazOffset, pazLength);
        var extension = System.IO.Path.GetExtension(virtualPath).ToLowerInvariant();
        var role = ArchiveEntryClassifier.Classify(virtualPath, extension);
        return new ArchiveEntryDto(
            entryId,
            virtualPath,
            pamt,
            paz,
            pazIndex,
            archiveOffset,
            storedSize,
            originalSize,
            flags,
            extension,
            ArchiveEntryClassifier.PackageLabel(pamt),
            role,
            ArchiveEntryClassifier.IsPreviewable(extension, role));
    }

    public IReadOnlyList<ArchiveEntryDto> FindEntriesByPath(string virtualPath, int maximumResults = 32)
    {
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
        ArgumentException.ThrowIfNullOrWhiteSpace(virtualPath);
        if (maximumResults < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(maximumResults));
        }
        var normalized = virtualPath.Replace('\\', '/').Trim('/');
        long low = 0;
        long high = EntryCount;
        while (low < high)
        {
            var middle = low + (high - low) / 2;
            var comparison = StringComparer.OrdinalIgnoreCase.Compare(ReadEntry(middle).Path, normalized);
            if (comparison < 0)
            {
                low = middle + 1;
            }
            else
            {
                high = middle;
            }
        }

        var results = new List<ArchiveEntryDto>(Math.Min(maximumResults, 4));
        for (var entryId = low; entryId < EntryCount && results.Count < maximumResults; entryId++)
        {
            var entry = ReadEntry(entryId);
            var comparison = StringComparer.OrdinalIgnoreCase.Compare(entry.Path, normalized);
            if (comparison > 0)
            {
                break;
            }
            if (comparison == 0)
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

    private string ReadString(long offset, int length)
    {
        if (offset < 0 || length < 0 || offset > _stringsSize || length > _stringsSize - offset)
        {
            throw new InvalidDataException("Archive index string range is invalid.");
        }
        if (length == 0)
        {
            return string.Empty;
        }
        var bytes = new byte[length];
        _view.ReadArray(checked(_stringsOffset + offset), bytes, 0, length);
        return Encoding.UTF8.GetString(bytes);
    }
}
