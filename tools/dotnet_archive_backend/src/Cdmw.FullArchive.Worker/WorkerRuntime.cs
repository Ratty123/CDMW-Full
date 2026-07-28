using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Worker;

internal sealed class WorkerRuntime : IAsyncDisposable
{
    private const int StreamBatchSize = 128;
    private readonly NativeArchiveCore _native = new();
    private readonly ArchiveCacheStore _cache;
    private readonly ArchiveSessionManager _sessions;
    private readonly ArchiveQueryService _queries;
    private readonly ArchiveLookupService _lookups;
    private readonly ArchiveNameIndexService _names;
    private readonly ArchiveItemCatalogBuildService _itemCatalogBuilder;
    private readonly ArchiveItemCatalogService _itemCatalog;
    private readonly ArchiveItemIconService _itemIcons;
    private readonly ArchiveItemCatalogScopeService _itemScopes;
    private readonly ArchiveEntryPreparationService _preparation;
    private readonly ArchiveTextSearchService _textSearch;
    private readonly ArchiveExportService _exports;
    private readonly CancellationTokenSource _backgroundCancellation = new();
    private readonly object _backgroundGate = new();
    private readonly HashSet<Task> _backgroundTasks = [];
    private readonly HashSet<string> _nameWarmupSessions = new(StringComparer.Ordinal);

    public WorkerRuntime(string cacheRoot)
    {
        _native.EnsureCompatible();
        _cache = new ArchiveCacheStore(cacheRoot);
        _sessions = new ArchiveSessionManager(_native, _cache);
        _queries = new ArchiveQueryService(_sessions);
        _lookups = new ArchiveLookupService(_sessions, _cache, _native);
        _names = new ArchiveNameIndexService(_sessions, _cache, _native);
        _preparation = new ArchiveEntryPreparationService(_sessions, _native);
        _itemCatalogBuilder = new ArchiveItemCatalogBuildService(_sessions, _native);
        _itemCatalog = new ArchiveItemCatalogService(_sessions, _itemCatalogBuilder);
        _itemIcons = new ArchiveItemIconService(_sessions, _itemCatalogBuilder, _preparation);
        _itemScopes = new ArchiveItemCatalogScopeService(_sessions, _itemCatalogBuilder, _lookups);
        _textSearch = new ArchiveTextSearchService(_sessions, _native);
        _exports = new ArchiveExportService(_sessions, _queries, _lookups, _native);
    }

