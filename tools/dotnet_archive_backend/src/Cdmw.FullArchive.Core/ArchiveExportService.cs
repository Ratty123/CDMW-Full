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
        try
        {
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
                            TryDeleteFile(publishFiles[supersededIndex].StagedPath);
                            publishFiles.RemoveAt(supersededIndex);
                        }
                    }
                }

                var stagedPath = ExportPathPolicy.ResolveContainedPath(stagingRoot, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(stagedPath)!);
                var decoded = await Task.Run(() => native.Decode(entry), cancellationToken).ConfigureAwait(false);
                await WriteFileAsync(stagedPath, decoded.Bytes, cancellationToken).ConfigureAwait(false);
                publishFiles.Add(new PublishFile(entry, relative, stagedPath, finalPath));
                reservedFinalPaths.Add(finalPath);
                AddItem(items, new ArchiveExportItem(
                    entry.Path,
                    finalPath,
                    renamed ? "renamed" : "exported",
                    decoded.Note));
                if (progress is not null && ((index & 0x3F) == 0 || index + 1 == entryIds.Count))
                {
                    await progress(new ProgressUpdate(index + 1, entryIds.Count, "export_decode", entry.Path)).ConfigureAwait(false);
                }
            }

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
                await WriteJsonAsync(stagedManifest, manifest, cancellationToken).ConfigureAwait(false);
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
        finally
        {
            TryDeleteDirectory(stagingRoot);
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
                    if (StructurePath(session.ReadEntry(entryId)).StartsWith(folder, StringComparison.OrdinalIgnoreCase))
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

    private static async Task WriteFileAsync(
        string path,
        ReadOnlyMemory<byte> bytes,
        CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path,
            FileMode.CreateNew,
            FileAccess.Write,
            FileShare.None,
            128 * 1024,
            FileOptions.Asynchronous | FileOptions.WriteThrough);
        await stream.WriteAsync(bytes, cancellationToken).ConfigureAwait(false);
        await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
        stream.Flush(flushToDisk: true);
    }

    private static async Task WriteJsonAsync<T>(string path, T value, CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path,
            FileMode.CreateNew,
            FileAccess.Write,
            FileShare.None,
            64 * 1024,
            FileOptions.Asynchronous | FileOptions.WriteThrough);
        await JsonSerializer.SerializeAsync(stream, value, WorkerProtocol.JsonOptions, cancellationToken).ConfigureAwait(false);
        await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
        stream.Flush(flushToDisk: true);
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
