using Cdmw.ArchiveLite.Contracts;
using System.Text.Json;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveExportService(
    ArchiveSessionManager sessions,
    ArchiveQueryService queries,
    NativeArchiveCore native,
    NativeModelExportService modelExports)
{
    private const int MaximumReturnedItems = 500;
    private const int MaximumReturnedItemBytes = 512 * 1024;

    public async Task<ExportPlanResult> ExportAsync(
        ExportPlanRequest request,
        Func<ProgressUpdate, Task>? progress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (request.Kind is not (ExportKind.RawEntries
            or ExportKind.FolderTree
            or ExportKind.FilteredEntries
            or ExportKind.ManifestOnly
            or ExportKind.Obj
            or ExportKind.Fbx
            or ExportKind.Glb))
        {
            throw new NotSupportedException($"Archive Lite does not support the {request.Kind} export format.");
        }
        if (request.Kind == ExportKind.FolderTree && string.IsNullOrWhiteSpace(request.FolderPath))
        {
            throw new InvalidDataException("A folder-tree export requires an archive folder path.");
        }
        if (request.Kind != ExportKind.FolderTree && !string.IsNullOrWhiteSpace(request.FolderPath))
        {
            throw new InvalidDataException("An archive folder path is only valid for a folder-tree export.");
        }
        var destination = Path.GetFullPath(request.Destination);
        var items = new List<ExportItemResult>();
        var outputPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var archiveEntries = ResolveArchiveEntries(request, cancellationToken);
        var loosePaths = request.LoosePaths?.Distinct(StringComparer.OrdinalIgnoreCase).ToArray() ?? [];
        var isMeshExport = NativeModelExportService.SupportsFormat(request.Kind);
        string? singleOutputPath = null;
        if (!string.IsNullOrWhiteSpace(request.SingleOutputPath))
        {
            if ((request.Kind != ExportKind.RawEntries && !isMeshExport)
                || archiveEntries.Count != 1
                || loosePaths.Length != 0)
            {
                throw new InvalidDataException("An explicit output file is only valid for one selected archive entry.");
            }
            singleOutputPath = Path.GetFullPath(request.SingleOutputPath);
            if (!ExportPathPolicy.IsWithinOrEqual(destination, singleOutputPath)
                || singleOutputPath.Equals(destination, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("The explicit output file must be inside the selected export directory.");
            }
            if (isMeshExport && !Path.GetExtension(singleOutputPath).Equals(
                NativeModelExportService.FileExtension(request.Kind),
                StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("The explicit mesh output extension does not match the selected format.");
            }
        }
        else if (isMeshExport && loosePaths.Length != 0)
        {
            throw new InvalidDataException("Mesh interchange export is only supported for archive entries.");
        }
        ArchiveSession? archiveSession = null;
        if (!string.IsNullOrWhiteSpace(request.SessionId))
        {
            archiveSession = sessions.GetRequired(request.SessionId);
            if (Directory.Exists(archiveSession.PackageRoot) && ExportPathPolicy.IsWithinOrEqual(archiveSession.PackageRoot, destination))
            {
                throw new InvalidDataException("Export destination must be outside the source archive tree.");
            }
        }
        if (!string.IsNullOrWhiteSpace(request.LooseSourceRoot) &&
            Directory.Exists(request.LooseSourceRoot) &&
            ExportPathPolicy.IsWithinOrEqual(request.LooseSourceRoot, destination))
        {
            throw new InvalidDataException("Export destination must be outside the loose search source.");
        }
        Directory.CreateDirectory(destination);
        var requested = archiveEntries.Count + loosePaths.LongLength;
        long completed = 0;
        long exported = 0;
        long skipped = 0;
        long failed = 0;
        long outcomeCount = 0;
        var returnedItemBytes = 0;
        var cancelled = false;

        if (archiveSession is not null)
        {
            var currentFingerprint = await ArchiveFingerprint.ComputeAsync(archiveSession!.PackageRoot, cancellationToken).ConfigureAwait(false);
            if (!currentFingerprint.Value.Equals(archiveSession.Fingerprint, StringComparison.Ordinal))
            {
                throw new InvalidDataException("The archive changed after it was opened. Refresh before exporting.");
            }
        }

        await using var manifestWriter = ExportManifestWriter.Create(
            destination,
            request.ManifestFormat,
            archiveSession?.Fingerprint);
        if (manifestWriter is not null)
        {
            outputPaths.Add(manifestWriter.DestinationPath);
        }

        void RecordOutcome(ExportOutcome outcome)
        {
            outcomeCount++;
            switch (outcome.Item.Status)
            {
                case "exported": exported++; break;
                case "skipped": skipped++; break;
                case "failed": failed++; break;
            }
            if (items.Count < MaximumReturnedItems)
            {
                var itemBytes = JsonSerializer.SerializeToUtf8Bytes(outcome.Item, WorkerProtocol.JsonOptions).Length;
                if (returnedItemBytes + itemBytes <= MaximumReturnedItemBytes)
                {
                    items.Add(outcome.Item);
                    returnedItemBytes += itemBytes;
                }
            }
        }

        foreach (var entry in archiveEntries.Entries)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (completed == 0 || completed % 64 == 0)
            {
                await PublishProgressAsync(progress, new ProgressUpdate(completed, requested, "export", entry.Path)).ConfigureAwait(false);
            }
            var relative = BuildArchiveOutputRelativePath(entry);
            var outputRelative = isMeshExport
                ? ExportPathPolicy.NormalizeVirtualPath(Path.ChangeExtension(relative, NativeModelExportService.FileExtension(request.Kind)))
                : relative;
            var target = singleOutputPath ?? ExportPathPolicy.ResolveContainedPath(destination, outputRelative);
            if (singleOutputPath is not null)
            {
                outputRelative = ExportPathPolicy.NormalizeVirtualPath(
                    Path.GetRelativePath(destination, singleOutputPath).Replace('\\', '/'));
            }
            EnsureArchiveSourceIsNotTarget(archiveSession!, target);
            ExportPathPolicy.PrepareContainedOutputPath(destination, target);
            var outcome = await ExportArchiveEntryAsync(
                archiveSession!,
                entry,
                target,
                outputRelative,
                request,
                outputPaths,
                progress,
                cancellationToken).ConfigureAwait(false);
            RecordOutcome(outcome);
            completed++;
            if (outcome.Cancelled)
            {
                cancelled = true;
                break;
            }
            if (outcome.Exported)
            {
                manifestWriter?.AddArchive(ToManifestEntry(entry, outputRelative));
            }
        }

        if (!cancelled && loosePaths.Length > 0)
        {
            foreach (var loosePath in loosePaths)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (completed == 0 || completed % 64 == 0)
                {
                    await PublishProgressAsync(progress, new ProgressUpdate(completed, requested, "export", loosePath)).ConfigureAwait(false);
                }
                var outcome = await ExportLooseFileAsync(loosePath, destination, request, outputPaths, cancellationToken).ConfigureAwait(false);
                RecordOutcome(outcome);
                completed++;
                if (outcome.Cancelled)
                {
                    cancelled = true;
                    break;
                }
                if (outcome.Exported && outcome.Item.OutputPath is { } looseOutput && !string.IsNullOrWhiteSpace(request.LooseSourceRoot))
                {
                    var source = ExportPathPolicy.ResolveContainedPath(request.LooseSourceRoot, looseOutput);
                    manifestWriter?.AddLoose(new ArchiveLiteLooseManifestEntry(looseOutput, new FileInfo(source).Length, looseOutput));
                }
            }
        }

        string? manifestPath = manifestWriter?.DestinationPath;
        if (manifestWriter is not null)
        {
            await manifestWriter.CompleteAsync(cancellationToken).ConfigureAwait(false);
        }
        await PublishProgressAsync(progress, new ProgressUpdate(completed, requested, "complete")).ConfigureAwait(false);
        return new ExportPlanResult(requested, exported, skipped, failed, cancelled, manifestPath, items, outcomeCount > items.Count);
    }

    private static async Task PublishProgressAsync(
        Func<ProgressUpdate, Task>? progress,
        ProgressUpdate update)
    {
        if (progress is null)
        {
            return;
        }
        await progress(update).ConfigureAwait(false);
    }

    private ArchiveEntrySet ResolveArchiveEntries(ExportPlanRequest request, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(request.SessionId)) return new ArchiveEntrySet(0, []);
        var session = sessions.GetRequired(request.SessionId);
        if (request.Kind == ExportKind.FilteredEntries)
        {
            var (query, total) = session.GetLastQuery();
            return new ArchiveEntrySet(
                total,
                queries.EnumerateMatchingEntries(session, query, cancellationToken));
        }
        if (request.Kind == ExportKind.FolderTree)
        {
            var folder = ExportPathPolicy.NormalizeVirtualPath(request.FolderPath!);
            var query = new ArchiveQuerySpec(
                session.Id,
                Folder: folder,
                ViewMode: ArchiveViewMode.Flat,
                SortField: ArchiveSortField.Path);
            var entryIds = queries
                .EnumerateMatchingEntries(session, query, cancellationToken)
                .Select(static entry => entry.EntryId)
                .ToArray();
            return new ArchiveEntrySet(
                entryIds.LongLength,
                entryIds.Select(session.Index.ReadEntry));
        }
        var ids = request.EntryIds.Distinct().ToArray();
        return new ArchiveEntrySet(ids.LongLength, ids.Select(session.Index.ReadEntry));
    }

    private static string BuildArchiveOutputRelativePath(ArchiveEntryDto entry)
    {
        var packageRoot = Path.GetFileName(Path.GetDirectoryName(entry.SourcePamt))?.Trim();
        if (string.IsNullOrWhiteSpace(packageRoot))
        {
            packageRoot = "package";
        }
        return ExportPathPolicy.NormalizeVirtualPath(
            $"{ExportPathPolicy.NormalizeVirtualPath(packageRoot)}/{ExportPathPolicy.NormalizeVirtualPath(entry.Path)}");
    }

    private async Task<ExportOutcome> ExportArchiveEntryAsync(
        ArchiveSession archiveSession,
        ArchiveEntryDto entry,
        string target,
        string relative,
        ExportPlanRequest request,
        HashSet<string> outputPaths,
        Func<ProgressUpdate, Task>? progress,
        CancellationToken cancellationToken)
    {
        var isMeshExport = NativeModelExportService.SupportsFormat(request.Kind);
        if (isMeshExport && !NativeModelPreviewService.Supports(entry.Extension))
        {
            return new ExportOutcome(
                new ExportItemResult(entry.Path, null, "failed", $"Mesh interchange export does not support {entry.Extension} files."),
                false,
                false);
        }
        var collision = CheckCollision(entry.Path, target, request.CollisionPolicy, outputPaths);
        if (collision is not null) return collision;
        try
        {
            if (request.Kind != ExportKind.ManifestOnly)
            {
                if (isMeshExport)
                {
                    await modelExports.ExportAsync(
                        archiveSession,
                        entry,
                        request.Kind,
                        target,
                        request.CollisionPolicy == ExportCollisionPolicy.Overwrite,
                        progress,
                        cancellationToken).ConfigureAwait(false);
                }
                else
                {
                    var decoded = await Task.Run(() => native.Decode(entry), cancellationToken).ConfigureAwait(false);
                    cancellationToken.ThrowIfCancellationRequested();
                    await AtomicFile.WriteAsync(
                        target,
                        async (stream, token) => await stream.WriteAsync(decoded.Bytes, token).ConfigureAwait(false),
                        cancellationToken,
                        overwrite: request.CollisionPolicy == ExportCollisionPolicy.Overwrite).ConfigureAwait(false);
                }
            }
            return new ExportOutcome(new ExportItemResult(entry.Path, relative, "exported", null), true, false);
        }
        catch (Exception exception) when (exception is IOException
            or UnauthorizedAccessException
            or NativeArchiveException
            or InvalidDataException
            or NotSupportedException
            or TimeoutException
            or InvalidOperationException
            or JsonException)
        {
            return new ExportOutcome(new ExportItemResult(entry.Path, null, "failed", exception.Message), false, false);
        }
    }

    private static async Task<ExportOutcome> ExportLooseFileAsync(
        string loosePath,
        string destination,
        ExportPlanRequest request,
        HashSet<string> outputPaths,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(request.LooseSourceRoot))
        {
            return new ExportOutcome(new ExportItemResult(loosePath, null, "failed", "Loose source root is missing."), false, false);
        }
        var sourceRoot = Path.GetFullPath(request.LooseSourceRoot);
        var relative = Path.IsPathRooted(loosePath) ? Path.GetRelativePath(sourceRoot, loosePath) : loosePath;
        string source;
        string target;
        try
        {
            source = ExportPathPolicy.ResolveContainedPath(sourceRoot, relative);
            target = ExportPathPolicy.ResolveContainedPath(destination, relative);
            if (ExportPathPolicy.IsWithinOrEqual(sourceRoot, target))
            {
                throw new InvalidDataException("Loose export target resolves inside the source tree.");
            }
            EnsureNoReparsePoints(sourceRoot, source);
            ExportPathPolicy.PrepareContainedOutputPath(destination, target);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or InvalidDataException)
        {
            return new ExportOutcome(new ExportItemResult(loosePath, null, "failed", exception.Message), false, false);
        }
        var collision = CheckCollision(loosePath, target, request.CollisionPolicy, outputPaths);
        if (collision is not null) return collision;
        try
        {
            await AtomicFile.WriteAsync(
                target,
                async (output, token) =>
                {
                    await using var input = new FileStream(
                        source,
                        FileMode.Open,
                        FileAccess.Read,
                        FileShare.ReadWrite | FileShare.Delete,
                        128 * 1024,
                        FileOptions.Asynchronous | FileOptions.SequentialScan);
                    await input.CopyToAsync(output, 128 * 1024, token).ConfigureAwait(false);
                },
                cancellationToken,
                overwrite: request.CollisionPolicy == ExportCollisionPolicy.Overwrite).ConfigureAwait(false);
            return new ExportOutcome(new ExportItemResult(loosePath, relative.Replace('\\', '/'), "exported", null), true, false);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return new ExportOutcome(new ExportItemResult(loosePath, null, "failed", exception.Message), false, false);
        }
    }

    private static ExportOutcome? CheckCollision(
        string source,
        string target,
        ExportCollisionPolicy policy,
        HashSet<string> outputPaths)
    {
        if (!outputPaths.Add(target))
        {
            return new ExportOutcome(new ExportItemResult(source, null, "skipped", "Another selected entry resolves to the same Windows path."), false, false);
        }
        if (!File.Exists(target)) return null;
        return policy switch
        {
            ExportCollisionPolicy.Skip => new ExportOutcome(new ExportItemResult(source, null, "skipped", "Destination already exists."), false, false),
            ExportCollisionPolicy.Cancel => new ExportOutcome(new ExportItemResult(source, null, "cancelled", "Destination already exists."), false, true),
            _ => null,
        };
    }

    private static ArchiveLiteManifestEntry ToManifestEntry(ArchiveEntryDto entry, string outputPath) => new(
        entry.Path,
        entry.Package,
        entry.SourcePamt,
        entry.PazFile,
        entry.PazIndex,
        entry.Offset,
        entry.StoredSize,
        entry.OriginalSize,
        entry.Flags,
        entry.CompressionType,
        entry.EncryptionType,
        entry.Role,
        outputPath);

    private static void EnsureNoReparsePoints(string root, string file)
    {
        FileSystemInfo? current = new FileInfo(file);
        while (current is not null && !current.FullName.Equals(root, StringComparison.OrdinalIgnoreCase))
        {
            if ((current.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException("Loose source path crosses a reparse point.");
            }
            current = current switch
            {
                FileInfo fileInfo => fileInfo.Directory,
                DirectoryInfo directoryInfo => directoryInfo.Parent,
                _ => null,
            };
        }
    }

    private static void EnsureArchiveSourceIsNotTarget(ArchiveSession session, string target)
    {
        if (Directory.Exists(session.PackageRoot) && ExportPathPolicy.IsWithinOrEqual(session.PackageRoot, target))
        {
            throw new InvalidDataException("Export target resolves inside the source archive tree.");
        }
        if (session.SourceFiles.Any(source => Path.GetFullPath(source).Equals(Path.GetFullPath(target), StringComparison.OrdinalIgnoreCase)))
        {
            throw new InvalidDataException("Export target resolves to an archive source file.");
        }
    }

    private sealed record ExportOutcome(ExportItemResult Item, bool Exported, bool Cancelled);
    private sealed record ArchiveEntrySet(long Count, IEnumerable<ArchiveEntryDto> Entries);
}
