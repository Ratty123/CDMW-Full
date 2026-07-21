using System.Buffers.Binary;
using System.IO.MemoryMappedFiles;
using System.Text;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

internal sealed class ArchiveDependencyIndex : IDisposable
{
    private const int Version = 1;
    private const int HeaderSize = 80;
    private const int RecordSize = 16;
    private const int WriteBufferSize = 1024 * 1024;
    private const int MaximumFacetBytes = 16 * 1024 * 1024;
    private static readonly byte[] Magic = "CDMWADI1"u8.ToArray();
    private readonly MemoryMappedFile _mapping;
    private readonly MemoryMappedViewAccessor _view;
    private readonly long _basenameRecordsOffset;
    private readonly long _stemRecordsOffset;
    private int _disposed;

    private ArchiveDependencyIndex(
        string path,
        MemoryMappedFile mapping,
        MemoryMappedViewAccessor view,
        long recordCount,
        long basenameRecordsOffset,
        long stemRecordsOffset,
        IReadOnlyList<ArchiveFacet> extensions,
        IReadOnlyList<ArchiveFacet> packages,
        IReadOnlyList<ArchiveFacet> roles,
        IReadOnlyList<ArchiveFacet> categories)
    {
        Path = path;
        _mapping = mapping;
        _view = view;
        RecordCount = recordCount;
        _basenameRecordsOffset = basenameRecordsOffset;
        _stemRecordsOffset = stemRecordsOffset;
        Extensions = extensions;
        Packages = packages;
        Roles = roles;
        Categories = categories;
    }

    public string Path { get; }
    public long RecordCount { get; }
    public IReadOnlyList<ArchiveFacet> Extensions { get; }
    public IReadOnlyList<ArchiveFacet> Packages { get; }
    public IReadOnlyList<ArchiveFacet> Roles { get; }
    public IReadOnlyList<ArchiveFacet> Categories { get; }

    public static async Task<ArchiveDependencyIndex> OpenOrBuildAsync(
        ArchiveIndex source,
        string path,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        ArchiveDependencyIndex? existing = null;
        try
        {
            existing = Open(path, source);
        }
        catch (Exception exception) when (
            exception is FileNotFoundException or InvalidDataException or IOException or OverflowException or FormatException)
        {
            // Missing, stale, and damaged derived indexes are safe to rebuild.
        }
        if (existing is not null)
        {
            try
            {
                await PublishProgressAsync(
                    publishProgress,
                    new ProgressUpdate(1, 1, "dependency_index_ready")).ConfigureAwait(false);
                cancellationToken.ThrowIfCancellationRequested();
                return existing;
            }
            catch
            {
                existing.Dispose();
                throw;
            }
        }

        var build = await Task.Run(
            () => Build(source, publishProgress, cancellationToken),
            CancellationToken.None).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        await PublishProgressAsync(
            publishProgress,
            new ProgressUpdate(0, 1, "dependency_index_write")).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        await WriteAsync(path, source, build, cancellationToken).ConfigureAwait(false);
        await PublishProgressAsync(
            publishProgress,
            new ProgressUpdate(1, 1, "dependency_index_write")).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        var rebuilt = Open(path, source);
        try
        {
            await PublishProgressAsync(
                publishProgress,
                new ProgressUpdate(1, 1, "dependency_index_ready")).ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();
            return rebuilt;
        }
        catch
        {
            rebuilt.Dispose();
            throw;
        }
    }

    public ArchiveDependencyLookupResult FindEntryIdsByBasename(
        ArchiveIndex source,
        string basename,
        int maximumResults = 32,
        CancellationToken cancellationToken = default) =>
        FindEntryIds(source, basename, maximumResults, _basenameRecordsOffset, stem: false, cancellationToken);

    public ArchiveDependencyLookupResult FindEntryIdsByStem(
        ArchiveIndex source,
        string stem,
        int maximumResults = 256,
        CancellationToken cancellationToken = default) =>
        FindEntryIds(source, stem, maximumResults, _stemRecordsOffset, stem: true, cancellationToken);

