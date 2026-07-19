using System.Collections.Concurrent;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveItemIconService(
    ArchiveSessionManager sessions,
    ArchiveItemNameIndexService catalogueBuilder,
    NativeArchiveCore native,
    NativeTexturePreviewService textures,
    ArchiveWorkPriority? workPriority = null)
{
    private const int MaximumVisibleBatch = 64;
    private const long MaximumIconBytes = 256L * 1024L * 1024L;
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _itemGates = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, NegativeIconCacheEntry> _negativeCache = new(StringComparer.Ordinal);
    private int _visibleRequestCount;

    public async Task<ItemIconBatchResult> LoadAsync(
        ItemIconBatchRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        ValidateThumbnailSize(request.ThumbnailSize);
        var itemIds = request.ItemIds
            .Distinct()
            .Take(MaximumVisibleBatch + 1)
            .ToArray();
        if (itemIds.Length > MaximumVisibleBatch)
        {
            throw new InvalidDataException($"An Item Finder icon request may contain at most {MaximumVisibleBatch} items.");
        }

        var (session, catalog) = await GetCatalogAsync(request.SessionId, cancellationToken).ConfigureAwait(false);
        Interlocked.Increment(ref _visibleRequestCount);
        try
        {
            using var concurrency = new SemaphoreSlim(3, 3);
            var tasks = itemIds.Select(async itemId =>
            {
                await concurrency.WaitAsync(cancellationToken).ConfigureAwait(false);
                try
                {
                    return await LoadOneSafeAsync(session, catalog, itemId, request.ThumbnailSize, cancellationToken).ConfigureAwait(false);
                }
                finally
                {
                    concurrency.Release();
                }
            });
            var results = await Task.WhenAll(tasks).ConfigureAwait(false);
            return new ItemIconBatchResult(request.SessionId, results);
        }
        finally
        {
            Interlocked.Decrement(ref _visibleRequestCount);
        }
    }

    public async Task<WarmItemIconsResult> WarmAsync(
        WarmItemIconsRequest request,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        ValidateThumbnailSize(request.ThumbnailSize);
        if (request.MaximumIcons < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(request.MaximumIcons));
        }
        var (session, catalog) = await GetCatalogAsync(request.SessionId, cancellationToken).ConfigureAwait(false);
        var priority = (request.PrioritizedItemIds ?? [])
            .Distinct()
            .ToArray();
        var prioritySet = priority.ToHashSet();
        var candidates = priority
            .Select(itemId => catalog.TryGet(itemId, out var item) ? item : null)
            .Concat(catalog.Items.Where(item => !prioritySet.Contains(item.ItemId)))
            .Where(static item => item is { IconPaths.Count: > 0 })
            .Cast<ArchiveItemCatalogRecord>();
        if (request.MaximumIcons > 0)
        {
            candidates = candidates.Take(request.MaximumIcons);
        }
        var items = candidates.ToArray();
        long ready = 0;
        long missing = 0;
        long failed = 0;
        for (var index = 0; index < items.Length; index++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            await WaitForVisibleRequestsAsync(cancellationToken).ConfigureAwait(false);
            var result = await LoadOneSafeAsync(
                session,
                catalog,
                items[index].ItemId,
                request.ThumbnailSize,
                cancellationToken).ConfigureAwait(false);
            if (!string.IsNullOrWhiteSpace(result.PngPath)) ready++;
            else if (result.Warning?.StartsWith("No archive DDS", StringComparison.OrdinalIgnoreCase) == true
                || result.Warning?.StartsWith("No inventory icon", StringComparison.OrdinalIgnoreCase) == true) missing++;
            else failed++;

            if (publishProgress is not null && ((index + 1) % 10 == 0 || index + 1 == items.Length))
            {
                await publishProgress(new ProgressUpdate(index + 1, items.Length, "item_icon_warmup", result.SourcePath)).ConfigureAwait(false);
            }
        }
        return new WarmItemIconsResult(request.SessionId, items.LongLength, ready, missing, failed);
    }

    private async Task<(ArchiveSession Session, ArchiveItemCatalog Catalog)> GetCatalogAsync(
        string sessionId,
        CancellationToken cancellationToken)
    {
        var session = sessions.GetRequired(sessionId);
        if (!session.TryGetItemCatalog(out var catalog) || catalog is null)
        {
            var built = await catalogueBuilder.BuildAsync(
                new BuildNameIndexRequest(sessionId),
                publishProgress: null,
                cancellationToken).ConfigureAwait(false);
            if (!built.Available || !session.TryGetItemCatalog(out catalog) || catalog is null)
            {
                throw new InvalidOperationException(built.Warning ?? "The Item Finder catalog is unavailable for this archive.");
            }
        }
        return (session, catalog);
    }

    private async Task<ItemIconResult> LoadOneSafeAsync(
        ArchiveSession session,
        ArchiveItemCatalog catalog,
        int itemId,
        int thumbnailSize,
        CancellationToken cancellationToken)
    {
        try
        {
            return await LoadOneAsync(session, catalog, itemId, thumbnailSize, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception exception)
        {
            var warning = BoundedMessage(exception.Message);
            _negativeCache[NegativeKey(session, itemId, thumbnailSize)] = new NegativeIconCacheEntry(
                DateTimeOffset.UtcNow.AddMinutes(2),
                warning);
            return new ItemIconResult(itemId, null, null, warning);
        }
    }

    private async Task<ItemIconResult> LoadOneAsync(
        ArchiveSession session,
        ArchiveItemCatalog catalog,
        int itemId,
        int thumbnailSize,
        CancellationToken cancellationToken)
    {
        if (!catalog.TryGet(itemId, out var item) || item is null)
        {
            return new ItemIconResult(itemId, null, null, "The item is not present in the active catalog.");
        }
        if (item.IconPaths.Count == 0)
        {
            return new ItemIconResult(itemId, null, null, "No inventory icon was recovered for this item.");
        }

        var gateKey = $"{session.Fingerprint}:{itemId}:{thumbnailSize}";
        var negativeKey = NegativeKey(session, itemId, thumbnailSize);
        if (_negativeCache.TryGetValue(negativeKey, out var negative))
        {
            if (negative.ExpiresUtc > DateTimeOffset.UtcNow)
            {
                return new ItemIconResult(itemId, null, null, negative.Warning);
            }
            _negativeCache.TryRemove(negativeKey, out _);
        }
        var gate = _itemGates.GetOrAdd(gateKey, static _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            foreach (var iconPath in item.IconPaths.Take(8))
            {
                cancellationToken.ThrowIfCancellationRequested();
                var iconEntry = ResolveIconEntry(session, iconPath);
                if (iconEntry is null || iconEntry.OriginalSize > MaximumIconBytes)
                {
                    continue;
                }
                if (textures.TryGetCachedThumbnail(session, iconEntry, thumbnailSize) is { } cached)
                {
                    _negativeCache.TryRemove(negativeKey, out _);
                    return new ItemIconResult(itemId, cached, iconEntry.Path);
                }

                var stagingRoot = Path.Combine(
                    ArchiveLiteDataPaths.PreviewCache,
                    "item-icon-staging",
                    $"{Environment.ProcessId}-{Guid.NewGuid():N}");
                Directory.CreateDirectory(stagingRoot);
                try
                {
                    var decoded = await Task.Run(() => native.Decode(iconEntry), cancellationToken).ConfigureAwait(false);
                    var ddsPath = Path.Combine(stagingRoot, "icon.dds");
                    await File.WriteAllBytesAsync(ddsPath, decoded.Bytes, cancellationToken).ConfigureAwait(false);
                    var pngPath = await textures.BuildThumbnailAsync(
                        session,
                        iconEntry,
                        ddsPath,
                        thumbnailSize,
                        cancellationToken).ConfigureAwait(false);
                    _negativeCache.TryRemove(negativeKey, out _);
                    return new ItemIconResult(itemId, pngPath, iconEntry.Path);
                }
                finally
                {
                    DeleteOwnedStaging(stagingRoot);
                }
            }
            const string warning = "No archive DDS could be resolved for the recovered inventory icon paths.";
            _negativeCache[negativeKey] = new NegativeIconCacheEntry(DateTimeOffset.UtcNow.AddMinutes(10), warning);
            return new ItemIconResult(itemId, null, null, warning);
        }
        finally
        {
            gate.Release();
        }
    }

    private static ArchiveEntryDto? ResolveIconEntry(ArchiveSession session, string iconPath)
    {
        var exact = session.Index.FindEntriesByPath(iconPath, 8)
            .FirstOrDefault(static entry => entry.Extension.Equals(".dds", StringComparison.OrdinalIgnoreCase));
        if (exact is not null)
        {
            return exact;
        }
        var basename = Path.GetFileName(iconPath.Replace('\\', '/'));
        if (string.IsNullOrWhiteSpace(basename))
        {
            return null;
        }
        var normalizedSuffix = iconPath.Replace('\\', '/').Trim('/');
        return session.BasenameIndex.FindEntriesByBasename(session.Index, basename, 32)
            .Where(static entry => entry.Extension.Equals(".dds", StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(entry => entry.Path.EndsWith(normalizedSuffix, StringComparison.OrdinalIgnoreCase))
            .ThenBy(static entry => entry.Path.Length)
            .FirstOrDefault();
    }

    private async Task WaitForVisibleRequestsAsync(CancellationToken cancellationToken)
    {
        while (Volatile.Read(ref _visibleRequestCount) > 0)
        {
            await Task.Delay(40, cancellationToken).ConfigureAwait(false);
        }
        if (workPriority is not null)
        {
            await workPriority.WaitForForegroundAsync(cancellationToken).ConfigureAwait(false);
        }
    }

    private static string NegativeKey(ArchiveSession session, int itemId, int thumbnailSize) =>
        $"{session.Fingerprint}:{itemId}:{thumbnailSize}";

    private static void ValidateThumbnailSize(int size)
    {
        if (size is < 48 or > 256)
        {
            throw new ArgumentOutOfRangeException(nameof(size), "Item Finder thumbnails must be between 48 and 256 pixels.");
        }
    }

    private static string BoundedMessage(string message) =>
        string.IsNullOrWhiteSpace(message)
            ? "The inventory icon could not be decoded."
            : message.Trim()[..Math.Min(message.Trim().Length, 512)];

    private static void DeleteOwnedStaging(string stagingRoot)
    {
        try
        {
            var ownedRoot = Path.GetFullPath(Path.Combine(ArchiveLiteDataPaths.PreviewCache, "item-icon-staging"))
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var resolved = Path.GetFullPath(stagingRoot);
            if (resolved.StartsWith(ownedRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                && Directory.Exists(resolved))
            {
                Directory.Delete(resolved, recursive: true);
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // Preview cache maintenance can remove a staging folder that is briefly locked.
        }
    }

    private sealed record NegativeIconCacheEntry(DateTimeOffset ExpiresUtc, string Warning);
}
