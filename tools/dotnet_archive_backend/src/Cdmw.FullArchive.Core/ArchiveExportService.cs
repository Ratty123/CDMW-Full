using System.Text.Json;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveExportService(
    ArchiveSessionManager sessions,
    ArchiveQueryService queries,
    ArchiveLookupService lookups,
    NativeArchiveCore native)
{
    private const int MaximumReportedItems = 4096;

    public async Task<ArchiveExportResult> ExportAsync(
        ArchiveExportRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(request.SessionId);
        var entryIds = await ResolveEntryIdsAsync(session, request, cancellationToken).ConfigureAwait(false);
        var destination = Path.TrimEndingDirectorySeparator(Path.GetFullPath(request.Destination));
        var parent = Path.GetDirectoryName(destination)
            ?? throw new InvalidDataException("Export destination has no parent directory.");
        RejectProtectedDestination(destination, session.PackageRoot, sessions.CacheRoot, request.ReplaceDestination);
        Directory.CreateDirectory(parent);
        var destinationName = Path.GetFileName(destination);
        if (string.IsNullOrWhiteSpace(destinationName))
        {
            throw new InvalidDataException("Export destination must be a specific folder beneath a filesystem root.");
        }
        if (File.Exists(destination))
        {
            throw new InvalidDataException("Export destination resolves to an existing file.");
        }

        var stagingRoot = Path.Combine(parent, $".{destinationName}.cdmw-export-{Guid.NewGuid():N}");
        var rollbackRoot = Path.Combine(parent, $".{destinationName}.cdmw-rollback-{Guid.NewGuid():N}");
        Directory.CreateDirectory(stagingRoot);
        var items = new List<ArchiveExportItem>(Math.Min(entryIds.Count, MaximumReportedItems));
        var publishFiles = new List<PublishFile>();
        var reservedFinalPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        long skipped = 0;
        var decodes = new ExportDecodePipeline(native, request.FlushToDisk, cancellationToken);
        try
        {
            // Before the first write: the staging folder is where it should be.
            RejectOpenedFolder(stagingRoot, destination, session.PackageRoot, sessions.CacheRoot, request.ReplaceDestination);
            if (progress is not null)
            {
                await progress(new ProgressUpdate(0, entryIds.Count, "export_decode")).ConfigureAwait(false);
            }
            for (var index = 0; index < entryIds.Count; index++)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var entry = session.ReadEntry(entryIds[index]);
                var relative = ExportRelativePath(entry, request.IncludePackageRoot);
                var finalPath = ExportPathPolicy.ResolveContainedPath(destination, relative);
                var collidesWithRequest = reservedFinalPaths.Contains(finalPath);
                var collidesWithDestination = !request.ReplaceDestination && File.Exists(finalPath);
                var renamed = false;
                if (request.CollisionPolicy == ArchiveExportCollisionPolicy.Rename &&
                    (collidesWithRequest || collidesWithDestination))
                {
                    finalPath = FindAvailableOutputPath(
                        destination,
                        finalPath,
                        reservedFinalPaths,
                        considerExisting: !request.ReplaceDestination);
                    relative = Path.GetRelativePath(destination, finalPath).Replace('\\', '/');
                    renamed = true;
                    collidesWithRequest = false;
                    collidesWithDestination = false;
                }
                if (collidesWithRequest || collidesWithDestination)
                {
                    if (request.CollisionPolicy == ArchiveExportCollisionPolicy.Cancel)
                    {
                        await decodes.DrainAsync(items, progress, entryIds.Count).ConfigureAwait(false);
                        return Result(session.Id, entryIds.Count, 0, 0, 0, cancelled: true, null, items);
                    }
                    if (request.CollisionPolicy == ArchiveExportCollisionPolicy.Skip)
                    {
                        skipped++;
                        AddItem(items, new ArchiveExportItem(entry.Path, finalPath, "skipped", "destination exists"));
                        continue;
                    }
                    if (collidesWithRequest)
                    {
                        var supersededIndex = publishFiles.FindIndex(file =>
                            file.Entry is not null && file.FinalPath.Equals(finalPath, StringComparison.OrdinalIgnoreCase));
                        if (supersededIndex >= 0)
                        {
                            // The superseded file may still be decoding or writing.
                            await decodes.DrainAsync(items, progress, entryIds.Count).ConfigureAwait(false);
                            TryDeleteFile(publishFiles[supersededIndex].StagedPath);
                            publishFiles.RemoveAt(supersededIndex);
                        }
                    }
                }

                var stagedPath = ExportPathPolicy.ResolveContainedPath(stagingRoot, relative);
                publishFiles.Add(new PublishFile(entry, relative, stagedPath, finalPath));
                reservedFinalPaths.Add(finalPath);
                // The item keeps its place in the report; its decode note is filled in
                // when the entry has been decoded and staged.
                var itemSlot = items.Count <= MaximumReportedItems ? items.Count : -1;
                var item = new ArchiveExportItem(entry.Path, finalPath, renamed ? "renamed" : "exported");
                AddItem(items, item);
                await decodes.EnqueueAsync(
                    new ExportJob(entry, stagedPath, index, itemSlot, item),
                    items,
                    progress,
                    entryIds.Count).ConfigureAwait(false);
            }
            await decodes.DrainAsync(items, progress, entryIds.Count).ConfigureAwait(false);

            string? manifestRelativePath = null;
            if (request.WriteManifest)
            {
                manifestRelativePath = "cdmw-export-manifest.json";
                var finalManifest = Path.Combine(destination, manifestRelativePath);
                if (request.CollisionPolicy == ArchiveExportCollisionPolicy.Rename &&
                    (reservedFinalPaths.Contains(finalManifest) || (!request.ReplaceDestination && File.Exists(finalManifest))))
                {
                    finalManifest = FindAvailableOutputPath(
                        destination,
                        finalManifest,
                        reservedFinalPaths,
                        considerExisting: !request.ReplaceDestination);
                    manifestRelativePath = Path.GetRelativePath(destination, finalManifest).Replace('\\', '/');
                }
                var stagedManifest = Path.Combine(stagingRoot, manifestRelativePath);
                Directory.CreateDirectory(Path.GetDirectoryName(stagedManifest)!);
                var manifest = new ArchiveExportManifest(
                    "cdmw_full_archive_export_v2",
                    session.Fingerprint,
                    DateTimeOffset.UtcNow,
                    publishFiles.Where(static item => item.Entry is not null).Select(static item =>
                    {
                        var entry = item.Entry!;
                        return new ArchiveExportManifestEntry(
                            entry.Path,
                            entry.Identity,
                            item.RelativePath,
                            entry.StoredSize,
                            entry.OriginalSize,
                            entry.Flags);
                    }).ToArray());
                await WriteJsonAsync(stagedManifest, manifest, request.FlushToDisk, cancellationToken).ConfigureAwait(false);
                if (!request.ReplaceDestination && File.Exists(finalManifest) &&
                    request.CollisionPolicy == ArchiveExportCollisionPolicy.Cancel)
                {
                    return Result(session.Id, entryIds.Count, 0, skipped, 0, cancelled: true, null, items);
                }
                if (request.ReplaceDestination || !File.Exists(finalManifest) ||
                    request.CollisionPolicy is ArchiveExportCollisionPolicy.Overwrite or ArchiveExportCollisionPolicy.Rename)
                {
                    publishFiles.Add(new PublishFile(null, manifestRelativePath, stagedManifest, finalManifest));
                    reservedFinalPaths.Add(finalManifest);
                }
                else
                {
                    manifestRelativePath = null;
                }
            }

            cancellationToken.ThrowIfCancellationRequested();
            if (progress is not null)
            {
                await progress(new ProgressUpdate(0, publishFiles.Count, "export_publish")).ConfigureAwait(false);
            }
            cancellationToken.ThrowIfCancellationRequested();
            // Right before the move or the first write into the destination.
            RejectOpenedFolder(stagingRoot, destination, session.PackageRoot, sessions.CacheRoot, request.ReplaceDestination);
            if (request.ReplaceDestination && Directory.Exists(destination))
            {
                PublishReplacingDestination(destination, stagingRoot, rollbackRoot);
            }
            else if (!Directory.Exists(destination))
            {
                Directory.Move(stagingRoot, destination);
            }
            else
            {
                PublishIntoExistingDestination(destination, rollbackRoot, publishFiles);
            }
            TryDeleteDirectory(rollbackRoot);
            var manifestPath = manifestRelativePath is not null
                ? ExportPathPolicy.ResolveContainedPath(destination, manifestRelativePath)
                : null;
            if (progress is not null)
            {
                await progress(new ProgressUpdate(publishFiles.Count, publishFiles.Count, "export_complete")).ConfigureAwait(false);
            }
            return Result(
                session.Id,
                entryIds.Count,
                publishFiles.LongCount(static item => item.Entry is not null),
                skipped,
                0,
                cancelled: false,
                manifestPath,
                items);
        }
        catch
        {
            // Nothing may still be writing into the staging folder when it is removed.
            await decodes.AbandonAsync().ConfigureAwait(false);
            throw;
        }
        finally
        {
            TryDeleteDirectory(stagingRoot);
        }
    }

    private sealed record ExportJob(ArchiveEntryDto Entry, string StagedPath, int Index, int ItemSlot, ArchiveExportItem Item);

    /// <summary>
    /// Decodes and stages entries a few at a time. Each staged file is still written
    /// and flushed on its own, but several are in flight at once; results are taken
    /// in request order, so the report, progress and the first failure match a
    /// one-at-a-time export.
    /// </summary>
    private sealed class ExportDecodePipeline(NativeArchiveCore native, bool flushToDisk, CancellationToken cancellationToken)
    {
        private readonly Queue<(ExportJob Job, Task<string> Note)> _pending = new();
        private readonly SemaphoreSlim _slots = new(ArchiveParallel.DegreeOfParallelism, ArchiveParallel.DegreeOfParallelism);
        private readonly CancellationTokenSource _abandon = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);

        public async Task EnqueueAsync(
            ExportJob job,
            List<ArchiveExportItem> items,
            Func<ProgressUpdate, Task>? progress,
            int total)
        {
            _pending.Enqueue((job, RunAsync(job)));
            // Bound the decoded bytes held in memory.
            while (_pending.Count > ArchiveParallel.DegreeOfParallelism * 2)
            {
                await CompleteOldestAsync(items, progress, total).ConfigureAwait(false);
            }
        }

        public async Task DrainAsync(List<ArchiveExportItem> items, Func<ProgressUpdate, Task>? progress, int total)
        {
            while (_pending.Count > 0)
            {
                await CompleteOldestAsync(items, progress, total).ConfigureAwait(false);
            }
        }

        public async Task AbandonAsync()
        {
            _abandon.Cancel();
            while (_pending.TryDequeue(out var pending))
            {
                try
                {
                    await pending.Note.ConfigureAwait(false);
                }
                catch
                {
                    // The export is already failing; only the first failure is reported.
                }
            }
        }

        private async Task CompleteOldestAsync(List<ArchiveExportItem> items, Func<ProgressUpdate, Task>? progress, int total)
        {
            var (job, noteTask) = _pending.Peek();
            string note;
            try
            {
                note = await noteTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw new OperationCanceledException(cancellationToken);
            }
            _pending.Dequeue();
            if (job.ItemSlot >= 0)
            {
                items[job.ItemSlot] = job.Item with { Message = note };
            }
            if (progress is not null && ((job.Index & 0x3F) == 0 || job.Index + 1 == total))
            {
                await progress(new ProgressUpdate(job.Index + 1, total, "export_decode", job.Entry.Path)).ConfigureAwait(false);
            }
        }

        private async Task<string> RunAsync(ExportJob job)
        {
            await _slots.WaitAsync(_abandon.Token).ConfigureAwait(false);
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(job.StagedPath)!);
                var decoded = await Task.Run(() => native.Decode(job.Entry), _abandon.Token).ConfigureAwait(false);
                await WriteFileAsync(job.StagedPath, decoded.Bytes, flushToDisk, _abandon.Token).ConfigureAwait(false);
                return decoded.Note;
            }
            finally
            {
                _slots.Release();
            }
        }
    }

    private async Task<IReadOnlyList<long>> ResolveEntryIdsAsync(
        ArchiveSession session,
        ArchiveExportRequest request,
        CancellationToken cancellationToken)
    {
        IReadOnlyList<long> resolved;
        switch (request.SelectionKind)
        {
            case ArchiveExportSelectionKind.EntryIds:
                resolved = (request.EntryIds ?? [])
                    .Where(id => id >= 0 && id < session.Index.EntryCount)
                    .Distinct()
                    .Order()
                    .ToArray();
                break;
            case ArchiveExportSelectionKind.Query:
                if (string.IsNullOrWhiteSpace(request.QueryId))
                {
                    throw new InvalidDataException("Filtered export requires a server-side query token.");
                }
                resolved = queries.GetEntryIds(session.Id, request.QueryId);
                break;
            case ArchiveExportSelectionKind.Folder:
                if (string.IsNullOrWhiteSpace(request.FolderPath))
                {
                    throw new InvalidDataException("Folder export requires a virtual folder path.");
                }
                // IncludePackageRoot picks the namespace the folder path is written in,
                // for matching as well as for the output layout. The browser's folder
                // tree is built on entry paths; the folder filter is built on
                // package-root paths. Matching only the latter silently exported
                // nothing for every folder the tree can name.
                var folder = request.FolderPath.Replace('\\', '/').Trim('/') + "/";
                var folderIds = new List<long>();
                var queryEntryIds = string.IsNullOrWhiteSpace(request.QueryId)
                    ? null
                    : queries.GetEntryIds(session.Id, request.QueryId);
                var candidateCount = queryEntryIds is null ? session.Index.EntryCount : queryEntryIds.Count;
                for (long candidateIndex = 0; candidateIndex < candidateCount; candidateIndex++)
                {
                    if ((candidateIndex & 0x1FFF) == 0)
                    {
                        cancellationToken.ThrowIfCancellationRequested();
                    }
                    var entryId = queryEntryIds is null
                        ? candidateIndex
                        : queryEntryIds[checked((int)candidateIndex)];
                    var hierarchyPath = request.IncludePackageRoot
                        ? StructurePath(session, entryId)
                        : session.Index.ReadEntryPath(entryId);
                    if (hierarchyPath.StartsWith(folder, StringComparison.OrdinalIgnoreCase))
                    {
                        folderIds.Add(entryId);
                    }
                }
                resolved = folderIds;
                break;
            case ArchiveExportSelectionKind.Family:
                if (request.FamilyEntryId is not { } familyEntryId)
                {
                    throw new InvalidDataException("Family export requires a seed entry id.");
                }
                var associated = await lookups.ResolveAssociationEntryIdsAsync(
                    session.Id,
                    familyEntryId,
                    cancellationToken).ConfigureAwait(false);
                resolved = associated
                    .Append(familyEntryId)
                    .Distinct()
                    .Order()
                    .ToArray();
                break;
            default:
                throw new InvalidDataException("The archive export selection kind is not supported.");
        }
        var extensions = (request.Extensions ?? [])
            .Select(NormalizeExtension)
            .Where(static value => !string.IsNullOrWhiteSpace(value))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (extensions.Count == 0)
        {
            return resolved;
        }
        var filtered = new List<long>();
        for (var index = 0; index < resolved.Count; index++)
        {
            if ((index & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }
            var entryId = resolved[index];
            if (extensions.Contains(session.ReadEntry(entryId).Extension))
            {
                filtered.Add(entryId);
            }
        }
        return filtered;
    }

    private static string NormalizeExtension(string value)
    {
        var normalized = value.Trim().ToLowerInvariant();
        return string.IsNullOrEmpty(normalized) || normalized.StartsWith('.') ? normalized : "." + normalized;
    }

    private static string ExportRelativePath(ArchiveEntryDto entry, bool includePackageRoot)
    {
        var relative = ExportPathPolicy.NormalizeVirtualPath(entry.Path);
        if (!includePackageRoot)
        {
            return relative;
        }
        return ExportPathPolicy.NormalizeVirtualPath($"{PackageRoot(entry)}/{relative}");
    }

    private static string StructurePath(ArchiveEntryDto entry)
    {
        return $"{PackageRoot(entry)}/{entry.Path.Trim('/')}";
    }

    private static string StructurePath(ArchiveSession session, long entryId) =>
        StructurePath(session.ReadEntry(entryId));

    private static string PackageRoot(ArchiveEntryDto entry)
    {
        var normalizedSource = entry.SourcePamt.Replace('/', Path.DirectorySeparatorChar);
        var packageRoot = Path.GetFileName(Path.GetDirectoryName(normalizedSource));
        if (string.IsNullOrWhiteSpace(packageRoot))
        {
            packageRoot = "package";
        }
        return packageRoot.Trim('/');
    }

    private static string FindAvailableOutputPath(
        string destination,
        string targetPath,
        IReadOnlySet<string> reservedPaths,
        bool considerExisting)
    {
        var parent = Path.GetDirectoryName(targetPath)!;
        var stem = Path.GetFileNameWithoutExtension(targetPath);
        var extension = Path.GetExtension(targetPath);
        for (var counter = 2; ; counter++)
        {
            var candidate = Path.Combine(parent, $"{stem}_{counter}{extension}");
            candidate = ExportPathPolicy.ResolveContainedPath(
                destination,
                Path.GetRelativePath(destination, candidate).Replace('\\', '/'));
            if (!reservedPaths.Contains(candidate) && (!considerExisting || !File.Exists(candidate)))
            {
                return candidate;
            }
        }
    }

    // CDMW never writes into a game installation. An export destination comes
    // from the request, and publishing it may move the folder there aside and
    // delete it (ReplaceDestination) or write over files in it (Overwrite), so
    // it may not be, hold or sit inside the archive source or the archive
    // cache, sit inside a game installation, or hold game archives; and no
    // folder on its path may be a link. Every check runs on the path as written
    // and on where it really leads (a junction on the way can point into the
    // game), and runs again on the folders actually opened before the first
    // write and before publishing (RejectOpenedFolder).
    internal static void RejectProtectedDestination(
        string destination,
        string packageRoot,
        string cacheRoot,
        bool replaceDestination)
    {
        try
        {
            if (GameFolderPolicy.HasLinkOnPath(destination))
            {
                throw new ExportDestinationRefusedException(
                    "Export destination's path goes through a link (a junction or symbolic link). Choose a folder whose path has no links, outside the game folder.");
            }
            var source = File.Exists(packageRoot) ? Path.GetDirectoryName(packageRoot) ?? packageRoot : packageRoot;
            var resolved = GameFolderPolicy.FinalPath(destination);
            var resolvedSource = GameFolderPolicy.FinalPath(source);
            var resolvedCache = GameFolderPolicy.FinalPath(cacheRoot);
            if (GameFolderPolicy.Overlaps(destination, source) || GameFolderPolicy.Overlaps(resolved, resolvedSource))
            {
                throw new ExportDestinationRefusedException(
                    "Export destination overlaps the archive source. CDMW does not write into the game folder; choose a folder outside it.");
            }
            if (GameFolderPolicy.Overlaps(destination, cacheRoot) || GameFolderPolicy.Overlaps(resolved, resolvedCache))
            {
                throw new ExportDestinationRefusedException("Export destination overlaps the archive cache; choose a folder outside it.");
            }
            if (GameFolderPolicy.IsInsideGameInstallation(resolved)
                || GameFolderPolicy.HoldsArchiveFiles(resolved)
                || (replaceDestination && Directory.Exists(resolved)
                    && Directory.EnumerateDirectories(resolved).Any(GameFolderPolicy.IsGameRoot)))
            {
                throw new ExportDestinationRefusedException(
                    "Export destination is inside a game installation or holds game archives. CDMW does not write into the game folder; choose a folder outside it.");
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            throw new ExportDestinationRefusedException($"Export destination could not be checked: {exception.Message}");
        }
    }

    // The folder an export has just opened or is about to publish into, checked
    // where it really is: nothing may have put a link on the way since the
    // destination was checked.
    internal static void RejectOpenedFolder(string folder, string destination, string packageRoot, string cacheRoot,
        bool replaceDestination)
    {
        RejectProtectedDestination(destination, packageRoot, cacheRoot, replaceDestination);
        try
        {
            var resolved = GameFolderPolicy.FinalPath(folder);
            var expected = GameFolderPolicy.FinalPath(Path.GetDirectoryName(Path.GetFullPath(destination))!);
            if (!string.Equals(Path.GetDirectoryName(resolved), expected, StringComparison.OrdinalIgnoreCase)
                || GameFolderPolicy.HasLinkOnPath(folder)
                || GameFolderPolicy.IsInsideGameInstallation(resolved))
            {
                throw new ExportDestinationRefusedException(
                    "Export destination changed while the export ran and now leads elsewhere. Nothing was published; choose a folder outside the game folder and export again.");
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            throw new ExportDestinationRefusedException($"Export destination could not be checked: {exception.Message}");
        }
    }

    private static void PublishReplacingDestination(
        string destination,
        string stagingRoot,
        string rollbackRoot)
    {
        Directory.Move(destination, rollbackRoot);
        try
        {
            Directory.Move(stagingRoot, destination);
        }
        catch
        {
            if (!Directory.Exists(destination) && Directory.Exists(rollbackRoot))
            {
                Directory.Move(rollbackRoot, destination);
            }
            throw;
        }
    }

    private static void PublishIntoExistingDestination(
        string destination,
        string rollbackRoot,
        IReadOnlyList<PublishFile> files)
    {
        Directory.CreateDirectory(rollbackRoot);
        var published = new List<PublishedFile>();
        var createdDirectories = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        try
        {
            foreach (var file in files)
            {
                var finalPath = ExportPathPolicy.ResolveContainedPath(destination, file.RelativePath);
                var parent = Path.GetDirectoryName(finalPath)!;
                TrackCreatedDirectories(destination, parent, createdDirectories);
                ExportPathPolicy.PrepareContainedOutputPath(destination, finalPath);
                string? backupPath = null;
                if (File.Exists(finalPath))
                {
                    backupPath = ExportPathPolicy.ResolveContainedPath(rollbackRoot, file.RelativePath);
                    Directory.CreateDirectory(Path.GetDirectoryName(backupPath)!);
                    File.Move(finalPath, backupPath);
                }
                try
                {
                    File.Move(file.StagedPath, finalPath);
                    published.Add(new PublishedFile(finalPath, backupPath));
                }
                catch
                {
                    if (backupPath is not null && File.Exists(backupPath) && !File.Exists(finalPath))
                    {
                        File.Move(backupPath, finalPath);
                    }
                    throw;
                }
            }
        }
        catch
        {
            foreach (var file in published.AsEnumerable().Reverse())
            {
                TryDeleteFile(file.FinalPath);
                if (file.BackupPath is not null && File.Exists(file.BackupPath))
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(file.FinalPath)!);
                    File.Move(file.BackupPath, file.FinalPath);
                }
            }
            foreach (var directory in createdDirectories.OrderByDescending(static path => path.Length))
            {
                TryDeleteEmptyDirectory(directory);
            }
            throw;
        }
    }

    private static void TrackCreatedDirectories(
        string root,
        string parent,
        HashSet<string> createdDirectories)
    {
        var missing = new Stack<string>();
        var current = parent;
        while (!current.Equals(root, StringComparison.OrdinalIgnoreCase) &&
               ExportPathPolicy.IsWithinOrEqual(root, current) &&
               !Directory.Exists(current))
        {
            missing.Push(current);
            current = Path.GetDirectoryName(current) ?? root;
        }
        foreach (var directory in missing)
        {
            createdDirectories.Add(directory);
        }
    }

    /// <summary>
    /// Writes a staged export file. With <paramref name="flushToDisk"/> (the default
    /// setting) the file is on disk before the export reports success; without it
    /// Windows writes it out shortly afterwards, so a power loss or system crash in
    /// that window can leave it empty or incomplete. The bytes are the same either way.
    /// </summary>
    private static async Task WriteFileAsync(
        string path,
        ReadOnlyMemory<byte> bytes,
        bool flushToDisk,
        CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path,
            FileMode.CreateNew,
            FileAccess.Write,
            FileShare.None,
            128 * 1024,
            flushToDisk ? FileOptions.Asynchronous | FileOptions.WriteThrough : FileOptions.Asynchronous);
        await stream.WriteAsync(bytes, cancellationToken).ConfigureAwait(false);
        await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
        if (flushToDisk)
        {
            stream.Flush(flushToDisk: true);
        }
    }

    private static async Task WriteJsonAsync<T>(string path, T value, bool flushToDisk, CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path,
            FileMode.CreateNew,
            FileAccess.Write,
            FileShare.None,
            64 * 1024,
            flushToDisk ? FileOptions.Asynchronous | FileOptions.WriteThrough : FileOptions.Asynchronous);
        await JsonSerializer.SerializeAsync(stream, value, WorkerProtocol.JsonOptions, cancellationToken).ConfigureAwait(false);
        await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
        if (flushToDisk)
        {
            stream.Flush(flushToDisk: true);
        }
    }

    private static ArchiveExportResult Result(
        string sessionId,
        long requested,
        long exported,
        long skipped,
        long failed,
        bool cancelled,
        string? manifestPath,
        IReadOnlyList<ArchiveExportItem> items) => new(
        sessionId,
        requested,
        exported,
        skipped,
        failed,
        cancelled,
        manifestPath,
        items.Take(MaximumReportedItems).ToArray(),
        items.Count > MaximumReportedItems);

    private static void AddItem(List<ArchiveExportItem> items, ArchiveExportItem item)
    {
        if (items.Count <= MaximumReportedItems)
        {
            items.Add(item);
        }
    }

    private static void TryDeleteFile(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // Rollback continues best effort and then surfaces the original publication failure.
        }
    }

    private static void TryDeleteEmptyDirectory(string path)
    {
        try
        {
            if (Directory.Exists(path) && !Directory.EnumerateFileSystemEntries(path).Any())
            {
                Directory.Delete(path);
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // Empty directory cleanup is best effort after rollback.
        }
    }

    private static void TryDeleteDirectory(string path)
    {
        try
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, recursive: true);
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // A later cleanup pass can remove an abandoned staging directory.
        }
    }

    private sealed record PublishFile(
        ArchiveEntryDto? Entry,
        string RelativePath,
        string StagedPath,
        string FinalPath);

    private sealed record PublishedFile(string FinalPath, string? BackupPath);
}

public sealed record ArchiveExportManifest(
    string Schema,
    string ArchiveFingerprint,
    DateTimeOffset CreatedUtc,
    IReadOnlyList<ArchiveExportManifestEntry> Entries);

public sealed record ArchiveExportManifestEntry(
    string Path,
    ArchiveDurableIdentity Identity,
    string OutputPath,
    long StoredSize,
    long OriginalSize,
    int Flags);