    public ArchiveFacetsResult CreateFacets(string sessionId)
    {
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
        return new ArchiveFacetsResult(sessionId, Extensions, Packages, Roles, Categories);
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 0)
        {
            _view.Dispose();
            _mapping.Dispose();
        }
    }

    private ArchiveDependencyLookupResult FindEntryIds(
        ArchiveIndex source,
        string value,
        int maximumResults,
        long recordsOffset,
        bool stem,
        CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
        ArgumentNullException.ThrowIfNull(source);
        ArgumentException.ThrowIfNullOrWhiteSpace(value);
        if (maximumResults < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(maximumResults));
        }

        var normalized = NormalizeBasename(value);
        var hash = HashNormalized(normalized);
        long low = 0;
        long high = RecordCount;
        while (low < high)
        {
            var middle = low + (high - low) / 2;
            if (ReadHash(recordsOffset, middle) < hash)
            {
                low = middle + 1;
            }
            else
            {
                high = middle;
            }
        }

        var ids = new List<long>(Math.Min(maximumResults, 8));
        for (var recordId = low; recordId < RecordCount; recordId++)
        {
            if ((recordId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }
            if (ReadHash(recordsOffset, recordId) != hash)
            {
                break;
            }
            var entryId = checked((long)_view.ReadUInt64(checked(recordsOffset + recordId * RecordSize + 8)));
            var entry = source.ReadEntry(entryId);
            var candidate = stem ? NormalizeStem(entry.Path) : NormalizeBasename(entry.Path);
            if (!string.Equals(candidate, normalized, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            if (ids.Count >= maximumResults)
            {
                return new ArchiveDependencyLookupResult(ids, Truncated: true);
            }
            ids.Add(entryId);
        }
        return new ArchiveDependencyLookupResult(ids, Truncated: false);
    }

    private static ArchiveDependencyIndex Open(string path, ArchiveIndex source)
    {
        var fullPath = System.IO.Path.GetFullPath(path);
        var stream = new FileStream(fullPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        try
        {
            if (stream.Length < HeaderSize)
            {
                throw new InvalidDataException("Archive dependency index is smaller than its header.");
            }
            var header = new byte[HeaderSize];
            stream.ReadExactly(header);
            var version = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(8));
            var recordSize = BinaryPrimitives.ReadUInt32LittleEndian(header.AsSpan(12));
            var recordCount = checked((long)BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(16)));
            var basenameRecordsOffset = checked((long)BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(24)));
            var stemRecordsOffset = checked((long)BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(32)));
            var facetsOffset = checked((long)BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(40)));
            var facetsSize = checked((long)BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(48)));
            var sourceEntryCount = checked((long)BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(56)));
            var sourceFileSize = checked((long)BinaryPrimitives.ReadUInt64LittleEndian(header.AsSpan(64)));
            var recordsBytes = checked(recordCount * RecordSize);
            if (!header.AsSpan(0, Magic.Length).SequenceEqual(Magic)
                || version != Version
                || recordSize != RecordSize
                || recordCount != source.EntryCount
                || sourceEntryCount != source.EntryCount
                || sourceFileSize != new FileInfo(source.Path).Length
                || basenameRecordsOffset != HeaderSize
                || stemRecordsOffset != checked(basenameRecordsOffset + recordsBytes)
                || facetsOffset != checked(stemRecordsOffset + recordsBytes)
                || facetsSize < 0
                || facetsSize > MaximumFacetBytes
                || facetsOffset > stream.Length
                || facetsSize != stream.Length - facetsOffset)
            {
                throw new InvalidDataException("Archive dependency index does not match its source archive index.");
            }

            stream.Position = facetsOffset;
            var facetBytes = new byte[checked((int)facetsSize)];
            stream.ReadExactly(facetBytes);
            IReadOnlyList<ArchiveFacet> extensions;
            IReadOnlyList<ArchiveFacet> packages;
            IReadOnlyList<ArchiveFacet> roles;
            IReadOnlyList<ArchiveFacet> categories;
            using (var facetStream = new MemoryStream(facetBytes, writable: false))
            using (var reader = new BinaryReader(facetStream, Encoding.UTF8, leaveOpen: false))
            {
                extensions = ReadFacets(reader, recordCount);
                packages = ReadFacets(reader, recordCount);
                roles = ReadFacets(reader, recordCount);
                categories = ReadFacets(reader, recordCount);
                if (facetStream.Position != facetStream.Length)
                {
                    throw new InvalidDataException("Archive dependency index facet data has trailing bytes.");
                }
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
                return new ArchiveDependencyIndex(
                    fullPath,
                    mapping,
                    view,
                    recordCount,
                    basenameRecordsOffset,
                    stemRecordsOffset,
                    extensions,
                    packages,
                    roles,
                    categories);
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

    private static DependencyIndexBuild Build(
        ArchiveIndex source,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        if (source.EntryCount > Array.MaxLength)
        {
            throw new InvalidDataException("Archive contains too many entries for the dependency lookup index.");
        }
        var count = checked((int)source.EntryCount);
        var basenameRecords = new LookupRecord[count];
        var stemRecords = new LookupRecord[count];
        var extensions = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        var packages = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        var roles = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        var categories = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        var packageLabels = new Dictionary<ArchiveIndexStringRange, string>();
        var pathBuffer = new byte[1024];
        publishProgress?.Invoke(new ProgressUpdate(
            0,
            source.EntryCount,
            "dependency_index_records")).GetAwaiter().GetResult();
        cancellationToken.ThrowIfCancellationRequested();
        for (long entryId = 0; entryId < source.EntryCount; entryId++)
        {
            if (entryId > 0 && (entryId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                publishProgress?.Invoke(new ProgressUpdate(
                    entryId,
                    source.EntryCount,
                    "dependency_index_records")).GetAwaiter().GetResult();
                cancellationToken.ThrowIfCancellationRequested();
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
            var path = pathBuffer.AsSpan(0, length);
            basenameRecords[checked((int)entryId)] = new LookupRecord(HashBasename(path), entryId);
            stemRecords[checked((int)entryId)] = new LookupRecord(HashStem(path), entryId);

            var virtualPath = Encoding.UTF8.GetString(path).Replace('\\', '/').Trim('/');
            var extension = System.IO.Path.GetExtension(virtualPath).ToLowerInvariant();
            var role = ArchiveEntryClassifier.Classify(virtualPath, extension);
            var category = ArchiveEntryClassifier.ClassifyExtensionCategory(extension);
            var pamtRange = source.GetPamtPathRange(entryId);
            if (!packageLabels.TryGetValue(pamtRange, out var package))
            {
                package = ArchiveEntryClassifier.PackageLabel(source.ReadString(pamtRange));
                if (packageLabels.Count < 8_192)
                {
                    packageLabels[pamtRange] = package;
                }
            }
            Increment(extensions, extension);
            Increment(packages, package);
            Increment(roles, role.ToString());
            Increment(categories, category.ToString());
        }
        cancellationToken.ThrowIfCancellationRequested();
        publishProgress?.Invoke(new ProgressUpdate(
            source.EntryCount,
            source.EntryCount,
            "dependency_index_records")).GetAwaiter().GetResult();
        publishProgress?.Invoke(new ProgressUpdate(
            0,
            1,
            "dependency_index_sort")).GetAwaiter().GetResult();
        cancellationToken.ThrowIfCancellationRequested();
        Parallel.Invoke(
            new ParallelOptions { MaxDegreeOfParallelism = 2 },
            () => Array.Sort(basenameRecords, LookupRecordComparer.Instance),
            () => Array.Sort(stemRecords, LookupRecordComparer.Instance));
        cancellationToken.ThrowIfCancellationRequested();
        publishProgress?.Invoke(new ProgressUpdate(
            1,
            1,
            "dependency_index_sort")).GetAwaiter().GetResult();
        return new DependencyIndexBuild(
            basenameRecords,
            stemRecords,
            extensions,
            packages,
            roles,
            categories);
    }

    private static async Task WriteAsync(
        string destination,
        ArchiveIndex source,
        DependencyIndexBuild build,
        CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(destination)
            ?? throw new InvalidDataException("Archive dependency index destination has no parent directory."));
        var facets = BuildFacetPayload(build);
        var recordsBytes = checked((long)build.BasenameRecords.Length * RecordSize);
        var basenameRecordsOffset = HeaderSize;
        var stemRecordsOffset = checked(basenameRecordsOffset + recordsBytes);
        var facetsOffset = checked(stemRecordsOffset + recordsBytes);
        var header = new byte[HeaderSize];
        Magic.CopyTo(header, 0);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(8), Version);
        BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(12), RecordSize);
        BinaryPrimitives.WriteUInt64LittleEndian(header.AsSpan(16), checked((ulong)build.BasenameRecords.Length));
        BinaryPrimitives.WriteUInt64LittleEndian(header.AsSpan(24), checked((ulong)basenameRecordsOffset));
        BinaryPrimitives.WriteUInt64LittleEndian(header.AsSpan(32), checked((ulong)stemRecordsOffset));
        BinaryPrimitives.WriteUInt64LittleEndian(header.AsSpan(40), checked((ulong)facetsOffset));
        BinaryPrimitives.WriteUInt64LittleEndian(header.AsSpan(48), checked((ulong)facets.Length));
        BinaryPrimitives.WriteUInt64LittleEndian(header.AsSpan(56), checked((ulong)source.EntryCount));
        BinaryPrimitives.WriteUInt64LittleEndian(header.AsSpan(64), checked((ulong)new FileInfo(source.Path).Length));

        var staging = System.IO.Path.Combine(
            System.IO.Path.GetDirectoryName(destination)!,
            $".{System.IO.Path.GetFileName(destination)}.{Guid.NewGuid():N}.tmp");
        try
        {
            await using (var stream = new FileStream(
                staging,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                WriteBufferSize,
                FileOptions.Asynchronous | FileOptions.SequentialScan))
            {
                await stream.WriteAsync(header, cancellationToken).ConfigureAwait(false);
                await WriteRecordsAsync(stream, build.BasenameRecords, cancellationToken).ConfigureAwait(false);
                await WriteRecordsAsync(stream, build.StemRecords, cancellationToken).ConfigureAwait(false);
                await stream.WriteAsync(facets, cancellationToken).ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
                stream.Flush(flushToDisk: true);
            }
            cancellationToken.ThrowIfCancellationRequested();
            File.Move(staging, destination, overwrite: true);
        }
        finally
        {
            TryDelete(staging);
        }
    }

    private static Task PublishProgressAsync(
        Func<ProgressUpdate, Task>? publishProgress,
        ProgressUpdate update) => publishProgress is null ? Task.CompletedTask : publishProgress(update);

    private static async Task WriteRecordsAsync(
        Stream stream,
        IReadOnlyList<LookupRecord> records,
        CancellationToken cancellationToken)
    {
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

    private static byte[] BuildFacetPayload(DependencyIndexBuild build)
    {
        using var stream = new MemoryStream();
        using (var writer = new BinaryWriter(stream, Encoding.UTF8, leaveOpen: true))
        {
            WriteFacets(writer, build.Extensions);
            WriteFacets(writer, build.Packages);
            WriteFacets(writer, build.Roles);
            WriteFacets(writer, build.Categories);
        }
        if (stream.Length > MaximumFacetBytes)
        {
            throw new InvalidDataException("Archive dependency facet payload exceeded its safety bound.");
        }
        return stream.ToArray();
    }

    private static void WriteFacets(BinaryWriter writer, IReadOnlyDictionary<string, long> facets)
    {
        writer.Write(facets.Count);
        foreach (var pair in facets.OrderBy(static pair => pair.Key, StringComparer.OrdinalIgnoreCase))
        {
            writer.Write(pair.Key);
            writer.Write(pair.Value);
        }
    }

    private static IReadOnlyList<ArchiveFacet> ReadFacets(BinaryReader reader, long entryCount)
    {
        var count = reader.ReadInt32();
        if (count < 0 || count > entryCount + 1)
        {
            throw new InvalidDataException("Archive dependency facet count is invalid.");
        }
        var facets = new ArchiveFacet[count];
        for (var index = 0; index < count; index++)
        {
            var key = reader.ReadString();
            var value = reader.ReadInt64();
            if (value < 0 || value > entryCount)
            {
                throw new InvalidDataException("Archive dependency facet value is invalid.");
            }
            facets[index] = new ArchiveFacet(key, key, value);
        }
        return facets
            .OrderByDescending(static facet => facet.Count)
            .ThenBy(static facet => facet.Key, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    private ulong ReadHash(long recordsOffset, long recordId) =>
        _view.ReadUInt64(checked(recordsOffset + recordId * RecordSize));

    private static void Increment(IDictionary<string, long> counts, string key)
    {
        counts.TryGetValue(key, out var current);
        counts[key] = current + 1;
    }

    private static string NormalizeBasename(string value)
    {
        var normalized = value.Replace('\\', '/').Trim('/');
        var slash = normalized.LastIndexOf('/');
        return (slash >= 0 ? normalized[(slash + 1)..] : normalized).ToLowerInvariant();
    }

    private static string NormalizeStem(string value)
    {
        var basename = NormalizeBasename(value);
        var dot = basename.LastIndexOf('.');
        return dot >= 0 ? basename[..dot] : basename;
    }

    private static ulong HashNormalized(string value)
    {
        var bytes = Encoding.UTF8.GetBytes(value);
        return HashRange(bytes, 0, bytes.Length);
    }

    internal static ulong HashBasename(ReadOnlySpan<byte> path)
    {
        var start = BasenameStart(path);
        return HashRange(path, start, path.Length);
    }

    internal static ulong HashStem(ReadOnlySpan<byte> path)
    {
        var start = BasenameStart(path);
        var end = path.Length;
        for (var index = start; index < path.Length; index++)
        {
            if (path[index] == (byte)'.')
            {
                end = index;
            }
        }
        return HashRange(path, start, end);
    }

    private static int BasenameStart(ReadOnlySpan<byte> path)
    {
        var start = 0;
        for (var index = 0; index < path.Length; index++)
        {
            if (path[index] is (byte)'/' or (byte)'\\')
            {
                start = index + 1;
            }
        }
        return start;
    }

    private static ulong HashRange(ReadOnlySpan<byte> value, int start, int end)
    {
        const ulong offsetBasis = 14695981039346656037UL;
        const ulong prime = 1099511628211UL;
        var hash = offsetBasis;
        for (var index = start; index < end; index++)
        {
            var current = value[index];
            if (current is >= (byte)'A' and <= (byte)'Z')
            {
                current = checked((byte)(current + ('a' - 'A')));
            }
            hash ^= current;
            hash *= prime;
        }
        return hash;
    }

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // A later generation prune can remove an abandoned staging file.
        }
    }

    private readonly record struct LookupRecord(ulong Hash, long EntryId);

    private sealed class LookupRecordComparer : IComparer<LookupRecord>
    {
        public static LookupRecordComparer Instance { get; } = new();

        public int Compare(LookupRecord left, LookupRecord right)
        {
            var hash = left.Hash.CompareTo(right.Hash);
            return hash != 0 ? hash : left.EntryId.CompareTo(right.EntryId);
        }
    }

    private sealed record DependencyIndexBuild(
        LookupRecord[] BasenameRecords,
        LookupRecord[] StemRecords,
        IReadOnlyDictionary<string, long> Extensions,
        IReadOnlyDictionary<string, long> Packages,
        IReadOnlyDictionary<string, long> Roles,
        IReadOnlyDictionary<string, long> Categories);
}

internal sealed record ArchiveDependencyLookupResult(
    IReadOnlyList<long> EntryIds,
    bool Truncated);