    public async Task<WorkerMessage> HandleAsync(
        WorkerMessage request,
        Func<ProgressUpdate, Task> publishProgress,
        Func<object, Task> publishBatch,
        CancellationToken cancellationToken)
    {
        switch (request.Operation)
        {
            case WorkerProtocol.CacheHealth:
                {
                    var payload = RequirePayload<CacheHealthRequest>(request);
                    var result = await _cache.InspectAsync(
                        payload.PackageRoot,
                        cancellationToken,
                        publishProgress).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result);
                }
            case WorkerProtocol.OpenArchive:
            case WorkerProtocol.RefreshArchive:
                {
                    var payload = RequirePayload<OpenArchiveRequest>(request);
                    var result = request.Operation == WorkerProtocol.RefreshArchive
                        ? await _sessions.RefreshAsync(payload, cancellationToken, publishProgress).ConfigureAwait(false)
                        : await _sessions.OpenAsync(payload, cancellationToken, publishProgress).ConfigureAwait(false);
                    StartLookupWarmup(result.SessionId);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result, result.SessionId);
                }
            case WorkerProtocol.CloseArchive:
                {
                    var payload = RequirePayload<CloseArchiveRequest>(request);
                    var closed = _sessions.Close(payload.SessionId);
                    return WorkerProtocol.Response(
                        request,
                        WorkerMessageStatus.Result,
                        new CloseArchiveResult(payload.SessionId, closed),
                        payload.SessionId);
                }
            case WorkerProtocol.CreateQuery:
                {
                    var payload = RequirePayload<CreateQueryRequest>(request);
                    RequireSession(request, payload.Query.SessionId);
                    var query = payload.Query;
                    if (query.IncludeText?.StartsWith("name:", StringComparison.OrdinalIgnoreCase) == true)
                    {
                        var nameIndex = await _names.WarmAsync(
                            query.SessionId,
                            cancellationToken,
                            publishProgress).ConfigureAwait(false);
                        if (!nameIndex.IsAvailable)
                        {
                            throw new InvalidDataException(nameIndex.UnavailableReason);
                        }
                        query = query with { IncludeText = query.IncludeText[5..].Trim() };
                    }
                    var result = await _queries.CreateAsync(
                        query,
                        request.UiGeneration,
                        cancellationToken,
                        publishProgress).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result, result.SessionId);
                }
            case WorkerProtocol.FetchPage:
                {
                    var sessionId = RequireSession(request);
                    var result = _queries.FetchPage(sessionId, RequirePayload<FetchPageRequest>(request));
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result, sessionId);
                }
            case WorkerProtocol.FetchChildren:
                {
                    var sessionId = RequireSession(request);
                    var result = _queries.FetchChildren(
                        sessionId,
                        RequirePayload<ArchiveChildrenRequest>(request),
                        cancellationToken);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result, sessionId);
                }
            case WorkerProtocol.Facets:
                {
                    var sessionId = RequireSession(request);
                    var result = await _lookups.FacetsAsync(sessionId, cancellationToken, publishProgress).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result, sessionId);
                }
            case WorkerProtocol.ResolveEntries:
                {
                    var payload = RequirePayload<ArchiveLookupRequest>(request);
                    RequireSession(request, payload.SessionId);
                    var result = await _lookups.ResolveAsync(payload, cancellationToken, publishProgress).ConfigureAwait(false);
                    for (var start = 0; start < result.Entries.Count; start += StreamBatchSize)
                    {
                        var entries = result.Entries.Skip(start).Take(StreamBatchSize).ToArray();
                        var queryRows = result.QueryRows?.Skip(start).Take(entries.Length).ToArray() ?? [];
                        await publishBatch(new ArchiveLookupResult(
                            result.SessionId,
                            entries,
                            result.TotalMatches,
                            result.Truncated,
                            queryRows)).ConfigureAwait(false);
                    }
                    return WorkerProtocol.Response(
                        request,
                        WorkerMessageStatus.Result,
                        result with { Entries = [], QueryRows = [] },
                        result.SessionId);
                }
            case WorkerProtocol.FindAssociationCandidates:
                {
                    var payload = RequirePayload<ArchiveAssociationRequest>(request);
                    RequireSession(request, payload.SessionId);
                    // The name index only enriches display names on the candidates, and
                    // building it against a cold archive walks every entry -- seconds
                    // that landed on the first preview click of a freshly cached
                    // archive. Reading back an already published index is cheap, so
                    // only the cold build is deferred, and only for previews.
                    var namesWarm = _names.IsWarm(payload.SessionId);
                    if (!namesWarm)
                    {
                        if (payload.Purpose == ArchiveAssociationPurpose.Preview
                            && !_names.IsPublished(payload.SessionId))
                        {
                            StartNameWarmup(payload.SessionId);
                        }
                        else
                        {
                            await _names.WarmAsync(payload.SessionId, cancellationToken, publishProgress).ConfigureAwait(false);
                            namesWarm = true;
                        }
                    }
                    var result = await _lookups.FindAssociationCandidatesAsync(
                        payload,
                        cancellationToken,
                        publishProgress).ConfigureAwait(false);
                    result = result with { SecondaryIndexPending = result.SecondaryIndexPending || !namesWarm };
                    foreach (var entries in result.Candidates.Chunk(StreamBatchSize))
                    {
                        await publishBatch(new ArchiveAssociationResult(
                            result.SessionId,
                            result.EntryId,
                            entries,
                            result.TotalCandidates,
                            result.Truncated,
                            result.SecondaryIndexPending)).ConfigureAwait(false);
                    }
                    return WorkerProtocol.Response(
                        request,
                        WorkerMessageStatus.Result,
                        result with { Candidates = [] },
                        result.SessionId);
                }
            case WorkerProtocol.BuildNameIndex:
                {
                    var payload = RequirePayload<BuildNameIndexRequest>(request);
                    RequireSession(request, payload.SessionId);
                    var result = await _itemCatalogBuilder.BuildAsync(
                        payload,
                        publishProgress,
                        cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result, payload.SessionId);
                }
            case WorkerProtocol.SearchItemCatalog:
                {
                    var payload = RequirePayload<ItemCatalogSearchRequest>(request);
                    RequireSession(request, payload.SessionId);
                    var result = await _itemCatalog.SearchAsync(
                        payload,
                        publishProgress,
                        cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result, payload.SessionId);
                }
            case WorkerProtocol.LoadItemIcons:
                {
                    var payload = RequirePayload<ItemIconBatchRequest>(request);
                    RequireSession(request, payload.SessionId);
                    var result = await _itemIcons.LoadAsync(payload, cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result, payload.SessionId);
                }
            case WorkerProtocol.ScopeItemCatalog:
                {
                    var payload = RequirePayload<ItemCatalogScopeRequest>(request);
                    RequireSession(request, payload.SessionId);
                    var result = await _itemScopes.ResolveAsync(
                        payload,
                        publishProgress,
                        cancellationToken).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result, payload.SessionId);
                }
            case WorkerProtocol.PrepareEntry:
                {
                    if (request.Payload is { } rawPayload &&
                        rawPayload.TryGetProperty("entry_ids", out _))
                    {
                        var batchPayload = RequirePayload<PrepareEntriesRequest>(request);
                        RequireSession(request, batchPayload.SessionId);
                        var batchResult = await _preparation.PrepareManyAsync(
                            batchPayload,
                            cancellationToken,
                            publishProgress).ConfigureAwait(false);
                        foreach (var items in batchResult.Items.Chunk(StreamBatchSize))
                        {
                            await publishBatch(batchResult with { Items = items }).ConfigureAwait(false);
                        }
                        return WorkerProtocol.Response(
                            request,
                            WorkerMessageStatus.Result,
                            batchResult with { Items = [] },
                            batchPayload.SessionId);
                    }
                    var payload = RequirePayload<PrepareEntryRequest>(request);
                    RequireSession(request, payload.SessionId);
                    var result = await _preparation.PrepareAsync(
                        payload,
                        cancellationToken,
                        publishProgress).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result, payload.SessionId);
                }
            case WorkerProtocol.TextSearch:
                {
                    var payload = RequirePayload<ArchiveTextSearchRequest>(request);
                    RequireSession(request, payload.SessionId);
                    var result = await _textSearch.SearchAsync(
                        payload,
                        publishBatch,
                        cancellationToken,
                        publishProgress).ConfigureAwait(false);
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result with { Matches = [] }, payload.SessionId);
                }
            case WorkerProtocol.Export:
                {
                    var payload = RequirePayload<ArchiveExportRequest>(request);
                    RequireSession(request, payload.SessionId);
                    var result = await _exports.ExportAsync(
                        payload,
                        cancellationToken,
                        publishProgress).ConfigureAwait(false);
                    foreach (var items in result.Items.Chunk(StreamBatchSize))
                    {
                        await publishBatch(result with { Items = items }).ConfigureAwait(false);
                    }
                    return WorkerProtocol.Response(request, WorkerMessageStatus.Result, result with { Items = [] }, payload.SessionId);
                }
            default:
                return WorkerProtocol.Failure(request, "unsupported_operation", $"Unsupported worker operation '{request.Operation}'.");
        }
    }

    public async ValueTask DisposeAsync()
    {
        _backgroundCancellation.Cancel();
        Task[] tasks;
        lock (_backgroundGate)
        {
            tasks = _backgroundTasks.ToArray();
        }
        if (tasks.Length > 0)
        {
            try
            {
                await Task.WhenAll(tasks).ConfigureAwait(false);
            }
            catch
            {
                // Background lookup failures are observed here; foreground requests rebuild on demand.
            }
        }
        _sessions.Dispose();
        _backgroundCancellation.Dispose();
    }

    private void StartLookupWarmup(string sessionId) =>
        TrackBackground(_lookups.WarmAsync(sessionId, _backgroundCancellation.Token));

    /// <summary>
    /// Starts the name-index build at most once per session, so a run of preview
    /// clicks through the cold window does not queue a warmup each time.
    /// </summary>
    private void StartNameWarmup(string sessionId)
    {
        lock (_backgroundGate)
        {
            if (!_nameWarmupSessions.Add(sessionId))
            {
                return;
            }
        }
        TrackBackground(_names.WarmAsync(sessionId, _backgroundCancellation.Token));
    }

    private void TrackBackground(Task task)
    {
        lock (_backgroundGate)
        {
            _backgroundTasks.Add(task);
        }
        _ = task.ContinueWith(
            completed =>
            {
                _ = completed.Exception;
                lock (_backgroundGate)
                {
                    _backgroundTasks.Remove(completed);
                }
            },
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }

    private static string RequireSession(WorkerMessage request, string? payloadSessionId = null)
    {
        var sessionId = request.SessionId;
        if (string.IsNullOrWhiteSpace(sessionId))
        {
            throw new InvalidDataException($"Worker operation '{request.Operation}' requires a session id.");
        }
        if (payloadSessionId is not null && !sessionId.Equals(payloadSessionId, StringComparison.Ordinal))
        {
            throw new InvalidDataException("Worker envelope and payload session ids do not match.");
        }
        return sessionId;
    }

    private static T RequirePayload<T>(WorkerMessage request) =>
        WorkerProtocol.ReadPayload<T>(request)
            ?? throw new InvalidDataException($"Worker request '{request.Operation}' has no valid payload.");
}
